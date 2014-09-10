import os
import re
import uuid
import math
import json
import yaml
import arrow
import urllib
import socket
import random
import logging
import operator
import requests
import feedparser

from xml.etree import ElementTree
from collections import deque, Counter
from datetime import timedelta
from .item import Item
from . import __version__
from .index import Index
from .utils import (seconds_in_timedelta, format_timestamp, seconds_until, seconds_since)

logger = logging.getLogger(__name__)

download_exceptions = (requests.exceptions.RequestException, socket.error)

class Feed(object):
    # check feeds no more/at least this often (in seconds)
    min_update_interval = 15*60
    max_update_interval = 60*60

    # update interval when interval can't otherwise be determined
    default_update_interval = 60*60

    # these updates are for the index
    updates = deque(maxlen=500)

    # number of timestamps to use for update interval
    window = 10

    # max number of items to store on first check
    initial_limit = 5

    # use this as timestamp during initial check
    started = arrow.utcnow()

    # this is true once all the initial checks are done
    running = False

    def __init__(self, url, title=None, factor=1.0):
        self.url = url
        self.title = title
        self.factor = factor
        self.last_checked = None
        self.headers = {}
        self.failed = False
        self.timestamps = []
        self.random_interval = self.generate_random_interval()
        self.fingerprints = deque(maxlen=1000)
        self.initial_check = True
        self.has_timestamps = False
        self.check_count = 0
        self.item_count = 0

    def __repr__(self):
        return '<Feed: %s>' % self.url

    def __eq__(self, other):
        return self.url == other.url

    def __ne__(self, other):
        return self.url != other.url

    def __iter__(self):
        self.parsed = self.parse()
        self.current = 0
        return self

    def __hash__(self):
        return hash(self.url)

    def next(self):
        if self.parsed is None:
            raise StopIteration
        try:
            item = Item(self.parsed.entries[self.current])
        except IndexError:
            raise StopIteration
        else:
            if not self.has_timestamps and item.timestamp_provided:
                self.has_timestamps = True
            self.current += 1
            return item

    def item_interval(self):
        """
        Return the average number of seconds between feed items.
        """
        if self.failed or not self.has_timestamps:
            return self.default_update_interval

        timestamps = sorted(self.timestamps, reverse=True)[:self.window]
        delta = timedelta()
        active = timestamps.pop(0)
        for timestamp in timestamps:
            delta += (active - timestamp)
            active = timestamp
        interval = delta / (len(timestamps) + 1)

        seconds = seconds_in_timedelta(interval)
        return seconds if seconds > 0 else self.default_update_interval

    def update_interval(self):
        """
        Return how many seconds to wait before checking this feed again.
        """
        seconds = self.item_interval()

        if seconds < self.min_update_interval:
            return timedelta(seconds=self.min_update_interval)
        elif seconds > self.max_update_interval:
            return timedelta(seconds=self.random_interval)
        else:
            return timedelta(seconds=seconds)

    def generate_random_interval(self, minimum=None):
        """
        Generate a random update interval. This is used when otherwise the
        update interval would be beyond self.max_update_interval.

        If `minimum` is provided, it is used as the lower bound for
        random.randint.

        If `minimum` is not provided, the lower bound is either
        self.min_update_interval or one-half self.max_update_interval
        (whichever is higher).

        The upper bound is self.max_update_interval.

        If the lower bound is greater than the higher bound,
        self.max_update_interval is used.

        The idea behind using a random update interval is without it
        all feeds with an item interval beyond
        self.max_update_interval would update at the same time (i.e.,
        time when feed was first parsed + the max update interval).

        By randomizing the interval, checks are nicely spaced out.
        """
        try:
            default_minimum = max(
                self.min_update_interval,
                int(self.max_update_interval / 2),
            )
            return random.randint(
                minimum or default_minimum,
                int(self.max_update_interval),
            )
        except ValueError:
            return int(self.max_update_interval)

    @property
    def next_check(self):
        """
        Return when this feed is due for a check.

        Returns a date far in the past (1/1/1970) if this feed hasn't
        been checked before. This ensures all feeds are checked upon
        startup.
        """
        if self.last_checked is None:
            return arrow.Arrow(1970, 1, 1)
        return self.last_checked + self.update_interval()

    def process_feed(self):
        """
        Return a list of new feed items.

        For feeds without provided timestamps, the top-most entry is
        the most recent. Otherwise, entries are sorted by their
        timestamp descending.
        """
        all_items = list(self)
        new_items = filter(lambda item: item.fingerprint not in self.fingerprints, all_items)

        self.fingerprints.extendleft(reversed([item.fingerprint for item in new_items]))
        logger.debug('Tracking %d fingerprints' % len(self.fingerprints))
        self.last_checked = arrow.utcnow()
        self.check_count += 1

        if self.has_timestamps:
            return sorted(new_items, key=operator.attrgetter('timestamp'), reverse=True)
        else:
            return list(reversed(new_items))

    def update_timestamps(self, items):
        """
        Update self.timestamps with the timestamps from items.

        If items is empty, add a "virtual timestamp" which has the
        effect of extending the update interval in the hopes that with
        a longer interval between feed checks, during the next check
        there will be new items.

        See <http://goo.gl/X6QhWN> ("3.3 Moving Average") for a more
        in-depth explanation of how this works.
        """
        if self.timestamps:
            logger.debug('Old delay: %d seconds' % seconds_in_timedelta(self.update_interval()))
            logger.debug('Old latest timestamp: %s' % format_timestamp(self.timestamps[0], web=False))

        timestamps = [item.timestamp for item in items if item.timestamp is not None]

        if timestamps:
            self.timestamps.extend(timestamps)

            # Reset here otherwise self.random_interval would only
            # ever keep incrementing closer and closer to
            # self.max_update_interval.
            self.random_interval = self.generate_random_interval()

        elif not timestamps and not self.failed:
            if self.item_interval() < self.max_update_interval:
                current_update_interval = self.update_interval()
                self.timestamps.insert(0, arrow.utcnow())
                if self.update_interval() < current_update_interval:
                    logger.debug('Skipping virtual timestamp as it would shorten the update interval')
                    self.timestamps.pop(0)

            elif self.item_interval() > self.max_update_interval:
                self.random_interval = self.generate_random_interval(minimum=self.random_interval + 1)

        self.timestamps = sorted(self.timestamps, reverse=True)[:self.window]

        logger.debug('Item interval: %d seconds' % self.item_interval())

        if self.timestamps:
            logger.debug('New latest timestamp: %s' % format_timestamp(self.timestamps[0], web=False))
            logger.debug('New delay: %d seconds' % seconds_in_timedelta(self.update_interval()))

    def display_next_check(self):
        logger.debug('Next check: %s (%s)' % (
            format_timestamp(self.next_check, web=False), seconds_until(self.next_check, readable=True)
        ))

    def build_update(self, new_items):
        update = {
            'timestamp': str(arrow.utcnow() if self.running else self.started),
            'uuid': str(uuid.uuid4()),
            'factor': self.factor,
            'feed': {
                'title': self.title or self.parsed.feed.get('title', ''),
                'description': self.parsed.feed.get('description', ''),
                'web_url': self.parsed.feed.get('link', ''),
                'feed_url': self.url,
            },
        }

        if self.initial_check:
            new_items = new_items[:self.initial_limit]
            update['initial_check'] = True

        self.item_count += len(new_items)

        update['feed_items'] = [item.info for item in new_items]

        return update

    def check(self, output):
        """
        Update this feed with new items and timestamps.
        """
        new_items = self.process_feed()

        if self.failed:
            self.display_next_check()
            return None

        if new_items:
            logger.info('Found %d new item(s)' % len(new_items))
            if not self.initial_check:
                for item in new_items:
                    logger.debug('New item: %r' % item.fingerprint)
        else:
            logger.info('No new items')

        self.update_timestamps(new_items)

        if new_items:
            update = self.build_update(new_items)
            self.write_update(update, output)

        self.initial_check = False

        logger.debug('Checked %d time(s)' % self.check_count)
        logger.debug('Processed %d total item(s)' % self.item_count)

        self.display_next_check()

    @staticmethod
    def json_path(output):
        """
        Return the location of the archive JSON file.
        """
        p = os.path.join(output, 'json', '%s.json' % arrow.now().format('YYYY-MM-DD'))
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        return p

    def write_update(self, update, output):
        json_path = self.json_path(output)

        try:
            with open(json_path) as fp:
                updates = json.load(fp)
        except (IOError, ValueError):
            updates = []

        updates.insert(0, update)

        logger.debug('Writing update %s' % update['uuid'])

        with open(json_path, 'wb') as fp:
            json.dump(updates, fp, indent=2, sort_keys=True)

        self.updates.appendleft(update)

        index = Index(output)
        index.write_archive(json_path)
        index.write_index(self.updates)

    def parse(self):
        """
        Return the feed's content as parsed by feedparser.

        If there was an error downloading the feed, return None.
        """
        try:
            content = self.download()
        except download_exceptions:
            return None
        else:
            return feedparser.parse(content)
            
    def download(self):
        """
        Return the raw feed body.

        Sends a conditional GET request to save some bandwidth.
        """
        headers = {}
        if self.headers.get('last-modified'):
            headers['If-Modified-Since'] = self.headers.get('last-modified')
        if self.headers.get('etag'):
            headers['If-None-Match'] = self.headers.get('etag')

        if headers:
            logger.debug('Including headers: %r' % headers)

        headers.update({
            'User-Agent': 'river/%s (https://github.com/edavis/river)' % __version__,
            'From': 'eric@davising.com',
        })

        try:
            response = requests.get(self.url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
        except download_exceptions:
            logger.exception('Failed to download %s' % self.url)
            self.failed = True
            raise
        else:
            self.failed = False

        logger.debug('Status code: %d' % response.status_code)

        self.headers.update(response.headers)

        if response.status_code != 304:
            logger.debug('Last-Modified: %s' % self.headers.get('last-modified'))
            logger.debug('ETag: %s' % self.headers.get('etag'))

        if response.status_code == 200:
            self.payload = response.text
            return response.text
        else:
            return self.payload

    @property
    def payload(self):
        with open(self.cache_path()) as fp:
            return fp.read().decode('utf-8')

    @payload.setter
    def payload(self, body):
        with open(self.cache_path(), 'w') as fp:
            fp.write(body.encode('utf-8'))

    def cache_path(self):
        cache_root = os.path.expanduser('~/.river/cache/')

        if not os.path.isdir(cache_root):
            os.makedirs(cache_root)

        return os.path.join(cache_root, urllib.quote(self.url, safe=''))

class FeedList(object):
    logger = logging.getLogger(__name__ + '.list')

    def __init__(self, feed_list):
        self.feed_list = feed_list
        self.feeds = self.parse(feed_list)
        self.last_checked = arrow.utcnow()
        random.shuffle(self.feeds)

    def parse(self, path):
        """
        Return a list of Feed objects from the feed list.
        """
        if re.search('^https?://', path):
            while True:
                try:
                    response = requests.get(path, timeout=15, verify=False)
                    response.raise_for_status()
                except download_exceptions:
                    self.logger.exception('Failed to download feed list, trying again in 60 seconds')
                    time.sleep(60)
                else:
                    content = response.content
                    break
        else:
            with open(path) as fp:
                content = fp.read()

        if path.endswith(('.opml', '.xml')):
            doc = self.parse_opml(content)
        else:
            doc = self.parse_yaml(content)

        self.last_checked = arrow.utcnow()

        feeds = []
        feed_counter = Counter()

        for obj in doc:
            feed = Feed(**obj)

            feed_counter.update([feed.url])
            if feed_counter[feed.url] > 1:
                self.logger.warning('%s found multiple times, only using the first' % feed.url)
                continue

            feeds.append(feed)
            self.refresh_feed(feed, obj)

        return feeds

    def parse_opml(self, content):
        parsed = ElementTree.fromstring(content)
        for outline in parsed.iter('outline'):
            if outline.get('type') == 'rss' and outline.get('xmlUrl'):
                yield {
                    'url': outline.get('xmlUrl'),
                    'title': outline.get('title') or outline.get('text'),
                    'factor': float(outline.get('factor', 1.0)),
                }

    def parse_yaml(self, content):
        parsed = yaml.load(content)
        for obj in parsed:
            if isinstance(obj, str):
                yield {'url': obj}

            elif isinstance(obj, dict):
                yield {
                    'url': obj['url'],
                    'title': obj.get('title'),
                    'factor': float(obj.get('factor', 1.0)),
                }

    def refresh_feed(self, f, info):
        """
        Catch updates to a feed's title and/or factor.

        This works by searching self.feeds for the given Feed object
        and setting the title and factor attribute based on what was
        passed.
        """
        try:
            idx = self.feeds.index(f)
            feed = self.feeds[idx]
        except (AttributeError, ValueError):
            pass
        else:
            feed.title = info.get('title')
            feed.factor = float(info.get('factor', 1.0))

    def active(self):
        """
        Return the next feed to be checked.
        """
        assert self.feeds, 'no feeds to check!'
        self.feeds = sorted(self.feeds, key=operator.attrgetter('next_check'))
        return self.feeds[0]

    def update(self):
        """
        Re-parse the feed list and add/remove feeds as necessary.
        """
        self.logger.debug('Refreshing feed list')
        updated = self.parse(self.feed_list)
        
        new_feeds = filter(lambda feed: feed not in self.feeds, updated)
        if new_feeds:
            for feed in new_feeds:
                self.logger.debug('Adding %s' % feed.url)
            self.feeds.extend(new_feeds)

        removed_feeds = filter(lambda feed: feed not in updated, self.feeds)
        if removed_feeds:
            for feed in removed_feeds:
                self.logger.debug('Removing %s' % feed.url)
                self.feeds.remove(feed)

        if not new_feeds and not removed_feeds:
            self.logger.debug('No updates to feed list')

    def need_update(self, interval):
        """
        Return True if the feed list is due for a check.
        """
        if seconds_since(self.last_checked) >= interval:
            return True

        next_check = self.last_checked + timedelta(seconds=interval)
        self.logger.debug('Next feed list check in %s' % seconds_until(next_check, readable=True))

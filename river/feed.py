import os
import re
import uuid
import math
import json
import yaml
import arrow
import urllib
import random
import logging
import operator
import requests
import feedparser
from datetime import timedelta
from .item import Item

from .utils import (seconds_in_timedelta, format_timestamp, seconds_until,
                    seconds_since, display_timestamp)

logger = logging.getLogger(__name__)

class Feed(object):
    min_update_interval = 15*60 # 15 minutes
    max_update_interval = 2*60*60 # 2 hours

    # number of timestamps to use for update interval
    window = 10

    # max number of items to store on first check
    initial_limit = 5

    def __init__(self, url):
        self.url = url
        self.last_checked = None
        self.headers = {}
        self.failed = False
        self.timestamps = []
        self.random_interval = self.generate_random_interval()
        self.fingerprints = set()
        self.initial_check = True
        self.previous_timestamp = None
        self.has_timestamps = False
        self.started = arrow.utcnow()
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
        Return the average number of seconds between feed items going back
        self.window number of items.
        """
        if self.failed or not self.has_timestamps:
            return 60*60

        timestamps = sorted(self.timestamps, reverse=True)[:self.window]
        delta = timedelta()
        active = timestamps.pop(0)
        for timestamp in timestamps:
            delta += (active - timestamp)
            active = timestamp
        interval = delta / (len(timestamps) + 1)

        seconds = seconds_in_timedelta(interval)
        return seconds if seconds > 0 else 60*60

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
        Generate a random interger between minimum and
        self.max_update_interval.

        If minimum is not provided, use half of
        self.max_update_interval.

        This value is used when setting the update interval for feeds
        with an item interval beyond max_update_interval.

        Instead of having all the feeds beyond max_update_interval
        refreshed at the same time, start the checks at (now + half of
        max_update_interval) and have them continue until (now +
        max_update_interval).
        """
        try:
            return random.randint(
                minimum if minimum is not None else int(self.max_update_interval / 2.0),
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
        new_items = sorted([item for item in all_items if item.fingerprint not in self.fingerprints],
                           key=operator.attrgetter('timestamp'), reverse=True)

        self.last_checked = arrow.utcnow()
        self.check_count += 1
        self.fingerprints = set([item.fingerprint for item in all_items])

        return new_items if self.has_timestamps else list(reversed(new_items))

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
            logger.debug('Old latest timestamp: %r' % self.timestamps[0])

        timestamps = [item.timestamp for item in items if item.timestamp is not None]

        if timestamps:
            self.timestamps.extend(timestamps)

            # Reset here otherwise self.random_interval would only
            # ever keep incrementing closer and closer to
            # self.max_update_interval.
            self.random_interval = self.generate_random_interval()

        elif not timestamps and not self.failed:
            current_update_interval = self.update_interval()

            if self.item_interval() < self.max_update_interval:
                self.timestamps.insert(0, arrow.utcnow())
                if self.update_interval() < current_update_interval:
                    logger.debug('Skipping virtual timestamp as it would shorten the update interval')
                    self.timestamps.pop(0)

            elif self.item_interval() > self.max_update_interval:
                self.random_interval = self.generate_random_interval(minimum=self.random_interval + 1)

        self.timestamps = sorted(self.timestamps, reverse=True)[:self.window]

        logger.debug('Item interval: %d seconds' % self.item_interval())

        if self.timestamps:
            logger.debug('New latest timestamp: %r' % self.timestamps[0])
            logger.debug('New delay: %d seconds' % seconds_in_timedelta(self.update_interval()))

    def display_next_check(self):
        logger.debug('Next check: %s (%s)' % (
            format_timestamp(self.next_check), seconds_until(self.next_check, readable=True)
        ))

    def build_update(self, new_items):
        timestamp = arrow.utcnow()
        update = {
            'timestamp': str(timestamp),
            'item_interval': self.item_interval(),
            'uuid': str(uuid.uuid4()),
            'feed': {
                'title': self.parsed.feed.get('title', ''),
                'description': self.parsed.feed.get('description', ''),
                'web_url': self.parsed.feed.get('link', ''),
                'feed_url': self.url,
            },
        }

        if self.previous_timestamp is not None:
            update['previous_timestamp'] = str(self.previous_timestamp)

        if self.initial_check:
            new_items = new_items[:self.initial_limit]
            update['initial_check'] = True

        self.item_count += len(new_items)

        update['item_count'] = self.item_count
        update['feed_items'] = [item.info for item in new_items]

        self.previous_timestamp = timestamp

        return update

    def check(self, output, skip_initial):
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

        if new_items and (not self.initial_check if skip_initial else True):
            update = self.build_update(new_items)
            self.write_update(update, output)

        self.initial_check = False

        logger.debug('Checked %d time(s)' % self.check_count)
        logger.debug('Processed %d total item(s)' % self.item_count)

        self.display_next_check()

    def write_update(self, update, output):
        json_path = os.path.join(output, '%s.json' % arrow.now().format('YYYY-MM-DD'))

        try:
            with open(json_path) as fp:
                updates = json.load(fp)
        except (IOError, ValueError):
            updates = []

        updates.insert(0, update)

        with open(json_path, 'wb') as fp:
            json.dump(updates, fp, indent=2, sort_keys=True)

    def parse(self):
        """
        Return the feed's content as parsed by feedparser.

        If there was an error downloading the feed, return None.
        """
        try:
            content = self.download()
        except requests.exceptions.RequestException:
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

        try:
            if headers:
                logger.debug('Including headers: %r' % headers)

            headers.update({
                'User-Agent': 'river/0.1 (https://github.com/edavis/river)',
                'From': 'eric@davising.com',
            })

            response = requests.get(self.url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
        except requests.exceptions.RequestException:
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
    def __init__(self, feed_list):
        self.feed_list = feed_list
        self.feeds = self.parse(feed_list)
        self.last_checked = arrow.utcnow()
        self.logger = logging.getLogger(__name__ + '.list')

        random.shuffle(self.feeds)

    def parse(self, path):
        """
        Return a list of Feed objects from the feed list.
        """
        if re.search('^https?://', path):
            response = requests.get(path)
            response.raise_for_status()
            doc = yaml.load(response.text)
        else:
            doc = yaml.load(open(path))

        self.last_checked = arrow.utcnow()

        return list(
            set([Feed(url) for url in doc])
        )

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
        return seconds_since(self.last_checked) > interval

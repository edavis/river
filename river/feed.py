import os
import re
import math
import json
import yaml
import arrow
import jinja2
import random
import logging
import operator
import requests
import feedparser
from datetime import timedelta
from .item import Item

from .utils import (seconds_in_timedelta, format_timestamp, seconds_until,
                    seconds_since, open_updates, write_updates, mkdir_p,
                    display_timestamp)

html_environment = jinja2.Environment(
    loader = jinja2.PackageLoader('river'),
)
html_environment.filters['display_timestamp'] = display_timestamp

logger = logging.getLogger(__name__)

class Update(object):
    """
    Represents one or more new items in a feed.
    """
    decay = -1

    def __init__(self, feed, items):
        self.created = arrow.utcnow()
        self.interval = feed.item_interval()
        self.feed = feed

        self.obj = {
            'timestamp': str(self.created),
            'feed': {
                'title': feed.parsed.feed.get('title', ''),
                'description': feed.parsed.feed.get('description', ''),
                'web_url': feed.parsed.feed.get('link', ''),
                'feed_url': feed.url,
            },
            'feed_items': [],
        }

        if feed.initial_check:
            items = items[:feed.initial_limit]

        for item in items:
            self.obj['feed_items'].append(item.info)

    @property
    def score(self):
        # http://www.evanmiller.org/rank-hotness-with-newtons-law-of-cooling.html
        hours_elapsed = seconds_in_timedelta(arrow.utcnow() - self.created) / (60.0**2)
        return math.log10(self.interval) * math.exp(self.decay * hours_elapsed)

class Feed(object):
    min_update_interval = 60
    max_update_interval = 60*60

    # number of timestamps to use for update interval
    window = 10

    # feed URLs that couldn't be downloaded
    failed_urls = set()

    # number of items to keep in items/timestamps
    history_limit = 1000

    # max number of items to store on first check
    initial_limit = 5

    updates = set()

    def __init__(self, url):
        self.url = url
        self.last_checked = None
        self.headers = {}
        self.payload = None
        self.timestamps = []
        self.items = set()
        self.initial_check = True
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

    @property
    def failed_download(self):
        return self.url in self.failed_urls

    def item_interval(self):
        """
        Return the average number of seconds between the last self.window
        new items.
        """
        timestamps = sorted(self.timestamps, reverse=True)[:self.window]
        delta = timedelta()
        active = timestamps.pop(0)
        for timestamp in timestamps:
            delta += (active - timestamp)
            active = timestamp
        interval = delta / (len(timestamps) + 1)
        return seconds_in_timedelta(interval)

    def update_interval(self):
        """
        Return how many seconds to wait before checking this feed again.

        Value is determined by adding the number of seconds between
        new items divided by the window size (specified in self.window).

        If raw=True, return the raw number of seconds (not a
        timedelta) and don't bound between the min/max update
        interval.
        """
        if self.failed_download or not self.has_timestamps:
            return timedelta(seconds=self.max_update_interval)

        seconds = self.item_interval()

        if seconds < self.min_update_interval:
            return timedelta(seconds=self.min_update_interval)
        elif seconds > self.max_update_interval:
            return timedelta(seconds=self.max_update_interval)
        else:
            return timedelta(seconds=seconds)

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
        new = sorted([item for item in self if item not in self.items],
                     key=operator.attrgetter('timestamp'), reverse=True)

        self.last_checked = arrow.utcnow()
        self.check_count += 1

        if self.has_timestamps:
            return new
        else:
            return list(reversed(new))

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

        elif not timestamps and not self.failed_download:
            old_update_interval = self.update_interval()
            self.timestamps.insert(0, arrow.utcnow())
            if self.update_interval() < old_update_interval:
                logger.debug('Skipping virtual timestamp as it would shorten the update interval')
                self.timestamps.pop(0)

        self.timestamps = sorted(self.timestamps, reverse=True)

        if self.timestamps:
            logger.debug('New latest timestamp: %r' % self.timestamps[0])
            logger.debug('New delay: %d seconds' % seconds_in_timedelta(self.update_interval()))

        del self.timestamps[self.history_limit:]

    def display_next_check(self):
        logger.debug('Next check: %s (%s)' % (
            format_timestamp(self.next_check), seconds_until(self.next_check, readable=True)
        ))

    def check(self, output, skip_initial):
        """
        Update this feed with new items and timestamps.
        """
        new_items = self.process_feed()

        if self.failed_download:
            self.display_next_check()
            return None

        if new_items:
            logger.info('Found %d new item(s)' % len(new_items))
            if not self.initial_check:
                for item in new_items:
                    logger.debug('New item: %r' % item.fingerprint)
            self.items.update(new_items)
            self.item_count += len(new_items)
        else:
            logger.info('No new items')

        self.update_timestamps(new_items)

        if len(self.items) > self.history_limit:
            items = sorted(self.items, key=operator.attrgetter('timestamp'), reverse=True)
            del items[self.history_limit:]
            self.items = set(items)

        if new_items and (not self.initial_check if skip_initial else True):
            update = Update(self, new_items)
            self.updates.add(update)
            self.write_updates(output)

        self.initial_check = False

        logger.debug('Checked %d time(s)' % self.check_count)
        logger.debug('Processed %d total item(s)' % self.item_count)

        self.display_next_check()

    def write_updates(self, output):
        updates = []
        for update in sorted(self.updates, key=operator.attrgetter('score'), reverse=True):
            update.obj.update({
                'score': str(update.score),
                'age': seconds_in_timedelta(arrow.utcnow() - update.created),
                'interval': update.interval,
            })
            updates.append(update.obj)
            if update.created.to('local').date() < arrow.now().date():
                self.updates.discard(update)

        logger.debug('Tracking %d update(s)' % len(self.updates))

        # Write the JSON
        json_fname = 'json/%s.json' % arrow.now().format('YYYY-MM-DD')
        archive_path = os.path.join(output, json_fname)
        mkdir_p(archive_path)
        with open(archive_path, 'wb') as fp:
            json.dump(updates, fp, indent=2, sort_keys=True)

        # Write the HTML
        html_archive_fname = '%s/index.html' % arrow.now().format('YYYY/MM/DD')
        html_index_fname = 'index.html'

        html_template = html_environment.get_template('index.html')
        html_body = html_template.render(updates=updates).encode('utf-8')

        for fname in [html_archive_fname, html_index_fname]:
            html_path = os.path.join(output, fname)
            mkdir_p(html_path)
            with open(html_path, 'wb') as html_fp:
                html_fp.write(html_body)

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
            self.failed_urls.add(self.url)
            raise
        else:
            self.failed_urls.discard(self.url)

        logger.debug('Status code: %d' % response.status_code)

        self.headers.update(response.headers)

        if response.status_code != 304:
            logger.debug('Last-Modified: %s' % self.headers.get('last-modified'))
            logger.debug('ETag: %s' % self.headers.get('etag'))

        if response.status_code == 200:
            self.payload = response.text

        assert self.payload, 'empty payload!'
        return self.payload

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

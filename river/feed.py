import os
import re
import json
import yaml
import arrow
import random
import logging
import operator
import requests
import feedparser
from datetime import timedelta
from .utils import seconds_in_timedelta, format_timestamp, seconds_until, seconds_since
from .item import Item

logger = logging.getLogger(__name__)

class Feed(object):
    min_update_interval = 60    # minimum number of seconds between feed checks
    max_update_interval = 60*60 # maximum number of seconds between feed checks
    failed_urls = set()         # feed URLs that couldn't be downloaded
    history_limit = 1000        # number of items to keep in items/timestamps
    initial_limit = 5           # max number of items to store on first check
    window = 10                 # number of timestamps to use for update interval

    def __init__(self, args, url):
        self.args = args
        self.url = url
        self.last_checked = None  # time of last feed check
        self.check_count = 0      # number of times the feed has been checked
        self.headers = {}         # response headers (updated each request)
        self.payload = None       # raw feed body
        self.timestamps = []      # timestamps used for update_interval
        self.items = set()        # previously seen items
        self.initial_check = True # whether this is the first check

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
            self.current += 1
            return item

    def update_interval(self):
        """
        Return how many seconds to wait before checking this feed again.

        Value is determined by adding the number of seconds between
        new items divided by the window size (specified in self.window).
        """
        if self.url in self.failed_urls:
            return timedelta(seconds=60*60)

        timestamps = sorted(self.timestamps, reverse=True)[:self.window]
        delta = timedelta()
        active = timestamps.pop(0)
        for timestamp in timestamps:
            delta += (active - timestamp)
            active = timestamp
        
        interval = delta / (len(timestamps) + 1) # '+ 1' to account for the pop
        seconds = seconds_in_timedelta(interval)

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

    def check(self):
        """
        Update this feed with new items and timestamps.
        """
        new_items = sorted([item for item in self if item not in self.items],
                           key=operator.attrgetter('timestamp'), reverse=True)
        new_timestamps = 0

        self.last_checked = arrow.utcnow()
        self.check_count += 1

        if self.url in self.failed_urls:
            logger.debug('Next check: %s (%s)' % (
                format_timestamp(self.next_check), seconds_until(self.next_check, readable=True)
            ))
            return

        if new_items:
            logger.info('Found %d new item(s)' % len(new_items))
            if not self.initial_check:
                for item in new_items:
                    logger.debug('New item: %r' % item.fingerprint)
            self.items.update(new_items)
        else:
            logger.info('No new items')

        if self.timestamps:
            logger.debug('Old delay: %d seconds' % seconds_in_timedelta(self.update_interval()))
            logger.debug('Old latest timestamp: %r' % self.timestamps[0])

        for item in reversed(new_items):
            if item.timestamp is not None:
                # Skip bogus timestamps
                self.timestamps.insert(0, item.timestamp)
                new_timestamps += 1

        if self.url not in self.failed_urls and not new_timestamps:
            old_update_interval = self.update_interval()
            self.timestamps.insert(0, arrow.utcnow())
            if self.update_interval() < old_update_interval:
                logger.debug('Skipping virtual timestamp as it would shorten update interval')
                self.timestamps.pop(0)

        self.timestamps = sorted(self.timestamps, reverse=True)

        logger.debug('New latest timestamp: %r' % self.timestamps[0])
        logger.debug('New delay: %d seconds' % seconds_in_timedelta(self.update_interval()))

        del self.timestamps[self.history_limit:]

        if len(self.items) > self.history_limit:
            items = sorted(self.items, key=operator.attrgetter('timestamp'), reverse=True)
            del items[self.history_limit:]
            self.items = set(items)

        if new_items:
            self.add_update(new_items)

        self.initial_check = False

        logger.debug('Checked %d time(s)' % self.check_count)

        logger.debug('Next check: %s (%s)' % (
            format_timestamp(self.next_check), seconds_until(self.next_check, readable=True)
        ))

    def open_updates(self, path):
        try:
            with open(path) as fp:
                updates = json.load(fp)
        except (IOError, ValueError):
            updates = []
        finally:
            return updates

    def write_updates(self, path, updates):
        with open(path, 'wb') as fp:
            json.dump(updates, fp, indent=2, sort_keys=True)

    def add_update(self, items):
        """
        Add an update to the archive JSON file.
        """
        obj = {
            'timestamp': str(arrow.utcnow()),
            'feed': {
                'title': self.parsed.feed.get('title', ''),
                'description': self.parsed.feed.get('description', ''),
                'web_url': self.parsed.feed.get('link', ''),
                'feed_url': self.url,
            },
            'items': [],
        }

        if self.initial_check:
            items = items[:self.initial_limit]

        for item in items:
            obj['items'].append(item.info())

        self.update_archive(obj)

    def update_archive(self, obj):
        fname = '%s.json' % arrow.now().format('YYYY-MM-DD')
        archive_path = os.path.join(self.args.output, fname)
        updates = self.open_updates(archive_path)
        updates.insert(0, obj)
        self.write_updates(archive_path, updates)

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
                logger.debug('Headers: %r' % headers)
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
    def __init__(self, args, feed_list):
        self.args = args
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
            doc = yaml.load(resp.text)
        else:
            doc = yaml.load(open(path))

        self.last_checked = arrow.utcnow()

        return list(
            set([Feed(self.args, url) for url in doc])
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
            self.logger.debug('Adding: %r' % new_feeds)
            self.feeds.extend(new_feeds)

        removed_feeds = filter(lambda feed: feed not in updated, self.feeds)
        if removed_feeds:
            self.logger.debug('Removing: %r' % removed_feeds)
            for feed in removed_feeds:
                self.feeds.remove(feed)

        if not new_feeds and not removed_feeds:
            self.logger.debug('No updates to feed list')

    def need_update(self, interval):
        """
        Return True if the feed list is due for a check.
        """
        return seconds_since(self.last_checked) > interval

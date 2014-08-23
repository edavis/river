import re
import yaml
import arrow
import logging
import operator
import requests
import feedparser
from datetime import timedelta
from .utils import seconds_in_timedelta, format_timestamp, seconds_until, seconds_since
from .item import Item

logger = logging.getLogger(__name__)

class Feed(object):
    failed_urls = set()
    min_update_interval = 15*60
    max_update_interval = 60*60
    history_limit = 1000 # number of items to keep in items/timestamps
    window = 10 # number of timestamps to use for update interval

    def __init__(self, url):
        self.url = url
        self.last_checked = None # time of last feed check
        self.check_count = 0     # number of times the feed has been checked
        self.headers = {}        # response headers (updated each request)
        self.payload = None      # unparsed feed content
        self.timestamps = []     # timestamps used for update_interval
        self.items = []          # previously seen items

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
        if self.last_checked is None:
            return arrow.Arrow(1970, 1, 1)
        return self.last_checked + self.update_interval()

    def check(self):
        new_items = filter(lambda item: item not in self.items, self)
        new_timestamps = 0

        if new_items:
            logger.info('Found %d new item(s)' % len(new_items))
        else:
            logger.info('No new items')

        if self.timestamps:
            logger.debug('Old delay: %d seconds' % seconds_in_timedelta(self.update_interval()))
            logger.debug('Old latest timestamp: %r' % self.timestamps[0])

        for item in new_items:
            if item.timestamp is not None:
                # Skip bogus timestamps
                self.timestamps.insert(0, item.timestamp)
                new_timestamps += 1
            self.items.insert(0, item)

        if (self.url not in self.failed_urls and
            not new_timestamps and
            arrow.utcnow() > self.timestamps[0]):
            self.timestamps.insert(0, arrow.utcnow())

        self.timestamps = sorted(self.timestamps, reverse=True)

        logger.debug('New latest timestamp: %r' % self.timestamps[0])
        logger.debug('New delay: %d seconds' % seconds_in_timedelta(self.update_interval()))

        del self.timestamps[self.history_limit:]
        del self.items[self.history_limit:]

        self.last_checked = arrow.utcnow()
        self.check_count += 1

        logger.debug('Checked %d time(s)' % self.check_count)

        logger.debug('Next check: %s (%s)' % (
            format_timestamp(self.next_check), seconds_until(self.next_check, readable=True)
        ))

    def parse(self):
        try:
            content = self.download()
        except requests.exceptions.RequestException:
            return None
        else:
            return feedparser.parse(content)
            
    def download(self):
        headers = {}
        if self.headers.get('last-modified'):
            headers['If-Modified-Since'] = self.headers.get('last-modified')
        if self.headers.get('etag'):
            headers['If-None-Match'] = self.headers.get('etag')

        try:
            logger.debug('Requesting with headers: %r' % headers)
            response = requests.get(self.url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            logger.exception('Request failed')
            self.failed_urls.add(self.url)
            raise
        else:
            self.failed_urls.discard(self.url)

        logger.debug('Status code: %d' % response.status_code)

        self.headers.update(response.headers)

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

    def parse(self, path):
        if re.search('^https?://', path):
            response = requests.get(path)
            response.raise_for_status()
            doc = yaml.load(resp.text)
        else:
            doc = yaml.load(open(path))

        self.last_checked = arrow.utcnow()

        return [Feed(url) for url in doc]

    def active(self):
        assert self.feeds, 'no feeds to check!'
        self.feeds = sorted(self.feeds, key=operator.attrgetter('next_check'))
        return self.feeds[0]

    def update(self):
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
        return seconds_since(self.last_checked) > interval

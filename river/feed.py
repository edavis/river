import arrow
import requests
import feedparser
from datetime import timedelta
from .utils import seconds_in_timedelta
from .item import Item

class Feed(object):
    failed_urls = set()
    min_update_interval = 2*60 # 2m
    max_update_interval = 24*60*60 # 24h
    history_limit = 1000 # number of items to keep in items/timestamps
    window = 10 # number of timestamps to use for update interval

    def __init__(self, url, group=None):
        self.url = url
        self.group = group
        self.last_checked = None # time of last feed check
        self.check_count = 0     # number of times the feed has been checked
        self.headers = {}        # response headers (updated each request)
        self.payload = None      # unparsed feed content
        self.timestamps = []     # timestamps used for update_interval
        self.items = []          # previously seen items

    def __cmp__(self, other):
        return cmp(self.next_check, other.next_check)

    def __repr__(self):
        return '<Feed: %s>' % self.url

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
            # Try again in an hour
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

    def is_outdated(self):
        return arrow.utcnow() > self.next_check

    def check(self):
        new_items = filter(lambda item: item not in self.items, self)
        new_timestamps = 0

        for item in new_items:
            if item.timestamp is not None:
                # Skip bogus timestamps
                self.timestamps.insert(0, item.timestamp)
                new_timestamps += 1
            self.items.insert(0, item)

        if self.url not in self.failed_urls:
            if new_timestamps:
                print ('new', new_timestamps)
            else:
                print ('no new timestamps',)
                self.timestamps.insert(0, arrow.utcnow())

        self.timestamps = sorted(self.timestamps, reverse=True)

        del self.timestamps[self.history_limit:]
        del self.items[self.history_limit:]

        print ('timestamps', self.timestamps[:self.window])

        self.last_checked = arrow.utcnow()
        self.check_count += 1

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
            response = requests.get(self.url, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
        except requests.exceptions.RequestException as ex:
            print ('failure', self.url)
            self.failed_urls.add(self.url)
            raise ex
        else:
            self.failed_urls.discard(self.url)
        
        self.headers.update(response.headers)

        if response.status_code == 200:
            self.payload = response.text

        assert self.payload, 'empty payload!'
        return self.payload
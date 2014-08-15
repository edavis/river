#!/usr/bin/env python

import re
import yaml
import time
import arrow
import random
import hashlib
import argparse
import operator
import requests
import itertools
import feedparser
from datetime import datetime, timedelta

class Item(object):
    def __init__(self, item):
        self.item = item

    def __eq__(self, other):
        return self.fingerprint == other.fingerprint

    def __ne__(self, other):
        return self.fingerprint != other.fingerprint

    @property
    def timestamp(self):
        for key in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if not self.item.get(key): continue
            val = (self.item[key])[:6]
            reported_timestamp = arrow.get(datetime(*val))
            if arrow.Arrow(2000, 1, 1) > reported_timestamp:
                # If pre-2000, consider it bogus
                return None
            elif reported_timestamp < arrow.utcnow():
                return reported_timestamp
        return arrow.utcnow()

    @property
    def fingerprint(self):
        if self.item.get('guid'):
            return self.item.get('guid')
        else:
            s = ''.join([
                self.item.get('title', ''),
                self.item.get('link', ''),
            ])
            s = s.encode('utf-8', 'ignore')
            return hashlib.sha1(s).hexdigest()

class Feed(object):
    id = itertools.count(1)
    failed_urls = set()
    min_update_interval = 2*60 # 2m
    max_update_interval = 24*60*60 # 24h

    def __init__(self, url, group=None, window=10):
        self.url = url
        self.group = group
        self.window = window      # number of timestamps to use
        self.last_checked = None  # time of last feed check
        self.check_count = 0      # number of times the feed has been checked
        self.headers = {}         # response headers (updated each request)
        self.payload = None       # unparsed feed content

        self.history_limit = 1000 # number of items to keep in below lists
        self.timestamps = []      # timestamps used for update_interval
        self.items = []           # previously seen items

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
        seconds = (interval.days * 24 * 60 * 60) + interval.seconds
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

        del self.timestamps[self.history_limit:]
        del self.items[self.history_limit:]

        print ('timestamps', sorted(self.timestamps, reverse=True)[:self.window])

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

def parse_feed_list(path):
    if re.search('^https?://', path):
        response = requests.get(path)
        response.raise_for_status()
        doc = yaml.load(resp.text)
    else:
        doc = yaml.load(open(path))

    for group, feed_urls in doc.items():
        for feed_url in feed_urls:
            yield Feed(feed_url, group)

def seconds_until(timestamp):
    if arrow.utcnow() > timestamp:
        return 0
    return (timestamp - arrow.utcnow()).seconds

def seconds_since(timestamp):
    return (arrow.utcnow() - timestamp).seconds

def outdated(feeds):
    return filter(lambda feed: feed.is_outdated(), feeds)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('feeds')
    args = parser.parse_args()

    feeds = list(parse_feed_list(args.feeds))
    random.shuffle(feeds)

    while True:
        for feed in outdated(feeds):
            print ('outdated', feed.url)
            feed.check()
            print

        print ('now', arrow.now())

        if Feed.failed_urls:
            print ('failed urls', Feed.failed_urls)

        feeds = sorted(feeds)
        for feed in feeds[:10]:
            seconds = seconds_until(feed.next_check)
            print ('upcoming', feed.check_count, feed.url, feed.next_check.to('local'), divmod(seconds, 60))
        print

        seconds = seconds_until(feeds[0].next_check)
        time.sleep(seconds + 1)

if __name__ == '__main__':
    main()

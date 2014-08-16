import re
import time
import yaml
import arrow
import random
import logging
import argparse
from .utils import seconds_until
from .feed import Feed

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

def outdated(feeds):
    return filter(lambda feed: feed.is_outdated(), feeds)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('feeds')
    args = parser.parse_args()

    logger = logging.getLogger('river')
    logger.setLevel(logging.DEBUG if args.debug else logging.INFO)
    formatter = logging.Formatter(
        '[%(levelname)-8s] %(asctime)s - %(message)s',
        '%Y-%m-%d %H:%M:%S',
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

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

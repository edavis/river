import re
import time
import yaml
import arrow
import random
import logging
import argparse
from .utils import seconds_until, format_timestamp
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
        '[%(levelname)-8s] %(asctime)s (%(name)s) - %(message)s',
        '%Y-%m-%d %H:%M:%S',
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    feeds = list(parse_feed_list(args.feeds))
    random.shuffle(feeds)

    try:
        while True:
            for feed in outdated(feeds):
                logger.info('Checking feed: %s' % feed.url)
                feed.check()

            feeds = sorted(feeds)
            logger.info('Update queue:')
            for idx, feed in enumerate(feeds[:10]):
                minutes, seconds = divmod(seconds_until(feed.next_check), 60)
                logger.info('%02d: %s at %s (%02d:%02d)' % (
                    idx + 1, feed.url, format_timestamp(feed.next_check),
                    minutes, seconds,
                ))

            seconds = seconds_until(feeds[0].next_check)
            time.sleep(seconds + 1)

    except KeyboardInterrupt:
        print '\nQuitting...'

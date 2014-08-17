import re
import time
import yaml
import arrow
import logging
import operator
import argparse
from .utils import seconds_until, seconds_since, format_timestamp
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
            yield Feed(feed_url)

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
    active_feed = feeds[0]

    try:
        while True:
            logger.info('Checking feed: %s' % active_feed.url)
            active_feed.check()

            feeds = sorted(feeds, key=operator.attrgetter('next_check'))
            active_feed = feeds[0]
            delay = seconds_until(active_feed.next_check)

            if active_feed.last_checked is not None:
                logger.info('Next feed to be checked: %s at %s (%s)' % (
                    active_feed.url, format_timestamp(active_feed.next_check),
                    seconds_until(active_feed.next_check, readable=True),
                ))

            time.sleep(delay)

    except KeyboardInterrupt:
        print '\nQuitting...'

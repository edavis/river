import time
import logging
import argparse
from .utils import seconds_until, seconds_since, format_timestamp
from .feed import FeedList

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('-r', '--refresh', default=15, type=int)
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

    feeds = FeedList(args.feeds)
    active_feed = None

    try:
        while True:
            if active_feed is not None:
                logger.info('Checking feed: %s' % active_feed.url)
                active_feed.check()

            if feeds.need_update(args.refresh * 60):
                feeds.update()

            active_feed = feeds.active()
            delay = seconds_until(active_feed.next_check)

            if active_feed.last_checked is not None:
                logger.info('Next feed to be checked: %s at %s (%s)' % (
                    active_feed.url, format_timestamp(active_feed.next_check),
                    seconds_until(active_feed.next_check, readable=True),
                ))

            time.sleep(delay)

    except KeyboardInterrupt:
        print '\nQuitting...'

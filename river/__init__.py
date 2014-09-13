import logging

__version__ = '0.3'

logger = logging.getLogger('river')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '[%(levelname)-8s] %(asctime)s (%(name)s) - %(message)s',
    '%Y-%m-%d %H:%M:%S',
)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)

file_handler = logging.FileHandler('/tmp/river.log')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.WARNING)
logger.addHandler(file_handler)

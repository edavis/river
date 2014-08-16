import arrow
import requests

def seconds_in_timedelta(delta):
    """
    Return the number of seconds in the given timedelta.

    Accounts for the number of days in the delta, too.
    """
    return (delta.days * 24 * 60 * 60) + delta.seconds

def seconds_until(timestamp):
    if arrow.utcnow() > timestamp:
        return 0
    return seconds_in_timedelta(timestamp - arrow.utcnow())

def format_timestamp(timestamp):
    return timestamp.to('local').format('ddd, DD MMM YYYY HH:mm:ss Z')

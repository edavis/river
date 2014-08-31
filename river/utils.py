import os
import json
import arrow
import requests

def seconds_in_timedelta(delta):
    """
    Return the number of seconds in the given timedelta.

    Accounts for the number of days in the delta, too.
    """
    return (delta.days * 24 * 60 * 60) + delta.seconds

def seconds_until(timestamp, readable=False):
    if arrow.utcnow() > timestamp:
        seconds = 0
    else:
        seconds = seconds_in_timedelta(timestamp - arrow.utcnow())

    if readable:
        m, s = divmod(seconds, 60)
        return '%02d:%02d' % (m, s)
    else:
        return seconds

def seconds_since(timestamp):
    return seconds_in_timedelta(arrow.utcnow() - timestamp)

# TODO merge these
def format_timestamp(timestamp, local=True):
    fmt = 'ddd, DD MMM YYYY HH:mm:ss Z'
    ts = timestamp.to('local') if local else timestamp
    return ts.format(fmt)

def display_timestamp(value, fmt='hh:mm A; M/D/YY'):
    timestamp = arrow.get(value).to('local')
    return timestamp.format(fmt)

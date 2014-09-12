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
    if isinstance(timestamp, basestring):
        timestamp = arrow.get(timestamp)
    return seconds_in_timedelta(arrow.utcnow() - timestamp)

def format_timestamp(timestamp, web=True, local=True):
    if isinstance(timestamp, basestring):
        timestamp = arrow.get(timestamp)

    if local:
        timestamp = timestamp.to('local')

    return timestamp.format('hh:mm A; M/D/YY' if web else 'ddd, DD MMM YYYY HH:mm:ss Z')

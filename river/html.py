import os
import glob
import math
import json
import arrow
import jinja2
import logging
import argparse
from datetime import timedelta
from river.utils import seconds_since, seconds_in_timedelta, display_timestamp

logger = logging.getLogger(__name__)

html_environment = jinja2.Environment(
    loader = jinja2.PackageLoader('river'),
)
html_environment.filters['display_timestamp'] = display_timestamp
html_template = html_environment.get_template('index.html')

def score_update(update, gravity=1.3):
    if 'previous_update' not in update:
        return None
    t = arrow.get(update['timestamp'])
    p = arrow.get(update['previous_timestamp'])
    delta = max(seconds_in_timedelta(t - p), 1)
    hours = seconds_since(t) / 60**2.0
    return math.log10(delta) / (hours+1) ** gravity

def html_filename(json_fname):
    """
    Return an HTML filename for the given JSON filename.

    Creates all the necessary parent directories, too.

    >>> html_filename('html/2014-08-31.json')
    'html/2014/08/31/index.html'
    """
    directory, fname = os.path.split(json_fname)
    archive, ext = os.path.splitext(fname)
    p = os.path.join(directory, archive.replace('-', '/'), 'index.html')
    if not os.path.isdir(os.path.dirname(p)):
        os.makedirs(os.path.dirname(p))
    return p

def render_html(updates, fname):
    body = html_template.render(updates=updates).encode('utf-8')
    with open(fname, 'w') as fp:
        fp.write(body)

def setmtime(json_fname, html_fname):
    mtime = os.path.getmtime(json_fname)
    os.utime(html_fname, (mtime, mtime))

def needs_update(json_fname, html_fname):
    if not os.path.isfile(html_fname):
        return True
    json_mtime = os.path.getmtime(json_fname)
    html_mtime = os.path.getmtime(html_fname)
    return json_mtime > html_mtime

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--gravity', default=1.3, type=float)
    parser.add_argument('--cron', action='store_true')
    parser.add_argument('directory')
    args = parser.parse_args()

    if args.cron:
        logger.setLevel(logging.WARNING)

    updates = []
    for json_fname in sorted(glob.iglob(os.path.join(args.directory, '*.json'))):
        html_fname = html_filename(json_fname)

        if not needs_update(json_fname, html_fname):
            continue

        logger.info('Processing %s -> %s' % (json_fname, html_fname))

        with open(json_fname) as fp:
            updates = json.load(fp)

        chronological_updates = sorted(updates, key=lambda u: u['timestamp'], reverse=True)
        render_html(chronological_updates, html_fname)
        setmtime(json_fname, html_fname)

    if updates:
        index_fname = os.path.join(args.directory, 'index.html')
        logger.info('Processing %s -> %s' % (json_fname, index_fname))

        # Rely on the fact that 'updates' from the last iteration (i.e.,
        # the most recent JSON file) is still available for use here.
        scored_updates = sorted(updates, key=lambda u: score_update(u, args.gravity), reverse=True)
        render_html(scored_updates, index_fname)

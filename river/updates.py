import os
import json
import arrow
import jinja2

def display_timestamp(value, fmt='hh:mm A; M/D/YY'):
    timestamp = arrow.get(value).to('local')
    return timestamp.format(fmt)

class Updates(object):
    def __init__(self, output):
        self.output = output
        self.environment = jinja2.Environment(
            loader = jinja2.PackageLoader('river'),
        )
        self.environment.filters['display_timestamp'] = display_timestamp

    def add_update(self, feed_obj, items):
        """
        Add an update to the archive JSON file.
        """
        obj = {
            'timestamp': str(arrow.utcnow()),
            'feed': {
                'title': feed_obj.parsed.feed.get('title', ''),
                'description': feed_obj.parsed.feed.get('description', ''),
                'web_url': feed_obj.parsed.feed.get('link', ''),
                'feed_url': feed_obj.url,
            },
            'feed_items': [],
        }

        if feed_obj.initial_check:
            items = items[:feed_obj.initial_limit]

        for item in items:
            obj['feed_items'].append(item.info)

        self.update_archive(obj)

    def mkdir_p(self, p):
        directory = os.path.dirname(p)
        if not os.path.isdir(directory):
            os.makedirs(directory)

    def update_archive(self, obj):
        fname = 'json/%s.json' % arrow.now().format('YYYY-MM-DD')
        archive_path = os.path.join(self.output, fname)
        self.mkdir_p(archive_path)

        updates = self.open_updates(archive_path)
        updates.insert(0, obj)
        self.write_updates(archive_path, updates)
        self.render_template(archive_path)

    def render_template(self, archive_path):
        html_archive_fname = '%s/index.html' % arrow.now().format('YYYY/MM/DD')
        html_archive_path = os.path.join(self.output, html_archive_fname)
        self.mkdir_p(html_archive_path)

        html_index_path = os.path.join(self.output, 'index.html')

        updates = self.open_updates(archive_path)
        html_template = self.environment.get_template('index.html')
        html_body = html_template.render(updates=updates).encode('utf-8')

        for fname in [html_archive_path, html_index_path]:
            with open(fname, 'wb') as html:
                html.write(html_body)

    def open_updates(self, path):
        try:
            with open(path) as fp:
                updates = json.load(fp)
        except (IOError, ValueError):
            updates = []
        finally:
            return updates

    def write_updates(self, path, updates):
        with open(path, 'wb') as fp:
            json.dump(updates, fp, indent=2, sort_keys=True)

import os
import json
import arrow

class Updates(object):
    def __init__(self, output):
        self.output = output

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
            'items': [],
        }

        if feed_obj.initial_check:
            items = items[:feed_obj.initial_limit]

        for item in items:
            obj['items'].append(item.info)

        self.update_archive(obj)

    def update_archive(self, obj):
        fname = '%s.json' % arrow.now().format('YYYY-MM-DD')
        archive_path = os.path.join(self.output, fname)
        updates = self.open_updates(archive_path)
        updates.insert(0, obj)
        self.write_updates(archive_path, updates)

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

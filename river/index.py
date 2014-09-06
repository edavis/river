import os
import json
import arrow
import jinja2
from .utils import format_timestamp, seconds_since

class Index(object):
    def __init__(self, output):
        self.output = output

        self.environment = jinja2.Environment(loader=jinja2.PackageLoader('river'))
        self.environment.filters['format_timestamp'] = format_timestamp
        self.template = self.environment.get_template('index.html')

        self.archive = os.path.join(self.output, arrow.now().format('YYYY/MM/DD'))
        if not os.path.isdir(self.archive):
            os.makedirs(self.archive)

    def write_archive(self, json_path):
        filename = os.path.join(self.archive, 'index.html')

        with open(json_path) as json_fp:
            updates = json.load(json_fp)

        with open(filename, 'w') as html_fp:
            body = self.template.render(updates=updates).encode('utf-8')
            html_fp.write(body)

    def factor_update(self, update):
        return seconds_since(arrow.get(update['timestamp'])) * (1 / float(update['factor']))

    def write_index(self, updates):
        filename = os.path.join(self.output, 'index.html')
        updates = sorted(updates, key=self.factor_update)
        with open(filename, 'w') as html_fp:
            body = self.template.render(updates=updates).encode('utf-8')
            html_fp.write(body)

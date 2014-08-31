import arrow
import bleach
import hashlib
from datetime import datetime, timedelta

class Item(object):
    def __init__(self, item):
        self.item = item
        self.created = arrow.utcnow()

    def __eq__(self, other):
        return self.fingerprint == other.fingerprint

    def __ne__(self, other):
        return self.fingerprint != other.fingerprint

    def __hash__(self):
        return hash(self.fingerprint)

    def clean_text(self, text, limit=280, suffix=u'\u2026'):
        cleaned = bleach.clean(text, tags=[], strip=True).strip()
        if len(cleaned) > limit:
            s = u''.join(cleaned[:limit]).strip()
            idx = s.rfind(' ')
            return s[:idx] + suffix
        else:
            return cleaned

    @property
    def info(self):
        obj = {
            'timestamp': str(self.timestamp or arrow.Arrow(1970, 1, 1)),
            'guid': self.item.get('guid', ''),
        }

        if self.item.get('title') and self.item.get('description'):
            obj['title'] = self.clean_text(self.item.get('title'))
            obj['body'] = self.clean_text(self.item.get('description'))

            if obj['title'] == obj['body']:
                obj['body'] = ''

        elif not self.item.get('title') and self.item.get('description'):
            obj['title'] = self.clean_text(self.item.get('description'))
            obj['body'] = ''

        elif self.item.get('title'):
            obj['title'] = self.clean_text(self.item.get('title'))
            obj['body'] = ''

        if self.item.get('link'):
            obj['link'] = self.item.get('link')

        if self.item.get('comments'):
            obj['comments'] = self.item.get('comments')

        return obj

    @property
    def delay(self):
        """
        Return a timedelta representing the delay between when the item
        appeared in the feed and when it was first seen.
        """
        if self.timestamp is not None:
            return self.created - self.timestamp
        else:
            return timedelta(seconds=0)

    @property
    def timestamp_provided(self):
        """
        Return True if there was a provided timestamp for the item.
        """
        return self.timestamp != self.created

    @property
    def timestamp(self):
        for key in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if not self.item.get(key): continue
            val = (self.item[key])[:6]
            reported_timestamp = arrow.get(datetime(*val))
            if arrow.Arrow(2000, 1, 1) > reported_timestamp:
                # If pre-2000, consider it bogus
                return None
            elif reported_timestamp < self.created:
                return reported_timestamp
        return self.created

    @property
    def fingerprint(self):
        if self.item.get('guid'):
            return self.item.get('guid')
        else:
            s = ''.join([
                self.item.get('title', ''),
                self.item.get('link', ''),
            ])
            s = s.encode('utf-8', 'ignore')
            return hashlib.sha1(s).hexdigest()

# river

`river` is a River of News aggregator written in Python.

Given a list of RSS feeds, each feed is periodically checked. Whenever
a feed updates, new items are written out to an HTML file.

The end result is a reverse chronological list of feed updates from a
variety of RSS feeds.

I find it a very pleasant way to consume the news. Maybe you will too.

## Quick Start

It's recommended to install river into a virtualenv:

```bash
$ virtualenv ~/river
$ source ~/river/bin/activate
(river)$ pip install river
(river)$ river -o ~/river/html/ https://raw.githubusercontent.com/edavis/river/master/feed-lists/tech.txt
```

`river` will now perform an initial check of each feed.

Once this finishes, `river` will periodically check each feed using a
scheduling algorithm that tries to minimize the delay between when new
items appear in the RSS feed and when the feed is checked.

Inside `~/river/html/` you'll see the generated HTML files.

## Options

- Min/max update interval
- How often to refresh the feed list
- Output

## Feed lists

- YAML
- How to set title
- Dropbox is good

## Factors

Explain how to assign different weights to feeds and the effect it has.

## Feed check algorithm

Explain moving averages, virtual timestamps, and min/max interval.

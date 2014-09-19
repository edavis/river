# river

`river` is a [River of News aggregator][definition] written in Python.

Given a list of RSS/Atom feeds, each feed is checked periodically and
new items are written out to a "stream" of all previous items from all feeds.

[definition]: http://scripting.com/2014/06/02/whatIsARiverOfNewsAggregator.html

## Quick Start

Creating a feed list is easy, but for now we'll use an existing
one. The [Techmeme Leaderboard][] is a list of feeds from 100 top
technology news sites and blogs.

It's recommended to install `river` into a virtualenv:

```bash
$ virtualenv ~/river
$ source ~/river/bin/activate
(river)$ pip install https://github.com/edavis/river/archive/v0.3.1.zip
(river)$ river -o ~/river/html/ http://www.techmeme.com/lb.opml
```

`river` will now start processing each feed in the feed list. This'll
take a few minutes to complete.

While it's running, the output HTML is being written to the
`~/river/html/` directory. Let's see what it looks like.

Open up a new terminal window (or tab) and change to the
`~/river/html/` directory. Now run: `python -m SimpleHTTPServer`. The
generated HTML depends on [normalize.css][] and some browsers won't
load external assets when viewing an HTML file directly from
disk. With this, we create a simple HTTP server to view the files,
bypassing that restriction.

Now visit [http://localhost:8000/][localhost] in your browser. This is
your river of news! Pretty cool, huh?

A black star ("&#9733;") next to a feed title indicates this feed is
being checked for the first time. These feeds only show the five most
recent items, to keep the page from getting too big.

`river` will keep checking the feeds until you stop it. Refresh
[http://localhost:8000/][localhost] in half an hour or so and you'll
see new feed items displayed at the top of the page.

[normalize.css]: http://necolas.github.io/normalize.css/
[Techmeme Leaderboard]: http://www.techmeme.com/lb.opml
[localhost]: http://localhost:8000/

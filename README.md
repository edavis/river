# river

`river` is a [River of News aggregator][definition] written in Python.

It takes a list of RSS/Atom feeds and checks them periodically. As new
updates arrive, they're written out to an HTML file.

[definition]: http://scripting.com/2014/06/02/whatIsARiverOfNewsAggregator.html

## Quick Start

Before we can get started, we need a feed list. Creating one is easy,
but for now we'll use one that [already exists][Techmeme Leaderboard].

It's recommended to install `river` into a virtualenv:

```bash
$ virtualenv ~/river/
$ source ~/river/bin/activate
(river)$ pip install https://github.com/edavis/river/archive/v0.3.2.zip
(river)$ river -o ~/river/html/ http://www.techmeme.com/lb.opml
```

`river` will now start processing each feed in the feed list. This'll
take a few minutes to complete.

Now let's see what the output HTML looks like. First, we start up a
simple HTTP server so all external assets get loaded:

```bash
$ cd ~/river/html/
$ python -m SimpleHTTPServer
```

Now, in your browser, visit [http://localhost:8000/][localhost]. If everything
worked, you'll see a bunch of technology related news and blog
posts. This is your river of news. Congrats!

`river` will keep checking the feeds until you tell it to
stop. Refresh [http://localhost:8000/][localhost] in half an hour or
so and you'll see new feed items displayed at the top of the page.

[Techmeme Leaderboard]: http://www.techmeme.com/lb.opml
[localhost]: http://localhost:8000/

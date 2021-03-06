# Demo access to synced Firefox passwords via OAuth.

Extremely experimental!  Proceed with caution.

This is a demo app that can access your synced Firefox passwords
using an OAuth authorization flow.  You'll need to create a
Firefox Account, sign in to Firefox, and sync some saved passwords
before we can do anything interesting here.

Once you've got that set up and syncing, there are two things in
this repo that you might find interesting.

The first is a python script that will prompt for access to your
sync data via OAuth, and then print out your synced passwords:

```
    pip install -r ./requirements.txt
    python ./boxlocker.py
```

This script will save the granted OAuth tokens to disk as
`./credentials.json`.

It's not particularly well-written python, because it's mostly thrown
together as a demo app to get something up and running.

The second is a rust program that does the same thing.  The OAuth
prompt part is not yet implemented, but if you've got saved
credentials from the script above, you can print out your synced
passwords with:

```
    cargo run
```

I'm sure it's terrible rust code, because it's the first rust code
I've ever written.  But if it seems useful, we can work on evolving
it into a better-strutured shared library for accessing sync data,
at which point we'd just delete the python version.

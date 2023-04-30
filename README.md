# GRANDMA interface for FRAM telescopes

 - listener.py - generic listener that polls SkyPortal for new plans for a given instruments, and stores them locally

It requires SkyPortal API access token to be provided either by command-line argument (`-t`), or in a text file `.token` placed in the same folder as the script.

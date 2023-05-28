# GRANDMA interface for FRAM telescopes

Simple interface between GRANDMA and FRAM telescopes.
It is designed to operate directly at the telescope machines, and thus to be as easy as possible. It works without any database and uses simple text files to store the observing plans and results of their observations.

 - listener.py - generic listener that polls SkyPortal for new plans for a given instruments, and stores them locally

It requires SkyPortal API access token to be provided either by command-line argument (`-t`), or in a text file `.token` placed in the same folder as the script.

It stores the original plans as JSON files in a dedicated folder. Alongside them, the lists of fields to be observed by the telescope are stored as simple text files.

 - plans.py - simple visibility checker for observing plans that uses telescope connection to get its latitude, longitude etc.

 - observe_rts2.py - RTS2 script for the telescope to observe the stored plans

 - export.py - exporter for FITS files from FRAM archive with proper keywords and file names for GRANDMA

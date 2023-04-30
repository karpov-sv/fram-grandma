#!/usr/bin/env python3

import os, sys, glob, time
import numpy as np

import urllib
import requests
import json

from astropy.time import Time, TimeDelta
from astropy import units as u

# Simple writing of some data to file
def file_write(filename, contents=None, append=False):
    """
    Simple utility for writing some contents into file.
    """

    with open(filename, 'a' if append else 'w') as f:
        if contents is not None:
            f.write(contents)

def file_read(filename):
    with open(filename, 'r') as f:
        return f.read()

def listen(options={}):
    print(f"Polling SkyPortal at {options.baseurl} every {options.delay} seconds")

    if options.instrument:
        print(f"Polling for instrument_id {options.instrument}")

    url = urllib.parse.urljoin(options.baseurl, "/api/observation_plan")
    headers = {'Authorization': f'token {options.token}'}

    while True:
        # print("Requesting plans")

        now = Time.now()
        start = now - TimeDelta(1*u.day)

        params = {"instrumentID": options.instrument,
                  "startDate": start.isot,
                  "endDate": now.isot,
                  "status": "complete",
                  "includePlannedObservations" : True}

        result = requests.get(url, headers=headers, params=params)

        if result.status_code != 200:
            print(f'Reply code {result.status_code} while requesting {url}')
            time.sleep(options.delay)
            continue

        # Now we iterate all observing plan requests
        for req in result.json()["data"]["requests"]:
            # print('Localization', req['localization_id'], 'event', req['gcnevent_id'])

            for plan in req['observation_plans']:
                # Sanitize plan name to be used as filename
                planname = plan['plan_name'].replace(' ', '_')
                planname = os.path.join(options.base, planname) + '.json'

                if os.path.exists(planname):
                    # We already know this plan
                    continue

                print(f"New plan {plan['id']} / {plan['plan_name']} for localization {req['localization_id']} - {len(plan['planned_observations'])} observations")
                print(f"stored to {planname}")

                os.makedirs(options.base, exist_ok=True)
                file_write(planname, json.dumps(plan, indent=4))

        time.sleep(options.delay)

if __name__ == '__main__':
    from optparse import OptionParser

    # Guess some defaults
    instrument_id = 22 # FRAM-Auger

    token_path = os.path.join(os.path.dirname(__file__), '.token')
    if os.path.exists(token_path):
        # Load the token from file
        token = file_read(token_path).strip()
    else:
        token = None

    parser = OptionParser(usage="usage: %prog [options] arg")
    parser.add_option('-b', '--base', help='Base path for storing plans', action='store', dest='base', default='plans')

    parser.add_option('-s', '--skyportal', help='SkyPortal base url', action='store', dest='baseurl', default='https://skyportal-icare.ijclab.in2p3.fr')
    parser.add_option('-t', '--token', help='SkyPortal API access token', action='store', dest='token', default=token)

    parser.add_option('-d', '--delay', help='Delay between the requests', action='store', dest='delay', type='int', default=10)

    parser.add_option('-i', '--instrument', help='Only accept packets for this instrument (SkyPortal ID)', action='store', dest='instrument', type='int', default=instrument_id)

    (options,args) = parser.parse_args()

    if not options.token:
        print('Cannot operate without SkyPortal API token!')
        sys.exit(1)

    # Main cycle
    listen(options=options)

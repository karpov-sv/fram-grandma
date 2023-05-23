#!/usr/bin/env python3

import os, sys, glob, time
import numpy as np

import urllib
import requests
import json

from astropy.time import Time, TimeDelta
from astropy import units as u
from astropy.table import Table

from telescope import get_horizon, send_email

def plan_basename(plan, base=None):
    """
    Get the filename for this plan
    """

    # Sanitize plan name to be used as filename
    planname = plan['plan_name'].replace(' ', '_')

    if base:
        planname = os.path.join(base, planname)

    return planname

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

def plan_fields(plan):
    # Individual fields inside the plan
    fields = Table([{**_['field'],  **{__: _[__] for __ in ['weight', 'exposure_time', 'filt']}}
                    for _ in plan['planned_observations']])

    if len(fields):
        fields = fields[['id', 'ra', 'dec', 'weight', 'filt', 'exposure_time']]

    return fields

def process_plan(plan, options={}):
    fields = plan_fields(plan)

    if not len(fields):
        # Empty plan?..
        return

    # Store them to a separate text file alongside with the plan
    fields_name = plan_basename(plan, base=options.base)
    fields_name = fields_name + '.fields'

    fields.write(fields_name, format='ascii.commented_header', overwrite=True)
    print(f"{len(fields)} fields to be observed stored to {fields_name}")

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

        try:
            result = requests.get(url, headers=headers, params=params)
        except KeyboardInterrupt:
            raise
        except:
            import traceback
            traceback.print_exc()
            time.sleep(options.delay)
            continue

        if result.status_code != 200:
            print(f'Reply code {result.status_code} while requesting {url}')
            time.sleep(options.delay)
            continue

        # Now we iterate all observing plan requests
        for req in result.json()["data"]["requests"]:
            # print('Localization', req['localization_id'], 'event', req['gcnevent_id'])

            for plan in req['observation_plans']:
                planname = plan_basename(plan, base=options.base) + '.json'

                if os.path.exists(planname):
                    # We already know this plan
                    continue

                print(f"New plan {plan['id']} / {plan['plan_name']} for localization {req['localization_id']} - {len(plan['planned_observations'])} observations")
                print(f"stored to {planname}")

                # Store the original plan to the file system
                os.makedirs(options.base, exist_ok=True)
                file_write(planname, json.dumps(plan, indent=4))

                # Now we should do something reasonable with the plan, e.g. notify the telescope or so
                process_plan(plan, options=options)

        time.sleep(options.delay)

if __name__ == '__main__':
    from optparse import OptionParser
    import platform

    # Guess some defaults
    if platform.node() == 'cta-n':
        instrument_id = 23 # FRAM-CTA-N
    else:
        instrument_id = 22 # FRAM-Auger

    api_url = 'http://localhost:8889' # Telescope RTS2 API URL

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

    parser.add_option('-a', '--api', help='Base URL for telescope RTS2 API', action='store', dest='api', default=api_url)
    parser.add_option('-u', '--username', help='Username', action='store', dest='username', default='karpov')
    parser.add_option('-p', '--password', help='Password', action='store', dest='password', default='1')

    (options,args) = parser.parse_args()

    if not options.token:
        print('Cannot operate without SkyPortal API token!')
        sys.exit(1)

    # Main cycle
    listen(options=options)

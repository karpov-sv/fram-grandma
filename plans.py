#!/usr/bin/env python3

import os, sys, glob, time, datetime
import numpy as np

import urllib
import requests
import json

from astropy.time import Time, TimeDelta
from astropy import units as u
from astropy.table import Table
from astropy.coordinates import SkyCoord, EarthLocation, AltAz

from listener import plan_fields, file_read
from telescope import get_horizon

# Main
if __name__ == '__main__':
    from optparse import OptionParser
    import platform

    # Guess some defaults
    if platform.node() == 'cta-n':
        instrument_id = 23 # FRAM-CTA-N
    else:
        instrument_id = 22 # FRAM-Auger

    default_base = os.path.join(os.path.split(__file__)[0], 'plans')
    api_url = 'http://localhost:8889' # Telescope RTS2 API URL

    # Command-line parameters
    parser = OptionParser(usage="usage: %prog [options] arg")
    parser.add_option('-b', '--base', help='Base path for storing data', action='store', dest='base', default=default_base)
    parser.add_option('-a', '--api', help='Base URL for RTS2 API', action='store', dest='api', default=api_url)
    parser.add_option('-u', '--username', help='Username', action='store', dest='username', default='karpov')
    parser.add_option('-p', '--password', help='Password', action='store', dest='password', default='1')

    (options,args) = parser.parse_args()

    if args:
        # Just dump the specified plans
        plans = args
    else:
        # Consider newest events first
        plans = sorted(glob.glob(os.path.join(options.base, '*.fields')), reverse=True)

    try:
        # Connect to RTS2 and get location and time info
        import requests
        from requests.auth import HTTPBasicAuth

        response = requests.get(options.api + '/api/getall', auth=HTTPBasicAuth(options.username, options.password))
        # response.status_code
        state = response.json()

        for _ in state.keys():
            if state[_]['type'] == 2:
                tel = _

        lon,lat,alt = state[tel]['d']['LONGITUD'], state[tel]['d']['LATITUDE'], state[tel]['d']['ALTITUDE']
        t1,t2 = state['centrald']['d']['night_beginning'], state['centrald']['d']['night_ending']
        if t2 < t1:
            t1 -= 3600*24

        obs = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=alt*u.m)
        horizon = get_horizon(min_alt=10)
        t = np.linspace(t1, t2)
        nt = Time(t, format='unix')
        nt0 = Time.now()

        has_rts2 = True
    except:
        import traceback
        traceback.print_exc()
        print('Can\'t connect to RTS2')
        has_rts2 = False

    # Process all plans
    for planname in plans:
        if '.json' in planname:
            # Original JSON plan format
            plan = json.loads(file_read(planname))
            plan = plan_fields(plan)
        else:
            # Simple text representation
            plan = Table.read(planname, format='ascii.commented_header')

        print(f"{planname}: GRANDMA plan with {len(plan['ra'])} 'pointings")

        aidx = np.argsort(-plan['weight'])
        mask = np.ones_like(plan['ra'], dtype=bool)

        for i in aidx:
            ra,dec,gid,grade = plan['ra'][i],plan['dec'][i],plan['id'][i],plan['weight'][i]

            text = ' |- grid point %d with grade %.2g at %.2f %.2f' % (gid, grade, ra, dec)

            if has_rts2:
                text += ': '

                obj = SkyCoord(ra, dec, unit='deg')

                altaz = obj.transform_to(AltAz(obstime=nt, location=obs))
                min_alt = horizon(altaz.az.deg)
                visible = altaz.alt.deg > min_alt

                altaz0 = obj.transform_to(AltAz(obstime=nt0, location=obs))
                min_alt0 = horizon(altaz0.az.deg)
                visible_now = altaz0.alt.deg > min_alt0

                if visible_now and not np.any(visible):
                    text += 'visible now but unobservable tonight'
                if visible_now and np.any(visible):
                    text += 'visible now and until ' + datetime.datetime.utcfromtimestamp(np.max(t[visible])).strftime('%H:%M:%S UT')
                elif np.any(visible):
                    text += 'visible since ' + datetime.datetime.utcfromtimestamp(np.min(t[visible])).strftime('%H:%M:%S UT')
                else:
                    text += 'unobservable tonight'

            print(text)

#!/usr/bin/env python3

import os, sys, glob, time
import datetime
import numpy as np
import platform

import urllib
import requests
from requests.auth import HTTPBasicAuth
import json

from astropy.time import Time, TimeDelta
from astropy import units as u
from astropy.table import Table

from astropy.coordinates import SkyCoord, EarthLocation, AltAz
try:
    from astropy.utils.iers import conf
    conf.auto_download = False
except:
    pass

import warnings
from astropy.utils.exceptions import AstropyWarning
warnings.simplefilter('ignore', category=AstropyWarning)


from telescope import get_horizon, send_email

def query_skyportal(endpoint, params=None, baseurl='', token=''):
    url = urllib.parse.urljoin(baseurl, endpoint)
    headers = {'Authorization': f'token {token}'}

    result = requests.get(url, headers=headers, params=params)

    if result.status_code != 200:
        print(f'Reply code {result.status_code} while requesting {url}')
        return None

    return result.json()

def plan_basename(plan, base=None):
    """
    Get the filename for this plan
    """

    # Sanitize plan name to be used as filename
    planname = plan['dateobs'] + '_' + plan['plan_name'].replace(' ', '_')

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

def plot_plan(plan, fields, options=None, visibilities=None):
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
    from matplotlib.figure import Figure
    from matplotlib.dates import DateFormatter

    import ephem

    date = Time(plan['dateobs']).datetime # datetime.datetime.utcnow()

    obs = ephem.Observer()
    obs.date = date

    moon,sun = ephem.Moon(), ephem.Sun()
    moon.compute(obs)
    sun.compute(obs)

    filenames = []

    basename = plan_basename(plan, base=options.base)

    # Map
    filename = '%s_map.jpg' % basename

    fig = Figure(facecolor='white', dpi=72, figsize=(12,6), tight_layout=True)
    ax = fig.add_subplot(111, projection='mollweide')

    idx = np.argsort(fields['weight'])
    s = ax.scatter((np.mod(fields['ra'][idx]+180.0, 360.0)-180.0)*np.pi/180, fields['dec'][idx]*np.pi/180, c=fields['weight'][idx], cmap='cool', marker='o', s=100)
    ax.set_xticklabels(['14h','16h','18h','20h','22h','0h','2h','4h','6h','8h','10h'], color='gray')
    fig.colorbar(s)
    ax.grid(color='lightgray')

    ax.scatter((np.mod(np.rad2deg(sun.ra)+180.0, 360.0)-180.0)*np.pi/180, np.rad2deg(sun.dec)*np.pi/180, s=2000, marker='o', color='lightgray', edgecolor='black')
    ax.text((np.mod(np.rad2deg(sun.ra)+180.0, 360.0)-180.0)*np.pi/180, np.rad2deg(sun.dec)*np.pi/180, 'Sun', color='black', va='center', ha='center')

    ax.scatter((np.mod(np.rad2deg(moon.ra)+180.0, 360.0)-180.0)*np.pi/180, np.rad2deg(moon.dec)*np.pi/180, s=1200, marker='o', color='lightgray', edgecolor='black')
    ax.text((np.mod(np.rad2deg(moon.ra)+180.0, 360.0)-180.0)*np.pi/180, np.rad2deg(moon.dec)*np.pi/180, 'Moon', color='black', va='center', ha='center')

    ax.set_title('%s %s: %d pointings' % (plan['event_name'], plan['plan_name'], len(fields['ra'])))

    fig.tight_layout()
    canvas = FigureCanvas(fig)
    canvas.print_png(filename)

    filenames.append(filename)

    # Visibilities and altitudes
    filename = '%s_visibility.jpg' % basename

    fig = Figure(facecolor='white', dpi=72, figsize=(12,6), tight_layout=True)
    ax = fig.add_subplot(111)

    for _ in range(len(fields['ra'])):
        gid = fields['id'][_]
        if visibilities and gid in visibilities:
            vis = visibilities[gid]
            ts = np.array([datetime.datetime.utcfromtimestamp(__) for __ in vis['t']])

            idx = vis['visible']
            s = ax.plot(ts, vis['alt'], '.-', alpha=0.1)
            ax.plot(ts[idx], vis['alt'][idx], '.', alpha=0.9, color=s[0].get_color(), label="Tile %d, p=%.2g" % (gid, fields['weight'][_]))

    ax.set_title('%s %s: %d pointings' % (plan['event_name'], plan['plan_name'], len(fields['ra'])))

    ax.set_ylim(0, 90)
    ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
    ax.set_xlabel('Time, UT')

    # ax.set_autoscale_on(False)
    ax.margins(0,0, tight=True)

    ax.axvline(date, color='gray')
    ax.axvline(datetime.datetime.utcnow(), color='black')

    ax.legend(loc=1)

    fig.tight_layout()
    canvas = FigureCanvas(fig)
    canvas.print_png(filename)

    filenames.append(filename)

    return filenames

def process_plan(plan, options={}):
    fields = plan_fields(plan)

    if not len(fields):
        # Empty plan?..
        return

    if options.maxtiles and len(fields) > options.maxtiles:
        print(f"Limiting number of fields to first {options.maxtiles} from original {len(['fields'])}")
        fields = fields[:options.maxtiles]

    # Store the plan fields to a separate text file alongside with the plan
    fields_name = plan_basename(plan, base=options.base) + '.fields'
    planname = plan_basename(plan, base=options.base) + '.json' # FIXME: propagare from upper layer somehow?..

    fields.write(fields_name, format='ascii.commented_header', overwrite=True)
    print(f"{len(fields)} fields to be observed stored to {fields_name}")

    visibilities = {}
    horizon = get_horizon(min_alt=10)

    # Visibilities
    try:
        # Connect to RTS2 and enable the target
        print('Enabling target 50')
        response = requests.get(options.api + '/api/update_target', auth=HTTPBasicAuth(options.username, options.password), params={'id': 50, 'enabled': 1})
        if response.status_code == 200:
            print('Successfully enabled target 50')
        else:
            print('Error', response.status_code, 'enabling target 50:', response.text)

        # Request observatory position and night timing
        print('Computing tiles visibility')
        response = requests.get(options.api + '/api/getall', auth=HTTPBasicAuth(options.username, options.password))
        state = response.json()

        for _ in state.keys():
            if state[_]['type'] == 2:
                tel = _

        lon,lat,alt = state[tel]['d']['LONGITUD'], state[tel]['d']['LATITUDE'], state[tel]['d']['ALTITUDE']
        t1,t2 = state['centrald']['d']['night_beginning'], state['centrald']['d']['night_ending']
        if t2 < t1:
            t1 -= 3600*24

        obs = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=alt*u.m)

        for _ in range(len(fields['ra'])):
            obj = SkyCoord(fields['ra'][_], fields['dec'][_], unit='deg')

            t = np.linspace(t1, t2)
            nt = Time(t, format='unix')
            altaz = obj.transform_to(AltAz(obstime=nt, location=obs))
            min_alt = horizon(altaz.az.deg)

            visibilities[fields['id'][_]] = {'t': t, 'alt': altaz.alt.deg, 'az': altaz.az.deg, 'visible': altaz.alt.deg > min_alt}

            nt0 = Time.now()
            altaz = obj.transform_to(AltAz(obstime=nt0, location=obs))
            min_alt = horizon(altaz.az.deg)
            visibilities[fields['id'][_]]['visible_now'] = altaz.alt.deg > min_alt

    except:
        import traceback
        traceback.print_exc()

    # Diagnostic plots
    try:
        print('Generating diagnostic plots')
        attachments = plot_plan(plan, fields, options=options, visibilities=visibilities)
    except:
        import traceback
        traceback.print_exc()
        attachments = []

    for address in options.mail:
        try:
            subject = 'GRANDMA plan ' + plan['plan_name']
            text = plan['plan_name'] + ': GRANDMA plan with %d pointings\n' % (len(fields['ra']))
            text += '\n' + planname + '\n';

            aidx = np.argsort(-fields['weight'])

            for i in aidx:
                ra,dec,gid,weight = fields['ra'][i],fields['dec'][i],fields['id'][i],fields['weight'][i]

                text += '  grid point %d with weight %.2g at %.2f %.2f' % (gid, weight, ra, dec)

                if visibilities and gid in visibilities:
                    vis = visibilities[gid]

                    text += ': '

                    if vis['visible_now'] and not np.any(vis['visible']):
                        text += 'visible now but unobservable tonight'
                    if vis['visible_now'] and np.any(vis['visible']):
                        text += 'visible now and until ' + datetime.datetime.utcfromtimestamp(np.max(vis['t'][vis['visible']])).strftime('%H:%M:%S UT')
                    elif np.any(vis['visible']):
                        text += 'visible since ' + datetime.datetime.utcfromtimestamp(np.min(vis['t'][vis['visible']])).strftime('%H:%M:%S UT')
                    else:
                        text += 'unobservable tonight'

                text += '\n'

            # print(text)

            print(f'Sending e-mail to {address}')
            sender = os.getlogin() + '@' + platform.node()
            send_email(text, to=address, sender=sender, subject=subject, attachments=attachments + [planname])
        except:
            import traceback
            traceback.print_exc()

def listen(options={}):
    print(f"Polling SkyPortal at {options.baseurl} every {options.delay} seconds")

    if options.instrument:
        print(f"Polling for instrument_id {options.instrument}")

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
            result = query_skyportal("/api/observation_plan", params=params, baseurl=options.baseurl, token=options.token)
        except KeyboardInterrupt:
            raise
        except:
            import traceback
            print("\n", Time.now())
            traceback.print_exc()

            result = None

        if not result:
            time.sleep(options.delay)
            continue

        # Now we iterate all observing plan requests
        for req in result["data"]["requests"]:
            # print('Localization', req['localization_id'], 'event', req['gcnevent_id'])

            for plan in req['observation_plans']:
                planname = plan_basename(plan, base=options.base) + '.json'

                if os.path.exists(planname):
                    # We already know this plan
                    continue

                # Time since trigger
                deltat = (Time.now() - Time(plan['dateobs'])).jd
                if deltat > options.maxage:
                    print(f"{deltat:.2f} days since event trigger, skipping plan {plan['plan_name']}")
                    continue

                event = query_skyportal("/api/gcn_event/" + plan['dateobs'], baseurl=options.baseurl, token=options.token)
                if event:
                    plan['event_name'] = event['data']['aliases'][0]
                    if plan['event_name'].startswith('LVC#'):
                        plan['event_name'] = plan['event_name'][4:]

                else:
                    print('Error requesting event information from SkyPortal')
                    plan['event_name'] = 'Unknown'

                print("\n", Time.now())
                print(f"New plan {plan['id']} / {plan['plan_name']} for event {plan['event_name']} localization {req['localization_id']} - {len(plan['planned_observations'])} fields")
                print(f"stored to {planname}")

                # Store the original plan to the file system
                os.makedirs(options.base, exist_ok=True)
                file_write(planname, json.dumps(plan, indent=4))

                # Remove the fields from previous plans for the same event
                # FIXME: de-hardcode the filename pattern somehow?.. And make it instrument-specific?..
                for oldname in glob.glob(os.path.join(options.base, plan['dateobs']) + '_*.fields'):
                    print(f"Removing older fields for the same event in {oldname}")
                    os.unlink(oldname)

                # Now we should do something reasonable with the plan, e.g. notify the telescope or so
                process_plan(plan, options=options)

        time.sleep(options.delay)

if __name__ == '__main__':
    from optparse import OptionParser

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
    parser.add_option('--max-age', help='Max age of the plan since trigger in days', action='store', dest='maxage', type='float', default=1.0)
    parser.add_option('--max-tiles', help='Max number of tiles to accept', action='store', dest='maxtiles', type='int', default=0)

    parser.add_option('-i', '--instrument', help='Only accept packets for this instrument (SkyPortal ID)', action='store', dest='instrument', type='int', default=instrument_id)

    parser.add_option('-a', '--api', help='Base URL for telescope RTS2 API', action='store', dest='api', default=api_url)
    parser.add_option('-u', '--username', help='Username', action='store', dest='username', default='karpov')
    parser.add_option('-p', '--password', help='Password', action='store', dest='password', default='1')
    parser.add_option('-m', '--mail', help='Email for sending the diagnostic message', action='append', dest='mail', type='string', default=[])

    (options,args) = parser.parse_args()

    if not options.token:
        print('Cannot operate without SkyPortal API token!')
        sys.exit(1)

    # Main cycle
    listen(options=options)

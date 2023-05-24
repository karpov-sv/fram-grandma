#!/usr/bin/env python

from __future__ import print_function, division

import datetime,time
import shutil, os, glob

import json
import numpy as np

from copy import deepcopy

from telescope import get_horizon

from astropy.table import Table
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
import astropy.units as u
try:
    from astropy.utils.iers import conf
    conf.auto_download = False
except:
    pass

import warnings
from astropy.utils.exceptions import AstropyWarning
warnings.simplefilter('ignore', category=AstropyWarning)

from rts2 import scriptcomm

if __name__ == '__main__':
    from optparse import OptionParser

    # Guess some defaults
    default_base = os.path.join(os.path.split(__file__)[0], 'plans')
    default_npointings = 20
    default_nframes = 1
    default_exposure = 120
    default_filter = 'R'

    # Command-line parameters
    parser = OptionParser(usage="usage: %prog [options] arg")
    parser.add_option('-b', '--base', help='Base path for storing data', action='store', dest='base', default=default_base)
    parser.add_option('-p', '--num-pointings', help='Number of pointings to process', action='store', dest='npointings', type='int', default=default_npointings)
    parser.add_option('-n', '--num-frames', help='Number of frames to acquire at every pointing', action='store', dest='nframes', type='int', default=default_nframes)
    parser.add_option('-e', '--exposure', help='Exposure, seconds', action='store', dest='exposure', type='int', default=default_exposure)
    parser.add_option('-f', '--filter', help='Filter to use', action='store', dest='filter', default=default_filter)

    (options,args) = parser.parse_args()

    # Consider newest events first
    fields = sorted(glob.glob(os.path.join(options.base, '*.fields')), reverse=True)

    comm = None
    Npointings = 0

    # Connect to script master
    comm = scriptcomm.Rts2Comm()
    telescope = comm.getDeviceByType(scriptcomm.DEVICE_TELESCOPE)

    lon = comm.getValueFloat('LONGITUD', device=telescope)
    lat = comm.getValueFloat('LATITUDE', device=telescope)
    alt = comm.getValueFloat('ALTITUDE', device=telescope)
    obs = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=alt*u.m)

    # Night start/end
    t_night_1,t_night_2 = comm.getValueFloat('night_beginning', device='centrald'), comm.getValueFloat('night_ending', device='centrald')
    if t_night_2 < t_night_1:
        t_night_1 -= 3600*24

    # Now
    time0 = Time.now()

    horizon = get_horizon(min_alt=10)

    # Process all plans
    for fieldsname in fields:
        planname = fieldsname.replace('.fields', '.json')
        with open(planname, 'r') as f:
            plan = json.load(f)
        fields = Table.read(fieldsname, format='ascii.commented_header')

        comm.log('I', 'Loaded GRANDMA plan with', len(fields['ra']), 'grid pointings for event', plan['event_name'])
        comm.log('I', 'Will consider no more than', options.npointings-Npointings, 'pointings from it')

        # Init some RTS2 values
        comm.setValue('exposure', options.exposure)
        comm.setValue('FILTER', options.filter)
        comm.setValue('SHUTTER', 'LIGHT')

        # Visibility checking utils
        def is_visible(ra, dec):
            obj = SkyCoord(ra, dec, unit='deg')
            altaz = obj.transform_to(AltAz(obstime=time0, location=obs))
            min_alt = horizon(altaz.az.deg)

            return altaz.alt.deg > min_alt

        def is_visible_tonight(ra, dec):
            obj = SkyCoord(ra, dec, unit='deg')

            t = np.linspace(t_night_1, t_night_2, num=10)
            nt = Time(t, format='unix')
            altaz = obj.transform_to(AltAz(obstime=nt, location=obs))
            min_alt = horizon(altaz.az.deg)

            return np.any(altaz.alt.deg > min_alt)

        aidx = np.argsort(-fields['weight'])
        mask = np.ones_like(fields['ra'], dtype=np.bool)

        for i in aidx:
            ra,dec,gid,weight = fields['ra'][i],fields['dec'][i],fields['id'][i],fields['weight'][i]
            # status,revision = fields['Event_status'],fields['Revision']
            should_sync = False

            if is_visible(ra, dec):
                comm.log('I', 'Pointing to GRANDMA event', plan['event_name'], 'grid point', gid, 'with weight', weight, 'at', ra, dec)

                try:
                    comm.radec(ra, dec)
                    comm.waitTargetMove()
                except scriptcomm.Rts2Exception:
                    import traceback
                    traceback.print_exc()

                    comm.log('E', 'repointing error, moving to next GRANDMA pointing')
                    continue

                comm.setOwnValue('OBJECT', 'GRANDMA_%s_%d' % (plan['event_name'], gid))

                for _ in xrange(options.nframes):
                    try:
                        img = comm.exposure()

                        if img is not None:
                            comm.process(img)
                    except scriptcomm.Rts2Exception:
                        import traceback
                        traceback.print_exc()

                        comm.log('E', 'exposure error')

                mask[i] = False
                Npointings += 1
                should_sync = True

            elif not is_visible_tonight(ra, dec):
                comm.log('I', 'Pointing', gid, 'of GRANDMA event', plan['event_name'], 'with weight', weight, 'at', ra, dec, 'is not observable tonight, removing it')
                mask[i] = False
                should_sync = True

            else:
                comm.log('I', 'Pointing', gid, 'of GRANDMA event', plan['event_id'], 'with weight', weight, 'at', ra, dec, 'is not visible, but observable tonight, skipping it')

            if should_sync:
                # Sync
                tfields = fields[mask].copy()

                if len(tfields) > 0:
                    tfields.write(fieldsname, format='ascii.commented_header', overwrite=True)
                    comm.log('I', 'GRANDMA pointings left for event', plan['event_name'], ':', len(tfields))
                else:
                    os.unlink(fieldsname)
                    comm.log('I', 'All GRANDMA pointings for event', plan['event_name'], 'observed, removing its plan')

            if Npointings >= options.npointings:
                break

        if Npointings >= options.npointings:
            comm.log('I', 'Visited', Npointings, 'GRANDMA pointings, stopping for now')
            break

    if Npointings == 0:
        # Workaround for a bug in RTS2
        # comm.setValue('exposure', 0)
        # comm.exposure()
        pass

    if len(glob.glob(os.path.join(options.base, '*.fields'))) == 0:
        if comm:
            comm.log('I', 'No more GRANDMA plans, disabling the target')
            comm.targetDisable()

# Local Variables:
# tab-width: 4
# python-indent-offset: 4
# indent-tabs-mode: t
# End:

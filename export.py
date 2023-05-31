#!/usr/bin/env python3

from __future__ import absolute_import, division, print_function, unicode_literals

import os, sys, glob

from astropy.wcs import WCS
from astropy.io import fits
from astropy.time import Time

import numpy as np

from fram.fram import Fram
from fram import calibrate

if __name__ == '__main__':
    from optparse import OptionParser

    basedir = os.path.expanduser('~/fram/') # os.path.dirname(__file__)

    parser = OptionParser(usage="usage: %prog [options] from to")
    parser.add_option('-d', '--db', help='Database name', action='store', dest='db', type='str', default='fram')
    parser.add_option('-H', '--host', help='Database host', action='store', dest='dbhost', type='str', default=None)
    parser.add_option('-o', '--out', help='Output directory', action='store', dest='outdir', type='str', default='output')
    parser.add_option('-n', '--obs-name', help='Observer name', action='store', dest='obsname', type='str', default='Karpov')
    parser.add_option('-r', '--replace', help='Replace existing files', action='store_true', dest='replace', default=False)
    parser.add_option('-v', '--verbose', help='Verbose', action='store_true', dest='verbose', default=False)

    (options,files) = parser.parse_args()

    fram = None

    for filename in files:
        header = fits.getheader(filename)

        name = header.get('OBJECT')

        if name.startswith('GRANDMA'):
            s = name.split('_')
            event_name = s[1]
            tile_id = int(s[2])
        else:
            continue

        fname = header.get('FILTER', 'Unknown')
        exposure = header.get('EXPOSURE')
        nstacked = 1

        ra,dec = header.get('TELRA'), header.get('TELDEC')

        if 'BART' in header.get('INSTRUME'):
            telname = 'FRAM-CTA-N'
        else:
            telname = 'FRAM-Auger'

        utctime = Time(header['DATE-OBS']).strftime('%Y-%m-%dT%H-%M-%S')

        outname = '_'.join([event_name,
                            options.obsname,
                            telname,
                            utctime,
                            fname,
                            'STACK' if nstacked>1 else 'UNSTACK',
                            str(nstacked)+'x'+str(int(exposure))+'s',
                            ('%03.6f' % ra).replace('.', '-'),
                            ('%03.6f' % dec).replace('.', '-')
                            ]) + '.fits'

        outdir = os.path.join(options.outdir, event_name)
        outname = os.path.join(outdir, outname)

        if os.path.exists(outname) and not options.replace:
            print(filename, 'already exported')
            continue

        # Modify the header
        header['USERNAME'] = options.obsname
        header['INSTRU'] = telname
        header['OBSDATE'] = header['DATE-OBS']
        header['TARGET'] = event_name
        header['TILEID'] = tile_id
        header['STACK'] = int(nstacked > 1)

        print(filename, '->', outname)

        try:
            os.makedirs(outdir)
        except:
            pass

        # Actual processing
        image = fits.getdata(filename)

        if fram is None:
            fram = Fram(dbname=options.db, dbhost=options.dbhost)

        #### Basic calibration
        darkname = fram.find_image('masterdark', header=header, debug=False)
        flatname = fram.find_image('masterflat', header=header, debug=False)

        if options.verbose:
            print('Dark:', darkname)
            print('Flat:', flatname)

        if darkname:
            dark = fits.getdata(basedir + '/' + darkname)
        else:
            dcname = fram.find_image('dcurrent', header=header, debug=False)
            biasname = fram.find_image('bias', header=header, debug=False)
            if dcname and biasname:
                bias = fits.getdata(basedir + '/' + biasname)
                dc = fits.getdata(basedir + '/' + dcname)

                dark = bias + header['EXPOSURE']*dc
            else:
                dark = None

        image,header = calibrate.calibrate(image, header, dark=dark)

        if flatname:
            flat = fits.getdata(basedir + '/' + flatname)

            image *= np.nanmedian(flat)/flat

        fits.writeto(outname, image, header, overwrite=True)

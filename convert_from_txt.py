#!/usr/bin/env python3

import os, sys, glob, time
from astropy.table import Table

if __name__ == '__main__':
    from optparse import OptionParser

    parser = OptionParser(usage="usage: %prog [options] arg")

    (options,args) = parser.parse_args()

    for filename in args:
        print("Processing", filename)

        data = Table.read(filename, format='ascii.no_header', data_start=1, delimiter=' ', names=['rank_id', 'id', 'ra', 'dec', 'weight', 'date', 'time'])
        data['filt'] = 'R'
        data['exposure_time'] = 120
        data.remove_columns(['rank_id', 'date', 'time'])
        data.meta = {}

        outname = os.path.splitext(filename)[0] + '.fields'
        print(" ->", outname)

        data.write(outname, format='ascii.commented_header', overwrite=True)

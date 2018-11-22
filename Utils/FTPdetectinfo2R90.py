# RPi Meteor Station
# Copyright (C) 2018  Alfredo Dal'Ava Júnior <alfredo.dalava@gmail.com>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# TODO complete this feature
# TODO take station coordinates data from RMS config file or similar

import sys
import csv
import re
import argparse

import FTPdetectinfo

# Test
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Converts RMS data file to format R90')
    parser.add_argument('file')
                    

    args = parser.parse_args()
    argment_file = args.file
    print('Parsing: {}'.format(argment_file))
    
    #sys.exit(0)

    # meteor_list = [["FF453_20160419_184117_248_0020992.bin", 1, 271.953268044, 8.13010235416,
    # [[ 124.5      ,   665.44095949,  235.00000979,  101.        ],
    #  [ 128.       ,   665.60121632,  235.9999914 ,  119.        ],
    #  [ 137.5      ,   666.54497978,  237.00000934,  195.        ],
    #  [ 151.5      ,   664.52378186,  238.99999005,  120.        ],
    #  [ 152.5      ,   666.        ,  239.        ,  47.        ]]]]

    # file_name = 'FTPdetect_test.txt'
    # ff_directory = 'here'
    # cal_directory = 'there'
    # cam_code = 450
    # fps = 25

    # writeFTPdetectinfo(meteor_list, ff_directory, file_name, cal_directory, cam_code, fps)

    lat = -21.79656
    lon = -46.57263
    altitude = 1249

    #dir_path = "/home/tbyte/src/az_ev/data/BR0003_20180820_211539_072741_detected"
    
    dir_path = '.'
    #file_name = "FTPdetectinfo_BR0003_20180820_211539_072741.txt"

    file_name = argment_file

    meteor_list = FTPdetectinfo.readFTPdetectinfo(dir_path, file_name)

    #print(meteor_list[0])
    R90_fields = [ 'Ver', 'Y', 'M', 'D', 'h', 'm', 's', 'Mag', 'Dur', 'Az1', 'Alt1', 
                   'Az2', 'Alt2', 'Ra1', 'Dec1', 'Ra2', 'Dec2', 'ID',
                   'Long', 'Lat', 'Alt', 'Tz' ]

    for meteor in meteor_list:
        # Unpack the meteor data
        #ff_name, meteor_No, rho, theta, centroids = meteor
        
        
        print(meteor)
        FFfile, cam_code, meteor_No, n_segments, fps, hnr, mle, binn, px_fm, rho, phi, frames_data = meteor

        year, month, day, hour, min, sec = re.match(r'FF_\w+_(\d\d\d\d)(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)_\d\d\d_\w+.fits', FFfile).groups()

        csv_filename = 'R90_{}.csv'.format(FFfile)

        with open(csv_filename, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=R90_fields)

            calib_status, frame_n, x, y, ra, dec, azim, elev, inten, mag = frames_data[0]
            calib_status2, frame_n2, x2, y2, ra2, dec2, azim2, elev2, inten2, mag2 = frames_data[int(n_segments)-1]

            # find max magnitude value
            max_mag = mag
            for frame in frames_data:
                calib_status, frame_n, x, y, ra, dec, azim, elev, inten, mag = frame
                if mag < max_mag:
                    max_mag = mag

            dur = (1/fps) * n_segments
            row = { 
                    'Ver' : 'R90',
                    'Y' : year,
                    'M' : month,
                    'D' : day,
                    'h' : hour,
                    'm' : min,
                    's' : sec,
                    'Mag' : max_mag, 
                    'Dur' : dur,
                    'Az1' : 999.9 ,
                    'Alt1' : 999.9 , 
                    'Az2' : 999.9 ,
                    'Alt2' : 999.9 ,
                    'Ra1' : ra,
                    'Dec1' : dec,
                    'Ra2' : ra2,
                    'Dec2' : dec2,
                    'ID' : cam_code,
                    'Long' : lon,
                    'Lat' : lat,
                    'Alt' : altitude,
                    'Tz' : 0            
                   }

            writer.writeheader()
            writer.writerow(row)
        


        print('-----')
    

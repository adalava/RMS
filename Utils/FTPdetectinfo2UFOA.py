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

# TODO complete feature

import FTPdetectinfo
from bs4 import BeautifulSoup

import copy

# Test
if __name__ == '__main__':
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


    dir_path = "/home/tbyte/src/az_ev/data/BR0003_20180820_211539_072741_detected"
    file_name = "FTPdetectinfo_BR0003_20180820_211539_072741.txt"

    template_file = "FTPdetectinfo2UFOA-XMLTemplate.xml"

    meteor_list = FTPdetectinfo.readFTPdetectinfo(dir_path, file_name)

    #print(meteor_list[0])


    for meteor in meteor_list:
        # Unpack the meteor data
        #ff_name, meteor_No, rho, theta, centroids = meteor
        print(meteor)
        FFfile, cam_code, meteor_No, n_segments, fps, hnr, mle, binn, px_fm, rho, phi, frames_data = meteor

        fp = open(template_file)
        soup = BeautifulSoup(fp, "xml")

        ufoanalyzer_record = soup.ufoanalyzer_record 

        ufoanalyzer_record['clip_name'] = FFfile
        ufoanalyzer_record['fps'] = fps
        ufoanalyzer_record['lid'] = cam_code

        objs = ufoanalyzer_record.ua2_objects
        obj = objs.ua2_object
        objpath = obj.ua2_objpath
        
        f_data_template = copy.copy(objpath.ua2_fdata2)
        objpath.clear()

        for frame in frames_data:
            calib_status, frame_n, x, y, ra, dec, azim, elev, inten, mag = frame
            fdata = copy.copy(f_data_template)

            fdata['fno'] = int(frame_n)
            fdata['ra'] = ra
            fdata['dec'] = dec
            fdata['mag'] = mag


            objpath.append(fdata)
            print(frame_n)

        print('-----')
        print(soup.prettify())
        print('-----')
    

#<?xml version="1.0" encoding="UTF-8" ?>
#<ufoanalyzer_record ....>
#	<ua2_objects>
#        <ua2_object .....>
#        	<ua2_objpath>
#                <ua2_fdata2 ...></ua2_fdata2>
#                <ua2_fdata2 ...></ua2_fdata2>
#            </ua2_objpath>
#        </ua2_object>
#    </ua2_objects>
#</ufoanalyzer_record>

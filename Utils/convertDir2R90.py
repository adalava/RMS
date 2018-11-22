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

import os

if not os.path.exists('tmp'):
    os.mkdir('tmp')

#for file in os.listdir():
#    if file.endswith(".bz2"):
#        print(os.path.join(file))
#        os.system('tar -xvf {} -C tmp --wildcards "*/FTPdetectinfo_*txt"'.format(file))


for file in os.listdir('tmp'):
    if file.endswith(".txt"):
        full_path = os.path.join('tmp', file)
        #os.system('tar -xvf {} -C tmp --wildcards "*/FTPdetectinfo_*txt"'.format(file))

        os.system('python ~/src/RMS/Utils/FTPdetectinfo2R90.py {}'.format(full_path))

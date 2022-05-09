""" Setting up the logger. """

# RPi Meteor Station
# Copyright (C) 2017 Denis Vida
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

import os
import sys
import logging
import logging.handlers
import datetime

from sympy import false, true

from RMS.Misc import mkdirP

class Logger(object):
    _instance = None
    _log = None
    _config = None
    _initialized = false
    DEBUG = logging.DEBUG

    #def instance(cls, config = None):
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)

        return cls._instance

    def initLogging(self, config, log_file_prefix=""):
        """ Initializes the logger. 
        
        Arguments:
            log_file_prefix: [str] String which will be prefixed to the log file. Empty string by default.

        """

        # Init logging
        log = logging.getLogger()
        log.setLevel(logging.INFO)
        log.setLevel(logging.DEBUG)


        # Path to the directory with log files
        log_path = os.path.join(config.data_dir, config.log_dir)

        # Make directories
        mkdirP(config.data_dir)
        mkdirP(log_path)

        # Generate a file name for the log file
        log_file_name = log_file_prefix + "log_" + str(config.stationID) + "_" + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S.%f') + ".log"
        
        '''
        # Make a new log file each day
        handler = logging.handlers.TimedRotatingFileHandler(os.path.join(log_path, log_file_name), when='D', \
            interval=1) 
        handler.setLevel(logging.INFO)
        handler.setLevel(logging.DEBUG)

        # Set the log formatting
        formatter = logging.Formatter(fmt='%(asctime)s-%(levelname)s-%(module)s-line:%(lineno)d - %(message)s', 
            datefmt='%Y/%m/%d %H:%M:%S')
        handler.setFormatter(formatter)
        log.addHandler(handler)
        '''

        # Stream all logs to stdout as well
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter(fmt='%(asctime)s-%(levelname)s-%(module)s-line:%(lineno)d - %(message)s', 
            datefmt='%Y/%m/%d %H:%M:%S')
        ch.setFormatter(formatter)
        log.addHandler(ch)

        # send log through sockets
        socket_handler = logging.handlers.SocketHandler('localhost', 9020)
        socket_handler.setLevel(logging.INFO)
        socket_handler.setLevel(logging.DEBUG)
        log.addHandler(socket_handler)

        self._initialized = true
        

        return log

    def getLogger(self):
        # in order to keep looging behavior, just return the logging object if consig is not set
#        print(self._config)

        #if self._config == None:
        #    raise RuntimeError('Call instance() instead')

        #if self._initialized == false:
        #    self.initLogging()

        return logging.getLogger()


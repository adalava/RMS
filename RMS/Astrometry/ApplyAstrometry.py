""" This module contains procedures for applying astrometry and field corrections to meteor data.
"""

# The MIT License

# Copyright (c) 2016 Denis Vida

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import print_function, division, absolute_import

import os
import sys
import math
import datetime
import shutil
import copy

import numpy as np
import scipy.optimize

from RMS.Astrometry.Conversions import date2JD, datetime2JD, jd2Date
from RMS.Astrometry.AtmosphericExtinction import atmosphericExtinctionCorrection
import RMS.Formats.Platepar
from RMS.Formats.FTPdetectinfo import readFTPdetectinfo, writeFTPdetectinfo
from RMS.Formats.FFfile import filenameToDatetime
from RMS.Math import angularSeparation

# Import Cython functions
import pyximport
pyximport.install(setup_args={'include_dirs':[np.get_include()]})
from RMS.Astrometry.CyFunctions import cyRaDecToCorrectedXY, cyXYToRADec


def photomLine(lsp, photom_offset):
    """ Line used for photometry, the slope is fixed to -2.5, only the photometric offset is given. 
    
    Arguments:
        lsp: [float] LogSum Pixel - logarith of the sum of pixel intensities.
        photom_offset: [float] The photometric offet.

    Return: 
        [float] Magnitude.
    """
    
    # The slope is fixed to -2.5, coming from the definition of magnitude
    return -2.5*lsp + photom_offset


def photometryFit(logsum_px, catalog_mags):
    """ Fit the photometry on given data. 
    
    Arguments:
        logsum_px: [list] A list of log sum pixel values (logarithms of sums of pixel intensities).
        catalog_mags: [list] A list of corresponding catalog magnitudes of stars.

    Return:
        (photom_offset, fit_stddev, fit_resid):
            photom_offset: [float] The photometric offset.
            fit_stddev: [float] The standard deviation of the fit.
            fit_resid: [float] Magnitude fit residuals.
    """

    # Fit a line to the star data, where only the intercept has to be estimated
    photom_params, _ = scipy.optimize.curve_fit(photomLine, logsum_px, catalog_mags, \
        method='trf', loss='soft_l1')

    # Calculate the standard deviation
    fit_resids = np.array(catalog_mags) - photomLine(np.array(logsum_px), *photom_params)
    fit_stddev = np.std(fit_resids)

    return photom_params[0], fit_stddev, fit_resids


def computeFOVSize(platepar):
    """ Computes the size of the FOV in deg from the given platepar. 
        
    Arguments:
        platepar: [Platepar instance]

    Return:
        fov_h: [float] Horizontal FOV in degrees.
        fov_v: [float] Vertical FOV in degrees.
    """

    # Construct poinits on the middle of every side of the image
    time_data = np.array(4*[jd2Date(platepar.JD)])
    x_data = np.array([0, platepar.X_res, platepar.X_res/2, platepar.X_res/2])
    y_data = np.array([platepar.Y_res/2, platepar.Y_res/2, 0, platepar.Y_res])
    level_data = np.ones(4)

    # Compute RA/Dec of the points
    _, ra_data, dec_data, _ = XY2CorrectedRADecPP(time_data, x_data, y_data, level_data, platepar)

    ra1, ra2, ra3, ra4 = ra_data
    dec1, dec2, dec3, dec4 = dec_data

    # Compute horizontal FOV
    fov_h = np.degrees(angularSeparation(np.radians(ra1), np.radians(dec1), np.radians(ra2), \
        np.radians(dec2)))

    # Compute vertical FOV
    fov_v = np.degrees(angularSeparation(np.radians(ra3), np.radians(dec3), np.radians(ra4), \
        np.radians(dec4)))


    return fov_h, fov_v



# def rotationWrtHorizon(platepar):
#     """ Given the platepar, compute the rotation of the FOV with respect to the horizon. 
    
#     Arguments:
#         pletepar: [Platepar object] Input platepar.

#     Return:
#         rot_angle: [float] Rotation w.r.t. horizon (degrees).
#     """

#     # Image coordiantes of the center
#     img_mid_w = platepar.X_res/2
#     img_mid_h = platepar.Y_res/2

#     # Image coordinate slighty up of the center
#     img_up_w = img_mid_w
#     img_up_h = img_mid_h - 10

#     # Compute alt/az
#     azim, alt = XY2altAz([img_mid_w, img_up_w], [img_mid_h, img_up_h], platepar.lat, platepar.lon, platepar.RA_d, \
#         platepar.dec_d, platepar.Ho, platepar.X_res, platepar.Y_res, platepar.pos_angle_ref, \
#         platepar.F_scale, platepar.x_poly_fwd, platepar.y_poly_fwd)
#     azim_mid = azim[0]
#     alt_mid = alt[0]
#     azim_up = azim[1]
#     alt_up = alt[1]

#     # Compute the rotation wrt horizon (deg)    
#     rot_angle = -np.degrees(np.arctan2(np.radians(alt_up) - np.radians(alt_mid), \
#         np.radians(azim_up) - np.radians(azim_mid))) + 90

#     # Wrap output to <-180, 180] range
#     if rot_angle > 180:
#         rot_angle -= 360

#     return rot_angle


def rotationWrtHorizon(platepar):
    """ Given the platepar, compute the rotation of the FOV with respect to the horizon. 
    
    Arguments:
        pletepar: [Platepar object] Input platepar.

    Return:
        rot_angle: [float] Rotation w.r.t. horizon (degrees).
    """

    # Image coordiantes of the center
    img_mid_w = platepar.X_res/2
    img_mid_h = platepar.Y_res/2

    # Image coordinate slighty right of the center (horizontal)
    img_up_w = img_mid_w + 10
    img_up_h = img_mid_h

    # Compute alt/az
    azim, alt = XY2altAz([img_mid_w, img_up_w], [img_mid_h, img_up_h], platepar.lat, platepar.lon, platepar.RA_d, \
        platepar.dec_d, platepar.Ho, platepar.X_res, platepar.Y_res, platepar.pos_angle_ref, \
        platepar.F_scale, platepar.x_poly_fwd, platepar.y_poly_fwd)
    azim_mid = azim[0]
    alt_mid = alt[0]
    azim_up = azim[1]
    alt_up = alt[1]

    # Compute the rotation wrt horizon (deg)    
    rot_angle = np.degrees(np.arctan2(np.radians(alt_up) - np.radians(alt_mid), \
        np.radians(azim_up) - np.radians(azim_mid)))

    # Wrap output to <-180, 180] range
    if rot_angle > 180:
        rot_angle -= 360

    return rot_angle



def rotationWrtHorizonToPosAngle(platepar, rot_angle):
    """ Given the rotation angle w.r.t horizon, numerically compute the position angle. 
    
    Arguments:
        pletepar: [Platepar object] Input platepar.
        rot_angle: [float] The rotation angle w.r.t. horizon (deg)>

    Return:
        pos_angle: [float] Position angle (deg).

    """

    platepar = copy.deepcopy(platepar)
    rot_angle = rot_angle%360


    def _rotAngleResidual(params, rot_angle):

        # Set the given position angle to the platepar
        platepar.pos_angle_ref = params[0]

        # Compute the rotation angle with the given guess of the position angle
        rot_angle_computed = rotationWrtHorizon(platepar)%360

        # Compute the deviation between computed and desired angle
        return 180 - abs(abs(rot_angle - rot_angle_computed) - 180)



    # Numerically find the position angle
    res = scipy.optimize.minimize(_rotAngleResidual, [platepar.pos_angle_ref], args=(rot_angle), \
        method='Nelder-Mead')


    return res.x[0]%360




def rotationWrtStandard(platepar):
    """ Given the platepar, compute the rotation from the celestial meridian passing through the centre of 
        the FOV.
    
    Arguments:
        pletepar: [Platepar object] Input platepar.

    Return:
        rot_angle: [float] Rotation from the meridian (degrees).
    """

    # Image coordiantes of the center
    img_mid_w = platepar.X_res/2
    img_mid_h = platepar.Y_res/2

    # Image coordinate slighty right of the centre
    img_up_w = img_mid_w + 10
    img_up_h = img_mid_h

    # Compute ra/dec
    _, ra, dec, _ = XY2CorrectedRADecPP(2*[jd2Date(platepar.JD)], [img_mid_w, img_up_w], [img_mid_h, img_up_h], \
        2*[1], platepar)
    ra_mid = ra[0]
    dec_mid = dec[0]
    ra_up = ra[1]
    dec_up = dec[1]

    # Compute the equatorial orientation
    rot_angle = np.degrees(np.arctan2(np.radians(dec_mid) - np.radians(dec_up), \
        np.radians(ra_mid) - np.radians(ra_up)))

    # Wrap output to 0-360 range
    rot_angle = rot_angle%360

    return rot_angle




def rotationWrtStandardToPosAngle(platepar, rot_angle):
    """ Given the rotation angle w.r.t horizon, numerically compute the position angle. 
    
    Arguments:
        pletepar: [Platepar object] Input platepar.
        rot_angle: [float] The rotation angle w.r.t. horizon (deg)>

    Return:
        pos_angle: [float] Position angle (deg).

    """

    platepar = copy.deepcopy(platepar)
    rot_angle = rot_angle%360


    def _rotAngleResidual(params, rot_angle):

        # Set the given position angle to the platepar
        platepar.pos_angle_ref = params[0]

        # Compute the rotation angle with the given guess of the position angle
        rot_angle_computed = rotationWrtStandard(platepar)%360

        # Compute the deviation between computed and desired angle
        return 180 - abs(abs(rot_angle - rot_angle_computed) - 180)



    # Numerically find the position angle
    res = scipy.optimize.minimize(_rotAngleResidual, [platepar.pos_angle_ref], args=(rot_angle), \
        method='Nelder-Mead')


    return res.x[0]%360



def raDec2AltAz(JD, lon, lat, ra, dec):
    """ Calculate the reference azimuth and altitude of the centre of the FOV from the given RA/Dec. 

    Arguments:
        JD: [float] Reference Julian date.
        lon: [float] Longitude +E in degrees.
        lat: [float] Latitude +N in degrees.
        ra_: [float] Right ascension in degrees.
        dec: [float] Declination in degrees.

    Return:
        (azim, elev): [tuple of float]: Azimuth and elevation (degrees).
    """

    # Compute the LST (local sidereal time)
    T = (JD - 2451545)/36525.0
    lst = (280.46061837 + 360.98564736629*(JD - 2451545.0) + 0.000387933*T**2 - (T**3)/38710000)%360
    lst = lst + lon

    # Convert all values to radians
    lst = np.radians(lst)
    lat = np.radians(lat)    
    ra = np.radians(ra)
    dec = np.radians(dec)

    # Calculate the hour angle
    ha = lst - ra

    # Constrain the hour angle to [-pi, pi] range
    ha = (ha + np.pi)%(2*np.pi) - np.pi

    # Calculate the azimuth
    azim = np.pi + np.arctan2(np.sin(ha), np.cos(ha)*np.sin(lat) - np.tan(dec)*np.cos(lat))

    # Calculate the sine of elevation
    sin_elev = np.sin(lat)*np.sin(dec) + np.cos(lat)*np.cos(dec)*np.cos(ha)

    # Wrap the sine of elevation in the [-1, +1] range
    sin_elev = (sin_elev + 1)%2 - 1

    elev = np.arcsin(sin_elev)
    

    # Convert alt/az to degrees
    azim = np.degrees(azim)
    elev = np.degrees(elev)

    return azim, elev



def applyFieldCorrection(x_poly_fwd, y_poly_fwd, X_res, Y_res, F_scale, X_data, Y_data):
    """ Apply field correction and vignetting correction to all given image points. 
`
    Arguments:
        x_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward X axis polynomial parameters.
        y_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward Y axis polynomial parameters.
        X_res: [int] Image size, X dimension (px).
        Y_res: [int] Image size, Y dimenstion (px).
        F_scale: [float] Sum of image scales per each image axis (px/deg).
        X_data: [ndarray] 1D float numpy array containing X component of the detection point.
        Y_data: [ndarray] 1D float numpy array containing Y component of the detection point.
    
    Return:
        (X_corrected, Y_corrected, levels_corrected): [tuple of ndarrays]
            X_corrected: 1D numpy array containing distortion corrected X component.
            Y_corrected: 1D numpy array containing distortion corrected Y component.
            
    """

    # Initialize final values containers
    X_corrected = np.zeros_like(X_data, dtype=np.float64)
    Y_corrected = np.zeros_like(Y_data, dtype=np.float64)

    i = 0

    data_matrix = np.vstack((X_data, Y_data)).T

    # Go through all given data points
    for Xdet, Ydet in data_matrix:

        Xdet = Xdet - X_res/2.0
        Ydet = Ydet - Y_res/2.0

        dX = (x_poly_fwd[0]
            + x_poly_fwd[1]*Xdet
            + x_poly_fwd[2]*Ydet
            + x_poly_fwd[3]*Xdet**2
            + x_poly_fwd[4]*Xdet*Ydet
            + x_poly_fwd[5]*Ydet**2
            + x_poly_fwd[6]*Xdet**3
            + x_poly_fwd[7]*Xdet**2*Ydet
            + x_poly_fwd[8]*Xdet*Ydet**2
            + x_poly_fwd[9]*Ydet**3
            + x_poly_fwd[10]*Xdet*np.sqrt(Xdet**2 + Ydet**2)
            + x_poly_fwd[11]*Ydet*np.sqrt(Xdet**2 + Ydet**2))

        # Add the distortion correction
        X_pix = Xdet + dX

        dY = (y_poly_fwd[0]
            + y_poly_fwd[1]*Xdet
            + y_poly_fwd[2]*Ydet
            + y_poly_fwd[3]*Xdet**2
            + y_poly_fwd[4]*Xdet*Ydet
            + y_poly_fwd[5]*Ydet**2
            + y_poly_fwd[6]*Xdet**3
            + y_poly_fwd[7]*Xdet**2*Ydet
            + y_poly_fwd[8]*Xdet*Ydet**2
            + y_poly_fwd[9]*Ydet**3
            + y_poly_fwd[10]*Ydet*np.sqrt(Xdet**2 + Ydet**2)
            + y_poly_fwd[11]*Xdet*np.sqrt(Xdet**2 + Ydet**2))

        # Add the distortion correction
        Y_pix = Ydet + dY

        # Scale back image coordinates
        X_pix = X_pix/F_scale
        Y_pix = Y_pix/F_scale

        # Store values to final arrays
        X_corrected[i] = X_pix
        Y_corrected[i] = Y_pix

        i += 1

    return X_corrected, Y_corrected



def XY2altAz(X_data, Y_data, lat, lon, RA_d, dec_d, Ho, X_res, Y_res, pos_angle_ref, F_scale, x_poly_fwd, \
    y_poly_fwd):
    """ Convert image coordinates (X, Y) to celestial altitude and azimuth. 
    
    Arguments:
        X_data: [ndarray] 1D numpy array containing the image pixel column.
        Y_data: [ndarray] 1D numpy array containing the image pixel row.
        lat: [float] Latitude of the observer +N (degrees).
        lon: [float] Longitde of the observer +E (degress).
        RA_d: [float] Reference right ascension of the image centre (degrees).
        dec_d: [float] Reference declination of the image centre (degrees).
        Ho: [float] Reference hour angle.
        X_res: [int] Image size, X dimension (px).
        Y_res: [int] Image size, Y dimenstion (px).
        pos_angle_ref: [float] Field rotation parameter (degrees).
        F_scale: [float] Sum of image scales per each image axis (px/deg).
        x_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward X axis polynomial parameters.
        y_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward Y axis polynomial parameters.
        
    
    Return:
        (azimuth_data, altitude_data): [tuple of ndarrays]
            azimuth_data: [ndarray] 1D numpy array containing the azimuth of each data point (degrees).
            altitude_data: [ndarray] 1D numyp array containing the altitude of each data point (degrees).
    """


    # Apply distorsion correction
    X_corrected, Y_corrected = applyFieldCorrection(x_poly_fwd, y_poly_fwd, X_res, Y_res, F_scale, X_data, \
        Y_data)

    # Initialize final values containers
    az_data = np.zeros_like(X_corrected, dtype=np.float64)
    alt_data = np.zeros_like(X_corrected, dtype=np.float64)

    # Convert declination to radians
    dec_rad = math.radians(dec_d)

    # Precalculate some parameters
    sl = math.sin(math.radians(lat))
    cl = math.cos(math.radians(lat))

    i = 0
    data_matrix = np.vstack((X_corrected, Y_corrected)).T

    # Go through all given data points
    for X_pix, Y_pix in data_matrix:

        # Caulucate the needed parameters
        radius = math.radians(np.sqrt(X_pix**2 + Y_pix**2))
        theta = math.radians((90 - pos_angle_ref + math.degrees(math.atan2(Y_pix, X_pix)))%360)

        sin_t = math.sin(dec_rad)*math.cos(radius) + math.cos(dec_rad)*math.sin(radius)*math.cos(theta)
        Dec0det = math.atan2(sin_t, math.sqrt(1 - sin_t**2))

        sin_t = math.sin(theta)*math.sin(radius)/math.cos(Dec0det)
        cos_t = (math.cos(radius) - math.sin(Dec0det)*math.sin(dec_rad))/(math.cos(Dec0det)*math.cos(dec_rad))
        RA0det = (RA_d - math.degrees(math.atan2(sin_t, cos_t)))%360

        h = math.radians(Ho + lon - RA0det)
        sh = math.sin(h)
        sd = math.sin(Dec0det)
        ch = math.cos(h)
        cd = math.cos(Dec0det)

        x = -ch*cd*sl + sd*cl
        y = -sh*cd
        z = ch*cd*cl + sd*sl

        r = math.sqrt(x**2 + y**2)

        # Calculate azimuth and altitude
        azimuth = math.degrees(math.atan2(y, x))%360
        altitude = math.degrees(math.atan2(z, r))

        # Save calculated values to an output array
        az_data[i] = azimuth
        alt_data[i] = altitude
        
        i += 1

    return az_data, alt_data



def altAz2RADec(lat, lon, UT_corr, time_data, azimuth_data, altitude_data, dt_time=False):
    """ Convert the azimuth and altitude in a given time and position on Earth to right ascension and 
        declination. 
    
    Arguments:
        lat: [float] latitude of the observer in degrees
        lon: [float] longitde of the observer in degress
        UT_corr: [float] UT correction in hours (difference from local time to UT)
        time_data: [2D ndarray] numpy array containing time tuples of each data point (year, month, day, 
            hour, minute, second, millisecond)
        azimuth_data: [ndarray] 1D numpy array containing the azimuth of each data point (degrees)
        altitude_data: [ndarray] 1D numpy array containing the altitude of each data point (degrees)

    Keyword arguments:
        dt_time: [bool] If True, datetime objects can be passed for time_data.

    Return: 
        (JD_data, RA_data, dec_data): [tuple of ndarrays]
            JD_data: [ndarray] julian date of each data point
            RA_data: [ndarray] right ascension of each point
            dec_data: [ndarray] declination of each point
    """

    # Initialize final values containers
    JD_data = np.zeros_like(azimuth_data, dtype=np.float64)
    RA_data = np.zeros_like(azimuth_data, dtype=np.float64)
    dec_data = np.zeros_like(azimuth_data, dtype=np.float64)

    # Precalculate some parameters
    sl = math.sin(math.radians(lat))
    cl = math.cos(math.radians(lat))

    i = 0
    data_matrix = np.vstack((azimuth_data, altitude_data)).T

    # Go through all given data points
    for azimuth, altitude in data_matrix:

        if dt_time:
            JD = datetime2JD(time_data[i], UT_corr=-UT_corr)

        else:
            # Extract time
            Y, M, D, h, m, s, ms = time_data[i]
            JD = date2JD(Y, M, D, h, m, s, ms, UT_corr=-UT_corr)

        # Never allow the altitude to be exactly 90 deg due to numerical issues
        if altitude == 90:
            altitude = 89.9999

        # Convert altitude and azimuth to radians
        az_rad = math.radians(azimuth)
        alt_rad = math.radians(altitude)

        saz = math.sin(az_rad)
        salt = math.sin(alt_rad)
        caz = math.cos(az_rad)
        calt = math.cos(alt_rad)

        x = -saz*calt
        y = -caz*sl*calt + salt*cl
        HA = math.degrees(math.atan2(x, y))

        # Calculate the reference hour angle
        
        T = (JD - 2451545.0)/36525.0
        hour_angle = (280.46061837 + 360.98564736629*(JD - 2451545.0) + 0.000387933*T**2 - T**3/38710000.0)%360

        RA = (hour_angle + lon - HA)%360
        dec = math.degrees(math.asin(sl*salt + cl*calt*caz))

        # Save calculated values to an output array
        JD_data[i] = JD
        RA_data[i] = RA
        dec_data[i] = dec

        i += 1

    return JD_data, RA_data, dec_data



def calculateMagnitudes(level_data, mag_0, mag_lev):
    """ Calculate the magnitude of the data points with given magnitude calibration parameters. 
    
    Arguments:
        level_data: [ndarray] Levels of the meteor centroid (arbitrary units).
        mag_0: [float] Magnitude slope (should be -2.5).
        mag_lev: [float] Magnitude intercept, i.e. the photometric offset.

    Return:
        magnitude_data: [ndarray] Apparent magnitude.
    """

    magnitude_data = np.zeros_like(level_data, dtype=np.float64)

    # Go through all levels of a meteor
    for i, level in enumerate(level_data):

        # Save magnitude data to the output array
        magnitude_data[i] = mag_0*np.log10(level) + mag_lev


    return magnitude_data



def XY2CorrectedRADec(time_data, X_data, Y_data, level_data, lat, lon, Ho, X_res, Y_res, RA_d, dec_d, 
    pos_angle_ref, F_scale, mag_0, mag_lev, x_poly_fwd, y_poly_fwd, station_ht):
    """ A function that does the complete calibration and coordinate transformations of a meteor detection.

    First, it applies field distortion on the data, then converts the XY coordinates
    to altitude and azimuth. Then it converts the altitude and azimuth data to right ascension and 
    declination. The resulting coordinates are in J2000.0 epoch.
    
    Arguments:
        time_data: [2D ndarray] Numpy array containing time tuples of each data point (year, month, day, 
            hour, minute, second, millisecond).
        X_data: [ndarray] 1D numpy array containing the image X component.
        Y_data: [ndarray] 1D numpy array containing the image Y component.
        level_data: [ndarray] Levels of the meteor centroid.
        lat: [float] Latitude of the observer in degrees.
        lon: [float] Longitde of the observer in degress.
        Ho: [float] Reference hour angle (deg).
        X_res: [int] Image size, X dimension (px).
        Y_res: [int] Image size, Y dimenstion (px).
        RA_d: [float] Reference right ascension of the image centre (degrees).
        dec_d: [float] Reference declination of the image centre (degrees).
        pos_angle_ref: [float] Field rotation parameter (degrees).
        F_scale: [float] Image scale (px/deg).
        mag_0: [float] Magnitude calibration equation parameter (slope).
        mag_lev: [float] Magnitude calibration equation parameter (intercept).
        x_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward X axis polynomial parameters.
        y_poly_fwd: [ndarray] 1D numpy array of 12 elements containing forward Y axis polynomial parameters.
        station_ht: [float] Height above sea level of the station (m).
    
    Return:
        (JD_data, RA_data, dec_data, magnitude_data): [tuple of ndarrays]
            JD_data: [ndarray] Julian date of each data point.
            RA_data: [ndarray] Right ascension of each point (deg).
            dec_data: [ndarray] Declination of each point (deg).
            magnitude_data: [ndarray] Array of meteor's lightcurve apparent magnitudes.

    """


    # Convert time to Julian date
    JD_data = np.array([date2JD(*time_data_entry) for time_data_entry in time_data])

    # Convert x,y to RA/Dec using a fast cython function
    RA_data, dec_data = cyXYToRADec(JD_data, np.array(X_data), np.array(Y_data), float(lat), float(lon), \
        float(Ho), float(X_res), float(Y_res), float(RA_d), float(dec_d), float(pos_angle_ref), \
        float(F_scale), x_poly_fwd, y_poly_fwd)

    # Calculate magnitudes
    magnitude_data = calculateMagnitudes(level_data, mag_0, mag_lev)

    
    return JD_data, RA_data, dec_data, magnitude_data



    ### CODE BELOW NOT USED !!! #
    ### SLOW PYTHON VERSION OF THE CODE BELOW, HERE FOR LEGACY PURPOSES ###

    # Convert XY image coordinates to azimuth and altitude
    az_data, alt_data = XY2altAz(X_data, Y_data, lat, lon, RA_d, dec_d, Ho, X_res, Y_res, pos_angle_ref, \
        F_scale, x_poly_fwd, y_poly_fwd)

    # Convert azimuth and altitude data to right ascension and declination
    JD_data, RA_data, dec_data = altAz2RADec(lat, lon, 0, time_data, az_data, alt_data)

    # Calculate magnitudes
    magnitude_data = calculateMagnitudes(level_data, mag_0, mag_lev)

    # # Remove all occurances of nans and infs in magnitudes
    # good_mag_indices = ~np.isnan(magnitude_data) & ~np.isinf(magnitude_data)
    # JD_data = JD_data[good_mag_indices]
    # RA_data = RA_data[good_mag_indices]
    # dec_data = dec_data[good_mag_indices]
    # magnitude_data = magnitude_data[good_mag_indices]


    # CURRENTLY DISABLED!
    # Compute the apparent magnitudes corrected to relative atmospheric extinction
    # magnitude_data -= atmosphericExtinctionCorrection(alt_data, station_ht) \
    #   - atmosphericExtinctionCorrection(90, station_ht)


    return JD_data, RA_data, dec_data, magnitude_data

 


def XY2CorrectedRADecPP(time_data, X_data, Y_data, level_data, platepar):
    """ Converts image XY to RA,Dec, but it takes a platepar instead of individual parameters. 
    
    Arguments:
        time_data: [2D ndarray] Numpy array containing time tuples of each data point (year, month, day, 
            hour, minute, second, millisecond).
        X_data: [ndarray] 1D numpy array containing the image X component.
        Y_data: [ndarray] 1D numpy array containing the image Y component.
        level_data: [ndarray] Levels of the meteor centroid.
        platepar: [Platepar structure] Astrometry parameters.


    Return:
        (JD_data, RA_data, dec_data, magnitude_data): [tuple of ndarrays]
            JD_data: [ndarray] Julian date of each data point.
            RA_data: [ndarray] Right ascension of each point (deg).
            dec_data: [ndarray] Declination of each point (deg).
            magnitude_data: [ndarray] Array of meteor's lightcurve apparent magnitudes.
    """


    return XY2CorrectedRADec(time_data, X_data, Y_data, level_data, platepar.lat, \
        platepar.lon, platepar.Ho, platepar.X_res, platepar.Y_res, platepar.RA_d, platepar.dec_d, \
        platepar.pos_angle_ref, platepar.F_scale, platepar.mag_0, platepar.mag_lev, platepar.x_poly_fwd, \
        platepar.y_poly_fwd, platepar.elev)




def raDecToCorrectedXY(RA_data, dec_data, jd, lat, lon, x_res, y_res, RA_d, dec_d, ref_jd, pos_angle_ref, \
    F_scale, x_poly_rev, y_poly_rev, UT_corr=0):
    """ Convert RA, Dec to distorion corrected image coordinates. 

    Arguments:
        RA: [ndarray] Array of right ascensions (degrees).
        dec: [ndarray] Array of declinations (degrees).
        jd: [float] Julian date.
        lat: [float] Latitude of station in degrees.
        lon: [float] Longitude of station in degrees.
        x_res: [int] X resolution of the camera.
        y_res: [int] Y resolution of the camera.
        RA_d: [float] Right ascension of the FOV centre (degrees).
        dec_d: [float] Declination of the FOV centre (degrees).
        ref_jd: [float] Reference Julian date from platepar.
        pos_angle_ref: [float] Rotation from the celestial meridial (degrees).
        F_scale: [float] Image scale (px/deg).
        x_poly_rev: [ndarray float] Distorsion polynomial in X direction for reverse mapping.
        y_poly_rev: [ndarray float] Distorsion polynomail in Y direction for reverse mapping.

    Keyword arguments:
        UT_corr: [float] UT correction (hours).
    
    Return:
        (x, y): [tuple of ndarrays] Image X and Y coordinates.
    """
    
    # Calculate the azimuth and altitude of the FOV centre
    az_centre, alt_centre = raDec2AltAz(ref_jd, lon, lat, RA_d, dec_d)

    # Apply the UT correction
    jd -= UT_corr/24.0

    # Use the cythonized funtion insted of the Python function
    return cyRaDecToCorrectedXY(RA_data, dec_data, jd, lat, lon, x_res, y_res, az_centre, alt_centre, 
        pos_angle_ref, F_scale, x_poly_rev, y_poly_rev)


    ### NOTE
    ### THE CODE BELOW IS GIVEN FOR ARCHIVAL PURPOSES - it is equivalent to the cython code, but slower

    RA_data = np.copy(RA_data)
    dec_data = np.copy(dec_data)

    
    
    # Calculate the reference hour angle
    T = (jd - 2451545.0)/36525.0
    Ho = (280.46061837 + 360.98564736629*(jd - 2451545) + 0.000387933*T**2 - (T**3)/38710000.0)%360

    sl = math.sin(math.radians(lat))
    cl = math.cos(math.radians(lat))

    # Calculate the hour angle
    salt = math.sin(math.radians(alt_centre))
    saz = math.sin(math.radians(az_centre))
    calt = math.cos(math.radians(alt_centre))
    caz = math.cos(math.radians(az_centre))
    x = -saz*calt
    y = -caz*sl*calt + salt*cl
    HA = math.degrees(math.atan2(x, y))

    # Centre of FOV at the given time
    RA_centre = (Ho + lon - HA)%360
    dec_centre = math.degrees(math.asin(sl*salt + cl*calt*caz))

    x_array = np.zeros_like(RA_data)
    y_array = np.zeros_like(RA_data)

    for i, (ra_star, dec_star) in enumerate(zip(RA_data, dec_data)):

        # Gnomonization of star coordinates to image coordinates
        ra_c = math.radians(RA_centre)
        dec_c = math.radians(dec_centre)
        ra_s = math.radians(ra_star)
        dec_s = math.radians(dec_star)

        ad = math.acos(math.sin(dec_c)*math.sin(dec_s) + math.cos(dec_c)*math.cos(dec_s)*math.cos(ra_s - ra_c))
        radius = math.degrees(ad)

        sinA = math.cos(dec_s)*math.sin(ra_s - ra_c)/math.sin(ad)
        cosA = (math.sin(dec_s) - math.sin(dec_c)*math.cos(ad))/(math.cos(dec_c) * math.sin(ad))

        theta = -math.degrees(math.atan2(sinA, cosA))
        theta = theta + pos_angle_ref - 90.0

        # Calculate standard coordinates
        X1 = radius*math.cos(math.radians(theta))*F_scale
        Y1 = radius*math.sin(math.radians(theta))*F_scale

        # Calculate distortion in X direction
        dX = (x_poly_rev[0]
            + x_poly_rev[1]*X1
            + x_poly_rev[2]*Y1
            + x_poly_rev[3]*X1**2
            + x_poly_rev[4]*X1*Y1
            + x_poly_rev[5]*Y1**2
            + x_poly_rev[6]*X1**3
            + x_poly_rev[7]*X1**2*Y1
            + x_poly_rev[8]*X1*Y1**2
            + x_poly_rev[9]*Y1**3
            + x_poly_rev[10]*X1*np.sqrt(X1**2 + Y1**2)
            + x_poly_rev[11]*Y1*np.sqrt(X1**2 + Y1**2))

        # Add the distortion correction and calculate X image coordinates
        Xpix = X1 - dX + x_res/2.0

        # Calculate distortion in Y direction
        dY = (y_poly_rev[0]
            + y_poly_rev[1]*X1
            + y_poly_rev[2]*Y1
            + y_poly_rev[3]*X1**2
            + y_poly_rev[4]*X1*Y1
            + y_poly_rev[5]*Y1**2
            + y_poly_rev[6]*X1**3
            + y_poly_rev[7]*X1**2*Y1
            + y_poly_rev[8]*X1*Y1**2
            + y_poly_rev[9]*Y1**3
            + y_poly_rev[10]*Y1*np.sqrt(X1**2 + Y1**2)
            + y_poly_rev[11]*X1*np.sqrt(X1**2 + Y1**2))

        # Add the distortion correction and calculate Y image coordinates
        Ypix = Y1 - dY + y_res/2.0

        x_array[i] = Xpix
        y_array[i] = Ypix


    return x_array, y_array



def raDecToCorrectedXYPP(RA_data, dec_data, jd, platepar):
    """ Converts RA, Dec to image coordinates, but the platepar is given instead of individual parameters.

    Arguments:
        RA: [ndarray] Array of right ascensions (degrees).
        dec: [ndarray] Array of declinations (degrees).
        jd: [float] Julian date.
        platepar: [Platepar structure] Astrometry parameters.

    Return:
        (x, y): [tuple of ndarrays] Image X and Y coordinates.

    """

    return raDecToCorrectedXY(RA_data, dec_data, jd, platepar.lat, platepar.lon, platepar.X_res, \
        platepar.Y_res, platepar.RA_d, platepar.dec_d, platepar.JD, platepar.pos_angle_ref, \
        platepar.F_scale, platepar.x_poly_rev, platepar.y_poly_rev, UT_corr=platepar.UT_corr)




def applyAstrometryFTPdetectinfo(dir_path, ftp_detectinfo_file, platepar_file, UT_corr=0, platepar=None):
    """ Use the given platepar to calculate the celestial coordinates of detected meteors from a FTPdetectinfo
        file and save the updates values.

    Arguments:
        dir_path: [str] Path to the night.
        ftp_detectinfo_file: [str] Name of the FTPdetectinfo file.
        platepar_file: [str] Name of the platepar file.

    Keyword arguments:
        UT_corr: [float] Difference of time from UTC in hours.
        platepar: [Platepar obj] Loaded platepar. None by default. If given, the platepar file won't be read, 
            but this platepar structure will be used instead.

    Return:
        None
    """

    # Save a copy of the uncalibrated FTPdetectinfo
    ftp_detectinfo_copy = "".join(ftp_detectinfo_file.split('.')[:-1]) + "_uncalibrated.txt"

    # Back up the original FTPdetectinfo, only if a backup does not exist already
    if not os.path.isfile(os.path.join(dir_path, ftp_detectinfo_copy)):
        shutil.copy2(os.path.join(dir_path, ftp_detectinfo_file), os.path.join(dir_path, ftp_detectinfo_copy))

    # Load platepar from file if not given
    if platepar is None:

        # Load the platepar
        platepar = RMS.Formats.Platepar.Platepar()
        platepar.read(os.path.join(dir_path, platepar_file))


    # Load the FTPdetectinfo file
    meteor_data = readFTPdetectinfo(dir_path, ftp_detectinfo_file)

    # List for final meteor data
    meteor_list = []

    # Go through every meteor
    for meteor in meteor_data:

        ff_name, cam_code, meteor_No, n_segments, fps, hnr, mle, binn, px_fm, rho, phi, meteor_meas = meteor

        meteor_meas = np.array(meteor_meas)

        # Remove all entries where levels are equal to or smaller than 0
        level_data = meteor_meas[:, 8]
        meteor_meas = meteor_meas[level_data > 0, :]

        # Extract frame number, x, y, intensity
        frames = meteor_meas[:, 1]
        X_data = meteor_meas[:, 2]
        Y_data = meteor_meas[:, 3]
        level_data = meteor_meas[:, 8]

        # Get the beginning time of the FF file
        time_beg = filenameToDatetime(ff_name)

        # Calculate time data of every point
        time_data = []
        for frame_n in frames:
            t = time_beg + datetime.timedelta(seconds=frame_n/fps)
            time_data.append([t.year, t.month, t.day, t.hour, t.minute, t.second, int(t.microsecond/1000)])



        # Convert image cooredinates to RA and Dec, and do the photometry
        JD_data, RA_data, dec_data, magnitudes = XY2CorrectedRADecPP(np.array(time_data), X_data, Y_data, \
            level_data, platepar)


        # Compute azimuth and altitude of centroids
        az_data = np.zeros_like(RA_data)
        alt_data = np.zeros_like(RA_data)

        for i in range(len(az_data)):

            jd = JD_data[i]
            ra_tmp = RA_data[i]
            dec_tmp = dec_data[i]

            # Alt and az are kept in the J2000 epoch, which is the CAMS standard!
            az_tmp, alt_tmp = raDec2AltAz(jd, platepar.lon, platepar.lat, ra_tmp, dec_tmp)

            az_data[i] = az_tmp
            alt_data[i] = alt_tmp


        # print(ff_name, cam_code, meteor_No, fps)
        # print(X_data, Y_data)
        # print(RA_data, dec_data)
        # print('------------------------------------------')

        # Construct the meteor measurements array
        meteor_picks = np.c_[frames, X_data, Y_data, RA_data, dec_data, az_data, alt_data, level_data, \
            magnitudes]

        # Add the calculated values to the final list
        meteor_list.append([ff_name, meteor_No, rho, phi, meteor_picks])


    # Calibration string to be written to the FTPdetectinfo file
    calib_str = 'Calibrated with RMS on: ' + str(datetime.datetime.utcnow()) + ' UTC'

    # If no meteors were detected, set dummpy parameters
    if len(meteor_list) == 0:
        cam_code = ''
        fps = 0

    # Save the updated FTPdetectinfo
    writeFTPdetectinfo(meteor_list, dir_path, ftp_detectinfo_file, dir_path, cam_code, fps, 
        calibration=calib_str, celestial_coords_given=True)





if __name__ == "__main__":

    # Read the path to the FTPdetectinfo file
    if not len(sys.argv) == 2:
        print("Usage: python -m RMS.Astrometry.ApplyAstrometry /path/to/FTPdetectinfo.txt")
        sys.exit()


    # Extract the directory path
    dir_path, ftp_detectinfo_file = os.path.split(os.path.abspath(sys.argv[1]))

    if not '.txt' in ftp_detectinfo_file:
        print("Usage: python -m RMS.Astrometry.ApplyAstrometry /path/to/FTPdetectinfo.txt")
        print("Please provide the FTPdetectinfo file!")
        sys.exit()

    # Find the platepar file
    platepar_file = None
    for file_name in os.listdir(dir_path):
        if 'platepar' in file_name:
            platepar_file = file_name
            break

    if platepar_file is None:
        print('ERROR! Could not find the platepar file!')
        sys.exit()


    # Apply the astrometry to the given FTPdetectinfo file
    applyAstrometryFTPdetectinfo(dir_path, ftp_detectinfo_file, platepar_file)

    print('Done!')



    # sys.exit()


    # # TEST CONVERSION FUNCTIONS

    # # Load the platepar
    # platepar = RMS.Formats.Platepar.Platepar()
    # platepar.read("/home/dvida/Desktop/HR000A_20181214_170136_990012_detected/platepar_cmn2010.cal")

    # from RMS.Formats.FFfile import getMiddleTimeFF
    # from RMS.Astrometry.Conversions import date2JD, jd2Date
    # time = getMiddleTimeFF('FF_HR000A_20181215_015724_739_0802560.fits', 25)

    # # Convert time to UT
    # #time = jd2Date(date2JD(*time, UT_corr=platepar.UT_corr))

    # # Star
    # star_x = 435.0
    # star_y = 285.0

    # print('Star X, Y:', star_x, star_y)

    # jd, ra_array, dec_array, mag = XY2CorrectedRADecPP(np.array([time, time]), np.array([star_x, 100]), np.array([star_y, 100]), np.array([1, 1]), platepar)

    # print(ra_array, dec_array)
    # ra = ra_array[0]
    # dec = dec_array[0]

    # ra_h = int(ra/15)
    # ra_min = int((ra/15 - ra_h)*60)
    # ra_sec = ((ra/15 - ra_h)*60 - ra_min)*60

    # dec_d = int(dec)
    # dec_min = int((dec - dec_d)*60)
    # dec_sec = ((dec - dec_d)*60 - dec_min)*60

    # print('Computed RA, Dec:')
    # print(ra_h, ra_min, ra_sec)
    # print(dec_d, dec_min, dec_sec)


    # # Convert the coordinates back to image coordinates
    # # ra_star = (6 + (45 + 8/60)/60)*15
    # # dec_star = -(16 + (43 + 21/60)/60)
    # ra_star = ra
    # dec_star = dec
    # x_star, y_star = raDecToCorrectedXYPP(np.array([ra_star]), np.array([dec_star]), \
    #     np.array([date2JD(*time)]), platepar)

    # print('Star X, Y computed:', x_star, y_star)
""" Generate a calibration report given the folder of the night. """


from __future__ import print_function, division, absolute_import

import os

import numpy as np
import matplotlib.pyplot as plt

from RMS.Astrometry.ApplyAstrometry import computeFOVSize, XY2CorrectedRADecPP, raDecToCorrectedXYPP, \
    photometryFit
from RMS.Astrometry.CheckFit import matchStarsResiduals
from RMS.Astrometry.Conversions import date2JD, jd2Date
from RMS.Formats.CALSTARS import readCALSTARS
from RMS.Formats.FFfile import validFFName, getMiddleTimeFF
from RMS.Formats.FFfile import read as readFF
from RMS.Formats.Platepar import Platepar
from RMS.Formats import StarCatalog

# Import Cython functions
import pyximport
pyximport.install(setup_args={'include_dirs':[np.get_include()]})
from RMS.Astrometry.CyFunctions import subsetCatalog


def generateCalibrationReport(config, night_dir_path, platepar=None, show_graphs=False):
    """ Given the folder of the night, find the Calstars file, check the star fit and generate a report
        with the quality of the calibration. The report contains information about both the astrometry and
        the photometry calibration. Graphs will be saved in the given directory of the night.
    
    Arguments:
        config: [Config instance]
        night_dir_path: [str] Full path to the directory of the night.

    Keyword arguments:
        platepar: [Platepar instance] Use this platepar instead of finding one in the folder.
        show_graphs: [bool] Show the graphs on the screen. False by default.

    Return:
        None
    """

    # Find the CALSTARS file in the given folder
    calstars_file = None
    for calstars_file in os.listdir(night_dir_path):
        if ('CALSTARS' in calstars_file) and ('.txt' in calstars_file):
            break

    if calstars_file is None:
        print('CALSTARS file could not be found in the given directory!')
        return None


    # Load the calstars file
    star_list = readCALSTARS(night_dir_path, calstars_file)



    # Find the platepar file in the given directory if it was not given
    if platepar is None:

        platepar_file = None
        for file_name in os.listdir(night_dir_path):
            if file_name == config.platepar_name:
                platepar_file = file_name
                break

        if platepar_file is None:
            print('The platepar cannot be found in the night directory!')
            return None

        # Load the platepar file
        platepar = Platepar()
        platepar.read(os.path.join(night_dir_path, platepar_file))


    night_name = os.path.split(night_dir_path.strip(os.sep))[1]


    # Go one mag deeper than in the config
    lim_mag = config.catalog_mag_limit + 1

    # Load catalog stars (load one magnitude deeper)
    catalog_stars, mag_band_str, config.star_catalog_band_ratios = StarCatalog.readStarCatalog(\
        config.star_catalog_path, config.star_catalog_file, lim_mag=lim_mag, \
        mag_band_ratios=config.star_catalog_band_ratios)

    
    ### Take only those CALSTARS entires for which FF files exist in the folder ###

    # Get a list of FF files in the folder\
    ff_list = []
    for file_name in os.listdir(night_dir_path):
        if validFFName(file_name):
            ff_list.append(file_name)


    # Filter out calstars entries, generate a star dictionary where the keys are JDs of FFs
    star_dict = {}
    ff_dict = {}
    for entry in star_list:

        ff_name, star_data = entry

        # Check if the FF from CALSTARS exists in the folder
        if ff_name not in ff_list:
            continue


        dt = getMiddleTimeFF(ff_name, config.fps, ret_milliseconds=True)
        jd = date2JD(*dt)

        # Add the time and the stars to the dict
        star_dict[jd] = star_data
        ff_dict[jd] = ff_name

    ### ###

    # If there are no FF files in the directory, don't generate a report
    if len(star_dict) == 0:
        print('No FF files from the CALSTARS file in the directory!')
        return None

    # If there are more than a set number of FF files to evaluate, choose only the ones with most stars on
    #   the image
    if len(star_dict) > config.calstars_files_N:

        # Find JDs of FF files with most stars on them
        top_nstars_indices = np.argsort([len(x) for x in star_dict.values()])[::-1][:config.calstars_files_N \
            - 1]

        filtered_star_dict = {}
        for i in top_nstars_indices:
            filtered_star_dict[list(star_dict.keys())[i]] = list(star_dict.values())[i]

        star_dict = filtered_star_dict


    # Match stars on the image with the stars in the catalog
    match_radius = 2.0
    n_matched, avg_dist, cost, matched_stars = matchStarsResiduals(config, platepar, catalog_stars, \
        star_dict, match_radius, ret_nmatch=True, lim_mag=lim_mag)

    # Find the image with the largest number of matched stars
    max_jd = 0
    max_matched_stars = 0
    for jd in matched_stars:
        _, _, distances = matched_stars[jd]
        if len(distances) > max_matched_stars:
            max_jd = jd
            max_matched_stars = len(distances)

    
    # If there are no matched stars, use the image with the largest number of detected stars
    if max_matched_stars <= 2:
        max_jd = max(star_dict, key=lambda x: len(star_dict[x]))
        distances = [np.inf]


    # Load the FF file with the largest number of matched stars
    ff = readFF(night_dir_path, ff_dict[max_jd])
    img_h, img_w = ff.avepixel.shape

    dpi = 200
    plt.figure(figsize=(ff.avepixel.shape[1]/dpi, ff.avepixel.shape[0]/dpi), dpi=dpi)
    plt.imshow(ff.avepixel, cmap='gray', interpolation='nearest')

    legend_handles = []


    # Plot detected stars
    for img_star in star_dict[max_jd]:

        y, x, _, _ = img_star

        rect_side = 5*match_radius
        square_patch = plt.Rectangle((x - rect_side/2, y - rect_side/2), rect_side, rect_side, color='g', \
            fill=False, label='Image stars')

        plt.gca().add_artist(square_patch)

    legend_handles.append(square_patch)



    # If there are matched stars, plot them
    if max_matched_stars > 2:

        # Take the solution with the largest number of matched stars
        image_stars, matched_catalog_stars, distances = matched_stars[max_jd]

        # Plot matched stars
        for img_star in image_stars:
            x, y, _, _ = img_star

            circle_patch = plt.Circle((y, x), radius=3*match_radius, color='y', fill=False, \
                label='Matched stars')

            plt.gca().add_artist(circle_patch)

        legend_handles.append(circle_patch)


        ### Plot match residuals ###

        # Compute preducted positions of matched image stars from the catalog
        x_predicted, y_predicted = raDecToCorrectedXYPP(matched_catalog_stars[:, 0], \
            matched_catalog_stars[:, 1], max_jd, platepar)

        img_y, img_x, _, _ = image_stars.T

        delta_x = x_predicted - img_x
        delta_y = y_predicted - img_y

        # Compute image residual and angle of the error
        res_angle = np.arctan2(delta_y, delta_x)
        res_distance = np.sqrt(delta_x**2 + delta_y**2)


        # Calculate coordinates of the beginning of the residual line
        res_x_beg = img_x + 3*match_radius*np.cos(res_angle)
        res_y_beg = img_y + 3*match_radius*np.sin(res_angle)

        # Calculate coordinates of the end of the residual line
        res_x_end = img_x + 100*np.cos(res_angle)*res_distance
        res_y_end = img_y + 100*np.sin(res_angle)*res_distance

        # Plot the 100x residuals
        for i in range(len(x_predicted)):
            res_plot = plt.plot([res_x_beg[i], res_x_end[i]], [res_y_beg[i], res_y_end[i]], color='orange', \
                lw=0.5, label='100x residuals')

        legend_handles.append(res_plot[0])

        ### ###

    else:
        
        # If there are no matched stars, plot large text in the middle of the screen
        plt.text(img_w/2, img_h/2, "NO MATCHED STARS!", color='r', alpha=0.5, fontsize=20, ha='center',
            va='center')


    ### Plot positions of catalog stars to the limiting magnitude of the faintest matched star + 1 mag ###

    # Find the faintest magnitude among matched stars
    if max_matched_stars > 2:
        faintest_mag = np.max(matched_catalog_stars[:, 2]) + 1

    else:
        # If there are no matched stars, use the limiting magnitude from config
        faintest_mag = config.catalog_mag_limit + 1


    # Estimate RA,dec of the centre of the FOV
    _, RA_c, dec_c, _ = XY2CorrectedRADecPP([jd2Date(max_jd)], [platepar.X_res/2], [platepar.Y_res/2], [1], 
        platepar)

    RA_c = RA_c[0]
    dec_c = dec_c[0]

    fov_radius = np.hypot(*computeFOVSize(platepar))

    # Get stars from the catalog around the defined center in a given radius
    _, extracted_catalog = subsetCatalog(catalog_stars, RA_c, dec_c, fov_radius, faintest_mag)
    ra_catalog, dec_catalog, mag_catalog = extracted_catalog.T

    # Compute image positions of all catalog stars that should be on the image
    x_catalog, y_catalog = raDecToCorrectedXYPP(ra_catalog, dec_catalog, max_jd, platepar)

    # Filter all catalog stars outside the image
    temp_arr = np.c_[x_catalog, y_catalog, mag_catalog]
    temp_arr = temp_arr[temp_arr[:, 0] >= 0]
    temp_arr = temp_arr[temp_arr[:, 0] <= ff.avepixel.shape[1]]
    temp_arr = temp_arr[temp_arr[:, 1] >= 0]
    temp_arr = temp_arr[temp_arr[:, 1] <= ff.avepixel.shape[0]]
    x_catalog, y_catalog, mag_catalog = temp_arr.T

    # Plot catalog stars on the image
    cat_stars_handle = plt.scatter(x_catalog, y_catalog, c='none', marker='D', lw=1.0, alpha=0.4, \
        s=((4.0 + (faintest_mag - mag_catalog))/3.0)**(2*2.512), edgecolor='r', label='Catalog stars')

    legend_handles.append(cat_stars_handle)

    ### ###


    # Add info text
    info_text = ff_dict[max_jd] + '\n' \
        + "Matched stars: {:d}/{:d}\n".format(max_matched_stars, len(star_dict[max_jd])) \
        + "Median distance: {:.2f} px".format(np.median(distances))

    plt.text(10, 10, info_text, bbox=dict(facecolor='black', alpha=0.5), va='top', ha='left', fontsize=4, \
        color='w')

    legend = plt.legend(handles=legend_handles, prop={'size': 4})
    legend.get_frame().set_facecolor('k')
    legend.get_frame().set_edgecolor('k')
    for txt in legend.get_texts():
        txt.set_color('w')


    plt.axis('off')
    plt.gca().get_xaxis().set_visible(False)
    plt.gca().get_yaxis().set_visible(False)

    plt.xlim([0, ff.avepixel.shape[1]])
    plt.ylim([ff.avepixel.shape[0], 0])

    # Remove the margins
    plt.subplots_adjust(left=0, bottom=0, right=1, top=1, wspace=0, hspace=0)

    plt.savefig(os.path.join(night_dir_path, night_name + '_calib_report_astrometry.jpg'), \
        bbox_inches='tight', pad_inches=0, dpi=dpi)


    if show_graphs:
        plt.show()

    else:
        plt.clf()
        plt.close()



    if max_matched_stars > 2:

        ### Plot the photometry ###

        # Take only those stars which are inside the 3/4 of the shorter image axis from the center
        photom_selection_radius = np.min([img_h, img_w])/3
        filter_indices = ((image_stars[:, 0] - img_h/2)**2 + (image_stars[:, 1] \
            - img_w/2)**2) <= photom_selection_radius**2
        star_intensities = image_stars[filter_indices, 2]
        catalog_mags = matched_catalog_stars[filter_indices, 2]

        # Plot intensities of image stars
        #star_intensities = image_stars[:, 2]
        plt.scatter(-2.5*np.log10(star_intensities), catalog_mags, s=5, c='r')

        # Fit the photometry on automated star intensities
        photom_offset, fit_stddev, _ = photometryFit(np.log10(star_intensities), catalog_mags)


        # Plot photometric offset from the platepar
        x_min, x_max = plt.gca().get_xlim()
        y_min, y_max = plt.gca().get_ylim()

        x_min_w = x_min - 3
        x_max_w = x_max + 3
        y_min_w = y_min - 3
        y_max_w = y_max + 3

        photometry_info = 'Platepar: {:+.2f}LSP {:+.2f} +/- {:.2f} \nGamma = {:.2f}'.format(platepar.mag_0, \
            platepar.mag_lev, platepar.mag_lev_stddev, platepar.gamma)

        # Plot the photometry calibration from the platepar
        logsum_arr = np.linspace(x_min_w, x_max_w, 10)
        plt.plot(logsum_arr, logsum_arr + platepar.mag_lev, label=photometry_info, linestyle='--', \
            color='k', alpha=0.5)

        # Plot the fitted photometry calibration
        fit_info = "Fit: {:+.2f}LSP {:+.2f} +/- {:.2f}".format(-2.5, photom_offset, fit_stddev)
        plt.plot(logsum_arr, logsum_arr + photom_offset, label=fit_info, linestyle='--', color='red', 
            alpha=0.5)

        plt.legend()

        plt.ylabel("Catalog magnitude ({:s})".format(mag_band_str))
        plt.xlabel("Uncalibrated magnitude")

        # Set wider axis limits
        plt.xlim(x_min_w, x_max_w)
        plt.ylim(y_min_w, y_max_w)

        plt.gca().invert_yaxis()
        plt.gca().invert_xaxis()

        plt.grid()

        plt.savefig(os.path.join(night_dir_path, night_name + '_calib_report_photometry.png'), dpi=150)


        if show_graphs:
            plt.show()

        else:
            plt.clf()
            plt.close()

        ### ###




if __name__ == "__main__":


    import argparse

    import RMS.ConfigReader as cr


    ### PARSE INPUT ARGUMENTS ###

    # Init the command line arguments parser
    arg_parser = argparse.ArgumentParser(description=""" Generate the calibration report.
        """)

    arg_parser.add_argument('dir_path', type=str, help="Path to the folder of the night.")


    # Parse the command line arguments
    cml_args = arg_parser.parse_args()

    #############################


    # Load the default configuration file
    config = cr.parse(".config")


    generateCalibrationReport(config, cml_args.dir_path, show_graphs=True)




import datetime
import typing
# from model_logging import get_logger

# import tensorflow as tf
import pandas as pd
import numpy as np
import h5py
import utils
import os
import tqdm
import json
# import cv2 as cv

import multiprocessing


def get_stations_coordinates(df: pd.DataFrame, stations) -> typing.Dict[str, typing.Tuple]:
    # takes one hdf5 path
    hdf5_path = "/project/cq-training-1/project1/data/hdf5v7_8bit/2015.01.01.0800.h5"

    with h5py.File(hdf5_path, 'r') as h5_data:
        lats, lons = utils.fetch_hdf5_sample("lat", h5_data, 0), utils.fetch_hdf5_sample("lon", h5_data, 0)

    stations_coords = {}

    for region, lats_lons in stations.items():
        coords = (np.argmin(np.abs(lats - lats_lons[0])), np.argmin(np.abs(lons - lats_lons[1])))
        stations_coords[region] = coords

    return stations_coords


def preprocess_dataframe(dataframe, train_config):
    main_df = dataframe.copy()

    # make sure it sorted by its index
    main_df.sort_index(ascending=True, inplace=True)

    # replace nan by np.nan (why??)
    main_df.replace('nan', np.NaN, inplace=True)

    # dropping records without hdf5 files
    main_df.drop(main_df.loc[main_df['hdf5_8bit_path'].isnull()].index, inplace=True)

    # dropping records without ncdf files
    main_df.drop(main_df.loc[main_df['ncdf_path'].isnull()].index, inplace=True)

    stations = train_config["stations"]
    # drop all night times
    station_names = list(stations.keys())
    b = [s + "_DAYTIME" for s in station_names]

    main_df.drop(main_df[(main_df[b[0]] == 0.0)
                         & (main_df[b[1]] == 0.0)
                         & (main_df[b[2]] == 0.0)
                         & (main_df[b[3]] == 0.0)
                         & (main_df[b[4]] == 0.0)
                         & (main_df[b[5]] == 0.0)
                         & (main_df[b[6]] == 0.0)].index, inplace=True)

    # shuffle dataframe
    main_df = main_df.sample(frac=1)

    return main_df


def load_file(path, name):
    assert os.path.isfile(path), f"invalid {name} config file: {path}"
    with open(path, "r") as fd:
        return json.load(fd)


def save_image_and_batch(dir_path,
                         file_name,
                         image_data,
                         true_ghis_data,
                         clear_sky_ghis_data,
                         station_ids,
                         datetime_sequence):
    file_name = file_name + ".hdf5"
    path = os.path.join(dir_path, file_name)
    with h5py.File(path, 'w') as f:
        f.create_dataset("images", shape=image_data.shape, dtype=np.float32, data=image_data)
        f.create_dataset("GHI", shape=true_ghis_data.shape, dtype=np.float32, data=true_ghis_data)
        f.create_dataset("clearsky_GHI", shape=clear_sky_ghis_data.shape, dtype=np.float32, data=clear_sky_ghis_data)
        station_ids = [n.encode("ascii", "ignore") for n in station_ids]
        f.create_dataset("station_id", shape=(len(station_ids), 1), dtype='S10', data=station_ids)
        datetime_sequence = [str(n).encode("ascii", "ignore") for n in datetime_sequence]
        f.create_dataset("datetime_sequence", shape=len(datetime_sequence,1), dtype='S10', data=datetime_sequence)


def get_channels(hdf5_path, hdf5_offset):
    with h5py.File(hdf5_path, "r") as h5_data:
        ch1_data = utils.fetch_hdf5_sample("ch1", h5_data, hdf5_offset)
        ch2_data = utils.fetch_hdf5_sample("ch2", h5_data, hdf5_offset)
        ch3_data = utils.fetch_hdf5_sample("ch3", h5_data, hdf5_offset)
        ch4_data = utils.fetch_hdf5_sample("ch4", h5_data, hdf5_offset)
        ch6_data = utils.fetch_hdf5_sample("ch6", h5_data, hdf5_offset)
    return ch1_data, ch2_data, ch3_data, ch4_data, ch6_data


def get_TrueGHIs(dataframe, target_time_offsets, timestamp, station_id):
    # check if its night at this station
    DAYTIME_col = station_id + "_DAYTIME"
    # return None if T0 time isn't daytime, we don't want to train on such sequences
    if dataframe.loc[timestamp][DAYTIME_col] == 0.0:
        return None

    trueGHIs = [0] * 4
    GHI_col = station_id + "_GHI"
    # if timestamp missing
    # TODO: interpolate GHI values if NaN
    try:
        trueGHIs[0] = dataframe.loc[timestamp][GHI_col]  # T0_GHI
        trueGHIs[1] = dataframe.loc[timestamp + target_time_offsets[1]][GHI_col]  # T1_GHI
        trueGHIs[2] = dataframe.loc[timestamp + target_time_offsets[2]][GHI_col]  # T3_GHI
        trueGHIs[3] = dataframe.loc[timestamp + target_time_offsets[3]][GHI_col]  # T6_GHI
    except:
        return None

    # if we still encounter NaN, handle it
    if np.any(np.isnan(trueGHIs)):
        return None

    return trueGHIs


def get_ClearSkyGHIs(dataframe, target_time_offsets, timestamp, station_id):
    # check if its night at this station
    DAYTIME_col = station_id + "_DAYTIME"
    # return None if T0 time isn't daytime, we don't want to train on such sequences
    if dataframe.loc[timestamp][DAYTIME_col] == 0.0:
        return None

    clearSkyGHIs = [0] * 4
    clearSkyGHI_col = station_id + "_CLEARSKY_GHI"
    # if timestamp missing
    # TODO: interpolate GHI values if NaN
    try:
        clearSkyGHIs[0] = dataframe.loc[timestamp][clearSkyGHI_col]  # T0_GHI
        clearSkyGHIs[1] = dataframe.loc[timestamp + target_time_offsets[1]][clearSkyGHI_col]  # T1_GHI
        clearSkyGHIs[2] = dataframe.loc[timestamp + target_time_offsets[2]][clearSkyGHI_col]  # T3_GHI
        clearSkyGHIs[3] = dataframe.loc[timestamp + target_time_offsets[3]][clearSkyGHI_col]  # T6_GHI
    except:
        return None

    # if we still encounter NaN, handle it
    if np.any(np.isnan(clearSkyGHIs)):
        return None

    return clearSkyGHIs


def normalize_images(images):
    means = [0.30, 272.52, 236.94, 261.47, 247.28]
    stds = [0.218, 13.66, 6.49, 15.91, 11.15]

    for channel, u, sig in zip(range(5), means, stds):
        images[:, :, channel] = (images[:, :, channel] - u) / sig
    return images


def crop_images(df, big_df, timestamps_from_history, target_time_offsets, coordinates, window_size=41):
    assert window_size < 42, f"window_size value of {window_size} is too big, please reduce it to 42 and lower"

    n_channels = 5
    image_crops_for_stations = []
    true_ghis_for_station = []
    clearSky_ghis_for_station = []
    station_ids = []
    considered_timestamps = []
    timestamps = []
    T_0_night_times = []

    # image_crops_for_stations = np.zeros(shape=(
    #    len(coordinates), len(timestamps_from_history), window_size * 2, window_size * 2, n_channels
    # ))

    # ghis_for_station = np.zeros(shape=(len(coordinates), len(target_time_offsets)))

    for index, timestamp in enumerate(timestamps_from_history):
        try:
            row = df.loc[timestamp]
        except:
            if index == 0:
                # print("Timestamp {} not found, Not considering this sequence! \n".format(timestamp))
                return None, None, None, None
            else:
                # use T0 image if missing
                # print("Timestamp {} not found, using T0 image".format(timestamp))
                row = df.loc[timestamps_from_history[0]]

        hdf5_path = row["hdf5_8bit_path"]
        hdf5_offset = row["hdf5_8bit_offset"]

        #         if index == 0:
        #             # read channel data for all stations at once,
        #             # because same file consists data for all stations
        #             channels_data = get_channels(hdf5_path, hdf5_offset)

        #         # TODO: avoid reading file multiple times if T-delta times are from same file
        #         else:
        #             offset_zero_time = pd.to_datetime('08:00:00')
        #             time_now = pd.to_datetime(str(timestamp).split()[-1])
        #             if time_now < offset_zero_time:
        #                 channels_data = get_channels(hdf5_path, hdf5_offset)

        channels_data = get_channels(hdf5_path, hdf5_offset)

        image_crops_per_stations = []
        timestamps = []
        # get cropped images for all stations
        for i, station_coordinates in enumerate(coordinates.items()):

            station_id = station_coordinates[0]
            DAYTIME_col = station_id + "_DAYTIME"
            # check if T0 time isn't daytime, we don't want to train on such sequences
            if dataframe.loc[timestamps_from_history[0]][DAYTIME_col] == 0.0:
                continue

            x_coord = station_coordinates[1][0]
            y_coord = station_coordinates[1][1]

            ch1_crop = channels_data[0][x_coord - window_size:x_coord + window_size,
                       y_coord - window_size:y_coord + window_size]
            ch2_crop = channels_data[1][x_coord - window_size:x_coord + window_size,
                       y_coord - window_size:y_coord + window_size]
            ch3_crop = channels_data[2][x_coord - window_size:x_coord + window_size,
                       y_coord - window_size:y_coord + window_size]
            ch4_crop = channels_data[3][x_coord - window_size:x_coord + window_size,
                       y_coord - window_size:y_coord + window_size]
            ch6_crop = channels_data[4][x_coord - window_size:x_coord + window_size,
                       y_coord - window_size:y_coord + window_size]

            #             image_crops_for_stations[i] = np.stack((ch1_crop,
            #                                                     ch2_crop,
            #                                                     ch3_crop,
            #                                                     ch4_crop,
            #                                                     ch6_crop), axis=-1)

            cropped_img = np.stack((ch1_crop,
                                    ch2_crop,
                                    ch3_crop,
                                    ch4_crop,
                                    ch6_crop), axis=-1)

            cropped_img = normalize_images(cropped_img)

            cropped_img = np.expand_dims(cropped_img, axis=0)
            # print("Cropped img size: {}".format(cropped_img.shape))

            image_crops_per_stations.append(cropped_img)
            timestamps.append(np.expand_dims(timestamp, axis=0))

            # image_crops_for_stations.append(cropped_img)

            # get true GHIs only for first timestamp - T0
            if index == 0:
                trueGHIs = get_TrueGHIs(big_df, target_time_offsets, timestamp, station_id)
                clearSkyGHIs = get_ClearSkyGHIs(big_df, target_time_offsets, timestamp, station_id)
                if trueGHIs is None or clearSkyGHIs is None:
                    # print("No target GHIs found for timestamp {}".format(timestamp))
                    # setup dummy GHIs for now!
                    trueGHIs = np.zeros(len(target_time_offsets))
                    clearSkyGHIs = np.ones(len(target_time_offsets))
                    # return None, None

                true_ghis_for_station.append(trueGHIs)
                clearSky_ghis_for_station.append(clearSkyGHIs)
                # append station id if everthing works well till this point
                station_ids.append(station_id)

        image_crops_per_stations = np.array(image_crops_per_stations)
        timestamps = np.array(timestamps)

        # print("T_{} timstamp Images size: {}\n".format(i, image_crops_per_stations.shape))

        # image_crops_for_stations.append(image_crops_per_stations)
        if len(image_crops_for_stations) == 0:
            image_crops_for_stations = image_crops_per_stations
            considered_timestamps = timestamps
        else:
            # print("before appending, total size: {}".format(image_crops_for_stations.shape))
            image_crops_for_stations = np.concatenate((image_crops_for_stations, image_crops_per_stations), axis=1)
            considered_timestamps = np.concatenate((considered_timestamps, timestamps), axis=1)
            # print("Harman: ",considered_timestamps.shape, np.array(timestamps).shape)
            # print("after appending, total size: {}\n".format(image_crops_for_stations.shape))

    # print("******harman: ", np.array(image_crops_for_stations).shape, np.array(considered_timestamps).shape)
    # print("\n*****************returning now\n")
    return np.array(image_crops_for_stations), np.array(true_ghis_for_station), np.array(
        clearSky_ghis_for_station), np.array(station_ids), np.array(considered_timestamps)


def save_batches(main_df, dataframe, stations_coordinates, user_config, train_config, save_dir_path, start_index,
                 end_index):
    input_time_offsets = [pd.Timedelta(d).to_pytimedelta() for d in user_config["input_time_offsets"]]
    target_time_offsets = [pd.Timedelta(d).to_pytimedelta() for d in train_config["target_time_offsets"]]

    mini_batch_size = user_config["batch_size_for_single_file"]  # 256
    window_size = user_config["image_size_m"] // 2
    n_channels = user_config["nb_channels"]

    concat_images = np.array([])
    target_trueGHIs = np.array([])
    target_clearSkyGHIs = np.array([])
    target_timestamps = np.array([])
    target_station_ids = np.array([])
    index = 0
    batch_counter = start_index

    if not os.path.exists(save_dir_path):
        os.makedirs(save_dir_path)

    for time_index, col in tqdm.tqdm(main_df[start_index:end_index].iterrows()):

        # get past timestamps in range of input_seq_length
        timestamps_from_history = []
        for i in range(user_config["input_seq_length"]):
            timestamps_from_history.append(time_index - input_time_offsets[i])

        images, trueGHIs, clearSkyGHIs, station_ids, timestamps = crop_images(main_df,
                                                                              dataframe,
                                                                              timestamps_from_history,
                                                                              target_time_offsets,
                                                                              stations_coordinates,
                                                                              window_size)

        if images is None or trueGHIs is None:
            # print("No image found for timestamp {}".format(time_index))
            # print("No target GHIs found for timestamp {}".format(time_index))
            continue

        if len(concat_images) == 0:
            concat_images = images
            target_trueGHIs = trueGHIs
            target_clearSkyGHIs = clearSkyGHIs
            target_timestamps = timestamps
            target_station_ids = station_ids
        else:
            concat_images = np.append(concat_images, images, axis=0)
            target_trueGHIs = np.append(target_trueGHIs, trueGHIs, axis=0)
            target_clearSkyGHIs = np.append(target_clearSkyGHIs, clearSkyGHIs, axis=0)
            target_timestamps = np.append(target_timestamps, timestamps, axis=0)
            target_station_ids = np.append(target_station_ids, station_ids, axis=0)

        index += images.shape[0]

        # save h5py file here
        if index >= mini_batch_size:
            # print("Harman: ",concat_images.shape, target_trueGHIs.shape, target_clearSkyGHIs.shape, target_station_ids.shape, target_timestamps.shape)
            assert concat_images.shape[0] == target_trueGHIs.shape[0]
            assert concat_images.shape[0] == target_clearSkyGHIs.shape[0]
            assert concat_images.shape[0] == target_timestamps.shape[0]
            assert concat_images.shape[0] == target_station_ids.shape[0]

            batch_counter += 1
            file_name = "batch_" + str(batch_counter)
            save_image_and_batch(save_dir_path, file_name,
                                 concat_images[:mini_batch_size],
                                 target_trueGHIs[:mini_batch_size],
                                 target_clearSkyGHIs[:mini_batch_size],
                                 target_station_ids[:mini_batch_size],
                                 target_timestamps[:mini_batch_size])

            concat_images = np.array([])
            target_trueGHIs = np.array([])
            target_clearSkyGHIs = np.array([])
            target_station_ids = np.array([])
            target_timestamps = np.array([])

            index = 0


if __name__ == "__main__":
    dataframe_path = "/project/cq-training-1/project1/data/catalog.helios.public.20100101-20160101.pkl"
    user_config_path = "eval_user_cfg.json"
    train_config_path = "train_cfg.json"

    dataframe = pd.read_pickle(dataframe_path)
    user_config = load_file(user_config_path, "user")
    train_config = load_file(train_config_path, "training")
    stations = train_config["stations"]

    time_offsets = [pd.Timedelta(d).to_pytimedelta() for d in train_config["target_time_offsets"]]

    train_dataframe = dataframe.loc['2010-01-01':'2014-12-31']
    val_dataframe = dataframe.loc['2015-01-01':'2015-12-31']

    train_dataframe = preprocess_dataframe(train_dataframe, train_config)
    val_dataframe = preprocess_dataframe(val_dataframe, train_config)

    # get station coordinates, need to be called only once
    stations_coordinates = get_stations_coordinates(train_dataframe, stations)

    train_file_path = "/project/cq-training-1/project1/teams/team08/data/train_crops"
    my_train_args = []
    for i in range(0, 90000, 500):
        args = (train_dataframe, dataframe, stations_coordinates, user_config, train_config, train_file_path, int(i),
                int(i) + 500)
        my_train_args.append(args)

    val_file_path = "/project/cq-training-1/project1/teams/team08/data/val_crops"

    my_val_args = []
    for i in range(0, 20000, 500):
        args = (
        val_dataframe, dataframe, stations_coordinates, user_config, train_config, val_file_path, int(i), int(i) + 500)
        my_val_args.append(args)

    p = multiprocessing.Pool(4)
    p.starmap(save_batches, my_train_args)

    # p.starmap(save_batches, my_val_args)
import datetime
import typing
import model_logging

import tensorflow as tf
import pandas as pd
import numpy as np


class DataLoader():

    def __init__(
        self,
        dataframe: pd.DataFrame,
        target_datetimes: typing.List[datetime.datetime],
        stations: typing.Dict[typing.AnyStr, typing.Tuple[float, float, float]],
        target_time_offsets: typing.List[datetime.timedelta],
        config: typing.Dict[typing.AnyStr, typing.Any],
    ):
        """
        Copy-paste from evaluator.py:
        Args:
            dataframe: a pandas dataframe that provides the netCDF file path (or HDF5 file path and offset) for all
                relevant timestamp values over the test period.
            target_datetimes: a list of timestamps that your data loader should use to provide imagery for your model.
                The ordering of this list is important, as each element corresponds to a sequence of GHI values
                to predict. By definition, the GHI values must be provided for the offsets given by ``target_time_offsets``
                which are added to each timestamp (T=0) in this datetimes list.
            stations: a map of station names of interest paired with their coordinates (latitude, longitude, elevation).
            target_time_offsets: the list of timedeltas to predict GHIs for (by definition: [T=0, T+1h, T+3h, T+6h]).
            config: configuration dictionary holding extra parameters
        """
        self.dataframe = dataframe
        self.target_datetimes = target_datetimes
        self.stations = list(stations.keys())
        self.config = config
        self.target_time_offsets = target_time_offsets
        self.initialize()

    def initialize(self):
        self.logger = model_logging.get_logger()
        self.logger.debug("Initialize start")
        # assert len([*self.stations]) == 1
        self.test_station = self.stations[0]
        self.batch_size = self.config["batch_size"]
        self.image_dim = (self.config["image_size_m"], self.config["image_size_n"])
        self.output_seq_len = len(self.target_time_offsets)
        self.data_loader = tf.data.Dataset.from_generator(
            self.data_generator_fn, output_types=(tf.float32, tf.float32, tf.float32, tf.float32)
        )

    def get_ghi_values(self, batch_of_datetimes, station_id):
        batch_of_clearsky_GHIs = np.zeros((len(batch_of_datetimes), self.output_seq_len))
        batch_of_true_GHIs = np.zeros((len(batch_of_datetimes), self.output_seq_len))

        for i, dt in enumerate(batch_of_datetimes):
            for j, time_offset in enumerate(self.target_time_offsets):
                dt_index = dt + time_offset
                batch_of_clearsky_GHIs[i, j] = self.dataframe.lookup([dt_index], [station_id + '_CLEARSKY_GHI'])
                # If the true GHI is not provided, return 0s instead:
                if station_id + "_GHI" in self.dataframe.columns:
                    batch_of_true_GHIs[i, j] = self.dataframe.lookup([dt_index], [station_id + '_GHI'])

        batch_of_true_GHIs = np.nan_to_num(batch_of_true_GHIs)  # TODO: We only convert nan to 0 for now

        return batch_of_true_GHIs, batch_of_clearsky_GHIs

    def get_image_data(self, batch_of_datetimes):
        n_channels = 5
        # TODO: Not implemented yet, generate random data instead
        image = tf.random.uniform(shape=(
            len(batch_of_datetimes), self.image_dim[0], self.image_dim[1], n_channels
        ))
        return image

    def data_generator_fn(self):
        for station_id in self.stations:
            for i in range(0, len(self.target_datetimes), self.batch_size):
                batch_of_datetimes = self.target_datetimes[i:(i + self.batch_size)]
                true_GHIs, clearsky_GHIs = self.get_ghi_values(batch_of_datetimes, station_id)
                images = self.get_image_data(batch_of_datetimes)

                # Remember that you do not have access to the targets.
                # Your dataloader should handle this accordingly.
                yield images, clearsky_GHIs, true_GHIs, true_GHIs

    def get_data_loader(self):
        '''
        Returns:
            A ``tf.data.Dataset`` object that can be used to produce input tensors for your model. One tensor
            must correspond to one sequence of past imagery data. The tensors must be generated in the order given
            by ``target_sequences``.
        '''
        return self.data_loader
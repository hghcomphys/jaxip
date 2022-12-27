from pathlib import Path
from typing import Optional

import jax
import jax.numpy as jnp
import numpy as np

from mlpot.base import _Base
from mlpot.logger import logger
from mlpot.types import Array, Dtype
from mlpot.types import dtype as _dtype


class DescriptorScaler(_Base):
    """
    Scale descriptor values.

    Scaling parameters are calculated by fitting over the samples in the dataset.
    Available scaler information are as follows:

    * minimum
    * maximum
    * mean
    * sigma (standard deviation)

    Scaler is also used to warn when setting out-of-distribution samples base
    on the fitted scaler parameters.
    """

    def __init__(
        self,
        scale_type: str = "scale_center",
        scale_min: float = 0.0,
        scale_max: float = 1.0,
        dtype: Dtype = _dtype.FLOATX,
    ) -> None:
        """Initialize scaler including scaler type and min/max values."""
        assert scale_min < scale_max

        # Set min/max range for scaler
        self.scale_type: str = scale_type
        self.scale_min: float = scale_min
        self.scale_max: float = scale_max
        self.dtype: Dtype = dtype
        super().__init__()

        # Statistical parameters
        self.nsamples: int = 0  # number of samples
        self.dimension: int = 0  # dimension of each sample
        self.mean: Array = jnp.asarray([])  # mean array of all fitted descriptor values
        self.sigma: Array = jnp.asarray([])  # standard deviation
        self.min: Array = jnp.asarray([])  # minimum
        self.max: Array = jnp.asarray([])  # maximum

        self.number_of_warnings: int = 0
        self.max_number_of_warnings: Optional[int] = None

        # Set scaler type function
        self._transform = getattr(self, f"{self.scale_type}")

    def fit(self, data: Array) -> None:
        """
        Fit scaler parameters using the given input data.
        Bach-wise sampling is also possible (see `this`_ for more details).

        .. _hear: https://notmatthancock.github.io/2017/03/23/simple-batch-stat-updates.html
        """
        data = jnp.atleast_2d(data)  # type: ignore

        if self.nsamples == 0:
            self.nsamples = data.shape[0]
            self.dimension = data.shape[1]
            self.mean = jnp.mean(data, axis=0)
            self.sigma = jnp.std(data, axis=0)
            self.max = jnp.max(data, axis=0)
            self.min = jnp.min(data, axis=0)
        else:
            if data.shape[1] != self.dimension:
                logger.error(
                    f"Data dimension doesn't match: {data.shape[1]} (expected {self.dimension})",
                    exception=ValueError,  # type: ignore
                )

            # New data (batch)
            new_mean: Array = jnp.mean(data, axis=0)
            new_sigma: Array = jnp.std(data, axis=0)
            new_min: Array = jnp.min(data, axis=0)
            new_max: Array = jnp.max(data, axis=0)
            m, n = float(self.nsamples), data.shape[0]

            # Calculate quantities for entire data
            mean = self.mean  # immutable
            self.mean = (
                m / (m + n) * mean + n / (m + n) * new_mean
            )  # self.mean is now a new array and different from the above mean variable
            self.sigma = jnp.sqrt(
                m / (m + n) * self.sigma**2
                + n / (m + n) * new_sigma**2
                + m * n / (m + n) ** 2 * (mean - new_mean) ** 2
            )
            self.max = jnp.maximum(self.max, new_max)
            self.min = jnp.minimum(self.min, new_min)
            self.nsamples += n

    def __call__(self, array: Array, warnings: bool = False) -> Array:
        """
        Transform the input descriptor values base on the scaler parameters.

        This method has to be called after fitting scaler over the dataset,
        or statistical parameters are already loaded (e.g. saved file).
        """
        if warnings:
            self._check_warnings(array)
        return self._transform(array)

    def set_max_number_of_warnings(self, number: int) -> None:
        """Set the maximum number of warning for out of range descriptor values."""
        self.max_number_of_warnings = number
        self.number_of_warnings = 0
        logger.debug(
            f"Setting the maximum number of scaler warnings: {self.max_number_of_warnings}"
        )

    def _check_warnings(self, array: Array) -> None:
        """
        Check whether the output scaler values exceed the predefined min/max range values or not.

        If it's the case, it keeps counting the number of warnings and
        raises an error when it exceeds the maximum number.

        An out of range descriptor value is in fact an indication of
        the descriptor extrapolation which has to be avoided.
        """
        if self.max_number_of_warnings is None:
            return

        gt: Array = jax.lax.gt(array, self.max)
        lt: Array = jax.lax.gt(self.min, array)

        self.number_of_warnings += int(
            jnp.any(jnp.logical_or(gt, lt))
        )  # alternative counting is using sum

        if self.number_of_warnings >= self.max_number_of_warnings:
            logger.warning(
                "Exceeding maximum number scaler warnings (extrapolation warning): "
                f"{self.number_of_warnings} (max={self.max_number_of_warnings})"
            )

    def center(self, array: Array) -> Array:
        return array - self.mean

    def scale(self, array: Array) -> Array:
        return self.scale_min + (self.scale_max - self.scale_min) * (
            array - self.min
        ) / (self.max - self.min)

    def scale_center(self, array: Array) -> Array:
        return self.scale_min + (self.scale_max - self.scale_min) * (
            array - self.mean
        ) / (self.max - self.min)

    def scale_center_sigma(self, array: Array) -> Array:
        return (
            self.scale_min
            + (self.scale_max - self.scale_min) * (array - self.mean) / self.sigma
        )

    def save(self, filename: Path) -> None:
        """Save scaler parameters into file."""
        with open(str(filename), "w") as file:
            file.write(f"{'# Min':<23s} {'Max':<23s} {'Mean':<23s} {'Sigma':<23s}\n")
            for i in range(self.dimension):
                file.write(
                    f"{self.min[i]:<23.15E} {self.max[i]:<23.15E} {self.mean[i]:<23.15E} {self.sigma[i]:<23.15E}\n"
                )

    def load(self, filename: Path) -> None:
        """Load scaler parameters from file."""
        data = np.loadtxt(str(filename)).T
        self.nsamples = 1
        self.dimension = data.shape[1]

        self.min = jnp.asarray(data[0], dtype=self.dtype)
        self.max = jnp.asarray(data[1], dtype=self.dtype)
        self.mean = jnp.asarray(data[2], dtype=self.dtype)
        self.sigma = jnp.asarray(data[3], dtype=self.dtype)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(scale_type='{self.scale_type}', "
            f"scale_min={self.scale_min}, scale_max={self.scale_max})"
        )

import jax.numpy as jnp
from typing import Mapping
from mlpot.logger import logger
from mlpot.base import _Base


class ErrorMetric(_Base):
    """
    A base error metric class.
    Note: gradient calculations is disabled for all error metrics.
    """

    def __init__(self):
        def mse(*, prediction: jnp.ndarray, target: jnp.ndarray):
            return ((target - prediction) ** 2).mean()

        self._mse_metric = mse

    def __call__(
        self, prediction: jnp.ndarray, target: jnp.ndarray, factor=None
    ) -> jnp.ndarray:
        raise NotImplementedError()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class MSE(ErrorMetric):
    """
    Mean squared error metric
    """

    def __call__(
        self, prediction: jnp.ndarray, target: jnp.ndarray, factor=None
    ) -> jnp.ndarray:
        return self._mse_metric(prediction=prediction, target=target)


class RMSE(MSE):
    """
    Root mean squared error metric
    """

    def __call__(
        self, prediction: jnp.ndarray, target: jnp.ndarray, factor=None
    ) -> jnp.ndarray:
        return jnp.sqrt(self._mse_metric(prediction=prediction, target=target))


class MSEpa(MSE):
    """
    Mean squared error per atom metric.
    MSE of energy per atom
    MSE of force
    """

    def __call__(
        self, prediction: jnp.ndarray, target: jnp.ndarray, factor: int = 1
    ) -> jnp.ndarray:
        return self._mse_metric(prediction=prediction, target=target) / factor


class RMSEpa(RMSE):
    """
    Root mean squared error per atom metric.
    RMSE of energy per atom
    RMSE of force
    """

    def __call__(
        self, prediction: jnp.ndarray, target: jnp.ndarray, factor: int = 1
    ) -> jnp.ndarray:
        return jnp.sqrt(self._mse_metric(prediction=prediction, target=target)) / factor


def init_error_metric(metric_type: str, **kwargs) -> ErrorMetric:
    """
    An utility function to create a given type of error metric.

    :param metric_type: MSE, RMSE, MSEpa, EMSEpa
    :type metric_type: str
    :return: An instance of desired error metric
    :rtype: ErrorMetric
    """
    _map_error_metric: Mapping[str, ErrorMetric] = {
        "MSE": MSE,
        "RMSE": RMSE,
        "MSEpa": MSEpa,
        "RMSEpa": RMSEpa,
        # Any new defined metrics must be added here.
    }
    try:
        return _map_error_metric[metric_type](**kwargs)
    except KeyError:
        logger.error(f"Unknown error metric '{metric_type}'", exception=KeyError)

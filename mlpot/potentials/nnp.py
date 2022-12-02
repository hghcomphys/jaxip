from ..logger import logger
from ..structure import Structure
from ..datasets.runner import RunnerStructureDataset
from ..descriptors.base import Descriptor
from ..descriptors.asf.asf import ASF
from ..descriptors.asf.cutoff import CutoffFunction
from ..descriptors.scaler import DescriptorScaler
from ..descriptors.asf.radial import G1, G2
from ..descriptors.asf.angular import G3, G9
from ..models.nn import NeuralNetworkModel
from ..structure.element import ElementMap
from .base import Potential
from .settings import NeuralNetworkPotentialSettings
from .trainer import NeuralNetworkPotentialTrainer
from ._energy import _energy_fn
from typing import List, Dict, Union, Tuple, Generator
from pathlib import Path
from jax import random
from frozendict import frozendict
import jax.numpy as jnp


class NeuralNetworkPotential(Potential):
    """
    A suitcase class of high-dimensional neural network potential (HDNNP).
    It contains all the required descriptors, scalers, neural networks, and a trainer to fit the potential using
    provided structure data and a potential setting file.
    """

    # TODO: split structures from the potential model
    # TODO: implement structure dumper/writer
    # TODO: split structure from the potential model (in design)

    _scaler_save_format: str = "scaling.{:03d}.data"
    _model_save_format: str = "weights.{:03d}.zip"

    def __init__(self, potfile: Path) -> None:
        """
        Initialize a HDNNP potential instance by reading the potential file and
        creating descriptors, scalers, models, and trainer.
        """
        self.potfile = Path(potfile)
        self.settings = NeuralNetworkPotentialSettings()
        super().__init__()

        self.settings.read(self.potfile)

        self.descriptor: Dict[str, Descriptor] = self.init_descriptor()
        self.scaler: Dict[str, DescriptorScaler] = self.init_scaler()
        self.model, self.model_params = self.init_model()

        # TODO: move training outside of the potential
        logger.debug("[Setting trainer]")
        self.trainer = NeuralNetworkPotentialTrainer(potential=self)

    def init_descriptor(self) -> Dict[str, Descriptor]:
        """
        Initialize descriptor for each element and add the relevant radial and angular
        symmetry functions from the potential settings.
        """
        # TODO: add logging
        logger.debug("[Setting descriptors]")
        descriptor = {}

        # Elements
        logger.info(f"Number of elements: {self.n_elements}")
        for element in self.elements:
            logger.info(f"Element: {element} ({ElementMap.get_atomic_number(element)})")

        # Instantiate ASF for each element
        for element in self.elements:
            descriptor[element] = ASF(element)

        # Add symmetry functions
        logger.debug(
            "Registering symmetry functions (radial and angular)"
        )  # TODO: move logging inside .add() method

        for cfg in self.settings["symfunction_short"]:
            if cfg[1] == 1:
                descriptor[cfg[0]].add(
                    symmetry_function=G1(
                        CutoffFunction(
                            r_cutoff=cfg[5], cutoff_type=self.settings["cutoff_type"]
                        )
                    ),
                    neighbor_element_j=cfg[2],
                )
            elif cfg[1] == 2:
                descriptor[cfg[0]].add(
                    symmetry_function=G2(
                        CutoffFunction(
                            r_cutoff=cfg[5], cutoff_type=self.settings["cutoff_type"]
                        ),
                        eta=cfg[3],
                        r_shift=cfg[4],
                    ),
                    neighbor_element_j=cfg[2],
                )
            elif cfg[1] == 3:
                descriptor[cfg[0]].add(
                    symmetry_function=G3(
                        CutoffFunction(
                            r_cutoff=cfg[7], cutoff_type=self.settings["cutoff_type"]
                        ),
                        eta=cfg[4],
                        zeta=cfg[6],
                        lambda0=cfg[5],
                        r_shift=0.0,
                    ),  # TODO: add r_shift!
                    neighbor_element_j=cfg[2],
                    neighbor_element_k=cfg[3],
                )
            elif cfg[1] == 9:
                descriptor[cfg[0]].add(
                    symmetry_function=G9(
                        CutoffFunction(
                            r_cutoff=cfg[7], cutoff_type=self.settings["cutoff_type"]
                        ),
                        eta=cfg[4],
                        zeta=cfg[6],
                        lambda0=cfg[5],
                        r_shift=0.0,
                    ),  # TODO: add r_shift!
                    neighbor_element_j=cfg[2],
                    neighbor_element_k=cfg[3],
                )

        return descriptor

    def init_scaler(self) -> Dict[str, DescriptorScaler]:
        """
        Initialize a descriptor scaler for each element from the potential settings.
        """
        logger.debug("[Setting scalers]")
        scaler = dict()

        # Prepare scaler input argument if exist in settings
        scaler_kwargs = {
            first: self.settings[second]
            for first, second in {
                "scale_type": "scale_type",
                "scale_min": "scale_min_short",
                "scale_max": "scale_max_short",
            }.items()
            if second in self.settings.keywords
        }
        logger.debug(f"Scaler kwargs={scaler_kwargs}")

        # Assign an ASF scaler to each element
        for element in self.elements:
            scaler[element] = DescriptorScaler(**scaler_kwargs)

        return scaler

    def init_model(self) -> Tuple[Dict[str, NeuralNetworkModel], frozendict]:
        """
        Initialize a neural network for each element using a dictionary representation of potential settings.
        """
        logger.debug("[Setting models]")
        model: Dict[str, NeuralNetworkModel] = dict()
        model_params: frozendict = dict()

        random_keys = random.split(random.PRNGKey(0), self.n_elements)

        for i, element in enumerate(self.elements):

            logger.debug(f"Element: {element}")

            # TODO: what if we have a different model architecture for each element
            hidden_layers = zip(
                self.settings["global_nodes_short"],
                self.settings["global_activation_short"][:-1],
            )
            output_layer: Tuple[int, str] = (
                1,
                self.settings["global_activation_short"][-1],
            )

            model_kwargs = {
                "hidden_layers": tuple([(n, t) for n, t in hidden_layers]),
                "output_layer": output_layer,
                "weights_range": (
                    self.settings["weights_min"],
                    self.settings["weights_max"],
                ),
            }
            model[element] = NeuralNetworkModel(**model_kwargs)

            model_params[element] = model[element].init(
                random_keys[i],
                jnp.ones((1, self.descriptor[element].n_symmetry_functions)),
            )["params"]

        return model, model_params

    # @Profiler.profile
    def fit_scaler(self, dataset: RunnerStructureDataset, **kwargs) -> None:
        """
        Fit scaler parameters for each element using the input structure data.
        No gradient history is required here.

        Args:
            structures (RunnerStructureDataset): Structure dataset
        """
        save_scaler: bool = kwargs.get("save_scaler", True)

        # loader = TorchDataLoader(dataset, collate_fn=lambda batch: batch)

        logger.info("Fitting descriptor scalers")
        for structure in dataset:
            for element in structure.elements:
                aid = structure.select(element)
                dsc_val = self.descriptor[element](structure, aid)
                # print(dsc_val.shape)
                self.scaler[element].fit(dsc_val)
        logger.debug("Finished scaler fitting.")

        if save_scaler:
            self.save_scaler()

    def save_scaler(self):
        """
        This method saves scaler parameters for each element into separate files.
        """
        # Save scaler parameters for each element separately
        for element in self.elements:
            atomic_number = ElementMap.get_atomic_number(element)
            scaler_fn = Path(
                self.potfile.parent, self._scaler_save_format.format(atomic_number)
            )
            logger.info(
                f"Saving scaler parameters for element ({element}): {scaler_fn.name}"
            )
            self.scaler[element].save(scaler_fn)

    # @Profiler.profile
    def load_scaler(self) -> None:
        """
        This method loads scaler parameters of each element from separate files.
        This save computational time as the would be no need to fit the scalers each time.
        """
        # Load scaler parameters for each element separately
        for element in self.elements:
            atomic_number = ElementMap.get_atomic_number(element)
            scaler_fn = Path(
                self.potfile.parent, self._scaler_save_format.format(atomic_number)
            )
            logger.debug(
                f"Loading scaler parameters for element {element}: {scaler_fn.name}"
            )
            self.scaler[element].load(scaler_fn)

    # @Profiler.profile
    def fit_model(self, dataset: RunnerStructureDataset, **kwargs) -> Dict:
        """
        Fit energy model for all elements using the input structure loader.
        """
        # TODO: avoid reading and calculating descriptor multiple times
        # TODO: descriptor element should be the same atom type as the aid
        # TODO: define a dataloader specific to energy and force data (shuffle, train & test split)
        # TODO: add validation output (MSE separate for force and energy)
        kwargs["validation_split"] = kwargs.get(
            "validation_split", self.settings["test_fraction"]
        )
        kwargs["epochs"] = kwargs.get("epochs", self.settings["epochs"])
        return self.trainer.fit(dataset, **kwargs)

    def save_model(self):
        """
        Save model weights separately for all elements.
        """
        for element in self.elements:
            logger.debug(f"Saving model weights for element: {element}")
            atomic_number = ElementMap.get_atomic_number(element)
            model_fn = Path(
                self.potfile.parent, self._model_save_format.format(atomic_number)
            )
            self.model[element].save(model_fn)

    # @Profiler.profile
    def load_model(self):
        """
        Load model weights separately for all elements.
        """
        for element in self.elements:
            logger.debug(f"Loading model weights for element: {element}")
            atomic_number = ElementMap.get_atomic_number(element)
            model_fn = Path(
                self.potfile.parent, self._model_save_format.format(atomic_number)
            )
            self.model[element].load(model_fn)

    def fit(self) -> None:
        """
        This method provides a user-friendly interface to fit both descriptor and model in one step.
        """
        pass

    def train(self, mode: bool = True) -> None:
        """
        Set pytorch models in training mode.
        This is because layers like dropout, batch normalization etc. behave differently on the train
        and test procedures.
        """
        for element in self.elements:
            self.model[element].train(mode)

    def eval(self) -> None:
        """
        Set pytorch models in evaluation mode.
        This is because layers like dropout, batch normalization etc. behave differently on the train
        and test procedures.
        """
        for element in self.elements:
            self.model[element].eval()

    def __call__(self, structure: Structure) -> jnp.ndarray:
        """
        Return the total energy of the input structure.

        :param structure: Structure
        :type structure: Structure
        :return: total energy
        :rtype: jnp.ndarray
        """

        return _energy_fn(
            self.get_static_inputs_per_element(),
            structure.get_position_per_element(),
            self.get_model_params_per_element(),
            structure.get_inputs_per_element(),
        )

    def get_static_inputs_per_element(self) -> Tuple:
        def extract_static_inputs():
            for element in self.elements:
                yield (
                    self.descriptor[element],
                    self.scaler[element],
                    self.model[element],
                )

        return tuple(inputs for inputs in extract_static_inputs())

    def get_model_params_per_element(self) -> Tuple[frozendict]:
        return tuple(params for params in self.model_params.values())

    def set_extrapolation_warnings(self, threshold: Union[int, None]) -> None:
        """
        shows warning whenever a descriptor value is out of bounds defined by
        minimum/maximum values in the scaler.

        set_extrapolation_warnings(None) will disable it.

        :param threshold: maximum number of warnings
        :type threshold: int
        """
        logger.info(f"Setting extrapolation warning: {threshold}")
        for scaler in self.scaler.values():
            scaler.set_max_number_of_warnings(threshold)

    @property
    def extrapolation_warnings(self) -> Dict[str, int]:
        return {
            element: scaler.number_of_warnings
            for element, scaler in self.scaler.items()
        }

    @property
    def elements(self) -> List[str]:
        return self.settings["elements"]

    @property
    def n_elements(self) -> int:
        return len(self.elements)

    @property
    def r_cutoff(self) -> float:
        """
        Return the maximum cutoff radius found between all descriptors.
        """
        return max([dsc.r_cutoff for dsc in self.descriptor.values()])

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(potfile='{self.potfile.name}')"

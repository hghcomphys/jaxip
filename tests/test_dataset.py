from pathlib import Path
from typing import Tuple

import jax.numpy as jnp
import pytest

from mlpot.datasets.runner import RunnerStructureDataset
from mlpot.structure.structure import Structure

h2o_filename = Path("tests", "h2o.data")
H2O_DATA = {
    "lattice": [
        [11.8086403654, 0.0, 0.0],
        [0.0, 11.8086403654, 0.0],
        [0.0, 0.0, 11.8086403654],
    ],
    "position": [
        [-0.0075149684, -0.99679652, 2.0432096893],
        [1.6785530169, -1.7652744389, 0.6272511261],
        [1.3209809278, -4.4733785988, 0.478346376],
        [2.5377510183, 6.6473573365, 1.7994898202],
        [6.4670963607, 4.0467540271, 1.709941368],
        [4.5666176862, 4.2124641117, 3.1394587162],
        [-2.7259110493, 1.4093199553, 3.2330757488],
        [-1.9756708773, -0.2319865595, 3.5377751905],
        [-0.4456843495, 0.2034309079, -5.3880816361],
        [-0.5311245372, 4.5221524303, -3.0878691928],
        [-2.2546133518, 0.9970025001, -3.8398101183],
        [-1.9353630189, 4.1351176211, -4.0833580223],
    ],
    "element": ["O", "H", "H", "O", "H", "H", "O", "H", "H", "O", "H", "H"],
    "charge": [
        0.442739,
        -0.244991,
        -0.31647,
        0.437298,
        -0.132604,
        -0.161461,
        0.452464,
        -0.432144,
        -0.0865354,
        0.430147,
        -0.0713622,
        -0.317081,
    ],
    "energy": [-0.0, -0.0, -0.0, -0.0, -0.0, -0.0, 0.0, -0.0, -0.0, -0.0, -0.0, -0.0],
    "force": [
        [0.0576867169, -0.2578270722, -0.2339365489],
        [-0.5157027617, -1.4143481512, -0.1199800167],
        [0.261360575, 2.1511972322, 0.444809068],
        [0.1560563599, -0.4345566594, -0.2367582949],
        [0.3723498983, 0.1835258917, -0.51876176],
        [-0.4569867202, -0.1613043018, 0.6545692241],
        [0.0005268906, -0.0777825655, -0.2173794536],
        [0.172259716, 0.0451839124, 0.3493889371],
        [-0.3358675037, -0.0775036969, 0.0481281739],
        [0.239214439, 0.0010185589, 0.3207105856],
        [0.3703935397, -0.16099179, -0.1473258662],
        [-0.3212920481, 0.2033815711, -0.343463465],
    ],
    "total_energy": [-32.2949885081],
    "total_charge": [-6e-07],
    "atom_type": [2, 1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1],
}


class TestRunnerStructureDataset:

    h2o: RunnerStructureDataset = RunnerStructureDataset(filename=h2o_filename)
    h2o_raw: RunnerStructureDataset = RunnerStructureDataset(
        filename=h2o_filename, transform=lambda x: x  # type: ignore
    )
    h2o_persist: RunnerStructureDataset = RunnerStructureDataset(
        filename=h2o_filename, persist=True
    )

    @pytest.mark.parametrize(
        "dataset",
        [
            h2o,
        ],
    )
    def test_mandatory_methods(
        self,
        dataset: RunnerStructureDataset,
    ) -> None:
        getattr(dataset, "__len__")
        getattr(dataset, "__getitem__")

    @pytest.mark.parametrize(
        "dataset, expected",
        [
            (
                h2o,
                (2, Structure),
            ),
            (
                h2o_raw,
                (2, dict),
            ),
        ],
    )
    def test_general(
        self,
        dataset: RunnerStructureDataset,
        expected: Tuple,
    ) -> None:
        assert len(dataset) == expected[0]
        for index in range(len(dataset)):
            assert isinstance(dataset[index], expected[1])

    @pytest.mark.parametrize(
        "dataset, expected",
        [
            (
                h2o,
                (0, 0, 0, 0),
            ),
            (
                h2o_persist,
                (0, 1, 1, 2),
            ),
        ],
    )
    def test_caching(
        self,
        dataset: RunnerStructureDataset,
        expected: Tuple,
    ) -> None:
        assert len(dataset._cached_structures) == expected[0]
        dataset[0]
        assert len(dataset._cached_structures) == expected[1]
        dataset[0]
        assert len(dataset._cached_structures) == expected[2]
        dataset[1]
        assert len(dataset._cached_structures) == expected[3]

    @pytest.mark.parametrize(
        "dataset, expected",
        [
            (
                h2o,
                tuple(
                    jnp.asarray(H2O_DATA[attr])
                    for attr in Structure._get_atom_attributes()
                ),
            ),
        ],
    )
    def test_loading_structure(
        self,
        dataset: RunnerStructureDataset,
        expected: Tuple,
    ) -> None:
        structure: Structure = dataset[1]
        for i, attr in enumerate(Structure._get_atom_attributes()):
            if attr == "position":
                assert jnp.all(
                    structure.position == structure.box.shift_inside_box(expected[i])
                )
            else:
                assert jnp.all(getattr(structure, attr) == expected[i])

from torchip.descriptors.asf.symmetry import SymmetryFunction
from ...logger import logger
from ...structure import Structure
from ...config import TaskClient
from ..base import Descriptor
from .angular import AngularSymmetryFunction
from .radial import RadialSymmetryFunction
from typing import Tuple, Union, List, Dict
import itertools
import torch
from torch import Tensor


class AtomicSymmetryFunction(Descriptor):
    """
    Atomic Symmetry Function (ASF) descriptor.
    ASF is a vector of different radial and angular terms which describe the chemical environment of an atom.
    TODO: ASF should be independent of the input structure, but it should knows how to calculate the descriptor vector.
    See N2P2 -> https://compphysvienna.github.io/n2p2/topics/descriptors.html?highlight=symmetry%20function#
    """

    def __init__(self, element: str) -> None:
        super().__init__(element)  # central element
        self._radial: Tuple[RadialSymmetryFunction, str, str] = list()
        self._angular: Tuple[AngularSymmetryFunction, str, str, str] = list()
        # self.__cosine_similarity = torch.nn.CosineSimilarity(dim=1, eps=1e-8) # instantiate
        logger.debug(f"Initializing {self}")

    def register(
        self,
        symmetry_function: SymmetryFunction,
        neighbor_element1: str,
        neighbor_element2: str = None,
    ) -> None:
        """
        This method registers an input symmetry function to the list of ASFs and assign it to the given neighbor element(s).
        # TODO: tuple of dict? (tuple is fine if it's used internally)
        # TODO: solve the confusion for aid, starting from 0 or 1?!
        """
        if isinstance(symmetry_function, RadialSymmetryFunction):
            self._radial.append((symmetry_function, self.element, neighbor_element1))
        elif isinstance(symmetry_function, AngularSymmetryFunction):
            self._angular.append(
                (symmetry_function, self.element, neighbor_element1, neighbor_element2)
            )
        else:
            logger.error(f"Unknown input symmetry function type", exception=TypeError)

    def __call__(
        self,
        structure: Structure,
        aid: Union[List[int], int] = None,
    ) -> Tensor:
        """
        Calculate descriptor values for the input given structure and atom id(s).
        """
        # Update neighbor list if needed
        structure.update_neighbor()

        # Check number of symmetry functions
        if self.n_descriptor == 0:
            logger.warning(
                f"No symmetry function was found: radial={self.n_radial}, angular={self.n_angular}"
            )

        # TODO: raise ValueError("Unknown atom id type")
        aids_ = [aid] if isinstance(aid, int) else aid
        # TODO: optimize ifs here
        aids_ = structure.select(self.element) if aids_ is None else aids_

        # ================ TODO: Parallel Computing ====================
        if TaskClient.client is None:
            results = [self.compute(structure, aid_) for aid_ in aids_]
        else:
            logger.debug(f"Parallelizing {self.__class__.__name__} computing kernel")
            tensors = [
                structure.position,
                structure.atype,
                structure.neighbor.number,
                structure.neighbor.index,
            ]
            params = {
                "lattice": structure.box.lattice,
                "emap": structure.element_map.element_to_atype,
                "dtype": structure.dtype,
                "device": structure.device,
            }
            scattered_tensors = TaskClient.client.scatter(tensors, broadcast=True)
            futures = [
                TaskClient.client.submit(
                    self._compute, *scattered_tensors, aid_, **params
                )
                for aid_ in aids_
            ]
            results = TaskClient.client.gather(futures)
        # ===========================================================

        # Return descriptor values
        return torch.stack(results, dim=0)  # torch.squeeze(torch.stack(results, dim=0))

    # TODO: static method?
    def _compute(
        self,
        pos: Tensor,
        at: Tensor,
        nn: Tensor,
        ni: Tensor,
        aid: int,
        lattice: Tensor,
        emap: Dict[str, int],
        dtype,
        device,
    ) -> Tensor:
        """
        [Kernel]
        Compute descriptor values of an input atom id for the given structure tensors.
        """
        # A tensor for final descriptor values of a single atom
        result = torch.zeros(self.n_descriptor, dtype=dtype, device=device)

        # Check aid atom type match the central element
        if not emap[self.element] == at[aid]:
            logger.error(
                f"Inconsistent central element ('{self.element}'): input aid={aid} (atype='{int(at[aid])}')",
                exception=ValueError,
            )

        # Get the list of neighboring atom indices
        ni_ = ni[aid, : nn[aid]]
        # Calculate distances of neighboring atoms (detach flag must be disabled to keep the history of gradients)
        dis_, diff_ = Structure._calculate_distance(
            pos, aid, lattice=lattice, neighbors=ni_, return_difference=True
        )  # self-count excluded, PBC applied
        # Get the corresponding neighboring atom types and position
        at_ = at[ni_]  # at_ refers to the array atom type of neighbors
        # x_ = x[ni_]    # x_ refers to the array position of neighbor atoms

        # print("i", aid)
        # Loop over the radial terms
        for radial_index, radial in enumerate(self._radial):
            # Find neighboring atom indices that match the given ASF cutoff radius AND atom type
            ni_rc__ = (dis_ <= radial[0].r_cutoff).detach()  # a logical array
            ni_rc_at_ = torch.nonzero(
                torch.logical_and(
                    ni_rc__,
                    at_ == emap[radial[2]],
                ),
                as_tuple=True,
            )[0]
            # Apply radial ASF term kernels and sum over the all neighboring atoms and finally return the result
            # print(aid.numpy(), radial[1], radial[2],
            #   radial[0].kernel(dis_[ni_rc_at_]).detach().numpy(),
            #   torch.sum( radial[0].kernel(dis_[ni_rc_at_] ), dim=0).detach().numpy())
            result[radial_index] = torch.sum(radial[0].kernel(dis_[ni_rc_at_]), dim=0)

        # Loop over the angular terms
        for angular_index, angular in enumerate(self._angular, start=self.n_radial):
            # Find neighboring atom indices that match the given ASF cutoff radius
            ni_rc__ = (dis_ <= angular[0].r_cutoff).detach()  # a logical array
            # Find LOCAL indices of neighboring elements j and k (can be used for ni_, at_, dis_, and x_ arrays)
            at_j, at_k = emap[angular[2]], emap[angular[3]]
            # local index
            ni_rc_at_j_ = torch.nonzero(
                torch.logical_and(
                    ni_rc__,
                    at_ == at_j,
                ),
                as_tuple=True,
            )[0]
            # local index
            ni_rc_at_k_ = torch.nonzero(
                torch.logical_and(
                    ni_rc__,
                    at_ == at_k,
                ),
                as_tuple=True,
            )[0]

            # Apply angular ASF term kernels and sum over the neighboring atoms
            # loop over neighbor element 1 (j)
            for j in ni_rc_at_j_:
                # ----
                ni_j_ = ni_[j]  # neighbor atom index for j (scalar)
                # k = ni_rc_at_k_[ ni_[ni_rc_at_k_] > ni_j_ ]
                # # apply k > j (k,j != i is already applied in the neighbor list)
                if at_j == at_k:  # TODO: why? dedicated k and j list to each element
                    k = ni_rc_at_k_[ni_[ni_rc_at_k_] > ni_j_]
                else:
                    k = ni_rc_at_k_[ni_[ni_rc_at_k_] != ni_j_]
                ni_k_ = ni_[k]  # neighbor atom index for k (an array)
                # ---
                rij = dis_[j]  # shape=(1), LOCAL index j
                rik = dis_[k]  # shape=(*), LOCAL index k (an array)
                Rij = diff_[j]  # x[aid] - x[ni_j_] # shape=(3)
                Rik = diff_[k]  # x[aid] - x[ni_k_] # shape=(*, 3)
                # ---
                rjk = Structure._calculate_distance(
                    pos, ni_j_, lattice=lattice, neighbors=ni_k_
                )  # shape=(*)
                # Rjk = structure.apply_pbc(x[ni_j_] - x[ni_k_])   # shape=(*, 3)
                # ---
                # Cosine of angle between k--<i>--j atoms
                # TODO: move cosine calculation to structure
                # cost = self.__cosine_similarity(Rij.expand(Rik.shape), Rik)   # shape=(*)
                cost = torch.inner(Rij, Rik) / (rij * rik)
                # ---
                # Broadcasting computation (avoiding to use the in-place add() because of autograd)
                result[angular_index] = result[angular_index] + torch.sum(
                    angular[0].kernel(rij, rik, rjk, cost),
                    dim=0,
                )

        return result

    def compute(self, structure: Structure, aid: int) -> Tensor:
        """
        Compute descriptor values of an input atom id for the given structure.
        """
        return self._compute(
            pos=structure.position,
            at=structure.atype,
            nn=structure.neighbor.number,
            ni=structure.neighbor.index,
            aid=aid,
            lattice=structure.box.lattice,
            emap=structure.element_map.element_to_atype,
            dtype=structure.dtype,
            device=structure.device,
        )

    @property
    def n_radial(self) -> int:
        return len(self._radial)

    @property
    def n_angular(self) -> int:
        return len(self._angular)

    @property
    def n_descriptor(self) -> int:
        return self.n_radial + self.n_angular

    @property
    def r_cutoff(self) -> float:
        """
        Return the maximum cutoff radius of all descriptor terms.
        """
        return max(
            [cfn[0].r_cutoff for cfn in itertools.chain(*[self._radial, self._angular])]
        )


ASF = AtomicSymmetryFunction

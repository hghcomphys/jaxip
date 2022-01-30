from ...logger import logger
from ...structure import Structure
from ..base import Descriptor
from .angular import AngularSymmetryFunction
from .radial import RadialSymmetryFunction
from typing import Union
import torch


class ASF(Descriptor):
  """
  Atomic Symmetry Function (ASF) descriptor.
  ASF is a vector of different radial and angular terms which describe the chemical environment of an atom.
  TODO: ASF should be independent of the input structure, but it should knows how to calculate the descriptor vector.
  See N2P2 -> https://compphysvienna.github.io/n2p2/topics/descriptors.html?highlight=symmetry%20function#
  """
  def __init__(self, element: str) -> None:
    self.element = element    # central element
    self._radial = []         # tuple(RadialSymmetryFunction , central_element, neighbor_element1)
    self._angular = []        # tuple(AngularSymmetryFunction, central_element, neighbor_element1, neighbor_element2)
    self.__cosine_similarity = torch.nn.CosineSimilarity(dim=1, eps=1e-6) # instantiate 

  def add(self, symmetry_function: Union[RadialSymmetryFunction,  AngularSymmetryFunction],
                neighbor_element1: str, 
                neighbor_element2: str = None) -> None:
    """
    This method adds an input radial symmetry function to the list of ASFs.
    # TODO: tuple of dict? (tuple is fine if it's used internally)
    # TODO: solve the confusion for aid, starting from 0 or 1?!
    """
    if isinstance(symmetry_function, RadialSymmetryFunction):
      self._radial.append((symmetry_function, self.element, neighbor_element1))
    elif isinstance(symmetry_function, AngularSymmetryFunction):
      self._angular.append((symmetry_function, self.element, neighbor_element1, neighbor_element2))
    else:
      msg = f"Unknown input symmetry function type"
      logger.error(msg)
      raise TypeError(msg)

  def __call__(self, structure:Structure, aid: int) -> torch.tensor: 
    """
    Calculate descriptor values for the input given structure.
    """
    # Update neighbor list first if needed
    if not structure.is_neighbor:
      structure.update_neighbor()

    x = structure.position            # tensor
    at = structure.atype              # tensor
    nn  = structure.neighbor.number   # tensor
    ni = structure.neighbor.index     # tensor
    emap= structure.element_map       # element map instance

    # Create output tensor
    if self.n_descriptor == 0:
      logger.warning(f"No symmetry function was found: radial={self.n_radial}, angular={self.n_angular}")
    result = torch.zeros(self.n_radial + self.n_angular, dtype=structure.dtype, device=structure.device)

    # Check aid atom type match the central element
    if not emap[self.element] == at[aid]:
      msg = f"Inconsistent central element ('{self.element}'): input aid={aid} ('{emap[int(at[aid])]}')"
      logger.error(msg)
      raise AssertionError(msg)

    # Get the list of neighboring atom indices
    ni_ = ni[aid, :nn[aid]]                                                    
    # Calculate distances of only neighboring atoms (detach flag must be disabled to keep the history of gradients)
    dis_ = structure.calculate_distance(aid, detach=False, neighbors=ni_) # self-count excluded, PBC applied
    # Get the corresponding neighboring atom types and position
    at_ = at[ni_]   # at_ refers to the array atom type of only neighbors
    #x_ = x[ni_]     # x_ refers to the array position of only neighbor atoms
    
    # Loop over the radial terms
    for index, sf in enumerate(self._radial):
      # Find neighboring atom indices that match the given ASF cutoff radius AND atom type
      ni_rc__ = ( dis_ < sf[0].r_cutoff ).detach() # a logical array
      ni_rc_at_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == emap(sf[2]) ), as_tuple=True)[0]
      # Apply radial ASF term kernels and sum over the all neighboring atoms and finally return the result
      result[index] = torch.sum( sf[0].kernel(dis_[ni_rc_at_] ), dim=0)

    # Loop over the angular terms
    for index, sf in enumerate(self._angular, start=self.n_radial):
      # Find neighboring atom indices that match the given ASF cutoff radius
      ni_rc__ = (dis_ < sf[0].r_cutoff ).detach() # a logical array
      # Find LOCAL indices of neighboring elements j and k (can be used for ni_, at_, dis_, and x_ arrays)
      ni_rc_at_j_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == emap(sf[2])), as_tuple=True)[0]  # local index
      ni_rc_at_k_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == emap(sf[3])), as_tuple=True)[0]  # local index
      # Apply angular ASF term kernels and sum over the neighboring atoms
      # loop over neighbor element 1 (j)
      for j in ni_rc_at_j_:                                                            
        ni_j_ = ni_[j]                                                      # neighbor atom index for j
        ni_k__ = ni_rc_at_k_[ ni_[ni_rc_at_k_] > ni_j_ ]                    # apply k > j (k,j != i already applied in neighbor list)
        ni_k_  = ni_[ni_k__]                                                # neighbor atom index for k (an array)
        # ---
        Rij = x[aid] - x[ni_j_]                                             # shape=(3)
        Rik = x[aid] - x[ni_k_]                                             # shape=(*, 3)
        #Rjk = x[ni_j_] - x[ni_k_]                                          # shape=(*, 3)
        # TODO: move cosine calculation to structure
        cost = self.__cosine_similarity(Rij.expand(Rik.shape), Rik)         # shape=(*)
        # ---
        rij = dis_[j]                                                      # shape=(1), LOCAL index (j)
        rik = dis_[ni_k__]                                                 # shape=(*), LOCAL index (k) - an array 
        rjk = structure.calculate_distance(j, neighbors=ni_k_)             # shape=(*)
        # Broadcasting computation
        result[index] += torch.sum( sf[0].kernel(rij, rik, rjk, cost), dim=0)  

    # Return array of ASF values
    return result

  @property
  def n_radial(self) -> int:
    return len(self._radial)

  @property
  def n_angular(self) -> int:
    return len(self._angular)

  @property
  def n_descriptor(self) -> int:
    return self.n_radial + self.n_angular



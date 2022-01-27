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
    elif isinstance(symmetry_function, RadialSymmetryFunction):
      self._angular((symmetry_function, self.element, neighbor_element1, neighbor_element2))
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

    #x = structure.position           # tensor
    at = structure.atype              # tensor
    nn  = structure.neighbor.number   # tensor
    ni = structure.neighbor.index     # tensor
    emap= structure.element_map       # element map instance

    # Create output tensor
    result = torch.zeros(len(self._radial), dtype=structure.dtype, device=structure.device)

    # Check aid atom type match the central element
    if not emap[self.element] == at[aid]:
      msg = f"Inconsistent central element ('{self.element}'): input aid={aid} ('{emap[int(at[aid])]}')"
      logger.error(msg)
      raise AssertionError(msg)

    # Get the list of neighboring atom indices
    ni_ = ni[aid, :nn[aid]]
    # Calculate the distances of neighboring atoms (detach flag must be disabled to keep the history of gradients)
    rij = structure.calculate_distance(aid, detach=False, neighbors=ni_)
    # Get the corresponding neighboring atom types
    tij = at[ni_] 
    
    # Loop over the radial terms
    for i, sf in enumerate(self._radial):
      # Find the neighboring atom indices that match the given ASF cutoff radius AND atom type
      ni_rc_ = (rij < sf[0].r_cutoff ).detach()
      ni_ = torch.nonzero( torch.logical_and(ni_rc_, tij == emap(sf[2]) ), as_tuple=True)[0]
      # Apply the ASF term kernels and sum over the neighboring atoms
      result[i] = torch.sum( sf[0].kernel(rij[ni_] ), dim=0)

    # TODO: add angular terms

    return result



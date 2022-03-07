from ...logger import logger
from ...structure import Structure
from ..base import Descriptor
from .angular import AngularSymmetryFunction
from .radial import RadialSymmetryFunction
from typing import Union, List
import itertools
import torch


class AtomicSymmetryFunction(Descriptor):
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
    self.result = None        # descriptor values after call method
    self.__cosine_similarity = torch.nn.CosineSimilarity(dim=1, eps=1e-8) # instantiate 
    logger.debug(f"Initializing {self.__class__.__name__} with central element ('{self.element}')") # TODO: define __repr__

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

  def __call__(self, structure:Structure, aid: Union[List[int], int]) -> torch.Tensor: 
    """
    Calculate descriptor values for the input given structure and atom id(s).
    """
    # Update neighbor list first if needed
    if not structure.is_neighbor:
      structure.update_neighbor()

    # Check number of symmetry functions
    if self.n_descriptor == 0:
      logger.warning(f"No symmetry function was found: radial={self.n_radial}, angular={self.n_angular}")

    if isinstance(aid, int):
      self.result = torch.zeros((1, self.n_descriptor), dtype=structure.dtype, device=structure.device)
      self._compute(structure, aid)
    else:
      # TODO: optimization, process pool?
      self.result = torch.zeros((len(aid), self.n_descriptor), dtype=structure.dtype, device=structure.device)
      for index, aid_ in enumerate(aid):
        self._compute(structure, aid_, index)
    # else:
    #   raise ValueError("Unknown atom id type")
    self.result = torch.squeeze(self.result)
    
    return self.result
        
   
  def _compute(self, structure:Structure, aid: int, index=0) -> None:
    """
    Comute descriptor vector for an input atom id. 
    """
    x = structure.position            # tensor
    at = structure.atype              # tensor
    nn  = structure.neighbor.number   # tensor
    ni = structure.neighbor.index     # tensor
    emap= structure.element_map       # element map instance

    # Check aid atom type match the central element
    if not emap[self.element] == at[aid]:
      msg = f"Inconsistent central element ('{self.element}'): input aid={aid} ('{emap[int(at[aid])]}')"
      logger.error(msg)
      raise AssertionError(msg)
        
    # Get the list of neighboring atom indices
    ni_ = ni[aid, :nn[aid]]                                                    
    # Calculate distances of only neighboring atoms (detach flag must be disabled to keep the history of gradients)
    dis_, diff_ = structure.calculate_distance(aid, neighbors=ni_, difference=True) # self-count excluded, PBC applied
    # Get the corresponding neighboring atom types and position
    at_ = at[ni_]   # at_ refers to the array atom type of only neighbors
    #x_ = x[ni_]    # x_ refers to the array position of only neighbor atoms
    
    # print("i", aid)
    # Loop over the radial terms
    for radial_i, radial in enumerate(self._radial):
      # Find neighboring atom indices that match the given ASF cutoff radius AND atom type
      ni_rc__ = ( dis_ <= radial[0].r_cutoff ).detach() # a logical array
      ni_rc_at_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == emap(radial[2]) ), as_tuple=True)[0]
      # Apply radial ASF term kernels and sum over the all neighboring atoms and finally return the result
      # print(aid.numpy(), radial[1], radial[2],
      #   radial[0].kernel(dis_[ni_rc_at_]).detach().numpy(),
      #   torch.sum( radial[0].kernel(dis_[ni_rc_at_] ), dim=0).detach().numpy())
      self.result[index, radial_i] = torch.sum( radial[0].kernel(dis_[ni_rc_at_] ), dim=0)

    # Loop over the angular terms
    for angular_i, angular in enumerate(self._angular, start=self.n_radial):
      # Find neighboring atom indices that match the given ASF cutoff radius
      ni_rc__ = (dis_ <= angular[0].r_cutoff ).detach() # a logical array
      # Find LOCAL indices of neighboring elements j and k (can be used for ni_, at_, dis_, and x_ arrays)
      at_j, at_k = emap(angular[2]), emap(angular[3])
      ni_rc_at_j_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == at_j), as_tuple=True)[0]  # local index
      ni_rc_at_k_ = torch.nonzero( torch.logical_and(ni_rc__, at_ == at_k), as_tuple=True)[0]  # local index
      # print("j", ni_[ni_rc_at_j_].detach().numpy())
      # print("k", ni_[ni_rc_at_k_].detach().numpy())

      # Apply angular ASF term kernels and sum over the neighboring atoms
      # loop over neighbor element 1 (j)
      for j in ni_rc_at_j_:     
        #----
        ni_j_ = ni_[j]                                                # neighbor atom index for j (a scaler)
        # k = ni_rc_at_k_[ ni_[ni_rc_at_k_] > ni_j_ ]                 # apply k > j (k,j != i is already applied in the neighbor list)
        if at_j == at_k:  # TODO: why? dedicated k and j list to each element 
           k = ni_rc_at_k_[ ni_[ni_rc_at_k_] > ni_j_ ]
        else:
           k = ni_rc_at_k_[ ni_[ni_rc_at_k_] != ni_j_ ]
        ni_k_  = ni_[k]                                               # neighbor atom index for k (an array)
        # ---
        rij = dis_[j]                                                 # shape=(1), LOCAL index j
        rik = dis_[k]                                                 # shape=(*), LOCAL index k (an array) 
        Rij = diff_[j] #x[aid] - x[ni_j_]                             # shape=(3)
        Rik = diff_[k] #x[aid] - x[ni_k_]                             # shape=(*, 3)
        # ---
        rjk = structure.calculate_distance(ni_j_, neighbors=ni_k_)    # shape=(*)
        #Rjk = structure.apply_pbc(x[ni_j_] - x[ni_k_])               # shape=(*, 3)
        # ---
        # Cosine of angle between k--<i>--j atoms
        # TODO: move cosine calculation to structure
        # cost = self.__cosine_similarity(Rij.expand(Rik.shape), Rik)   # shape=(*)
        cost = torch.inner(Rij, Rik)/(rij*rik)
        # ---
        # Broadcasting computation
        self.result[index, angular_i] += torch.sum(angular[0].kernel(rij, rik, rjk, cost), dim=0)  

        # Debugging --------------------------------------------
        # ni_j_ = ni_[j] # atom index i
        # rij = dis_[j]  
        # Rij = structure.apply_pbc(x[aid] - x[ni_j_])
        # for k in ni_rc_at_k_:
        #   ni_k_ = ni_[k]  # atom index j
            
        #   # if (ni_k_ <= ni_j_):
        #   #   continue
        #   if at_j == at_k: 
        #     if ni_k_ <= ni_j_:
        #       continue
        #   else:
        #     if ni_k_ == ni_j_:
        #       continue
        #     pass

        #   rjk = structure.calculate_distance(ni_j_, neighbors=ni_k_)[0]
        #   # if rjk > angular[0].r_cutoff: 
        #   #   continue

        #   rik = dis_[k]          
        #   Rik = structure.apply_pbc(x[aid] - x[ni_k_])

        #   cost = self.__cosine_similarity(torch.unsqueeze(Rij, 0), torch.unsqueeze(Rik, 0))[0] 
        #   # cost = torch.inner(Rij, Rik)/(rij*rik)
        #   kernel = angular[0].kernel(rij, rik, rjk, cost)
        #   self.result[index, angular_i] += kernel

        #   if index == 0 and angular_i == 2:
        #     print(f"i={aid}({emap[int(at[aid])]}), j={ni_j_.numpy()}({emap[int(at[ni_j_.numpy()])]}), k={ni_k_.numpy()}({emap[int(at[ni_k_.numpy()])]})"\
        #       f", rij={rij.detach().numpy()}, rik={rik.detach().numpy()}, rjk={rjk.detach().numpy()}, cost={cost.detach().numpy()}"\
        #         # f", local_j={j}, local_k={k}"\
        #         f", kernel[{index}, {angular_i}]={kernel}")        
        # --------------------------------------------
      # print(f"result[{index}, {angular_i}]={self.result[index, angular_i].detach().numpy()}")

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
    Return the maximum cutoff radius.
    """
    return max([ \
      cfn[0].r_cutoff for cfn in itertools.chain(*[self._radial, self._angular])
    ])

# Define ASF alias
ASF = AtomicSymmetryFunction
 
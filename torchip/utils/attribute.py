from ..logger import logger
from ..config import dtype, device
from typing import Dict, Any
from torch import Tensor
import torch


def set_as_attribute(obj: Any, items: Dict[str, Tensor]) -> None:
  """
  An utility function to set an input dictionary of items as the class attributes.

  Args:
      obj (Any): an instance
      tensors (Dict): a dictionary of items
  """  
  logger.debug(f"Setting {len(items)} items as the {obj.__class__.__name__}"
              f" attributes: {', '.join(items.keys())}")
  for name, item in items.items():
    setattr(obj, name, item)


def cast_to_tensor(x) -> Tensor:
  """
  An utility function to cast input variable (scaler, array, etc) 
  to torch tensor with predefined data and device types.

  Args:
      x (Any): input variable (e.g. scaler, array)

  Returns:
      Tensor: casted input to a tensor
  """  
  return torch.tensor(x, dtype=dtype.FLOATX, device=device.DEVICE) 
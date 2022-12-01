from ...structure._structure import _calculate_distance_per_atom
from ...structure._neighbor import _calculate_cutoff_mask_per_atom
from .angular import AngularSymmetryFunction
from .radial import RadialSymmetryFunction
from typing import Callable, Tuple, Dict
from functools import partial
from jax import jit, vmap, lax
import jax.numpy as jnp


@partial(jit, static_argnums=(0,))  # FIXME
def _calculate_radial_asf_per_atom(
    radial: Tuple[RadialSymmetryFunction, str, str],
    atype: jnp.ndarray,
    dist_i: jnp.ndarray,
    emap: Dict,
) -> jnp.ndarray:

    # cutoff-radius mask
    mask_cutoff_i = _calculate_cutoff_mask_per_atom(
        dist_i, jnp.asarray(radial[0].r_cutoff)
    )
    # get the corresponding neighboring atom types
    mask_cutoff_and_atype_ij = mask_cutoff_i & (atype == emap[radial[2]])

    return jnp.sum(
        radial[0](dist_i),
        where=mask_cutoff_and_atype_ij,
        axis=0,
    )


@partial(jit, static_argnums=(0,))  # FIXME
def _calculate_angular_asf_per_atom(
    angular: Tuple[AngularSymmetryFunction, str, str, str],
    atype: jnp.ndarray,
    diff_i: jnp.ndarray,
    dist_i: jnp.ndarray,
    lattice: jnp.ndarray,
    emap: Dict,
) -> jnp.ndarray:

    # cutoff-radius mask
    mask_cutoff_i = _calculate_cutoff_mask_per_atom(
        dist_i, jnp.asarray(angular[0].r_cutoff)
    )
    # mask for neighboring element j
    at_j = emap[angular[2]]
    mask_cutoff_and_atype_ij = mask_cutoff_i & (atype == at_j)
    # mask for neighboring element k
    at_k = emap[angular[3]]
    mask_cutoff_and_atype_ik = mask_cutoff_i & (atype == at_k)

    total, _ = lax.scan(
        partial(
            _inner_loop_over_angular_asf_terms,
            mask_ik=mask_cutoff_and_atype_ik,
            diff_i=diff_i,
            dist_i=dist_i,
            lattice=lattice,
            kernel=angular[0],
        ),
        0.0,
        (diff_i, dist_i, mask_cutoff_and_atype_ij),
    )
    # correct double-counting
    total = lax.cond(
        at_j == at_k,
        lambda x: x * 0.5,
        lambda x: x,
        total,
    )

    return total


# Called by jax.lax.scan (no need for @jax.jit)
def _inner_loop_over_angular_asf_terms(
    total: jnp.ndarray,
    inputs: Tuple[jnp.ndarray],
    diff_i: jnp.ndarray,
    dist_i: jnp.ndarray,
    mask_ik: jnp.ndarray,
    lattice: jnp.ndarray,
    kernel: Callable,
) -> Tuple[jnp.ndarray, jnp.ndarray]:

    # Scan occurs along the leading axis
    Rij, rij, mask_ij = inputs

    # rik = jnp.where(
    #     mask_cutoff_and_atype_ik,
    #     dist_i,
    #     0.0,
    # ) # same for Rjk if using diff_i

    # fix nan issue in gradient
    # see https://github.com/google/jax/issues/1052#issuecomment-514083352
    operand = rij * dist_i
    is_zero = operand == 0.0
    true_op = jnp.where(is_zero, 1.0, operand)
    cost = jnp.where(
        mask_ik,
        jnp.inner(Rij, diff_i) / true_op,
        1.0,
    )
    cost = jnp.where(is_zero, 0.0, cost)  # FIXME: gradient value!

    rjk = jnp.where(  # diff_jk = diff_ji - diff_ik
        mask_ik,
        _calculate_distance_per_atom(Rij, diff_i, lattice)[0],
        0.0,
    )  # second tuple output for Rjk

    value = jnp.where(
        mask_ij,
        jnp.sum(
            kernel(rij, dist_i, rjk, cost),
            where=mask_ik & (rjk > 0.0),  # exclude k=j
            axis=0,
        ),
        0.0,
    )
    return total + value, value


@partial(jit, static_argnums=(0, 5))  # FIXME
def _calculate_descriptor_per_atom(
    asf,
    atom_position: jnp.ndarray,  # must be a single atom position shape=(1, 3)
    neighbor_positions: jnp.ndarray,
    atype: jnp.ndarray,
    lattice: jnp.ndarray,
    dtype: jnp.dtype,
    emap: Dict,
) -> jnp.ndarray:
    """
    Compute descriptor values per atom in the structure (via atom id).
    """
    result = jnp.empty(asf.n_symmetry_functions, dtype=dtype)

    dist_i, diff_i = _calculate_distance_per_atom(
        atom_position, neighbor_positions, lattice
    )

    # Loop over the radial terms
    for index, radial in enumerate(asf._radial):
        result = result.at[index].set(
            _calculate_radial_asf_per_atom(radial, atype, dist_i, emap)
        )

    # Loop over the angular terms
    for index, angular in enumerate(
        asf._angular, start=asf.n_radial_symmetry_functions
    ):
        result = result.at[index].set(
            _calculate_angular_asf_per_atom(
                angular, atype, diff_i, dist_i, lattice, emap
            )
        )

    return result


_calculate_descriptor = jit(
    vmap(
        _calculate_descriptor_per_atom,
        in_axes=(None, 0, None, None, None, None, None),
    ),
    static_argnums=(0, 5),  # FIXME
)

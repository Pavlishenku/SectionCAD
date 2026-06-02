"""
Finite Difference Method (FDM) for the St-Venant torsional constant J.

Solves the Prandtl stress-function equation on a regular Cartesian grid:

    ∇²φ = −2   inside the section (between outer boundary and holes)
    φ = 0       on the outer boundary
    φ = c_k     on hole k  (c_k determined by compatibility condition)

Torsional constant:  J = 2 ∫∫_D φ dA  ≈  2 h² Σ φ_i

For multi-connected sections (holes), each hole k contributes an unknown
constant c_k that is determined from the compatibility (single-valuedness
of the warping function):

    ∮_{Γk} ∂φ/∂n ds = −2 A_k

In discrete form this becomes one additional equation per hole:

    N_{f,k} · c_k − Σ_{adj. interior cells} φ_i = −2 A_k_discrete

where N_{f,k} = number of cell faces on the interface between hole k
and the interior, and A_k_discrete = (number of hole-k cells) × h².

Advantages over BEM:
  • Robust for any polygon shape — no singularities at sharp corners
  • Naturally handles composite sections (holes of any shape)
  • Accuracy improves monotonically with grid refinement
  • ~1–3 % for solid / closed sections with n_cells=150
  • ~2–5 % for open thin-walled sections (web ≥ 3 cells wide)

References
----------
Pilkey W.D. (2002)   Analysis and Design of Elastic Beams. Wiley, §6.2–6.3.
Timoshenko & Goodier (1970)  Theory of Elasticity. McGraw-Hill, §107–111.
Sadd M.H. (2005)     Elasticity: Theory, Applications and Numerics.
                     Elsevier, §9.5.
"""

import math
import logging
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from typing import List, Tuple, Optional

_log = logging.getLogger(__name__)

Pts = List[Tuple[float, float]]

# Cell-type labels stored in the integer grid array
_EXT       = 0   # outside all outer polygons
_INT       = 1   # interior of section  (solve ∇²φ = −2 here)
_HOLE_BASE = 2   # hole k  → grid value  _HOLE_BASE + k  (k ≥ 0)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bbox(outer_polygons: List[Pts]) -> Tuple[float, float, float, float]:
    all_pts = [p for poly in outer_polygons for p in poly]
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    return min(xs), max(xs), min(ys), max(ys)


def _pip_vectorised(cx: np.ndarray, cy: np.ndarray,
                    pts: List[Tuple[float, float]]) -> np.ndarray:
    """
    Vectorised even-odd (ray-casting) point-in-polygon test.

    Returns boolean array of shape ``(len(cx),)``.
    Winding order does not matter (works for CW and CCW polygons).

    Parameters
    ----------
    cx, cy : 1-D arrays of x and y coordinates of query points.
    pts    : polygon vertices as a list of (x, y) tuples.
    """
    n = len(pts)
    inside = np.zeros(len(cx), dtype=bool)
    xv = np.array([p[0] for p in pts], dtype=float)
    yv = np.array([p[1] for p in pts], dtype=float)
    xi = xv
    yi = yv
    xj = np.roll(xv, -1)  # next vertex (wraps around)
    yj = np.roll(yv, -1)

    for i in range(n):
        dy = yj[i] - yi[i]
        # Ray crosses the edge if y_i and y_j straddle the query y
        cross = (yi[i] > cy) != (yj[i] > cy)
        # x-coordinate of the crossing
        with np.errstate(divide='ignore', invalid='ignore'):
            xc = np.where(dy != 0.0,
                          xi[i] + (cy - yi[i]) * (xj[i] - xi[i]) / dy,
                          np.inf)
        inside ^= cross & (cx < xc)
    return inside


def _classify_cells(outer_polygons: List[Pts],
                    hole_polygons: List[Pts],
                    h: float, x0: float, y0: float,
                    nx: int, ny: int) -> np.ndarray:
    """
    Classify every grid cell centre as _EXT, _INT, or _HOLE_BASE+k.

    Returns a (ny, nx) integer array.
    """
    # Build 1-D arrays of cell-centre coordinates
    cx_1d = x0 + (np.arange(nx) + 0.5) * h
    cy_1d = y0 + (np.arange(ny) + 0.5) * h
    CX, CY = np.meshgrid(cx_1d, cy_1d)   # row = y, col = x
    cx_f = CX.ravel()
    cy_f = CY.ravel()

    grid_f = np.zeros(nx * ny, dtype=np.int32)  # default: _EXT

    # Mark cells inside the union of outer polygons
    in_outer = np.zeros(nx * ny, dtype=bool)
    for poly in outer_polygons:
        in_outer |= _pip_vectorised(cx_f, cy_f, poly)
    grid_f[in_outer] = _INT

    # Override with hole markers (holes are inside the outer polygon)
    for k, poly in enumerate(hole_polygons):
        in_hole = _pip_vectorised(cx_f, cy_f, poly)
        grid_f[in_outer & in_hole] = _HOLE_BASE + k

    return grid_f.reshape(ny, nx)


# ---------------------------------------------------------------------------
# Main FDM solver
# ---------------------------------------------------------------------------

def compute_J_fdm(outer_polygons: List[Pts],
                  hole_polygons: Optional[List[Pts]] = None,
                  n_cells: int = 150) -> float:
    """
    Compute the St-Venant torsional constant J by the Finite Difference Method.

    Works for any polygonal section geometry:
      • solid sections (no holes)
      • composite sections with one or more holes (any shape, any winding order)
      • sections defined by catalogue, parametric generators, or free-hand drawing

    The Prandtl stress function φ is solved on a square Cartesian grid.
    Boundary conditions:
      • φ = 0 on outer boundary (automatically satisfied by exterior cells)
      • φ = c_k on each hole k (c_k unknown, solved simultaneously via
        compatibility condition)

    Parameters
    ----------
    outer_polygons : list of polygon vertex lists  (mm, any winding order)
    hole_polygons  : list of hole vertex lists      (mm, any winding order)
    n_cells        : approximate number of grid cells along the longest
                     dimension.  Higher → more accurate, slower.
                     Rule of thumb: at least 5 cells across the thinnest wall.
                     Default 150 targets < 3 % error for most sections.

    Returns
    -------
    J : float  (mm⁴)

    Accuracy notes
    --------------
    • Solid / closed sections (rectangle, circle, RHS) : ~1–2 % at n_cells=150
    • Thin-walled open sections (I, U, T, L) : ~3–8 % at n_cells=150
      Increase n_cells to 300 for < 3 % on thin-walled open sections.
    • Sections with holes : compatible with multiple holes of arbitrary shape.
    """
    if hole_polygons is None:
        hole_polygons = []

    if not outer_polygons:
        return 0.0

    # ------------------------------------------------------------------
    # Grid setup
    # ------------------------------------------------------------------
    xmin, xmax, ymin, ymax = _bbox(outer_polygons)
    span_x = xmax - xmin
    span_y = ymax - ymin
    span   = max(span_x, span_y, 1.0)
    h      = span / n_cells

    # Margin of 3 cells on each side ensures outer φ = 0 boundary is respected
    margin = 3.0 * h
    x0 = xmin - margin
    y0 = ymin - margin
    nx = int(math.ceil((xmax + margin - x0) / h)) + 1
    ny = int(math.ceil((ymax + margin - y0) / h)) + 1

    _log.debug("FDM grid: %d×%d  h=%.3f mm  %d outer  %d holes",
               nx, ny, h, len(outer_polygons), len(hole_polygons))

    # ------------------------------------------------------------------
    # Cell classification
    # ------------------------------------------------------------------
    grid     = _classify_cells(outer_polygons, hole_polygons, h, x0, y0, nx, ny)
    n_holes  = len(hole_polygons)
    h2       = h * h

    # ------------------------------------------------------------------
    # Index interior cells
    # ------------------------------------------------------------------
    int_mask = (grid == _INT)
    int_r, int_c = np.where(int_mask)
    n_int = int_r.size

    if n_int == 0:
        _log.warning("FDM: no interior cells — degenerate section or grid too coarse")
        return 0.0

    cell_idx = np.full((ny, nx), -1, dtype=np.int64)
    cell_idx[int_mask] = np.arange(n_int, dtype=np.int64)

    # Total unknowns: φ values at interior cells + one c_k per hole
    n_vars = n_int + n_holes
    eq_all = np.arange(n_int, dtype=np.int64)  # equation index for each interior cell

    # ------------------------------------------------------------------
    # Sparse matrix assembly  (COO format: lists → coo_matrix → csr)
    # ------------------------------------------------------------------
    rows_: List = []
    cols_: List = []
    vals_: List = []
    rhs = np.zeros(n_vars)

    # Diagonal: −4 for every interior cell (5-point Laplacian)
    rows_.extend(eq_all.tolist())
    cols_.extend(eq_all.tolist())
    vals_.extend((-4.0 * np.ones(n_int)).tolist())
    rhs[:n_int] = -2.0 * h2          # RHS of ∇²φ = −2 (multiplied by h²)

    # Off-diagonals: check all 4 neighbours of each interior cell
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr  = int_r + dr
        nc_ = int_c + dc
        valid = (nr >= 0) & (nr < ny) & (nc_ >= 0) & (nc_ < nx)

        nr_v  = nr[valid]
        nc_v  = nc_[valid]
        eq_v  = eq_all[valid]
        nbr   = grid[nr_v, nc_v]

        # Interior neighbour → standard off-diagonal entry (+1)
        sel_int = (nbr == _INT)
        if sel_int.any():
            rows_.extend(eq_v[sel_int].tolist())
            cols_.extend(cell_idx[nr_v[sel_int], nc_v[sel_int]].tolist())
            vals_.extend(np.ones(int(sel_int.sum())).tolist())

        # Hole-k neighbour → contributes to the c_k column (+1)
        for k in range(n_holes):
            sel_k = (nbr == _HOLE_BASE + k)
            if sel_k.any():
                count_k = int(sel_k.sum())
                rows_.extend(eq_v[sel_k].tolist())
                cols_.extend([n_int + k] * count_k)
                vals_.extend(np.ones(count_k).tolist())

        # Exterior neighbour (φ = 0): contributes 0 to RHS — already zero

    # ------------------------------------------------------------------
    # Compatibility equations: one per hole
    #
    #   N_{f,k} · c_k − Σ_{adj. interior} φ_i = −2 A_k
    #
    # where N_{f,k} = number of interior cells adjacent to hole k,
    # and A_k_discrete = (number of hole-k cells) × h².
    # ------------------------------------------------------------------
    for k in range(n_holes):
        eq_k      = n_int + k
        hole_mask = (grid == _HOLE_BASE + k)
        hr, hc    = np.where(hole_mask)
        A_k       = float(hr.size) * h2   # discrete hole area

        n_faces_k = 0
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr  = hr + dr
            nc_ = hc + dc
            valid   = (nr >= 0) & (nr < ny) & (nc_ >= 0) & (nc_ < nx)
            nr_v    = nr[valid]
            nc_v    = nc_[valid]
            sel_int = (grid[nr_v, nc_v] == _INT)
            phi_idx = cell_idx[nr_v[sel_int], nc_v[sel_int]]

            if phi_idx.size > 0:
                # −φ_i  terms in the compatibility equation
                rows_.extend([eq_k] * phi_idx.size)
                cols_.extend(phi_idx.tolist())
                vals_.extend((-1.0 * np.ones(phi_idx.size)).tolist())
                n_faces_k += phi_idx.size

        if n_faces_k == 0:
            _log.warning("FDM: hole %d has no adjacent interior cells "
                         "(grid too coarse?)", k)
            # Trivial equation c_k = 0 to keep the system non-singular
            rows_.append(eq_k)
            cols_.append(eq_k)
            vals_.append(1.0)
            rhs[eq_k] = 0.0
            continue

        # Diagonal: N_{f,k} · c_k
        rows_.append(eq_k)
        cols_.append(eq_k)
        vals_.append(float(n_faces_k))
        # Compatibility condition: ∮_{Γk} ∂φ/∂n ds = +2 A_k
        # (outward normal from D into the hole; Pilkey 2002 §6.2.4)
        rhs[eq_k] = +2.0 * A_k

    # ------------------------------------------------------------------
    # Solve the sparse linear system
    # ------------------------------------------------------------------
    if not rows_:
        return 0.0

    A_mat = sparse.coo_matrix(
        (vals_, (rows_, cols_)), shape=(n_vars, n_vars)
    ).tocsr()

    try:
        x = spsolve(A_mat, rhs)
    except Exception as exc:
        _log.warning("FDM: sparse solve failed — %s", exc)
        return 0.0

    if np.any(~np.isfinite(x)):
        _log.warning("FDM: non-finite solution (NaN or Inf)")
        return 0.0

    # ------------------------------------------------------------------
    # Torsional constant:
    #   J = 2 h² Σ φ_i  +  2 Σ_k c_k · A_k
    #
    # The second term accounts for the fact that φ = c_k (not 0) on each
    # hole boundary.  For solid sections n_holes=0 so the term vanishes.
    # For hollow sections (CHS, RHS) it can dominate (≈ 86 % for thin CHS).
    # ------------------------------------------------------------------
    phi        = x[:n_int]
    J_interior = 2.0 * h2 * float(phi.sum())

    J_holes = 0.0
    for k in range(n_holes):
        c_k         = float(x[n_int + k])
        A_k_discrete = float((grid == _HOLE_BASE + k).sum()) * h2
        J_holes += 2.0 * c_k * A_k_discrete

    J = J_interior + J_holes

    if J <= 0.0:
        _log.warning("FDM: J ≤ 0 (%.3g) — check geometry or increase n_cells", J)
        return 0.0

    return J


# ---------------------------------------------------------------------------
# Convenience: adapt FDM to centroid-centered polygons coming from
# section_properties.compute_properties()
# ---------------------------------------------------------------------------

def compute_J_fdm_from_centered(outer_c: List[Pts],
                                 hole_c: List[Pts],
                                 n_cells: int = 150) -> float:
    """
    Thin wrapper used by section_properties.compute_properties().

    Polygons are already centroid-centred (required by BEM; FDM is
    translation-invariant but we keep the same interface for consistency).
    """
    return compute_J_fdm(outer_c, hole_c, n_cells=n_cells)

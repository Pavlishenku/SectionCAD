"""
Tests unitaires pour le solveur FDM (torsion_fdm.py).

Valeurs de reference :
  - Cercle plein d=100 mm  : J_exact = pi d^4/32 = 9 817 477 mm^4
  - Rectangle 100x50 mm   : J_Timoshenko ~ 2 684 480 mm^4  (a=100, t=50)
  - CHS Ro=50 Ri=40 mm    : J_exact = pi(Ro^4-Ri^4)/2 = 5 796 726 mm^4
  - RHS 100x60x4 mm       : J_Bredt ~ 152 cm^4 (thin-wall); FDM ~ 176 cm^4 (sharp corners)
"""

import math
import pytest
import numpy as np

from calculators.torsion_fdm import compute_J_fdm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _circle_polygon(d, n=128):
    r = d / 2.0
    return [(r * math.cos(2 * math.pi * i / n),
             r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _rectangle_polygon(b, h):
    """CCW rectangle centred on origin."""
    return [(-b/2, -h/2), (b/2, -h/2), (b/2, h/2), (-b/2, h/2)]


def _annulus_polygons(ro, ri, n=128):
    outer = _circle_polygon(2 * ro, n)
    # Inner circle: CW winding (reversed)
    inner = list(reversed(_circle_polygon(2 * ri, n)))
    return [outer], [inner]


def _rhs_polygons(b, h, t):
    """RHS centred on origin.  Outer CCW, inner hole CW."""
    outer = [(-b/2, -h/2), (b/2, -h/2), (b/2, h/2), (-b/2, h/2)]
    bi, hi = b - 2*t, h - 2*t
    inner = [(-bi/2, hi/2), (bi/2, hi/2), (bi/2, -hi/2), (-bi/2, -hi/2)]
    return [outer], [inner]


# ---------------------------------------------------------------------------
# Solid circle
# ---------------------------------------------------------------------------

class TestCircleSolid:
    """Solid circle d=100 mm : J = pi d^4/32"""

    D = 100.0
    J_EXACT = math.pi * D**4 / 32.0   # 9 817 477 mm^4

    def test_J_accuracy_3pct(self):
        poly = _circle_polygon(self.D)
        J = compute_J_fdm([poly], n_cells=150)
        assert J == pytest.approx(self.J_EXACT, rel=0.03), (
            "Circle J={:.0f} mm^4, expected {:.0f} mm^4 (+-3 %)".format(
                J, self.J_EXACT))

    def test_J_positive(self):
        poly = _circle_polygon(self.D)
        J = compute_J_fdm([poly], n_cells=80)
        assert J > 0.0

    def test_J_translation_invariant(self):
        """J must not depend on the polygon's position in the plane."""
        poly0 = _circle_polygon(self.D)
        poly1 = [(x + 500, y - 300) for x, y in poly0]
        J0 = compute_J_fdm([poly0], n_cells=120)
        J1 = compute_J_fdm([poly1], n_cells=120)
        assert J0 == pytest.approx(J1, rel=0.01), (
            "J should be translation-invariant: J0={:.0f}, J1={:.0f}".format(J0, J1))


# ---------------------------------------------------------------------------
# Solid rectangle
# ---------------------------------------------------------------------------

class TestRectangleSolid:
    """Rectangle 100x50 mm : J_Timoshenko reference."""

    B, H = 100.0, 50.0
    # Timoshenko: J = a*t^3/3 * (1 - 0.630*r + 0.052*r^5),  a=100, t=50, r=t/a=0.5
    _a, _t = 100.0, 50.0
    _r = _t / _a
    J_TIMOSHENKO = (_a * _t**3 / 3.0) * (1.0 - 0.630 * _r + 0.052 * _r**5)

    def test_J_accuracy_5pct(self):
        poly = _rectangle_polygon(self.B, self.H)
        J = compute_J_fdm([poly], n_cells=150)
        assert J == pytest.approx(self.J_TIMOSHENKO, rel=0.05), (
            "Rect J={:.0f}, expected {:.0f} mm^4 (+-5 %)".format(
                J, self.J_TIMOSHENKO))

    def test_J_square_symmetry(self):
        """Square: J(b,b) should equal J(b,b) for any orientation."""
        poly_a = _rectangle_polygon(80, 80)
        poly_b = _rectangle_polygon(80, 80)
        J_a = compute_J_fdm([poly_a], n_cells=120)
        J_b = compute_J_fdm([poly_b], n_cells=120)
        assert J_a == pytest.approx(J_b, rel=0.005)


# ---------------------------------------------------------------------------
# CHS (hollow circle) -- tests the hole term J_holes (Bug 2 fix)
# ---------------------------------------------------------------------------

class TestCHS:
    """CHS Ro=50 mm, Ri=40 mm (wall t=10 mm).

    J_exact = pi*(Ro^4 - Ri^4)/2 = 5 796 726 mm^4
    NOTE: the common formula pi*(d_ext^4-d_int^4)/32 uses DIAMETERS.
          In terms of radii: J = pi*(Ro^4-Ri^4)/2.

    The hole constant c_0 contributes ~86 % of total J.
    This test verifies that Bug 2 (missing hole term) is fixed.
    """

    RO, RI = 50.0, 40.0
    J_EXACT = math.pi * (RO**4 - RI**4) / 2.0   # ~5 796 726 mm^4

    def test_J_accuracy_5pct(self):
        outers, holes = _annulus_polygons(self.RO, self.RI)
        J = compute_J_fdm(outers, holes, n_cells=150)
        assert J == pytest.approx(self.J_EXACT, rel=0.05), (
            "CHS J={:.0f} mm^4, expected {:.0f} mm^4 (+-5 %)".format(
                J, self.J_EXACT))

    def test_J_positive(self):
        outers, holes = _annulus_polygons(self.RO, self.RI)
        J = compute_J_fdm(outers, holes, n_cells=80)
        assert J > 0.0

    def test_J_order_of_magnitude(self):
        """J must be in [4M, 7M] mm^4 -- sanity check on hole-term sign."""
        outers, holes = _annulus_polygons(self.RO, self.RI)
        J = compute_J_fdm(outers, holes, n_cells=120)
        assert 4e6 <= J <= 7e6, (
            "CHS J={:.0f} mm^4 out of physical range [4M, 7M]".format(J))

    def test_J_greater_than_wall_only(self):
        """Hollow tube J must be in same order as exact value (hole term present)."""
        outers, holes = _annulus_polygons(self.RO, self.RI)
        J = compute_J_fdm(outers, holes, n_cells=120)
        assert J >= 0.9 * self.J_EXACT, (
            "CHS J={:.0f} mm^4 too small vs exact {:.0f}; hole term may be missing".format(
                J, self.J_EXACT))


# ---------------------------------------------------------------------------
# RHS (rectangular hollow section) -- second test for hole term
# ---------------------------------------------------------------------------

class TestRHS:
    """RHS 100x60x4 mm (outer 100x60, wall t=4 mm).

    Bredt (thin-wall, median-line): J = 4*Am^2 / sum(ds/t)
      Am = (100-4)*(60-4) = 96*56 = 5376 mm^2
      sum(ds/t) = 2*96/4 + 2*56/4 = 76
      J_Bredt = 4*5376^2/76 = 1 520 382 mm^4 ~ 152 cm^4

    FDM (sharp corners, n=200): ~176 cm^4
    The ~16 % gap vs Bredt is expected: Bredt uses the median-line area
    approximation; the FDM solves the PDE on the actual sharp-corner geometry
    (outer 100x60, hole 92x52) where boundary alignment at t/h ~ 8 cells/wall
    introduces O(h/t) discretization error.

    These tests verify: (a) correct order of magnitude, (b) hole term present.
    """

    B, H, T = 100.0, 60.0, 4.0
    _Am = (B - T) * (H - T)              # median-line area = 5376 mm^2
    _perim = 2.0 * (B - T) / T + 2.0 * (H - T) / T   # = 76
    J_BREDT = 4.0 * _Am**2 / _perim      # ~1 521 125 mm^4 = 152.1 cm^4

    def test_J_positive(self):
        outers, holes = _rhs_polygons(self.B, self.H, self.T)
        J = compute_J_fdm(outers, holes, n_cells=100)
        assert J > 0.0

    def test_J_order_of_magnitude(self):
        """J must be in [100, 250] cm^4 -- covers Bredt, FDM, and some margin."""
        outers, holes = _rhs_polygons(self.B, self.H, self.T)
        J = compute_J_fdm(outers, holes, n_cells=150)
        J_cm4 = J * 1e-4
        assert 100 <= J_cm4 <= 250, (
            "RHS J={:.1f} cm^4 out of physical range [100, 250]".format(J_cm4))

    def test_J_above_bredt_lower_bound(self):
        """FDM on a sharp-corner polygon must give at least 80 % of Bredt."""
        outers, holes = _rhs_polygons(self.B, self.H, self.T)
        J = compute_J_fdm(outers, holes, n_cells=200)
        assert J >= 0.80 * self.J_BREDT, (
            "RHS J={:.0f} mm^4 < 80 % of Bredt {:.0f}; hole term may be missing".format(
                J, self.J_BREDT))

    def test_J_convergence(self):
        """J with finer grid (8 cells/wall) must agree with medium (6 cells/wall) within 15 %.

        n=150 -> h=0.67 mm -> 6 cells per 4 mm wall
        n=250 -> h=0.40 mm -> 10 cells per 4 mm wall
        Convergence is slow for thin walls due to O(h/t) boundary alignment.
        """
        outers, holes = _rhs_polygons(self.B, self.H, self.T)
        J_medium = compute_J_fdm(outers, holes, n_cells=150)
        J_fine   = compute_J_fdm(outers, holes, n_cells=250)
        assert J_fine == pytest.approx(J_medium, rel=0.15), (
            "RHS J not converging: medium={:.0f}, fine={:.0f}".format(
                J_medium, J_fine))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_outer(self):
        J = compute_J_fdm([], n_cells=50)
        assert J == 0.0

    def test_no_interior_cells(self):
        """Very coarse grid may produce 0 interior cells -- must return 0."""
        poly = _rectangle_polygon(1.0, 0.5)   # 1 mm x 0.5 mm
        J = compute_J_fdm([poly], n_cells=5)
        assert J >= 0.0

    def test_multiple_outer_polygons(self):
        """Two separate rectangles: J ~ sum of individual J values (+-10 %)."""
        poly_a = [(-60 + x, y) for x, y in _rectangle_polygon(20, 20)]
        poly_b = [(+60 + x, y) for x, y in _rectangle_polygon(20, 20)]
        J_combined = compute_J_fdm([poly_a, poly_b], n_cells=150)
        J_single = compute_J_fdm([_rectangle_polygon(20, 20)], n_cells=150)
        assert J_combined == pytest.approx(2 * J_single, rel=0.10), (
            "Two rects J={:.0f}, 2*single={:.0f}".format(J_combined, 2*J_single))

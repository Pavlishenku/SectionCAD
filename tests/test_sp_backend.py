"""
Tests du backend sectionproperties (calculators/sp_backend.py).

Valide les propriétés FEA contre :
  - des références analytiques exactes (cercle, rectangle),
  - les valeurs de catalogue (IPE 300 : Cw),
  - le moteur analytique maison pour les propriétés géométriques (recoupement),
et vérifie la gestion des sections disjointes et de la densité de maillage.
"""
import math
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculators.sp_backend import (
    SECTIONPROPERTIES_AVAILABLE, compute_properties_fea, fea_results_to_dict,
    _build_material_region,
)
from calculators.section_properties import compute_properties
import sections.parametric as para

pytestmark = pytest.mark.skipif(
    not SECTIONPROPERTIES_AVAILABLE,
    reason="package sectionproperties non installé",
)


def _rel(a, b):
    return abs(a - b) / abs(b) if b else abs(a)


# ===========================================================================
# Recoupement géométrique : FEA vs moteur analytique sur les mêmes polygones
# ===========================================================================
class TestGeometricCrossCheck:
    def test_rectangle_matches_analytic(self):
        outers = para.rectangle(100, 200)
        fea = compute_properties_fea(outers, [], quality="Moyen")
        ana = compute_properties(outers, [])
        assert _rel(fea.area, ana.area) < 0.005
        assert _rel(fea.Ix, ana.Ix) < 0.01
        assert _rel(fea.Iy, ana.Iy) < 0.01
        assert abs(fea.xc - ana.xc) < 0.1
        assert abs(fea.yc - ana.yc) < 0.1

    def test_rectangle_exact_values(self):
        b, h = 100.0, 200.0
        fea = compute_properties_fea(para.rectangle(b, h), [])
        assert _rel(fea.area, b * h) < 0.005
        assert _rel(fea.Ix, b * h**3 / 12) < 0.01
        assert _rel(fea.Iy, h * b**3 / 12) < 0.01

    def test_ipe300_area_matches_analytic(self):
        outers = para.i_section(300, 150, 7.1, 10.7)
        fea = compute_properties_fea(outers, [])
        ana = compute_properties(outers, [])
        assert _rel(fea.area, ana.area) < 0.005
        assert _rel(fea.Ix, ana.Ix) < 0.01

    def test_centroid_offset_section(self):
        # Rectangle non centré : contrôle que le centroïde FEA suit la translation.
        pts = [(10, 20), (110, 20), (110, 220), (10, 220)]
        fea = compute_properties_fea([pts], [])
        assert abs(fea.xc - 60.0) < 0.2
        assert abs(fea.yc - 120.0) < 0.2


# ===========================================================================
# Torsion / gauchissement : valeurs de référence
# ===========================================================================
class TestWarpingReference:
    def test_circle_torsion_constant(self):
        # Cercle plein d=100 : J = pi*d^4/32 (tolérance pour polygone 64 côtés + maillage)
        d = 100.0
        fea = compute_properties_fea(para.circle(d), [], quality="Fin")
        J_exact = math.pi * d**4 / 32.0
        assert fea.warping_valid
        assert _rel(fea.J, J_exact) < 0.02

    def test_rectangle_torsion_constant(self):
        # Rectangle 100x200 : J via série de Timoshenko ≈ 4.577e6 mm^4
        fea = compute_properties_fea(para.rectangle(100, 200), [], quality="Fin")
        a, t = 200.0, 100.0
        r = t / a
        J_ref = (a * t**3 / 3.0) * (1 - 0.630 * r + 0.052 * r**5)
        assert fea.warping_valid
        assert _rel(fea.J, J_ref) < 0.05

    def test_ipe300_warping_constant_vs_catalog(self):
        # IPE 300 (sans congés) : Cw catalogue = 125 900 cm^6 = 1.259e11 mm^6
        fea = compute_properties_fea(para.i_section(300, 150, 7.1, 10.7), [],
                                     quality="Moyen")
        assert fea.warping_valid
        Cw_catalog = 1.259e11
        assert _rel(fea.Cw, Cw_catalog) < 0.03
        # J du polygone sans congés ≈ (1/3)(2*b*tf^3 + hw*tw^3)
        b, tf, tw = 150.0, 10.7, 7.1
        hw = 300 - 2 * tf
        J_thinwall = (2 * b * tf**3 + hw * tw**3) / 3.0
        assert _rel(fea.J, J_thinwall) < 0.06

    def test_doubly_symmetric_shear_centre_at_centroid(self):
        fea = compute_properties_fea(para.i_section(300, 150, 7.1, 10.7), [])
        assert abs(fea.xsc - fea.xc) < 0.5
        assert abs(fea.ysc - fea.yc) < 0.5


# ===========================================================================
# Sections composites / trous
# ===========================================================================
class TestCompositeAndHoles:
    def test_box_with_hole_area(self):
        outers, holes = para.box_section(200, 100, 8, 8)
        # box_section renvoie ([outer], [hole]) déjà en listes
        fea = compute_properties_fea(outers, holes)
        ana = compute_properties(outers, holes)
        assert _rel(fea.area, ana.area) < 0.01
        assert fea.warping_valid
        assert fea.J > 0
        assert fea.Cw >= 0

    def test_hollow_circle_connected(self):
        outers, holes = para.hollow_circle(300, 260)
        fea = compute_properties_fea(outers, holes, quality="Moyen")
        assert fea.warping_valid
        # CHS : J = pi*(D_ext^4 - D_int^4)/32
        J_exact = math.pi * (300**4 - 260**4) / 32.0
        assert _rel(fea.J, J_exact) < 0.05

    def test_solid_island_inside_hole(self):
        # Imbrication : contour 200 → trou 120 → îlot solide 60 (tous centrés).
        # L'îlot ne doit PAS être effacé par la soustraction du trou.
        def sq(s):
            h = s / 2.0
            return [(-h, -h), (h, -h), (h, h), (-h, h)]
        outer, hole, island = sq(200), sq(120), sq(60)
        fea = compute_properties_fea([outer, island], [hole])
        ana = compute_properties([outer, island], [hole])
        # Aire = 200² − 120² + 60² = 29200 (et non 25600 si l'îlot était perdu)
        assert _rel(fea.area, 29200.0) < 0.01, f"aire={fea.area} (îlot perdu ?)"
        assert _rel(fea.area, ana.area) < 0.01
        # L'îlot est séparé du cadre par le vide -> régions disjointes -> warping invalide
        assert not fea.warping_valid
        assert any("disjoint" in w.lower() for w in fea.warnings)


# ===========================================================================
# Régions disjointes
# ===========================================================================
class TestDisjointRegions:
    def test_two_disjoint_rectangles(self):
        r1 = [(-60, -10), (-20, -10), (-20, 10), (-60, 10)]
        r2 = [(20, -10), (60, -10), (60, 10), (20, 10)]
        fea = compute_properties_fea([r1, r2], [])
        # Géométrique valide (somme des aires), gauchissement invalide.
        assert _rel(fea.area, 2 * 40 * 20) < 0.01
        assert not fea.warping_valid
        assert fea.J == 0.0
        assert fea.Cw == 0.0
        assert any("disjoint" in w.lower() for w in fea.warnings)
        # Centre de cisaillement rabattu sur le centroïde (pas de marqueur parasite)
        assert fea.xsc == fea.xc and fea.ysc == fea.yc

    def test_connectivity_detection(self):
        # Deux rectangles qui se touchent → région connexe
        r1 = [(-40, -10), (0, -10), (0, 10), (-40, 10)]
        r2 = [(0, -10), (40, -10), (40, 10), (0, 10)]
        mat, connected = _build_material_region([r1, r2], [])
        assert connected
        # Deux rectangles séparés → disjoints
        r3 = [(20, -10), (60, -10), (60, 10), (20, 10)]
        mat2, connected2 = _build_material_region([r1, r3], [])
        assert not connected2


# ===========================================================================
# Maillage et mise en forme
# ===========================================================================
class TestMeshAndFormatting:
    def test_finer_mesh_more_elements(self):
        outers = para.i_section(300, 150, 7.1, 10.7)
        coarse = compute_properties_fea(outers, [], quality="Grossier")
        fine = compute_properties_fea(outers, [], quality="Fin")
        assert fine.n_elements > coarse.n_elements
        # La valeur de J doit rester stable entre maillages (<2 %)
        assert _rel(fine.J, coarse.J) < 0.02

    def test_results_to_dict_keys(self):
        fea = compute_properties_fea(para.rectangle(100, 200), [])
        d = fea_results_to_dict(fea)
        assert "A" in d
        assert "I_t" in d and "I_w" in d        # torsion / gauchissement (FEM valide)
        assert "A_vy" in d and "A_vz" in d      # aires de cisaillement (FEM)
        assert all(isinstance(v, tuple) and len(v) == 2 for v in d.values())

    def test_results_to_dict_disjoint_nd(self):
        r1 = [(-60, -10), (-20, -10), (-20, 10), (-60, 10)]
        r2 = [(20, -10), (60, -10), (60, 10), (20, 10)]
        d = fea_results_to_dict(compute_properties_fea([r1, r2], []))
        assert d["I_t"][0] == "n/d" and d["I_w"][0] == "n/d"


# ===========================================================================
# Robustesse / erreurs
# ===========================================================================
class TestErrors:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_properties_fea([], [])

    def test_degenerate_polygon_raises(self):
        with pytest.raises(ValueError):
            compute_properties_fea([[(0, 0), (10, 0)]], [])  # 2 points


# ===========================================================================
# Régressions issues de la revue adversariale
# ===========================================================================
class TestReviewRegressions:
    def test_theta_p_matches_analytic_on_unequal_angle(self):
        # Cornière à ailes inégales : Ixy != 0, axes principaux tournés.
        # FEA (get_phi, axe majeur (-180,180]) doit être ramené dans la même
        # convention (-90,90] que le moteur analytique.
        outers = para.angle_section(150, 90, 10, 10)
        fea = compute_properties_fea(outers, [], quality="Fin")
        ana = compute_properties(outers, [])
        assert -90.0 < fea.theta_p <= 90.0
        assert abs(fea.theta_p - ana.theta_p) < 1.0


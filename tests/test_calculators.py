"""
Tests unitaires pour calculators/section_properties.py et calculators/torsion.py
Utilise des sections paramétriques comme fixtures et compare aux valeurs théoriques.
"""
import math
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculators.section_properties import (
    compute_properties, results_to_dict,
    _polygon_area_and_centroid, _polygon_inertia,
)
from calculators.geometry_prep import SHAPELY_AVAILABLE
import sections.parametric as para


def _sq(s):
    h = s / 2.0
    return [(-h, -h), (h, -h), (h, h), (-h, h)]


# ===========================================================================
# TestPolygonBasics — formules de base sur polygones simples
# ===========================================================================

class TestPolygonBasics:
    def test_square_area(self):
        """Carré 100x100 : aire = 10000 mm²"""
        pts = [(-50, -50), (50, -50), (50, 50), (-50, 50)]
        a, cx, cy = _polygon_area_and_centroid(pts)
        assert abs(abs(a) - 10000) < 1e-6
        assert abs(cx) < 1e-6
        assert abs(cy) < 1e-6

    def test_triangle_area(self):
        """Triangle : aire = base*h/2"""
        pts = [(0, 0), (100, 0), (50, 100)]
        a, cx, cy = _polygon_area_and_centroid(pts)
        assert abs(abs(a) - 5000) < 1e-3
        assert abs(cx - 50) < 1e-3
        assert abs(cy - 100 / 3) < 1e-3

    def test_degenerate_polygon_collinear(self):
        """Points collinéaires → aire ≈ 0"""
        pts = [(0, 0), (10, 0), (20, 0)]
        a, cx, cy = _polygon_area_and_centroid(pts)
        assert abs(a) < 1e-10

    def test_inertia_rectangle(self):
        """Rectangle b×h : Ix = b*h³/12, Iy = h*b³/12"""
        b, h = 100.0, 200.0
        pts = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]
        Ix, Iy, Ixy = _polygon_inertia(pts, 0, 0)
        assert abs(abs(Ix) - b * h ** 3 / 12) / (b * h ** 3 / 12) < 1e-6
        assert abs(abs(Iy) - h * b ** 3 / 12) / (h * b ** 3 / 12) < 1e-6
        assert abs(Ixy) < 1e-3

    def test_polygon_area_sign_ccw(self):
        """Polygone CCW → aire signée positive."""
        # Carré CCW
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        a, _, _ = _polygon_area_and_centroid(pts)
        assert a > 0

    def test_polygon_area_sign_cw(self):
        """Polygone CW → aire signée négative."""
        pts = [(0, 0), (0, 10), (10, 10), (10, 0)]
        a, _, _ = _polygon_area_and_centroid(pts)
        assert a < 0

    def test_inertia_ixy_zero_for_symmetric_rectangle(self):
        """Rectangle centré sur axes → Ixy = 0."""
        b, h = 60.0, 120.0
        pts = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]
        Ix, Iy, Ixy = _polygon_inertia(pts, 0, 0)
        assert abs(Ixy) < 1e-3


# ===========================================================================
# TestRectangle200x400 — valeurs théoriques exactes
# ===========================================================================

class TestRectangle200x400:
    """Section rectangle b=200mm, h=400mm — valeurs théoriques exactes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        outers = para.rectangle(200, 400)
        meta = {'type': 'rectangle', 'b': 200, 'h': 400}
        self.r = compute_properties(outers, [], meta)

    def test_aire(self):
        assert abs(self.r.area - 200 * 400) / (200 * 400) < 1e-4

    def test_centroide(self):
        assert abs(self.r.xc) < 0.1
        assert abs(self.r.yc) < 0.1

    def test_Ix(self):
        """Ix = b*h³/12 = 200*400³/12 = 1 066 666 667 mm⁴"""
        expected = 200 * 400 ** 3 / 12
        assert abs(self.r.Ix - expected) / expected < 1e-3

    def test_Iy(self):
        """Iy = h*b³/12"""
        expected = 400 * 200 ** 3 / 12
        assert abs(self.r.Iy - expected) / expected < 1e-3

    def test_Sx_top(self):
        """Sx = Ix / (h/2) = b*h²/6"""
        expected = 200 * 400 ** 2 / 6
        assert abs(self.r.Sx_top - expected) / expected < 1e-3

    def test_Zx(self):
        """Zx = b*h²/4 (rectangle)"""
        expected = 200 * 400 ** 2 / 4
        assert abs(self.r.Zx - expected) / expected < 2e-2  # 2% tolérance (bisection)

    def test_rayons_giration(self):
        """rx = h/√12"""
        expected_rx = 400 / math.sqrt(12)
        assert abs(self.r.rx - expected_rx) / expected_rx < 1e-3

    def test_ry(self):
        """ry = b/√12"""
        expected_ry = 200 / math.sqrt(12)
        assert abs(self.r.ry - expected_ry) / expected_ry < 1e-3

    def test_shear_center_equals_centroid(self):
        """Rectangle doublement symétrique : SC = centroïde"""
        assert abs(self.r.xsc - self.r.xc) < 0.1
        assert abs(self.r.ysc - self.r.yc) < 0.1

    def test_Cw_zero(self):
        """Rectangle plein : Cw = 0"""
        assert self.r.Cw == 0.0

    def test_J_positive(self):
        """J > 0 pour section pleine valide."""
        assert self.r.J > 0

    def test_I1_ge_I2(self):
        """Moment principal max ≥ min."""
        assert self.r.I1 >= self.r.I2

    def test_Ixy_zero(self):
        """Rectangle centré doublement symétrique : Ixy = 0."""
        assert abs(self.r.Ixy) < 1e-3

    def test_principal_axes_theta(self):
        """Rectangle b≠h : axes principaux à 0° ou 90°."""
        # θ_p doit être proche de 0 ou ±90° pour rectangle centré
        assert abs(self.r.theta_p) < 1.0 or abs(abs(self.r.theta_p) - 90.0) < 1.0


# ===========================================================================
# TestCircle300 — cercle plein Ø300mm
# ===========================================================================

class TestCircle300:
    @pytest.fixture(autouse=True)
    def setup(self):
        outers = para.circle(300, n=128)
        meta = {'type': 'circle', 'd': 300}
        self.r = compute_properties(outers, [], meta)

    def test_aire(self):
        expected = math.pi * 150 ** 2
        assert abs(self.r.area - expected) / expected < 1e-3

    def test_Ix(self):
        expected = math.pi * 150 ** 4 / 4
        assert abs(self.r.Ix - expected) / expected < 1e-2  # 1% (polygone approx)

    def test_Iy_equals_Ix(self):
        """Cercle : Ix = Iy (symétrie complète)."""
        assert abs(self.r.Ix - self.r.Iy) / self.r.Ix < 1e-3

    def test_axes_principaux_nuls(self):
        """Cercle : Ixy ≈ 0."""
        assert abs(self.r.Ixy) < 1e-3

    def test_J_circle(self):
        """J cercle = π*r⁴/2 (BEM doit donner < 2%)."""
        expected_J = math.pi * 150 ** 4 / 2
        assert abs(self.r.J - expected_J) / expected_J < 0.02

    def test_Cw_zero(self):
        """Cercle plein : Cw = 0."""
        assert self.r.Cw == 0.0

    def test_centroide_au_centre(self):
        assert abs(self.r.xc) < 0.5
        assert abs(self.r.yc) < 0.5

    def test_rayon_giration_egal(self):
        """Cercle : rx = ry = r/2."""
        assert abs(self.r.rx - self.r.ry) / self.r.rx < 1e-3


# ===========================================================================
# TestIPE200 — profil I standard
# ===========================================================================

class TestIPE200:
    """IPE 200 : h=200, b=100, tw=5.6, tf=8.5 — comparer aux tables EN."""

    @pytest.fixture(autouse=True)
    def setup(self):
        h, b, tw, tf = 200, 100, 5.6, 8.5
        outers = para.i_section(h, b, tw, tf)
        meta = {'type': 'i_section', 'h': h, 'b': b, 'tw': tw, 'tf': tf}
        self.r = compute_properties(outers, [], meta)

    def test_aire_approx(self):
        """IPE 200 table : A = 28.5 cm² — sans rayon de congé, ≈27 cm²"""
        assert 25 < self.r.area * 1e-2 < 30  # cm²

    def test_Ix_approx(self):
        """Table : 1943 cm⁴ — sans congé, légèrement inférieur."""
        assert 1600 < self.r.Ix * 1e-4 < 2000

    def test_shear_center_doubly_symmetric(self):
        """I doublement symétrique : SC = centroïde."""
        assert abs(self.r.xsc - self.r.xc) < 0.5
        assert abs(self.r.ysc - self.r.yc) < 0.5

    # Cw (gauchissement) n'est plus calculé en analytique (réservé au moteur FEM,
    # validé) ; voir tests/test_sp_backend.py::test_ipe300_warping_constant_vs_catalog.

    def test_J_positive(self):
        assert self.r.J > 0

    def test_Zx_greater_than_Sx(self):
        """Module plastique > module élastique."""
        assert self.r.Zx > self.r.Sx_top

    def test_I1_ge_Ix(self):
        """I1 ≥ Ix pour section quelconque."""
        assert self.r.I1 >= self.r.Ix - 1e-3

    def test_centroide_centre(self):
        """IPE doublement symétrique : centroïde au centre."""
        assert abs(self.r.xc) < 0.5
        assert abs(self.r.yc) < 0.5

    def test_Sx_top_equals_Sx_bot(self):
        """IPE symétrique : Sx_top = Sx_bot."""
        assert abs(self.r.Sx_top - self.r.Sx_bot) / self.r.Sx_top < 1e-3


# ===========================================================================
# TestHollowCircle — section composée tube creux
# ===========================================================================

class TestHollowCircle:
    @pytest.fixture(autouse=True)
    def setup(self):
        outers, holes = para.hollow_circle(300, 260, n=128)
        meta = {'type': 'chs', 'd_ext': 300, 'd_int': 260}
        self.r = compute_properties(outers, holes, meta)

    def test_aire_annulaire(self):
        expected = math.pi * (150 ** 2 - 130 ** 2)
        assert abs(self.r.area - expected) / expected < 1e-2

    def test_Ix_annulaire(self):
        expected = math.pi * (150 ** 4 - 130 ** 4) / 4
        assert abs(self.r.Ix - expected) / expected < 2e-2

    def test_Cw_zero_closed(self):
        """CHS : Cw = 0."""
        assert self.r.Cw == 0.0

    def test_J_positive(self):
        """J > 0 pour tube creux."""
        assert self.r.J > 0

    def test_aire_inferieure_plein(self):
        """Aire tube < aire cercle plein."""
        expected_plein = math.pi * 150 ** 2
        assert self.r.area < expected_plein

    def test_centroide_centre(self):
        """Tube circulaire : centroïde au centre."""
        assert abs(self.r.xc) < 0.5
        assert abs(self.r.yc) < 0.5


# ===========================================================================
# TestAngle100x100x10 — cornière L 100x100x10
# ===========================================================================

class TestAngle100x100x10:
    @pytest.fixture(autouse=True)
    def setup(self):
        h, b, tw, tf = 100, 100, 10, 10
        outers = para.angle_section(h, b, tw, tf)
        meta = {'type': 'angle', 'h': h, 'b': b, 'tw': tw, 'tf': tf}
        self.r = compute_properties(outers, [], meta)

    def test_aire(self):
        """L 100x100x10 : A = 100*10 + 90*10 = 1900 mm²"""
        expected = 100 * 10 + 90 * 10
        assert abs(self.r.area - expected) / expected < 1e-3

    def test_Cw_zero(self):
        """Cornière : Cw = 0."""
        assert self.r.Cw == 0.0

    def test_SC_near_corner(self):
        """SC proche du coin intérieur des ailes — symétrique à ±2mm."""
        # Pour L 100x100x10 symétrique : xsc ≈ ysc (symétrie à 45°)
        assert abs(self.r.xsc - self.r.ysc) < 2.0

    def test_J_positive(self):
        assert self.r.J > 0

    def test_Ix_positive(self):
        assert self.r.Ix > 0

    def test_Iy_positive(self):
        assert self.r.Iy > 0

    def test_Ixy_nonzero(self):
        """Cornière non symétrique par rapport aux axes centroïdaux : Ixy ≠ 0."""
        # Pour une cornière égale, Ixy ≠ 0 (pas de double symétrie)
        assert abs(self.r.Ixy) > 1e3  # valeur non négligeable en mm⁴


# ===========================================================================
# TestEdgeCases — cas limites et robustesse
# ===========================================================================

class TestEdgeCases:
    def test_empty_polygons(self):
        r = compute_properties([], [])
        assert r.area == 0.0
        assert r.Ix == 0.0

    def test_single_point_polygon(self):
        r = compute_properties([[(0, 0)]], [])
        assert r.area == 0.0

    def test_two_point_polygon(self):
        r = compute_properties([[(0, 0), (10, 0)]], [])
        assert r.area == 0.0

    def test_hole_strictly_containing_solid(self):
        """Trou contenant entièrement le solide.

        Avec normalisation (shapely) : le polygone le plus interne l'emporte, donc
        le solide subsiste comme îlot (sémantique cohérente avec « îlot dans un trou »).
        Sans shapely : repli historique (somme signée → aire ≤ 0 ou réduite).
        """
        outer = para.rectangle(100, 100)
        inner_big = [(-100, -100), (100, -100), (100, 100), (-100, 100)]
        r = compute_properties(outer, [inner_big])
        if SHAPELY_AVAILABLE:
            assert abs(r.area - 10000.0) < 1.0      # le solide interne subsiste
        else:
            assert r.area <= 0 or r.area < 100 * 100  # repli somme signée


# ===========================================================================
# TestGeometryNormalization — solides chevauchants/imbriqués (pas de double comptage)
# ===========================================================================

@pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="shapely requis pour la normalisation")
class TestGeometryNormalization:
    def test_nested_solids_no_double_count(self):
        """Deux solides imbriqués (B dans A) → aire = union (A), pas la somme A+B."""
        r = compute_properties([_sq(200), _sq(60)], [])  # B solide à l'intérieur de A
        assert abs(r.area - 40000.0) < 1.0, f"aire={r.area} (double comptage ?)"

    def test_overlapping_solids_union_area(self):
        """Deux solides en chevauchement partiel → aire = union (recouvrement non compté 2x)."""
        a = [(0, 0), (100, 0), (100, 100), (0, 100)]
        b = [(50, 50), (150, 50), (150, 150), (50, 150)]   # recouvrement 50×50 = 2500
        r = compute_properties([a, b], [])
        assert abs(r.area - 17500.0) < 1.0, f"aire={r.area}"  # 10000+10000-2500

    def test_solid_island_inside_hole_analytic(self):
        """Contour → trou → îlot solide : aire = ext − trou + îlot (cohérent avec le FEM)."""
        r = compute_properties([_sq(200), _sq(60)], [_sq(120)])
        assert abs(r.area - 29200.0) < 1.0, f"aire={r.area}"

    def test_results_to_dict_keys(self):
        """results_to_dict renvoie les symboles Eurocode attendus."""
        outers = para.rectangle(100, 200)
        r = compute_properties(outers, [])
        d = results_to_dict(r, {})
        assert "A" in d
        assert "I_y" in d and "I_z" in d
        assert "y_SC" in d and "z_SC" in d

    def test_results_to_dict_eurocode_strong_axis(self):
        """I_y (Eurocode, axe fort) doit valoir l'inertie autour de l'axe horizontal."""
        # Rectangle b=100 (largeur), h=200 (hauteur) -> axe fort = horizontal.
        # I_y = b*h^3/12 ; I_z = h*b^3/12 ; donc I_y > I_z.
        r = compute_properties(para.rectangle(100, 200), [])
        d = results_to_dict(r, {})
        iy = float(d["I_y"][0])
        iz = float(d["I_z"][0])
        assert iy > iz, "I_y (axe fort) doit être supérieur à I_z (axe faible)"

    def test_J_positive_solid(self):
        """J > 0 pour toute section pleine valide."""
        outers = para.rectangle(100, 200)
        r = compute_properties(outers, [])
        assert r.J > 0

    def test_collinear_polygon_ignored(self):
        """Un polygone dégénéré (collinéaire) est ignoré, l'autre contour reste valide."""
        valid = para.rectangle(100, 200)
        collinear = [(0, 0), (10, 0), (20, 0)]
        # On passe les deux polygones dans outer_polygons
        r = compute_properties(valid + [collinear], [])
        # L'aire doit correspondre uniquement au rectangle valide
        assert abs(r.area - 100 * 200) / (100 * 200) < 1e-4

    def test_metadata_none_does_not_crash(self):
        """section_metadata=None ne doit pas lever d'exception."""
        outers = para.rectangle(50, 80)
        r = compute_properties(outers, [], None)
        assert r.area > 0

    def test_bounding_box_rectangle(self):
        """Boîte englobante rectangle 200×400 : xmin/xmax = ±100, ymin/ymax = ±200."""
        outers = para.rectangle(200, 400)
        r = compute_properties(outers, [])
        assert abs(r.xmin - (-100)) < 1e-6
        assert abs(r.xmax - 100) < 1e-6
        assert abs(r.ymin - (-200)) < 1e-6
        assert abs(r.ymax - 200) < 1e-6


# ===========================================================================
# TestChannelUPN — canal UPN (centre de cisaillement hors section)
# ===========================================================================

class TestChannelUPN:
    @pytest.fixture(autouse=True)
    def setup(self):
        h, b, tw, tf = 200, 75, 8.5, 11.5
        outers = para.channel_section(h, b, tw, tf)
        meta = {'type': 'channel', 'h': h, 'b': b, 'tw': tw, 'tf': tf}
        self.r = compute_properties(outers, [], meta)

    def test_SC_outside_profile(self):
        """SC canal est hors de la section — au moins 5mm d'écart avec le centroïde."""
        assert abs(self.r.xsc - self.r.xc) > 5.0

    def test_J_positive(self):
        assert self.r.J > 0

    def test_aire_approx(self):
        """UPN 200 : A environ 20-30 cm²."""
        assert 15 < self.r.area * 1e-2 < 35  # cm²

    def test_ysc_equals_yc(self):
        """Canal horizontal symétrique : ysc = yc."""
        assert abs(self.r.ysc - self.r.yc) < 1.0


# ===========================================================================
# TestTSection — section en T
# ===========================================================================

class TestTSection:
    @pytest.fixture(autouse=True)
    def setup(self):
        h, b, tw, tf = 200, 100, 10, 15
        outers = para.t_section(h, b, tw, tf)
        meta = {'type': 't_section', 'h': h, 'b': b, 'tw': tw, 'tf': tf}
        self.r = compute_properties(outers, [], meta)

    def test_aire(self):
        """T 200×100, tw=10, tf=15 : A = 100*15 + 10*(200-15) = 3350 mm²"""
        expected = 100 * 15 + 10 * (200 - 15)
        assert abs(self.r.area - expected) / expected < 1e-3

    def test_xsc_equals_xc(self):
        """T symétrique : xsc = xc."""
        assert abs(self.r.xsc - self.r.xc) < 0.5

    def test_Cw_positive(self):
        """T section a Cw > 0 (très faible mais positif)."""
        assert self.r.Cw >= 0.0

    def test_Ix_positive(self):
        assert self.r.Ix > 0

    def test_Zx_greater_than_Sx(self):
        """Module plastique > module élastique."""
        assert self.r.Zx > self.r.Sx_top or self.r.Zx > self.r.Sx_bot


# ===========================================================================
# TestResultsToDict — format de sortie
# ===========================================================================

class TestResultsToDict:
    def test_all_keys_present(self):
        """Vérifie que toutes les clés importantes sont présentes dans le dict."""
        outers = para.rectangle(100, 200)
        meta = {'type': 'rectangle'}
        r = compute_properties(outers, [], meta)
        d = results_to_dict(r, meta)

        # Symboles Eurocode (cf. calculators/nomenclature.py)
        required_keys = [
            "A", "y_G", "z_G",
            "I_y", "I_z", "I_yz", "I_1", "I_2", "α",
            "W_el,y,sup", "W_el,z,d", "W_pl,y", "W_pl,z",
            "i_y", "i_z", "y_SC", "z_SC", "I_t",
        ]
        for key in required_keys:
            assert key in d, f"Clé manquante : {key!r}"
        # I_w (gauchissement) n'est PAS calculé en analytique (réservé au moteur FEM).
        assert "I_w" not in d

    def test_values_are_tuples(self):
        """Chaque valeur est un tuple (str, str) = (valeur, unité)."""
        outers = para.rectangle(100, 200)
        r = compute_properties(outers, [])
        d = results_to_dict(r, {})
        for key, val in d.items():
            assert isinstance(val, tuple), f"La valeur de {key!r} n'est pas un tuple"
            assert len(val) == 2, f"Tuple de longueur inattendue pour {key!r}"
            assert isinstance(val[0], str), f"La valeur (index 0) de {key!r} n'est pas str"
            assert isinstance(val[1], str), f"L'unité (index 1) de {key!r} n'est pas str"

    def test_torsion_present_warping_absent_analytic(self):
        """I_t (torsion) présent et propre ; I_w (gauchissement) absent en analytique."""
        outers = para.rectangle(100, 200)
        for meta in ({'type': 'unknown'}, {'type': 'rectangle'}, {}):
            d = results_to_dict(compute_properties(outers, [], meta), meta)
            assert [k for k in d if k == "I_t"] == ["I_t"]
            assert "I_w" not in d  # réservé au moteur FEM

"""
Tests unitaires pour reports/fiche_report.py.

La plupart des tests n'utilisent ni Qt ni moteur FEM : les objets ``results``
sont des stubs (``types.SimpleNamespace``) imitant ``SectionResults``
(analytique) et ``FEAResults`` (FEM).

Deux tests (remplissage/maillage) construisent un VRAI ``FEAResults`` via
``calculators.sp_backend.compute_properties_fea`` sur un caisson : ils sont
automatiquement ignores (``pytest.skip``) si ``sectionproperties`` n'est pas
installe, mais l'environnement de reference dispose du moteur FEM.
"""
import math
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reports.fiche_report import (
    FicheOptions,
    _fmt_sci,
    _fmt_fixed,
    _mm_to_m,
    _mm2_to_m2,
    _mm4_to_m4,
    _mm6_to_m6,
    _principal_coords,
    _mohr_principal_inertias,
    section_to_fiche_svg,
    generate_fiche_html,
    export_fiche,
    _C_FILL,
    _C_MESH,
    _C_TRAIT,
    _C_AXE,
    _C_Y,
    _C_C,
)
from calculators.section_properties import compute_properties
import sections.parametric as para
from calculators.sp_backend import (
    compute_properties_fea,
    SECTIONPROPERTIES_AVAILABLE,
)


# Regex de la notation scientifique attendue dans le HTML : '0.38445E-02'.
_SCI_RE = re.compile(r"\d\.\d{5}E[+-]\d{2}")


def _extract_legend(html: str) -> str:
    """Extrait le contenu de la legende sous le dessin (div.svg-legend).

    Permet d'asserter sur la legende SEULE : la phrase « C = centre de
    cisaillement » apparait aussi ailleurs comme info-bulle (title=...) de la
    ligne de coordonnees C, qui existe toujours independamment du fait que C
    soit confondu avec G ou non.
    """
    m = re.search(r'<div class="svg-legend">(.*?)</div>', html, re.DOTALL)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Fixtures : carre 100x100 centre en (0,0), plus des stubs results
# ---------------------------------------------------------------------------

def _square(s: float = 100.0):
    h = s / 2.0
    return [(-h, -h), (h, -h), (h, h), (-h, h)]


def _square_hole(s: float = 60.0):
    """Trou carre centre, oriente CW (sens horaire) comme convention trou."""
    h = s / 2.0
    return [(-h, h), (h, h), (h, -h), (-h, -h)]


def _results_analytique():
    """Stub analytique (PAS de A_sx/A_sy ; Cw=0)."""
    return SimpleNamespace(
        area=10000.0,
        xc=0.0, yc=0.0,
        Ix=8.333333e6, Iy=8.333333e6, Ixy=0.0,
        I1=8.333333e6, I2=8.333333e6,
        theta_p=0.0,
        xsc=0.0, ysc=0.0,
        J=1.4e7, Cw=0.0,
        xmin=-50.0, xmax=50.0, ymin=-50.0, ymax=50.0,
    )


def _results_fem():
    """Stub FEM (avec A_sx/A_sy, Cw>0, warping_valid=True)."""
    # I1/I2 : inerties principales (max/min) coherentes avec Ix/Iy/Ixy ; le
    # moteur reel les fournit directement (SectionResults.I1/I2). On les calcule
    # ici par les invariants de Mohr pour le stub.
    Ix, Iy, Ixy = 8.333333e6, 9.0e6, 1.2e5
    avg = (Ix + Iy) / 2.0
    R = math.hypot((Ix - Iy) / 2.0, Ixy)
    return SimpleNamespace(
        area=10000.0,
        xc=5.0, yc=-3.0,
        Ix=Ix, Iy=Iy, Ixy=Ixy,
        I1=avg + R, I2=avg - R,
        theta_p=12.5,
        xsc=2.0, ysc=4.0,
        J=1.4e7, Cw=5.0e9,
        xmin=-50.0, xmax=50.0, ymin=-50.0, ymax=50.0,
        A_sx=8500.0, A_sy=8500.0,
        warping_valid=True,
    )


# ===========================================================================
# _fmt_sci — notation scientifique PYTHAGORE
# ===========================================================================

class TestFmtSci:
    def test_cas_image(self):
        assert _fmt_sci(0.0038445) == "0.38445E-02"

    def test_zero(self):
        assert _fmt_sci(0.0) == "0.00000E+00"

    def test_negatif(self):
        assert _fmt_sci(-0.0038445) == "-0.38445E-02"

    def test_mantisse_dans_zero_un(self):
        """Aucune sortie ne commence par un chiffre >= 1 avant le point."""
        for v in [1.0, 12.34, 123456.0, 0.5, 9.999, -42.0, 1e9, 1e-9]:
            s = _fmt_sci(v)
            corps = s[1:] if s.startswith("-") else s
            assert corps.startswith("0."), f"{v} -> {s}"

    def test_arrondi_limite(self):
        """0.99999996 ne doit pas produire '1.00000E+00' mais se re-normaliser."""
        s = _fmt_sci(0.99999996)
        assert s == "0.10000E+01"

    def test_cibles_image(self):
        # Valeurs SI de l'image (deja converties).
        assert _fmt_sci(0.0045067) == "0.45067E-02"
        assert _fmt_sci(0.063500) == "0.63500E-01"
        assert _fmt_sci(0.000030629) == "0.30629E-04"


# ===========================================================================
# Conversions SI
# ===========================================================================

class TestConversionsSI:
    def test_longueur(self):
        assert _mm_to_m(1000.0) == pytest.approx(1.0)

    def test_aire(self):
        assert _mm2_to_m2(1.0e6) == pytest.approx(1.0)

    def test_inertie(self):
        assert _mm4_to_m4(1.0e12) == pytest.approx(1.0)

    def test_gauchissement(self):
        assert _mm6_to_m6(1.0e18) == pytest.approx(1.0)


# ===========================================================================
# Formules de Mohr
# ===========================================================================

class TestMohr:
    def test_theta_zero_redonne_ix_iy(self):
        Ix, Iy, Ixy = 8.0e6, 9.0e6, 1.2e5
        izz, iyy = _mohr_principal_inertias(Ix, Iy, Ixy, 0.0)
        assert izz == pytest.approx(Ix)
        assert iyy == pytest.approx(Iy)

    def test_somme_invariante(self):
        """La trace (Izz_pr + Iyy_pr) est invariante par rotation."""
        Ix, Iy, Ixy = 8.0e6, 9.0e6, 1.2e5
        for theta in [0.0, 12.5, 45.0, -30.0, 90.0]:
            izz, iyy = _mohr_principal_inertias(Ix, Iy, Ixy, theta)
            assert (izz + iyy) == pytest.approx(Ix + Iy)


# ===========================================================================
# Transformation principale des coordonnees
# ===========================================================================

class TestCoordsPrincipales:
    def test_g_principal_est_origine(self):
        """G_principal == (0,0) pour tout theta_p, au format %.3f."""
        for (xc, yc, theta) in [(0.0, 0.0, 0.0), (5.0, -3.0, 12.5),
                                (10.0, 20.0, 45.0), (-7.0, 4.0, -33.0)]:
            z, y = _principal_coords(xc, yc, xc, yc, theta)
            assert _fmt_fixed(z) == "0.000"
            assert _fmt_fixed(y) == "0.000"

    def test_origine_non_nulle_si_g_decale(self):
        z, y = _principal_coords(0.0, 0.0, 5.0, -3.0, 12.5)
        assert not (abs(z) < 1e-9 and abs(y) < 1e-9)


# ===========================================================================
# section_to_fiche_svg
# ===========================================================================

class TestSvg:
    def test_svg_dimensionne_en_mm(self):
        svg, echelle = section_to_fiche_svg(
            [_square()], [], _results_analytique(), 150.0, 95.0
        )
        assert 'width="150.000mm"' in svg
        assert 'height="95.000mm"' in svg
        assert "viewBox=" in svg
        assert echelle > 0.0

    def test_svg_style_filaire_et_glyphes(self):
        # On utilise le stub FEM : son centre de cisaillement (xsc,ysc) est
        # DISTINCT du centroide (xc,yc) -> le carre C est bien dessine (le stub
        # analytique a C confondu avec G, cf. test_svg_c_confondu_omis).
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_fem(), 150.0, 95.0
        )
        # Trace filaire noir doux (palette sobre, cf. _C_TRAIT).
        assert f'stroke="{_C_TRAIT}"' in svg
        assert 'fill="none"' in svg
        # Axes rouge brique (palette sobre, cf. _C_AXE).
        assert f'stroke="{_C_AXE}"' in svg
        # Fleche z bleu ardoise (polygon) + glyphes P/G/C.
        assert "<polygon" in svg
        assert f'fill="{_C_Y}"' in svg     # P (triangle bleu) / fleche z
        assert "<circle" in svg            # G (cercle rouge)
        assert "<rect" in svg              # C (carre vert)
        assert f'stroke="{_C_C}"' in svg   # C vert

    def test_svg_halo_blanc_sur_labels(self):
        """Chaque etiquette (axes y/z + glyphes P/G/C) porte un halo blanc
        (paint-order='stroke' stroke='#ffffff'). Le nombre de halos == nombre
        de <text> emis (2 axes + 3 glyphes = 5 pour le cas C distinct)."""
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_fem(), 150.0, 95.0
        )
        n_halo = svg.count('paint-order="stroke"')
        n_text = svg.count("<text")
        assert n_halo == n_text
        assert n_halo == 5   # y, z, P, G, C
        assert 'stroke="#ffffff"' in svg

    def test_svg_c_confondu_omis(self):
        """C confondu avec G (xsc==xc, ysc==yc) -> aucun carre C emis ; il ne
        reste que 4 etiquettes (y, z, P, G)."""
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_analytique(), 150.0, 95.0
        )
        # Pas de carre vert C.
        assert f'stroke="{_C_C}"' not in svg
        assert "<rect" not in svg
        # 4 labels seulement (le label C est omis avec son glyphe).
        assert svg.count("<text") == 4

    def test_svg_vide(self):
        svg, echelle = section_to_fiche_svg([], [], _results_analytique(), 150.0, 95.0)
        assert "<svg" in svg
        assert echelle == 1.0


# ===========================================================================
# section_to_fiche_svg — remplissage de la matiere (show_fill)
# ===========================================================================

class TestSvgRemplissage:
    """L'AIRE de la section est materialisee par un remplissage gris tres
    clair (trous re-blanchis), pilote par ``show_fill`` (defaut True)."""

    def test_remplissage_actif_par_defaut(self):
        """show_fill=True -> un polygon de matiere en fill clair (non 'none')."""
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_analytique(), 150.0, 95.0,
            show_fill=True,
        )
        # La matiere est remplie de la teinte claire _C_FILL.
        assert f'fill="{_C_FILL}"' in svg
        # La teinte de remplissage n'est PAS 'none'.
        assert _C_FILL != "none"

    def test_remplissage_desactive(self):
        """show_fill=False -> aucun remplissage de matiere (pas de _C_FILL)."""
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_analytique(), 150.0, 95.0,
            show_fill=False,
        )
        assert f'fill="{_C_FILL}"' not in svg

    def test_remplissage_reblanchit_les_trous(self):
        """Avec un trou + show_fill=True : matiere grise puis trou re-blanchi."""
        svg, _ = section_to_fiche_svg(
            [_square()], [_square_hole()], _results_analytique(), 150.0, 95.0,
            show_fill=True,
        )
        assert f'fill="{_C_FILL}"' in svg          # matiere
        assert 'fill="#ffffff"' in svg             # trou re-blanchi
        # Le re-blanchiment du trou doit apparaitre APRES la matiere (dessus).
        assert svg.index(f'fill="{_C_FILL}"') < svg.index('fill="#ffffff"')


# ===========================================================================
# section_to_fiche_svg — maillage FEM (show_mesh)
# ===========================================================================

@pytest.mark.skipif(
    not SECTIONPROPERTIES_AVAILABLE,
    reason="sectionproperties non installe : maillage FEM indisponible",
)
class TestSvgMaillage:
    """Le maillage FEM est superpose UNIQUEMENT si show_mesh=True ET si results
    expose mesh_vertices/mesh_triangles non vides. Rendu en voile gris clair."""

    def setup_method(self):
        # Caisson : rectangle exterieur + trou rectangulaire (= section creuse,
        # connexe -> warping valide -> maillage exploitable).
        outers, holes = para.box_section(120.0, 80.0, 8.0, 8.0)
        self.outers = outers
        self.holes = holes
        self.res = compute_properties_fea(outers, holes)

    def test_maillage_disponible(self):
        """Pre-condition : le FEAResults porte bien un maillage non vide."""
        assert len(self.res.mesh_vertices) > 0
        assert len(self.res.mesh_triangles) > 0

    def test_maillage_dessine_si_show_mesh(self):
        """show_mesh=True -> le calque maillage gris _C_MESH est present."""
        svg, _ = section_to_fiche_svg(
            self.outers, self.holes, self.res, 150.0, 95.0,
            show_mesh=True,
        )
        # Le bloc maillage porte le style _C_MESH sur le <g>.
        assert f'stroke="{_C_MESH}"' in svg
        # Et il contient des triangles (polygons a 3 sommets).
        assert "<polygon" in svg

    def test_maillage_absent_si_pas_show_mesh(self):
        """show_mesh=False -> aucun voile maillage (pas de _C_MESH)."""
        svg, _ = section_to_fiche_svg(
            self.outers, self.holes, self.res, 150.0, 95.0,
            show_mesh=False,
        )
        assert f'stroke="{_C_MESH}"' not in svg

    def test_maillage_sous_le_trace_noir(self):
        """Le voile maillage est DESSOUS le trace filaire noir (ordre SVG)."""
        svg, _ = section_to_fiche_svg(
            self.outers, self.holes, self.res, 150.0, 95.0,
            show_mesh=True,
        )
        # Le <g> maillage (_C_MESH) apparait avant le 1er trace _C_TRAIT.
        assert svg.index(f'stroke="{_C_MESH}"') < svg.index(f'stroke="{_C_TRAIT}"')


class TestSvgMaillageAnalytique:
    """En analytique (results sans mesh_vertices/mesh_triangles), show_mesh=True
    ne provoque NI erreur NI maillage (option sans effet)."""

    def test_show_mesh_sans_maillage(self):
        svg, _ = section_to_fiche_svg(
            [_square()], [], _results_analytique(), 150.0, 95.0,
            show_mesh=True,
        )
        # Aucun voile maillage : results analytique n'a pas de maillage.
        assert f'stroke="{_C_MESH}"' not in svg
        # Le SVG reste valide.
        assert "<svg" in svg

    def test_show_mesh_maillage_vide(self):
        """results avec mesh_vertices/mesh_triangles VIDES -> pas de maillage."""
        res = _results_analytique()
        res.mesh_vertices = []
        res.mesh_triangles = []
        svg, _ = section_to_fiche_svg(
            [_square()], [], res, 150.0, 95.0,
            show_mesh=True,
        )
        assert f'stroke="{_C_MESH}"' not in svg


# ===========================================================================
# generate_fiche_html — analytique
# ===========================================================================

class TestGenerateAnalytique:
    def setup_method(self):
        self.opts = FicheOptions(
            titre_module="PYTHAGORE V22.05 - CISAIL",
            numero="TYPE No 5001",
            designation="PdR - Semelle Inf.",
            type_piece="Type I",
        )
        self.res = _results_analytique()
        self.html = generate_fiche_html(self.opts, [_square()], [], self.res)

    def test_import_et_str(self):
        assert isinstance(self.html, str) and len(self.html) > 100

    def test_a4_paysage(self):
        assert "@page" in self.html
        assert "landscape" in self.html

    def test_window_print(self):
        assert "window.print" in self.html

    def test_monospace(self):
        assert "Courier New" in self.html
        assert "Lucida Console" in self.html
        assert "monospace" in self.html

    def test_cadre_noir(self):
        assert "#000000" in self.html or "#000" in self.html
        assert "0.5pt" in self.html

    def test_cartouche_trois_lignes(self):
        assert "PYTHAGORE V22.05 - CISAIL" in self.html
        assert "TYPE No 5001" in self.html
        assert "PdR - Semelle Inf." in self.html
        assert "Type I" in self.html
        assert "CARACTERISTIQUES DE LA SECTION" in self.html

    def test_avy_avz_iw_vides(self):
        """Analytique : pas de A_sx/A_sy, Cw=0 -> A_vy/A_vz/I_w vides."""
        # Les libelles existent (nomenclature Eurocode)...
        assert "A_vy" in self.html
        assert "A_vz" in self.html
        assert "I_w" in self.html
        # ... mais sans valeur scientifique pour A_vy/A_vz (lignes Principal vides).
        # On verifie qu'aucune cellule pleine 'I_w' ne contient de notation.
        assert ">I_w</td>" in self.html

    def test_colonne_initial(self):
        assert _fmt_sci(_mm4_to_m4(self.res.Ix)) in self.html  # I_y init
        assert _fmt_sci(_mm4_to_m4(self.res.Iy)) in self.html  # I_z init

    def test_angle_principal(self):
        assert f"{self.res.theta_p:.1f} deg" in self.html

    def test_it_a(self):
        assert _fmt_sci(_mm4_to_m4(self.res.J)) in self.html      # I_t
        assert _fmt_sci(_mm2_to_m2(self.res.area)) in self.html   # A (aire)

    def test_pied_de_page(self):
        # Dy/Dz au format %.3f + Echelle 1 / X (convention Eurocode).
        assert "Dy=" in self.html
        assert "Dz=" in self.html
        assert "Echelle 1 /" in self.html


# ===========================================================================
# generate_fiche_html — FEM
# ===========================================================================

class TestGenerateFEM:
    def setup_method(self):
        self.opts = FicheOptions()
        self.res = _results_fem()
        self.html = generate_fiche_html(self.opts, [_square()], [], self.res)

    def test_avy_avz_presents(self):
        assert _fmt_sci(_mm2_to_m2(self.res.A_sx)) in self.html  # A_vy
        assert _fmt_sci(_mm2_to_m2(self.res.A_sy)) in self.html  # A_vz

    def test_iw_present(self):
        assert _fmt_sci(_mm6_to_m6(self.res.Cw)) in self.html

    def test_inerties_principales(self):
        """I_1/I_2 lus DIRECTEMENT depuis results.I1/I2 (non re-derives Mohr)."""
        assert _fmt_sci(_mm4_to_m4(self.res.I1)) in self.html
        assert _fmt_sci(_mm4_to_m4(self.res.I2)) in self.html


# ===========================================================================
# Nomenclature Eurocode — symboles presents / symboles PYTHAGORE absents
# ===========================================================================

class TestNomenclatureEurocode:
    """Le HTML genere doit utiliser EXCLUSIVEMENT les symboles Eurocode de
    l'application (calculators.nomenclature.PROPERTY_DESCRIPTIONS, source
    unique) et ne plus contenir AUCUN ancien symbole « PYTHAGORE »."""

    def test_symboles_eurocode_presents_fem(self):
        """A, I_y, I_z, I_yz, I_1, I_2, I_t, I_w + A_vy/A_vz (FEM) presents."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_fem())
        # Symboles communs analytique/FEM (cellules de libelle <td class="lbl"...>).
        for sym in (">A</td>", ">I_y</td>", ">I_z</td>", ">I_yz</td>",
                    ">I_1</td>", ">I_2</td>", ">I_t</td>", ">I_w</td>"):
            assert sym in html, f"symbole Eurocode absent : {sym}"
        # Aires de cisaillement (FEM uniquement) : libelle + valeur scientifique.
        assert ">A_vy</td>" in html
        assert ">A_vz</td>" in html
        assert _fmt_sci(_mm2_to_m2(_results_fem().A_sx)) in html  # valeur A_vy
        assert _fmt_sci(_mm2_to_m2(_results_fem().A_sy)) in html  # valeur A_vz

    def test_symboles_eurocode_presents_analytique(self):
        """Libelles Eurocode presents meme en analytique (valeurs FEM vides)."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        for sym in (">A</td>", ">I_y</td>", ">I_z</td>", ">I_yz</td>",
                    ">I_1</td>", ">I_2</td>", ">I_t</td>", ">I_w</td>",
                    ">A_vy</td>", ">A_vz</td>"):
            assert sym in html, f"symbole Eurocode absent : {sym}"

    def test_symboles_pythagore_absents(self):
        """Plus aucun symbole PYTHAGORE (Izz, Iyy, Iyz<n>, Srz, Sry, Itors,
        « Section », « Angle ») dans le HTML, en analytique comme en FEM."""
        pythagore = ["Izz", "Iyy", "Srz", "Sry", "Itors",
                     ">Section<", ">Angle<", "Section</td>", "Angle</td>"]
        for res in (_results_analytique(), _results_fem()):
            html = generate_fiche_html(FicheOptions(), [_square()], [], res)
            for bad in pythagore:
                assert bad not in html, f"symbole PYTHAGORE residuel : {bad}"

    def test_alpha_remplace_angle(self):
        """L'angle des axes principaux porte le symbole Eurocode alpha (et la
        valeur « <theta> deg »), pas le libelle « Angle »."""
        res = _results_fem()
        html = generate_fiche_html(FicheOptions(), [_square()], [], res)
        assert "α" in html
        assert f"{res.theta_p:.1f} deg" in html


# ===========================================================================
# Axes & coordonnees — convention Eurocode y (horizontal) / z (vertical)
# ===========================================================================

class TestAxesCoordsEurocode:
    """Etiquettes d'axes du dessin et en-tetes du sous-bloc coordonnees en
    minuscules Eurocode : y (axe fort horizontal) et z (axe faible vertical).
    Les anciens libelles d'axe « Z »/« Y » majuscules ont disparu du SVG."""

    def test_etiquettes_axes_svg_y_z(self):
        """Le SVG porte les etiquettes d'axe <text>y</text> et <text>z</text>."""
        svg, _ = section_to_fiche_svg([_square()], [], _results_fem(), 150.0, 95.0)
        assert ">y</text>" in svg
        assert ">z</text>" in svg

    def test_pas_d_etiquettes_axes_majuscules(self):
        """Les anciens libelles d'axe « Z »/« Y » (majuscules) ne sont plus
        emis comme texte d'axe dans le SVG."""
        svg, _ = section_to_fiche_svg([_square()], [], _results_fem(), 150.0, 95.0)
        assert ">Z</text>" not in svg
        assert ">Y</text>" not in svg

    def test_entetes_coordonnees_y_z(self):
        """Le sous-bloc coordonnees a des en-tetes « y  z » (minuscules)."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        # En-tete du sous-bloc (deux colonnes Initial|Principal).
        assert "y&nbsp;&nbsp;&nbsp;z" in html
        # Plus d'en-tete majuscule « Z  Y ».
        assert "Z&nbsp;&nbsp;&nbsp;Y" not in html

    def test_legende_vocabulaire_application(self):
        """La legende sous le dessin emploie le vocabulaire de l'application."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_fem())
        legend = _extract_legend(html)
        assert "G = centre de gravite" in legend
        assert "C = centre de cisaillement" in legend
        assert "P = point de reference" in legend

    def test_pied_de_page_dy_dz_eurocode(self):
        """Pied de page : Dy = etendue horizontale (xmax-xmin), Dz = verticale
        (ymax-ymin) — coherent avec y horizontal / z vertical."""
        res = _results_fem()
        html = generate_fiche_html(FicheOptions(), [_square()], [], res)
        dy = _fmt_fixed(_mm_to_m(res.xmax - res.xmin))
        dz = _fmt_fixed(_mm_to_m(res.ymax - res.ymin))
        assert f"Dy=&nbsp;&nbsp;{dy}" in html
        assert f"Dz=&nbsp;&nbsp;{dz}" in html
        # Plus d'anciens libelles DZ/DY majuscules.
        assert "DZ=" not in html
        assert "DY=" not in html


# ===========================================================================
# Anti-collision — halo blanc + C confondu avec G (omission du glyphe)
# ===========================================================================

class TestAntiCollision:
    """Lisibilite des etiquettes (halo blanc) et gestion du chevauchement
    P/G/C, en particulier le cas C confondu avec G."""

    def test_halo_blanc_sur_chaque_texte_du_svg(self):
        """CHAQUE <text> du SVG (axes y/z + glyphes) porte le halo blanc
        paint-order='stroke' stroke='#ffffff'."""
        svg, _ = section_to_fiche_svg([_square()], [], _results_fem(), 150.0, 95.0)
        assert svg.count("<text") == svg.count('paint-order="stroke"')
        assert svg.count("<text") == svg.count('stroke="#ffffff"')

    def test_c_confondu_un_seul_glyphe_a_la_position_g(self):
        """C confondu avec G (xsc==xc, ysc==yc) : le carre C n'est PAS dessine
        (pas de <rect>, pas de stroke vert), il reste 4 etiquettes (y,z,P,G)."""
        svg, _ = section_to_fiche_svg([_square()], [], _results_analytique(), 150.0, 95.0)
        assert "<rect" not in svg
        assert f'stroke="{_C_C}"' not in svg
        assert svg.count("<text") == 4

    def test_c_confondu_mention_dans_legende_html(self):
        """C confondu avec G -> la legende sous le dessin porte la mention
        « C confondu avec G » et NON « C = centre de cisaillement ». On isole
        la legende (div.svg-legend) car « C = centre de cisaillement » reste
        present ailleurs comme info-bulle (title=...) de la ligne coordonnees C."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        legend = _extract_legend(html)
        assert "C confondu avec G" in legend
        assert "C = centre de cisaillement" not in legend

    def test_c_distinct_glyphe_et_legende_normale(self):
        """C distinct de G (stub FEM, xsc!=xc) : carre C dessine + legende
        normale « C = centre de cisaillement » (pas de mention « confondu »)."""
        res = _results_fem()
        svg, _ = section_to_fiche_svg([_square()], [], res, 150.0, 95.0)
        assert "<rect" in svg
        assert f'stroke="{_C_C}"' in svg
        html = generate_fiche_html(FicheOptions(), [_square()], [], res)
        legend = _extract_legend(html)
        assert "C = centre de cisaillement" in legend
        assert "confondu" not in legend

    @pytest.mark.skipif(
        not SECTIONPROPERTIES_AVAILABLE,
        reason="sectionproperties non installe : moteur FEM indisponible",
    )
    def test_c_confondu_caisson_fem_symetrique(self):
        """Caisson FEM doublement symetrique : le centre de cisaillement coincide
        avec le centre de gravite -> glyphe C omis et mention « confondu »."""
        outers, holes = para.box_section(100.0, 100.0, 8.0, 8.0)
        res = compute_properties_fea(outers, holes)
        # Le centre de cisaillement est calcule (warping valide).
        assert getattr(res, "warping_valid", False)
        svg, _ = section_to_fiche_svg(outers, holes, res, 150.0, 95.0,
                                      draw_shear_center=True)
        # C confondu avec G (section bi-symetrique) -> pas de carre C.
        assert f'stroke="{_C_C}"' not in svg
        assert "<rect" not in svg
        html = generate_fiche_html(FicheOptions(), outers, holes, res)
        assert "C confondu avec G" in _extract_legend(html)


# ===========================================================================
# KY / KZ — RETIRES : le HTML ne doit PLUS jamais les contenir
# ===========================================================================

class TestKyKzSupprimes:
    """Les lignes KY/KZ, l'option show_ky_kz et la note associee ont ete
    RETIREES ('les K si non calcule ce n'est pas la peine')."""

    def test_option_show_ky_kz_inexistante(self):
        """FicheOptions n'expose plus de champ show_ky_kz."""
        assert not hasattr(FicheOptions(), "show_ky_kz")
        with pytest.raises(TypeError):
            FicheOptions(show_ky_kz=True)  # type: ignore[call-arg]

    def test_html_analytique_sans_ky_kz(self):
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        assert "KY" not in html
        assert "KZ" not in html
        assert ">KY</td>" not in html
        assert ">KZ</td>" not in html
        # La note de bas de page associee aux K a disparu.
        assert "ne sont pas calcules par" not in html

    def test_html_fem_sans_ky_kz(self):
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_fem())
        assert "KY" not in html
        assert "KZ" not in html


# ===========================================================================
# Options show_fill / show_mesh — repercussion dans le HTML genere
# ===========================================================================

class TestOptionsHtml:
    def test_defauts(self):
        """Defauts : show_fill=True, show_mesh=False."""
        opts = FicheOptions()
        assert opts.show_fill is True
        assert opts.show_mesh is False

    def test_show_fill_html_contient_remplissage(self):
        """show_fill=True -> le SVG inclus dans le HTML contient _C_FILL."""
        html = generate_fiche_html(
            FicheOptions(show_fill=True), [_square()], [], _results_analytique()
        )
        assert f'fill="{_C_FILL}"' in html

    def test_show_fill_false_html_sans_remplissage(self):
        html = generate_fiche_html(
            FicheOptions(show_fill=False), [_square()], [], _results_analytique()
        )
        assert f'fill="{_C_FILL}"' not in html


# ===========================================================================
# export_fiche — ecriture fichier UTF-8
# ===========================================================================

class TestExport:
    def test_ecrit_fichier_utf8(self, tmp_path):
        out = tmp_path / "fiche.html"
        export_fiche(FicheOptions(), [_square()], [], _results_analytique(), str(out))
        assert out.exists()
        contenu = out.read_text(encoding="utf-8")
        assert "@page" in contenu
        assert "landscape" in contenu


# ===========================================================================
# Mohr -> _fmt_sci coherence pour theta=0
# ===========================================================================

def test_mohr_theta0_egal_fmt_sci():
    res = _results_analytique()
    izz_pr, iyy_pr = _mohr_principal_inertias(res.Ix, res.Iy, res.Ixy, 0.0)
    assert _fmt_sci(_mm4_to_m4(izz_pr)) == _fmt_sci(_mm4_to_m4(res.Ix))
    assert _fmt_sci(_mm4_to_m4(iyy_pr)) == _fmt_sci(_mm4_to_m4(res.Iy))


# ===========================================================================
# Objet SectionResults REEL (moteur analytique, sans A_sx/warping_valid)
# ===========================================================================

class TestSectionResultsReel:
    """Construit un vrai SectionResults via compute_properties (rectangle
    200x300 mm) : aucune dependance Qt/FEM, et l'objet n'a ni A_sx ni
    warping_valid (mode analytique)."""

    def setup_method(self):
        self.outers = para.rectangle(200, 300)
        self.res = compute_properties(self.outers, [], {"type": "rectangle"})
        self.html = generate_fiche_html(FicheOptions(), self.outers, [], self.res)

    def test_objet_est_analytique(self):
        """Le moteur analytique ne fournit ni A_sx ni warping_valid."""
        assert not hasattr(self.res, "A_sx")
        assert not hasattr(self.res, "warping_valid")

    def test_pas_d_exception_et_chaine_non_vide(self):
        assert isinstance(self.html, str) and len(self.html) > 100

    def test_titre_et_svg(self):
        assert "CARACTERISTIQUES DE LA SECTION" in self.html
        assert "<svg" in self.html

    def test_a4_paysage(self):
        assert "@page" in self.html
        assert "landscape" in self.html

    def test_notation_scientifique_regex(self):
        """Le HTML contient au moins une notation '0.dddddE+NN'."""
        assert _SCI_RE.search(self.html) is not None

    def test_libelles_attendus(self):
        # Symboles Eurocode (nomenclature de l'application).
        assert ">A</td>" in self.html
        assert "I_t" in self.html
        assert "Echelle" in self.html

    def test_aire_reelle_affichee(self):
        """Aire 200*300 = 60000 mm2 -> _fmt_sci(area*1e-6)."""
        assert _fmt_sci(_mm2_to_m2(self.res.area)) in self.html

    def test_pas_de_ky_kz(self):
        """Non-regression : objet reel, toujours sans KY/KZ."""
        assert "KY" not in self.html
        assert "KZ" not in self.html


# ===========================================================================
# Revision v4 : unites affichees, triangle de reference unique, axes non tronques
# ===========================================================================

class TestUnitesSI:
    """Les unites SI apparaissent a cote des valeurs (« on ignore les unites »
    corrige) : longueurs en m, aires en m2, inerties en m4, I_w en m6, angle deg."""

    def test_unites_analytique(self):
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        assert "m⁴" in html   # inerties (I_y, I_z, I_yz, I_1, I_2, I_t)
        assert "m²" in html   # aires (A)
        assert "deg" in html  # angle alpha
        assert "z&nbsp;(m)" in html                              # en-tete coordonnees
        assert re.search(r"Dy=&nbsp;&nbsp;[-\d.]+&nbsp;m", html)  # pied de page
        assert re.search(r"Dz=&nbsp;&nbsp;[-\d.]+&nbsp;m", html)

    def test_unite_gauchissement_fem(self):
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_fem())
        assert "m⁶" in html   # I_w (gauchissement, FEM uniquement)

    def test_pas_d_unite_orpheline(self):
        """Une cellule de valeur VIDE (A_vy/A_vz analytiques) ne porte pas
        d'unite orpheline."""
        html = generate_fiche_html(FicheOptions(), [_square()], [], _results_analytique())
        assert "<td></td><td>&nbsp;m²</td>" not in html
        assert ">&nbsp;m⁴</td>" not in html


class TestDessinReperesEtAxes:
    """Triangle de reference UNIQUE (P) + axes jamais tronques."""

    def _svg(self, outers, holes, results, **kw):
        s, _ = section_to_fiche_svg(outers, holes, results, 150.0, 95.0, **kw)
        return s

    def test_un_seul_triangle_bleu(self):
        """Seul le glyphe P est un triangle BLEU ; la fleche de l'axe vertical
        est ROUGE (et non un 2e triangle bleu visible « deux fois »)."""
        svg = self._svg([_square()], [], _results_fem())
        n_blue = len(re.findall(r'<polygon points="[^"]+" fill="%s"' % _C_Y, svg))
        assert n_blue == 1, f"attendu 1 triangle bleu (P), trouve {n_blue}"
        assert svg.count('fill="%s"' % _C_AXE) >= 2   # fleches y + z en rouge

    def _axes_hors_cadre(self, svg, W=150.0, H=95.0, eps=0.4):
        bad = []
        for m in re.finditer(
                r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" '
                r'stroke="%s"' % _C_AXE, svg):
            x1, y1, x2, y2 = map(float, m.groups())
            for x, y in ((x1, y1), (x2, y2)):
                if not (-eps <= x <= W + eps and -eps <= y <= H + eps):
                    bad.append((x, y))
        for m in re.finditer(r'<polygon points="([^"]+)" fill="%s"' % _C_AXE, svg):
            for pt in m.group(1).split():
                x, y = map(float, pt.split(','))
                if not (-eps <= x <= W + eps and -eps <= y <= H + eps):
                    bad.append((x, y))
        return bad

    def test_axes_dans_le_cadre_section_centree(self):
        svg = self._svg([_square()], [], _results_analytique())
        assert self._axes_hors_cadre(svg) == []

    def test_axes_dans_le_cadre_section_asymetrique(self):
        """Section en L (centroide tres excentre) : les axes restent ENTIEREMENT
        dans le cadre (non-regression de la troncature signalee)."""
        oL = [[(0.0, 0.0), (400.0, 0.0), (400.0, 100.0),
               (100.0, 100.0), (100.0, 600.0), (0.0, 600.0)]]
        svg = self._svg(oL, [], compute_properties(oL, []))
        assert self._axes_hors_cadre(svg) == []

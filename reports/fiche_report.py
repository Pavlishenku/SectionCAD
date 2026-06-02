"""
Generateur de la « fiche » d'archive SectionCAD (style PYTHAGORE).

Ce module produit un livrable HTML autonome (CSS inline + SVG inline, AUCUNE
dependance externe : seulement math, dataclasses, datetime, typing) destine a
etre imprime en PDF via ``window.print()`` au format A4 PAYSAGE.

La fiche est une mise en page sobre, en police monospace, encadree d'un filet
noir fin, reprenant la presentation des fiches « caracteristiques de la
section » du logiciel PYTHAGORE :

- un cartouche superieur a 3 lignes (module / numero-designation-type / titre) ;
- une colonne gauche : tableau « Repere | Initial | Principal » (inerties,
  aires de cisaillement, coordonnees des points remarquables P/G/C), suivi de
  lignes pleine largeur (I_t, I_w, A). Les symboles sont ceux de la nomenclature
  Eurocode de l'application (calculators.nomenclature.PROPERTY_DESCRIPTIONS,
  source unique) : A, alpha, I_y, I_z, I_yz, I_1, I_2, A_vy, A_vz, I_t, I_w ;
- une colonne droite : dessin vectoriel epure de la section : matiere remplie
  d'un gris tres clair (trous en blanc), maillage FEM optionnel en voile gris,
  trace filaire noir doux par-dessus, axes rouges briques centres au centroide
  G (etiquettes y horizontal / z vertical), fleche z bleu ardoise, glyphes
  P/G/C en tons assagis avec HALO BLANC et offsets anti-chevauchement ;
- un pied de page (Dy, Dz, echelle).

Convention d'axes Eurocode : y-y = axe fort (horizontal), z-z = axe faible
(vertical). L'application SectionCAD dessine en x horizontal et y vertical ; on a
donc la correspondance x_dessin -> y_Eurocode et y_dessin -> z_Eurocode. Toutes
les grandeurs internes de ``results`` sont en millimetres et sont converties ici
en unites SI (m, m2, m4, m6) pour l'affichage.

Les attributs de ``results`` sont relus DIRECTEMENT (``getattr`` avec defaut)
afin de gerer indifferemment le moteur analytique (``SectionResults``, sans
aires de cisaillement, Cw=0) et le moteur FEM (``FEAResults``, avec A_sx/A_sy et
Cw>0). Aucune dependance a results_to_dict / fea_results_to_dict.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import List, Tuple, Optional

from calculators.nomenclature import PROPERTY_DESCRIPTIONS

# Seuil (mm papier) en deca duquel le centre de cisaillement C est considere
# confondu avec le centre de gravite G : on n'affiche alors pas un glyphe C
# redondant par-dessus G (cf. demande anti-chevauchement).
_C_CONFONDU_SEUIL_MM = 2.0


# ---------------------------------------------------------------------------
# Dataclass d'options
# ---------------------------------------------------------------------------

@dataclass
class FicheOptions:
    """Options editables de la fiche (cf. ui/fiche_dialog.py).

    - ``show_fill`` (defaut True) : remplit la matiere de la section d'un gris
      tres clair (trous laisses en blanc). C'est l'amelioration demandee : une
      SECTION pleine plutot qu'un simple fil de fer.
    - ``show_mesh`` (defaut False) : superpose le maillage FEM en voile gris
      clair, UNIQUEMENT si ``results`` expose mesh_vertices/mesh_triangles
      (moteur FEM). Cher visuellement, donc OFF par defaut ; sans maillage
      l'option est sans effet.
    """
    titre_module: str = "PYTHAGORE V22.05 - CISAIL"   # L1 du cartouche
    numero: str = ""                                   # ex "TYPE No 5001"
    designation: str = ""                              # ex "PdR - Semelle Inf."
    type_piece: str = ""                               # ex "Type I"
    titre_fiche: str = "CARACTERISTIQUES DE LA SECTION"  # L3 du cartouche
    show_fill: bool = True                             # remplit la matiere (aire grisee)
    show_mesh: bool = False                            # superpose le maillage FEM (si dispo)
    engine_label: str = ""                             # moteur de calcul


# ---------------------------------------------------------------------------
# Helpers de format
# ---------------------------------------------------------------------------

def _fmt_sci(v: float) -> str:
    """Notation scientifique PYTHAGORE « 0.38445E-02 ».

    Mantisse normalisee dans [0, 1) (et non [1, 10)), 5 decimales, suivie de
    « E », du signe de l'exposant et de l'exposant sur 2 chiffres.

    - ``v == 0`` -> ``'0.00000E+00'``.
    - ``v < 0``  -> prefixe ``'-'`` devant la mantisse.
    - Garde-fou : si l'arrondi de la mantisse atteint 1.00000, on re-normalise
      (mantisse /= 10, exposant += 1).

    Garantie : ``_fmt_sci(0.0038445) == '0.38445E-02'``.
    """
    if v == 0 or v != v:           # zero (ou NaN traite comme zero)
        return "0.00000E+00"

    negatif = v < 0
    av = abs(float(v))

    # Exposant tel que la mantisse soit dans [0, 1) : mant = av / 10**exp.
    exp = math.floor(math.log10(av)) + 1
    mant = av / (10.0 ** exp)

    # Arrondi a 5 decimales puis garde-fou de re-normalisation.
    mant = round(mant, 5)
    if mant >= 1.0:
        mant /= 10.0
        exp += 1
        mant = round(mant, 5)
    elif mant < 0.1:
        # Peut survenir a cause d'imprecisions flottantes sur log10 : la
        # mantisse devrait toujours commencer par un chiffre significatif.
        mant *= 10.0
        exp -= 1
        mant = round(mant, 5)

    # Normalisation du zero signe : si la mantisse arrondie est nulle (valeur
    # quasi-nulle negative), ne pas prefixer "-" pour eviter un "-0.00000E...".
    signe_exp = "+" if exp >= 0 else "-"
    prefixe = "-" if (negatif and mant != 0.0) else ""
    return f"{prefixe}{mant:.5f}E{signe_exp}{abs(exp):02d}"


def _fmt_fixed(v: float, decimals: int = 3) -> str:
    """Format decimal fixe (coordonnees, DZ/DY), ex ``'%.3f'``.

    On ajoute ``+ 0.0`` pour normaliser le zero signe (``-0.0`` -> ``0.0``) :
    sans cela un ``-0.0`` produit ``'-0.000'`` au lieu de ``'0.000'``.
    """
    return f"{v + 0.0:.{decimals}f}"


def _esc(text: str) -> str:
    """Echappement HTML minimal du texte utilisateur."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Conversions SI (mm internes -> SI affiche)
# ---------------------------------------------------------------------------

def _mm_to_m(v: float) -> float:
    """Longueur : mm -> m (* 1e-3)."""
    return v * 1e-3


def _mm2_to_m2(v: float) -> float:
    """Aire : mm2 -> m2 (* 1e-6)."""
    return v * 1e-6


def _mm4_to_m4(v: float) -> float:
    """Inertie : mm4 -> m4 (* 1e-12)."""
    return v * 1e-12


def _mm6_to_m6(v: float) -> float:
    """Constante de gauchissement : mm6 -> m6 (* 1e-18)."""
    return v * 1e-18


# ---------------------------------------------------------------------------
# Transformation principale des coordonnees + formules de Mohr
# ---------------------------------------------------------------------------

def _principal_coords(px: float, py: float,
                      xc: float, yc: float,
                      theta_p_deg: float) -> Tuple[float, float]:
    """Coordonnees (Z, Y) d'un point dans le repere PRINCIPAL centre en G.

    ``d = (px - xc, py - yc)`` puis rotation de ``-theta_p`` autour de G :
        Z_pr = d.x*cos(t) + d.y*sin(t)
        Y_pr = -d.x*sin(t) + d.y*cos(t)
    En particulier G_principal == (0, 0) pour tout ``theta_p``.
    Les valeurs retournees sont en mm (conversion SI a effectuer par l'appelant).
    """
    t = math.radians(theta_p_deg)
    dx = px - xc
    dy = py - yc
    cos_t = math.cos(t)
    sin_t = math.sin(t)
    z_pr = dx * cos_t + dy * sin_t
    y_pr = -dx * sin_t + dy * cos_t
    return z_pr, y_pr


def _mohr_principal_inertias(Ix: float, Iy: float, Ixy: float,
                             theta_p_deg: float) -> Tuple[float, float]:
    """Inerties dans le repere principal via la transformation de Mohr.

        th = radians(theta_p) ; c = cos(2*th) ; s = sin(2*th)
        Izz_pr = (Ix+Iy)/2 + ((Ix-Iy)/2)*c - Ixy*s
        Iyy_pr = (Ix+Iy)/2 - ((Ix-Iy)/2)*c + Ixy*s

    Redonne exactement {Ix, Iy} lorsque theta_p == 0. Valeurs en mm4.
    """
    th = math.radians(theta_p_deg)
    c = math.cos(2.0 * th)
    s = math.sin(2.0 * th)
    demi_somme = (Ix + Iy) / 2.0
    demi_diff = (Ix - Iy) / 2.0
    izz_pr = demi_somme + demi_diff * c - Ixy * s
    iyy_pr = demi_somme - demi_diff * c + Ixy * s
    return izz_pr, iyy_pr


def _c_confondu_avec_g(results,
                       outer_polygons: List[List[Tuple[float, float]]],
                       hole_polygons: List[List[Tuple[float, float]]],
                       svg_w_mm: float,
                       svg_h_mm: float,
                       draw_shear_center: bool) -> bool:
    """Indique si le centre de cisaillement C est confondu avec G en PAPIER.

    Le test est effectue dans le repere PAPIER (mm) en repliquant exactement le
    calcul d'ajustement (« fit ») de ``section_to_fiche_svg`` : on convertit G
    (centroide) et C (centre de cisaillement) en coordonnees papier puis on
    mesure leur distance. Si elle est inferieure a ``_C_CONFONDU_SEUIL_MM``
    (~2 mm), C est juge confondu avec G.

    Factorise la detection pour que le SVG (omission du glyphe C) et le HTML
    (mention « C confondu avec G » dans la legende) restent strictement
    coherents — aucune divergence possible.

    Retourne ``False`` si ``draw_shear_center`` est faux (centre non calcule) ou
    si la geometrie est vide.
    """
    if not draw_shear_center:
        return False

    hole_polygons = hole_polygons or []
    all_x: List[float] = []
    all_y: List[float] = []
    for poly in outer_polygons + hole_polygons:
        for (x, y) in poly:
            all_x.append(x)
            all_y.append(y)
    if not all_x:
        return False

    xc = getattr(results, "xc", 0.0)
    yc = getattr(results, "yc", 0.0)
    xsc = getattr(results, "xsc", 0.0)
    ysc = getattr(results, "ysc", 0.0)

    xmin_w = min(all_x)
    xmax_w = max(all_x)
    ymin_w = min(all_y)
    ymax_w = max(all_y)
    # Memes points remarquables que dans section_to_fiche_svg (origine + G + C).
    for (px, py) in [(0.0, 0.0), (xc, yc), (xsc, ysc)]:
        xmin_w = min(xmin_w, px)
        xmax_w = max(xmax_w, px)
        ymin_w = min(ymin_w, py)
        ymax_w = max(ymax_w, py)
    ext_w = max(xmax_w - xmin_w, 1e-9)
    ext_h = max(ymax_w - ymin_w, 1e-9)

    draw_w = svg_w_mm - 2.0 * _FICHE_SVG_MARGIN_MM
    draw_h = svg_h_mm - 2.0 * _FICHE_SVG_MARGIN_MM
    fit = min(draw_w / ext_w, draw_h / ext_h)   # mm dessine / mm reel

    # Distance papier = distance monde * fit (le facteur d'echelle est isotrope).
    d_pap = math.hypot(xsc - xc, ysc - yc) * fit
    return d_pap < _C_CONFONDU_SEUIL_MM


# ---------------------------------------------------------------------------
# Dessin SVG re-style (filaire noir, axes rouges, glyphes P/G/C)
# ---------------------------------------------------------------------------

# Dimensions physiques (mm) du cadre de dessin de la colonne droite. Le SVG est
# dimensionne en mm physiques (attributs width/height en 'mm', viewBox en mm)
# afin qu'une impression a 100 % donne une echelle VRAIE mesurable a la regle.
_FICHE_SVG_W_MM = 150.0   # largeur physique du dessin (mm)
_FICHE_SVG_H_MM = 95.0    # hauteur physique du dessin (mm)
# Marge interne reduite (etait 12.0) pour que le dessin REMPLISSE mieux la
# colonne droite, a la densite de la reference Pythagore. 6 mm suffisent aux
# etiquettes d'axe et aux glyphes.
_FICHE_SVG_MARGIN_MM = 6.0    # marge interne (mm) reservee aux axes/glyphes

# ---------------------------------------------------------------------------
# Palette SOBRE (identite Pythagore conservee, tons assagis). REGLE D'OR :
# la couleur PORTE une information (un repere physique, un axe). Tout le reste
# est noir/gris. Les hex des classes CSS .glyph-* sont STRICTEMENT egaux a
# ceux des glyphes SVG correspondants (coherence dessin <-> tableau).
# ---------------------------------------------------------------------------
_C_TRAIT = "#111111"   # trace filaire (noir doux ; le CADRE de page reste #000000)
_C_FILL = "#f3f3f3"    # remplissage matiere (gris tres clair, neutre)
_C_MESH = "#d9d9d9"    # maillage FEM (gris clair, < contraste que le trait)
_C_AXE = "#c0392b"     # axes Z/Y + glyphe G (rouge brique assagi, ex #FF0000)
_C_Y = "#1f4e79"       # fleche Y + glyphe P (bleu ardoise assagi, ex #0040FF)
_C_C = "#2e7d32"       # glyphe C (vert foret assagi, ex #008000)


def _f(v: float) -> str:
    """Format court d'une coordonnee SVG (mm), 3 decimales."""
    return f"{v:.3f}"


def _mesh_svg(mv: List[Tuple[float, float]],
              mt: List[Tuple[int, int, int]],
              w2s) -> str:
    """Bloc ``<g>`` UNIQUE du maillage FEM (voile gris discret).

    Tous les triangles partagent un seul style porte par le ``<g>``
    (fill='none', stroke=_C_MESH, stroke-width 0.08) : a l'interieur seules les
    geometries ``<polygon>`` nues, sans repeter le style. Trois benefices : le
    fichier reste leger, l'impression PDF applique un style coherent au calque
    entier, et le maillage devient un VOILE de texture grise homogene plutot
    qu'un dessin qui CRIE le maillage.

    ``mv`` : sommets ``[(x, y), ...]`` ; ``mt`` : triangles ``[(i, j, k), ...]``
    en indices de sommets. ``w2s`` : conversion monde (mm) -> papier (mm).
    """
    nv = len(mv)
    polys: List[str] = []
    for tri in mt:
        i, j, k = tri[0], tri[1], tri[2]
        if i >= nv or j >= nv or k >= nv:
            continue
        ax, ay = w2s(mv[i][0], mv[i][1])
        bx, by = w2s(mv[j][0], mv[j][1])
        cx, cy = w2s(mv[k][0], mv[k][1])
        polys.append(
            f'<polygon points="{_f(ax)},{_f(ay)} '
            f'{_f(bx)},{_f(by)} {_f(cx)},{_f(cy)}"/>'
        )
    if not polys:
        return ""
    return (
        f'<g fill="none" stroke="{_C_MESH}" stroke-width="0.08">'
        + "".join(polys)
        + "</g>"
    )


def section_to_fiche_svg(outer_polygons: List[List[Tuple[float, float]]],
                         hole_polygons: List[List[Tuple[float, float]]],
                         results,
                         svg_w_mm: float,
                         svg_h_mm: float,
                         draw_shear_center: bool = True,
                         show_mesh: bool = False,
                         show_fill: bool = True) -> Tuple[str, float]:
    """Dessin vectoriel epure de la section pour la fiche.

    Retourne ``(svg_str, echelle_X)`` ou ``echelle_X`` est le rapport entre la
    plus grande dimension reelle de la section (mm) et sa taille dessinee sur le
    papier (mm) : il sert a annoter « Echelle 1 / X ».

    Le SVG est dimensionne en MILLIMETRES PHYSIQUES (attributs width/height en
    'mm', viewBox en mm) : a 100 %, l'echelle imprimee est donc reelle.

    Rendu en CALQUES, du bas vers le haut (ordre des ``append``) :
      (a) REMPLISSAGE matiere si ``show_fill`` : chaque contour exterieur en
          ``fill=_C_FILL`` (gris tres clair) ``stroke=none``, puis chaque trou
          ``fill=#ffffff`` (re-blanchiment) par-dessus -> gere les trous sans
          dependre du support de ``fill-rule`` du moteur de rendu/impression ;
      (b) MAILLAGE si ``show_mesh`` ET ``results`` expose mesh_vertices +
          mesh_triangles non vides : voile gris ``_C_MESH`` en un seul ``<g>`` ;
      (c) TRACE FILAIRE de la section (contours + trous), ``stroke=_C_TRAIT`` ;
      (d) AXES ``_C_AXE`` centres en G (fleche Y ``_C_Y``) ;
      (e) GLYPHES P (``_C_Y``) / G (``_C_AXE``) / C (``_C_C``) par-dessus tout.
    Le maillage est donc DESSOUS le trace noir et les axes/glyphes.

    ``draw_shear_center`` : si ``False`` (cas FEM-invalide, region disjointe ou
    warping echoue), le centre de cisaillement n'est PAS calcule -> on ne
    dessine NI le glyphe C NI son extension de la boite englobante, pour ne pas
    presenter une position non calculee comme physique.

    ``show_mesh`` / ``show_fill`` : interrupteurs des nouvelles capacites. Le
    maillage n'a d'effet que si ``results`` porte un maillage non vide (FEM).
    """
    hole_polygons = hole_polygons or []

    # ---- Boite englobante de la geometrie (mm, repere monde) ----
    all_x: List[float] = []
    all_y: List[float] = []
    for poly in outer_polygons + hole_polygons:
        for (x, y) in poly:
            all_x.append(x)
            all_y.append(y)

    if not all_x:
        svg = (
            f'<svg width="{_f(svg_w_mm)}mm" height="{_f(svg_h_mm)}mm" '
            f'viewBox="0 0 {_f(svg_w_mm)} {_f(svg_h_mm)}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{_f(svg_w_mm / 2)}" y="{_f(svg_h_mm / 2)}" '
            f'text-anchor="middle" fill="#999" font-size="4" '
            f'font-family="monospace">Aucune geometrie</text></svg>'
        )
        return svg, 1.0

    xmin_w = min(all_x)
    xmax_w = max(all_x)
    ymin_w = min(all_y)
    ymax_w = max(all_y)
    width_mm = max(xmax_w - xmin_w, 1e-9)
    height_mm = max(ymax_w - ymin_w, 1e-9)

    # Points remarquables doivent rester visibles : on etend la boite englobante
    # pour englober l'origine (0,0), G et C s'ils sortent de la section.
    xc = getattr(results, "xc", 0.0)
    yc = getattr(results, "yc", 0.0)
    xsc = getattr(results, "xsc", 0.0)
    ysc = getattr(results, "ysc", 0.0)
    pts_remarquables = [(0.0, 0.0), (xc, yc)]
    if draw_shear_center:
        pts_remarquables.append((xsc, ysc))
    for (px, py) in pts_remarquables:
        xmin_w = min(xmin_w, px)
        xmax_w = max(xmax_w, px)
        ymin_w = min(ymin_w, py)
        ymax_w = max(ymax_w, py)
    ext_w = max(xmax_w - xmin_w, 1e-9)
    ext_h = max(ymax_w - ymin_w, 1e-9)

    # ---- Facteur d'ajustement (mm papier / mm reel) dans le cadre ----
    draw_w = svg_w_mm - 2.0 * _FICHE_SVG_MARGIN_MM
    draw_h = svg_h_mm - 2.0 * _FICHE_SVG_MARGIN_MM
    fit = min(draw_w / ext_w, draw_h / ext_h)   # mm dessine / mm reel

    # Centrage du dessin dans le cadre.
    drawn_w = ext_w * fit
    drawn_h = ext_h * fit
    off_x = (svg_w_mm - drawn_w) / 2.0
    off_y = (svg_h_mm - drawn_h) / 2.0

    def w2s(x: float, y: float) -> Tuple[float, float]:
        """Monde (mm) -> papier (mm). y inverse (SVG vers le bas)."""
        sx = off_x + (x - xmin_w) * fit
        sy = off_y + (ymax_w - y) * fit   # y inverse vers le bas
        return sx, sy

    lines: List[str] = []
    lines.append(
        f'<svg width="{_f(svg_w_mm)}mm" height="{_f(svg_h_mm)}mm" '
        f'viewBox="0 0 {_f(svg_w_mm)} {_f(svg_h_mm)}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#FFFFFF;">'
    )

    def poly_points_str(pts: List[Tuple[float, float]]) -> str:
        parts = []
        for (x, y) in pts:
            sx, sy = w2s(x, y)
            parts.append(f"{_f(sx)},{_f(sy)}")
        return " ".join(parts)

    def _label(x: float, y: float, txt: str, couleur: str,
               taille: float = 3.0, anchor: Optional[str] = None) -> str:
        """Emet un ``<text>`` avec HALO BLANC pour lisibilite par-dessus le
        maillage et le trace.

        Technique SVG ``paint-order="stroke"`` : le contour blanc (stroke
        ``#ffffff``, epais) est peint SOUS le remplissage de la lettre, ce qui
        forme un halo lisible sans masquer le glyphe. ``stroke-linejoin=round``
        adoucit les angles du halo. ``anchor`` (``start``/``middle``/``end``)
        est optionnel : utile pour ancrer une etiquette a sa fin (offset gauche).
        """
        anchor_attr = f' text-anchor="{anchor}"' if anchor else ""
        return (
            f'<text x="{_f(x)}" y="{_f(y)}" font-size="{_f(taille)}" '
            f'fill="{couleur}" font-family="monospace"{anchor_attr} '
            f'paint-order="stroke" stroke="#ffffff" stroke-width="0.7" '
            f'stroke-linejoin="round">{txt}</text>'
        )

    # ---- (a) REMPLISSAGE matiere (gris tres clair, trous re-blanchis) ----
    # Calque le PLUS BAS : la matiere d'abord, puis les trous en blanc par-
    # dessus. Le re-blanchiment des trous ne depend pas du support de
    # ``fill-rule`` du moteur de rendu/impression (technique la plus robuste).
    if show_fill:
        for poly in outer_polygons:
            if len(poly) < 3:
                continue
            lines.append(
                f'<polygon points="{poly_points_str(poly)}" '
                f'fill="{_C_FILL}" stroke="none"/>'
            )
        for poly in hole_polygons:
            if len(poly) < 3:
                continue
            lines.append(
                f'<polygon points="{poly_points_str(poly)}" '
                f'fill="#ffffff" stroke="none"/>'
            )

    # ---- (b) MAILLAGE FEM (voile gris discret), DESSOUS le trace noir ----
    # N'a d'effet qu'en presence d'un maillage non vide (moteur FEM).
    if show_mesh:
        mv = getattr(results, "mesh_vertices", None)
        mt = getattr(results, "mesh_triangles", None)
        if mv and mt:
            mesh_block = _mesh_svg(mv, mt, w2s)
            if mesh_block:
                lines.append(mesh_block)

    # ---- (c) Trace filaire de la section (contours + trous), PAR-DESSUS ----
    for poly in outer_polygons:
        if len(poly) < 3:
            continue
        lines.append(
            f'<polygon points="{poly_points_str(poly)}" '
            f'fill="none" stroke="{_C_TRAIT}" stroke-width="0.3" '
            f'stroke-linejoin="round"/>'
        )
    for poly in hole_polygons:
        if len(poly) < 3:
            continue
        lines.append(
            f'<polygon points="{poly_points_str(poly)}" '
            f'fill="none" stroke="{_C_TRAIT}" stroke-width="0.3" '
            f'stroke-linejoin="round"/>'
        )

    # ---- (d) Axes Eurocode centres en G : y horizontal (axe fort), z vertical
    # (axe faible). Les axes COUVRENT tout le cadre (bord a bord) en passant par
    # G, et les fleches + etiquettes restent A L'INTERIEUR du cadre : ainsi les
    # axes ne sont JAMAIS tronques, quelle que soit la position de G dans le
    # dessin (correctif : auparavant un bras de longueur fixe depassait le cadre
    # quand G etait excentre).
    gsx, gsy = w2s(xc, yc)
    inset = _FICHE_SVG_MARGIN_MM * 0.6   # marge reservee aux pointes/etiquettes
    x_left, x_right = inset, svg_w_mm - inset
    y_top, y_bot = inset, svg_h_mm - inset
    # Borne G dans le cadre par securite (sections degenerees) ; en pratique le
    # centrage place deja G a l'interieur.
    gsx = min(max(gsx, x_left), x_right)
    gsy = min(max(gsy, y_top), y_bot)
    ah = 2.6   # taille des fleches (mm)

    # Axe y (horizontal) : ligne rouge brique bord a bord, fleche a DROITE (+y).
    lines.append(
        f'<line x1="{_f(x_left)}" y1="{_f(gsy)}" '
        f'x2="{_f(x_right)}" y2="{_f(gsy)}" '
        f'stroke="{_C_AXE}" stroke-width="0.3"/>'
    )
    lines.append(
        f'<polygon points="'
        f'{_f(x_right)},{_f(gsy)} '
        f'{_f(x_right - ah)},{_f(gsy - ah * 0.55)} '
        f'{_f(x_right - ah)},{_f(gsy + ah * 0.55)}" '
        f'fill="{_C_AXE}" stroke="{_C_AXE}" stroke-width="0.2"/>'
    )

    # Axe z (vertical) : ligne rouge brique bord a bord, fleche en HAUT (+z).
    lines.append(
        f'<line x1="{_f(gsx)}" y1="{_f(y_bot)}" '
        f'x2="{_f(gsx)}" y2="{_f(y_top)}" '
        f'stroke="{_C_AXE}" stroke-width="0.3"/>'
    )
    # Fleche z ROUGE (et non bleue) : seul le glyphe P reste un triangle BLEU, ce
    # qui evite de voir « deux fois » le triangle du point de reference.
    lines.append(
        f'<polygon points="'
        f'{_f(gsx)},{_f(y_top)} '
        f'{_f(gsx - ah * 0.55)},{_f(y_top + ah)} '
        f'{_f(gsx + ah * 0.55)},{_f(y_top + ah)}" '
        f'fill="{_C_AXE}" stroke="{_C_AXE}" stroke-width="0.2"/>'
    )

    # Etiquettes d'axes (halo blanc), A L'INTERIEUR du cadre et en ROUGE
    # (coherent avec les axes). y pres de la pointe droite (ancre fin), z sous la
    # pointe haute. Emises avec les glyphes pour que tous les halos soient APRES
    # les traits.
    axis_labels = [
        _label(x_right - ah - 0.6, gsy - 1.4, "y", _C_AXE, taille=3.2, anchor="end"),
        _label(gsx + 1.6, y_top + ah + 1.6, "z", _C_AXE, taille=3.2),
    ]

    # ---- (e) Glyphes P / G / C (par-dessus tout) ----
    # Detection C confondu avec G (distance papier < seuil) : on n'emet alors
    # PAS le glyphe C redondant (la legende HTML porte la mention « C confondu
    # avec G », via la meme detection factorisee).
    psx, psy = w2s(0.0, 0.0)
    csx, csy = w2s(xsc, ysc)
    c_confondu = draw_shear_center and (
        math.hypot(csx - gsx, csy - gsy) < _C_CONFONDU_SEUIL_MM
    )

    # GEOMETRIES des glyphes d'abord (triangle P, cercle G, carre C), puis TOUS
    # les labels avec halo APRES, pour que les halos blancs ne soient pas
    # recouverts par un glyphe voisin.
    glyph_labels: List[str] = []

    # P : triangle BLEU ardoise a l'origine du dessin (0,0).
    gp = 1.7
    lines.append(
        f'<polygon points="'
        f'{_f(psx)},{_f(psy - gp)} '
        f'{_f(psx - gp)},{_f(psy + gp)} '
        f'{_f(psx + gp)},{_f(psy + gp)}" '
        f'fill="{_C_Y}" stroke="{_C_Y}" stroke-width="0.2"/>'
    )
    # Label P en BAS-GAUCHE (ancre fin de texte). FAN-OUT : si P et G sont tres
    # proches (< 4 mm papier), accentuer le decalage vers le bas pour separer
    # nettement les deux labels.
    p_dy = gp + 3.2 if math.hypot(psx - gsx, psy - gsy) < 4.0 else gp + 1.0
    glyph_labels.append(
        _label(psx - gp - 0.6, psy + p_dy, "P", _C_Y, anchor="end")
    )

    # G : cercle ROUGE brique au centroide (meme rouge que les axes).
    lines.append(
        f'<circle cx="{_f(gsx)}" cy="{_f(gsy)}" r="1.6" '
        f'fill="none" stroke="{_C_AXE}" stroke-width="0.35"/>'
    )
    # Label G en HAUT-DROITE (direction distincte de P et de C).
    glyph_labels.append(_label(gsx + 2.0, gsy - 1.6, "G", _C_AXE))

    # C : carre VERT foret au centre de cisaillement. Dessine UNIQUEMENT si le
    # centre de cisaillement est calcule (draw_shear_center) ET non confondu
    # avec G (sinon on omet le glyphe redondant). Label en BAS-DROITE.
    if draw_shear_center and not c_confondu:
        gc = 1.5
        lines.append(
            f'<rect x="{_f(csx - gc)}" y="{_f(csy - gc)}" '
            f'width="{_f(2 * gc)}" height="{_f(2 * gc)}" '
            f'fill="none" stroke="{_C_C}" stroke-width="0.35"/>'
        )
        glyph_labels.append(_label(csx + gc + 0.6, csy + gc + 2.0, "C", _C_C))

    # Tous les labels (axes + glyphes) APRES les geometries -> halos non couverts.
    lines.extend(axis_labels)
    lines.extend(glyph_labels)

    lines.append("</svg>")

    # ---- Echelle 1 / X : plus grande dimension REELLE / sa taille DESSINEE ----
    # On se base sur la section seule (width_mm/height_mm), pas sur la boite
    # etendue aux points remarquables.
    max_real = max(width_mm, height_mm)
    max_drawn = max_real * fit
    echelle_x = max_real / max_drawn if max_drawn > 1e-9 else 1.0  # == 1/fit

    return "\n".join(lines), echelle_x


# ---------------------------------------------------------------------------
# CSS de la fiche (A4 paysage, monospace, cadre noir fin)
# ---------------------------------------------------------------------------

_FICHE_CSS = """
@page {
    size: A4 landscape;
    margin: 8mm;
}
* { box-sizing: border-box; }
html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #000000;
    font-family: 'Courier New', 'Lucida Console', monospace;
    font-size: 10pt;
}
.fiche-page {
    width: 281mm;
    min-height: 194mm;
    margin: 0 auto;
    padding: 4mm 5mm;
    border: 0.5pt solid #000000;
    display: flex;
    flex-direction: column;
}
.cartouche {
    border-bottom: 0.5pt solid #000000;
    padding-bottom: 2mm;
    margin-bottom: 2mm;
}
.cartouche .l1 { font-weight: bold; font-size: 11pt; }
.cartouche .l2 { font-size: 10pt; }
.cartouche .l3 { font-weight: bold; font-size: 11pt; margin-top: 1mm; }
.fiche-body {
    display: flex;
    flex-direction: row;
    flex: 1 1 auto;
    gap: 4mm;
}
.col-gauche { width: 45%; }
.col-droite {
    width: 55%;
    display: flex;
    align-items: center;
    justify-content: center;
}
table.tbl {
    width: 100%;
    border-collapse: collapse;
    font-family: 'Courier New', 'Lucida Console', monospace;
    font-size: 9.5pt;
}
table.tbl th, table.tbl td {
    border: 0.5pt solid #000000;
    padding: 1px 4px;
    text-align: right;
    white-space: nowrap;
}
table.tbl th {
    text-align: center;
    font-weight: bold;
    background: #ffffff;
}
table.tbl td.lbl { text-align: left; }
table.tbl td.center { text-align: center; }
table.tbl td.full { text-align: center; }
.glyph-p { color: #1f4e79; font-weight: bold; }
.glyph-g { color: #c0392b; font-weight: bold; }
.glyph-c { color: #2e7d32; font-weight: bold; }
.svg-wrap { width: 100%; text-align: center; }
.svg-legend { font-size: 8pt; color: #555555; margin-top: 1mm; text-align: center; }
.fiche-footer {
    border-top: 0.5pt solid #000000;
    padding-top: 1.5mm;
    margin-top: 2mm;
    display: flex;
    justify-content: space-between;
    font-size: 9.5pt;
}
.note {
    font-size: 8.5pt;
    margin-top: 1mm;
}
.print-btn {
    position: fixed;
    top: 8px;
    right: 12px;
    background: #000000;
    color: #ffffff;
    border: none;
    padding: 6px 14px;
    cursor: pointer;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    z-index: 100;
}
@media print {
    .print-btn { display: none; }
    .fiche-page { margin: 0; border: 0.5pt solid #000000; }
}
"""


# ---------------------------------------------------------------------------
# Generateur principal
# ---------------------------------------------------------------------------

def generate_fiche_html(options: FicheOptions,
                        outer_polygons: List[List[Tuple[float, float]]],
                        hole_polygons: List[List[Tuple[float, float]]],
                        results,
                        results_dict: Optional[dict] = None) -> str:
    """Construit la fiche HTML autonome (A4 paysage, CSS + SVG inline).

    ``results_dict`` est ACCEPTE pour symetrie d'API avec ``generate_html_report``
    mais N'EST PAS utilise : la fiche relit les attributs bruts (mm) de
    ``results`` via ``getattr`` puis convertit en unites SI.
    """
    hole_polygons = hole_polygons or []

    # ---- Lecture des attributs bruts (mm) ; gere analytique ET FEM ----
    area = getattr(results, "area", 0.0)
    xc = getattr(results, "xc", 0.0)
    yc = getattr(results, "yc", 0.0)
    Ix = getattr(results, "Ix", 0.0)
    Iy = getattr(results, "Iy", 0.0)
    Ixy = getattr(results, "Ixy", 0.0)
    theta_p = getattr(results, "theta_p", 0.0)
    xsc = getattr(results, "xsc", 0.0)
    ysc = getattr(results, "ysc", 0.0)
    I1 = getattr(results, "I1", 0.0)
    I2 = getattr(results, "I2", 0.0)
    J = getattr(results, "J", 0.0)
    Cw = getattr(results, "Cw", 0.0)
    xmin = getattr(results, "xmin", 0.0)
    xmax = getattr(results, "xmax", 0.0)
    ymin = getattr(results, "ymin", 0.0)
    ymax = getattr(results, "ymax", 0.0)
    A_sx = getattr(results, "A_sx", None)
    A_sy = getattr(results, "A_sy", None)
    # warping_valid : False si l'analyse de gauchissement a echoue (region
    # disjointe). Dans ce cas le moteur FEM laisse A_sx/A_sy/J/Cw/xsc/ysc a
    # leur valeur PAR DEFAUT (0.0) : ce ne sont PAS des valeurs physiques mais
    # des grandeurs NON CALCULEES qu'il ne faut pas afficher comme des zeros.
    _warping_valid = getattr(results, "warping_valid", False)

    # Mode analytique : pas d'aires de cisaillement (attribut A_sx absent ->
    # None). En analytique, J est calcule par FDM (toujours valide) et Cw=0.
    is_analytique = A_sx is None

    # Disponibilite des grandeurs de gauchissement (FEM uniquement) : on ne
    # les affiche que si le warping a reussi. Cf. fea_results_to_dict de
    # sp_backend qui OMET les aires de cisaillement et affiche I_t/I_w='n/d'
    # quand ``not warping_valid``.
    has_warping = (not is_analytique) and _warping_valid

    # Disponibilite du centre de cisaillement C : il est exploitable en
    # analytique (xsc/ysc calcules, exacts pour I/U/L/T) et en FEM si le
    # warping a reussi. En FEM-invalide, sp_backend laisse xsc/ysc au centroide
    # (valeurs NON calculees) : on n'affiche alors NI le glyphe C NI sa ligne
    # de coordonnees pour ne pas le presenter comme calcule.
    has_shear_center = is_analytique or _warping_valid

    # Unite SI affichee a cote de chaque VALEUR non vide (cellule vide -> reste
    # vide). Placee dans la cellule de valeur (pas le libelle) pour repondre a
    # « on ignore les unites » sans alourdir la colonne Repere : longueurs en m,
    # aires en m2, inerties en m4, gauchissement I_w en m6, angle en degres.
    def _with_unit(value_str: str, unit: str) -> str:
        return f"{value_str}&nbsp;{unit}" if value_str else ""

    # ---- Colonne Initial (repere geometrique y-z, inerties centroidales) ----
    # Convention Eurocode (cf. calculators.nomenclature) : x_dessin -> y_Eurocode
    # (axe fort horizontal), y_dessin -> z_Eurocode (axe faible vertical). Donc
    # I_y = ∫y_dessin² dA = results.Ix et I_z = results.Iy.
    iy_init = _with_unit(_fmt_sci(_mm4_to_m4(Ix)), "m⁴")    # I_y  <- results.Ix
    iz_init = _with_unit(_fmt_sci(_mm4_to_m4(Iy)), "m⁴")    # I_z  <- results.Iy
    iyz_init = _with_unit(_fmt_sci(_mm4_to_m4(Ixy)), "m⁴")  # I_yz <- results.Ixy

    # ---- Colonne Principal ----
    # I_1/I_2 sont DEJA calcules par le moteur (SectionResults.I1/I2) : on les
    # lit directement plutot que de re-deriver Mohr.
    i1_pr = _with_unit(_fmt_sci(_mm4_to_m4(I1)), "m⁴")    # I_1 (max) <- results.I1
    i2_pr = _with_unit(_fmt_sci(_mm4_to_m4(I2)), "m⁴")    # I_2 (min) <- results.I2
    # I_yz principal = 0 par definition -> case Principal VIDE.

    # Angle alpha des axes principaux : normalisation du zero signe (theta_p vaut
    # souvent -0.0 pour un rectangle) via ``+ 0.0`` -> "0.0 deg" et non "-0.0 deg".
    angle_str = f"{theta_p + 0.0:.1f} deg"

    # Aires de cisaillement A_vy/A_vz (colonne Principal, FEM uniquement). On les
    # gate sur ``has_warping`` : en analytique (pas de A_sx) ET en FEM-invalide
    # (warping_valid=False, A_sx/A_sy restes a 0.0 non calcules) on laisse
    # VIDE plutot que d'afficher un faux 0.00000E+00.
    if not has_warping:
        avy = ""
        avz = ""
    else:
        avy = _with_unit(_fmt_sci(_mm2_to_m2(A_sx)), "m²")  # A_vy <- results.A_sx
        avz = _with_unit(_fmt_sci(_mm2_to_m2(A_sy)), "m²")  # A_vz <- results.A_sy

    # ---- Coordonnees des points remarquables P / G / C ----
    # Initial : coordonnee geometrique (Z=x, Y=y) en m.
    def init_coord(px: float, py: float) -> Tuple[str, str]:
        return _fmt_fixed(_mm_to_m(px)), _fmt_fixed(_mm_to_m(py))

    # Principal : rotation -theta_p autour de G, en m.
    def princ_coord(px: float, py: float) -> Tuple[str, str]:
        z_pr, y_pr = _principal_coords(px, py, xc, yc, theta_p)
        return _fmt_fixed(_mm_to_m(z_pr)), _fmt_fixed(_mm_to_m(y_pr))

    p_zi, p_yi = init_coord(0.0, 0.0)
    p_zp, p_yp = princ_coord(0.0, 0.0)
    g_zi, g_yi = init_coord(xc, yc)
    g_zp, g_yp = princ_coord(xc, yc)        # == (0.000, 0.000)
    if has_shear_center:
        c_zi, c_yi = init_coord(xsc, ysc)
        c_zp, c_yp = princ_coord(xsc, ysc)
    else:
        # FEM-invalide : C non calcule -> cellules vides.
        c_zi = c_yi = c_zp = c_yp = ""

    # ---- Lignes pleine largeur ----
    # I_t = J. En analytique J est toujours calcule (FDM) donc valide ; en
    # FEM J n'est calcule que si le warping a reussi (sinon J reste a 0.0 non
    # calcule -> on vide la cellule plutot que d'afficher un faux 0).
    if is_analytique or _warping_valid:
        it_val = _with_unit(_fmt_sci(_mm4_to_m4(J)), "m⁴")   # I_t
    else:
        it_val = ""
    # I_w = Cw : vide en analytique (Cw=0 non calcule) et en FEM-invalide.
    if has_warping and Cw != 0:
        iw_val = _with_unit(_fmt_sci(_mm6_to_m6(Cw)), "m⁶")  # I_w
    else:
        iw_val = ""
    a_val = _with_unit(_fmt_sci(_mm2_to_m2(area)), "m²")     # A (aire)

    # ---- SVG (dimensionne en mm physiques) + echelle ----
    # On propage show_mesh/show_fill ; le maillage n'a d'effet que si results
    # expose un maillage non vide (FEM). La logique de gating warping est
    # inchangee (A_vy/A_vz/I_t/I_w/C).
    svg_str, echelle_x = section_to_fiche_svg(
        outer_polygons, hole_polygons, results,
        _FICHE_SVG_W_MM, _FICHE_SVG_H_MM,
        draw_shear_center=has_shear_center,
        show_mesh=options.show_mesh,
        show_fill=options.show_fill,
    )

    # Detection C confondu avec G (meme logique factorisee que le SVG) pour la
    # legende sous le dessin : aucune divergence possible.
    c_confondu = _c_confondu_avec_g(
        results, outer_polygons, hole_polygons,
        _FICHE_SVG_W_MM, _FICHE_SVG_H_MM,
        draw_shear_center=has_shear_center,
    )

    # ---- Pied de page : Dy / Dz (m) + Echelle 1 / X ----
    # Convention Eurocode : Dy = etendue HORIZONTALE (xmax-xmin), Dz = etendue
    # VERTICALE (ymax-ymin), coherent avec les axes y(horizontal)/z(vertical).
    dy_ext = _fmt_fixed(_mm_to_m(xmax - xmin))
    dz_ext = _fmt_fixed(_mm_to_m(ymax - ymin))
    echelle_str = f"Echelle 1 / {echelle_x:.2f}"

    # ---- Cartouche : 3 lignes ----
    l1 = _esc(options.titre_module)
    # L2 combine numero / designation / type_piece (separes par " - ").
    l2_parts = [p for p in (options.numero, options.designation, options.type_piece)
                if p and p.strip()]
    l2 = _esc("  -  ".join(l2_parts)) if l2_parts else "&nbsp;"
    l3 = _esc(options.titre_fiche)

    report_date = date.today().strftime("%d/%m/%Y")

    # ---- Construction du tableau colonne gauche ----
    # Les libelles de ligne proviennent EXCLUSIVEMENT des cles de
    # calculators.nomenclature.PROPERTY_DESCRIPTIONS (source unique de verite des
    # symboles Eurocode), avec leur description en info-bulle (title=...).
    def _lbl(sym: str) -> str:
        """Cellule de libelle d'une ligne : symbole Eurocode + info-bulle."""
        desc = PROPERTY_DESCRIPTIONS.get(sym, "")
        title = f' title="{_esc(desc)}"' if desc else ""
        return f'<td class="lbl"{title}>{_esc(sym)}</td>'

    tbl: List[str] = []
    tbl.append('<table class="tbl">')
    # Entete Repere | Initial | Principal
    tbl.append(
        '<tr><th>Repere</th><th>Initial</th><th>Principal</th></tr>'
    )
    # alpha : angle des axes principaux (Principal seulement, Initial vide).
    tbl.append(
        f'<tr>{_lbl("α")}'
        f'<td></td><td>{_esc(angle_str)}</td></tr>'
    )
    # I_y / I_z / I_yz (repere centroidal y-z) en colonne Initial.
    tbl.append(
        f'<tr>{_lbl("I_y")}'
        f'<td>{iy_init}</td><td></td></tr>'
    )
    tbl.append(
        f'<tr>{_lbl("I_z")}'
        f'<td>{iz_init}</td><td></td></tr>'
    )
    # I_yz : Initial seulement (Principal vide car nul par definition).
    tbl.append(
        f'<tr>{_lbl("I_yz")}'
        f'<td>{iyz_init}</td><td></td></tr>'
    )
    # I_1 / I_2 : inerties principales (colonne Principal, lignes propres).
    tbl.append(
        f'<tr>{_lbl("I_1")}'
        f'<td></td><td>{i1_pr}</td></tr>'
    )
    tbl.append(
        f'<tr>{_lbl("I_2")}'
        f'<td></td><td>{i2_pr}</td></tr>'
    )
    # A_vy / A_vz : aires de cisaillement (Principal seulement, vide en analytique).
    tbl.append(
        f'<tr>{_lbl("A_vy")}'
        f'<td></td><td>{avy}</td></tr>'
    )
    tbl.append(
        f'<tr>{_lbl("A_vz")}'
        f'<td></td><td>{avz}</td></tr>'
    )
    # Sous-bloc coordonnees : entete "y  z" (axe horizontal puis vertical) sous
    # chaque colonne. L'ordre des deux nombres par cellule est (y puis z) =
    # (composante horizontale x_dessin puis verticale y_dessin) -> inchange.
    tbl.append(
        '<tr><th></th>'
        '<th>y&nbsp;&nbsp;&nbsp;z&nbsp;(m)</th>'
        '<th>y&nbsp;&nbsp;&nbsp;z&nbsp;(m)</th></tr>'
    )
    tbl.append(
        f'<tr><td class="lbl" title="P = point de reference">'
        f'<span class="glyph-p">&#9650;</span> P</td>'
        f'<td>{p_zi}&nbsp;&nbsp;{p_yi}</td>'
        f'<td>{p_zp}&nbsp;&nbsp;{p_yp}</td></tr>'
    )
    tbl.append(
        f'<tr><td class="lbl" title="G = centre de gravite">'
        f'<span class="glyph-g">&#9679;</span> G</td>'
        f'<td>{g_zi}&nbsp;&nbsp;{g_yi}</td>'
        f'<td>{g_zp}&nbsp;&nbsp;{g_yp}</td></tr>'
    )
    tbl.append(
        f'<tr><td class="lbl" title="C = centre de cisaillement">'
        f'<span class="glyph-c">&#9632;</span> C</td>'
        f'<td>{c_zi}&nbsp;&nbsp;{c_yi}</td>'
        f'<td>{c_zp}&nbsp;&nbsp;{c_yp}</td></tr>'
    )
    # Lignes pleine largeur (une valeur centree sur 2 colonnes).
    tbl.append(
        f'<tr>{_lbl("I_t")}'
        f'<td class="full" colspan="2">{it_val}</td></tr>'
    )
    tbl.append(
        f'<tr>{_lbl("I_w")}'
        f'<td class="full" colspan="2">{iw_val}</td></tr>'
    )
    # La ligne A (=aire) suit directement I_w : KY/KZ ont ete retires
    # (grandeurs non calculees par SectionCAD ; une fiche ne doit contenir que
    # des chiffres dans lesquels on a confiance).
    tbl.append(
        f'<tr>{_lbl("A")}'
        f'<td class="full" colspan="2">{a_val}</td></tr>'
    )
    tbl.append('</table>')

    engine_note = ''
    if options.engine_label:
        engine_note = (f'<div class="note">Moteur : '
                       f'{_esc(options.engine_label)}</div>')

    # Note FEM-invalide : warping echoue / region disjointe -> I_t, I_w, le centre
    # de cisaillement C et les aires de cisaillement A_vy/A_vz ne sont PAS
    # calcules (cf. fea_results_to_dict de sp_backend qui affiche I_t/I_w='n/d').
    warping_note = ''
    if (not is_analytique) and (not _warping_valid):
        warping_note = (
            '<div class="note">'
            'Note : l\'analyse de gauchissement a echoue (region disjointe) ; '
            'I_t, I_w, le centre de cisaillement C et les aires de cisaillement '
            'A_vy/A_vz ne sont pas calcules.'
            '</div>'
        )

    tbl_html = "\n".join(tbl)

    # Legende discrete sous le dessin (vocabulaire de l'application). Couleurs
    # strictement egales a celles des glyphes SVG/CSS. Si C est confondu avec G
    # (meme detection que le SVG), on n'affiche PAS le glyphe carre C (omis du
    # dessin) et on ajoute la mention « C confondu avec G ».
    legend_items = [
        '<span class="glyph-p">&#9650;</span> P = point de reference',
        '<span class="glyph-g">&#9679;</span> G = centre de gravite',
    ]
    if has_shear_center and not c_confondu:
        legend_items.append(
            '<span class="glyph-c">&#9632;</span> C = centre de cisaillement'
        )
    elif c_confondu:
        legend_items.append(
            '<span class="glyph-c">&#9632;</span> C confondu avec G'
        )
    svg_legend = (
        '<div class="svg-legend">'
        + '&nbsp;&nbsp;'.join(legend_items)
        + '</div>'
    )

    # ---- Assemblage du document ----
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{l3}</title>
  <style>
{_FICHE_CSS}
  </style>
</head>
<body>
<button class="print-btn" onclick="window.print()" title="Imprimer ou enregistrer en PDF">Imprimer / PDF</button>
<div class="fiche-page">
  <div class="cartouche">
    <div class="l1">{l1}</div>
    <div class="l2">{l2}</div>
    <div class="l3">{l3}</div>
  </div>
  <div class="fiche-body">
    <div class="col-gauche">
{tbl_html}
{warping_note}
{engine_note}
    </div>
    <div class="col-droite">
      <div class="svg-wrap">
{svg_str}
{svg_legend}
      </div>
    </div>
  </div>
  <div class="fiche-footer">
    <span>Dy=&nbsp;&nbsp;{dy_ext}&nbsp;m&nbsp;&nbsp;&nbsp;Dz=&nbsp;&nbsp;{dz_ext}&nbsp;m</span>
    <span>{_esc(echelle_str)}</span>
  </div>
</div>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# API publique d'export
# ---------------------------------------------------------------------------

def export_fiche(options: FicheOptions,
                 outer_polygons: List[List[Tuple[float, float]]],
                 hole_polygons: List[List[Tuple[float, float]]],
                 results,
                 filepath: str) -> None:
    """Genere la fiche et l'ecrit dans ``filepath`` (UTF-8).

    Comportement identique a ``export_report`` : pas de moteur PDF, simple
    ecriture du HTML autonome.
    """
    html = generate_fiche_html(
        options, outer_polygons, hole_polygons, results
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

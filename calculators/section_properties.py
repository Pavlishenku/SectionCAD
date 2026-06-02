"""
Section properties calculator for arbitrary polygonal sections.
Supports composite sections (multiple polygons with holes).
All geometric inputs in mm, outputs in standard civil engineering units.
"""
import math
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from calculators.torsion_fdm import compute_J_fdm
from calculators.geometry_prep import normalize_polygons

_log = logging.getLogger(__name__)


@dataclass
class SectionResults:
    # Basic
    area: float = 0.0           # mm²
    # Centroid
    xc: float = 0.0             # mm
    yc: float = 0.0             # mm
    # Moments of inertia about centroidal axes
    Ix: float = 0.0             # mm⁴
    Iy: float = 0.0             # mm⁴
    Ixy: float = 0.0            # mm⁴
    # Principal moments
    I1: float = 0.0             # mm⁴ (max)
    I2: float = 0.0             # mm⁴ (min)
    theta_p: float = 0.0        # deg - angle of principal axes
    # Elastic section moduli
    Sx_top: float = 0.0         # mm³
    Sx_bot: float = 0.0         # mm³
    Sy_left: float = 0.0        # mm³
    Sy_right: float = 0.0       # mm³
    # Plastic section moduli (simplified - for solid sections)
    Zx: float = 0.0             # mm³
    Zy: float = 0.0             # mm³
    # Radii of gyration
    rx: float = 0.0             # mm
    ry: float = 0.0             # mm
    # Bounding box (in global coords)
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    # Shear center (approximate for open sections, = centroid for solid)
    xsc: float = 0.0            # mm
    ysc: float = 0.0            # mm
    # Torsion (approximate — isoperimetric / Bredt formula)
    J: float = 0.0              # mm⁴ — St-Venant torsional constant
    Cw: float = 0.0             # mm⁶ — warping constant (0 for general sections)


def _polygon_area_and_centroid(pts: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """Signed area and centroid of a single closed polygon (shoelace formula)."""
    n = len(pts)
    A = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        A += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    A *= 0.5
    if abs(A) < 1e-12:
        return A, 0.0, 0.0
    cx /= (6.0 * A)
    cy /= (6.0 * A)
    return A, cx, cy


def _polygon_inertia(pts: List[Tuple[float, float]], xc: float, yc: float) -> Tuple[float, float, float]:
    """Second moments of area of a polygon about point (xc, yc)."""
    n = len(pts)
    Ix = 0.0
    Iy = 0.0
    Ixy = 0.0
    for i in range(n):
        x0, y0 = pts[i][0] - xc, pts[i][1] - yc
        x1, y1 = pts[(i + 1) % n][0] - xc, pts[(i + 1) % n][1] - yc
        cross = x0 * y1 - x1 * y0
        Ix += (y0 * y0 + y0 * y1 + y1 * y1) * cross
        Iy += (x0 * x0 + x0 * x1 + x1 * x1) * cross
        Ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cross
    Ix /= 12.0
    Iy /= 12.0
    Ixy /= 24.0
    return Ix, Iy, Ixy


def _plastic_modulus_x(pts: List[Tuple[float, float]], xc: float, yc: float, area: float) -> float:
    """Plastic modulus Zx: first moment of area on each side of PNA (y = yc for symmetric)."""
    arr = np.array(pts)
    ymin = arr[:, 1].min()
    ymax = arr[:, 1].max()

    target = area / 2.0
    y_lo, y_hi = ymin, ymax
    for _ in range(50):
        y_mid = (y_lo + y_hi) / 2.0
        a_above = _area_above(pts, y_mid)
        if a_above > target:
            y_lo = y_mid
        else:
            y_hi = y_mid
    y_pna = (y_lo + y_hi) / 2.0

    Q_above = abs(_first_moment_above(pts, y_pna))
    Q_below = abs(_first_moment_below(pts, y_pna))
    return Q_above + Q_below


def _plastic_modulus_composite(
    outer_list: List[List[Tuple[float, float]]],
    hole_list: List[List[Tuple[float, float]]],
    xc: float, yc: float, total_area: float,
) -> float:
    """
    Plastic modulus Zx for composite sections (outers minus holes).
    Finds the PNA where net area above = net area below = total_area/2.
    """
    all_y = [p[1] for pts in outer_list for p in pts]
    if hole_list:
        all_y += [p[1] for pts in hole_list for p in pts]
    ymin, ymax = min(all_y), max(all_y)

    def _net_area_above(y_cut: float) -> float:
        a = sum(_area_above(pts, y_cut) for pts in outer_list)
        a -= sum(_area_above(pts, y_cut) for pts in hole_list)
        return a

    target = total_area / 2.0
    y_lo, y_hi = ymin, ymax
    for _ in range(60):
        y_mid = (y_lo + y_hi) / 2.0
        if _net_area_above(y_mid) > target:
            y_lo = y_mid
        else:
            y_hi = y_mid
    y_pna = (y_lo + y_hi) / 2.0

    Q_above = sum(_first_moment_above(pts, y_pna) for pts in outer_list)
    Q_above -= sum(_first_moment_above(pts, y_pna) for pts in hole_list)
    Q_below = sum(_first_moment_below(pts, y_pna) for pts in outer_list)
    Q_below -= sum(_first_moment_below(pts, y_pna) for pts in hole_list)
    return abs(Q_above) + abs(Q_below)


def _area_above(pts, y_cut):
    """Area of polygon above y = y_cut (approximate using shoelace on clipped polygon)."""
    clipped = _clip_polygon_above(pts, y_cut)
    if len(clipped) < 3:
        return 0.0
    a, _, _ = _polygon_area_and_centroid(clipped)
    return abs(a)


def _first_moment_above(pts, y_cut):
    """First moment of area about y_cut for region above y_cut."""
    clipped = _clip_polygon_above(pts, y_cut)
    if len(clipped) < 3:
        return 0.0
    a, cx, cy = _polygon_area_and_centroid(clipped)
    return abs(a) * (cy - y_cut)


def _first_moment_below(pts, y_cut):
    """First moment of area about y_cut for region below y_cut."""
    clipped = _clip_polygon_below(pts, y_cut)
    if len(clipped) < 3:
        return 0.0
    a, cx, cy = _polygon_area_and_centroid(clipped)
    return abs(a) * (y_cut - cy)


def _clip_polygon_above(pts, y_cut):
    """Sutherland-Hodgman clipping: keep parts above y >= y_cut."""
    output = []
    n = len(pts)
    for i in range(n):
        curr = pts[i]
        nxt = pts[(i + 1) % n]
        if curr[1] >= y_cut:
            output.append(curr)
            if nxt[1] < y_cut:
                dy = nxt[1] - curr[1]
                if abs(dy) < 1e-12:
                    continue
                t = (y_cut - curr[1]) / dy
                xi = curr[0] + t * (nxt[0] - curr[0])
                output.append((xi, y_cut))
        else:
            if nxt[1] >= y_cut:
                dy = nxt[1] - curr[1]
                if abs(dy) < 1e-12:
                    continue
                t = (y_cut - curr[1]) / dy
                xi = curr[0] + t * (nxt[0] - curr[0])
                output.append((xi, y_cut))
    return output


def _clip_polygon_below(pts, y_cut):
    """Keep parts below y <= y_cut."""
    output = []
    n = len(pts)
    for i in range(n):
        curr = pts[i]
        nxt = pts[(i + 1) % n]
        if curr[1] <= y_cut:
            output.append(curr)
            if nxt[1] > y_cut:
                dy = nxt[1] - curr[1]
                if abs(dy) < 1e-12:
                    continue
                t = (y_cut - curr[1]) / dy
                xi = curr[0] + t * (nxt[0] - curr[0])
                output.append((xi, y_cut))
        else:
            if nxt[1] <= y_cut:
                dy = nxt[1] - curr[1]
                if abs(dy) < 1e-12:
                    continue
                t = (y_cut - curr[1]) / dy
                xi = curr[0] + t * (nxt[0] - curr[0])
                output.append((xi, y_cut))
    return output


def _compute_shear_center_and_cw(
    metadata: dict,
    xc: float, yc: float,
    Ix: float, Iy: float, Ixy: float,
    outer_polygons=None,
) -> Tuple[float, float, float]:
    """
    Compute shear center (xsc, ysc) and warping constant Cw analytically.

    All coordinates and dimensions in mm. Cw in mm⁶.

    Returns
    -------
    (xsc, ysc, Cw)

    References
    ----------
    - Timoshenko & Gere, Theory of Elastic Stability, 2nd ed. (1961) — I-section Cw
    - Galambos, Guide to Stability Design Criteria for Metal Structures, 5th ed. (1998)
    - Pilkey, Analysis and Design of Elastic Beams, Wiley (2002)
    - EN 1993-1-1 (Eurocode 3) commentaries
    """
    if not metadata:
        return xc, yc, 0.0

    sec_type = metadata.get('type', '')

    # -----------------------------------------------------------------------
    # I-section doublement symétrique : IPE, HEA, HEB, section en I, croix
    # -----------------------------------------------------------------------
    if sec_type in ('i_section', 'cross'):
        h  = metadata.get('h', 0.0)
        tf = metadata.get('tf', 0.0)
        # xsc = xc, ysc = yc (double symétrie → SC = centroïde, exact)
        # Cw = Iy * h0² / 4  où h0 = distance entre centroïdes de semelles
        # Réf : Timoshenko & Gere eq. 6-30 ; Pilkey eq. 6.98
        h0 = h - tf  # distance âme-à-âme des centroïdes de semelles (= h - tf pour flanges égaux)
        Cw = Iy * h0 ** 2 / 4.0
        return xc, yc, Cw

    # -----------------------------------------------------------------------
    # Rectangle plein, cercle, CHS : SC = centroïde, Cw = 0
    # -----------------------------------------------------------------------
    if sec_type in ('rectangle', 'circle', 'chs'):
        return xc, yc, 0.0

    # -----------------------------------------------------------------------
    # Caisson / SHS / RHS (sections creuses fermées) : SC = centroïde, Cw ≈ 0
    # Réf : Pilkey (2002) — closed thin-walled sections have negligible Cw
    # -----------------------------------------------------------------------
    if sec_type == 'box':
        return xc, yc, 0.0

    # -----------------------------------------------------------------------
    # Channel / UPN — section en U ouverte
    # Réf : Timoshenko & Gere (1961) §5.4 ; Pilkey (2002) §6.6
    # -----------------------------------------------------------------------
    if sec_type == 'channel':
        h   = metadata.get('h', 0.0)   # hauteur totale
        b   = metadata.get('b', 0.0)   # largeur de semelle
        tw  = metadata.get('tw', 0.0)  # épaisseur d'âme
        tf  = metadata.get('tf', 0.0)  # épaisseur de semelle

        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return xc, yc, 0.0

        # Distance entre axes des semelles (ligne neutre des semelles)
        h_f = h - tf                          # distance entre axes des semelles

        # Longueur effective de semelle mesurée depuis l'axe de l'âme
        b_f = b - tw / 2.0                    # mm — semelle depuis axe âme jusqu'au bord libre

        # Excentricité e du centre de cisaillement depuis l'AXE de l'âme
        # Formule de Timoshenko (1961) §5.4 :
        #   e = (3 * b_f² * tf) / (h_f * tw + 6 * b_f * tf)
        denom = h_f * tw + 6.0 * b_f * tf
        if denom < 1e-12:
            return xc, yc, 0.0
        e = (3.0 * b_f ** 2 * tf) / denom

        # Position de l'axe de l'âme dans le repère centroïdal actuel.
        # channel_section() construit le canal avec l'âme depuis x=0 jusqu'à x=tw,
        # axe âme = tw/2, puis décale de xc_original (centroïde avant décalage).
        # Donc : x_axe_âme_centroïdal = tw/2 - xc_original.
        # Or après centrage : xc_centroïdal = 0 (par construction).
        # Reconstruction de xc_original depuis les polygones si dispo, sinon approximation.
        # Approximation directe : pour un canal classique, xc_original ≈ position du centroïde
        # avant centrage = paramètre non retourné par le générateur.
        # On recalcule xc_original analytiquement (centroïde exact du profil non centré) :
        #
        # Sections d'un canal (avant centrage) :
        #   Âme          : rect. (tw × (h - 2*tf)), centré sur x = tw/2
        #   Semelle inf  : rect. (b × tf), centré sur x = b/2
        #   Semelle sup  : rect. (b × tf), centré sur x = b/2
        A_web    = tw * (h - 2.0 * tf)
        A_flange = b  * tf
        A_total  = A_web + 2.0 * A_flange
        if A_total < 1e-12:
            return xc, yc, 0.0
        xc_orig = (A_web * (tw / 2.0) + 2.0 * A_flange * (b / 2.0)) / A_total

        # Position de l'axe de l'âme dans repère centroïdal (centroïde = 0)
        x_web_axis = tw / 2.0 - xc_orig

        # xsc = x_axe_âme - e  (le SC est du côté ouvert, c.-à-d. à gauche de l'âme pour
        # un canal ouvert vers la droite ; la channel_section() pointe vers la droite)
        xsc = x_web_axis - e
        ysc = yc   # symétrie horizontale (y identique au centroïde)

        # Cw pour canal (Galambos 1998, formule 3.34 simplifiée) :
        #   Cw = tf * b_f³ * h_f² / 12  ×  [1 − 3*b_f*tf / (h_f*tw/2 + 3*b_f*tf)]
        # Forme équivalente Pilkey (2002) §6.6 :
        #   Cw = (h_f² * tf * b_f³) / 12 × (2 / (1 + (h_f*tw)/(6*b_f*tf)))
        # On utilise la forme Galambos :
        denom2 = h_f * tw / 2.0 + 3.0 * b_f * tf
        if denom2 < 1e-12:
            Cw = 0.0
        else:
            Cw = (tf * b_f ** 3 * h_f ** 2 / 12.0) * (1.0 - 3.0 * b_f * tf / denom2)
        return xsc, ysc, max(Cw, 0.0)

    # -----------------------------------------------------------------------
    # Cornière à ailes égales (angle_section) — SC au coin intérieur des ailes
    # Réf : Pilkey (2002) §6.5 — thin open sections, SC at intersection of legs
    # -----------------------------------------------------------------------
    if sec_type == 'angle':
        h   = metadata.get('h', 0.0)
        b   = metadata.get('b', 0.0)
        tw  = metadata.get('tw', 0.0)
        tf  = metadata.get('tf', 0.0)

        if h <= 0 or b <= 0:
            return xc, yc, 0.0

        # Pour une cornière, le centre de cisaillement est à l'intersection
        # des lignes médianes des deux ailes (axe mi-épaisseur de l'aile verticale
        # × axe mi-épaisseur de l'aile horizontale).
        # Dans le repère non centré de angle_section() :
        #   Coin extérieur en (0,0), aile horizontale vers x>0, aile verticale vers y>0
        #   Ligne médiane aile horizontale : y = tf/2
        #   Ligne médiane aile verticale   : x = tw/2
        #   Intersection (SC avant centrage) : (tw/2, tf/2)
        #
        # Calcul du centroïde d'origine (avant centrage) :
        #   Aile horizontale : rect (b × tf), centrée en (b/2, tf/2)
        #   Aile verticale   : rect (tw × (h-tf)), centrée en (tw/2, tf + (h-tf)/2)
        A_h   = b  * tf
        A_v   = tw * (h - tf)
        A_tot = A_h + A_v
        if A_tot < 1e-12:
            return xc, yc, 0.0
        xc_orig = (A_h * (b / 2.0) + A_v * (tw / 2.0)) / A_tot
        yc_orig = (A_h * (tf / 2.0) + A_v * (tf + (h - tf) / 2.0)) / A_tot

        # Position du SC dans le repère centroïdal
        xsc = tw / 2.0 - xc_orig
        ysc = tf / 2.0 - yc_orig

        # Cw ≈ 0 pour cornières (sections ouvertes minces à centre de cisaillement au coin)
        # Réf : Galambos (1998) — Cw négligeable pour cornières standard
        Cw = 0.0
        return xsc, ysc, Cw

    # -----------------------------------------------------------------------
    # Section en T — SC sur l'axe de symétrie, attiré vers la semelle
    # Réf : Pilkey (2002) §6.5 ; Galambos (1998)
    # -----------------------------------------------------------------------
    if sec_type == 't_section':
        h   = metadata.get('h', 0.0)
        b   = metadata.get('b', 0.0)
        tw  = metadata.get('tw', 0.0)
        tf  = metadata.get('tf', 0.0)

        if h <= 0 or b <= 0:
            return xc, yc, 0.0

        # xsc = xc (axe de symétrie vertical)
        # ysc = centroïde de la semelle (la semelle attire le SC)
        # t_section() : la semelle est en haut (y de h-tf à h), âme de 0 à h.
        # Après centrage (centroïde yc calculé), position centroïde semelle :
        # y_centroïde_semelle_avant_centrage = h - tf/2
        # ysc = (h - tf/2) - yc_orig
        # Calcul de yc_orig (centroïde avant centrage) :
        A_flange = b  * tf
        A_web    = tw * (h - tf)
        A_tot    = A_flange + A_web
        if A_tot < 1e-12:
            return xc, yc, 0.0
        yc_orig = (A_flange * (h - tf / 2.0) + A_web * ((h - tf) / 2.0)) / A_tot

        ysc = (h - tf / 2.0) - yc_orig   # dans le repère centroïdal

        # Cw T-section (Galambos 1998) — très faible mais non nul :
        #   Cw = (b³ * tf) / 144 + (tw³ * (h - tf)) / 144
        # Note : cette formule donne Cw en mm⁶ pour dimensions en mm.
        Cw = (b ** 3 * tf) / 144.0 + (tw ** 3 * (h - tf)) / 144.0
        return xc, ysc, max(Cw, 0.0)

    # -----------------------------------------------------------------------
    # Fallback — section dessinée à main libre ou type inconnu
    # -----------------------------------------------------------------------
    return xc, yc, 0.0


def _compute_J_analytical(metadata: dict) -> float:
    """
    Compute St-Venant torsional constant J analytically for known section types.
    Returns 0.0 if type is unknown or dimensions are invalid.
    All dimensions in mm, result in mm⁴.

    References
    ----------
    - Circle/CHS   : exact — J = π d⁴/32 or π(d_ext⁴−d_int⁴)/32
    - Rectangle    : Timoshenko & Gere (1961) §5.3 — J = (a t³/3)(1−0.630 t/a+0.052(t/a)⁵)
    - Box/RHS/SHS  : Bredt (1896) — J = 4 A_m²/∮(ds/t)
    - I/U/T/L thin : J = (1/3)Σ b_i t_i³ — approximate, no fillets
    """
    sec_type = metadata.get('type', '')

    # ------------------------------------------------------------------
    if sec_type == 'circle':
        d = metadata.get('d', 0.0)
        if d <= 0:
            return 0.0
        return math.pi * d**4 / 32.0

    # ------------------------------------------------------------------
    if sec_type == 'chs':
        d_ext = metadata.get('d_ext', 0.0)
        d_int = metadata.get('d_int', 0.0)
        if d_ext <= 0 or d_int <= 0 or d_int >= d_ext:
            return 0.0
        return math.pi * (d_ext**4 - d_int**4) / 32.0

    # ------------------------------------------------------------------
    if sec_type == 'rectangle':
        b = metadata.get('b', 0.0)
        h = metadata.get('h', 0.0)
        if b <= 0 or h <= 0:
            return 0.0
        a = max(b, h)
        t = min(b, h)
        r = t / a
        return (a * t**3 / 3.0) * (1.0 - 0.630 * r + 0.052 * r**5)

    # ------------------------------------------------------------------
    # Bredt formula for closed thin-walled rectangular sections (Box/RHS/SHS)
    if sec_type == 'box':
        h  = metadata.get('h', 0.0)
        b  = metadata.get('b', 0.0)
        tw = metadata.get('tw', 0.0)
        tf = metadata.get('tf', 0.0)
        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return 0.0
        A_m = (h - tf) * (b - tw)
        perim_over_t = 2.0 * (h - tf) / tw + 2.0 * (b - tw) / tf
        if perim_over_t < 1e-12 or A_m <= 0:
            return 0.0
        return 4.0 * A_m**2 / perim_over_t

    # ------------------------------------------------------------------
    # Open thin-walled sections: J = (1/3) Σ b_i t_i³  (Timoshenko §5.3)
    # Note: underestimates I/T/L by ~25-35% (fillets ignored),
    # may overestimate U slightly (tapered flanges not modelled).
    if sec_type == 'i_section':
        h  = metadata.get('h', 0.0)
        b  = metadata.get('b', 0.0)
        tw = metadata.get('tw', 0.0)
        tf = metadata.get('tf', 0.0)
        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return 0.0
        hw = h - 2.0 * tf
        return (1.0 / 3.0) * (2.0 * b * tf**3 + hw * tw**3)

    if sec_type == 'channel':
        h  = metadata.get('h', 0.0)
        b  = metadata.get('b', 0.0)
        tw = metadata.get('tw', 0.0)
        tf = metadata.get('tf', 0.0)
        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return 0.0
        hw = h - 2.0 * tf
        return (1.0 / 3.0) * (hw * tw**3 + 2.0 * b * tf**3)

    if sec_type == 't_section':
        h  = metadata.get('h', 0.0)
        b  = metadata.get('b', 0.0)
        tw = metadata.get('tw', 0.0)
        tf = metadata.get('tf', 0.0)
        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return 0.0
        hw = h - tf
        return (1.0 / 3.0) * (b * tf**3 + hw * tw**3)

    if sec_type == 'angle':
        h  = metadata.get('h', 0.0)
        b  = metadata.get('b', 0.0)
        tw = metadata.get('tw', 0.0)
        tf = metadata.get('tf', 0.0)
        if h <= 0 or b <= 0 or tw <= 0 or tf <= 0:
            return 0.0
        return (1.0 / 3.0) * (b * tf**3 + (h - tf) * tw**3)

    return 0.0


def _validate_polygon(pts):
    """Return (is_valid, reason_str). Minimum 3 non-collinear points required."""
    if len(pts) < 3:
        return False, f"Polygone dégénéré : {len(pts)} point(s) (minimum 3)"
    a, _, _ = _polygon_area_and_centroid(pts)
    if abs(a) < 1e-6:
        return False, "Polygone dégénéré : aire nulle (points collinéaires ?)"
    return True, ""


def compute_properties(outer_polygons: List[List[Tuple[float, float]]],
                        hole_polygons: List[List[Tuple[float, float]]] = None,
                        section_metadata: dict = None) -> SectionResults:
    """
    Compute all section properties for a composite section.
    outer_polygons: list of polygon vertex lists (CCW positive area)
    hole_polygons: list of polygon vertex lists (holes, CW or will be subtracted)
    section_metadata: optional dict with section type/dimensions for exact SC and Cw
    All coordinates in mm.
    """
    if hole_polygons is None:
        hole_polygons = []
    if section_metadata is None:
        section_metadata = {}

    # Normalise la géométrie : union des solides, soustraction des trous, imbrication
    # respectée (cf. geometry_prep). Évite le double comptage de contours qui se
    # chevauchent/s'imbriquent et garantit la cohérence avec le moteur FEM. Repli
    # silencieux sur l'entrée brute si shapely est absent ou en cas d'échec.
    outer_polygons, hole_polygons = normalize_polygons(outer_polygons, hole_polygons)

    res = SectionResults()
    total_area = 0.0
    total_cx = 0.0
    total_cy = 0.0

    all_x = []
    all_y = []

    # Accumulate area and centroid
    parts = []  # (signed_area, cx, cy, pts)
    for pts in outer_polygons:
        ok, reason = _validate_polygon(pts)
        if not ok:
            _log.warning("Section extérieure ignorée : %s", reason)
            continue
        a, cx, cy = _polygon_area_and_centroid(pts)
        a = abs(a)
        parts.append((a, cx, cy, pts))
        total_area += a
        total_cx += a * cx
        total_cy += a * cy
        all_x.extend(p[0] for p in pts)
        all_y.extend(p[1] for p in pts)

    for pts in hole_polygons:
        ok, reason = _validate_polygon(pts)
        if not ok:
            _log.warning("Trou ignoré : %s", reason)
            continue
        a, cx, cy = _polygon_area_and_centroid(pts)
        a = abs(a)
        parts.append((-a, cx, cy, pts))
        total_area -= a
        total_cx -= a * cx
        total_cy -= a * cy
        all_x.extend(p[0] for p in pts)
        all_y.extend(p[1] for p in pts)

    if total_area <= 0 or not all_x:
        _log.warning("Aire totale nulle ou négative (trous plus grands que contour ?)")
        return res

    xc = total_cx / total_area
    yc = total_cy / total_area

    res.area = total_area
    res.xc = xc
    res.yc = yc

    if all_x:
        res.xmin = min(all_x)
        res.xmax = max(all_x)
        res.ymin = min(all_y)
        res.ymax = max(all_y)

    # Moments of inertia about centroid (parallel axis theorem)
    # _polygon_inertia returns signed values (positive for CCW, negative for CW).
    # Holes may be CCW or CW depending on the generator; we normalise to CCW before
    # applying the explicit ±1 sign so that both orientations are handled correctly.
    Ix_total = 0.0
    Iy_total = 0.0
    Ixy_total = 0.0
    sign_list = [(1, pts) for pts in outer_polygons] + [(-1, pts) for pts in hole_polygons]
    for sign, pts in sign_list:
        if len(pts) < 3:
            continue
        a, cx_part, cy_part = _polygon_area_and_centroid(pts)
        ix, iy, ixy = _polygon_inertia(pts, xc, yc)
        # Normalise to CCW convention: negate if polygon is CW (signed area < 0)
        orient = 1 if a >= 0 else -1
        Ix_total  += sign * orient * ix
        Iy_total  += sign * orient * iy
        Ixy_total += sign * orient * ixy

    res.Ix = abs(Ix_total)
    res.Iy = abs(Iy_total)
    res.Ixy = Ixy_total

    # Principal moments
    avg = (res.Ix + res.Iy) / 2.0
    diff = (res.Ix - res.Iy) / 2.0
    R = math.sqrt(diff**2 + res.Ixy**2)
    res.I1 = avg + R
    res.I2 = avg - R
    if abs(res.Ix - res.Iy) < 1e-10:
        res.theta_p = 0.0
    else:
        res.theta_p = math.degrees(0.5 * math.atan2(-2 * res.Ixy, res.Ix - res.Iy))

    # Elastic section moduli
    h_top = res.ymax - yc
    h_bot = yc - res.ymin
    w_right = res.xmax - xc
    w_left = xc - res.xmin
    res.Sx_top = res.Ix / h_top if h_top > 0 else 0.0
    res.Sx_bot = res.Ix / h_bot if h_bot > 0 else 0.0
    res.Sy_right = res.Iy / w_right if w_right > 0 else 0.0
    res.Sy_left = res.Iy / w_left if w_left > 0 else 0.0

    # Plastic moduli — sections composites (contours extérieurs moins trous)
    if outer_polygons:
        try:
            res.Zx = _plastic_modulus_composite(outer_polygons, hole_polygons, xc, yc, total_area)
            # Zy : rotation 90° CCW de tous les polygones (x,y) → (-y, x)
            outer_rot = [[(-p[1], p[0]) for p in pts] for pts in outer_polygons]
            hole_rot  = [[(-p[1], p[0]) for p in pts] for pts in hole_polygons]
            res.Zy = _plastic_modulus_composite(outer_rot, hole_rot, -yc, xc, total_area)
        except Exception as e:
            _log.warning("Calcul module plastique échoué : %s", e)
            res.Zx = 0.0
            res.Zy = 0.0

    # Radii of gyration
    res.rx = math.sqrt(res.Ix / total_area) if total_area > 0 else 0.0
    res.ry = math.sqrt(res.Iy / total_area) if total_area > 0 else 0.0

    # Centre de cisaillement — analytique si metadata disponible (exact pour I/U/L/T).
    # La constante de gauchissement Cw analytique n'est PAS fiable pour les sections
    # générales (BEM non validé) : elle n'est plus calculée ici et reste réservée au
    # moteur FEM (sectionproperties), validé (<0,1 % sur IPE 300).
    try:
        res.xsc, res.ysc, _cw_unused = _compute_shear_center_and_cw(
            section_metadata, xc, yc, res.Ix, res.Iy, res.Ixy,
            outer_polygons
        )
    except Exception:
        res.xsc = xc
        res.ysc = yc
    res.Cw = 0.0  # non calculé en analytique (cf. moteur FEM)

    # Torsion de St-Venant J — formules analytiques pour types connus, FDM pour les
    # sections libres (Prandtl, robuste pour les sections ouvertes à coins vifs).
    J_analytical = _compute_J_analytical(section_metadata)
    if J_analytical > 0.0:
        res.J = J_analytical
    else:
        outer_c = [[(p[0] - xc, p[1] - yc) for p in pts] for pts in outer_polygons]
        hole_c  = [[(p[0] - xc, p[1] - yc) for p in pts] for pts in hole_polygons]
        try:
            res.J = compute_J_fdm(outer_c, hole_c, n_cells=150)
        except Exception:
            res.J = 0.0

    return res


def results_to_dict(r: SectionResults, section_metadata: dict = None) -> dict:
    """
    Renvoie les résultats sous forme de dict ordonné {symbole_Eurocode: (valeur, unité)}.

    Convention d'axes Eurocode (y = axe fort horizontal, z = axe faible vertical).
    Dans le repère de dessin (x horizontal, y vertical) : I_y = ∫y²dA = r.Ix (axe fort),
    I_z = ∫x²dA = r.Iy. Les descriptions des symboles sont dans calculators.nomenclature.
    """
    mm2_to_cm2 = 1e-2
    mm4_to_cm4 = 1e-4
    mm3_to_cm3 = 1e-3

    return {
        "A":          (f"{r.area * mm2_to_cm2:.4f}", "cm²"),
        "y_G":        (f"{r.xc:.3f}", "mm"),
        "z_G":        (f"{r.yc:.3f}", "mm"),
        "I_y":        (f"{r.Ix * mm4_to_cm4:.4f}", "cm⁴"),
        "I_z":        (f"{r.Iy * mm4_to_cm4:.4f}", "cm⁴"),
        "I_yz":       (f"{r.Ixy * mm4_to_cm4:.4f}", "cm⁴"),
        "I_1":        (f"{r.I1 * mm4_to_cm4:.4f}", "cm⁴"),
        "I_2":        (f"{r.I2 * mm4_to_cm4:.4f}", "cm⁴"),
        "α":          (f"{r.theta_p:.2f}", "°"),
        "W_el,y,sup": (f"{r.Sx_top * mm3_to_cm3:.4f}", "cm³"),
        "W_el,y,inf": (f"{r.Sx_bot * mm3_to_cm3:.4f}", "cm³"),
        "W_el,z,g":   (f"{r.Sy_left * mm3_to_cm3:.4f}", "cm³"),
        "W_el,z,d":   (f"{r.Sy_right * mm3_to_cm3:.4f}", "cm³"),
        "W_pl,y":     (f"{r.Zx * mm3_to_cm3:.4f}", "cm³"),
        "W_pl,z":     (f"{r.Zy * mm3_to_cm3:.4f}", "cm³"),
        "i_y":        (f"{r.rx:.3f}", "mm"),
        "i_z":        (f"{r.ry:.3f}", "mm"),
        "y_SC":       (f"{r.xsc:.3f}", "mm"),
        "z_SC":       (f"{r.ysc:.3f}", "mm"),
        "I_t":        (f"{r.J * mm4_to_cm4:.4f}", "cm⁴"),
        # I_w (gauchissement) : non calculé en analytique — réservé au moteur FEM.
    }

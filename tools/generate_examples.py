"""
Générateur des sections d'exemple importables par SectionCAD.

Reproduit une sélection de géométries issues des notebooks d'exemple de
``sectionproperties`` (canal PFC, canal à ailes inclinées, arc, profil en Z,
cornière sur platine, double-I fusionné, etc.), les convertit au format projet
``.scad`` de l'application (contours + trous), et les écrit dans le dossier
``exemples/`` à la racine du projet.

Les sections multi-matériaux (béton armé, CLT, composites) des notebooks sont
volontairement écartées : SectionCAD est un outil géométrique mono-matériau et
des régions superposées de matériaux différents y seraient géométriquement
incohérentes (double comptage).

Exécution :  python tools/generate_examples.py
"""
from __future__ import annotations

import json
import math
import os

from shapely import LineString, Polygon, buffer
from shapely.ops import unary_union

from sectionproperties.pre import CompoundGeometry, Geometry
from sectionproperties.pre.library import (
    channel_section,
    circular_section,
    i_section,
    nastran_sections,
    rectangular_section,
    tapered_flange_channel,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "exemples")


# ---------------------------------------------------------------------------
# Conversion shapely / sectionproperties -> modèle de polygones de l'application
# ---------------------------------------------------------------------------
def _to_shapely(obj):
    """Renvoie la géométrie shapely d'un objet sectionproperties ou shapely."""
    return obj.geom if hasattr(obj, "geom") else obj


def _ring_to_pts(ring):
    coords = list(ring.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]  # retire le point de fermeture dupliqué
    return [[round(float(x), 4), round(float(y), 4)] for x, y in coords]


def shapely_to_polygons(shp):
    """Convertit un (Multi)Polygon shapely en liste {pts, is_hole} pour le .scad."""
    if shp.geom_type == "MultiPolygon":
        members = list(shp.geoms)
    elif shp.geom_type == "Polygon":
        members = [shp]
    else:
        raise ValueError(f"Type de géométrie inattendu : {shp.geom_type}")

    polygons = []
    for poly in members:
        polygons.append({"pts": _ring_to_pts(poly.exterior), "is_hole": False})
        for interior in poly.interiors:
            polygons.append({"pts": _ring_to_pts(interior), "is_hole": True})
    return polygons


def _nice_grid(max_dim: float) -> float:
    """Espacement de grille « rond » proche de max_dim/20 (1, 2 ou 5 ×10^k)."""
    raw = max_dim / 20.0
    if raw <= 0:
        return 10.0
    k = math.floor(math.log10(raw))
    base = 10.0 ** k
    for m in (1, 2, 5):
        if raw <= m * base:
            return round(m * base, 6)
    return round(10 * base, 6)


def write_scad(filename, name, description, source, units, geom):
    """Construit et écrit un fichier projet .scad pour une géométrie donnée."""
    shp = unary_union(_to_shapely(geom))  # silhouette propre (fusionne les régions accolées)
    polygons = shapely_to_polygons(shp)

    xs = [p[0] for poly in polygons for p in poly["pts"]]
    ys = [p[1] for poly in polygons for p in poly["pts"]]
    max_dim = max(max(xs) - min(xs), max(ys) - min(ys))

    data = {
        "version": 1,
        "app": "SectionCAD",
        "name": name,
        "description": description,
        "source": source,
        "units": units,
        "grid_spacing": _nice_grid(max_dim),
        "snap_enabled": True,
        "polygons": polygons,
    }

    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    n_holes = sum(1 for p in polygons if p["is_hole"])
    n_out = len(polygons) - n_holes
    print(f"  {filename:34s} {len(polygons):2d} polygone(s) "
          f"({n_out} contour(s), {n_holes} trou(s))  [{units}]")


# ---------------------------------------------------------------------------
# Constructeurs de géométries spécifiques (depuis des points / courbes)
# ---------------------------------------------------------------------------
def arc_geometry(r, t, alpha_deg, n=128):
    """Arc circulaire mince : LineString du centre, extrudé orthogonalement (Pilkey B.7)."""
    alpha = math.radians(alpha_deg)
    pts = []
    for i in range(n):
        theta = -alpha / 2 + i / (n - 1) * alpha
        pts.append((r * math.sin(theta), r * math.cos(theta)))
    return buffer(LineString(pts), distance=0.5 * t, cap_style="flat", join_style="mitre")


def trapezoid_geometry(b, d1, d2):
    """Section trapézoïdale (gousset/haunch) depuis 4 points."""
    return Polygon([(0, 0), (0, d1), (b, d2), (b, 0)])


def angle_plate_geometry(scale=100.0):
    """Cornière inversée posée sur une platine — deux régions accolées (from_points)."""
    w_a, w_p, d, t = 1 * scale, 2 * scale, 2 * scale, 0.1 * scale
    points = [
        (w_p * -0.5, 0), (w_p * 0.5, 0), (w_p * 0.5, t), (w_p * -0.5, t),  # platine
        (t * -0.5, t), (t * 0.5, t), (t * 0.5, d - t),
        (w_a - 0.5 * t, d - t), (w_a - 0.5 * t, d), (t * -0.5, d),         # cornière
    ]
    facets = [(0, 1), (1, 2), (2, 3), (3, 0),
              (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 4)]
    control_points = [(0, t * 0.5), (0, d - t)]
    return CompoundGeometry.from_points(points=points, facets=facets,
                                        control_points=control_points)


def merged_double_i():
    """Deux profils en I fusionnés (un droit, un tourné à 45°) — advanced_geometry.ipynb."""
    i1 = i_section(d=250, b=150, t_f=13, t_w=10, r=12, n_r=12)
    i2 = i1.rotate_section(angle=45)
    return i1.geom.union(i2.geom)


# ---------------------------------------------------------------------------
# Catalogue d'exemples
# ---------------------------------------------------------------------------
def build_all():
    examples = [
        ("01_rectangle.scad", "Rectangle plein 200×100",
         "Rectangle plein — section de référence.",
         "sectionproperties (rectangular_section)", "mm",
         rectangular_section(d=200, b=100)),

        ("02_cercle.scad", "Cercle plein Ø50",
         "Cercle plein discrétisé par 64 points (J = Ix + Iy).",
         "section_library.ipynb (circular_section)", "mm",
         circular_section(d=50, n=64)),

        ("03_profil_I_avec_conges.scad", "Profil en I 250×150 (congés r=12)",
         "Profil en I laminé AVEC congés de raccordement — impossible avec les "
         "générateurs paramétriques internes (sans congés).",
         "advanced_geometry.ipynb (i_section)", "mm",
         i_section(d=250, b=150, t_f=13, t_w=10, r=12, n_r=12)),

        ("04_canal_PFC_250.scad", "Canal 250 PFC (congés r=12)",
         "Canal laminé type PFC avec congés — section ouverte à parois minces.",
         "warping_analysis.ipynb (channel_section)", "mm",
         channel_section(d=250, b=90, t_f=15, t_w=8, r=12, n_r=8)),

        ("05_canal_ailes_inclinees.scad", "Canal à ailes inclinées (impérial)",
         "Canal à semelles inclinées (taper) et congés — profil impérial.",
         "section_library.ipynb (tapered_flange_channel)", "pouces",
         tapered_flange_channel(d=10, b=3.5, t_f=0.575, t_w=0.475,
                                r_r=0.575, r_f=0.4, alpha=8, n_r=16)),

        ("06_profil_Z.scad", "Profil en Z dissymétrique",
         "Profil en Z : Ixy ≠ 0, axes principaux tournés (flexion déviée).",
         "peery.ipynb (nastran_zed)", "pouces",
         nastran_sections.nastran_zed(dim_1=4, dim_2=2, dim_3=8, dim_4=12)),

        ("07_arc_circulaire.scad", "Arc circulaire 120°",
         "Arc mince ouvert de 120° (rayon 16, épaisseur 0,5) — section courbe.",
         "pilkey_arc.ipynb (LineString.buffer)", "pouces",
         arc_geometry(r=16, t=0.5, alpha_deg=120, n=128)),

        ("08_trapeze_gousset.scad", "Trapèze (gousset de pont)",
         "Section trapézoïdale (gousset/haunch de poutre composite).",
         "trapezoidal_torsion.ipynb", "mm",
         trapezoid_geometry(b=400, d1=150, d2=300)),

        ("09_corniere_sur_platine.scad", "Cornière sur platine",
         "Cornière inversée accolée à une platine (deux régions connexes).",
         "geometry_coordinates.ipynb (from_points)", "mm",
         angle_plate_geometry(scale=100.0)),

        ("10_double_I_fusionne.scad", "Deux profils I fusionnés à 45°",
         "Union d'un profil I droit et d'un profil I tourné à 45° — la fusion "
         "crée deux interstices (trous).",
         "advanced_geometry.ipynb", "mm",
         merged_double_i()),
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Écriture des exemples dans : {OUTPUT_DIR}")
    for filename, name, desc, source, units, geom in examples:
        write_scad(filename, name, desc, source, units, geom)
    print(f"\n{len(examples)} exemples générés.")


if __name__ == "__main__":
    build_all()

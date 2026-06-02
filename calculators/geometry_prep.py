"""
Préparation géométrique partagée (shapely) — source unique d'interprétation de la
géométrie pour les moteurs ANALYTIQUE et FEM, afin qu'ils soient cohérents.

À partir du modèle de l'application (liste de contours + liste de trous), on construit
la VRAIE région matérielle en respectant l'imbrication arbitraire
(contour → trou → îlot solide → trou dans l'îlot → …) :

  - on traite les polygones du plus GRAND au plus PETIT (un polygone contenant ayant
    toujours une aire supérieure à ce qu'il contient → ordre topologique correct,
    indépendant de l'ordre de saisie) ;
  - on UNIONNE les solides et on SOUSTRAIT les trous dans cet ordre.

Cela évite notamment le double comptage de deux solides qui se chevauchent/s'imbriquent
(un simple Σ aires les additionnerait), et la disparition d'un îlot logé dans un trou
(un simple « union(contours) − union(trous) » l'effacerait).

`normalize_polygons()` est en repli silencieux si shapely est absent ou en cas d'échec :
elle renvoie l'entrée inchangée (comportement historique du moteur analytique).
"""
from __future__ import annotations

import importlib.util
from typing import List, Optional, Tuple

SHAPELY_AVAILABLE = importlib.util.find_spec("shapely") is not None

REPAIR_WARNING = (
    "Un contour auto-intersectant a été réparé automatiquement (buffer 0) ; "
    "l'aire calculée peut différer de la saisie."
)


def _warn_once(sink, msg):
    if sink is not None and msg not in sink:
        sink.append(msg)


def _prepare_polygon(pts, polygon_cls, warn_sink):
    """Construit un Polygon shapely valide (répare si besoin), ou None si dégénéré."""
    if len(pts) < 3:
        return None
    poly = polygon_cls(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)  # tente de réparer auto-intersections mineures
        _warn_once(warn_sink, REPAIR_WARNING)
    if poly.is_valid and poly.area > 1e-9:
        return poly
    return None


def build_material_region(outer_polygons, hole_polygons, warn_sink=None):
    """
    Construit la région matérielle en respectant l'imbrication des polygones.

    Renvoie un `shapely (Multi)Polygon`. `warn_sink`, si fourni, reçoit des
    avertissements (ex. réparation de contour).
    Lève ValueError si la géométrie est dégénérée, RuntimeError si shapely manque.
    """
    if not SHAPELY_AVAILABLE:
        raise RuntimeError("shapely indisponible")
    from shapely import MultiPolygon, Polygon

    items = []           # (aire, is_hole, polygone)
    has_outer = False
    for pts in outer_polygons:
        poly = _prepare_polygon(pts, Polygon, warn_sink)
        if poly is not None:
            items.append((poly.area, False, poly))
            has_outer = True
    for pts in (hole_polygons or []):
        poly = _prepare_polygon(pts, Polygon, warn_sink)
        if poly is not None:
            items.append((poly.area, True, poly))

    if not has_outer:
        raise ValueError("Aucun contour extérieur valide (minimum 3 points, aire non nulle).")

    # Du plus grand au plus petit : un contenant est traité avant son contenu.
    items.sort(key=lambda it: it[0], reverse=True)
    material = Polygon()  # géométrie vide
    for _area, is_hole, poly in items:
        material = material.difference(poly) if is_hole else material.union(poly)

    if material.is_empty or material.area <= 1e-9:
        raise ValueError("Aire matérielle nulle (les trous couvrent-ils tout le contour ?).")

    # Normalise en (Multi)Polygon ; ignore d'éventuelles lignes/points résiduels.
    if material.geom_type == "GeometryCollection":
        polys = [g for g in material.geoms if g.geom_type == "Polygon" and g.area > 1e-9]
        material = MultiPolygon(polys) if len(polys) > 1 else polys[0]
    return material


def material_pieces(material):
    """Liste des Polygon constitutifs, orientés (extérieur CCW, intérieurs CW)."""
    from shapely.geometry.polygon import orient
    pieces = list(material.geoms) if material.geom_type == "MultiPolygon" else [material]
    return [orient(p, 1.0) for p in pieces]


def void_markers(material, pieces):
    """
    Points représentatifs des VRAIS vides (= remplissage des contours − matière).
    Sert à placer les marqueurs de trous du mailleur, y compris autour d'un îlot
    logé dans un trou (sinon le marqueur tomberait dans l'îlot et le « percerait »).
    """
    from shapely import Polygon
    from shapely.ops import unary_union
    filled = unary_union([Polygon(p.exterior.coords) for p in pieces])
    voids = filled.difference(material)
    if voids.geom_type == "MultiPolygon":
        vlist = list(voids.geoms)
    elif voids.geom_type == "Polygon" and not voids.is_empty:
        vlist = [voids]
    else:
        vlist = []
    markers = []
    for v in vlist:
        if v.area > 1e-9:
            rp = v.representative_point()
            markers.append((rp.x, rp.y))
    return markers


def _ring_pts(coords) -> List[Tuple[float, float]]:
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]  # retire le point de fermeture dupliqué
    return [(float(x), float(y)) for x, y in pts]


def normalize_polygons(outer_polygons, hole_polygons):
    """
    Décompose la vraie région matérielle en (clean_outers, clean_holes) :
    anneaux extérieurs (solides) et intérieurs (trous), SANS chevauchement ni
    double comptage. Utilisable directement par le moteur analytique (sommes signées).

    En l'absence de shapely ou en cas d'échec, renvoie l'entrée inchangée (repli).
    """
    holes = list(hole_polygons or [])
    if not SHAPELY_AVAILABLE:
        return list(outer_polygons), holes
    try:
        material = build_material_region(outer_polygons, holes)
    except Exception:
        # Géométrie dégénérée ou échec shapely : on laisse le moteur appelant gérer.
        return list(outer_polygons), holes

    clean_outers: List[List[Tuple[float, float]]] = []
    clean_holes: List[List[Tuple[float, float]]] = []
    for piece in material_pieces(material):
        clean_outers.append(_ring_pts(piece.exterior.coords))
        for interior in piece.interiors:
            clean_holes.append(_ring_pts(interior.coords))
    return clean_outers, clean_holes

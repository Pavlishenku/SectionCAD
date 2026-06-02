"""
Backend de calcul des propriétés de section basé sur le package `sectionproperties`
(méthode des éléments finis — maillage triangulaire + analyse de gauchissement).

Ce module est **pur** (aucune dépendance Qt) afin de pouvoir être exécuté dans un
thread d'arrière-plan (voir ui/fea_worker.py) sans bloquer l'interface.

Rôle dans l'application
-----------------------
Les calculateurs maison (calculators/section_properties.py : shoelace, FDM, BEM)
restent le moteur par défaut et l'aperçu instantané pendant le dessin. Ce backend
FEA est lancé à la demande (bouton « Calculer (FEA) ») et fournit des valeurs de
référence précises pour J (constante de torsion de St-Venant), Cw (gauchissement),
le centre de cisaillement et les aires de cisaillement — propriétés que les formules
analytiques n'approchent qu'à ±30 % pour les sections ouvertes.

Conventions
-----------
- Toutes les coordonnées d'entrée et de sortie sont en millimètres.
- Entrée : `outer_polygons` = liste de contours (listes de (x, y)),
           `hole_polygons` = liste de trous (listes de (x, y)).
  Le matériau réel est calculé par union des contours moins union des trous
  (opérations booléennes shapely), ce qui gère automatiquement l'imbrication
  des trous, les chevauchements éventuels et la détection des régions disjointes.

Précision (validée) : Cw d'un IPE300 = 125 800 cm⁶ contre 125 900 cm⁶ au catalogue.
"""
from __future__ import annotations

import importlib.util
import warnings as _warnings
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from calculators.geometry_prep import (
    build_material_region as _build_region,
    material_pieces as _material_pieces,
    void_markers as _void_markers,
)

# Disponibilité détectée SANS importer les packages (find_spec ne les exécute pas) :
# l'import réel de sectionproperties prend 1-2 s, on le diffère au premier calcul
# (exécuté dans un thread worker) pour ne pas ralentir le démarrage de l'application.
SECTIONPROPERTIES_AVAILABLE = (
    importlib.util.find_spec("sectionproperties") is not None
    and importlib.util.find_spec("shapely") is not None
)
IMPORT_ERROR: Optional[str] = None if SECTIONPROPERTIES_AVAILABLE else (
    "Packages requis introuvables (sectionproperties et/ou shapely)."
)

# Noms remplis paresseusement par _ensure_imports().
Polygon = MultiPolygon = orient = unary_union = None
Geometry = CompoundGeometry = Section = None


def _ensure_imports():
    """Importe shapely + sectionproperties à la première utilisation (coûteux)."""
    global Polygon, MultiPolygon, orient, unary_union
    global Geometry, CompoundGeometry, Section
    if Section is not None:
        return
    from shapely import Polygon as _Polygon, MultiPolygon as _MultiPolygon
    from shapely.geometry.polygon import orient as _orient
    from shapely.ops import unary_union as _unary_union
    from sectionproperties.pre import Geometry as _Geometry, CompoundGeometry as _CompoundGeometry
    from sectionproperties.analysis import Section as _Section
    Polygon, MultiPolygon, orient, unary_union = _Polygon, _MultiPolygon, _orient, _unary_union
    Geometry, CompoundGeometry, Section = _Geometry, _CompoundGeometry, _Section


# Densité de maillage : nombre d'éléments visé -> taille max d'élément = aire / N.
# La taille réelle est plafonnée pour que les parois minces soient résolues.
MESH_QUALITY = {
    "Grossier": 300,
    "Moyen": 1200,
    "Fin": 3500,
}
DEFAULT_QUALITY = "Moyen"


@dataclass
class FEAResults:
    """Résultats d'une analyse sectionproperties. Unités : mm, mm², mm⁴, mm⁶."""
    # Géométrie de base
    area: float = 0.0
    xc: float = 0.0
    yc: float = 0.0
    # Inerties centroïdales
    Ix: float = 0.0
    Iy: float = 0.0
    Ixy: float = 0.0
    # Axes principaux
    I1: float = 0.0
    I2: float = 0.0
    theta_p: float = 0.0          # deg
    # Modules élastiques
    Sx_top: float = 0.0
    Sx_bot: float = 0.0
    Sy_right: float = 0.0
    Sy_left: float = 0.0
    # Rayons de giration
    rx: float = 0.0
    ry: float = 0.0
    # Modules plastiques + centroïde plastique
    Zx: float = 0.0
    Zy: float = 0.0
    x_pc: float = 0.0
    y_pc: float = 0.0
    # Boîte englobante
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    # Torsion / gauchissement / cisaillement (analyse de warping)
    J: float = 0.0                # mm⁴
    Cw: float = 0.0               # mm⁶ (gamma)
    xsc: float = 0.0              # centre de cisaillement (élastique)
    ysc: float = 0.0
    A_sx: float = 0.0             # aire de cisaillement selon x
    A_sy: float = 0.0
    # Métadonnées d'analyse
    n_elements: int = 0
    n_nodes: int = 0
    mesh_size: float = 0.0
    quality: str = DEFAULT_QUALITY
    warping_valid: bool = False   # False si régions disjointes / échec du warping
    warnings: List[str] = field(default_factory=list)
    # Maillage éléments finis (pour visualisation optionnelle sur le canvas).
    # Coordonnées dans le repère de la géométrie (mm), mêmes que les polygones.
    mesh_vertices: list = field(default_factory=list)   # [(x, y), ...]
    mesh_triangles: list = field(default_factory=list)  # [(i, j, k), ...] indices de sommets


# ---------------------------------------------------------------------------
# Construction de la géométrie sectionproperties (préparation partagée : geometry_prep)
# ---------------------------------------------------------------------------
def _build_material_region(outer_polygons, hole_polygons, warn_sink=None):
    """
    Région matérielle shapely (imbrication respectée) + indicateur de connexité.

    La construction est déléguée au module partagé `geometry_prep` afin que les
    moteurs analytique et FEM interprètent la géométrie de façon strictement
    identique. Renvoie (geom_shapely, is_connected) ; un Polygon est connexe
    (gauchissement valide), un MultiPolygon est disjoint.
    """
    material = _build_region(outer_polygons, hole_polygons, warn_sink)
    is_connected = (material.geom_type == "Polygon")
    return material, is_connected


def _to_sp_geometry(material):
    """
    Convertit un (Multi)Polygon shapely en Geometry/CompoundGeometry sectionproperties.

    Pour un MultiPolygon, le compile_geometry de sectionproperties place les marqueurs
    de trous au point représentatif de chaque intérieur — ce qui tombe À L'INTÉRIEUR
    d'un éventuel îlot solide logé dans un trou et le « perce » (CyTriangle n'a pas de
    z-ordering). On recalcule donc les marqueurs depuis les vrais vides et on les force
    (create_mesh lit self.holes tel quel, sans recompiler).
    """
    pieces = _material_pieces(material)
    if material.geom_type == "MultiPolygon":
        geom = CompoundGeometry([Geometry(p) for p in pieces])
        geom.holes = _void_markers(material, pieces)
        return geom
    return Geometry(pieces[0])


def _mesh_size_for(area: float, quality: str) -> float:
    """Taille max d'élément (aire en mm²) pour une aire de section et une qualité données."""
    n_target = MESH_QUALITY.get(quality, MESH_QUALITY[DEFAULT_QUALITY])
    return max(area / float(n_target), 1e-4)


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------
def compute_properties_fea(
    outer_polygons: List[List[Tuple[float, float]]],
    hole_polygons: Optional[List[List[Tuple[float, float]]]] = None,
    section_metadata: Optional[dict] = None,
    quality: str = DEFAULT_QUALITY,
    compute_plastic: bool = True,
    compute_warping: bool = True,
) -> FEAResults:
    """
    Calcule les propriétés de section via sectionproperties (FEA).

    Géométrique est toujours calculé. `compute_plastic` / `compute_warping` permettent
    de désactiver les étapes plastique / gauchissement (le gauchissement est l'étape
    coûteuse) — utile pour des comparaisons géométriques rapides A/Iy/Iz.
    L'analyse de gauchissement (J, Cw, centre de cisaillement, aires de cisaillement)
    n'est de toute façon lancée que si la région est connexe ; sinon ces valeurs
    restent à 0 et un avertissement est ajouté.

    Lève RuntimeError si le package n'est pas installé, ValueError si la géométrie
    est invalide.
    """
    if not SECTIONPROPERTIES_AVAILABLE:
        raise RuntimeError(
            "Le package « sectionproperties » n'est pas installé.\n"
            f"Détail : {IMPORT_ERROR}\n"
            "Installez-le avec :  pip install sectionproperties"
        )

    _ensure_imports()

    if hole_polygons is None:
        hole_polygons = []
    # section_metadata est accepté pour la symétrie d'API avec le moteur analytique
    # mais n'est pas utilisé : l'analyse FEA repose uniquement sur la géométrie.
    _ = section_metadata

    res = FEAResults(quality=quality)

    material, is_connected = _build_material_region(
        outer_polygons, hole_polygons, warn_sink=res.warnings
    )
    xmin, ymin, xmax, ymax = material.bounds
    res.xmin, res.ymin, res.xmax, res.ymax = xmin, ymin, xmax, ymax

    geom = _to_sp_geometry(material)
    mesh_size = _mesh_size_for(material.area, quality)
    res.mesh_size = mesh_size

    geom.create_mesh(mesh_sizes=[mesh_size])
    sec = Section(geom)

    res.n_elements = len(sec.mesh["triangles"])
    res.n_nodes = len(sec.mesh["vertices"])
    # Extrait le maillage (noeuds + coins de triangles) pour la visualisation.
    _vert = sec.mesh["vertices"]
    _tri = sec.mesh["triangles"]
    res.mesh_vertices = [(float(v[0]), float(v[1])) for v in _vert]
    res.mesh_triangles = [(int(t[0]), int(t[1]), int(t[2])) for t in _tri]

    # --- Propriétés géométriques (rapides, toujours valides) ---
    sec.calculate_geometric_properties()
    res.area = float(sec.get_area())
    cx, cy = sec.get_c()
    res.xc, res.yc = float(cx), float(cy)
    # Par défaut le centre de cisaillement = centroïde (écrasé si le gauchissement
    # est calculé) ; évite un marqueur SC parasite à l'origine sur le canvas.
    res.xsc, res.ysc = res.xc, res.yc
    ixx, iyy, ixy = sec.get_ic()
    res.Ix, res.Iy, res.Ixy = float(ixx), float(iyy), float(ixy)
    i11, i22 = sec.get_ip()
    res.I1, res.I2 = float(i11), float(i22)
    # get_phi() renvoie l'angle de l'axe principal MAJEUR dans (-180, 180]. On le
    # ramène dans (-90, 90] pour rester cohérent avec le moteur analytique de
    # référence (sinon une section dissymétrique afficherait un θ décalé de 180°).
    phi = float(sec.get_phi())
    res.theta_p = ((phi + 90.0) % 180.0) - 90.0
    zxx_p, zxx_m, zyy_p, zyy_m = sec.get_z()
    res.Sx_top, res.Sx_bot = float(zxx_p), float(zxx_m)
    res.Sy_right, res.Sy_left = float(zyy_p), float(zyy_m)
    rx, ry = sec.get_rc()
    res.rx, res.ry = float(rx), float(ry)

    # --- Propriétés plastiques (valides même pour sections disjointes) ---
    if compute_plastic:
        try:
            sec.calculate_plastic_properties()
            sxx, syy = sec.get_s()
            res.Zx, res.Zy = float(sxx), float(syy)
            x_pc, y_pc = sec.get_pc()
            res.x_pc, res.y_pc = float(x_pc), float(y_pc)
        except Exception as exc:
            res.warnings.append(f"Modules plastiques non calculés : {exc}")

    # --- Analyse de gauchissement (J, Cw, centre de cisaillement) ---
    if not compute_warping:
        pass
    elif not is_connected:
        res.warping_valid = False
        res.warnings.append(
            "Régions disjointes détectées : J, Cw, centre de cisaillement et aires "
            "de cisaillement ne sont pas calculés (l'analyse de gauchissement exige "
            "une section d'un seul tenant)."
        )
    else:
        try:
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                sec.calculate_warping_properties()
                disjoint_warn = any(
                    "disjoint" in str(w.message).lower() for w in caught
                )
            if disjoint_warn:
                res.warping_valid = False
                res.warnings.append(
                    "sectionproperties signale des régions disjointes : J/Cw ignorés."
                )
            else:
                res.J = float(sec.get_j())
                res.Cw = float(sec.get_gamma())
                xse, yse = sec.get_sc()
                res.xsc, res.ysc = float(xse), float(yse)
                a_sx, a_sy = sec.get_as()
                res.A_sx, res.A_sy = float(a_sx), float(a_sy)
                res.warping_valid = True
        except Exception as exc:
            res.warping_valid = False
            res.warnings.append(f"Analyse de gauchissement échouée : {exc}")

    return res


# ---------------------------------------------------------------------------
# Mise en forme pour affichage (même format que results_to_dict : {label: (val, unit)})
# ---------------------------------------------------------------------------
def fea_results_to_dict(r: FEAResults) -> dict:
    """Renvoie les résultats sous forme de dict ordonné {label: (valeur_str, unité)}."""
    mm2_to_cm2 = 1e-2
    mm4_to_cm4 = 1e-4
    mm3_to_cm3 = 1e-3
    mm6_to_cm6 = 1e-6

    d = {
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
    }

    if r.warping_valid:
        d["y_SC"] = (f"{r.xsc:.3f}", "mm")
        d["z_SC"] = (f"{r.ysc:.3f}", "mm")
        d["I_t"] = (f"{r.J * mm4_to_cm4:.4f}", "cm⁴")
        d["I_w"] = (f"{r.Cw * mm6_to_cm6:.4f}", "cm⁶")
        d["A_vy"] = (f"{r.A_sx * mm2_to_cm2:.4f}", "cm²")
        d["A_vz"] = (f"{r.A_sy * mm2_to_cm2:.4f}", "cm²")
    else:
        d["I_t"] = ("n/d", "—")
        d["I_w"] = ("n/d", "—")

    return d

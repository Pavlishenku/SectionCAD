"""
Base de comparaison FEM ⇄ analytique.

Pour un large panel de sections diverses (paramétriques, catalogue, composites,
décentrées, tournées, chevauchantes, îlots…), on vérifie que les deux moteurs
s'accordent sur les propriétés GÉOMÉTRIQUES :
    A (aire), Ix/Iy (= I_y/I_z Eurocode), Ixy, et le centroïde.

But : détecter toute incohérence entre moteurs. Les propriétés géométriques de
sectionproperties sont mesh-indépendantes (intégration exacte sur le polygone
triangulé), donc l'accord doit être quasi exact ; on n'active ni le plastique ni
le gauchissement (rapide).

Exécutable en script pour afficher le tableau des écarts :  python tests/test_fem_vs_analytic.py
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculators.section_properties import compute_properties
from calculators.sp_backend import SECTIONPROPERTIES_AVAILABLE, compute_properties_fea
import sections.parametric as para

pytestmark = pytest.mark.skipif(
    not SECTIONPROPERTIES_AVAILABLE, reason="sectionproperties requis"
)


# --------------------------------------------------------------------------- helpers
def _rotate(pts, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


def _shift(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def _sq(s, cx=0.0, cy=0.0):
    h = s / 2.0
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def _outer(result):
    """Renvoie la liste de contours d'un générateur paramétrique ([outer] ou (outers,holes))."""
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, []


# --------------------------------------------------------------------------- cas de test
def build_cases():
    """Renvoie une liste de (label, outers, holes) variés."""
    c = []

    # --- pleines simples ---
    c.append(("rectangle 100x200", para.rectangle(100, 200), []))
    c.append(("rectangle plat 300x40", para.rectangle(300, 40), []))
    c.append(("carré 150", [_sq(150)], []))
    c.append(("cercle d120 (64)", para.circle(120), []))
    c.append(("triangle", [[(0, 0), (200, 0), (60, 180)]], []))

    # --- profils ouverts (asymétriques inclus) ---
    c.append(("I 300x150", para.i_section(300, 150, 8, 12), []))
    c.append(("I 200x100", para.i_section(200, 100, 5.6, 8.5), []))
    c.append(("Té 300x150", para.t_section(300, 150, 8, 12), []))
    c.append(("UPN 250x90", para.channel_section(250, 90, 8, 15), []))
    c.append(("cornière égale 100", para.angle_section(100, 100, 10, 10), []))
    c.append(("cornière inégale 150x100", para.angle_section(150, 100, 12, 10), []))
    c.append(("croix 300", para.cross_section(300, 300, 20, 20), []))

    # --- creuses (contour + trou) ---
    o, h = _outer(para.hollow_circle(200, 150)); c.append(("CHS 200/150", o, h))
    o, h = _outer(para.box_section(300, 200, 10, 14)); c.append(("caisson 300x200", o, h))
    o, h = _outer(para.square_hollow(120, 8)); c.append(("SHS 120x8", o, h))
    o, h = _outer(para.rectangular_hollow(200, 100, 6)); c.append(("RHS 200x100x6", o, h))

    # --- catalogue (dimensions réelles) ---
    c.append(("IPE 300 (cat)", para.i_section(300, 150, 7.1, 10.7), []))
    c.append(("HEA 200 (cat)", para.i_section(190, 200, 6.5, 10), []))
    c.append(("UPN 200 (cat)", para.channel_section(200, 75, 8.5, 11.5), []))

    # --- décentrées / tournées (Ixy ≠ 0, axes principaux tournés) ---
    c.append(("rectangle décentré (80,40)", [_shift(_sq(100), 80, 40)], []))
    c.append(("I tourné 30°", [_rotate(para.i_section(300, 150, 8, 12)[0], 30)], []))
    c.append(("rectangle tourné 45°", [_rotate(_sq(120), 45)], []))
    c.append(("L depuis points", [[(0, 0), (120, 0), (120, 20), (20, 20), (20, 160), (0, 160)]], []))

    # --- composites / trous multiples / disjoints / îlots ---
    c.append(("plaque 200x100, 2 trous",
              [_sq(200)],  # placeholder remplacé ci-dessous
              []))
    c[-1] = ("plaque 300x120, 2 trous carrés",
             [[(-150, -60), (150, -60), (150, 60), (-150, 60)]],
             [_sq(40, -70, 0), _sq(40, 70, 0)])
    c.append(("deux rectangles disjoints",
              [_shift(_sq(80), -90, 0), _shift(_sq(80), 90, 0)], []))
    c.append(("îlot dans trou", [_sq(200), _sq(60)], [_sq(120)]))
    c.append(("solides chevauchants", [_sq(120), _shift(_sq(100), 70, 0)], []))

    return c


CASES = build_cases()


def compare(outers, holes):
    """Renvoie (ana, fea, dict d'écarts relatifs/absolus)."""
    ana = compute_properties(outers, holes)
    fea = compute_properties_fea(outers, holes, quality="Grossier",
                                 compute_plastic=False, compute_warping=False)

    def rel(a, b):
        d = abs(a - b)
        return d / max(abs(a), abs(b)) if max(abs(a), abs(b)) > 1e-12 else d

    inertia_scale = max(abs(ana.Ix), abs(ana.Iy), 1.0)
    errors = {
        "A": rel(ana.area, fea.area),
        "Iy(=Ix)": rel(ana.Ix, fea.Ix),
        "Iz(=Iy)": rel(ana.Iy, fea.Iy),
        "Iyz(=Ixy)": abs(ana.Ixy - fea.Ixy) / inertia_scale,
        "yc": abs(ana.xc - fea.xc),
        "zc": abs(ana.yc - fea.yc),
    }
    return ana, fea, errors


@pytest.mark.parametrize("label,outers,holes", CASES, ids=[c[0] for c in CASES])
def test_fem_matches_analytic(label, outers, holes):
    ana, fea, e = compare(outers, holes)
    assert ana.area > 0 and fea.area > 0, f"{label}: aire nulle"
    # Propriétés géométriques mesh-indépendantes (intégration exacte sur le polygone) :
    # l'accord doit être quasi exact. Tolérance 1e-4 = détecteur sensible (écarts
    # observés ~1e-14) ; un vrai bug (signe, double comptage, formule) donnerait >1 %.
    assert e["A"] < 1e-4, f"{label}: A écart {e['A']:.2e} (ana={ana.area:.3f} fea={fea.area:.3f})"
    assert e["Iy(=Ix)"] < 1e-4, f"{label}: Iy écart {e['Iy(=Ix)']:.2e} (ana={ana.Ix:.1f} fea={fea.Ix:.1f})"
    assert e["Iz(=Iy)"] < 1e-4, f"{label}: Iz écart {e['Iz(=Iy)']:.2e} (ana={ana.Iy:.1f} fea={fea.Iy:.1f})"
    assert e["Iyz(=Ixy)"] < 1e-4, f"{label}: Iyz écart {e['Iyz(=Ixy)']:.2e} (ana={ana.Ixy:.1f} fea={fea.Ixy:.1f})"
    assert e["yc"] < 0.02, f"{label}: yc écart {e['yc']:.3f} mm"
    assert e["zc"] < 0.02, f"{label}: zc écart {e['zc']:.3f} mm"


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    hdr = f"{'section':30s} {'A':>9s} {'Iy':>9s} {'Iz':>9s} {'Iyz':>9s} {'yc':>7s} {'zc':>7s}"
    print(hdr); print("-" * len(hdr))
    worst = 0.0
    for label, outers, holes in CASES:
        try:
            ana, fea, e = compare(outers, holes)
            worst = max(worst, e["A"], e["Iy(=Ix)"], e["Iz(=Iy)"], e["Iyz(=Ixy)"])
            print(f"{label:30s} {e['A']:9.1e} {e['Iy(=Ix)']:9.1e} {e['Iz(=Iy)']:9.1e} "
                  f"{e['Iyz(=Ixy)']:9.1e} {e['yc']:7.3f} {e['zc']:7.3f}")
        except Exception as exc:
            print(f"{label:30s} ERREUR: {exc}")
    print(f"\nÉcart relatif maximal (A/Iy/Iz/Iyz) = {worst:.2e}")

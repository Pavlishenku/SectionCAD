"""
Parametric section generators — return polygon vertex lists in mm.
Convention: CCW = positive area (outer contour), CW = hole.
Origin centered at centroid unless noted.
"""
import math
from typing import List, Tuple

Pts = List[Tuple[float, float]]


def rectangle(b: float, h: float) -> List[Pts]:
    """Solid rectangle. b=width, h=height."""
    hb, hh = b / 2, h / 2
    outer = [(-hb, -hh), (hb, -hh), (hb, hh), (-hb, hh)]
    return [outer]


def circle(d: float, n: int = 64) -> List[Pts]:
    """Solid circle of diameter d."""
    r = d / 2
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return [pts]


def hollow_circle(d_ext: float, d_int: float, n: int = 64) -> List[Pts]:
    """Hollow circular section (tube)."""
    outer = circle(d_ext, n)[0]
    r = d_int / 2
    hole = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
            for i in range(n - 1, -1, -1)]  # CW for hole
    return [outer], [hole]


def i_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """
    I-section (IPE-like, no fillet radius).
    h = total height, b = flange width, tw = web thickness, tf = flange thickness.
    """
    hh = h / 2
    hb = b / 2
    htw = tw / 2
    outer = [
        (-hb, -hh),
        (hb, -hh),
        (hb, -hh + tf),
        (htw, -hh + tf),
        (htw, hh - tf),
        (hb, hh - tf),
        (hb, hh),
        (-hb, hh),
        (-hb, hh - tf),
        (-htw, hh - tf),
        (-htw, -hh + tf),
        (-hb, -hh + tf),
    ]
    return [outer]


def box_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """
    Box / caisson section.
    h = total height, b = total width, tw = web thickness, tf = flange thickness.
    """
    hh = h / 2
    hb = b / 2
    outer = [(-hb, -hh), (hb, -hh), (hb, hh), (-hb, hh)]
    hole = [
        (-(hb - tw), -(hh - tf)),
        (-(hb - tw), hh - tf),
        (hb - tw, hh - tf),
        (hb - tw, -(hh - tf)),
    ]
    return [outer], [hole]


def angle_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """
    L-angle section. Origin at corner.
    h = leg height, b = leg width, tw = vertical leg thickness, tf = horizontal leg thickness.
    """
    outer = [
        (0, 0), (b, 0), (b, tf), (tw, tf), (tw, h), (0, h)
    ]
    # Shift to centroid — approximate
    from calculators.section_properties import _polygon_area_and_centroid
    a, cx, cy = _polygon_area_and_centroid(outer)
    shifted = [(x - cx, y - cy) for x, y in outer]
    return [shifted]


def channel_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """
    UPN / C channel.
    h = total height, b = flange width, tw = web thickness, tf = flange thickness.
    """
    outer = [
        (0, 0), (b, 0), (b, tf),
        (tw, tf), (tw, h - tf), (b, h - tf),
        (b, h), (0, h)
    ]
    from calculators.section_properties import _polygon_area_and_centroid
    a, cx, cy = _polygon_area_and_centroid(outer)
    shifted = [(x - cx, y - cy) for x, y in outer]
    return [shifted]


def t_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """T-section."""
    hb = b / 2
    htw = tw / 2
    outer = [
        (-hb, h - tf), (-hb, h), (hb, h), (hb, h - tf),
        (htw, h - tf), (htw, 0), (-htw, 0), (-htw, h - tf)
    ]
    from calculators.section_properties import _polygon_area_and_centroid
    a, cx, cy = _polygon_area_and_centroid(outer)
    shifted = [(x - cx, y - cy) for x, y in outer]
    return [shifted]


def square_hollow(b: float, t: float) -> List[Pts]:
    """Square hollow section (SHS)."""
    return box_section(b, b, t, t)


def rectangular_hollow(h: float, b: float, t: float) -> List[Pts]:
    """Rectangular hollow section (RHS)."""
    return box_section(h, b, t, t)


def cross_section(h: float, b: float, tw: float, tf: float) -> List[Pts]:
    """
    Cross / plus-shaped section.
    h = total height, b = total width,
    tw = thickness of vertical band, tf = thickness of horizontal band.
    Contour has 12 vertices, centred at centroid (origin).
    """
    hh, hb, htw, htf = h / 2, b / 2, tw / 2, tf / 2
    outer = [
        (-htw, -hh), ( htw, -hh),
        ( htw, -htf), ( hb, -htf),
        ( hb,  htf), ( htw,  htf),
        ( htw,  hh), (-htw,  hh),
        (-htw,  htf), (-hb,  htf),
        (-hb, -htf), (-htw, -htf),
    ]
    return [outer]

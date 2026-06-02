"""
HTML report generator for SectionCAD.
Generates a fully self-contained HTML report (inline CSS + SVG, no external dependencies).
All inputs in mm; display in cm/cm² etc. as defined by results_to_dict().
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Tuple, Optional

from calculators.nomenclature import PROPERTY_DESCRIPTIONS

# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReportOptions:
    # Project info
    title: str = "Rapport de section transversale"
    author: str = ""
    project: str = ""
    date: str = ""          # auto-filled if empty
    notes: str = ""

    # Content toggles
    show_geometry: bool = True          # SVG of the section
    show_dimensions: bool = True        # dimension lines on SVG
    show_centroid: bool = True          # centroid mark + principal axes
    show_coordinates: bool = True       # vertex coordinate table
    show_results_basic: bool = True     # A, P, y_G, z_G
    show_results_inertia: bool = True   # I_y, I_z, I_yz, I_1, I_2, α
    show_results_moduli: bool = True    # W_el,*, W_pl,*
    show_results_gyration: bool = True  # i_y, i_z
    show_results_torsion: bool = True   # I_t, I_w
    show_results_shear: bool = True     # centre de cisaillement, A_v
    show_theory: bool = True            # theory/methods section
    show_mesh: bool = False             # overlay du maillage FEM sur le SVG
    engine_label: str = ""              # moteur de calcul ("analytique" / "FEM ...")


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

def _fmt(v: float, decimals: int = 2) -> str:
    """Format a float for SVG attribute or label."""
    return f"{v:.{decimals}f}"


def _world_to_svg(x: float, y: float,
                  xmin: float, ymin: float,
                  scale: float,
                  margin: float,
                  svg_height: float) -> Tuple[float, float]:
    """Convert world (mm) coordinates to SVG pixel coordinates.
    SVG y-axis points downward, world y-axis points upward.
    """
    px = margin + (x - xmin) * scale
    py = svg_height - margin - (y - ymin) * scale
    return px, py


def _arrow_head(x1: float, y1: float, x2: float, y2: float,
                size: float = 7.0) -> str:
    """Return SVG <polygon> string for a filled arrowhead at (x2, y2)
    pointing from (x1,y1) toward (x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return ""
    ux, uy = dx / length, dy / length
    # perpendicular
    px, py = -uy, ux
    # base of arrowhead
    bx = x2 - ux * size
    by = y2 - uy * size
    pts = (
        f"{_fmt(x2)},{_fmt(y2)} "
        f"{_fmt(bx + px * size * 0.4)},{_fmt(by + py * size * 0.4)} "
        f"{_fmt(bx - px * size * 0.4)},{_fmt(by - py * size * 0.4)}"
    )
    return f'<polygon points="{pts}" fill="#555"/>'


def section_to_svg(outer_polygons: List[List[Tuple[float, float]]],
                   hole_polygons: List[List[Tuple[float, float]]],
                   results,
                   options: ReportOptions,
                   svg_size: int = 500) -> str:
    """
    Generate a complete SVG string representing the cross-section.

    Parameters
    ----------
    outer_polygons : list of polygon vertex lists [(x,y), ...] in mm
    hole_polygons  : list of hole vertex lists [(x,y), ...] in mm
    results        : SectionResults (may be None)
    options        : ReportOptions
    svg_size       : total SVG canvas size in pixels (square)

    Returns
    -------
    str : complete SVG element as a string
    """
    hole_polygons = hole_polygons or []

    # Collect all vertices for bounding box
    all_x: List[float] = []
    all_y: List[float] = []
    for poly in outer_polygons + hole_polygons:
        for (x, y) in poly:
            all_x.append(x)
            all_y.append(y)

    if not all_x:
        # Return a placeholder SVG
        return (
            f'<svg width="{svg_size}" height="{svg_size}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{svg_size//2}" y="{svg_size//2}" '
            f'text-anchor="middle" fill="#999" font-size="14">'
            f'Aucune géométrie</text></svg>'
        )

    xmin_w = min(all_x)
    xmax_w = max(all_x)
    ymin_w = min(all_y)
    ymax_w = max(all_y)
    width_mm = xmax_w - xmin_w
    height_mm = ymax_w - ymin_w

    # Avoid division by zero for degenerate sections
    width_mm = width_mm if width_mm > 1e-9 else 1.0
    height_mm = height_mm if height_mm > 1e-9 else 1.0

    margin = 60.0
    draw_area = svg_size - 2 * margin
    scale = min(draw_area / width_mm, draw_area / height_mm)  # px per mm
    px_per_mm = scale

    # Helper: convert world → SVG pixel
    def w2s(x: float, y: float) -> Tuple[float, float]:
        return _world_to_svg(x, y, xmin_w, ymin_w, scale, margin, svg_size)

    lines: List[str] = []
    lines.append(
        f'<svg width="{svg_size}" height="{svg_size}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#FFFFFF;border:1px solid #ddd;border-radius:4px;">'
    )

    # ------------------------------------------------------------------
    # 1. Light grid (only when px_per_mm > 3)
    # ------------------------------------------------------------------
    if px_per_mm > 3:
        grid_interval = 10.0  # mm
        # vertical lines
        x_start = math.ceil(xmin_w / grid_interval) * grid_interval
        gx = x_start
        while gx <= xmax_w + 1e-9:
            sx, _ = w2s(gx, ymin_w)
            _, sy_top = w2s(gx, ymax_w)
            lines.append(
                f'<line x1="{_fmt(sx)}" y1="{_fmt(margin)}" '
                f'x2="{_fmt(sx)}" y2="{_fmt(svg_size - margin)}" '
                f'stroke="#e8e8e8" stroke-width="0.5"/>'
            )
            gx += grid_interval
        # horizontal lines
        y_start = math.ceil(ymin_w / grid_interval) * grid_interval
        gy = y_start
        while gy <= ymax_w + 1e-9:
            _, sy = w2s(xmin_w, gy)
            lines.append(
                f'<line x1="{_fmt(margin)}" y1="{_fmt(sy)}" '
                f'x2="{_fmt(svg_size - margin)}" y2="{_fmt(sy)}" '
                f'stroke="#e8e8e8" stroke-width="0.5"/>'
            )
            gy += grid_interval

    # ------------------------------------------------------------------
    # 2. Reference axes at world origin (0,0) if visible
    # ------------------------------------------------------------------
    ox, oy = w2s(0.0, 0.0)
    if (margin - 5 <= ox <= svg_size - margin + 5 or
            margin - 5 <= oy <= svg_size - margin + 5):
        # Clip to drawing area
        x_left = margin
        x_right = svg_size - margin
        y_top = margin
        y_bot = svg_size - margin
        # horizontal axis through y=0
        if margin - 5 <= oy <= svg_size - margin + 5:
            lines.append(
                f'<line x1="{_fmt(x_left)}" y1="{_fmt(oy)}" '
                f'x2="{_fmt(x_right)}" y2="{_fmt(oy)}" '
                f'stroke="#aac8e8" stroke-width="1" '
                f'stroke-dasharray="6,4"/>'
            )
        # vertical axis through x=0
        if margin - 5 <= ox <= svg_size - margin + 5:
            lines.append(
                f'<line x1="{_fmt(ox)}" y1="{_fmt(y_top)}" '
                f'x2="{_fmt(ox)}" y2="{_fmt(y_bot)}" '
                f'stroke="#aac8e8" stroke-width="1" '
                f'stroke-dasharray="6,4"/>'
            )

    # ------------------------------------------------------------------
    # 3. Polygons
    # ------------------------------------------------------------------
    def poly_points_str(pts: List[Tuple[float, float]]) -> str:
        parts = []
        for (x, y) in pts:
            px, py = w2s(x, y)
            parts.append(f"{_fmt(px)},{_fmt(py)}")
        return " ".join(parts)

    # Outer polygons
    for poly in outer_polygons:
        if len(poly) < 3:
            continue
        pts_str = poly_points_str(poly)
        lines.append(
            f'<polygon points="{pts_str}" '
            f'fill="rgba(70,130,200,0.25)" '
            f'stroke="#4682C8" stroke-width="2" '
            f'stroke-linejoin="round"/>'
        )

    # Hole polygons
    for poly in hole_polygons:
        if len(poly) < 3:
            continue
        pts_str = poly_points_str(poly)
        lines.append(
            f'<polygon points="{pts_str}" '
            f'fill="rgba(240,100,100,0.15)" '
            f'stroke="#DC3C3C" stroke-width="1.5" '
            f'stroke-linejoin="round"/>'
        )
        # "TROU" label at centroid of hole
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        hcx = sum(xs) / len(xs)
        hcy = sum(ys) / len(ys)
        lx, ly = w2s(hcx, hcy)
        lines.append(
            f'<text x="{_fmt(lx)}" y="{_fmt(ly + 4)}" '
            f'text-anchor="middle" font-size="11" '
            f'fill="#DC3C3C" font-family="Arial,sans-serif" '
            f'font-weight="bold">TROU</text>'
        )

    # ------------------------------------------------------------------
    # 3b. FEA mesh overlay (si demandé et disponible dans les résultats)
    # ------------------------------------------------------------------
    mesh_verts = getattr(results, "mesh_vertices", None) if results is not None else None
    mesh_tris = getattr(results, "mesh_triangles", None) if results is not None else None
    if options.show_mesh and mesh_verts and mesh_tris:
        nv = len(mesh_verts)
        for tri in mesh_tris:
            i, j, k = tri[0], tri[1], tri[2]
            if i >= nv or j >= nv or k >= nv:
                continue
            ax, ay = w2s(mesh_verts[i][0], mesh_verts[i][1])
            bx, by = w2s(mesh_verts[j][0], mesh_verts[j][1])
            cxx, cyy = w2s(mesh_verts[k][0], mesh_verts[k][1])
            lines.append(
                f'<polygon points="{_fmt(ax)},{_fmt(ay)} '
                f'{_fmt(bx)},{_fmt(by)} {_fmt(cxx)},{_fmt(cyy)}" '
                f'fill="none" stroke="#999" stroke-width="0.4"/>'
            )

    # ------------------------------------------------------------------
    # 4. Vertex dots
    # ------------------------------------------------------------------
    for poly in outer_polygons:
        for (x, y) in poly:
            px, py = w2s(x, y)
            lines.append(
                f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="3" '
                f'fill="#4682C8" stroke="white" stroke-width="1"/>'
            )

    for poly in hole_polygons:
        for (x, y) in poly:
            px, py = w2s(x, y)
            lines.append(
                f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="3" '
                f'fill="#DC3C3C" stroke="white" stroke-width="1"/>'
            )

    # ------------------------------------------------------------------
    # 5. Centroid + principal axes
    # ------------------------------------------------------------------
    if options.show_centroid and results is not None:
        gcx, gcy = w2s(results.xc, results.yc)
        arm = min(width_mm, height_mm) / 2.0 * scale  # px

        # Principal axis 1 (angle theta_p from x-axis)
        theta_rad = math.radians(results.theta_p)
        cos_t = math.cos(theta_rad)
        sin_t = math.sin(theta_rad)

        # Axis 1 (I1, red): direction (cos_t, sin_t) in world → SVG y inverted
        ax1_dx = cos_t * arm
        ax1_dy = -sin_t * arm   # negate because SVG y is flipped
        lines.append(
            f'<line x1="{_fmt(gcx - ax1_dx)}" y1="{_fmt(gcy + ax1_dy)}" '
            f'x2="{_fmt(gcx + ax1_dx)}" y2="{_fmt(gcy - ax1_dy)}" '
            f'stroke="#CC0000" stroke-width="1.2" stroke-dasharray="8,4"/>'
        )

        # Axis 2 (I2, blue): perpendicular to axis 1
        ax2_dx = -sin_t * arm
        ax2_dy = -cos_t * arm
        lines.append(
            f'<line x1="{_fmt(gcx - ax2_dx)}" y1="{_fmt(gcy + ax2_dy)}" '
            f'x2="{_fmt(gcx + ax2_dx)}" y2="{_fmt(gcy - ax2_dy)}" '
            f'stroke="#2266CC" stroke-width="1.2" stroke-dasharray="8,4"/>'
        )

        # Centroid cross (12 px arms)
        cs = 12
        lines.append(
            f'<line x1="{_fmt(gcx - cs)}" y1="{_fmt(gcy)}" '
            f'x2="{_fmt(gcx + cs)}" y2="{_fmt(gcy)}" '
            f'stroke="#CC0000" stroke-width="2"/>'
        )
        lines.append(
            f'<line x1="{_fmt(gcx)}" y1="{_fmt(gcy - cs)}" '
            f'x2="{_fmt(gcx)}" y2="{_fmt(gcy + cs)}" '
            f'stroke="#CC0000" stroke-width="2"/>'
        )
        # Centroid circle
        lines.append(
            f'<circle cx="{_fmt(gcx)}" cy="{_fmt(gcy)}" r="4" '
            f'fill="none" stroke="#CC0000" stroke-width="1.5"/>'
        )
        # Label "G"
        lines.append(
            f'<text x="{_fmt(gcx + 8)}" y="{_fmt(gcy - 8)}" '
            f'font-size="13" fill="#CC0000" '
            f'font-family="Arial,sans-serif" font-weight="bold">G</text>'
        )

    # ------------------------------------------------------------------
    # 6. Dimension lines
    # ------------------------------------------------------------------
    if options.show_dimensions:
        # Horizontal dimension (total width) — below the section
        y_dim_bot = svg_size - margin + 28   # px, below drawing area
        x_left_dim, _ = w2s(xmin_w, ymin_w)
        x_right_dim, _ = w2s(xmax_w, ymin_w)
        # Extension lines
        _, y_bot_px = w2s(xmin_w, ymin_w)
        lines.append(
            f'<line x1="{_fmt(x_left_dim)}" y1="{_fmt(y_bot_px + 4)}" '
            f'x2="{_fmt(x_left_dim)}" y2="{_fmt(y_dim_bot + 4)}" '
            f'stroke="#555" stroke-width="0.8"/>'
        )
        lines.append(
            f'<line x1="{_fmt(x_right_dim)}" y1="{_fmt(y_bot_px + 4)}" '
            f'x2="{_fmt(x_right_dim)}" y2="{_fmt(y_dim_bot + 4)}" '
            f'stroke="#555" stroke-width="0.8"/>'
        )
        # Main dimension line
        lines.append(
            f'<line x1="{_fmt(x_left_dim)}" y1="{_fmt(y_dim_bot)}" '
            f'x2="{_fmt(x_right_dim)}" y2="{_fmt(y_dim_bot)}" '
            f'stroke="#555" stroke-width="1"/>'
        )
        # Arrowheads
        lines.append(_arrow_head(x_right_dim, y_dim_bot, x_left_dim, y_dim_bot))
        lines.append(_arrow_head(x_left_dim, y_dim_bot, x_right_dim, y_dim_bot))
        # Label
        mid_x = (x_left_dim + x_right_dim) / 2
        lines.append(
            f'<text x="{_fmt(mid_x)}" y="{_fmt(y_dim_bot + 14)}" '
            f'text-anchor="middle" font-size="11" fill="#333" '
            f'font-family="Arial,sans-serif">{width_mm:.1f} mm</text>'
        )

        # Vertical dimension (total height) — to the right of the section
        x_dim_right = svg_size - margin + 28  # px, right of drawing area
        _, y_top_px = w2s(xmin_w, ymax_w)
        _, y_bot_px2 = w2s(xmin_w, ymin_w)
        x_right_px2, _ = w2s(xmax_w, ymin_w)
        # Extension lines
        lines.append(
            f'<line x1="{_fmt(x_right_px2 + 4)}" y1="{_fmt(y_top_px)}" '
            f'x2="{_fmt(x_dim_right + 4)}" y2="{_fmt(y_top_px)}" '
            f'stroke="#555" stroke-width="0.8"/>'
        )
        lines.append(
            f'<line x1="{_fmt(x_right_px2 + 4)}" y1="{_fmt(y_bot_px2)}" '
            f'x2="{_fmt(x_dim_right + 4)}" y2="{_fmt(y_bot_px2)}" '
            f'stroke="#555" stroke-width="0.8"/>'
        )
        # Main dimension line
        lines.append(
            f'<line x1="{_fmt(x_dim_right)}" y1="{_fmt(y_top_px)}" '
            f'x2="{_fmt(x_dim_right)}" y2="{_fmt(y_bot_px2)}" '
            f'stroke="#555" stroke-width="1"/>'
        )
        # Arrowheads
        lines.append(_arrow_head(x_dim_right, y_bot_px2, x_dim_right, y_top_px))
        lines.append(_arrow_head(x_dim_right, y_top_px, x_dim_right, y_bot_px2))
        # Label (rotated 90°)
        mid_y = (y_top_px + y_bot_px2) / 2
        lines.append(
            f'<text x="{_fmt(x_dim_right + 16)}" y="{_fmt(mid_y)}" '
            f'text-anchor="middle" font-size="11" fill="#333" '
            f'font-family="Arial,sans-serif" '
            f'transform="rotate(-90 {_fmt(x_dim_right + 16)} {_fmt(mid_y)})">'
            f'{height_mm:.1f} mm</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
    color: #222;
    line-height: 1.5;
}
h1 {
    color: #1a3a5c;
    border-bottom: 3px solid #4682C8;
    padding-bottom: 8px;
    margin-bottom: 16px;
}
h2 {
    color: #2a5a8c;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-top: 30px;
    margin-bottom: 14px;
}
.meta-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
    background: #f8f9fc;
}
.meta-table td {
    padding: 6px 10px;
    border: 1px solid #ddd;
}
.meta-table td:first-child {
    font-weight: bold;
    width: 140px;
    color: #555;
}
.results-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    margin-bottom: 20px;
}
.results-table th {
    background: #1a3a5c;
    color: white;
    padding: 8px;
    text-align: left;
}
.results-table td {
    padding: 6px 8px;
    border-bottom: 1px solid #eee;
}
.results-table tr:nth-child(even) td {
    background: #f5f7fa;
}
.results-table td:last-child {
    text-align: right;
    font-family: 'Courier New', monospace;
}
.results-table td:nth-child(2) {
    text-align: right;
    font-family: 'Courier New', monospace;
    font-weight: bold;
}
.group-header td {
    font-weight: bold;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 4px 8px;
    color: white;
}
.group-basic td   { background: #2a6a9a !important; }
.group-inertia td { background: #7a4a10 !important; }
.group-moduli td  { background: #5a3a8a !important; }
.group-gyration td{ background: #2a6a5a !important; }
.group-torsion td { background: #8a7a10 !important; }
.group-shear td   { background: #6a2a4a !important; }
.theory {
    background: #f8f9fc;
    border-left: 4px solid #4682C8;
    padding: 15px 20px;
    border-radius: 4px;
    margin-bottom: 20px;
}
.theory h3 {
    color: #2a5a8c;
    margin-top: 18px;
    margin-bottom: 6px;
}
.formula {
    font-family: 'Courier New', monospace;
    background: #fff;
    border: 1px solid #ddd;
    padding: 8px 12px;
    border-radius: 3px;
    margin: 6px 0;
    display: block;
    font-size: 13px;
    white-space: pre;
}
.coord-table {
    border-collapse: collapse;
    font-size: 13px;
    margin-bottom: 20px;
}
.coord-table th,
.coord-table td {
    padding: 5px 14px;
    border: 1px solid #ddd;
    text-align: right;
}
.coord-table th {
    background: #2a5a8c;
    color: white;
    text-align: center;
}
.coord-table td:first-child {
    text-align: center;
    color: #555;
}
.svg-container {
    text-align: center;
    margin: 20px 0;
}
.warning {
    color: #a06000;
    background: #fff8e0;
    border: 1px solid #f0c060;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 13px;
    margin: 10px 0;
}
.section-label {
    font-size: 12px;
    color: #888;
    margin-bottom: 4px;
}
.print-btn {
    position: fixed;
    top: 16px;
    right: 20px;
    background: #1a3a5c;
    color: white;
    border: none;
    padding: 8px 18px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    z-index: 100;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    font-family: 'Segoe UI', Arial, sans-serif;
}
.print-btn:hover { background: #2a5a8c; }
@media print {
    body { max-width: 100%; }
    h1, h2 { page-break-after: avoid; }
    .theory { border-left: 4px solid #4682C8; }
    .print-btn { display: none; }
}
footer {
    margin-top: 40px;
    font-size: 12px;
    color: #888;
    text-align: center;
    border-top: 1px solid #eee;
    padding-top: 10px;
}
"""


# ---------------------------------------------------------------------------
# Results table rows configuration
# ---------------------------------------------------------------------------

# Symboles Eurocode (clés de results_to_dict()), groupés par catégorie
_RESULT_GROUPS = [
    ("Géométrie de base", "group-basic", [
        "A", "y_G", "z_G",
    ]),
    ("Moments d'inertie centroïdaux", "group-inertia", [
        "I_y", "I_z", "I_yz", "I_1", "I_2", "α",
    ]),
    ("Modules élastiques", "group-moduli", [
        "W_el,y,sup", "W_el,y,inf", "W_el,z,g", "W_el,z,d",
        "W_pl,y", "W_pl,z",
    ]),
    ("Rayons de giration", "group-gyration", [
        "i_y", "i_z",
    ]),
    ("Torsion / gauchissement", "group-torsion", [
        "I_t", "I_w",
    ]),
    ("Cisaillement", "group-shear", [
        "y_SC", "z_SC", "A_vy", "A_vz",
    ]),
]

# Map group name → toggle option attribute
_GROUP_TOGGLE = {
    "Géométrie de base": "show_results_basic",
    "Moments d'inertie centroïdaux": "show_results_inertia",
    "Modules élastiques": "show_results_moduli",
    "Rayons de giration": "show_results_gyration",
    "Torsion / gauchissement": "show_results_torsion",
    "Cisaillement": "show_results_shear",
}


# ---------------------------------------------------------------------------
# Theory section HTML
# ---------------------------------------------------------------------------

def _theory_html() -> str:
    return """
<div class="theory">

  <h3>1. Aire et centroïde — Formule de Gauss (shoelace)</h3>
  <p>Pour un polygone à n sommets (x<sub>i</sub>, y<sub>i</sub>) :</p>
  <code class="formula">A = ½ |Σ(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)|</code>
  <code class="formula">xc = (1/6A) · Σ(xᵢ + xᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
yc = (1/6A) · Σ(yᵢ + yᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)</code>
  <p>Pour les sections composites (avec trous), les contributions des trous sont soustraites
  en changeant le signe de leur aire.</p>

  <h3>2. Moments d'inertie — Intégration polygonale (théorème de Green)</h3>
  <code class="formula">Ix = (1/12) · Σ (yᵢ² + yᵢ·yᵢ₊₁ + yᵢ₊₁²) · (xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
Iy = (1/12) · Σ (xᵢ² + xᵢ·xᵢ₊₁ + xᵢ₊₁²) · (xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)</code>
  <p>Les moments sont calculés directement par rapport au centroïde global.
  Pour les sections composites, le théorème de Huygens-Steiner (axes parallèles) est appliqué :
  <code class="formula">I_total = Σ (Iᵢ,centroïdal + Aᵢ · dᵢ²)</code>
  où dᵢ est la distance entre le centroïde partiel i et le centroïde global.</p>

  <h3>3. Axes principaux — Transformation de Mohr</h3>
  <code class="formula">I₁,₂ = (Ix + Iy)/2  ±  √[ ((Ix − Iy)/2)² + Ixy² ]
θp   = ½ · arctan(−2·Ixy / (Ix − Iy))</code>
  <p>I₁ est le moment maximal (axe principal fort), I₂ le moment minimal.
  θp est l'angle (en degrés) entre l'axe x centroïdal et l'axe principal 1.</p>

  <h3>4. Modules élastiques</h3>
  <code class="formula">Sel,y,sup = Ix / (ymax − yc)      (fibre comprimée supérieure)
Sel,y,inf = Ix / (yc − ymin)      (fibre tendue inférieure)
Sel,z,d   = Iy / (xmax − xc)
Sel,z,g   = Iy / (xc − xmin)</code>

  <h3>5. Module plastique — Axe neutre plastique (PNA) par bisection</h3>
  <p>Le PNA divise la section en deux sous-aires égales (A/2 chacune).
  Il est localisé par recherche dichotomique en 50 itérations.</p>
  <code class="formula">Zx = Q_sup + Q_inf
   = Σ |Aᵢ · (ȳᵢ − y_PNA)|  (de part et d'autre du PNA)</code>

  <h3>6. Torsion de Saint-Venant — Stratégie de calcul</h3>
  <p>La constante de torsion J est calculée selon la nature de la section :</p>

  <h4>6a. Formules analytiques exactes</h4>
  <p><strong>Cercle plein / CHS (tube circulaire creux) :</strong></p>
  <code class="formula">J = π d⁴ / 32          (plein)
J = π (d_ext⁴ − d_int⁴) / 32    (CHS)</code>
  <p><strong>Rectangle — formule de Timoshenko :</strong></p>
  <code class="formula">J = a·t³/3 · (1 − 0.630·r + 0.052·r⁵)     r = t/a  (t ≤ a)</code>
  <p><strong>Section creuse rectangulaire — formule de Bredt (Batho) :</strong></p>
  <code class="formula">J = 4·Am² / ∮(ds/t)
Am = aire enfermée par la ligne médiane de la paroi</code>

  <h4>6b. Formules parois minces (~±30 %)</h4>
  <p>Pour les profilés ouverts à parois minces (I, U, T, cornières) :</p>
  <code class="formula">J ≈ (1/3) · Σ bᵢ · tᵢ³    (Timoshenko, parois minces)</code>
  <p>Précision : ±30 % par rapport aux valeurs de catalogue, car les congés de raccordement
  (fillet radius) — non modélisés dans les polygones — augmentent J de 20 à 40 %.</p>

  <h4>6c. Différences finies (FDM) — sections libres et sections avec trous</h4>
  <p>Pour les sections dessinées librement ou non reconnues, J est calculé par la méthode
  des <strong>Différences Finies (FDM)</strong> sur la fonction de contrainte de Prandtl φ :</p>
  <code class="formula">∇²φ = −2  dans Ω  (intérieur de la section)
φ = 0      sur ∂Ω_ext  (contour extérieur)
φ = cₖ    sur ∂Ωₖ  (bord du trou k, cₖ inconnu)

J = 2 h² · Σ φᵢ  +  2 · Σₖ cₖ · Aₖ</code>
  <p>Les constantes cₖ sont déterminées par la condition de compatibilité (unicité de la
  fonction de gauchissement) :</p>
  <code class="formula">∮_{Γₖ} ∂φ/∂n ds = +2 Aₖ</code>
  <p>La résolution utilise un système creux assemblé via <code>scipy.sparse</code> et résolu
  par <code>spsolve</code>. Précision typique : ~3 % (sections pleines / tubes),
  ~5-8 % (parois minces sans congés).</p>

  <h4>6d. Constante de gauchissement Cw</h4>
  <p>Pour les sections paramétriques connues, Cw est calculé analytiquement
  (Timoshenko–Galambos). Pour les sections libres, Cw est approché via la méthode
  des Éléments de Frontière (BEM) — résolution de l'équation de Neumann pour la
  fonction de gauchissement ω.</p>
  <p><em>Références : Pilkey W.D. (2002) ; Timoshenko &amp; Goodier (1970) ;
  Sadd M.H. (2005) ; Bredt R. (1896).</em></p>

</div>
"""


# ---------------------------------------------------------------------------
# Main HTML generator
# ---------------------------------------------------------------------------

def generate_html_report(options: ReportOptions,
                         outer_polygons: List[List[Tuple[float, float]]],
                         hole_polygons: List[List[Tuple[float, float]]],
                         results,
                         results_dict: dict) -> str:
    """
    Build and return a complete, self-contained HTML report string.

    Parameters
    ----------
    options        : ReportOptions
    outer_polygons : list of polygon vertex lists in mm
    hole_polygons  : list of hole vertex lists in mm
    results        : SectionResults instance (may be None)
    results_dict   : dict from results_to_dict() — {label: (value_str, unit)}

    Returns
    -------
    str : full HTML document
    """
    hole_polygons = hole_polygons or []
    report_date = options.date if options.date else date.today().strftime("%d/%m/%Y")

    parts: List[str] = []

    # ------------------------------------------------------------------
    # DOCTYPE + head
    # ------------------------------------------------------------------
    parts.append(f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(options.title)}</title>
  <style>
{_CSS}
  </style>
</head>
<body>
<button class="print-btn" onclick="window.print()" title="Imprimer ou enregistrer en PDF">&#128438; Imprimer / PDF</button>""")

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    parts.append(f'<h1>{_esc(options.title)}</h1>')

    # Meta table
    meta_rows = [
        ("Projet", options.project),
        ("Auteur", options.author),
        ("Date", report_date),
    ]
    if options.engine_label:
        meta_rows.append(("Moteur de calcul", options.engine_label))
    if options.notes:
        meta_rows.append(("Notes", options.notes))

    parts.append('<table class="meta-table"><tbody>')
    for label, value in meta_rows:
        if value:
            parts.append(
                f'<tr><td>{_esc(label)}</td>'
                f'<td>{_esc(value)}</td></tr>'
            )
    parts.append('</tbody></table>')

    # ------------------------------------------------------------------
    # Geometry SVG
    # ------------------------------------------------------------------
    if options.show_geometry:
        parts.append('<section>')
        parts.append('<h2>Géométrie de la section</h2>')
        parts.append('<div class="svg-container">')
        svg_str = section_to_svg(
            outer_polygons, hole_polygons, results, options, svg_size=500
        )
        parts.append(svg_str)
        parts.append('</div>')

        # Legend
        legend_items = []
        legend_items.append(
            '<span style="display:inline-block;width:14px;height:14px;'
            'background:rgba(70,130,200,0.25);border:2px solid #4682C8;'
            'margin-right:5px;vertical-align:middle;"></span>'
            '<span style="font-size:12px;margin-right:16px;">Matière</span>'
        )
        if hole_polygons:
            legend_items.append(
                '<span style="display:inline-block;width:14px;height:14px;'
                'background:rgba(240,100,100,0.15);border:2px solid #DC3C3C;'
                'margin-right:5px;vertical-align:middle;"></span>'
                '<span style="font-size:12px;margin-right:16px;">Trou</span>'
            )
        if options.show_centroid and results is not None:
            legend_items.append(
                '<span style="color:#CC0000;font-weight:bold;font-size:13px;'
                'margin-right:4px;">&#215;</span>'
                '<span style="font-size:12px;margin-right:16px;">Centroïde G</span>'
            )
            legend_items.append(
                '<span style="display:inline-block;width:24px;height:2px;'
                'background:#CC0000;border-top:2px dashed #CC0000;'
                'margin-right:5px;vertical-align:middle;"></span>'
                '<span style="font-size:12px;margin-right:16px;">Axe principal 1 (I₁)</span>'
            )
            legend_items.append(
                '<span style="display:inline-block;width:24px;height:2px;'
                'border-top:2px dashed #2266CC;'
                'margin-right:5px;vertical-align:middle;"></span>'
                '<span style="font-size:12px;">Axe principal 2 (I₂)</span>'
            )
        parts.append(
            '<p style="text-align:center;margin-top:8px;">'
            + "".join(legend_items)
            + "</p>"
        )
        parts.append('</section>')

    # ------------------------------------------------------------------
    # Vertex coordinates
    # ------------------------------------------------------------------
    if options.show_coordinates:
        parts.append('<section>')
        parts.append('<h2>Coordonnées des sommets</h2>')

        poly_idx = 0
        for poly in outer_polygons:
            poly_idx += 1
            parts.append(
                f'<p class="section-label">Polygone extérieur {poly_idx}</p>'
            )
            parts.append(_coord_table_html(poly))

        for h_idx, poly in enumerate(hole_polygons, 1):
            parts.append(
                f'<p class="section-label">Trou {h_idx}</p>'
            )
            parts.append(_coord_table_html(poly))

        parts.append('</section>')

    # ------------------------------------------------------------------
    # Results table
    # ------------------------------------------------------------------
    any_result_shown = any([
        options.show_results_basic,
        options.show_results_inertia,
        options.show_results_moduli,
        options.show_results_gyration,
        options.show_results_torsion,
        options.show_results_shear,
    ])

    if any_result_shown and results_dict:
        parts.append('<section>')
        parts.append('<h2>Propriétés géométriques de la section</h2>')
        parts.append(
            '<table class="results-table">'
            '<thead><tr>'
            '<th>Symbole</th><th>Désignation</th><th>Valeur</th><th>Unité</th>'
            '</tr></thead>'
            '<tbody>'
        )

        for group_name, group_css, keys in _RESULT_GROUPS:
            toggle_attr = _GROUP_TOGGLE.get(group_name, "")
            if toggle_attr and not getattr(options, toggle_attr, True):
                continue

            # Group header row
            parts.append(
                f'<tr class="group-header {group_css}">'
                f'<td colspan="4">{_esc(group_name)}</td>'
                f'</tr>'
            )

            for key in keys:
                if key not in results_dict:
                    continue
                value_str, unit = results_dict[key]
                desc = PROPERTY_DESCRIPTIONS.get(key, "")
                parts.append(
                    f'<tr>'
                    f'<td>{_esc(key)}</td>'
                    f'<td>{_esc(desc)}</td>'
                    f'<td>{_esc(value_str)}</td>'
                    f'<td>{_esc(unit)}</td>'
                    f'</tr>'
                )

        parts.append('</tbody></table>')
        parts.append('</section>')

    # ------------------------------------------------------------------
    # Theory
    # ------------------------------------------------------------------
    if options.show_theory:
        parts.append('<section>')
        parts.append('<h2>Méthodes de calcul</h2>')
        parts.append(_theory_html())
        parts.append('</section>')

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    parts.append(
        f'<footer>Généré par SectionCAD — {_esc(report_date)}</footer>'
    )
    parts.append('</body>\n</html>')

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Minimal HTML escaping for text content."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _coord_table_html(pts: List[Tuple[float, float]]) -> str:
    """Return an HTML table of vertex coordinates."""
    rows = ['<table class="coord-table">',
            '<thead><tr><th>#</th><th>x (mm)</th><th>y (mm)</th></tr></thead>',
            '<tbody>']
    for i, (x, y) in enumerate(pts, 1):
        rows.append(
            f'<tr><td>{i}</td>'
            f'<td>{x:.3f}</td>'
            f'<td>{y:.3f}</td></tr>'
        )
    rows.append('</tbody></table>')
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_report(options: ReportOptions,
                  outer_polygons: List[List[Tuple[float, float]]],
                  hole_polygons: List[List[Tuple[float, float]]],
                  results,
                  results_dict: dict,
                  filepath: str) -> None:
    """
    Generate and save the HTML report to *filepath*.

    Parameters
    ----------
    options        : ReportOptions — title, author, project, toggles …
    outer_polygons : list of polygon vertex lists (mm)
    hole_polygons  : list of hole vertex lists (mm)
    results        : SectionResults (may be None if not yet computed)
    results_dict   : dict returned by results_to_dict()
    filepath       : destination path, e.g. "/home/user/report.html"
    """
    html = generate_html_report(
        options, outer_polygons, hole_polygons, results, results_dict
    )
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

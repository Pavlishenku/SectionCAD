# SectionCAD

Desktop application for computing the geometric properties of arbitrary cross-sections.
Built with Python 3.10+ (PyQt6, NumPy, SciPy, sectionproperties, Shapely).

The French [README.md](README.md) is the authoritative version; this English file is a translation.

> Status: pre-release (v0).
> This software has not been validated against a recognised structural design standard.
> Do not use the computed results as the sole basis for a structural design decision without
> independent verification.

## ⬇️ Download (Windows 10/11)

**[Download the latest version »](https://github.com/Pavlishenku/SectionCAD/releases/latest)** — get `SectionCAD-portable.zip`, extract it anywhere (Desktop, USB drive) and run `SectionCAD.exe`. **No installation, no administrator rights.**

---

## Requirements and installation

Python ≥ 3.10, then:

```
pip install -r requirements.txt
python main.py
```

Dependencies (`requirements.txt`):

- PyQt6 — graphical interface
- numpy, scipy — numerical computing
- sectionproperties ≥ 3.0 — finite-element analysis (J, Cw, shear centre, shear areas)
- shapely ≥ 2.0 — geometry preparation (union/difference of contours)

---

## Quick start

1. Draw or generate a section (tabs "Dessin", "Paramétrique", "Catalogue"), or open a bundled
   example: File → Ouvrir un exemple.
2. Click "Calculer (analytique)" for fast geometric properties, or "Calculer (FEA)" for the
   finite-element analysis (J, Cw, shear centre, etc.).
3. If you change the geometry, the results become stale (greyed out): re-run a calculation.
4. Export to CSV, copy to the clipboard, generate an HTML report, or produce an A4-landscape
   archive "fiche" (datasheet, PYTHAGORE style).

To draw a hole (or a polygon inside another), use Shift+click — or the "Nouveau contour / trou"
button — otherwise a click selects the existing polygon. Then close with Enter (contour) or the
H key (hole).

---

## Features

### Section geometry

A section is defined by one or more closed polygons, in millimetres, with hole support (Boolean
subtraction). Input methods:

- Freehand drawing on the canvas (snap-to-grid, vertex dragging).
- Exact coordinate entry (Ctrl+click) or tabular entry (Ctrl+I).
- Parametric generators: rectangle, circle, hollow circle, I-section, box, angle, channel (U),
  T-section, cross, square hollow, rectangular hollow.
- European catalogue: IPE, HEA, HEB, HEM, UPN, equal-leg angles, CHS (EN 10210), RHS, SHS.
- Example library (File → Ouvrir un exemple): ready-made `.scad` sections derived from the
  sectionproperties example notebooks (channels with fillets, tapered-flange channel, Z-section,
  circular arc, trapezoid, merged double-I, etc.). See the [`exemples/`](exemples/) folder.

### Calculation model: on demand

Nothing is computed automatically while you draw. The right-hand panel has two buttons:

- "Calculer (analytique)" — fast analytical engine (Green's theorem for A, I, centroid; FDM for the
  torsion constant of freehand sections).
- "Calculer (FEA — sectionproperties)" — finite-element analysis (see below).

Staleness: as soon as the geometry changes (vertex drag, polygon move or delete, paste, undo/redo,
contour/hole toggle, coordinate entry, parametric/catalogue/example load), the displayed results are
greyed out and a banner marks them obsolete; the canvas overlay (centroid, principal axes, shear
centre, mesh) is removed. Re-run a calculation to refresh. View-only actions (zoom, pan, grid, snap,
theme, selection) never invalidate the results.

### Computed properties — Eurocode nomenclature

Eurocode axis convention (EN 1993): y-y is the strong (horizontal) axis, z-z the weak (vertical) axis.
The panel shows the symbol only; the full description appears as a hover tooltip (and as a
"Désignation" column in the CSV and the report). Symbols and descriptions are centralised in
`calculators/nomenclature.py`.

| Symbol | Property | Method | Note |
|---|---|---|---|
| A | Area | Green's theorem | Exact for polygons |
| y_G, z_G | Centroid | Green's theorem | Exact |
| I_y, I_z, I_yz | Second moments of area (centroidal) | Polygon integration | Exact; I_y = strong axis |
| I_1, I_2, α | Principal moments / axis angle | Mohr's circle | Exact |
| W_el,y, W_el,z | Elastic section moduli | I / extreme-fibre distance | Exact |
| W_pl,y, W_pl,z | Plastic section moduli | Bisection on the plastic neutral axis | Exact to discretisation |
| i_y, i_z | Radii of gyration | √(I/A) | Exact |
| I_t | Torsion constant (St-Venant) | analytical (known types) / FDM / FEM | see below |
| I_w | Warping constant | FEM only (sectionproperties) | not computed analytically |
| y_SC, z_SC | Shear centre | analytical (I/U/L/T) or FEM | approximate analytically for general sections |
| A_vy, A_vz | Shear areas | FEM only | — |

Geometry normalisation (shared by both engines): contours and holes are first combined into the true
material region (`calculators/geometry_prep.py`, via Shapely) — solids unioned and holes subtracted
from largest to smallest, so nesting is respected and overlapping/nested contours are not
double-counted (the innermost/smallest polygon containing a point wins; a solid island inside a hole
is kept). Both the analytical and FEM engines consume this same region, so they agree by construction
(machine-precision agreement on A, I_y, I_z).

### Torsion and warping

Torsion is a delicate topic: accuracy depends strongly on the section type and the method used.

St-Venant torsion constant I_t:

| Section type | Method | Expected error |
|---|---|---|
| Solid circle | Exact: I_t = π·D⁴/32 | Exact |
| CHS (circular hollow section) | Exact: π(D₀⁴ − Dᵢ⁴)/32 | Exact |
| Solid rectangle | Timoshenko series | < 1 % for common aspect ratios |
| Closed box / RHS / SHS | Bredt formula 4·A²/∮(ds/t) | Exact for uniform thin walls |
| Open thin-wall sections (I, U, T, L) | Σ b·t³/3 | ±30 %; fillets and welds ignored |
| Arbitrary / freehand sections | FDM (Prandtl stress function, ~150-cell grid) | 3–8 % for simple shapes |

Warning: for open thin-wall sections a ±30 % error is realistic. Other than circles and CHS, treat
analytical I_t as an order-of-magnitude estimate — or use the FEM engine.

Warping constant I_w (Cw) — FEM only: it is no longer computed by the analytical engine (its BEM
solver was unreliable for general sections). It is provided only by the FEM engine
(sectionproperties), which is validated (IPE 300: I_w = 125 800 cm⁶ vs catalogue 125 900 cm⁶, < 0.1 %).

### Finite-element analysis (sectionproperties)

The "Calculer (FEA)" button runs a finite-element analysis (triangular mesh + warping solver) via the
[sectionproperties](https://github.com/robbievanleeuwen/section-properties) package. This is the
recommended way to obtain accurate values of J, Cw, shear centre and shear areas, for any geometry,
including freehand ones.

- Runs in a background thread, so the UI never freezes (warping takes ~0.1–2 s depending on mesh
  density). A result is discarded if the geometry changed while it was running.
- Selectable mesh density (Grossier / Moyen / Fin); the element count is shown. A finer mesh converges
  but is slower; J and Cw are typically stable to < 2 % between densities. Changing the density marks
  the displayed FEM results obsolete.
- Mesh visualisation: tick "Afficher le maillage FEM" to overlay the mesh on the section.
- Holes are handled automatically with nesting respected (contour → hole → solid island → hole inside
  the island, etc.).
- Disjoint sections (several disconnected regions, including a solid island floating inside a hole):
  geometric and plastic properties are computed, but warping (J, Cw, shear centre) is not — a warning
  is shown — because warping requires a single connected region.

CSV export, "Copier" and the HTML report reflect whichever results are currently displayed (analytical
or FEM). The HTML report states which calculation engine was used and, for FEM results, offers an
optional mesh overlay.

---

## Output

- Results panel: Eurocode symbols with hover descriptions; rows colour-grouped, greyed out when the
  geometry changes.
- CSV export / Copy: symbol, full description, value and unit.
- HTML report: self-contained file (SVG geometry, optional FEM mesh, symbol + description table, theory
  section, calculation-engine label); printable to PDF from a browser.
- Fiche (datasheet): self-contained, A4-landscape archive HTML in a monospace font framed by a thin
  black border, styled after the PYTHAGORE "section characteristics" datasheets. Uses the Z (horizontal)
  / Y (vertical) axis convention; a "Repère | Initial | Principal" table (second moments, shear areas,
  coordinates of the notable points P/G/C, Itors, Iw, Section), a clean vector drawing of the section
  (black wireframe outline, red principal axes centred on the centroid G, blue Y arrow, glyphs P blue
  triangle / G red circle / C green square), and a footer (DZ, DY, scale). File menu → "Exporter
  fiche..." (Ctrl+Shift+R) or the "Fiche" toolbar button; a dialog offers editable fields (module,
  number, designation, type/location, title) and an option to show the KY/KZ factors. Preview and
  print-to-PDF via `window.print()` from a browser. The SVG is sized in physical millimetres so the
  printed scale is true at 100 %.
- Project save/load: `.scad` format (JSON) preserving polygon geometry.

---

## File formats

| Extension | Description |
|---|---|
| `.scad` | Project file — JSON containing polygon vertices and grid settings |
| `.csv` | Section-properties export |
| `.html` | Self-contained calculation report, or A4-landscape archive fiche (PYTHAGORE style) |

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Enter / double-click | Close the current polygon as a contour |
| H | Close the current polygon as a hole |
| Shift+click | Start a new polygon: places the first point even inside an existing polygon (to draw a hole). Same as the "Nouveau contour / trou" button. |
| Escape | Cancel the current polygon / deselect |
| Ctrl+Z / Ctrl+Y | Undo / Redo (100 levels) |
| Ctrl+C | Copy the selected polygon |
| Ctrl+V | Paste (ghost preview, click to place) |
| Delete | Delete the selected polygon (or clear all if none is selected) |
| Ctrl+click | Enter exact coordinates |
| Ctrl+I | Tabular coordinate input |
| Ctrl+D | Toggle dark theme |
| Ctrl+O / Ctrl+S | Open / Save project |
| Ctrl+R | Export an HTML report |
| Ctrl+Shift+R | Export an archive fiche (A4 landscape) |
| F | Fit view to geometry |
| Wheel / middle-drag | Zoom / pan |
| G | Toggle snap-to-grid |

The grid stays visible at any zoom level: its step adapts automatically (multiples of 10).

---

## Tests

```
pytest tests/
```

156 tests: analytical section properties (reference values), FEM backend (sectionproperties),
FEM/analytical cross-checks on A, I_y, I_z over a broad case base, FDM torsion solver, geometry
normalisation (overlap / nesting / islands), and the adaptive canvas grid.

---

## Known limitations

Analytical engine (button "Calculer (analytique)"):

- I_t is exact only for circle, CHS, solid rectangle and box. For open thin-wall sections it uses
  Σ b·t³/3 (±30 %, fillets/welds ignored); for freehand sections it uses an FDM grid (150 cells,
  ~3–8 %, possibly insufficient for very thin features or large aspect ratios).
- Shear centre is exact only for symmetric I, U, L, T sections; otherwise it falls back to the
  centroid (incorrect).
- Warping constant I_w is not computed — use the FEM engine.

FEM engine (button "Calculer (FEA)", recommended for I_t, I_w, shear centre, shear areas):

- Warping (I_t, I_w, shear centre, shear areas) requires a single connected region. For disconnected
  sections — including a solid island floating inside a hole — these values are reported as "n/d";
  geometric and plastic properties are still computed.
- Warping results depend on mesh density; I_t/I_w are typically stable to < 2 % between densities.

General:

- Geometric properties (A, I_y, I_z, I_yz, moduli, radii) agree between both engines to machine
  precision and are exact for polygons.
- Parametric generators produce sharp corners (no fillet radii); the bundled example library
  (`exemples/`) includes profiles with fillets or tapered flanges for realistic FEM results.
- Catalogue profiles use nominal dimensions (no rolling tolerances, no root radii in the polygon).
- No DXF import/export yet.
- Not validated against a recognised design standard: verify the results independently before any use
  in structural design.

---

## License

Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later) — see the
[`LICENSE`](LICENSE) file.

The GUI uses PyQt6, distributed under the GPL v3 (Riverbank Computing). A redistributed application
linking PyQt6 must therefore be GPL-compatible, which makes GPL-3.0 the appropriate licence here. The
computation dependencies are permissive and GPL-compatible:
[sectionproperties](https://github.com/robbievanleeuwen/section-properties) (MIT), shapely (BSD-3-Clause),
numpy / scipy (BSD-3-Clause).

© 2026 Pavlishenku. SectionCAD is free software; you may redistribute it and/or modify it under the
terms of the GPL, either version 3 or (at your option) any later version. It is distributed WITHOUT
ANY WARRANTY; see the GPL for details.

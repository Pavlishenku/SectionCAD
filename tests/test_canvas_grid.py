"""
Tests de la grille adaptative du canvas : elle doit rester visible et raisonnablement
espacée à TOUT niveau de zoom (ne plus disparaître au dézoom).
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication
from ui.canvas import SectionCanvas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# Du très dézoomé (1e-4 px/mm) au très zoomé (1000 px/mm)
ZOOMS = [1e-4, 1e-3, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 20.0, 100.0, 1000.0]


@pytest.mark.parametrize("scale", ZOOMS)
def test_grid_spacing_visible_at_all_zoom(app, scale):
    c = SectionCanvas()
    c.grid_spacing = 10.0
    c._scale = scale
    minor, major = c._grid_steps()
    assert minor is not None and minor > 0
    on_screen = minor * scale  # espacement écran des lignes mineures (px)
    # Toujours dans [target, 10·target[ -> jamais invisible, jamais absurde.
    assert SectionCanvas.GRID_TARGET_PX <= on_screen < SectionCanvas.GRID_TARGET_PX * 10 + 1e-6
    assert abs(major - minor * 10.0) < 1e-6


@pytest.mark.parametrize("base", [0.5, 2.0, 10.0, 25.0, 100.0])
def test_grid_steps_various_base(app, base):
    c = SectionCanvas()
    c.grid_spacing = base
    c._scale = 0.037   # zoom arbitraire (dézoomé)
    minor, _ = c._grid_steps()
    on_screen = minor * c._scale
    assert SectionCanvas.GRID_TARGET_PX <= on_screen < SectionCanvas.GRID_TARGET_PX * 10 + 1e-6


def test_grid_render_extreme_zoom_no_crash(app):
    c = SectionCanvas()
    c.resize(400, 300)
    c.grid_spacing = 10.0
    for s in (1e-5, 1e-2, 1.0, 1e4):
        c._scale = s
        c.grab()  # force un paintEvent -> _draw_grid ne doit ni planter ni boucler


def test_grid_steps_invalid(app):
    c = SectionCanvas()
    c.grid_spacing = 0.0
    assert c._grid_steps() == (None, None)

"""
Drawing canvas for section geometry.
Features: grid with magnetic snap, polygon drawing, coordinate input,
image import with scale setting, zoom/pan, centroid/axes display.
"""
import math
from typing import List, Tuple, Optional

from PyQt6.QtWidgets import (QWidget, QInputDialog, QMenu, QApplication)
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize, pyqtSignal
from PyQt6.QtGui import (QPainter, QPen, QBrush, QColor, QFont,
                          QCursor, QKeyEvent,
                          QMouseEvent, QWheelEvent, QPainterPath)

from ui.calibration_manager import ImageCalibrationManager


class SectionCanvas(QWidget):
    section_changed = pyqtSignal()        # emitted when geometry changes
    open_coord_dialog_requested = pyqtSignal()  # emitted by Ctrl+I

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Minimum modeste : le canvas reste la zone extensible mais la fenêtre peut
        # être réduite sans rogner les panneaux latéraux.
        self.setMinimumSize(420, 320)

        # View transform
        self._scale = 2.0        # pixels per mm
        self._offset = QPointF(0, 0)  # world origin in screen coords
        self._last_size = None        # taille précédente (pour le recentrage au resize)
        self._panning = False
        self._pan_start = QPoint()

        # Grid
        self.grid_spacing = 10.0   # mm
        self.snap_enabled = True
        self.snap_radius = 8       # pixels

        # Drawing state
        self.current_points: List[Tuple[float, float]] = []
        self.hover_point: Optional[Tuple[float, float]] = None
        self.drawing_mode = True   # True = adding points
        # Force le prochain clic à démarrer un nouveau polygone même à l'intérieur
        # d'un autre (pour dessiner un trou). Activé par Shift+clic ou le bouton dédié.
        self._force_new_polygon = False

        # Finished polygons: list of (pts, is_hole)
        self.polygons: List[Tuple[List[Tuple[float, float]], bool]] = []

        # Section display
        self.centroid: Optional[Tuple[float, float]] = None
        self.section_results = None

        # FEA mesh overlay (optional visualisation)
        self.fea_mesh = None          # (vertices: list[(x, y)], triangles: list[(i, j, k)])
        self.show_mesh = False

        # Image overlay + calibration (delegated to manager)
        self._img_mgr = ImageCalibrationManager(self)

        # Vertex drag state
        self._drag_polygon_idx: Optional[int] = None
        self._drag_point_idx: Optional[int] = None
        self._dragging_vertex = False
        self._hover_polygon_idx: Optional[int] = None  # for cursor / highlight
        self._hover_vertex_idx: Optional[int] = None

        # Polygon selection / move / copy-paste state
        self._selected_polygon_idx: Optional[int] = None
        self._drag_poly_pending = False
        self._dragging_polygon = False
        self._drag_poly_press_screen: Tuple[float, float] = (0.0, 0.0)
        self._drag_poly_world_start: Tuple[float, float] = (0.0, 0.0)
        self._drag_poly_pts_orig: List[Tuple[float, float]] = []
        self._clipboard: Optional[Tuple[List[Tuple[float, float]], bool]] = None
        self._paste_mode = False
        self._paste_preview_world: Optional[Tuple[float, float]] = None

        # Undo/Redo
        from ui.undo_stack import UndoStack, CanvasState
        self._undo_stack = UndoStack(max_size=100)
        self._save_undo_state()

        # Colors — thème clair par défaut (voir apply_theme).
        self.dark_mode = False
        self.apply_theme(False)

        # Center view
        self._center_view()

    # ------------------------------------------------------------------ theme
    def apply_theme(self, dark: bool):
        """Définit toutes les couleurs du canvas pour le thème clair ou sombre."""
        self.dark_mode = bool(dark)
        if dark:
            self.c_background   = QColor(30, 30, 35)
            self.c_grid         = QColor(55, 55, 65)
            self.c_grid_major   = QColor(82, 82, 102)
            self.c_grid_label   = QColor(150, 150, 170)
            self.c_origin       = QColor(120, 120, 215)
            self.c_polygon      = QColor(90, 160, 235)
            self.c_fill         = QColor(60, 120, 200, 70)
            self.c_hole_fill    = QColor(240, 110, 110, 70)
            self.c_hole         = QColor(240, 110, 110)   # contour de trou
            self.c_current      = QColor(255, 160, 40)
            self.c_centroid     = QColor(255, 90, 90)
            self.c_axis         = QColor(255, 95, 95)
            self.c_axis2        = QColor(95, 175, 245)
            self.c_snap         = QColor(60, 220, 120)
            self.c_vertex_hover = QColor(60, 220, 120)
            self.c_selected     = QColor(255, 210, 70)
            self.c_mesh         = QColor(150, 150, 185, 130)
            self.c_sc           = QColor(60, 220, 130)   # shear centre marker
            self.c_text         = QColor(220, 215, 215)  # numeric labels on canvas
        else:
            self.c_background   = QColor(245, 245, 250)
            self.c_grid         = QColor(200, 200, 200)
            self.c_grid_major   = QColor(160, 160, 180)
            self.c_grid_label   = QColor(140, 140, 160)
            self.c_origin       = QColor(100, 100, 200)
            self.c_polygon      = QColor(70, 130, 200)
            self.c_fill         = QColor(70, 130, 200, 50)
            self.c_hole_fill    = QColor(240, 100, 100, 60)
            self.c_hole         = QColor(220, 60, 60)     # contour de trou
            self.c_current      = QColor(255, 140, 0)
            self.c_centroid     = QColor(220, 0, 0)
            self.c_axis         = QColor(200, 0, 0)
            self.c_axis2        = QColor(0, 120, 200)
            self.c_snap         = QColor(0, 180, 80)
            self.c_vertex_hover = QColor(0, 200, 80)
            self.c_selected     = QColor(255, 200, 0)
            self.c_mesh         = QColor(110, 110, 130, 120)
            self.c_sc           = QColor(0, 140, 60)
            self.c_text         = QColor(80, 40, 40)
        self.update()

    # ------------------------------------------------------------------ undo/redo
    def _save_undo_state(self):
        import copy
        from ui.undo_stack import CanvasState
        self._undo_stack.push(CanvasState(
            polygons=copy.deepcopy(self.polygons),
            current_points=copy.deepcopy(self.current_points)
        ))

    def _restore_undo_state(self, state):
        import copy
        self.polygons = copy.deepcopy(state.polygons)
        self.current_points = copy.deepcopy(state.current_points)
        self._selected_polygon_idx = None
        self._paste_mode = False
        self.section_changed.emit()
        self.update()

    # ------------------------------------------------------------------ view
    def _center_view(self):
        w, h = self.width() or 800, self.height() or 600
        self._offset = QPointF(w / 2, h / 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new = event.size()
        prev = self._last_size
        self._last_size = QSize(new)
        if prev is not None and prev.width() > 0 and prev.height() > 0:
            # Garde fixe le point au centre du viewport lors d'un redimensionnement
            # (le dessin ne dérive pas vers un coin / hors écran).
            self._offset += QPointF((new.width() - prev.width()) / 2.0,
                                    (new.height() - prev.height()) / 2.0)
        else:
            # Premier dimensionnement réel : centre la vue sur la taille allouée.
            self._center_view()

    def world_to_screen(self, wx: float, wy: float) -> QPointF:
        sx = self._offset.x() + wx * self._scale
        sy = self._offset.y() - wy * self._scale   # y flipped
        return QPointF(sx, sy)

    def screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        wx = (sx - self._offset.x()) / self._scale
        wy = -(sy - self._offset.y()) / self._scale
        return wx, wy

    def snap_to_grid(self, wx: float, wy: float) -> Tuple[float, float]:
        if not self.snap_enabled:
            return wx, wy
        g = self.grid_spacing
        return round(wx / g) * g, round(wy / g) * g

    def _nearest_snap(self, sx: float, sy: float) -> Tuple[float, float]:
        wx, wy = self.screen_to_world(sx, sy)
        snapped = self.snap_to_grid(wx, wy)
        sp = self.world_to_screen(*snapped)
        dist = math.hypot(sp.x() - sx, sp.y() - sy)
        if dist <= self.snap_radius:
            return snapped
        return wx, wy

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        pos = event.position()
        wx, wy = self.screen_to_world(pos.x(), pos.y())
        self._scale *= factor
        self._scale = max(0.05, min(200.0, self._scale))
        # Keep mouse position fixed
        self._offset = QPointF(
            pos.x() - wx * self._scale,
            pos.y() + wy * self._scale,
        )
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position()

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.pos())
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._img_mgr.is_calibrating:
                self._img_mgr.handle_calibration_click(self.screen_to_world(pos.x(), pos.y()))
                return

            # Paste mode: place polygon at snap point
            if self._paste_mode:
                wx, wy = self._nearest_snap(pos.x(), pos.y())
                self._place_pasted_polygon(wx, wy)
                return

            if self.drawing_mode:
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                # force_new : démarrer un nouveau polygone même à l'intérieur d'un
                # autre (Shift+clic ou bouton « Nouveau contour / trou »).
                force_new = self._force_new_polygon or shift

                # Vertex drag BEFORE adding a new point (sauf si on force un nouveau polygone)
                if not force_new:
                    pidx, vidx = self._find_vertex_at(pos.x(), pos.y())
                    if pidx is not None and not ctrl:
                        self._drag_polygon_idx = pidx
                        self._drag_point_idx = vidx
                        self._dragging_vertex = True
                        self._selected_polygon_idx = pidx
                        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                        self.update()
                        return

                wx, wy = self._nearest_snap(pos.x(), pos.y())
                if ctrl:
                    self._input_exact_coords(wx, wy)
                    return

                if self.current_points:
                    # Déjà en train de dessiner : ajoute un point
                    self.current_points.append((wx, wy))
                elif force_new:
                    # Démarre un nouveau polygone (ex. trou) même à l'intérieur d'un autre
                    self._force_new_polygon = False
                    self._selected_polygon_idx = None
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                    self.current_points.append((wx, wy))
                else:
                    # Pas en train de dessiner : sélectionne un polygone si clic à l'intérieur
                    hit_idx = self._find_polygon_at(pos.x(), pos.y())
                    if hit_idx is not None:
                        import copy
                        self._selected_polygon_idx = hit_idx
                        self._drag_poly_pending = True
                        self._drag_poly_press_screen = (pos.x(), pos.y())
                        self._drag_poly_world_start = self.screen_to_world(pos.x(), pos.y())
                        self._drag_poly_pts_orig = copy.deepcopy(self.polygons[hit_idx][0])
                        self.update()
                        return
                    else:
                        # Clic dans le vide : désélectionne et commence à dessiner
                        self._selected_polygon_idx = None
                        self.current_points.append((wx, wy))
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()

        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self._offset += QPointF(delta.x(), delta.y())
            self.update()
            return

        if self._dragging_vertex:
            wx, wy = self._nearest_snap(pos.x(), pos.y())
            pts = self.polygons[self._drag_polygon_idx][0]
            pts[self._drag_point_idx] = (wx, wy)
            self.hover_point = (wx, wy)
            self.section_changed.emit()
            self.update()
            return

        # Activate polygon drag once threshold is exceeded
        if self._drag_poly_pending:
            dx_px = pos.x() - self._drag_poly_press_screen[0]
            dy_px = pos.y() - self._drag_poly_press_screen[1]
            if math.hypot(dx_px, dy_px) > 5:
                self._dragging_polygon = True
                self._drag_poly_pending = False

        if self._dragging_polygon and self._selected_polygon_idx is not None:
            wx, wy = self.screen_to_world(pos.x(), pos.y())
            dx = wx - self._drag_poly_world_start[0]
            dy = wy - self._drag_poly_world_start[1]
            new_pts = [(x + dx, y + dy) for x, y in self._drag_poly_pts_orig]
            is_hole = self.polygons[self._selected_polygon_idx][1]
            self.polygons[self._selected_polygon_idx] = (new_pts, is_hole)
            self.hover_point = self._nearest_snap(pos.x(), pos.y())
            self.section_changed.emit()
            self.update()
            return

        wx, wy = self._nearest_snap(pos.x(), pos.y())
        self.hover_point = (wx, wy)

        # Update paste preview position
        if self._paste_mode:
            self._paste_preview_world = (wx, wy)
            self.update()
            return

        # Vertex hover detection — update cursor and repaint if changed
        pidx, vidx = self._find_vertex_at(pos.x(), pos.y())
        if (pidx != self._hover_polygon_idx or vidx != self._hover_vertex_idx):
            self._hover_polygon_idx = pidx
            self._hover_vertex_idx = vidx
            if pidx is not None:
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        if event.button() == Qt.MouseButton.LeftButton and self._dragging_vertex:
            self._dragging_vertex = False
            self._drag_polygon_idx = None
            self._drag_point_idx = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.section_changed.emit()
            self.update()
            self._save_undo_state()

        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_poly_pending:
                self._drag_poly_pending = False  # was a click, not a drag — selection already done
            if self._dragging_polygon:
                self._dragging_polygon = False
                self._drag_poly_pending = False
                self._drag_poly_pts_orig = []
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self.section_changed.emit()
                self.update()
                self._save_undo_state()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing_mode:
            self._close_polygon(is_hole=False)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._close_polygon(is_hole=False)
        elif key == Qt.Key.Key_H:
            self._close_polygon(is_hole=True)
        elif key == Qt.Key.Key_Escape:
            if self._paste_mode:
                self._paste_mode = False
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self.update()
            else:
                self.current_points.clear()
                self._selected_polygon_idx = None
                self._force_new_polygon = False
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self.update()
        elif key == Qt.Key.Key_I and mods & Qt.KeyboardModifier.ControlModifier:
            self._open_coord_dialog()
        elif key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            if self.current_points:
                self.current_points.pop()
                self.update()
            else:
                state = self._undo_stack.undo()
                if state:
                    self._restore_undo_state(state)
        elif key == Qt.Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            state = self._undo_stack.redo()
            if state:
                self._restore_undo_state(state)
        elif key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            self._copy_selected_polygon()
        elif key == Qt.Key.Key_V and mods & Qt.KeyboardModifier.ControlModifier:
            self._start_paste_mode()
        elif key == Qt.Key.Key_Delete:
            if self._selected_polygon_idx is not None:
                self._delete_selected_polygon()
            else:
                self.clear_all()
        elif key == Qt.Key.Key_F:
            self.fit_view()
        elif key == Qt.Key.Key_G:
            self.snap_enabled = not self.snap_enabled
            self.update()

    # ------------------------------------------------------------------ drawing
    def _close_polygon(self, is_hole: bool):
        if len(self.current_points) < 3:
            return
        pts = list(self.current_points)
        self.polygons.append((pts, is_hole))
        self.current_points = []
        self._force_new_polygon = False
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.section_changed.emit()
        self.update()
        self._save_undo_state()

    def start_new_polygon(self):
        """Force le prochain clic gauche à démarrer un nouveau polygone, même à
        l'intérieur d'un polygone existant (utile pour dessiner un trou). Le
        polygone se ferme ensuite avec Entrée (contour) ou H (trou)."""
        self.current_points = []
        self._force_new_polygon = True
        self._selected_polygon_idx = None
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.update()

    def _input_exact_coords(self, default_x: float, default_y: float):
        text, ok = QInputDialog.getText(
            self, "Coordonnées exactes",
            "Entrez x,y (mm) :",
            text=f"{default_x:.2f},{default_y:.2f}"
        )
        if ok and text:
            try:
                parts = text.replace(';', ',').split(',')
                x, y = float(parts[0]), float(parts[1])
                self.current_points.append((x, y))
                self.update()
            except Exception:
                pass

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        if self._selected_polygon_idx is not None:
            _, is_hole = self.polygons[self._selected_polygon_idx]
            menu.addAction("Supprimer ce polygone (Suppr)", self._delete_selected_polygon)
            menu.addAction("Copier ce polygone (Ctrl+C)", self._copy_selected_polygon)
            toggle_lbl = "Convertir en contour" if is_hole else "Convertir en trou"
            menu.addAction(toggle_lbl, self._toggle_hole)
            menu.addSeparator()
        menu.addAction("Nouveau contour / trou (Shift+clic)", self.start_new_polygon)
        menu.addAction("Fermer polygone (Entrée)", lambda: self._close_polygon(False))
        menu.addAction("Fermer comme TROU (H)", lambda: self._close_polygon(True))
        if self._clipboard is not None:
            menu.addAction("Coller polygone (Ctrl+V)", self._start_paste_mode)
        menu.addAction("Saisir coordonnées (Ctrl+clic)", lambda: self._input_exact_coords(0, 0))
        menu.addAction("Saisir liste de coordonnées (Ctrl+I)", self._open_coord_dialog)
        menu.addSeparator()
        menu.addAction("Importer image de fond", self._img_mgr.import_background)
        if self._img_mgr.bg_image:
            menu.addAction("Calibrer l'échelle (2 points)", self._img_mgr.start_calibration)
            menu.addAction("Supprimer image", self._img_mgr.remove_background)
        menu.addSeparator()
        menu.addAction("Ajuster la vue (F)", self.fit_view)
        menu.addAction("Tout effacer (Suppr)", self.clear_all)
        menu.exec(self.mapToGlobal(pos))

    # ------------------------------------------------------------------ coord dialog
    def _open_coord_dialog(self):
        from ui.coord_dialog import CoordInputDialog
        dlg = CoordInputDialog(self)
        if dlg.exec():
            pts = dlg.points
            if pts:
                self.polygons.append((pts, dlg.is_hole))
                self.section_changed.emit()
                self.fit_view()
                self.update()
                self._save_undo_state()

    # ------------------------------------------------------------------ vertex hit-test
    def _find_vertex_at(self, sx: float, sy: float
                        ) -> Tuple[Optional[int], Optional[int]]:
        """Return (polygon_idx, vertex_idx) for the nearest vertex within
        snap_radius*2 pixels, or (None, None) if none found."""
        hit_radius = self.snap_radius * 2
        best_dist = hit_radius + 1
        best_p: Optional[int] = None
        best_v: Optional[int] = None
        for p_idx, (pts, _) in enumerate(self.polygons):
            for v_idx, (wx, wy) in enumerate(pts):
                sp = self.world_to_screen(wx, wy)
                d = math.hypot(sp.x() - sx, sp.y() - sy)
                if d <= hit_radius and d < best_dist:
                    best_dist = d
                    best_p = p_idx
                    best_v = v_idx
        return best_p, best_v

    # ------------------------------------------------------------------ polygon selection helpers
    def _point_in_polygon(self, wx: float, wy: float,
                          pts: List[Tuple[float, float]]) -> bool:
        """Ray-casting point-in-polygon test."""
        n = len(pts)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > wy) != (yj > wy)) and (wx < (xj - xi) * (wy - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _find_polygon_at(self, sx: float, sy: float) -> Optional[int]:
        """Return index of the topmost polygon containing screen point (sx, sy)."""
        wx, wy = self.screen_to_world(sx, sy)
        for idx in range(len(self.polygons) - 1, -1, -1):
            pts, _ = self.polygons[idx]
            if self._point_in_polygon(wx, wy, pts):
                return idx
        return None

    def _poly_centroid(self, pts: List[Tuple[float, float]]) -> Tuple[float, float]:
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

    def _delete_selected_polygon(self):
        if self._selected_polygon_idx is not None:
            del self.polygons[self._selected_polygon_idx]
            self._selected_polygon_idx = None
            self.section_changed.emit()
            self.update()
            self._save_undo_state()

    def _copy_selected_polygon(self):
        if self._selected_polygon_idx is not None:
            import copy
            pts, is_hole = self.polygons[self._selected_polygon_idx]
            self._clipboard = (copy.deepcopy(pts), is_hole)

    def _start_paste_mode(self):
        if self._clipboard is not None:
            self._paste_mode = True
            self._paste_preview_world = None
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def _place_pasted_polygon(self, wx: float, wy: float):
        if self._clipboard is None:
            return
        pts, is_hole = self._clipboard
        import copy
        cx, cy = self._poly_centroid(pts)
        dx, dy = wx - cx, wy - cy
        new_pts = [(x + dx, y + dy) for x, y in pts]
        self.polygons.append((new_pts, is_hole))
        self._paste_mode = False
        self._paste_preview_world = None
        self._selected_polygon_idx = len(self.polygons) - 1
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.section_changed.emit()
        self.update()
        self._save_undo_state()

    def _toggle_hole(self):
        if self._selected_polygon_idx is not None:
            pts, is_hole = self.polygons[self._selected_polygon_idx]
            self.polygons[self._selected_polygon_idx] = (pts, not is_hole)
            self.section_changed.emit()
            self.update()
            self._save_undo_state()

    # ------------------------------------------------------------------ image (forwarding to manager)
    def import_background(self):
        """Forwarding method — keeps compatibility with main_window.py menu/toolbar."""
        self._img_mgr.import_background()

    def start_calibration(self):
        """Forwarding method — keeps compatibility with external callers."""
        self._img_mgr.start_calibration()

    def remove_background(self):
        """Forwarding method — keeps compatibility with external callers."""
        self._img_mgr.remove_background()

    # ------------------------------------------------------------------ view helpers
    def fit_view(self):
        all_pts = []
        for pts, _ in self.polygons:
            all_pts.extend(pts)
        all_pts.extend(self.current_points)
        if not all_pts:
            self._center_view()
            self.update()
            return
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        margin = 80
        w, h = self.width() - 2 * margin, self.height() - 2 * margin
        if w <= 0 or h <= 0:
            return
        rng_x = max(xs) - min(xs) or 100
        rng_y = max(ys) - min(ys) or 100
        self._scale = min(w / rng_x, h / rng_y)
        self._offset = QPointF(
            self.width() / 2 - cx * self._scale,
            self.height() / 2 + cy * self._scale,
        )
        self.update()

    def clear_all(self):
        self._undo_stack.clear()
        self.polygons.clear()
        self.current_points.clear()
        self.centroid = None
        self.section_results = None
        self._selected_polygon_idx = None
        self._paste_mode = False
        self.section_changed.emit()
        self.update()
        self._save_undo_state()

    def set_polygons(self, outer_list, hole_list=None):
        """Load a set of predefined polygons (from parametric/catalog)."""
        self.polygons.clear()
        self.current_points.clear()
        self._selected_polygon_idx = None
        self._paste_mode = False
        for pts in outer_list:
            self.polygons.append((list(pts), False))
        if hole_list:
            for pts in hole_list:
                self.polygons.append((list(pts), True))
        self.fit_view()
        self.section_changed.emit()
        self._save_undo_state()

    def get_outer_polygons(self):
        return [pts for pts, hole in self.polygons if not hole]

    def get_hole_polygons(self):
        return [pts for pts, hole in self.polygons if hole]

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        p.fillRect(self.rect(), getattr(self, 'c_background', QColor(245, 245, 250)))

        # Background image
        self._img_mgr.draw_bg_image(p)

        # Grid (respects grid_visible flag set by toolbar toggle)
        if getattr(self, "grid_visible", True):
            self._draw_grid(p)

        # World origin axes
        self._draw_origin(p)

        # Finished polygons
        for poly_idx, (pts, is_hole) in enumerate(self.polygons):
            self._draw_polygon(p, pts, is_hole, poly_idx)

        # FEA mesh overlay (above polygons, below centroid/axes)
        if self.show_mesh and self.fea_mesh:
            self._draw_mesh(p)

        # Current polygon in progress
        if self.current_points:
            self._draw_current_polygon(p)

        # Paste preview (ghost polygon following cursor)
        if self._paste_mode and self._clipboard and self._paste_preview_world:
            self._draw_paste_preview(p)

        # Centroid + axes
        if self.centroid and self.section_results:
            self._draw_centroid(p)

        # Calibration points
        if self._img_mgr.is_calibrating:
            self._img_mgr.draw_calibration_points(p)

        # Coordinates display
        if self.hover_point:
            self._draw_coords(p)

        p.end()

    # Espacement écran minimal souhaité (px) entre lignes mineures de la grille.
    GRID_TARGET_PX = 12.0

    def _grid_steps(self):
        """Pas (mineur, majeur) ADAPTATIFS de la grille pour le zoom courant.

        Le pas mineur est un multiple du pas de base par une puissance de 10, choisi
        pour que l'espacement à l'écran reste dans [GRID_TARGET_PX, 10·GRID_TARGET_PX[ :
        la grille ne disparaît jamais (dézoom) et ne devient jamais trop dense (zoom).
        Renvoie (None, None) si la grille ne peut pas être calculée.
        """
        base, scale = self.grid_spacing, self._scale
        if base <= 0 or scale <= 0:
            return None, None
        target = self.GRID_TARGET_PX
        minor = base
        guard = 0
        while minor * scale < target and guard < 40:
            minor *= 10.0
            guard += 1
        guard = 0
        while minor * scale >= target * 10.0 and guard < 40:
            minor /= 10.0
            guard += 1
        return minor, minor * 10.0

    def _draw_grid(self, p: QPainter):
        minor, major = self._grid_steps()
        if minor is None:
            return

        w, h = self.width(), self.height()
        x0, y0 = self.screen_to_world(0, 0)
        x1, y1 = self.screen_to_world(w, h)
        xmin = math.floor(min(x0, x1) / major) * major
        xmax = math.ceil(max(x0, x1) / major) * major
        ymin = math.floor(min(y0, y1) / major) * major
        ymax = math.ceil(max(y0, y1) / major) * major

        def _vlines(step, pen):
            p.setPen(pen)
            x = xmin
            while x <= xmax + 1e-9:
                sx = self.world_to_screen(x, 0).x()
                p.drawLine(int(sx), 0, int(sx), h)
                x += step
            y = ymin
            while y <= ymax + 1e-9:
                sy = self.world_to_screen(0, y).y()
                p.drawLine(0, int(sy), w, int(sy))
                y += step

        # Lignes mineures puis majeures (×10)
        _vlines(minor, QPen(self.c_grid, 0.5))
        _vlines(major, QPen(self.c_grid_major, 1.0))

        # Étiquettes sur la grille majeure
        p.setFont(QFont("Arial", 7))
        p.setPen(QPen(self.c_grid_label))
        x = xmin
        while x <= xmax + 1e-9:
            sx = self.world_to_screen(x, 0).x()
            p.drawText(int(sx) + 2, h - 5, f"{x:g}")
            x += major
        y = ymin
        while y <= ymax + 1e-9:
            sy = self.world_to_screen(0, y).y()
            p.drawText(5, int(sy) - 2, f"{y:g}")
            y += major

    def _draw_origin(self, p: QPainter):
        o = self.world_to_screen(0, 0)
        p.setPen(QPen(self.c_origin, 1.5, Qt.PenStyle.DashLine))
        p.drawLine(0, int(o.y()), self.width(), int(o.y()))
        p.drawLine(int(o.x()), 0, int(o.x()), self.height())
        p.setPen(QPen(self.c_origin, 2))
        p.drawText(int(o.x()) + 4, int(o.y()) - 4, "O")

    def _draw_polygon(self, p: QPainter, pts, is_hole: bool, poly_idx: int = -1):
        if len(pts) < 2:
            return
        screen_pts = [self.world_to_screen(x, y) for x, y in pts]
        is_selected = (poly_idx == self._selected_polygon_idx)

        path = QPainterPath()
        path.moveTo(screen_pts[0])
        for sp in screen_pts[1:]:
            path.lineTo(sp)
        path.closeSubpath()

        fill = self.c_hole_fill if is_hole else self.c_fill
        p.fillPath(path, QBrush(fill))

        color = self.c_hole if is_hole else self.c_polygon
        p.setPen(QPen(color, 2))
        for i in range(len(screen_pts)):
            p.drawLine(screen_pts[i], screen_pts[(i + 1) % len(screen_pts)])

        # Selection highlight: dashed yellow border
        if is_selected:
            sel_pen = QPen(self.c_selected, 2.5, Qt.PenStyle.DashLine)
            p.setPen(sel_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # Vertices — taille adaptative pour ne pas masquer les sections denses
        # ou courbes (cercles, arcs très discrétisés).
        n_pts = len(screen_pts)
        if n_pts >= 2:
            min_edge = min(
                math.hypot(screen_pts[i].x() - screen_pts[(i + 1) % n_pts].x(),
                           screen_pts[i].y() - screen_pts[(i + 1) % n_pts].y())
                for i in range(n_pts)
            )
        else:
            min_edge = 1e9
        # Rayon ≤ ~1/5 de la plus courte arête à l'écran, plafonné à 4 px.
        vr = max(1.5, min(4.0, 0.22 * min_edge))
        # Pastilles masquées pour les polygones denses non sélectionnés : l'outline
        # suffit et reste lisible ; le sommet survolé reste toujours visible/déplaçable.
        show_dots = is_selected or (n_pts <= 24 and vr >= 2.0)
        for v_idx, sp in enumerate(screen_pts):
            hovered = (poly_idx == self._hover_polygon_idx
                       and v_idx == self._hover_vertex_idx)
            dragging = (self._dragging_vertex
                        and poly_idx == self._drag_polygon_idx
                        and v_idx == self._drag_point_idx)
            if hovered or dragging:
                p.setPen(QPen(self.c_vertex_hover, 1.5))
                p.setBrush(QBrush(self.c_vertex_hover))
                p.drawEllipse(sp, 6, 6)
            elif show_dots:
                vc = self.c_selected if is_selected else color
                p.setPen(QPen(vc))
                p.setBrush(QBrush(vc))
                p.drawEllipse(sp, vr, vr)

        # Label (hole)
        if is_hole:
            cx = sum(pt.x() for pt in screen_pts) / len(screen_pts)
            cy = sum(pt.y() for pt in screen_pts) / len(screen_pts)
            p.setPen(QPen(self.c_hole))
            p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            p.drawText(int(cx) - 15, int(cy) + 4, "TROU")

    def _draw_current_polygon(self, p: QPainter):
        screen_pts = [self.world_to_screen(x, y) for x, y in self.current_points]
        hover_s = self.world_to_screen(*self.hover_point) if self.hover_point else None

        p.setPen(QPen(self.c_current, 2))
        for i in range(len(screen_pts) - 1):
            p.drawLine(screen_pts[i], screen_pts[i + 1])

        if screen_pts and hover_s:
            p.setPen(QPen(self.c_current, 1, Qt.PenStyle.DashLine))
            p.drawLine(screen_pts[-1], hover_s)

        p.setPen(QPen(self.c_current))
        p.setBrush(QBrush(self.c_current))
        for sp in screen_pts:
            p.drawEllipse(sp, 4, 4)

        # Snap indicator
        if self.hover_point and self.snap_enabled:
            sp = self.world_to_screen(*self.hover_point)
            p.setPen(QPen(self.c_snap, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(sp, 6, 6)

        # Closing line preview
        if len(screen_pts) >= 3 and hover_s:
            close_dist = math.hypot(hover_s.x() - screen_pts[0].x(),
                                    hover_s.y() - screen_pts[0].y())
            if close_dist < self.snap_radius * 2:
                p.setPen(QPen(self.c_snap, 2))
                p.drawLine(screen_pts[-1], screen_pts[0])

    def _draw_centroid(self, p: QPainter):
        cx, cy = self.centroid
        sp = self.world_to_screen(cx, cy)

        # Centroid marker
        r = 8
        p.setPen(QPen(self.c_centroid, 2))
        p.drawLine(int(sp.x()) - r, int(sp.y()), int(sp.x()) + r, int(sp.y()))
        p.drawLine(int(sp.x()), int(sp.y()) - r, int(sp.x()), int(sp.y()) + r)
        fill_c = QColor(self.c_centroid)
        fill_c.setAlpha(180)
        p.setBrush(QBrush(fill_c))
        p.drawEllipse(sp, 4, 4)

        # Principal axes
        res = self.section_results
        theta = math.radians(res.theta_p)
        L = 60  # pixels
        dx1, dy1 = math.cos(theta), math.sin(theta)
        dx2, dy2 = -math.sin(theta), math.cos(theta)
        p.setPen(QPen(self.c_axis, 1.5, Qt.PenStyle.DashDotLine))
        p.drawLine(
            int(sp.x() - dx1 * L), int(sp.y() + dy1 * L),
            int(sp.x() + dx1 * L), int(sp.y() - dy1 * L)
        )
        p.setPen(QPen(self.c_axis2, 1.5, Qt.PenStyle.DashDotLine))
        p.drawLine(
            int(sp.x() - dx2 * L), int(sp.y() + dy2 * L),
            int(sp.x() + dx2 * L), int(sp.y() - dy2 * L)
        )

        # Labels
        p.setPen(QPen(self.c_centroid))
        p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        p.drawText(int(sp.x()) + 10, int(sp.y()) - 10, "G")
        p.setFont(QFont("Arial", 8))
        p.setPen(QPen(self.c_axis))
        p.drawText(int(sp.x() + dx1 * L) + 3, int(sp.y() - dy1 * L), "1")
        p.setPen(QPen(self.c_axis2))
        p.drawText(int(sp.x() + dx2 * L) + 3, int(sp.y() - dy2 * L), "2")

        # Coordonnées numériques du centroïde
        p.setFont(QFont("Consolas", 8))
        p.setPen(QPen(self.c_text))
        coord_text = f"({res.xc:.1f} ; {res.yc:.1f}) mm"
        p.drawText(int(sp.x()) + 12, int(sp.y()) + 16, coord_text)
        theta_text = f"θ = {res.theta_p:.1f}°"
        p.drawText(int(sp.x()) + 12, int(sp.y()) + 28, theta_text)

        # Marqueur du centre de cisaillement si différent du centroïde
        if abs(res.xsc - res.xc) > 0.5 or abs(res.ysc - res.yc) > 0.5:
            sp_sc = self.world_to_screen(res.xsc, res.ysc)
            p.setPen(QPen(self.c_sc, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            sz = 7
            p.drawRect(int(sp_sc.x()) - sz, int(sp_sc.y()) - sz, sz * 2, sz * 2)
            p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            p.drawText(int(sp_sc.x()) + sz + 2, int(sp_sc.y()) + 4, "SC")
            p.setFont(QFont("Consolas", 7))
            sc_text = f"({res.xsc:.1f} ; {res.ysc:.1f})"
            p.drawText(int(sp_sc.x()) + sz + 2, int(sp_sc.y()) + 14, sc_text)

    def _draw_paste_preview(self, p: QPainter):
        pts, _ = self._clipboard
        cx, cy = self._poly_centroid(pts)
        wx, wy = self._paste_preview_world
        dx, dy = wx - cx, wy - cy
        preview_pts = [(x + dx, y + dy) for x, y in pts]
        screen_pts = [self.world_to_screen(x, y) for x, y in preview_pts]
        path = QPainterPath()
        path.moveTo(screen_pts[0])
        for sp in screen_pts[1:]:
            path.lineTo(sp)
        path.closeSubpath()
        sel_fill = QColor(self.c_selected)
        sel_fill.setAlpha(60)
        p.fillPath(path, QBrush(sel_fill))
        p.setPen(QPen(self.c_selected, 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _draw_coords(self, p: QPainter):
        wx, wy = self.hover_point
        text = f"x={wx:.2f} mm   y={wy:.2f} mm"
        if self.snap_enabled:
            text += "  [snap]"
        if self.dark_mode:
            box_c, txt_c = QColor(40, 40, 48, 210), QColor(225, 225, 230)
        else:
            box_c, txt_c = QColor(255, 255, 255, 200), QColor(40, 40, 40)
        p.setFont(QFont("Consolas", 9))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text) + 8
        th = fm.height() + 4
        p.fillRect(self.width() - tw - 5, self.height() - th - 5, tw, th, box_c)
        p.setPen(QPen(txt_c))
        p.drawText(self.width() - tw - 1, self.height() - 7, text)

    def update_section_display(self, results):
        self.section_results = results
        if results and results.area > 0:
            self.centroid = (results.xc, results.yc)
        else:
            self.centroid = None
        self.update()

    # ------------------------------------------------------------------ FEA mesh overlay
    def set_fea_mesh(self, vertices, triangles):
        """Stocke le maillage FEA à dessiner (ou None pour l'effacer)."""
        if vertices and triangles:
            self.fea_mesh = (vertices, triangles)
        else:
            self.fea_mesh = None
        self.update()

    def set_mesh_visible(self, visible: bool):
        if self.show_mesh == bool(visible):
            return
        self.show_mesh = bool(visible)
        self.update()

    def clear_results_overlay(self):
        """Retire centroïde, axes, centre de cisaillement et maillage du canvas —
        appelé quand la géométrie change (résultats devenus obsolètes)."""
        if self.centroid is None and self.section_results is None and self.fea_mesh is None:
            return
        self.centroid = None
        self.section_results = None
        self.fea_mesh = None
        self.update()

    def _draw_mesh(self, p: QPainter):
        verts, tris = self.fea_mesh
        p.setPen(QPen(self.c_mesh, 0.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        n = len(verts)
        for tri in tris:
            i, j, k = tri[0], tri[1], tri[2]
            if i >= n or j >= n or k >= n:
                continue
            a = self.world_to_screen(verts[i][0], verts[i][1])
            b = self.world_to_screen(verts[j][0], verts[j][1])
            c = self.world_to_screen(verts[k][0], verts[k][1])
            path.moveTo(a)
            path.lineTo(b)
            path.lineTo(c)
            path.lineTo(a)
        p.drawPath(path)

"""
Manages background image import and 2-point scale calibration for SectionCanvas.
"""
import math
from typing import Optional, Tuple

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox


class ImageCalibrationManager:
    """Handles background image and 2-point calibration for a SectionCanvas."""

    def __init__(self, canvas):
        """canvas: the SectionCanvas parent — needed for coords, update(), and as dialog parent."""
        self._canvas = canvas
        self.bg_image: Optional[QPixmap] = None
        self.img_origin = QPointF(0, 0)   # world coords of image top-left (mm)
        self.img_scale = 1.0              # mm per pixel of the source image
        self._calibrating = False
        self._calib_p1: Optional[Tuple[float, float]] = None
        self._calib_p2: Optional[Tuple[float, float]] = None

    @property
    def is_calibrating(self) -> bool:
        return self._calibrating

    def import_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self._canvas, "Importer image",
            filter="Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.svg)"
        )
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self._canvas, "Erreur", "Impossible de charger l'image.")
            return
        self.bg_image = px
        self.img_scale = 1.0  # 1 pixel = 1 mm initially
        self.img_origin = QPointF(0, 0)
        self._canvas.update()
        QMessageBox.information(
            self._canvas, "Image importée",
            "Image chargée.\n"
            "Faites clic droit → 'Calibrer l'échelle' pour définir l'échelle réelle.\n"
            "Cliquez 2 points connus puis entrez la distance réelle."
        )

    def start_calibration(self):
        self._calibrating = True
        self._calib_p1 = None
        self._calib_p2 = None
        QMessageBox.information(
            self._canvas, "Calibration",
            "Cliquez sur 2 points dont vous connaissez la distance réelle."
        )

    def handle_calibration_click(self, world_pt: Tuple[float, float]):
        """Call from mousePressEvent when is_calibrating is True."""
        if self._calib_p1 is None:
            self._calib_p1 = world_pt
            self._canvas.update()
        else:
            self._calib_p2 = world_pt
            self._finish_calibration()

    def _finish_calibration(self):
        p1, p2 = self._calib_p1, self._calib_p2
        pixel_dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / self.img_scale
        if pixel_dist < 1e-6:
            self._calibrating = False
            return
        dist_mm, ok = QInputDialog.getDouble(
            self._canvas, "Calibration",
            "Distance réelle entre les 2 points (mm) :",
            value=100.0, min=0.001, max=1e9, decimals=3
        )
        if ok:
            self.img_scale = dist_mm / pixel_dist
        self._calibrating = False
        self._calib_p1 = None
        self._calib_p2 = None
        self._canvas.update()

    def remove_background(self):
        self.bg_image = None
        self._canvas.update()

    def draw_bg_image(self, p: QPainter):
        if not self.bg_image:
            return
        ox, oy = self.img_origin.x(), self.img_origin.y()
        s = self.img_scale * self._canvas._scale  # image pixels -> screen pixels
        sp = self._canvas.world_to_screen(ox, oy)
        img_w = self.bg_image.width() * s
        img_h = self.bg_image.height() * s
        p.setOpacity(0.55)
        p.drawPixmap(
            int(sp.x()), int(sp.y() - img_h),
            int(img_w), int(img_h),
            self.bg_image
        )
        p.setOpacity(1.0)

    def draw_calibration_points(self, p: QPainter):
        """Draw calibration point markers P1/P2."""
        if self._calib_p1:
            sp = self._canvas.world_to_screen(*self._calib_p1)
            p.setPen(QPen(QColor(255, 200, 0), 2))
            p.drawEllipse(sp, 6, 6)
            p.drawText(int(sp.x()) + 8, int(sp.y()), "P1")
        if self._calib_p2:
            sp = self._canvas.world_to_screen(*self._calib_p2)
            p.drawEllipse(sp, 6, 6)
            p.drawText(int(sp.x()) + 8, int(sp.y()), "P2")
        if self._calib_p1 and self._calib_p2:
            s1 = self._canvas.world_to_screen(*self._calib_p1)
            s2 = self._canvas.world_to_screen(*self._calib_p2)
            p.drawLine(s1, s2)

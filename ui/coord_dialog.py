"""Dialog for bulk coordinate input via a table."""
import re
from typing import List, Tuple, Optional

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                              QTableWidgetItem, QPushButton, QLabel, QMessageBox,
                              QApplication, QHeaderView, QAbstractItemView,
                              QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QFont


class _PreviewWidget(QFrame):
    """Minimal polygon preview — 120×120 px."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._points: List[Tuple[float, float]] = []

    def set_points(self, pts: List[Tuple[float, float]]):
        self._points = pts
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Thème détecté via la feuille de style globale (vide = clair, sinon sombre).
        dark = bool(QApplication.instance().styleSheet())
        bg = QColor(40, 40, 46) if dark else QColor(248, 248, 252)
        placeholder = QColor(120, 120, 135) if dark else QColor(180, 180, 180)
        poly_c = QColor(90, 160, 235) if dark else QColor(70, 130, 200)
        p.fillRect(self.rect(), bg)

        pts = self._points
        if len(pts) < 2:
            p.setPen(QPen(placeholder))
            p.setFont(QFont("Arial", 8))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aperçu")
            p.end()
            return

        # Fit to widget with margin
        margin = 12
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        w_range = max(xs) - min(xs) or 1
        h_range = max(ys) - min(ys) or 1
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        scale = min(avail_w / w_range, avail_h / h_range)
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        pw, ph = self.width() / 2, self.height() / 2

        def to_screen(x, y):
            return QPointF(pw + (x - cx) * scale, ph - (y - cy) * scale)

        screen_pts = [to_screen(x, y) for x, y in pts]

        path = QPainterPath()
        path.moveTo(screen_pts[0])
        for sp in screen_pts[1:]:
            path.lineTo(sp)
        path.closeSubpath()

        fill_c = QColor(poly_c)
        fill_c.setAlpha(60)
        p.fillPath(path, QBrush(fill_c))
        p.setPen(QPen(poly_c, 1.5))
        p.drawPath(path)

        p.setPen(QPen(poly_c))
        p.setBrush(QBrush(poly_c))
        for sp in screen_pts:
            p.drawEllipse(sp, 3, 3)

        p.end()


class CoordInputDialog(QDialog):
    """Dialog allowing engineers to enter or paste a list of polygon vertices."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saisie de coordonnées")
        self.resize(440, 540)
        self._result_points: List[Tuple[float, float]] = []
        self._is_hole = False
        self._build_ui()

    # ------------------------------------------------------------------ public API
    @property
    def points(self) -> List[Tuple[float, float]]:
        return self._result_points

    @property
    def is_hole(self) -> bool:
        return self._is_hole

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header
        lbl = QLabel(
            "Entrez les coordonnées des sommets (au moins 3 points).\n"
            "Vous pouvez coller directement depuis Excel ou un tableur."
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        # Table + preview side by side
        table_row = QHBoxLayout()

        # Table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["X (mm)", "Y (mm)"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setMinimumWidth(220)
        self._table.itemChanged.connect(self._on_table_changed)
        table_row.addWidget(self._table, stretch=1)

        # Preview
        preview_col = QVBoxLayout()
        self._preview = _PreviewWidget()
        preview_col.addWidget(self._preview)
        preview_col.addStretch()
        table_row.addLayout(preview_col)

        layout.addLayout(table_row)

        # Row-level buttons
        row_btns = QHBoxLayout()
        btn_add = QPushButton("➕ Ajouter ligne")
        btn_add.clicked.connect(self._add_row)
        btn_del = QPushButton("➖ Supprimer ligne")
        btn_del.clicked.connect(self._delete_row)
        btn_paste = QPushButton("📋 Coller depuis presse-papiers")
        btn_paste.clicked.connect(self._paste_clipboard)
        row_btns.addWidget(btn_add)
        row_btns.addWidget(btn_del)
        row_btns.addWidget(btn_paste)
        layout.addLayout(row_btns)

        # Point count label
        self._count_label = QLabel("0 point(s)")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._count_label)

        # Validation buttons
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        action_btns = QHBoxLayout()
        btn_contour = QPushButton("✅ Fermer comme contour")
        btn_contour.setDefault(True)
        btn_contour.clicked.connect(lambda: self._accept(is_hole=False))

        btn_hole = QPushButton("🔲 Fermer comme trou")
        btn_hole.clicked.connect(lambda: self._accept(is_hole=True))

        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)

        action_btns.addWidget(btn_contour)
        action_btns.addWidget(btn_hole)
        action_btns.addStretch()
        action_btns.addWidget(btn_cancel)
        layout.addLayout(action_btns)

        # Start with 5 empty rows
        for _ in range(5):
            self._add_row()

    # ------------------------------------------------------------------ row helpers
    def _add_row(self):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))
        self._table.setItem(row, 1, QTableWidgetItem(""))

    def _delete_row(self):
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True
        )
        if not rows:
            row = self._table.rowCount() - 1
            if row >= 0:
                self._table.removeRow(row)
        else:
            for r in rows:
                self._table.removeRow(r)
        self._refresh_preview()

    # ------------------------------------------------------------------ clipboard
    def _paste_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if not text.strip():
            QMessageBox.information(self, "Presse-papiers vide",
                                    "Le presse-papiers ne contient pas de texte.")
            return
        pts = self._parse_text(text)
        if not pts:
            QMessageBox.warning(
                self, "Format non reconnu",
                "Impossible de lire les coordonnées.\n"
                "Format attendu : une paire X,Y (ou X;Y ou X↹Y) par ligne."
            )
            return
        # Replace table content
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for x, y in pts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(x)))
            self._table.setItem(row, 1, QTableWidgetItem(str(y)))
        self._table.blockSignals(False)
        self._refresh_preview()

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def _parse_text(text: str) -> List[Tuple[float, float]]:
        """Parse lines of 'x sep y' where sep is tab, comma, or semicolon."""
        pts: List[Tuple[float, float]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Split on tab, semicolon, or comma (keep only first 2 tokens)
            parts = re.split(r"[\t;,]+", line)
            if len(parts) < 2:
                continue
            try:
                x = float(parts[0].replace(",", ".").strip())
                y = float(parts[1].replace(",", ".").strip())
                pts.append((x, y))
            except ValueError:
                continue
        return pts

    # ------------------------------------------------------------------ validation
    def _collect_points(self, silent: bool = False) -> Optional[List[Tuple[float, float]]]:
        """Read the table and return parsed points, or None on error.

        silent=True : skip partial/invalid rows without showing a dialog.
                      Used during live preview while the user is still typing.
        silent=False: show an error dialog and return None on the first bad row.
                      Used when the user clicks Accept.
        """
        pts: List[Tuple[float, float]] = []
        for row in range(self._table.rowCount()):
            x_item = self._table.item(row, 0)
            y_item = self._table.item(row, 1)
            x_text = x_item.text().strip() if x_item else ""
            y_text = y_item.text().strip() if y_item else ""
            if not x_text and not y_text:
                continue  # skip fully empty rows
            # One cell filled, the other empty — partial row
            if not x_text or not y_text:
                if silent:
                    continue
                QMessageBox.warning(
                    self, "Valeur invalide",
                    f"Ligne {row + 1} : les deux colonnes X et Y doivent être remplies."
                )
                return None
            try:
                x = float(x_text.replace(",", "."))
                y = float(y_text.replace(",", "."))
                pts.append((x, y))
            except ValueError:
                if silent:
                    continue
                QMessageBox.warning(
                    self, "Valeur invalide",
                    f"Ligne {row + 1} : valeurs non numériques ({x_text!r}, {y_text!r})."
                )
                return None
        return pts

    def _validate(self, pts: List[Tuple[float, float]]) -> bool:
        if len(pts) < 3:
            QMessageBox.warning(
                self, "Pas assez de points",
                "Un polygone nécessite au moins 3 points distincts."
            )
            return False
        # Check consecutive duplicates
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
                QMessageBox.warning(
                    self, "Points dupliqués",
                    f"Les points {i + 1} et {(i + 1) % len(pts) + 1} "
                    f"sont identiques ou consécutifs dupliqués."
                )
                return False
        return True

    # ------------------------------------------------------------------ signals
    def _on_table_changed(self, _item):
        self._refresh_preview()

    def _refresh_preview(self):
        pts = self._collect_points(silent=True)
        count = len(pts) if pts else 0
        self._count_label.setText(f"{count} point(s)")
        self._preview.set_points(pts if pts else [])

    # ------------------------------------------------------------------ accept
    def _accept(self, is_hole: bool):
        pts = self._collect_points()
        if pts is None:
            return
        if not self._validate(pts):
            return
        self._result_points = pts
        self._is_hole = is_hole
        self.accept()

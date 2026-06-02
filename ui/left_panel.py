"""
Left panel: section type selector.
Tabs: Dessin libre | Paramétrique | Catalogue
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QLabel, QDoubleSpinBox, QPushButton, QComboBox,
                              QFormLayout, QGroupBox, QSpinBox, QCheckBox,
                              QFrame, QScrollArea, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from data.european_catalog import ALL_CATALOGS
import sections.parametric as para


class LeftPanel(QWidget):
    section_requested = pyqtSignal(list, list, dict)  # (outer_polygons, hole_polygons, metadata)
    grid_changed = pyqtSignal(float, bool)             # (grid_spacing_mm, snap_enabled)
    coord_dialog_requested = pyqtSignal()              # open bulk coordinate input dialog
    new_polygon_requested = pyqtSignal()               # démarrer un nouveau contour/trou

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setMaximumWidth(290)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Sections transversales")
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_freehand_tab(), "✏️ Dessin")
        self.tabs.addTab(self._build_parametric_tab(), "⚙️ Paramétrique")
        self.tabs.addTab(self._build_catalog_tab(), "📋 Catalogue")
        layout.addWidget(self.tabs)

    # ------------------------------------------------------------------ theme
    def set_dark_mode(self, dark: bool):
        """Adapte les éléments à style propre (non couverts par le QSS global)."""
        self._style_cat_info(dark)

    def _style_cat_info(self, dark: bool):
        self._cat_info_dark = dark
        if dark:
            self.cat_info.setStyleSheet("background: #2d2d2d; color: #cfcfcf; padding: 4px;")
        else:
            self.cat_info.setStyleSheet("background: #f8f8f8; color: #202020; padding: 4px;")

    # ------------------------------------------------------------------ dessin libre
    def _build_freehand_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        grp = QGroupBox("Grille et accrochage")
        form = QFormLayout(grp)

        self.grid_spin = QDoubleSpinBox()
        self.grid_spin.setRange(0.1, 1000)
        self.grid_spin.setValue(10.0)
        self.grid_spin.setSuffix(" mm")
        self.grid_spin.valueChanged.connect(self._emit_grid)
        form.addRow("Espacement :", self.grid_spin)

        self.snap_check = QCheckBox("Activer l'accrochage")
        self.snap_check.setChecked(True)
        self.snap_check.toggled.connect(self._emit_grid)
        form.addRow(self.snap_check)

        layout.addWidget(grp)

        btn_new = QPushButton("➕ Nouveau contour / trou")
        btn_new.setToolTip(
            "Démarre un nouveau polygone. Permet de placer le premier point même\n"
            "à l'intérieur d'un polygone existant (pour dessiner un trou).\n"
            "Équivaut à Shift+clic. Fermez ensuite avec Entrée (contour) ou H (trou)."
        )
        btn_new.clicked.connect(self.new_polygon_requested.emit)
        layout.addWidget(btn_new)

        grp2 = QGroupBox("Saisie polygone")
        v2 = QVBoxLayout(grp2)
        v2.addWidget(QLabel("• Clic gauche : ajouter un sommet"))
        v2.addWidget(QLabel("• Shift+clic : nouveau polygone / trou dans un polygone"))
        v2.addWidget(QLabel("• Ctrl+clic : saisir coordonnées exactes"))
        v2.addWidget(QLabel("• Entrée / double-clic : fermer"))
        v2.addWidget(QLabel("• Touche H : fermer comme trou"))
        v2.addWidget(QLabel("• Ctrl+Z : annuler dernier point"))
        v2.addWidget(QLabel("• Clic molette : déplacer la vue"))
        v2.addWidget(QLabel("• Molette : zoom"))
        v2.addWidget(QLabel("• Touche F : ajuster la vue"))
        v2.addWidget(QLabel("• Touche G : on/off accrochage"))
        v2.addWidget(QLabel("• Drag sommet : déplacer un point"))
        layout.addWidget(grp2)

        btn_coord = QPushButton("Saisir liste de coordonnées (Ctrl+I)")
        btn_coord.setToolTip(
            "Ouvre un tableau pour saisir ou coller\n"
            "une liste de coordonnées X, Y."
        )
        btn_coord.clicked.connect(self.coord_dialog_requested.emit)
        layout.addWidget(btn_coord)

        grp3 = QGroupBox("Image de fond")
        v3 = QVBoxLayout(grp3)
        v3.addWidget(QLabel("Clic droit sur le canvas :"))
        v3.addWidget(QLabel("• Importer image de fond"))
        v3.addWidget(QLabel("• Calibrer l'échelle (2 pts)"))
        v3.addWidget(QLabel("• Supprimer image"))
        layout.addWidget(grp3)

        layout.addStretch()
        return w

    def _emit_grid(self):
        self.grid_changed.emit(self.grid_spin.value(), self.snap_check.isChecked())

    # ------------------------------------------------------------------ paramétrique
    def _build_parametric_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        self._param_widgets = {}

        # sections_def: (name, param_labels, defaults, func, metadata_builder)
        # metadata_builder(vals) -> dict  — None means use auto-builder
        sections_def = [
            ("Rectangle", ["Largeur b (mm)", "Hauteur h (mm)"],
             [200, 400], para.rectangle,
             lambda v: {'type': 'rectangle', 'b': v[0], 'h': v[1]}),
            ("Cercle plein", ["Diamètre d (mm)"],
             [300], para.circle,
             lambda v: {'type': 'circle', 'd': v[0]}),
            ("Section en I", ["Hauteur h", "Largeur b", "Âme tw", "Semelle tf"],
             [300, 150, 8, 12], para.i_section,
             lambda v: {'type': 'i_section', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
            ("Caisson (Box)", ["Hauteur h", "Largeur b", "Âme tw", "Semelle tf"],
             [400, 200, 10, 14], para.box_section,
             lambda v: {'type': 'box', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
            ("Cornière L", ["Hauteur h", "Largeur b", "Âme tw", "Semelle tf"],
             [100, 100, 10, 10], para.angle_section,
             lambda v: {'type': 'angle', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
            ("UPN / Canal U", ["Hauteur h", "Largeur b", "Âme tw", "Semelle tf"],
             [200, 75, 8, 11], para.channel_section,
             lambda v: {'type': 'channel', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
            ("Section en T", ["Hauteur h", "Largeur b", "Âme tw", "Semelle tf"],
             [300, 150, 8, 12], para.t_section,
             lambda v: {'type': 't_section', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
            ("RHS (rect. creux)", ["Hauteur h", "Largeur b", "Épaisseur t"],
             [200, 100, 6], para.rectangular_hollow,
             lambda v: {'type': 'box', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[2]}),
            ("SHS (carré creux)", ["Largeur b", "Épaisseur t"],
             [100, 5], para.square_hollow,
             lambda v: {'type': 'box', 'h': v[0], 'b': v[0], 'tw': v[1], 'tf': v[1]}),
            ("Tube creux circulaire", ["Diamètre extérieur d_ext", "Diamètre intérieur d_int"],
             [300, 260], para.hollow_circle,
             lambda v: {'type': 'chs', 'd_ext': v[0], 'd_int': v[1]}),
            ("Croix", ["Hauteur h", "Largeur b", "Épaisseur verticale tw", "Épaisseur horizontale tf"],
             [300, 300, 20, 20], para.cross_section,
             lambda v: {'type': 'cross', 'h': v[0], 'b': v[1], 'tw': v[2], 'tf': v[3]}),
        ]

        for name, param_names, defaults, func, meta_builder in sections_def:
            grp = QGroupBox(name)
            grp.setCheckable(False)
            form = QFormLayout(grp)
            spins = []
            for pname, dval in zip(param_names, defaults):
                spin = QDoubleSpinBox()
                spin.setRange(0.1, 10000)
                spin.setValue(dval)
                spin.setSuffix(" mm")
                spin.setDecimals(1)
                spins.append(spin)
                form.addRow(pname + ":", spin)

            btn = QPushButton(f"Générer {name}")
            btn.clicked.connect(self._make_param_handler(name, func, spins, meta_builder))
            form.addRow(btn)
            self._param_widgets[name] = spins
            layout.addWidget(grp)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    @staticmethod
    def _is_flat_polygon(lst) -> bool:
        """Return True if lst is a single polygon (list of 2-number tuples/lists).

        A flat polygon looks like [(x0,y0), (x1,y1), ...].
        A nested list of polygons looks like [[(x0,y0), ...], [(x0,y0), ...]].
        We distinguish them by checking whether the first element is a
        2-element sequence of numbers — not another sequence-of-points.
        """
        if not lst:
            return False
        first = lst[0]
        # first must be a tuple or list of exactly 2 numbers
        return (
            isinstance(first, (tuple, list))
            and len(first) == 2
            and isinstance(first[0], (int, float))
            and isinstance(first[1], (int, float))
        )

    def _make_param_handler(self, name, func, spins, meta_builder=None):
        def handler():
            vals = [s.value() for s in spins]
            try:
                result = func(*vals)
                metadata = meta_builder(vals) if meta_builder else {}
                if isinstance(result, tuple) and len(result) == 2:
                    # Function returns (outers, holes) — e.g. box_section, hollow_circle
                    outers, holes = result
                    # Normalise to list-of-polygons if a bare polygon was returned
                    if self._is_flat_polygon(outers):
                        outers = [outers]
                    if self._is_flat_polygon(holes):
                        holes = [holes]
                    self.section_requested.emit(outers, holes, metadata)
                else:
                    # Function returns a list of outer polygons (plain sections)
                    outers = result
                    if self._is_flat_polygon(outers):
                        outers = [outers]
                    self.section_requested.emit(outers, [], metadata)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(None, "Erreur", str(e))
        return handler

    # ------------------------------------------------------------------ catalogue
    def _build_catalog_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()

        self.cat_family = QComboBox()
        self.cat_family.addItems(list(ALL_CATALOGS.keys()))
        self.cat_family.currentTextChanged.connect(self._update_profile_list)
        form.addRow("Famille :", self.cat_family)

        self.cat_profile = QComboBox()
        self.cat_profile.setMaxVisibleItems(20)
        form.addRow("Profil :", self.cat_profile)

        layout.addLayout(form)

        # Profile info display
        self.cat_info = QLabel()
        self.cat_info.setWordWrap(True)
        self.cat_info.setFont(QFont("Consolas", 8))
        self.cat_info.setFrameShape(QFrame.Shape.StyledPanel)
        self._cat_info_dark = False
        self._style_cat_info(False)
        layout.addWidget(self.cat_info)

        self.cat_profile.currentTextChanged.connect(self._update_cat_info)

        btn = QPushButton("Charger le profil")
        btn.clicked.connect(self._load_catalog_section)
        layout.addWidget(btn)

        layout.addStretch()
        self._update_profile_list()
        return w

    def _update_profile_list(self):
        family = self.cat_family.currentText()
        catalog = ALL_CATALOGS.get(family, {})
        self.cat_profile.clear()
        self.cat_profile.addItems(list(catalog.keys()))

    def _update_cat_info(self):
        family = self.cat_family.currentText()
        profile = self.cat_profile.currentText()
        catalog = ALL_CATALOGS.get(family, {})
        data = catalog.get(profile, {})
        if not data:
            self.cat_info.setText("")
            return
        lines = []
        for k, v in data.items():
            lines.append(f"{k:6s} = {v}")
        self.cat_info.setText("\n".join(lines))

    def _load_catalog_section(self):
        family = self.cat_family.currentText()
        profile = self.cat_profile.currentText()
        catalog = ALL_CATALOGS.get(family, {})
        data = catalog.get(profile, {})
        if not data:
            return

        h = data.get("h", 0)
        b = data.get("b", 0)
        tw = data.get("tw", 0)
        tf = data.get("tf", 0)

        try:
            if family == "IPE" or family in ("HEA", "HEB", "HEM"):
                polygons = para.i_section(h, b, tw, tf)
                metadata = {'type': 'i_section', 'h': h, 'b': b, 'tw': tw, 'tf': tf, 'name': profile}
                self.section_requested.emit(polygons, [], metadata)
            elif family == "UPN":
                polygons = para.channel_section(h, b, tw, tf)
                metadata = {'type': 'channel', 'h': h, 'b': b, 'tw': tw, 'tf': tf, 'name': profile}
                self.section_requested.emit(polygons, [], metadata)
            elif "Cornière" in family or family.startswith("L"):
                polygons = para.angle_section(h, b, tw, tf)
                metadata = {'type': 'angle', 'h': h, 'b': b, 'tw': tw, 'tf': tf, 'name': profile}
                self.section_requested.emit(polygons, [], metadata)
            elif family == "CHS":
                # CHS: hollow circle — h=b=d_ext, tw=tf=t
                d_ext = h
                d_int = h - 2 * tw
                if d_int <= 0:
                    return
                outers, holes = para.hollow_circle(d_ext, d_int)
                metadata = {'type': 'chs', 'd_ext': d_ext, 'd_int': d_int, 'tw': tw, 'name': profile}
                self.section_requested.emit(outers, holes, metadata)
            elif family in ("RHS", "SHS"):
                # RHS/SHS: rectangular hollow section — tw=tf=t (épaisseurs identiques)
                outers, holes = para.rectangular_hollow(h, b, tw)
                metadata = {'type': 'box', 'h': h, 'b': b, 'tw': tw, 'tf': tw, 'name': profile}
                self.section_requested.emit(outers, holes, metadata)
            else:
                polygons = para.i_section(h, b, tw, tf)
                metadata = {'type': 'i_section', 'h': h, 'b': b, 'tw': tw, 'tf': tf, 'name': profile}
                self.section_requested.emit(polygons, [], metadata)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "Erreur catalogue", str(e))

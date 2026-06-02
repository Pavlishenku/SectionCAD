"""Right panel: displays calculated section properties."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                              QTableWidgetItem, QPushButton, QFileDialog,
                              QHBoxLayout, QFrame, QComboBox, QCheckBox, QHeaderView)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from calculators.sp_backend import (SECTIONPROPERTIES_AVAILABLE, MESH_QUALITY,
                                     DEFAULT_QUALITY)
from calculators.nomenclature import PROPERTY_DESCRIPTIONS

ANALYTIC_SOURCE = "Moteur : analytique"
NOT_COMPUTED_MSG = "Cliquez « Calculer (analytique) » ou « Calculer (FEA) »."
STALE_GEOM = "⚠ Géométrie modifiée — résultats obsolètes. Relancez le calcul."
STALE_MESH = "⚠ Densité de maillage modifiée — relancez « Calculer (FEA) »."

# Groupe d'appartenance de chaque symbole (lookup exact -> pas d'ambiguïté de préfixe)
_GROUP_OF = {
    "A": "basic", "y_G": "centroid", "z_G": "centroid",
    "I_y": "inertia", "I_z": "inertia", "I_yz": "inertia",
    "I_1": "principal", "I_2": "principal", "α": "principal",
    "W_el,y,sup": "moduli", "W_el,y,inf": "moduli",
    "W_el,z,g": "moduli", "W_el,z,d": "moduli",
    "W_pl,y": "plastic", "W_pl,z": "plastic",
    "i_y": "gyration", "i_z": "gyration",
    "y_SC": "shear", "z_SC": "shear", "A_vy": "shear", "A_vz": "shear",
    "I_t": "torsion", "I_w": "torsion",
}
_GROUP_COLORS_LIGHT = {
    "basic": QColor(230, 245, 255), "centroid": QColor(220, 255, 220),
    "inertia": QColor(255, 240, 220), "principal": QColor(255, 225, 200),
    "moduli": QColor(240, 230, 255), "plastic": QColor(255, 240, 255),
    "gyration": QColor(240, 255, 240), "shear": QColor(255, 245, 230),
    "torsion": QColor(255, 245, 180),
}
_GROUP_COLORS_DARK = {
    "basic": QColor(15, 35, 60), "centroid": QColor(15, 50, 15),
    "inertia": QColor(55, 35, 10), "principal": QColor(60, 28, 5),
    "moduli": QColor(40, 15, 60), "plastic": QColor(50, 10, 55),
    "gyration": QColor(15, 50, 15), "shear": QColor(50, 35, 5),
    "torsion": QColor(55, 45, 0),
}


class PropertiesPanel(QWidget):
    fea_requested = pyqtSignal(str)         # émet la qualité de maillage choisie
    analytic_requested = pyqtSignal()       # demande de calcul analytique
    mesh_visibility_changed = pyqtSignal(bool)  # case « Afficher le maillage FEM »
    mesh_quality_changed = pyqtSignal()     # changement de densité de maillage (combo)
    fiche_requested = pyqtSignal()          # demande d'export de la fiche d'archive

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setMaximumWidth(300)
        self._source_text = ANALYTIC_SOURCE
        self._warnings = []
        self._stale = False        # True = résultats obsolètes
        self._placeholder = True   # True = aucun résultat calculé pour l'instant
        self._is_fea_result = False  # True = les valeurs affichées viennent du FEA
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Propriétés de section")
        title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # --- Bouton de calcul analytique ---
        self.btn_analytic = QPushButton("Calculer (analytique)")
        self.btn_analytic.setToolTip(
            "Calcule les propriétés par les méthodes analytiques rapides "
            "(shoelace, FDM/BEM pour la torsion)."
        )
        self.btn_analytic.clicked.connect(self.analytic_requested.emit)
        layout.addWidget(self.btn_analytic)

        # --- Contrôles d'analyse FEA (sectionproperties) ---
        fea_row = QHBoxLayout()
        fea_row.setSpacing(4)
        lbl_mesh = QLabel("Maillage :")
        fea_row.addWidget(lbl_mesh)
        self.mesh_combo = QComboBox()
        self.mesh_combo.addItems(list(MESH_QUALITY.keys()))
        self.mesh_combo.setCurrentText(DEFAULT_QUALITY)
        self.mesh_combo.setToolTip("Densité du maillage éléments finis.\n"
                                   "Plus fin = plus précis mais plus lent.")
        self.mesh_combo.currentTextChanged.connect(lambda _t: self.mesh_quality_changed.emit())
        fea_row.addWidget(self.mesh_combo, 1)
        layout.addLayout(fea_row)

        self.btn_fea = QPushButton("Calculer (FEA)")
        self.btn_fea.setToolTip(
            "Lance une analyse par éléments finis (sectionproperties) pour obtenir\n"
            "des valeurs précises de J, Cw, centre de cisaillement et aires de\n"
            "cisaillement. Le calcul s'exécute en arrière-plan."
        )
        self.btn_fea.clicked.connect(self._on_fea_clicked)
        if not SECTIONPROPERTIES_AVAILABLE:
            self.btn_fea.setEnabled(False)
            self.btn_fea.setToolTip("Package « sectionproperties » non installé "
                                    "(pip install sectionproperties).")
        layout.addWidget(self.btn_fea)

        # Case d'affichage du maillage FEM
        self.mesh_check = QCheckBox("Afficher le maillage FEM")
        self.mesh_check.setToolTip(
            "Superpose le maillage éléments finis sur la section "
            "(disponible après un calcul FEA)."
        )
        self.mesh_check.toggled.connect(self.mesh_visibility_changed.emit)
        if not SECTIONPROPERTIES_AVAILABLE:
            self.mesh_check.setEnabled(False)
        layout.addWidget(self.mesh_check)

        # Libellé indiquant le moteur ayant produit les valeurs affichées / l'état
        self.source_label = QLabel(NOT_COMPUTED_MSG)
        self.source_label.setFont(QFont("Arial", 8))
        self.source_label.setStyleSheet("color: #888;")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        # Bandeau « résultats obsolètes » (géométrie modifiée) — masqué par défaut
        self.stale_banner = QLabel("⚠ Géométrie modifiée — résultats obsolètes. "
                                   "Relancez le calcul.")
        self.stale_banner.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        self.stale_banner.setStyleSheet("color: #8a5000; background: #fff4e0; "
                                        "border: 1px solid #e0b060; padding: 3px;")
        self.stale_banner.setWordWrap(True)
        self.stale_banner.setVisible(False)
        layout.addWidget(self.stale_banner)

        # Zone d'avertissements (régions disjointes, etc.) — masquée par défaut
        self.warn_label = QLabel("")
        self.warn_label.setFont(QFont("Arial", 8))
        self.warn_label.setStyleSheet("color: #b00; background: #fff3f3; "
                                      "border: 1px solid #f0c0c0; padding: 3px;")
        self.warn_label.setWordWrap(True)
        self.warn_label.setVisible(False)
        layout.addWidget(self.warn_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Propriété", "Valeur", "Unité"])
        # Colonne « Propriété » extensible, « Valeur »/« Unité » fixes : le tableau
        # s'adapte à la largeur du panneau lors d'un redimensionnement (pas de
        # défilement horizontal).
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 85)
        self.table.setColumnWidth(2, 45)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Consolas", 9))
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("Exporter CSV")
        self.btn_export.clicked.connect(self._export_csv)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)

        # Bouton d'export de la fiche d'archive (HTML/PDF), a cote d'« Exporter
        # CSV ». Reutilise le slot _export_fiche de la fenetre principale via le
        # signal fiche_requested ; son etat actif/inactif suit btn_export.
        self.btn_fiche = QPushButton("Exporter fiche")
        self.btn_fiche.setToolTip(
            "Genere la fiche d'archive (HTML/PDF) de la section courante."
        )
        self.btn_fiche.clicked.connect(self.fiche_requested.emit)
        self.btn_fiche.setEnabled(False)
        btn_row.addWidget(self.btn_fiche)

        self.btn_copy = QPushButton("Copier")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        self.btn_copy.setEnabled(False)
        btn_row.addWidget(self.btn_copy)
        layout.addLayout(btn_row)

        self._data = {}
        self._dark_mode = False

    def set_dark_mode(self, dark: bool):
        self._dark_mode = dark
        if dark:
            self.stale_banner.setStyleSheet("color: #ffcf80; background: #3a2e12; "
                                            "border: 1px solid #6a551f; padding: 3px;")
            self.warn_label.setStyleSheet("color: #ff9a9a; background: #3a1818; "
                                          "border: 1px solid #6a3030; padding: 3px;")
            self.source_label.setStyleSheet("color: #9a9a9a;")
        else:
            self.stale_banner.setStyleSheet("color: #8a5000; background: #fff4e0; "
                                            "border: 1px solid #e0b060; padding: 3px;")
            self.warn_label.setStyleSheet("color: #b00; background: #fff3f3; "
                                          "border: 1px solid #f0c0c0; padding: 3px;")
            self.source_label.setStyleSheet("color: #888;")
        if self._data:
            self._render_table(self._data)

    # ------------------------------------------------------------------ FEA controls
    def _on_fea_clicked(self):
        """Émet la demande de calcul FEA avec la qualité de maillage sélectionnée."""
        self.fea_requested.emit(self.mesh_combo.currentText())

    def set_fea_busy(self, busy: bool):
        """Active/désactive l'indicateur d'analyse FEA en cours."""
        self.btn_fea.setEnabled(not busy and SECTIONPROPERTIES_AVAILABLE)
        self.mesh_combo.setEnabled(not busy)
        if busy:
            self.btn_fea.setText("⏳ Analyse FEA en cours…")
        else:
            self.btn_fea.setText("Calculer (FEA)")

    def _refresh_labels(self):
        self.source_label.setText(self._source_text)
        if self._warnings:
            self.warn_label.setText("\n".join("⚠ " + w for w in self._warnings))
            self.warn_label.setVisible(True)
        else:
            self.warn_label.setVisible(False)

    def has_results(self) -> bool:
        """True si des valeurs calculées sont actuellement affichées (même obsolètes)."""
        return bool(self._data) and not self._placeholder

    def is_stale(self) -> bool:
        return self._stale

    def is_fea_displayed(self) -> bool:
        """True si les valeurs affichées proviennent du calcul FEA."""
        return self._is_fea_result and self.has_results()

    def show_analytic_results(self, props_dict: dict):
        """Affiche des résultats du moteur analytique."""
        self._data = props_dict
        self._placeholder = False
        self._stale = False
        self._is_fea_result = False
        self.stale_banner.setVisible(False)
        self._source_text = ANALYTIC_SOURCE
        self._warnings = []
        self._render_table(props_dict)
        self._refresh_labels()
        self.btn_export.setEnabled(True)
        self.btn_fiche.setEnabled(True)
        self.btn_copy.setEnabled(True)

    def show_fea_results(self, props_dict: dict, source_text: str, warnings=None):
        """Affiche des résultats du moteur sectionproperties (FEA)."""
        self._data = props_dict
        self._placeholder = False
        self._stale = False
        self._is_fea_result = True
        self.stale_banner.setVisible(False)
        self._source_text = source_text
        self._warnings = list(warnings) if warnings else []
        self._render_table(props_dict)
        self._refresh_labels()
        self.btn_export.setEnabled(True)
        self.btn_fiche.setEnabled(True)
        self.btn_copy.setEnabled(True)

    def set_stale(self, stale: bool = True, reason: str = "geometry"):
        """Marque les résultats affichés comme obsolètes.

        reason="geometry" (édition) ou "mesh" (densité de maillage changée) —
        adapte le texte du bandeau.
        """
        if stale:
            self.stale_banner.setText(STALE_MESH if reason == "mesh" else STALE_GEOM)
        if self._stale == stale:
            return
        self._stale = stale
        self.stale_banner.setVisible(stale)
        if self._data:
            self._render_table(self._data)  # re-rendu grisé

    def set_not_computed(self, message: str = None):
        """État « pas encore calculé » : efface les valeurs, message neutre."""
        msg = message or NOT_COMPUTED_MSG
        if self._placeholder and not self._data:
            self.source_label.setText(msg)  # déjà dans cet état, simple maj du message
            return
        self._data = {}
        self._placeholder = True
        self._stale = False
        self._is_fea_result = False
        self.stale_banner.setVisible(False)
        self.warn_label.setVisible(False)
        self.table.setRowCount(0)
        self.source_label.setText(msg)
        self.btn_export.setEnabled(False)
        self.btn_fiche.setEnabled(False)
        self.btn_copy.setEnabled(False)

    def _render_table(self, props_dict: dict):
        self.table.setRowCount(len(props_dict))
        group_colors = _GROUP_COLORS_DARK if self._dark_mode else _GROUP_COLORS_LIGHT

        for row, (name, (val, unit)) in enumerate(props_dict.items()):
            item_name = QTableWidgetItem(name)
            item_val = QTableWidgetItem(val)
            item_unit = QTableWidgetItem(unit)
            item_val.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_unit.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Info-bulle : description complète du symbole (nomenclature Eurocode)
            desc = PROPERTY_DESCRIPTIONS.get(name, "")
            if desc:
                for item in (item_name, item_val, item_unit):
                    item.setToolTip(desc)

            if self._stale:
                # Résultats obsolètes : texte grisé, sans couleur de groupe.
                grey = QColor(150, 150, 150)
                for item in (item_name, item_val, item_unit):
                    item.setForeground(grey)
            else:
                bg = group_colors.get(_GROUP_OF.get(name))
                if bg is not None:
                    for item in (item_name, item_val, item_unit):
                        item.setBackground(bg)

            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_val)
            self.table.setItem(row, 2, item_unit)

        self.table.resizeRowsToContents()
        self.btn_export.setEnabled(True)
        self.btn_fiche.setEnabled(True)
        self.btn_copy.setEnabled(True)

    def clear(self):
        self.table.setRowCount(0)
        self._data = {}
        self._placeholder = True
        self._stale = False
        self._is_fea_result = False
        self.stale_banner.setVisible(False)
        self.warn_label.setVisible(False)
        self._source_text = ANALYTIC_SOURCE
        self._warnings = []
        self.source_label.setText("Aucune section définie.")
        self.btn_export.setEnabled(False)
        self.btn_fiche.setEnabled(False)
        self.btn_copy.setEnabled(False)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter", "section_properties.csv",
            "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("Symbole;Désignation;Valeur;Unité\n")
            for name, (val, unit) in self._data.items():
                desc = PROPERTY_DESCRIPTIONS.get(name, "")
                f.write(f"{name};{desc};{val};{unit}\n")

    def _copy_to_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        lines = ["Symbole\tDésignation\tValeur\tUnité"]
        for name, (val, unit) in self._data.items():
            desc = PROPERTY_DESCRIPTIONS.get(name, "")
            lines.append(f"{name}\t{desc}\t{val}\t{unit}")
        QApplication.clipboard().setText("\n".join(lines))

"""Dialog for configuring and exporting the HTML section report."""
import os
import tempfile
import webbrowser
from datetime import date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QCheckBox, QPushButton, QFileDialog, QMessageBox,
    QFormLayout, QScrollArea, QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt


class ReportOptionsDialog(QDialog):
    """
    Shows report configuration options and triggers export when confirmed.

    Parameters
    ----------
    parent : QWidget
        Parent window.
    outers : list
        List of outer polygon point-lists.
    holes : list
        List of hole polygon point-lists.
    results : object
        Result object returned by ``compute_properties``.
    props : dict
        Properties dict returned by ``results_to_dict``.
    """

    def __init__(self, parent, outers, holes, results, props, engine_label=""):
        super().__init__(parent)
        self.setWindowTitle("Exporter le rapport HTML")
        self.setMinimumWidth(520)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._outers = outers
        self._holes = holes
        self._results = results
        self._props = props
        self._engine_label = engine_label
        # Le maillage n'est disponible que si les résultats proviennent d'un calcul FEA.
        self._has_mesh = bool(getattr(results, "mesh_triangles", None))

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- Project information group --------------------------------
        grp_info = QGroupBox("Informations du projet")
        form = QFormLayout(grp_info)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ed_title   = QLineEdit()
        self._ed_project = QLineEdit()
        self._ed_author  = QLineEdit()
        self._ed_date    = QLineEdit(str(date.today()))
        self._ed_notes   = QLineEdit()

        form.addRow("Titre du rapport :", self._ed_title)
        form.addRow("Projet :",           self._ed_project)
        form.addRow("Auteur :",           self._ed_author)
        form.addRow("Date :",             self._ed_date)
        form.addRow("Notes :",            self._ed_notes)

        layout.addWidget(grp_info)

        # ---- Report content group ------------------------------------
        grp_content = QGroupBox("Contenu du rapport")
        content_layout = QVBoxLayout(grp_content)
        content_layout.setSpacing(4)

        # -- Geometry (SVG) --
        self._chk_geometry = QCheckBox("Géométrie (SVG)")
        self._chk_geometry.setChecked(True)
        content_layout.addWidget(self._chk_geometry)

        self._chk_dimensions = QCheckBox("    Cotes (largeur / hauteur)")
        self._chk_dimensions.setChecked(True)
        content_layout.addWidget(self._chk_dimensions)

        self._chk_centroid_axes = QCheckBox("    Centroïde et axes principaux")
        self._chk_centroid_axes.setChecked(True)
        content_layout.addWidget(self._chk_centroid_axes)

        self._chk_mesh = QCheckBox("    Maillage FEM (éléments finis)")
        self._chk_mesh.setChecked(self._has_mesh)
        self._chk_mesh.setEnabled(self._has_mesh)
        if not self._has_mesh:
            self._chk_mesh.setToolTip("Disponible uniquement si le rapport "
                                      "utilise un calcul FEA récent.")
        content_layout.addWidget(self._chk_mesh)

        # -- Coordinates table --
        self._chk_coords_table = QCheckBox("Tableau des coordonnées")
        self._chk_coords_table.setChecked(True)
        content_layout.addWidget(self._chk_coords_table)

        # -- Geometric properties --
        self._chk_properties = QCheckBox("Propriétés géométriques")
        self._chk_properties.setChecked(True)
        content_layout.addWidget(self._chk_properties)

        self._chk_area_perim   = QCheckBox("    Aire, centroïde")
        self._chk_area_perim.setChecked(True)
        content_layout.addWidget(self._chk_area_perim)

        self._chk_inertia      = QCheckBox("    Moments d'inertie")
        self._chk_inertia.setChecked(True)
        content_layout.addWidget(self._chk_inertia)

        self._chk_principal    = QCheckBox("    Axes principaux")
        self._chk_principal.setChecked(True)
        content_layout.addWidget(self._chk_principal)

        self._chk_elastic_mod  = QCheckBox("    Modules élastiques")
        self._chk_elastic_mod.setChecked(True)
        content_layout.addWidget(self._chk_elastic_mod)

        self._chk_plastic_mod  = QCheckBox("    Modules plastiques")
        self._chk_plastic_mod.setChecked(True)
        content_layout.addWidget(self._chk_plastic_mod)

        self._chk_gyration     = QCheckBox("    Rayons de giration")
        self._chk_gyration.setChecked(True)
        content_layout.addWidget(self._chk_gyration)

        self._chk_torsion      = QCheckBox("    Torsion (J, Cw)")
        self._chk_torsion.setChecked(True)
        content_layout.addWidget(self._chk_torsion)

        self._chk_shear_center = QCheckBox("    Centre de cisaillement")
        self._chk_shear_center.setChecked(True)
        content_layout.addWidget(self._chk_shear_center)

        # -- Theory section --
        self._chk_theory = QCheckBox("Théorie et méthodes de calcul")
        self._chk_theory.setChecked(True)
        content_layout.addWidget(self._chk_theory)

        layout.addWidget(grp_content)

        # ---- Buttons row ---------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_preview = QPushButton("Aperçu navigateur")
        self._btn_preview.setToolTip("Générer le rapport et l'ouvrir dans le navigateur par défaut")
        self._btn_preview.clicked.connect(self._preview_in_browser)
        btn_layout.addWidget(self._btn_preview)

        self._btn_export = QPushButton("Exporter...")
        self._btn_export.setToolTip("Enregistrer le rapport HTML dans un fichier")
        self._btn_export.setDefault(True)
        self._btn_export.clicked.connect(self._export_to_file)
        btn_layout.addWidget(self._btn_export)

        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

        # ---- Wire parent-child enable/disable logic ------------------
        self._chk_geometry.toggled.connect(self._sync_geometry_children)
        self._chk_properties.toggled.connect(self._sync_properties_children)

    # ------------------------------------------------------------------
    # Enable / disable child checkboxes
    # ------------------------------------------------------------------

    def _sync_geometry_children(self, checked: bool):
        self._chk_dimensions.setEnabled(checked)
        self._chk_centroid_axes.setEnabled(checked)
        self._chk_mesh.setEnabled(checked and self._has_mesh)

    def _sync_properties_children(self, checked: bool):
        for chk in (
            self._chk_area_perim,
            self._chk_inertia,
            self._chk_principal,
            self._chk_elastic_mod,
            self._chk_plastic_mod,
            self._chk_gyration,
            self._chk_torsion,
            self._chk_shear_center,
        ):
            chk.setEnabled(checked)

    # ------------------------------------------------------------------
    # Build ReportOptions from current checkbox state
    # ------------------------------------------------------------------

    def get_options(self):
        """
        Return a ``ReportOptions`` object reflecting the current dialog state.

        This method performs a late import of ``reports.html_report`` so that
        the dialog can be constructed even if that module is not yet available.

        Returns
        -------
        ReportOptions
        """
        from reports.html_report import ReportOptions  # late import — module may not exist yet

        def _on(chk) -> bool:
            """Return True only if the checkbox is both checked and enabled."""
            return chk.isChecked() and chk.isEnabled()

        return ReportOptions(
            title=self._ed_title.text().strip() or "Rapport de section",
            project=self._ed_project.text().strip(),
            author=self._ed_author.text().strip(),
            date=self._ed_date.text().strip() or str(date.today()),
            notes=self._ed_notes.text().strip(),
            # Geometry
            show_geometry=self._chk_geometry.isChecked(),
            show_dimensions=_on(self._chk_dimensions),
            show_centroid=_on(self._chk_centroid_axes),
            show_mesh=_on(self._chk_mesh),
            engine_label=self._engine_label,
            # Coordinates table
            show_coordinates=self._chk_coords_table.isChecked(),
            # Properties — inertia and principal axes combined into show_results_inertia
            #              elastic + plastic combined into show_results_moduli
            show_results_basic=_on(self._chk_area_perim),
            show_results_inertia=(_on(self._chk_inertia) or _on(self._chk_principal)),
            show_results_moduli=(_on(self._chk_elastic_mod) or _on(self._chk_plastic_mod)),
            show_results_gyration=_on(self._chk_gyration),
            show_results_torsion=_on(self._chk_torsion),
            show_results_shear=_on(self._chk_shear_center),
            # Theory
            show_theory=self._chk_theory.isChecked(),
        )

    # ------------------------------------------------------------------
    # Internal export helpers
    # ------------------------------------------------------------------

    def _do_export(self, filepath: str) -> bool:
        """
        Generate the report and write it to *filepath*.

        Returns True on success, False if an error occurred (after showing a
        QMessageBox to the user).
        """
        try:
            from reports.html_report import ReportOptions, export_report  # late import
            opts = self.get_options()
            export_report(opts, self._outers, self._holes, self._results, self._props, filepath)
            return True
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Module manquant",
                f"Le module de génération de rapport n'est pas disponible :\n{exc}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Erreur d'export",
                f"Impossible de générer le rapport :\n{exc}",
            )
        return False

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _preview_in_browser(self):
        """Generate report into a temp file and open in the default browser."""
        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        if self._do_export(tmp_path):
            webbrowser.open(f"file:///{tmp_path.replace(os.sep, '/')}")

    def _export_to_file(self):
        """Ask for a save path and export the report there."""
        default_name = (self._ed_title.text().strip() or "rapport_section") + ".html"
        # Sanitise filename
        for ch in r'\/:*?"<>|':
            default_name = default_name.replace(ch, "_")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le rapport HTML",
            default_name,
            "Rapport HTML (*.html);;Tous les fichiers (*)",
        )
        if not path:
            return

        if self._do_export(path):
            QMessageBox.information(
                self,
                "Export réussi",
                f"Rapport enregistré :\n{path}",
            )
            self.accept()

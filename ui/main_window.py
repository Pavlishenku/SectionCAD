"""Main application window."""
import glob
import json
import os
import sys

from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QStatusBar,
                              QLabel, QSplitter, QMenuBar, QMenu, QMessageBox,
                              QToolBar, QFileDialog)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont, QKeySequence

from ui.canvas import SectionCanvas
from ui.left_panel import LeftPanel
from ui.properties_panel import PropertiesPanel
from calculators.section_properties import compute_properties, results_to_dict


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._current_file: str | None = None
        self._modified = False
        self._section_metadata: dict = {}    # metadata from last parametric/catalog load
        self._fea_worker = None              # thread d'analyse sectionproperties en cours
        # Jeton de génération : incrémenté à chaque changement de géométrie. Permet
        # d'ignorer les résultats FEA périmés (géométrie modifiée / nouveau projet /
        # ouverture pendant qu'un calcul tournait).
        self._fea_generation = 0
        self._fea_launch_generation = -1
        # Derniers résultats FEA et la génération à laquelle ils correspondent
        # (réutilisés par le rapport HTML s'ils sont toujours à jour).
        self._last_fea_results = None
        self._last_fea_gen = -2
        # _metadata_fresh : la métadonnée de section vient d'être chargée (génération
        # paramétrique/catalogue) et doit survivre jusqu'au prochain calcul.
        # _loading_new_geometry : le changement courant est un chargement (génère/ouvre)
        # et non une édition — on affiche « à calculer » plutôt que « obsolète ».
        self._metadata_fresh = False
        self._loading_new_geometry = False
        self.setWindowTitle("SectionCAD — Géométrie de sections civiles")
        self.resize(1280, 780)
        self._build_ui()
        self._build_menu()
        self._build_toolbar()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        self.left = LeftPanel()
        splitter.addWidget(self.left)

        # Canvas
        self.canvas = SectionCanvas()
        splitter.addWidget(self.canvas)

        # Right panel
        self.props = PropertiesPanel()
        splitter.addWidget(self.props)

        splitter.setSizes([260, 800, 300])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        # Status bar
        self.status_label = QLabel("Prêt  |  Clic gauche : ajouter point  |  Ctrl+clic : coordonnées exactes  |  Ctrl+I : liste de coords  |  Drag sommet : déplacer  |  Clic droit : menu")
        self.status_label.setFont(QFont("Arial", 9))
        status = QStatusBar()
        status.addWidget(self.status_label)
        self.setStatusBar(status)

        # Wire signals
        self.left.section_requested.connect(self._on_section_requested)
        self.left.grid_changed.connect(self._on_grid_changed)
        self.left.coord_dialog_requested.connect(self.canvas._open_coord_dialog)
        self.canvas.section_changed.connect(self._on_geometry_changed)
        self.canvas.section_changed.connect(self._mark_modified)
        self.props.fea_requested.connect(self._on_fea_requested)
        self.props.analytic_requested.connect(self._on_compute_analytic)
        self.props.mesh_visibility_changed.connect(self._on_mesh_visibility_changed)
        self.props.mesh_quality_changed.connect(self._on_mesh_quality_changed)
        self.props.fiche_requested.connect(self._export_fiche)
        self.left.new_polygon_requested.connect(self.canvas.start_new_polygon)

        # Init grid
        self.canvas.grid_spacing = self.left.grid_spin.value()
        self.canvas.snap_enabled = self.left.snap_check.isChecked()

        # État initial du panneau : aucune section.
        self.props.clear()

    def _build_menu(self):
        mb = QMenuBar()
        self.setMenuBar(mb)

        # Fichier
        mf = QMenu("Fichier", self)
        mb.addMenu(mf)
        a_new = QAction("Nouveau", self)
        a_new.setShortcut(QKeySequence("Ctrl+N"))
        a_new.triggered.connect(self._new_project)
        mf.addAction(a_new)

        mf.addSeparator()

        a_open = QAction("Ouvrir projet...", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_project)
        mf.addAction(a_open)

        # Sous-menu des sections d'exemple fournies (dossier exemples/)
        self._build_examples_menu(mf)

        a_save = QAction("Enregistrer", self)
        a_save.setShortcut(QKeySequence("Ctrl+S"))
        a_save.triggered.connect(self._save_project)
        mf.addAction(a_save)

        a_saveas = QAction("Enregistrer sous...", self)
        a_saveas.setShortcut(QKeySequence("Ctrl+Shift+S"))
        a_saveas.triggered.connect(self._save_project_as)
        mf.addAction(a_saveas)

        mf.addSeparator()

        a_img = QAction("Importer image de fond...", self)
        a_img.triggered.connect(self.canvas.import_background)
        mf.addAction(a_img)

        mf.addSeparator()

        a_export = QAction("Exporter propriétés CSV...", self)
        a_export.triggered.connect(self.props._export_csv)
        mf.addAction(a_export)

        a_report = QAction("Exporter rapport HTML...", self)
        a_report.setShortcut(QKeySequence("Ctrl+R"))
        a_report.triggered.connect(self._export_report)
        mf.addAction(a_report)

        a_fiche = QAction("Exporter fiche...", self)
        a_fiche.setShortcut(QKeySequence("Ctrl+Shift+R"))
        a_fiche.triggered.connect(self._export_fiche)
        mf.addAction(a_fiche)

        mf.addSeparator()
        a_quit = QAction("Quitter", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        mf.addAction(a_quit)

        # Édition
        me = QMenu("Édition", self)
        mb.addMenu(me)
        a_undo = QAction("Annuler", self)
        a_undo.setShortcut(QKeySequence("Ctrl+Z"))
        a_undo.triggered.connect(self._undo)
        me.addAction(a_undo)

        a_redo = QAction("Rétablir", self)
        a_redo.setShortcut(QKeySequence("Ctrl+Y"))
        a_redo.triggered.connect(self._redo)
        me.addAction(a_redo)

        # Vue
        mv = QMenu("Vue", self)
        mb.addMenu(mv)
        a_fit = QAction("Ajuster la vue (F)", self)
        a_fit.setShortcut(QKeySequence("F"))
        a_fit.triggered.connect(self.canvas.fit_view)
        mv.addAction(a_fit)

        a_clear = QAction("Tout effacer", self)
        a_clear.setShortcut(QKeySequence("Delete"))
        a_clear.triggered.connect(self.canvas.clear_all)
        mv.addAction(a_clear)

        mv.addSeparator()
        self._act_dark = QAction("Thème sombre", self)
        self._act_dark.setCheckable(True)
        self._act_dark.setShortcut(QKeySequence("Ctrl+D"))
        self._act_dark.toggled.connect(self._toggle_dark_theme)
        mv.addAction(self._act_dark)

        # Aide
        mh = QMenu("Aide", self)
        mb.addMenu(mh)
        a_about = QAction("À propos", self)
        a_about.triggered.connect(self._show_about)
        mh.addAction(a_about)

        a_shortcuts = QAction("Raccourcis clavier", self)
        a_shortcuts.triggered.connect(self._show_shortcuts)
        mh.addAction(a_shortcuts)

    def _build_toolbar(self):
        tb = QToolBar("Outils", self)
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Nouveau
        a_new = QAction("Nouveau", self)
        a_new.setToolTip("Nouveau projet (Ctrl+N)")
        a_new.triggered.connect(self._new_project)
        tb.addAction(a_new)

        # Ouvrir
        a_open_tb = QAction("Ouvrir...", self)
        a_open_tb.setToolTip("Ouvrir un projet (.json) (Ctrl+O)")
        a_open_tb.triggered.connect(self._open_project)
        tb.addAction(a_open_tb)

        # Enregistrer
        a_save_tb = QAction("Enregistrer", self)
        a_save_tb.setToolTip("Enregistrer le projet (Ctrl+S)")
        a_save_tb.triggered.connect(self._save_project)
        tb.addAction(a_save_tb)

        tb.addSeparator()

        # Image
        a_img = QAction("Image...", self)
        a_img.setToolTip("Importer une image de fond")
        a_img.triggered.connect(self.canvas.import_background)
        tb.addAction(a_img)

        # Ajuster vue
        a_fit = QAction("Ajuster", self)
        a_fit.setToolTip("Zoom ajuster — adapter la vue (F)")
        a_fit.triggered.connect(self.canvas.fit_view)
        tb.addAction(a_fit)

        tb.addSeparator()

        # Grille (toggle)
        self._act_grid = QAction("Grille", self)
        self._act_grid.setToolTip("Afficher / masquer la grille")
        self._act_grid.setCheckable(True)
        self._act_grid.setChecked(True)
        # Ensure canvas has the flag
        if not hasattr(self.canvas, "grid_visible"):
            self.canvas.grid_visible = True
        self._act_grid.toggled.connect(self._toggle_grid)
        tb.addAction(self._act_grid)

        # Snap (toggle)
        self._act_snap = QAction("Snap", self)
        self._act_snap.setToolTip("Activer / désactiver l'accrochage à la grille (G)")
        self._act_snap.setCheckable(True)
        self._act_snap.setChecked(self.canvas.snap_enabled)
        self._act_snap.toggled.connect(self._toggle_snap)
        # Keep toolbar snap in sync when left panel checkbox changes
        self.left.snap_check.toggled.connect(self._sync_snap_from_panel)
        tb.addAction(self._act_snap)

        # Rapport HTML
        a_report_tb = QAction("Rapport", self)
        a_report_tb.setToolTip("Exporter rapport HTML... (Ctrl+R)")
        a_report_tb.triggered.connect(self._export_report)
        tb.addAction(a_report_tb)

        # Fiche d'archive (A4 paysage, style PYTHAGORE)
        a_fiche_tb = QAction("Fiche", self)
        a_fiche_tb.setToolTip("Exporter fiche... (Ctrl+Shift+R)")
        a_fiche_tb.triggered.connect(self._export_fiche)
        tb.addAction(a_fiche_tb)

        tb.addSeparator()

        # Effacer
        a_clear = QAction("Effacer", self)
        a_clear.setToolTip("Tout effacer (Suppr)")
        a_clear.triggered.connect(self.canvas.clear_all)
        tb.addAction(a_clear)

    def _undo(self):
        state = self.canvas._undo_stack.undo()
        if state:
            self.canvas._restore_undo_state(state)

    def _redo(self):
        state = self.canvas._undo_stack.redo()
        if state:
            self.canvas._restore_undo_state(state)

    def _toggle_grid(self, checked: bool):
        self.canvas.grid_visible = checked
        self.canvas.update()

    def _toggle_snap(self, checked: bool):
        self.canvas.snap_enabled = checked
        self.canvas.update()
        # Synchronise the left panel checkbox without re-triggering this slot
        self.left.snap_check.blockSignals(True)
        self.left.snap_check.setChecked(checked)
        self.left.snap_check.blockSignals(False)

    def _sync_snap_from_panel(self, checked: bool):
        """Called when the left panel snap checkbox changes; mirrors to toolbar action."""
        self._act_snap.blockSignals(True)
        self._act_snap.setChecked(checked)
        self._act_snap.blockSignals(False)
        self.canvas.snap_enabled = checked
        self.canvas.update()

    def _on_section_requested(self, outers, holes, metadata=None):
        """Called when left panel generates a parametric/catalog section."""
        self._section_metadata = metadata if metadata is not None else {}
        self._metadata_fresh = True          # conservée jusqu'au prochain calcul
        self._loading_new_geometry = True    # chargement, pas une édition
        self.canvas.set_polygons(outers, holes)

    def _on_grid_changed(self, spacing, snap):
        self.canvas.grid_spacing = spacing
        self.canvas.snap_enabled = snap
        self.canvas.update()

    def _on_geometry_changed(self):
        """
        Appelé à chaque modification de géométrie. Ne calcule RIEN (les calculs sont
        déclenchés par les boutons). Marque les résultats affichés comme obsolètes et
        retire l'overlay du canvas dont les positions sont devenues invalides.
        """
        # Invalide les calculs : génération courante, et un éventuel résultat FEA
        # mémorisé (pour le rapport) ne s'applique plus.
        self._fea_generation += 1
        self._last_fea_results = None

        # Métadonnée de section : conservée lors de l'émission propre d'un chargement
        # paramétrique (pour le futur calcul), effacée à toute édition manuelle.
        if self._metadata_fresh:
            self._metadata_fresh = False
        else:
            self._section_metadata = {}

        loading = self._loading_new_geometry
        self._loading_new_geometry = False

        outers = self.canvas.get_outer_polygons()
        holes = self.canvas.get_hole_polygons()

        # Retire centroïde / axes / centre de cisaillement / maillage du canvas.
        self.canvas.clear_results_overlay()

        if not outers:
            self.props.clear()
            self.status_label.setText("Aucune section définie.")
            return

        n_poly = len(outers) + len(holes)
        if loading or not self.props.has_results():
            # Nouvelle section (chargée ou premier tracé) : rien de calculé encore.
            self.props.set_not_computed()
            self.status_label.setText(
                f"{n_poly} polygone(s) — cliquez « Calculer » pour afficher les propriétés."
            )
        else:
            # Des résultats étaient affichés : ils deviennent obsolètes.
            self.props.set_stale(True)
            self.status_label.setText(
                f"{n_poly} polygone(s) — géométrie modifiée : résultats obsolètes, "
                f"relancez le calcul."
            )

    def _on_compute_analytic(self):
        """Calcule les propriétés par le moteur analytique (déclenché par le bouton)."""
        outers = self.canvas.get_outer_polygons()
        holes = self.canvas.get_hole_polygons()
        if not outers:
            QMessageBox.warning(self, "Calcul", "Aucune section à calculer.")
            return
        try:
            results = compute_properties(outers, holes, self._section_metadata)
        except Exception as e:
            self.status_label.setText(f"Erreur de calcul : {e}")
            QMessageBox.critical(self, "Erreur de calcul", str(e))
            return
        if results.area <= 0:
            self.props.set_not_computed("Géométrie invalide (aire nulle).")
            self.canvas.clear_results_overlay()
            self.status_label.setText("Géométrie invalide (aire nulle).")
            return
        props = results_to_dict(results, self._section_metadata)
        self.props.show_analytic_results(props)
        self.canvas.update_section_display(results)
        self.canvas.set_fea_mesh(None, None)   # l'analytique n'a pas de maillage
        self._last_fea_results = None          # le rapport reflète l'analytique
        a_cm2 = results.area * 1e-2
        n_poly = len(outers) + len(holes)
        self.status_label.setText(
            f"{n_poly} polygone(s)  |  A = {a_cm2:.3f} cm²  |  "
            f"Ix = {results.Ix * 1e-4:.2f} cm⁴  |  Iy = {results.Iy * 1e-4:.2f} cm⁴  |  "
            f"Centroïde G({results.xc:.1f}, {results.yc:.1f}) mm"
        )

    def _on_mesh_visibility_changed(self, visible: bool):
        self.canvas.set_mesh_visible(visible)

    def _on_mesh_quality_changed(self):
        """Changer la densité de maillage rend les résultats FEA affichés obsolètes."""
        if self.props.is_fea_displayed() and not self.props.is_stale():
            self.props.set_stale(True, reason="mesh")
            self.canvas.set_fea_mesh(None, None)   # le maillage affiché ne correspond plus
            self._last_fea_results = None           # le rapport ne réutilise plus ce FEA
            self.status_label.setText(
                "Densité de maillage modifiée — relancez « Calculer (FEA) »."
            )

    # ------------------------------------------------------------------
    # Analyse FEA (sectionproperties) — lancée à la demande, en arrière-plan
    # ------------------------------------------------------------------
    def _on_fea_requested(self, quality: str):
        """Lance une analyse sectionproperties dans un thread d'arrière-plan."""
        if self._fea_worker is not None and self._fea_worker.isRunning():
            return  # une analyse est déjà en cours

        outers = self.canvas.get_outer_polygons()
        holes = self.canvas.get_hole_polygons()
        if not outers:
            QMessageBox.warning(self, "Analyse FEA", "Aucune section à analyser.")
            return

        from ui.fea_worker import FEAWorker
        self.props.set_fea_busy(True)
        self.status_label.setText(f"Analyse FEA (maillage « {quality} ») en cours…")

        # Mémorise la génération de géométrie soumise à ce calcul.
        self._fea_launch_generation = self._fea_generation

        # parent=self : Qt conserve la propriété de l'objet (évite une destruction
        # prématurée du QThread par le GC Python).
        worker = FEAWorker(outers, holes, self._section_metadata, quality, parent=self)
        worker.succeeded.connect(self._on_fea_succeeded)
        worker.failed.connect(self._on_fea_failed)
        worker.finished.connect(self._on_fea_finished)
        self._fea_worker = worker
        worker.start()

    def _on_fea_succeeded(self, results):
        # Ignore un résultat devenu périmé : la géométrie a changé (édition, nouveau
        # projet, ouverture) depuis le lancement de ce calcul.
        if self._fea_launch_generation != self._fea_generation:
            self.status_label.setText(
                "Analyse FEA ignorée (géométrie modifiée pendant le calcul). "
                "Relancez « Calculer (FEA) »."
            )
            return

        from calculators.sp_backend import fea_results_to_dict
        # Conserve les résultats pour le rapport HTML (tant que la géométrie n'a pas changé).
        self._last_fea_results = results
        self._last_fea_gen = self._fea_generation
        props = fea_results_to_dict(results)
        src = (f"Moteur : sectionproperties (FEA) — maillage « {results.quality} », "
               f"{results.n_elements} éléments")
        self.props.show_fea_results(props, src, results.warnings)
        # Centroïde, axes principaux et centre de cisaillement issus du FEA sur le canvas
        self.canvas.update_section_display(results)
        # Maillage FEA disponible pour la visualisation (selon l'état de la case).
        self.canvas.set_fea_mesh(results.mesh_vertices, results.mesh_triangles)
        self.canvas.set_mesh_visible(self.props.mesh_check.isChecked())
        a_cm2 = results.area * 1e-2
        msg = (f"FEA terminée  |  A = {a_cm2:.3f} cm²  |  "
               f"Ix = {results.Ix * 1e-4:.2f} cm⁴")
        if results.warping_valid:
            msg += (f"  |  J = {results.J * 1e-4:.3f} cm⁴  |  "
                    f"Cw = {results.Cw * 1e-6:.3f} cm⁶")
        else:
            msg += "  |  J/Cw non calculés (régions disjointes)"
        self.status_label.setText(msg)

    def _on_fea_failed(self, message: str):
        QMessageBox.critical(self, "Analyse FEA échouée", message)
        self.status_label.setText(f"Analyse FEA échouée : {message}")

    def _on_fea_finished(self):
        self.props.set_fea_busy(False)
        # Différer la destruction à la boucle d'évènements (ne jamais détruire un
        # QThread depuis son propre slot finished).
        worker = self._fea_worker
        self._fea_worker = None
        if worker is not None:
            worker.deleteLater()

    def _export_report(self):
        outers = self.canvas.get_outer_polygons()
        holes = self.canvas.get_hole_polygons()
        if not outers:
            QMessageBox.warning(self, "Rapport", "Aucune section à exporter.")
            return

        # Si une analyse FEA récente correspond à la géométrie courante, on
        # l'utilise pour le rapport (J, Cw, centre de cisaillement précis) afin que
        # le rapport reflète ce qui est affiché ; sinon on recalcule en analytique.
        if (self._last_fea_results is not None
                and self._last_fea_gen == self._fea_generation):
            from calculators.sp_backend import fea_results_to_dict
            results = self._last_fea_results
            props = fea_results_to_dict(results)
            engine_label = (f"sectionproperties (FEM) — maillage « {results.quality} », "
                            f"{results.n_elements} éléments")
        else:
            from calculators.section_properties import compute_properties, results_to_dict
            results = compute_properties(outers, holes, self._section_metadata)
            props = results_to_dict(results, self._section_metadata)
            engine_label = "analytique (shoelace / FDM / BEM)"

        from ui.report_dialog import ReportOptionsDialog
        dlg = ReportOptionsDialog(self, outers, holes, results, props,
                                  engine_label=engine_label)
        dlg.exec()

    def _export_fiche(self):
        outers = self.canvas.get_outer_polygons()
        holes = self.canvas.get_hole_polygons()
        if not outers:
            QMessageBox.warning(self, "Fiche", "Aucune section à exporter.")
            return

        # Meme selection de moteur que _export_report : on privilegie une analyse
        # FEA recente correspondant a la geometrie courante (J, Cw, centre de
        # cisaillement, aires de cisaillement precis) ; sinon calcul analytique.
        # La fiche relit les attributs bruts de `results`, on ne calcule pas de
        # dict de proprietes.
        if (self._last_fea_results is not None
                and self._last_fea_gen == self._fea_generation):
            results = self._last_fea_results
            engine_label = (f"sectionproperties (FEM) — maillage « {results.quality} », "
                            f"{results.n_elements} éléments")
        else:
            from calculators.section_properties import compute_properties
            results = compute_properties(outers, holes, self._section_metadata)
            engine_label = "analytique (shoelace / FDM / BEM)"

        from ui.fiche_dialog import FicheOptionsDialog
        dlg = FicheOptionsDialog(self, outers, holes, results,
                                 engine_label=engine_label)
        dlg.exec()

    def _show_about(self):
        QMessageBox.about(self, "À propos", (
            "<b>SectionCAD</b><br>"
            "Outil de géométrie de sections transversales<br>"
            "pour le génie civil et la construction métallique.<br><br>"
            "Supports : sections paramétriques, catalogue européen<br>"
            "(IPE, HEA, HEB, UPN, cornières), dessin libre avec<br>"
            "import d'image et calibration d'échelle.<br><br>"
            "Calcule : A, centroïde, Iy, Iz, Iyz,<br>"
            "axes principaux, Sx, Sy, Zx, Zy, rx, ry, centre de cisaillement."
        ))

    def _show_shortcuts(self):
        QMessageBox.information(self, "Raccourcis clavier", (
            "Dessin\n"
            "-------\n"
            "Clic gauche         Ajouter sommet\n"
            "Shift + clic        Nouveau polygone / trou (même à l'intérieur)\n"
            "Ctrl + clic         Saisir coordonnées exactes\n"
            "Ctrl + I            Saisir liste de coordonnées (tableau)\n"
            "Drag sommet         Déplacer un sommet existant\n"
            "Entrée / Dbl-clic   Fermer polygone (contour)\n"
            "H                   Fermer comme trou (soustraction)\n"
            "Ctrl+Z              Annuler dernier point / polygone (undo)\n"
            "Ctrl+Y              Rétablir (redo)\n"
            "Suppr               Tout effacer\n\n"
            "Vue\n"
            "-------\n"
            "Molette             Zoom\n"
            "Clic molette + drag Panoramique\n"
            "F                   Ajuster la vue\n"
            "G                   Activer/désactiver l'accrochage\n\n"
            "Image\n"
            "-------\n"
            "Clic droit → Importer image de fond\n"
            "Clic droit → Calibrer l'échelle (2 points)\n"
        ))

    # ------------------------------------------------------------------
    # Dark theme
    # ------------------------------------------------------------------

    _DARK_QSS = """
        QWidget          { background: #1e1e1e; color: #e0e0e0; }
        QMainWindow      { background: #1e1e1e; }
        QMenuBar         { background: #2d2d2d; color: #e0e0e0; }
        QMenuBar::item:selected { background: #3a3a3a; }
        QMenu            { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; }
        QMenu::item:selected    { background: #3c6ea0; }
        QToolBar         { background: #2d2d2d; border-bottom: 1px solid #444; }
        QToolButton      { background: transparent; color: #e0e0e0; padding: 4px 6px;
                           border: none; border-radius: 3px; }
        QToolButton:hover       { background: #3a3a3a; }
        QToolButton:pressed     { background: #3c6ea0; }
        QToolButton:checked     { background: #2a5080; }
        QSplitter::handle       { background: #3a3a3a; }
        QScrollArea      { background: #252525; border: none; }
        QTableWidget     { background: #252525; color: #e0e0e0;
                           alternate-background-color: #2c2c32;
                           gridline-color: #3a3a3a; selection-background-color: #3c6ea0; }
        QTableWidget QHeaderView::section { background: #2d2d2d; color: #aaa;
                                             border: 1px solid #444; }
        QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox
                         { background: #2d2d2d; color: #e0e0e0; border: 1px solid #555;
                           border-radius: 3px; padding: 2px 4px; }
        QGroupBox        { color: #aaa; border: 1px solid #444; border-radius: 4px;
                           margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; padding: 0 4px; }
        QPushButton      { background: #3a3a3a; color: #e0e0e0; border: 1px solid #555;
                           border-radius: 3px; padding: 4px 12px; }
        QPushButton:hover       { background: #4a4a4a; }
        QPushButton:pressed     { background: #3c6ea0; }
        QTabWidget::pane        { border: 1px solid #444; }
        QTabBar::tab     { background: #2d2d2d; color: #aaa; padding: 5px 10px;
                           border: 1px solid #444; }
        QTabBar::tab:selected   { background: #3c6ea0; color: white; }
        QStatusBar       { background: #2d2d2d; color: #aaa; }
        QLabel           { background: transparent; }
        QCheckBox        { color: #e0e0e0; }
    """

    def _toggle_dark_theme(self, dark: bool):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        app.setStyleSheet(self._DARK_QSS if dark else "")
        self.canvas.apply_theme(dark)   # applique toutes les couleurs du canvas
        self.props.set_dark_mode(dark)
        self.left.set_dark_mode(dark)

    # ------------------------------------------------------------------
    # Project modification tracking
    # ------------------------------------------------------------------

    def _mark_modified(self):
        if not self._modified:
            self._modified = True
            self._update_title()

    def _update_title(self):
        name = os.path.basename(self._current_file) if self._current_file else "Sans titre"
        marker = " *" if self._modified else ""
        self.setWindowTitle(f"SectionCAD — {name}{marker}")

    def _confirm_discard(self) -> bool:
        """Return True if user is OK to discard unsaved changes (or there are none)."""
        if not self._modified:
            return True
        reply = QMessageBox.question(
            self,
            "Modifications non enregistrées",
            "Le projet a été modifié. Enregistrer avant de continuer ?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self._save_project()
        if reply == QMessageBox.StandardButton.Discard:
            return True
        return False  # Cancel

    def closeEvent(self, event):
        if self._confirm_discard():
            # Attend la fin d'une éventuelle analyse FEA pour ne pas détruire
            # un QThread encore en cours d'exécution.
            if self._fea_worker is not None and self._fea_worker.isRunning():
                # sectionproperties n'est pas interruptible : si 3 s ne suffisent
                # pas, on attend la fin complète plutôt que de détruire un QThread
                # encore actif (sinon crash « QThread destroyed while running »).
                if not self._fea_worker.wait(3000):
                    self._fea_worker.wait()
            event.accept()
        else:
            event.ignore()

    # ------------------------------------------------------------------
    # New / Open / Save
    # ------------------------------------------------------------------

    def _new_project(self):
        if not self._confirm_discard():
            return
        self.canvas.section_changed.disconnect(self._mark_modified)
        self.canvas.clear_all()
        self.canvas.section_changed.connect(self._mark_modified)
        self._current_file = None
        self._modified = False
        self._section_metadata = {}
        self._update_title()

    def _save_project(self) -> bool:
        """Save to current file, or prompt for path. Returns True on success."""
        if self._current_file:
            return self._write_project(self._current_file)
        return self._save_project_as()

    def _save_project_as(self) -> bool:
        """Prompt for path and save. Returns True on success."""
        default = os.path.splitext(self._current_file)[0] if self._current_file else "section"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le projet",
            default + ".scad",
            "SectionCAD (*.scad);;JSON (*.json);;Tous les fichiers (*)",
        )
        if not path:
            return False
        return self._write_project(path)

    def _write_project(self, path: str) -> bool:
        try:
            data = {
                "version": 1,
                "app": "SectionCAD",
                "grid_spacing": self.canvas.grid_spacing,
                "snap_enabled": self.canvas.snap_enabled,
                "polygons": [
                    {"pts": [[x, y] for x, y in pts], "is_hole": is_hole}
                    for pts, is_hole in self.canvas.polygons
                ],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._current_file = path
            self._modified = False
            self._update_title()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Erreur d'enregistrement",
                                 f"Impossible d'enregistrer :\n{exc}")
            return False

    def _open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir un projet",
            "",
            "SectionCAD (*.scad);;JSON (*.json);;Tous les fichiers (*)",
        )
        if not path:
            return
        self._load_project_file(path, as_template=False)

    def _load_project_file(self, path: str, as_template: bool = False) -> bool:
        """
        Charge un projet/exemple .scad dans le canvas.

        as_template=True (exemples) : la géométrie est chargée comme point de
        départ, sans associer le fichier source (Enregistrer demandera un chemin).
        Renvoie True en cas de succès.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("app") != "SectionCAD":
                QMessageBox.warning(self, "Format inconnu",
                                    "Ce fichier ne semble pas être un projet SectionCAD.")
                return False
            raw = data.get("polygons", [])
            self.canvas.polygons.clear()
            self.canvas.current_points.clear()
            for entry in raw:
                pts = [tuple(pt) for pt in entry["pts"]]
                is_hole = bool(entry.get("is_hole", False))
                self.canvas.polygons.append((pts, is_hole))
            self.canvas.grid_spacing = float(data.get("grid_spacing", 10.0))
            self.canvas.snap_enabled = bool(data.get("snap_enabled", True))
            # Sync left panel controls
            self.left.grid_spin.setValue(self.canvas.grid_spacing)
            self.left.snap_check.setChecked(self.canvas.snap_enabled)
            self._act_snap.setChecked(self.canvas.snap_enabled)
            self.canvas.fit_view()
            self._section_metadata = {}
            self._metadata_fresh = False
            self._loading_new_geometry = True   # chargement -> état « à calculer »
            self.canvas.section_changed.disconnect(self._mark_modified)
            self.canvas.section_changed.emit()
            self.canvas.section_changed.connect(self._mark_modified)
            self._current_file = None if as_template else path
            self._modified = False
            self._update_title()
            if as_template:
                name = data.get("name", os.path.basename(path))
                self.status_label.setText(
                    f"Exemple chargé : {name}. Cliquez « Calculer (FEA) » pour "
                    f"l'analyse par éléments finis."
                )
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Erreur d'ouverture",
                                 f"Impossible de charger le fichier :\n{exc}")
            return False

    def _open_example(self, path: str):
        if not self._confirm_discard():
            return
        self._load_project_file(path, as_template=True)

    def _examples_dir(self) -> str:
        # Sous PyInstaller, les donnees embarquees (dont exemples/) sont
        # extraites dans sys._MEIPASS ; en mode developpement on resout par
        # rapport au source. Sans cette branche, « Ouvrir un exemple » serait
        # vide dans l'exe (cf. DISTRIBUTION.md).
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return os.path.join(base, "exemples")
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "exemples")

    def _build_examples_menu(self, parent_menu):
        """Construit le sous-menu « Ouvrir un exemple » à partir du dossier exemples/."""
        sub = QMenu("Ouvrir un exemple", self)
        parent_menu.addMenu(sub)
        ex_dir = self._examples_dir()
        files = sorted(glob.glob(os.path.join(ex_dir, "*.scad"))) if os.path.isdir(ex_dir) else []
        if not files:
            act = QAction("(aucun exemple disponible)", self)
            act.setEnabled(False)
            sub.addAction(act)
            return
        for path in files:
            label = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                label = meta.get("name", label)
            except Exception:
                pass
            act = QAction(label, self)
            act.triggered.connect(lambda checked=False, p=path: self._open_example(p))
            sub.addAction(act)

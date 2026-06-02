"""Dialogue de configuration et d'export de la « fiche » d'archive (PYTHAGORE).

Calque sur ui/report_dialog.py (ReportOptionsDialog) : un groupe
« Identification » (cartouche editable) et un groupe « Options » a deux cases
plates et independantes :

- « Remplir la matiere » (``show_fill``, defaut True) : grise l'interieur de la
  section (trous laisses en blanc) ;
- « Superposer le maillage FEM » (``show_mesh``) : ACTIVEE uniquement si
  ``results`` porte un maillage (moteur FEM), exactement comme ReportOptionsDialog
  gere ``_has_mesh``.

Les options KY/KZ ont ete RETIREES (grandeurs non calculees par SectionCAD).
Les imports de ``reports.fiche_report`` sont differes (late import) afin de ne
pas alourdir le demarrage de l'application.
"""
import os
import tempfile
import webbrowser

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit, QCheckBox,
    QPushButton, QFileDialog, QMessageBox, QFormLayout, QSizePolicy,
)
from PyQt6.QtCore import Qt


class FicheOptionsDialog(QDialog):
    """
    Affiche les options de la fiche et declenche l'export quand confirme.

    Parameters
    ----------
    parent : QWidget
        Fenetre parente.
    outers : list
        Liste des contours exterieurs (listes de points).
    holes : list
        Liste des trous (listes de points).
    results : object
        Objet de resultats (``SectionResults`` analytique ou ``FEAResults`` FEM).
        La fiche relit ses attributs bruts (mm) ; on ne passe PAS de dict.
    engine_label : str
        Libelle du moteur de calcul (affiche en note).
    """

    def __init__(self, parent, outers, holes, results, engine_label=""):
        super().__init__(parent)
        self.setWindowTitle("Exporter la fiche")
        self.setMinimumWidth(480)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._outers = outers
        self._holes = holes
        self._results = results
        self._engine_label = engine_label
        # Le maillage n'est disponible que si les resultats proviennent d'un
        # calcul FEA (meme schema que ReportOptionsDialog._has_mesh).
        self._has_mesh = bool(getattr(results, "mesh_triangles", None))

        self._build_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- Identification (cartouche editable) -----------------------
        grp = QGroupBox("Identification")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        app_name = ""
        if self.parent() is not None:
            app_name = getattr(self.parent(), "windowTitle", lambda: "")() or ""

        self._ed_module = QLineEdit(app_name or "PYTHAGORE V22.05 - CISAIL")
        self._ed_numero = QLineEdit()
        self._ed_designation = QLineEdit()
        self._ed_type = QLineEdit()
        self._ed_titre = QLineEdit("CARACTERISTIQUES DE LA SECTION")

        self._ed_numero.setPlaceholderText("ex : TYPE No 5001")
        self._ed_designation.setPlaceholderText("ex : PdR - Semelle Inf.")
        self._ed_type.setPlaceholderText("ex : Type I")

        form.addRow("Module / logiciel :", self._ed_module)
        form.addRow("Numero :",            self._ed_numero)
        form.addRow("Designation :",       self._ed_designation)
        form.addRow("Type / localisation :", self._ed_type)
        form.addRow("Titre de la fiche :", self._ed_titre)

        layout.addWidget(grp)

        # ---- Options ---------------------------------------------------
        # Deux interrupteurs plats et independants : aucune relation
        # parent/enfant a synchroniser (plus simple que ReportOptionsDialog,
        # et c'est voulu). Seule la case maillage est conditionnelle.
        grp_opt = QGroupBox("Options")
        opt_layout = QVBoxLayout(grp_opt)
        opt_layout.setSpacing(4)

        self._chk_fill = QCheckBox("Remplir la matiere (aire grisee)")
        self._chk_fill.setChecked(True)
        self._chk_fill.setToolTip(
            "Grise l'interieur de la section (trous laisses en blanc)."
        )
        opt_layout.addWidget(self._chk_fill)

        self._chk_mesh = QCheckBox("Superposer le maillage FEM")
        self._chk_mesh.setChecked(self._has_mesh)
        self._chk_mesh.setEnabled(self._has_mesh)
        if not self._has_mesh:
            self._chk_mesh.setToolTip(
                "Disponible uniquement avec un calcul FEA recent."
            )
        opt_layout.addWidget(self._chk_mesh)

        layout.addWidget(grp_opt)

        # ---- Boutons ---------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_preview = QPushButton("Apercu navigateur")
        self._btn_preview.setToolTip("Generer la fiche et l'ouvrir dans le navigateur")
        self._btn_preview.clicked.connect(self._preview_in_browser)
        btn_layout.addWidget(self._btn_preview)

        self._btn_export = QPushButton("Imprimer / Enregistrer fiche...")
        self._btn_export.setToolTip("Enregistrer la fiche HTML (impression PDF via le navigateur)")
        self._btn_export.setDefault(True)
        self._btn_export.clicked.connect(self._export_to_file)
        btn_layout.addWidget(self._btn_export)

        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Construction des options
    # ------------------------------------------------------------------

    def get_options(self):
        """Retourne un objet ``FicheOptions`` refletant l'etat du dialogue."""
        from reports.fiche_report import FicheOptions  # late import

        # ``show_mesh`` : on applique le meme motif que ReportOptionsDialog._on
        # (coche ET active) ; le 'and isEnabled()' garantit show_mesh=False en
        # l'absence de maillage, meme si un etat coche etait residuel.
        return FicheOptions(
            titre_module=self._ed_module.text().strip() or "PYTHAGORE V22.05 - CISAIL",
            numero=self._ed_numero.text().strip(),
            designation=self._ed_designation.text().strip(),
            type_piece=self._ed_type.text().strip(),
            titre_fiche=self._ed_titre.text().strip() or "CARACTERISTIQUES DE LA SECTION",
            show_fill=self._chk_fill.isChecked(),
            show_mesh=(self._chk_mesh.isChecked() and self._chk_mesh.isEnabled()),
            engine_label=self._engine_label,
        )

    # ------------------------------------------------------------------
    # Helpers d'export
    # ------------------------------------------------------------------

    def _do_export(self, filepath: str) -> bool:
        """Genere la fiche et l'ecrit dans *filepath*. Retourne True si succes."""
        try:
            from reports.fiche_report import export_fiche  # late import
            opts = self.get_options()
            export_fiche(opts, self._outers, self._holes, self._results, filepath)
            return True
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Module manquant",
                f"Le module de generation de fiche n'est pas disponible :\n{exc}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Erreur d'export",
                f"Impossible de generer la fiche :\n{exc}",
            )
        return False

    # ------------------------------------------------------------------
    # Gestionnaires de boutons
    # ------------------------------------------------------------------

    def _preview_in_browser(self):
        """Genere la fiche dans un fichier temporaire et l'ouvre au navigateur."""
        fd, tmp_path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        if self._do_export(tmp_path):
            webbrowser.open(f"file:///{tmp_path.replace(os.sep, '/')}")

    def _export_to_file(self):
        """Demande un chemin d'enregistrement et exporte la fiche."""
        default_name = "fiche_section.html"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer la fiche HTML",
            default_name,
            "Fiche HTML (*.html);;Tous les fichiers (*)",
        )
        if not path:
            return

        if self._do_export(path):
            QMessageBox.information(
                self,
                "Export reussi",
                f"Fiche enregistree :\n{path}",
            )
            self.accept()

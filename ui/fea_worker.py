"""
Worker d'arrière-plan pour l'analyse sectionproperties (FEA).

L'analyse de gauchissement (J, Cw) peut prendre de 0,1 à ~2 s ; la lancer dans le
thread principal figerait l'interface. Ce QThread exécute le backend pur
(calculators/sp_backend.py) hors du thread UI et communique le résultat via signaux.

Aucune primitive Qt graphique n'est touchée depuis run() — seules des données pures
(FEAResults) transitent, ce qui est sûr entre threads avec les connexions Qt.
"""
from PyQt6.QtCore import QThread, pyqtSignal

from calculators.sp_backend import compute_properties_fea, DEFAULT_QUALITY


class FEAWorker(QThread):
    succeeded = pyqtSignal(object)   # émet un FEAResults
    failed = pyqtSignal(str)         # émet un message d'erreur lisible

    def __init__(self, outer_polygons, hole_polygons, metadata=None,
                 quality=DEFAULT_QUALITY, parent=None):
        super().__init__(parent)
        # Copie défensive : la géométrie ne doit pas être mutée par l'UI pendant le calcul.
        self._outers = [list(p) for p in outer_polygons]
        self._holes = [list(p) for p in (hole_polygons or [])]
        self._metadata = dict(metadata) if metadata else {}
        self._quality = quality

    def run(self):
        try:
            results = compute_properties_fea(
                self._outers, self._holes, self._metadata, self._quality
            )
            self.succeeded.emit(results)
        except Exception as exc:  # remonté à l'UI via le signal failed
            self.failed.emit(str(exc))

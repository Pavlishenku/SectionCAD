"""SectionCAD — Entry point."""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow


def _resource_path(name: str) -> str:
    """Chemin d'une ressource embarquee : sys._MEIPASS sous PyInstaller, sinon
    le dossier du script (mode developpement)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SectionCAD")
    app.setStyle("Fusion")
    win = MainWindow()
    _icon_path = _resource_path("sectioncad.ico")
    if os.path.exists(_icon_path):
        _icon = QIcon(_icon_path)
        win.setWindowIcon(_icon)
        app.setWindowIcon(_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

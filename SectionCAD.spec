# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
#  SectionCAD.spec — recette de build PyInstaller (mode ONEDIR, --windowed)
# -----------------------------------------------------------------------------
#  Outil : PyInstaller 6.20+ (premiere version supportant Python 3.8-3.14).
#  Mode  : onedir (JAMAIS onefile) — onefile re-extrait 200-400 Mo dans %TEMP%
#          a chaque lancement (lent, suspect pour l'antivirus).
#  Lancer : uv run --group build pyinstaller --noconfirm SectionCAD.spec
#
#  Ce .spec couvre les pieges specifiques du stack scientifique :
#    - imports PARESSEUX (sectionproperties.analysis, shapely, dialogs) invisibles
#      a l'analyse statique  -> hidden-imports + collect_submodules
#    - DLL natives GEOS de shapely (noms hashes), OpenBLAS (numpy/scipy),
#      extensions C de cytriangle (.pyd), matplotlib (charge EAGEREMENT par
#      sectionproperties) -> collect_all
#    - dossier exemples/ resolu au RUNTIME -> embarque en datas (et le code doit
#      gerer sys._MEIPASS, cf. DISTRIBUTION.md : bug _examples_dir a corriger)
#    - LICENSE embarque -> conformite GPL-3 de la redistribution
# =============================================================================

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# --- Donnees a embarquer (format PyInstaller : (source, destination_dans_bundle)) ---
datas = [
    ("exemples", "exemples"),   # 10 *.scad + README, charges via « Ouvrir un exemple »
    ("LICENSE", "."),           # conformite GPL-3 (redistribution)
    ("sectioncad.ico", "."),    # icone fenetre (setWindowIcon resout via sys._MEIPASS)
]
binaries = []
hiddenimports = []

# --- collect_all : embarque code Python + donnees + binaires natifs ---
# sectionproperties : tire matplotlib/rich/more-itertools/cytriangle (deps dures).
# shapely           : DLL GEOS natives a noms hashes (geos_c-*.dll, geos-*.dll, msvcp140-*.dll).
# cytriangle        : extensions C compilees (cytriangle.cpXYZ-win_amd64.pyd) — maillage.
for _pkg in ("sectionproperties", "shapely", "cytriangle"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# --- collect_submodules : sous-modules souvent manques par l'analyse statique ---
# scipy.sparse / .spatial / .optimize / ._lib ... charges paresseusement par le FEA.
# matplotlib : backends Agg/QtAgg + contourpy, charge EAGEREMENT par sectionproperties.
for _pkg in ("scipy", "matplotlib"):
    hiddenimports += collect_submodules(_pkg)

# --- hidden-imports explicites : imports differes invisibles depuis main.py ---
hiddenimports += [
    "sectionproperties.analysis.section",  # importe au 1er calcul FEA (sp_backend._ensure_imports)
    "cytriangle",                          # maillage, charge a l'import de la section
    "cytriangleio",                        # idem (extension C compagne)
    "ui.fea_worker",                       # thread FEA, importe paresseusement
    "ui.report_dialog",                    # dialogue rapport, importe a la demande
    "ui.fiche_dialog",                     # dialogue fiche, importe a la demande
]

# --- Icone : OPTIONNELLE. Le depot n'en fournit aucune (confirme).
#     Deposer sectioncad.ico a la racine pour l'activer (16/32/48/256 px). ---
_icon_path = "sectioncad.ico"
icon = _icon_path if os.path.exists(_icon_path) else None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter inutile (PyQt6 fournit l'UI) : allege l'exe.
    excludes=["tkinter"],
    noarchive=False,
    # optimize=2 (equivaut a python -OO) : retire asserts ET docstrings du
    # bytecode embarque -> moins lisible si quelqu'un decompile le .pyc.
    # (Decision : l'utilisateur ne doit pas voir le source ; cf. DISTRIBUTION.md.)
    optimize=2,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir : binaires hors de l'exe, dans le dossier dist
    name="SectionCAD",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX deconseille avec PyQt6/DLL natives (faux positifs AV)
    console=False,           # --windowed : pas de console noire au lancement
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SectionCAD",       # -> dist/SectionCAD/  (dossier a empaqueter par Inno Setup)
)

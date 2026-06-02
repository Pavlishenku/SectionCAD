# SectionCAD

Application de bureau pour le calcul des propriétés géométriques de sections transversales quelconques.
Développée en Python 3.10+ (PyQt6, NumPy, SciPy, sectionproperties, Shapely).

Ce README en français fait foi. English version: [README.en.md](README.en.md).

> Statut : pré-version (v0).
> Le logiciel n'a pas été validé par rapport à une norme de dimensionnement reconnue.
> N'utilisez pas les résultats comme seule base d'une décision de dimensionnement structural
> sans vérification indépendante.

## ⬇️ Télécharger (Windows 10/11)

**[Télécharger la dernière version »](https://github.com/Pavlishenku/SectionCAD/releases/latest)** — récupérez `SectionCAD-portable.zip`, extrayez-le où vous voulez (Bureau, clé USB) et lancez `SectionCAD.exe`. **Aucune installation, aucun droit administrateur.**

---

## Prérequis et installation

Python ≥ 3.10, puis :

```
pip install -r requirements.txt
python main.py
```

Dépendances (`requirements.txt`) :

- PyQt6 — interface graphique
- numpy, scipy — calcul numérique
- sectionproperties ≥ 3.0 — analyse par éléments finis (J, Cw, centre de cisaillement, aires de cisaillement)
- shapely ≥ 2.0 — préparation géométrique (union/différence des contours)

---

## Démarrage rapide

1. Dessinez ou générez une section (onglets « Dessin », « Paramétrique », « Catalogue »),
   ou ouvrez un exemple fourni : menu Fichier → Ouvrir un exemple.
2. Cliquez sur « Calculer (analytique) » pour les propriétés géométriques rapides, ou sur
   « Calculer (FEA) » pour l'analyse par éléments finis (J, Cw, centre de cisaillement, etc.).
3. Si vous modifiez la géométrie, les résultats deviennent obsolètes (grisés) : relancez un calcul.
4. Exportez en CSV, copiez vers le presse-papiers, générez un rapport HTML, ou
   produisez une « fiche » d'archive A4 paysage (style PYTHAGORE).

Pour dessiner un trou (ou un polygone à l'intérieur d'un autre), utilisez Shift+clic
— ou le bouton « Nouveau contour / trou » — sinon le clic sélectionne le polygone existant.
Fermez ensuite avec Entrée (contour) ou la touche H (trou).

---

## Fonctionnalités

### Géométrie de la section

Une section est définie par un ou plusieurs polygones fermés, en millimètres, avec gestion des
trous (soustraction booléenne). Méthodes de saisie :

- Dessin à main levée sur le canvas (accrochage à la grille, déplacement de sommets).
- Saisie de coordonnées exactes (Ctrl+clic) ou par tableau (Ctrl+I).
- Générateurs paramétriques : rectangle, cercle, tube circulaire, profil en I, caisson, cornière,
  U (canal), profil en T, croix, carré creux, rectangulaire creux.
- Catalogue européen : IPE, HEA, HEB, HEM, UPN, cornières à ailes égales, CHS (EN 10210), RHS, SHS.
- Bibliothèque d'exemples (Fichier → Ouvrir un exemple) : sections `.scad` prêtes à l'emploi
  dérivées des notebooks de sectionproperties (canaux avec congés, canal à ailes inclinées,
  profil en Z, arc circulaire, trapèze, double-I fusionné, etc.). Voir le dossier [`exemples/`](exemples/).

### Modèle de calcul : à la demande

Aucun calcul n'est lancé automatiquement pendant le dessin. Le panneau de droite propose deux boutons :

- « Calculer (analytique) » — moteur analytique rapide (théorème de Green pour A, I, centre de
  gravité ; FDM pour la torsion des sections libres).
- « Calculer (FEA — sectionproperties) » — analyse par éléments finis (voir plus bas).

Obsolescence : dès que la géométrie change (déplacement de sommet, déplacement ou suppression de
polygone, collage, annuler/rétablir, conversion contour/trou, saisie de coordonnées, chargement
paramétrique/catalogue/exemple), les résultats affichés sont grisés et un bandeau indique qu'ils
sont obsolètes ; l'overlay du canvas (centre de gravité, axes principaux, centre de cisaillement,
maillage) est retiré. Relancez un calcul pour rafraîchir. Les actions de vue (zoom, panoramique,
grille, accrochage, thème, sélection) n'invalident jamais les résultats.

### Propriétés calculées — nomenclature Eurocode

Convention d'axes Eurocode (EN 1993) : y-y est l'axe fort (horizontal), z-z l'axe faible (vertical).
Le panneau affiche le symbole seul ; la description complète apparaît en info-bulle au survol (et en
colonne « Désignation » dans le CSV et le rapport). Symboles et descriptions sont centralisés dans
`calculators/nomenclature.py`.

| Symbole | Propriété | Méthode | Remarque |
|---|---|---|---|
| A | Aire | Théorème de Green | Exact pour les polygones |
| y_G, z_G | Centre de gravité | Théorème de Green | Exact |
| I_y, I_z, I_yz | Moments d'inertie (centroïdaux) | Intégration polygonale | Exact ; I_y = axe fort |
| I_1, I_2, α | Inerties principales / angle | Cercle de Mohr | Exact |
| W_el,y, W_el,z | Modules de flexion élastiques | I / distance à la fibre extrême | Exact |
| W_pl,y, W_pl,z | Modules de flexion plastiques | Bissection sur l'axe neutre plastique | Exact à la discrétisation près |
| i_y, i_z | Rayons de giration | √(I/A) | Exact |
| I_t | Constante de torsion (St-Venant) | analytique (types connus) / FDM / FEM | voir plus bas |
| I_w | Constante de gauchissement | FEM uniquement (sectionproperties) | non calculée en analytique |
| y_SC, z_SC | Centre de cisaillement | analytique (I/U/L/T) ou FEM | approché en analytique pour les sections quelconques |
| A_vy, A_vz | Aires de cisaillement | FEM uniquement | — |

Normalisation géométrique (partagée par les deux moteurs) : contours et trous sont d'abord combinés
en la vraie région matérielle (`calculators/geometry_prep.py`, via Shapely) — union des solides et
soustraction des trous, du plus grand au plus petit, de sorte que l'imbrication est respectée et que
les contours qui se chevauchent ou s'imbriquent ne sont pas comptés deux fois (le polygone le plus
interne l'emporte ; un îlot solide dans un trou est conservé). Les moteurs analytique et FEM
consomment cette même région, donc ils concordent par construction (accord à la précision machine
sur A, I_y, I_z).

### Torsion et gauchissement

La torsion est un sujet délicat : la précision dépend fortement du type de section et de la méthode.

Constante de torsion de St-Venant I_t :

| Type de section | Méthode | Erreur attendue |
|---|---|---|
| Cercle plein | Formule exacte I_t = π·D⁴/32 | Exact |
| CHS (tube circulaire) | Formule exacte π(D₀⁴ − Dᵢ⁴)/32 | Exact |
| Rectangle plein | Série de Timoshenko | < 1 % pour les élancements courants |
| Caisson fermé / RHS / SHS | Formule de Bredt 4·A²/∮(ds/t) | Exact pour parois minces uniformes |
| Sections ouvertes à parois minces (I, U, T, L) | Σ b·t³/3 | ±30 % ; congés et soudures ignorés |
| Sections quelconques / à main levée | FDM (fonction de Prandtl, grille ~150 cellules) | 3–8 % sur formes simples |

Attention : pour les sections ouvertes à parois minces, une erreur de ±30 % est réaliste. Hormis
cercles et CHS, considérez I_t analytique comme un ordre de grandeur — ou utilisez le moteur FEM.

Constante de gauchissement I_w (Cw) — FEM uniquement : elle n'est plus calculée par le moteur
analytique (son solveur BEM n'était pas fiable pour les sections générales). Elle est fournie
uniquement par le moteur FEM (sectionproperties), validé (IPE 300 : I_w = 125 800 cm⁶ contre
125 900 cm⁶ au catalogue, soit < 0,1 %).

### Analyse par éléments finis (sectionproperties)

Le bouton « Calculer (FEA) » lance une analyse par éléments finis (maillage triangulaire + solveur de
gauchissement) via le paquet [sectionproperties](https://github.com/robbievanleeuwen/section-properties).
C'est la méthode recommandée pour obtenir des valeurs précises de J, Cw, centre de cisaillement et
aires de cisaillement, pour n'importe quelle géométrie, y compris à main levée.

- S'exécute dans un thread d'arrière-plan : l'interface ne se fige jamais (le gauchissement prend
  ~0,1 à 2 s selon la densité). Un résultat est ignoré si la géométrie a changé pendant le calcul.
- Densité de maillage réglable (Grossier / Moyen / Fin) ; le nombre d'éléments est affiché. Un maillage
  plus fin converge mais est plus lent ; J et Cw sont en général stables à < 2 % d'une densité à
  l'autre. Changer la densité rend les résultats FEM affichés obsolètes.
- Visualisation du maillage : cochez « Afficher le maillage FEM » pour le superposer à la section.
- Trous gérés automatiquement, imbrication respectée (contour → trou → îlot solide → trou dans l'îlot…).
- Sections disjointes (plusieurs régions déconnectées, y compris un îlot solide flottant dans un trou) :
  les propriétés géométriques et plastiques sont calculées, mais le gauchissement (J, Cw, centre de
  cisaillement) ne l'est pas — un avertissement est affiché — car il exige une région d'un seul tenant.

L'export CSV, « Copier » et le rapport HTML reflètent les résultats actuellement affichés (analytiques
ou FEM). Le rapport HTML indique le moteur de calcul utilisé et, pour des résultats FEM, propose un
calque optionnel du maillage.

---

## Sorties

- Panneau de résultats : symboles Eurocode avec descriptions en info-bulle ; lignes colorées par
  groupe, grisées quand la géométrie change.
- Export CSV / Copier : symbole, désignation complète, valeur et unité.
- Rapport HTML : fichier autonome (géométrie SVG, maillage FEM optionnel, tableau symbole + désignation,
  section théorie, moteur de calcul) ; imprimable en PDF depuis le navigateur.
- Fiche (format rapport) : livrable d'archive HTML autonome au format A4 paysage, police monospace,
  encadré d'un filet noir fin, dans le style des fiches « caractéristiques de la section » de PYTHAGORE.
  Convention de repère Z (horizontal) / Y (vertical) ; tableau « Repère | Initial | Principal » (inerties,
  aires de cisaillement, coordonnées des points remarquables P/G/C, Itors, Iw, Section), dessin vectoriel
  épuré de la section (tracé filaire noir, axes principaux rouges centrés en G, flèche Y bleue, glyphes
  P triangle bleu / G cercle rouge / C carré vert), pied de page (DZ, DY, échelle). Menu Fichier
  → « Exporter fiche... » (Ctrl+Shift+R) ou bouton « Fiche » de la barre d'outils ; un dialogue propose
  des champs éditables (module, numéro, désignation, type/localisation, titre) et une option d'affichage
  des facteurs KY/KZ. Aperçu et impression PDF via `window.print()` depuis le navigateur. Le SVG est
  dimensionné en millimètres physiques pour une échelle imprimée à 100 % véritable.
- Sauvegarde/ouverture de projet : format `.scad` (JSON) conservant la géométrie des polygones.

---

## Formats de fichiers

| Extension | Description |
|---|---|
| `.scad` | Fichier projet — JSON contenant les sommets des polygones et les réglages de grille |
| `.csv` | Export des propriétés de section |
| `.html` | Rapport de calcul autonome, ou fiche d'archive A4 paysage (style PYTHAGORE) |

---

## Raccourcis clavier

| Touche | Action |
|---|---|
| Entrée / double-clic | Fermer le polygone courant en contour |
| H | Fermer le polygone courant en trou |
| Shift+clic | Démarrer un nouveau polygone : place le premier point même à l'intérieur d'un polygone existant (pour dessiner un trou). Équivaut au bouton « Nouveau contour / trou ». |
| Échap | Annuler le polygone courant / désélectionner |
| Ctrl+Z / Ctrl+Y | Annuler / Rétablir (100 niveaux) |
| Ctrl+C | Copier le polygone sélectionné |
| Ctrl+V | Coller (aperçu fantôme, clic pour placer) |
| Suppr | Supprimer le polygone sélectionné (ou tout effacer si aucun n'est sélectionné) |
| Ctrl+clic | Saisir des coordonnées exactes |
| Ctrl+I | Saisie de coordonnées en tableau |
| Ctrl+D | Basculer le thème sombre |
| Ctrl+O / Ctrl+S | Ouvrir / Enregistrer un projet |
| Ctrl+R | Exporter un rapport HTML |
| Ctrl+Shift+R | Exporter une fiche d'archive (A4 paysage) |
| F | Ajuster la vue à la géométrie |
| Molette / clic-molette + glisser | Zoom / panoramique |
| G | Activer/désactiver l'accrochage à la grille |

La grille reste visible à tout niveau de zoom : son pas s'adapte automatiquement (multiples de 10).

---

## Tests

```
pytest tests/
```

156 tests : propriétés analytiques (valeurs de référence), backend FEM (sectionproperties),
recoupements FEM/analytique sur A, I_y, I_z sur une large base de cas, solveur de torsion FDM,
normalisation géométrique (chevauchement / imbrication / îlots), grille adaptative du canvas.

---

## Limitations connues

Moteur analytique (bouton « Calculer (analytique) ») :

- I_t exact uniquement pour cercle, CHS, rectangle plein et caisson. Pour les sections ouvertes à
  parois minces : Σ b·t³/3 (±30 %, congés et soudures ignorés) ; pour les sections libres : grille
  FDM (150 cellules, ~3–8 %, parfois insuffisante pour des parois très fines ou de grands élancements).
- Centre de cisaillement exact uniquement pour les sections symétriques I, U, L, T ; sinon il est
  ramené au centre de gravité (incorrect).
- Constante de gauchissement I_w non calculée — utilisez le moteur FEM.

Moteur FEM (bouton « Calculer (FEA) », recommandé pour I_t, I_w, centre de cisaillement, aires de
cisaillement) :

- Le gauchissement (I_t, I_w, centre de cisaillement, aires de cisaillement) exige une région d'un
  seul tenant. Pour les sections déconnectées — y compris un îlot solide flottant dans un trou —
  ces valeurs sont marquées « n/d » ; les propriétés géométriques et plastiques restent calculées.
- Les résultats de gauchissement dépendent de la densité de maillage ; I_t/I_w sont en général
  stables à < 2 % entre densités.

Général :

- Les propriétés géométriques (A, I_y, I_z, I_yz, modules, rayons) concordent entre les deux moteurs
  à la précision machine et sont exactes pour les polygones.
- Les générateurs paramétriques produisent des angles vifs (sans congés) ; la bibliothèque d'exemples
  (`exemples/`) inclut des profils avec congés ou ailes inclinées pour des résultats FEM réalistes.
- Les profils du catalogue utilisent des dimensions nominales (sans tolérances de laminage ni congés
  de raccordement dans le polygone).
- Pas encore d'import/export DXF.
- Non validé par rapport à une norme de dimensionnement reconnue : vérifiez les résultats de manière
  indépendante avant tout usage en dimensionnement.

---

## Licence

Sous licence GNU General Public License v3.0 ou ultérieure (GPL-3.0-or-later) — voir le fichier
[`LICENSE`](LICENSE).

L'interface utilise PyQt6, distribué sous GPL v3 (Riverbank Computing). Une application redistribuée
liée à PyQt6 doit donc être compatible GPL, ce qui rend GPL-3.0 appropriée ici. Les dépendances de
calcul sont permissives et compatibles GPL :
[sectionproperties](https://github.com/robbievanleeuwen/section-properties) (MIT), shapely (BSD-3-Clause),
numpy / scipy (BSD-3-Clause).

© 2026 Pavlishenku. SectionCAD est un logiciel libre ; vous pouvez le redistribuer et/ou le modifier
selon les termes de la GPL, version 3 ou (à votre choix) toute version ultérieure. Distribué SANS
AUCUNE GARANTIE ; voir la GPL pour les détails.

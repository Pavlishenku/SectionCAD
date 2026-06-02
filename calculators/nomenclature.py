"""
Nomenclature Eurocode des caractéristiques de section.

Source unique de vérité pour :
- les symboles utilisés comme clés dans results_to_dict() / fea_results_to_dict()
  (affichés tels quels dans le panneau et le rapport),
- les descriptions (info-bulles du panneau et colonne « Désignation » du rapport).

Convention d'axes Eurocode (EN 1993) :
  y-y = axe fort (horizontal), z-z = axe faible (vertical).
Dans le repère de dessin de l'application, x est horizontal et y vertical ; on a
donc la correspondance  x_dessin → y_Eurocode  et  y_dessin → z_Eurocode.
Ainsi le moment d'inertie « fort » (∫ y_dessin² dA, autour de l'axe horizontal) est
noté I_y, conformément aux tables de profilés (IPE 300 : I_y = 8356 cm⁴).
"""

# Symbole Eurocode -> description française (info-bulle / désignation)
PROPERTY_DESCRIPTIONS = {
    "A":          "Aire de la section transversale",
    "y_G":        "Position du centre de gravité selon l'axe horizontal y",
    "z_G":        "Position du centre de gravité selon l'axe vertical z",
    "I_y":        "Moment d'inertie de flexion — axe fort y-y (centroïdal)",
    "I_z":        "Moment d'inertie de flexion — axe faible z-z (centroïdal)",
    "I_yz":       "Produit d'inertie",
    "I_1":        "Moment d'inertie principal maximal",
    "I_2":        "Moment d'inertie principal minimal",
    "α":          "Angle des axes principaux d'inertie (par rapport à l'horizontale)",
    "W_el,y,sup": "Module de flexion élastique, axe y — fibre supérieure",
    "W_el,y,inf": "Module de flexion élastique, axe y — fibre inférieure",
    "W_el,z,g":   "Module de flexion élastique, axe z — fibre gauche",
    "W_el,z,d":   "Module de flexion élastique, axe z — fibre droite",
    "W_pl,y":     "Module de flexion plastique, axe y",
    "W_pl,z":     "Module de flexion plastique, axe z",
    "i_y":        "Rayon de giration, axe y",
    "i_z":        "Rayon de giration, axe z",
    "y_SC":       "Centre de cisaillement — coordonnée horizontale y",
    "z_SC":       "Centre de cisaillement — coordonnée verticale z",
    "I_t":        ("Constante de torsion de Saint-Venant (exacte pour les profils "
                  "types ; estimée par FDM/FEM pour les sections quelconques)"),
    "I_w":        "Constante de gauchissement",
    "A_vy":       "Aire de cisaillement selon y (FEM)",
    "A_vz":       "Aire de cisaillement selon z (FEM)",
}


def describe(symbol: str) -> str:
    """Description d'un symbole (chaîne vide si inconnu)."""
    return PROPERTY_DESCRIPTIONS.get(symbol, "")

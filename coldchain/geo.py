"""Where things are: the towns of the 20 stores (config/chain.yaml) and the two distribution centres. Real towns, fictional chain."""

# (longitude, latitude, town) of each store
STORE_GEO = {
    "S01": (7.752, 48.573, "Strasbourg"),
    "S02": (7.749, 48.608, "Schiltigheim"),
    "S03": (7.336, 47.75, "Mulhouse"),
    "S04": (7.789, 48.815, "Haguenau"),
    "S05": (7.454, 48.26, "Selestat"),
    "S06": (7.363, 48.742, "Saverne"),
    "S07": (7.358, 48.079, "Colmar"),
    "S08": (7.716, 48.53, "Illkirch"),
    "S09": (7.105, 47.81, "Thann"),
    "S10": (7.944, 49.037, "Wissembourg"),
    "S11": (7.815, 48.573, "Kehl"),
    "S12": (7.944, 48.473, "Offenburg"),
    "S13": (7.842, 47.999, "Freiburg"),
    "S14": (7.87, 48.34, "Lahr"),
    "S15": (8.24, 48.76, "Baden-Baden"),
    "S16": (8.204, 48.859, "Rastatt"),
    "S17": (7.852, 48.121, "Emmendingen"),
    "S18": (7.661, 47.615, "Loerrach"),
    "S19": (8.404, 49.007, "Karlsruhe"),
    "S20": (7.632, 47.808, "Muellheim"),
}

# distribution centres of the chain (DC Nord near Strasbourg, DC Sud near Mulhouse): (longitude, latitude, name)
DEPOTS = {"DCN": (7.790, 48.585, "DC Nord (Strasbourg)"), "DCS": (7.300, 47.760, "DC Sud (Mulhouse)")}

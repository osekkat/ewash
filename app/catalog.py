"""Static catalog for Ewash — swap placeholder values when Omar confirms."""

# Services offered. Row id -> (title, description).
# TODO(omar): confirm service names, add prices if Omar wants to display them.
SERVICES = [
    ("svc_eco",     "Lavage Éco Standard",  "Lavage extérieur sans eau, écologique"),
    ("svc_premium", "Lavage Premium",       "Extérieur + finitions détaillées"),
    ("svc_interieur","Intérieur Complet",   "Aspirateur, plastiques, vitres intérieures"),
    ("svc_full",    "Lavage Complet",       "Intérieur + extérieur premium"),
]

# Vehicle size tiers (button payload id -> label).
# Max 3 because WhatsApp buttons are capped at 3.
VEHICLE_TYPES = [
    ("veh_berline", "🚗 Berline"),
    ("veh_suv",     "🚙 SUV / 4x4"),
    ("veh_utility", "🚐 Utilitaire"),
]

# Color quick-picks. 4th button reserved for "Autre" to trigger free text.
COLORS = [
    ("col_white",  "⚪ Blanc"),
    ("col_black",  "⚫ Noir"),
    ("col_grey",   "🩶 Gris"),
]
# Remaining common colors shown as a fallback LIST if user taps "Autre".
COLORS_EXTRA = [
    ("col_red",    "Rouge",        ""),
    ("col_blue",   "Bleu",         ""),
    ("col_silver", "Argent",       ""),
    ("col_beige",  "Beige",        ""),
    ("col_green",  "Vert",         ""),
    ("col_other",  "Autre couleur","Tapez la couleur manuellement"),
]

# Ewash centers. Swap to real addresses when Omar confirms.
# TODO(omar): confirm how many centers + exact names/addresses.
CENTERS = [
    ("ctr_casa", "Centre Ewash Casablanca", "Adresse à confirmer"),
]

# Time slots offered for bookings.
# TODO(omar): confirm hours + whether weekends differ.
SLOTS = [
    ("slot_9_11",  "09h – 11h",  "Matin"),
    ("slot_11_13", "11h – 13h",  "Fin de matinée"),
    ("slot_14_16", "14h – 16h",  "Début après-midi"),
    ("slot_16_18", "16h – 18h",  "Fin d'après-midi"),
]

# Lookup helpers.
def label_for(pairs, rid: str) -> str:
    for row in pairs:
        if row[0] == rid:
            return row[1]
    return rid  # fallback: show the raw id if unknown

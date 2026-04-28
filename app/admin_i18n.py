"""French-first admin UI translations.

The admin portal is for Omar/Ewash staff, so every label defaults to French.
English remains available for Oussama/developer support through an explicit
language switch.
"""
from __future__ import annotations

DEFAULT_LOCALE = "fr"
SUPPORTED_LOCALES = ("fr", "en")

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "fr": {
        "nav.dashboard": "Tableau de bord",
        "nav.bookings": "Réservations",
        "nav.customers": "Clients",
        "nav.prices": "Prix",
        "nav.promos": "Promos",
        "nav.reminders": "Rappels",
        "nav.closed_dates": "Fermetures",
        "nav.time_slots": "Créneaux",
        "nav.centers": "Centres",
        "nav.copy": "Textes",
        "nav.logout": "Déconnexion",
        "action.save": "Enregistrer",
        "action.cancel": "Annuler",
        "action.edit": "Modifier",
        "action.delete": "Supprimer",
        "action.language_fr": "FR",
        "action.language_en": "EN",
        "admin.not_configured.title": "Portail admin non configuré",
        "admin.not_configured.body": "Ajoutez ADMIN_PASSWORD pour activer le portail.",
        "admin.password.title": "Accès admin",
        "admin.password.label": "Mot de passe",
        "admin.password.submit": "Entrer",
        "admin.password.invalid": "Mot de passe incorrect.",
        "admin.dashboard.version_label": "Version actuelle :",
        "admin.dashboard.placeholder": "Réservations, clients et prix sont disponibles. Les prochains lots couvriront promos, rappels, fermetures, créneaux, centres et textes.",
        "admin.metric.bookings_today": "Réservations aujourd'hui",
        "admin.metric.awaiting_confirmation": "En attente de confirmation",
        "admin.metric.customers": "Clients enregistrés",
        "admin.metric.reminders": "Rappels en attente",
        "admin.metric.pending_data": "Données réelles après connexion WhatsApp → DB",
        "admin.metric.from_db": "Données persistées en base",
        "admin.panel.recent_bookings": "Réservations récentes",
        "admin.panel.no_bookings": "Aucune réservation persistée pour le moment.",
        "admin.panel.recent_bookings_intro": "Dernières réservations confirmées via WhatsApp.",
        "admin.panel.next_steps": "État du chantier",
        "admin.next.password": "Accès par mot de passe",
        "admin.next.db": "Fondation base de données",
        "admin.next.persistence": "Persistance des réservations WhatsApp",
        "admin.next.pages": "Pages réservations / clients / prix",
        "admin.next.soon": "Bientôt",
        "admin.prices.intro": "Tarifs publics issus du catalogue WhatsApp actuel. Les prix partenaires restent visibles dans la page Promos.",
        "admin.prices.public_tariff": "Tarifs publics",
        "admin.prices.group": "Famille",
        "admin.prices.service": "Service",
        "admin.prices.description": "Description",
        "admin.prices.washes": "Lavages",
        "admin.prices.detailing": "Esthétique",
        "admin.prices.moto": "Moto",
        "admin.page.placeholder": "Cette page arrive dans le prochain lot. Le menu est maintenant cliquable pour préparer la navigation opérationnelle.",
        "admin.page.what_is_ready": "Déjà prêt",
        "admin.page.ready_body": "L'accès admin, la session sécurisée et la persistance des réservations confirmées sont en place.",
        "admin.page.next_body": "Prochaine étape : remplacer cet écran par la vraie table ou le vrai formulaire de gestion.",
        "status.draft": "Brouillon",
        "status.awaiting_confirmation": "En attente de confirmation",
        "status.confirmed": "Confirmée",
        "status.rescheduled": "Reportée",
        "status.customer_cancelled": "Annulée par le client",
        "status.admin_cancelled": "Annulée par l'équipe",
        "status.expired": "Expirée",
        "status.no_show": "Client absent",
        "status.technician_en_route": "Technicien en route",
        "status.arrived": "Arrivé",
        "status.in_progress": "Nettoyage en cours",
        "status.completed": "Voiture nettoyée",
        "status.completed_with_issue": "Terminée avec incident",
        "status.refunded": "Remboursée",
    },
    "en": {
        "nav.dashboard": "Dashboard",
        "nav.bookings": "Bookings",
        "nav.customers": "Customers",
        "nav.prices": "Prices",
        "nav.promos": "Promos",
        "nav.reminders": "Reminders",
        "nav.closed_dates": "Closures",
        "nav.time_slots": "Time slots",
        "nav.centers": "Centers",
        "nav.copy": "Copy",
        "nav.logout": "Logout",
        "action.save": "Save",
        "action.cancel": "Cancel",
        "action.edit": "Edit",
        "action.delete": "Delete",
        "action.language_fr": "FR",
        "action.language_en": "EN",
        "admin.not_configured.title": "Admin portal is not configured",
        "admin.not_configured.body": "Set ADMIN_PASSWORD to enable the portal.",
        "admin.password.title": "Admin access",
        "admin.password.label": "Password",
        "admin.password.submit": "Enter",
        "admin.password.invalid": "Incorrect password.",
        "admin.dashboard.version_label": "Current version:",
        "admin.dashboard.placeholder": "Bookings, customers, and prices are available. Next batches cover promos, reminders, closures, time slots, centers, and copy.",
        "admin.metric.bookings_today": "Bookings today",
        "admin.metric.awaiting_confirmation": "Awaiting confirmation",
        "admin.metric.customers": "Saved customers",
        "admin.metric.reminders": "Pending reminders",
        "admin.metric.pending_data": "Real data after WhatsApp → DB wiring",
        "admin.metric.from_db": "Persisted database data",
        "admin.panel.recent_bookings": "Recent bookings",
        "admin.panel.no_bookings": "No persisted bookings yet.",
        "admin.panel.recent_bookings_intro": "Latest bookings confirmed through WhatsApp.",
        "admin.panel.next_steps": "Build status",
        "admin.next.password": "Password access",
        "admin.next.db": "Database foundation",
        "admin.next.persistence": "WhatsApp booking persistence",
        "admin.next.pages": "Bookings / customers / prices pages",
        "admin.next.soon": "Soon",
        "admin.prices.intro": "Public prices from the current WhatsApp catalog. Partner prices remain visible on the Promos page.",
        "admin.prices.public_tariff": "Public tariff",
        "admin.prices.group": "Group",
        "admin.prices.service": "Service",
        "admin.prices.description": "Description",
        "admin.prices.washes": "Washes",
        "admin.prices.detailing": "Detailing",
        "admin.prices.moto": "Motorbike",
        "admin.page.placeholder": "This page is coming in the next batch. The menu is now clickable to prepare operational navigation.",
        "admin.page.what_is_ready": "Already ready",
        "admin.page.ready_body": "Admin access, secure session, and confirmed-booking persistence are in place.",
        "admin.page.next_body": "Next step: replace this screen with the real table or management form.",
        "status.draft": "Draft",
        "status.awaiting_confirmation": "Awaiting confirmation",
        "status.confirmed": "Confirmed",
        "status.rescheduled": "Rescheduled",
        "status.customer_cancelled": "Cancelled by customer",
        "status.admin_cancelled": "Cancelled by team",
        "status.expired": "Expired",
        "status.no_show": "No-show",
        "status.technician_en_route": "Technician en route",
        "status.arrived": "Arrived",
        "status.in_progress": "In progress",
        "status.completed": "Completed",
        "status.completed_with_issue": "Completed with issue",
        "status.refunded": "Refunded",
    },
}

_NAV_KEYS = (
    "nav.dashboard",
    "nav.bookings",
    "nav.customers",
    "nav.prices",
    "nav.promos",
    "nav.reminders",
    "nav.closed_dates",
    "nav.time_slots",
    "nav.centers",
    "nav.copy",
)


def normalize_locale(locale: str | None) -> str:
    """Return a supported locale, defaulting to French."""
    if not locale:
        return DEFAULT_LOCALE
    normalized = locale.strip().lower()
    return normalized if normalized in SUPPORTED_LOCALES else DEFAULT_LOCALE


def t(key: str, locale: str | None = None) -> str:
    """Translate an admin UI key.

    Missing English keys fall back to French. Missing French keys return the key
    itself, which keeps templates visible instead of crashing.
    """
    lang = normalize_locale(locale)
    if key in _TRANSLATIONS[lang]:
        return _TRANSLATIONS[lang][key]
    return _TRANSLATIONS[DEFAULT_LOCALE].get(key, key)


def admin_nav_labels(locale: str | None = None) -> list[str]:
    """Localized admin navigation labels, French by default."""
    return [t(key, locale) for key in _NAV_KEYS]

"""Small, dependency-free UI localization layer.

Keys are intentionally stable and centrally reviewed. Missing translations fall
back to English instead of exposing identifiers or crashing a dialog.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    flag: str
    name: str
    rtl: bool = False


LANGUAGES = (
    Language("en", "🇬🇧", "English"),
    Language("de", "🇩🇪", "Deutsch"),
    Language("fr", "🇫🇷", "Français"),
    Language("es", "🇪🇸", "Español"),
    Language("ar", "🇸🇦", "العربية", True),
    Language("he", "🇮🇱", "עברית", True),
)
LANGUAGE_CODES = {item.code for item in LANGUAGES}

_STRINGS = {
    "en": {
        "subtitle": "Cloud sync, streaming, and encrypted peer sharing",
        "connect_cloud": "Connect cloud account", "peer_folders": "Peer-to-peer shared folders",
        "health": "Sync health, peer audit timeline, and provider capabilities", "settings": "Settings",
        "help": "User documentation and how-to guides", "language": "Language",
        "visual_style": "Visual design", "theme_applies_after_save": "Applied immediately after saving.",
        "connected_services": "Connected services", "active_syncs": "Active syncs", "protected_folders": "Protected folders",
        "cloud_accounts": "Cloud accounts", "connect_account": "Connect account",
        "synced_folders": "Synchronized folders", "add_folder": "Add folder", "live_log": "Live activity log",
        "network_traffic": "Network", "network_traffic_hint": "Current device traffic and totals accumulated today",
        "download_now": "Down now", "upload_now": "Up now", "download_today": "Down today", "upload_today": "Up today", "unavailable": "Unavailable",
        "new_group": "New group", "group": "Group", "ungrouped": "Ungrouped",
        "expand_group": "Expand group", "minimize_group": "Minimize group",
        "drag_folder_hint": "Drag to reorder or move this synchronized folder into a group",
        "drop_group_hint": "Drop a synchronized folder here to move it into this group",
        "connected": "Connected", "synchronizing": "Synchronizing", "attention": "Needs attention",
        "peer_settings": "Peer settings", "open_online": "Open online", "reconnect": "Reconnect / refresh credentials",
        "remove_account": "Remove account", "empty_jobs": "Connect an account, then add a synchronized folder or virtual drive.",
        "automatic_sync": "Enable automatic synchronization", "open_drive": "Open drive",
        "start_streaming": "Start streaming", "sync_now": "Sync now", "disconnect": "Disconnect", "stop": "Stop",
        "open_folder": "Open folder", "open_online_folder": "Open online folder", "history": "History", "verify": "Verify",
        "conflicts": "Conflicts", "rename": "Rename", "edit": "Edit", "view_log": "View log",
        "remove_sync": "Remove synchronization", "cloud_storage": "Cloud storage",
        "stream_hint": "Show cloud files immediately; download content only when a file is opened",
        "keep_drive_offline": "Keep drive offline", "make_drive_online_only": "Make drive online-only",
        "keep_drive_offline_hint": "Explicitly download and retain the complete streaming drive",
        "make_drive_online_only_hint": "Remove all offline rules and release the drive's local file cache",
        "choose_provider": "Connect cloud storage", "choose_provider_heading": "Choose a storage provider",
        "provider_hint": "Cloud providers support selective folders and files on demand; GitHub uses repository synchronization.",
        "create_vault": "Create encrypted vault on a connected account", "cancel": "Cancel",
        "documentation": "TuxInDrive User Documentation", "documentation_intro": "Functions, safe operating guidance, and practical how-to instructions",
        "search_help": "Search documentation…", "all_topics": "All topics", "close": "Close",
        "preparing": "Preparing the cloud transfer engine…", "loaded": "TuxInDrive loaded and is running in the tray.",
    },
    "de": {
        "subtitle": "Cloud-Synchronisierung, Streaming und verschlüsselte Peer-Freigabe",
        "connect_cloud": "Cloud-Konto verbinden", "peer_folders": "Peer-to-Peer-Freigaben",
        "health": "Synchronisierungsstatus, Peer-Prüfprotokoll und Anbieterfunktionen", "settings": "Einstellungen",
        "help": "Benutzerdokumentation und Anleitungen", "language": "Sprache",
        "visual_style": "Visuelles Design", "theme_applies_after_save": "Wird direkt nach dem Speichern angewendet.",
        "connected_services": "Verbundene Dienste", "active_syncs": "Aktive Synchronisierungen", "protected_folders": "Geschützte Ordner",
        "cloud_accounts": "Cloud-Konten", "connect_account": "Konto verbinden",
        "synced_folders": "Synchronisierte Ordner", "add_folder": "Ordner hinzufügen", "live_log": "Live-Aktivitätsprotokoll",
        "network_traffic": "Netzwerk", "network_traffic_hint": "Aktueller Geräteverkehr und heutige Gesamtsummen",
        "download_now": "Download jetzt", "upload_now": "Upload jetzt", "download_today": "Download heute", "upload_today": "Upload heute", "unavailable": "Nicht verfügbar",
        "new_group": "Neue Gruppe", "group": "Gruppe", "ungrouped": "Nicht gruppiert",
        "expand_group": "Gruppe erweitern", "minimize_group": "Gruppe minimieren",
        "drag_folder_hint": "Ziehen, um diesen synchronisierten Ordner neu anzuordnen oder in eine Gruppe zu verschieben",
        "drop_group_hint": "Synchronisierten Ordner hier ablegen, um ihn in diese Gruppe zu verschieben",
        "connected": "Verbunden", "synchronizing": "Wird synchronisiert", "attention": "Aktion erforderlich",
        "peer_settings": "Peer-Einstellungen", "open_online": "Online öffnen", "reconnect": "Anmeldedaten erneuern",
        "remove_account": "Konto entfernen", "empty_jobs": "Verbinden Sie ein Konto und fügen Sie einen synchronisierten Ordner oder ein virtuelles Laufwerk hinzu.",
        "automatic_sync": "Automatische Synchronisierung aktivieren", "open_drive": "Laufwerk öffnen",
        "start_streaming": "Streaming starten", "sync_now": "Jetzt synchronisieren", "disconnect": "Trennen", "stop": "Stoppen",
        "open_folder": "Ordner öffnen", "open_online_folder": "Online-Ordner öffnen", "history": "Verlauf", "verify": "Prüfen",
        "conflicts": "Konflikte", "rename": "Umbenennen", "edit": "Bearbeiten", "view_log": "Protokoll",
        "remove_sync": "Synchronisierung entfernen", "cloud_storage": "Cloud-Speicher",
        "stream_hint": "Cloud-Dateien sofort anzeigen; Inhalte erst beim Öffnen herunterladen",
        "keep_drive_offline": "Laufwerk offline behalten", "make_drive_online_only": "Laufwerk nur online verwenden",
        "keep_drive_offline_hint": "Das gesamte Streaming-Laufwerk ausdrücklich herunterladen und behalten",
        "make_drive_online_only_hint": "Alle Offline-Regeln entfernen und den lokalen Datei-Cache freigeben",
        "choose_provider": "Cloud-Speicher verbinden", "choose_provider_heading": "Speicheranbieter auswählen",
        "provider_hint": "Cloud-Anbieter unterstützen Auswahl und Dateien bei Bedarf; GitHub nutzt Repository-Synchronisierung.",
        "create_vault": "Verschlüsselten Tresor auf einem verbundenen Konto erstellen", "cancel": "Abbrechen",
        "documentation": "TuxInDrive-Benutzerdokumentation", "documentation_intro": "Funktionen, sicherer Betrieb und praktische Anleitungen",
        "search_help": "Dokumentation durchsuchen…", "all_topics": "Alle Themen", "close": "Schließen",
        "preparing": "Cloud-Übertragungsmodul wird vorbereitet…", "loaded": "TuxInDrive läuft im Infobereich.",
    },
    "fr": {
        "subtitle": "Synchronisation cloud, streaming et partage pair-à-pair chiffré",
        "connect_cloud": "Connecter un compte cloud", "peer_folders": "Dossiers pair-à-pair",
        "health": "Santé des synchronisations, audit des pairs et capacités", "settings": "Paramètres",
        "help": "Documentation et guides pratiques", "language": "Langue",
        "visual_style": "Design visuel", "theme_applies_after_save": "Appliqué immédiatement après l’enregistrement.",
        "connected_services": "Services connectés", "active_syncs": "Synchronisations actives", "protected_folders": "Dossiers protégés",
        "cloud_accounts": "Comptes cloud", "connect_account": "Connecter un compte",
        "synced_folders": "Dossiers synchronisés", "add_folder": "Ajouter un dossier", "live_log": "Journal d’activité",
        "network_traffic": "Réseau", "network_traffic_hint": "Trafic actuel de l’appareil et totaux cumulés aujourd’hui",
        "download_now": "Réception actuelle", "upload_now": "Envoi actuel", "download_today": "Reçu aujourd’hui", "upload_today": "Envoyé aujourd’hui", "unavailable": "Indisponible",
        "new_group": "Nouveau groupe", "group": "Groupe", "ungrouped": "Non groupé",
        "expand_group": "Développer le groupe", "minimize_group": "Réduire le groupe",
        "drag_folder_hint": "Faire glisser pour réorganiser ce dossier synchronisé ou le déplacer dans un groupe",
        "drop_group_hint": "Déposer un dossier synchronisé ici pour le déplacer dans ce groupe",
        "connected": "Connecté", "synchronizing": "Synchronisation", "attention": "Intervention requise",
        "peer_settings": "Paramètres du pair", "open_online": "Ouvrir en ligne", "reconnect": "Actualiser les identifiants",
        "remove_account": "Supprimer le compte", "empty_jobs": "Connectez un compte, puis ajoutez un dossier synchronisé ou un lecteur virtuel.",
        "automatic_sync": "Activer la synchronisation automatique", "open_drive": "Ouvrir le lecteur",
        "start_streaming": "Démarrer le streaming", "sync_now": "Synchroniser", "disconnect": "Déconnecter", "stop": "Arrêter",
        "open_folder": "Ouvrir le dossier", "open_online_folder": "Ouvrir le dossier en ligne", "history": "Historique", "verify": "Vérifier",
        "conflicts": "Conflits", "rename": "Renommer", "edit": "Modifier", "view_log": "Voir le journal",
        "remove_sync": "Supprimer la synchronisation", "cloud_storage": "Stockage cloud",
        "stream_hint": "Afficher immédiatement les fichiers cloud et télécharger leur contenu à l’ouverture",
        "keep_drive_offline": "Conserver le lecteur hors ligne", "make_drive_online_only": "Lecteur en ligne uniquement",
        "keep_drive_offline_hint": "Télécharger explicitement et conserver tout le lecteur streaming",
        "make_drive_online_only_hint": "Supprimer toutes les règles hors ligne et libérer le cache local",
        "choose_provider": "Connecter un stockage cloud", "choose_provider_heading": "Choisir un fournisseur",
        "provider_hint": "Les services cloud offrent la sélection et les fichiers à la demande; GitHub synchronise des dépôts.",
        "create_vault": "Créer un coffre chiffré sur un compte connecté", "cancel": "Annuler",
        "documentation": "Documentation utilisateur TuxInDrive", "documentation_intro": "Fonctions, conseils de sécurité et guides pratiques",
        "search_help": "Rechercher dans la documentation…", "all_topics": "Tous les sujets", "close": "Fermer",
        "preparing": "Préparation du moteur de transfert…", "loaded": "TuxInDrive fonctionne dans la zone de notification.",
    },
    "es": {
        "subtitle": "Sincronización cloud, streaming y uso compartido cifrado entre pares",
        "connect_cloud": "Conectar cuenta cloud", "peer_folders": "Carpetas entre pares",
        "health": "Estado de sincronización, auditoría y capacidades", "settings": "Configuración",
        "help": "Documentación y guías prácticas", "language": "Idioma",
        "visual_style": "Diseño visual", "theme_applies_after_save": "Se aplica inmediatamente después de guardar.",
        "connected_services": "Servicios conectados", "active_syncs": "Sincronizaciones activas", "protected_folders": "Carpetas protegidas",
        "cloud_accounts": "Cuentas cloud", "connect_account": "Conectar cuenta",
        "synced_folders": "Carpetas sincronizadas", "add_folder": "Añadir carpeta", "live_log": "Registro de actividad",
        "network_traffic": "Red", "network_traffic_hint": "Tráfico actual del dispositivo y totales acumulados hoy",
        "download_now": "Bajada actual", "upload_now": "Subida actual", "download_today": "Bajado hoy", "upload_today": "Subido hoy", "unavailable": "No disponible",
        "new_group": "Nuevo grupo", "group": "Grupo", "ungrouped": "Sin grupo",
        "expand_group": "Expandir grupo", "minimize_group": "Minimizar grupo",
        "drag_folder_hint": "Arrastre para reordenar esta carpeta sincronizada o moverla a un grupo",
        "drop_group_hint": "Suelte aquí una carpeta sincronizada para moverla a este grupo",
        "connected": "Conectado", "synchronizing": "Sincronizando", "attention": "Requiere atención",
        "peer_settings": "Configuración del par", "open_online": "Abrir en línea", "reconnect": "Actualizar credenciales",
        "remove_account": "Eliminar cuenta", "empty_jobs": "Conecte una cuenta y añada una carpeta sincronizada o unidad virtual.",
        "automatic_sync": "Activar sincronización automática", "open_drive": "Abrir unidad",
        "start_streaming": "Iniciar streaming", "sync_now": "Sincronizar", "disconnect": "Desconectar", "stop": "Detener",
        "open_folder": "Abrir carpeta", "open_online_folder": "Abrir carpeta en línea", "history": "Historial", "verify": "Verificar",
        "conflicts": "Conflictos", "rename": "Renombrar", "edit": "Editar", "view_log": "Ver registro",
        "remove_sync": "Eliminar sincronización", "cloud_storage": "Almacenamiento cloud",
        "stream_hint": "Mostrar archivos cloud inmediatamente y descargar el contenido solo al abrirlo",
        "keep_drive_offline": "Mantener unidad sin conexión", "make_drive_online_only": "Unidad solo en línea",
        "keep_drive_offline_hint": "Descargar y conservar explícitamente toda la unidad de streaming",
        "make_drive_online_only_hint": "Eliminar todas las reglas sin conexión y liberar la caché local",
        "choose_provider": "Conectar almacenamiento cloud", "choose_provider_heading": "Elegir proveedor",
        "provider_hint": "Los servicios cloud permiten selección y archivos bajo demanda; GitHub sincroniza repositorios.",
        "create_vault": "Crear bóveda cifrada en una cuenta conectada", "cancel": "Cancelar",
        "documentation": "Documentación de usuario de TuxInDrive", "documentation_intro": "Funciones, uso seguro y guías prácticas",
        "search_help": "Buscar en la documentación…", "all_topics": "Todos los temas", "close": "Cerrar",
        "preparing": "Preparando el motor de transferencia…", "loaded": "TuxInDrive se está ejecutando en la bandeja.",
    },
    "ar": {
        "subtitle": "مزامنة سحابية وبث ملفات ومشاركة مشفرة بين الأجهزة",
        "connect_cloud": "ربط حساب سحابي", "peer_folders": "مجلدات مشتركة بين الأجهزة",
        "health": "حالة المزامنة وسجل الأجهزة وإمكانات المزود", "settings": "الإعدادات",
        "help": "دليل المستخدم والإرشادات", "language": "اللغة",
        "visual_style": "التصميم المرئي", "theme_applies_after_save": "يُطبّق فور الحفظ.",
        "connected_services": "الخدمات المتصلة", "active_syncs": "عمليات المزامنة النشطة", "protected_folders": "المجلدات المحمية",
        "cloud_accounts": "الحسابات السحابية", "connect_account": "ربط حساب",
        "synced_folders": "المجلدات المتزامنة", "add_folder": "إضافة مجلد", "live_log": "سجل النشاط المباشر",
        "network_traffic": "الشبكة", "network_traffic_hint": "حركة الجهاز الحالية وإجماليات اليوم",
        "download_now": "تنزيل الآن", "upload_now": "رفع الآن", "download_today": "تنزيل اليوم", "upload_today": "رفع اليوم", "unavailable": "غير متاح",
        "new_group": "مجموعة جديدة", "group": "المجموعة", "ungrouped": "دون مجموعة",
        "expand_group": "توسيع المجموعة", "minimize_group": "تصغير المجموعة",
        "drag_folder_hint": "اسحب لإعادة ترتيب هذا المجلد المتزامن أو نقله إلى مجموعة",
        "drop_group_hint": "أفلت مجلدًا متزامنًا هنا لنقله إلى هذه المجموعة",
        "connected": "متصل", "synchronizing": "تجري المزامنة", "attention": "يتطلب الانتباه",
        "peer_settings": "إعدادات الجهاز", "open_online": "فتح عبر الإنترنت", "reconnect": "إعادة الربط وتحديث بيانات الاعتماد",
        "remove_account": "إزالة الحساب", "empty_jobs": "اربط حسابًا ثم أضف مجلدًا متزامنًا أو محركًا افتراضيًا.",
        "automatic_sync": "تفعيل المزامنة التلقائية", "open_drive": "فتح المحرك",
        "start_streaming": "بدء البث", "sync_now": "مزامنة الآن", "disconnect": "قطع الاتصال", "stop": "إيقاف",
        "open_folder": "فتح المجلد", "open_online_folder": "فتح المجلد عبر الإنترنت", "history": "السجل", "verify": "تحقق",
        "conflicts": "التعارضات", "rename": "إعادة تسمية", "edit": "تحرير", "view_log": "عرض السجل",
        "remove_sync": "إزالة المزامنة", "cloud_storage": "التخزين السحابي",
        "stream_hint": "إظهار الملفات السحابية فورًا وتنزيل المحتوى عند فتح الملف فقط",
        "keep_drive_offline": "الاحتفاظ بالمحرك دون اتصال", "make_drive_online_only": "المحرك عبر الإنترنت فقط",
        "keep_drive_offline_hint": "تنزيل محرك البث بالكامل والاحتفاظ به بصورة صريحة",
        "make_drive_online_only_hint": "إزالة جميع قواعد عدم الاتصال وتحرير ذاكرة الملفات المحلية",
        "choose_provider": "ربط تخزين سحابي", "choose_provider_heading": "اختر مزود التخزين",
        "provider_hint": "يدعم مزودو السحابة الاختيار والملفات عند الطلب؛ ويزامن GitHub المستودعات.",
        "create_vault": "إنشاء خزنة مشفرة في حساب متصل", "cancel": "إلغاء",
        "documentation": "دليل مستخدم TuxInDrive", "documentation_intro": "الوظائف وإرشادات التشغيل الآمن والخطوات العملية",
        "search_help": "البحث في الدليل…", "all_topics": "جميع المواضيع", "close": "إغلاق",
        "preparing": "جارٍ إعداد محرك النقل السحابي…", "loaded": "يعمل TuxInDrive الآن في شريط النظام.",
    },
    "he": {
        "subtitle": "סנכרון ענן, הזרמת קבצים ושיתוף עמיתים מוצפן",
        "connect_cloud": "חיבור חשבון ענן", "peer_folders": "תיקיות משותפות בין עמיתים",
        "health": "מצב סנכרון, יומן עמיתים ויכולות ספק", "settings": "הגדרות",
        "help": "תיעוד משתמש ומדריכים", "language": "שפה",
        "visual_style": "עיצוב חזותי", "theme_applies_after_save": "מוחל מיד לאחר השמירה.",
        "connected_services": "שירותים מחוברים", "active_syncs": "סנכרונים פעילים", "protected_folders": "תיקיות מוגנות",
        "cloud_accounts": "חשבונות ענן", "connect_account": "חיבור חשבון",
        "synced_folders": "תיקיות מסונכרנות", "add_folder": "הוספת תיקייה", "live_log": "יומן פעילות חי",
        "network_traffic": "רשת", "network_traffic_hint": "תעבורת המכשיר הנוכחית והסכומים המצטברים היום",
        "download_now": "הורדה כעת", "upload_now": "העלאה כעת", "download_today": "הורדה היום", "upload_today": "העלאה היום", "unavailable": "לא זמין",
        "new_group": "קבוצה חדשה", "group": "קבוצה", "ungrouped": "ללא קבוצה",
        "expand_group": "הרחבת הקבוצה", "minimize_group": "מזעור הקבוצה",
        "drag_folder_hint": "גררו כדי לשנות את סדר התיקייה המסונכרנת או להעביר אותה לקבוצה",
        "drop_group_hint": "שחררו כאן תיקייה מסונכרנת כדי להעביר אותה לקבוצה זו",
        "connected": "מחובר", "synchronizing": "מסנכרן", "attention": "נדרשת תשומת לב",
        "peer_settings": "הגדרות עמית", "open_online": "פתיחה בענן", "reconnect": "חיבור מחדש ורענון הרשאות",
        "remove_account": "הסרת חשבון", "empty_jobs": "חברו חשבון ולאחר מכן הוסיפו תיקייה מסונכרנת או כונן וירטואלי.",
        "automatic_sync": "הפעלת סנכרון אוטומטי", "open_drive": "פתיחת כונן",
        "start_streaming": "התחלת הזרמה", "sync_now": "סנכרון עכשיו", "disconnect": "ניתוק", "stop": "עצירה",
        "open_folder": "פתיחת תיקייה", "open_online_folder": "פתיחת תיקייה בענן", "history": "היסטוריה", "verify": "אימות",
        "conflicts": "התנגשויות", "rename": "שינוי שם", "edit": "עריכה", "view_log": "הצגת יומן",
        "remove_sync": "הסרת סנכרון", "cloud_storage": "אחסון ענן",
        "stream_hint": "הצגת מבנה הענן מיד והורדת תוכן רק בעת פתיחת הקובץ",
        "keep_drive_offline": "שמירת הכונן במצב לא מקוון", "make_drive_online_only": "כונן מקוון בלבד",
        "keep_drive_offline_hint": "הורדה ושמירה מפורשת של כל כונן ההזרמה",
        "make_drive_online_only_hint": "הסרת כל כללי השימוש הלא מקוון ושחרור מטמון הקבצים המקומי",
        "choose_provider": "חיבור אחסון ענן", "choose_provider_heading": "בחירת ספק אחסון",
        "provider_hint": "ספקי ענן תומכים בבחירה ובקבצים לפי דרישה; GitHub מסנכרן מאגרים.",
        "create_vault": "יצירת כספת מוצפנת בחשבון מחובר", "cancel": "ביטול",
        "documentation": "תיעוד המשתמש של TuxInDrive", "documentation_intro": "תכונות, הנחיות להפעלה בטוחה ומדריכים מעשיים",
        "search_help": "חיפוש בתיעוד…", "all_topics": "כל הנושאים", "close": "סגירה",
        "preparing": "מכין את מנוע העברת הענן…", "loaded": "TuxInDrive פועל באזור ההודעות.",
    },
}

_current = "en"


def set_language(code: str) -> str:
    global _current
    _current = code if code in LANGUAGE_CODES else "en"
    return _current


def get_language() -> str:
    return _current


def is_rtl(code: str | None = None) -> bool:
    selected = code or _current
    return any(item.code == selected and item.rtl for item in LANGUAGES)


def tr(key: str, **values: object) -> str:
    value = _STRINGS.get(_current, {}).get(key, _STRINGS["en"].get(key, key))
    return value.format(**values) if values else value

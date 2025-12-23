import os
from datetime import time
from dotenv import load_dotenv

# PERMISOS
try:
    PUID = int(os.getenv("PUID", "0"))
    PGID = int(os.getenv("PGID", "0"))
except:
    PUID, PGID = 0, 0

load_dotenv()

# --- DIRECTORIOS ---
# --- PERSISTENCIA DE SESIÓN ---
# Definimos la carpeta persistente (dentro del contenedor suele ser /config)
CONFIG_DIR = "/config"

# Si no existe (ej: entorno local Windows), usamos una carpeta 'config' local
if not os.path.exists(CONFIG_DIR):
    CONFIG_DIR = os.path.join(os.getcwd(), "config")
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

# --- RUTAS DE ARCHIVOS PERSISTENTES ---
# Ruta absoluta al archivo de sesión
SESSION_FILE = os.path.join(CONFIG_DIR, "config.json")

# Credenciales Foro
FORO_USER = os.getenv("FORO_USER")
FORO_PASS = os.getenv("FORO_PASS")
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL")

# Debrid
RD_TOKEN = os.getenv("REALDEBRID_API_TOKEN")
DL_TOKEN = os.getenv("DEBRIDLINK_API_KEY")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/app/downloads")
DEBRID_PRIORIDAD = os.getenv("DEBRID_PRIORIDAD", "RD")

# --- AJUSTES DE EXTRACCIÓN (NUEVO) ---
# Contraseña por defecto para los archivos RAR de DescargasDD
RAR_PASSWORD = os.getenv("RAR_PASSWORD", "descargasdd")

# Base de Datos
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432")
}

# Configuración del Bot
FOROS_PROCESAR = ["250", "142", "143", "164"]
IDS_IGNORADOS = [""] 

# Paralelismo y Límites
MAX_WORKERS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "10"))

try:
    SPEED_LIMIT_MB = float(os.getenv("SPEED_LIMIT_MB", "0"))
except: SPEED_LIMIT_MB = 0

_enable_txt = os.getenv("ENABLE_SPEED_LIMIT", "true").lower()
ENABLE_SPEED_LIMIT = _enable_txt in ["true", "1", "yes", "si", "on"]

# Función auxiliar para convertir "08:30" -> objeto time(8, 30)
def _parse_time(time_str):
    try:
        if not time_str: return None
        parts = list(map(int, time_str.split(':')))
        if len(parts) == 3: return time(parts[0], parts[1], parts[2]) # HH:MM:SS
        if len(parts) == 2: return time(parts[0], parts[1])           # HH:MM
        if len(parts) == 1: return time(parts[0], 0)                  # HH
    except: pass
    return None

# Cargamos las horas exactas (Default: 08:00 a 00:00)
LIMIT_START_TIME = _parse_time(os.getenv("LIMIT_START_TIME", "08:00:00")) or time(8, 0, 0)
LIMIT_END_TIME = _parse_time(os.getenv("LIMIT_END_TIME", "20:00:00")) or time(0, 0, 0)

# Enrutamiento de Servidores
# Configuración CONJUNTA: Lista 1 -> RD | Lista 2 -> DL
HOSTER_PREFS = {
    # --- ASIGNADOS A REAL DEBRID (RD) ---
    "1fichier": "RD",
    "4shared": "RD",
    "brupload": "RD",
    "clicknupload": "RD",
    "dailymotion": "RD",
    "dailyuploads": "RD",
    "ddl.to": "RD",
    "dropbox": "RD",
    "filefactory": "RD",
    "filespace": "RD",
    "filestore": "RD",
    "filextras": "RD",
    "gigapeta": "RD",
    "drive": "RD",       # Google Drive
    "google": "RD",      # Variación Google
    "hexupload": "RD",
    "hexload": "RD",
    "hitfile": "RD",
    "icloud": "RD",
    "isra.cloud": "RD",
    "katfile": "RD",
    "mediafire": "RD",
    "mega": "RD",
    "prefiles": "RD",
    "radiotunes": "RD",
    "rapidgator": "RD",
    "redtube": "RD",
    "scribd": "RD",
    "send.cm": "RD",
    "send.now": "RD",
    "sendspace": "RD",
    "terabytez": "RD",
    "turbobit": "RD",
    "uploady": "RD",
    "vimeo": "RD",
    "voe": "RD",

    # --- ASIGNADOS A DEBRIDLINK (DL) ---
    "ddownload": "DL",      
    "file.al": "DL",        
    "drop.download": "DL",
    "elitefile": "DL",
    "emload": "DL",
    "fikper": "DL",
    "filecat": "DL",
    "filedot": "DL",
    "fileland": "DL",
    "filer.net": "DL",
    "gofile": "DL",
    "hulkshare": "DL",
    "kshared": "DL",
    "mixdrop": "DL",
    "nelion": "DL",
    "pixeldrain": "DL",
    "silkfiles": "DL",
    "terabox": "DL",
    "tezfiles": "DL"
}

# ORDEN DE PREFERENCIA DE DESCARGA
PRIORIDAD_DOMINIOS = [
    "1fichier",
    "katfile",
    "pixeldrain",
    "mega",
    "drive",
    "rapidgator",
    "turbobit"
]

# PALABRAS NEGRAS (BLACKLIST)
PALABRAS_EXCLUIDAS = ["REMUX", "FULLUHD", "ISO", "720P", "CANAL TELEGRAM", "LISTADO", "HIDE"]

# --- INTERVALO DE COMPROBACIÓN ---
# Tiempo en segundos que el bot duerme entre escaneos (Por defecto: 10 minutos)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))

# --- CONFIGURACIÓN DE IDENTIDAD ---
# User-Agent moderno (Chrome 123 en Windows 10) para parecer un humano real
DEFAULT_USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
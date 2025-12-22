import re
from datetime import datetime
import config
import unicodedata

def extraer_hilo_id(url):
    match = re.search(r't=(\d+)', url)
    return match.group(1) if match else url

def quitar_tildes(texto):
    return ''.join((c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn'))

# --- NUEVA FUNCIÓN DE SANITIZACIÓN WINDOWS ---
def sanitizar_nombre(texto):
    """
    Elimina caracteres prohibidos en Windows y sistemas de archivos NTFS/FAT32.
    Prohibidos: < > : " / \ | ? *
    """
    if not texto: return "sin_titulo"
    # Reemplazamos los prohibidos por nada o por un guion si es necesario
    limpio = re.sub(r'[<>:"/\\|?*]', '', texto)
    # Eliminamos espacios dobles y espacios al final/inicio
    limpio = re.sub(r'\s+', ' ', limpio).strip()
    return limpio

def limpiar_titulo(titulo_sucio):
    try:
        match_anio = re.search(r'[\(\[\s\|](\d{4})[\)\]\s\|]', titulo_sucio)
        if not match_anio:
            limpio = re.sub(r'\[.*?\]', '', titulo_sucio).strip()
            return quitar_tildes(limpio)
        titulo_parte = titulo_sucio[:match_anio.start()]
        titulo_parte = re.sub(r'\(.*?\)', '', titulo_parte)
        titulo_parte = titulo_parte.replace('[', '').replace(']', '').replace('|', '').replace('-', '')
        titulo_parte = quitar_tildes(titulo_parte)
        titulo_parte = re.sub(r'\s+', ' ', titulo_parte).strip()
        return f"{titulo_parte} ({match_anio.group(1)})"
    except: return titulo_sucio.strip()

def detectar_formato(titulo, foro_id):
    if str(foro_id) == "164": return "2160p"
    if str(foro_id) == "250": return "x265"
    if str(foro_id) == "142": return "1080p"
    if str(foro_id) == "143": return "m1080p"
    t = titulo.upper()
    if "2160P" in t or "4K" in t: return "2160p"
    if "X265" in t: return "x265"
    if "MICRO" in t or "M1080P" in t: return "m1080p"
    if "1080P" in t: return "1080p"
    return "Desconocido"

def debe_aplicar_limite():
    if not config.ENABLE_SPEED_LIMIT:
        return False
    now = datetime.now().time()
    start = config.LIMIT_START_TIME
    end = config.LIMIT_END_TIME
    if not start or not end:
        return False
    if start < end:
        return start <= now < end
    else:
        return now >= start or now < end
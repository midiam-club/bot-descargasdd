import re
from datetime import datetime
import config
import unicodedata

def extraer_hilo_id(url):
    match = re.search(r't=(\d+)', url)
    return match.group(1) if match else url

def quitar_tildes(texto):
    return ''.join((c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn'))

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
    """
    Devuelve True si la hora actual está dentro del rango de limitación
    y el interruptor maestro está activado.
    """
    # 1. Si el interruptor maestro está apagado, nunca limitamos
    if not config.ENABLE_SPEED_LIMIT:
        return False

    # 2. Obtenemos la hora EXACTA actual
    now = datetime.now().time()
    start = config.LIMIT_START_TIME
    end = config.LIMIT_END_TIME
    
    # Si por error no hay horas definidas, no limitamos
    if not start or not end:
        return False
    
    # Caso A: Rango en el mismo día (Ej: 08:30 a 23:15)
    if start < end:
        return start <= now < end
        
    # Caso B: Rango cruza medianoche (Ej: 23:30 a 07:15)
    else:
        # Es válido si estamos después del inicio (23:30...) O antes del fin (...07:15)
        return now >= start or now < end
import os
import re
import subprocess
import json
import glob
from config import PUID, PGID

# --- 1. EXTRACCIÓN BASADA EN TEXTO (TÍTULOS) ---

def extraer_fuente_del_titulo(titulo_original):
    patrones = [r"BDRip", r"BRRip", r"BluRay", r"Bluray", r"Web-?DL", r"WEBDL", r"HDTV", r"UHD", r"FullUHD"]
    for pat in patrones:
        match = re.search(f"({pat})", titulo_original, re.IGNORECASE)
        if match:
            encontrado = match.group(1)
            if "WEB" in encontrado.upper(): return "WebDL"
            if "BLU" in encontrado.upper(): return "BluRay"
            return encontrado
    return "WebDL"

def extraer_resolucion_del_texto(titulo_original, formato_foro):
    """
    Determina la resolución basándose SOLO en el nombre del archivo/hilo
    o en la categoría del foro. Prioridad: Texto > Foro.
    """
    t = titulo_original.upper()
    f = formato_foro.upper()
    
    # 1. Búsqueda explícita en el título
    if "2160P" in t or "4K" in t or "UHD" in t: return "2160p"
    
    # [CAMBIO] Prioridad para m1080p/MicroHD antes que 1080p normal
    if "M1080P" in t or "MICRO" in t: return "m1080p"
    
    if "1080P" in t or "FULLHD" in t or "FHD" in t: return "1080p"
    if "720P" in t or "HD" in t: return "720p"
    
    # 2. Fallback: Lo que nos dijo el scraper (formato_foro)
    if "2160" in f or "4K" in f: return "2160p"
    
    # [CAMBIO] Fallback también para m1080p
    if "M1080" in f or "MICRO" in f: return "m1080p"
    
    if "1080" in f: return "1080p"
    if "720" in f: return "720p"
    
    return "1080p" # Valor por defecto

# --- 2. DATOS TÉCNICOS (Solo Codec y Bits) ---

def obtener_datos_tecnicos(filepath):
    try:
        cmd = ["mediainfo", "--Output=JSON", filepath]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0: return {}
        data = json.loads(result.stdout)
        
        for track in data.get("media", {}).get("track", []):
            if track.get("@type") == "Video":
                codec_id = track.get("Format", "")
                bits = track.get("BitDepth", "")
                return {"codec": codec_id, "bits": bits}
    except: pass
    return {}

# --- 3. UTILIDADES DE SISTEMA ---

def fijar_permisos(ruta_archivo):
    try:
        os.chown(ruta_archivo, PUID, PGID)
        os.chmod(ruta_archivo, 0o666)
        print(f"      [PERMISOS] Cambiados a UID:{PUID} GID:{PGID}")
    except Exception as e:
        print(f"      [!] Error cambiando permisos: {e}")

def renombrar_archivo_final(ruta_archivo, titulo_peli, formato_foro, titulo_original):
    try:
        directorio = os.path.dirname(ruta_archivo)
        ext = os.path.splitext(ruta_archivo)[1]
        
        # A. Limpieza de Título y Año
        match_anio = re.search(r'\((\d{4})\)', titulo_peli)
        anio_str = f"({match_anio.group(1)})" if match_anio else ""
        titulo_solo = titulo_peli.replace(anio_str, "").strip()

        # B. Obtención de datos
        source = extraer_fuente_del_titulo(titulo_original)
        resolucion = extraer_resolucion_del_texto(titulo_original, formato_foro)
        tech = obtener_datos_tecnicos(ruta_archivo)
        
        # C. Lógica de Codec (HEVC vs AVC)
        codec_raw = tech.get("codec", "").upper()
        # Si el título dice x265 o el archivo es HEVC -> HEVC
        es_x265 = "HEVC" in codec_raw or "X265" in titulo_original.upper()
        codec_str = "HEVC" if es_x265 else "AVC"
        
        # D. Bits (Solo si es 10 o 12)
        bits_str = f"{tech.get('bits')}bit" if tech.get("bits") in ["10", "12"] else ""
        
        # E. Construcción: [Fuente] [Resolución] [Codec] [Bits]
        tags = [t for t in [source, resolucion, codec_str, bits_str] if t]
        etiquetas = " ".join(tags)
        
        nombre_limpio = re.sub(r'[\\/*?:"<>|]', "", titulo_solo)
        nuevo_nombre = f"{nombre_limpio} {anio_str} [{etiquetas}]{ext}"
        nueva_ruta = os.path.join(directorio, nuevo_nombre)
        
        os.rename(ruta_archivo, nueva_ruta)
        print(f"      [RENOMBRADO] -> {nuevo_nombre}")
        
        fijar_permisos(nueva_ruta)
        return nueva_ruta

    except Exception as e:
        print(f"      [!] Error renombrando: {e}")
        fijar_permisos(ruta_archivo)
        return ruta_archivo

def procesar_carpeta_final(carpeta_destino, titulo_peli, formato_res, titulo_original):
    archivos = os.listdir(carpeta_destino)
    archivo_comprimido = None
    archivo_video = None
    
    # Detección
    for f in archivos:
        lf = f.lower()
        if (lf.endswith(".rar") or lf.endswith(".zip") or lf.endswith(".7z") or lf.endswith(".001")):
            if "part" in lf and "part1" not in lf and "part01" not in lf and ".part" not in lf: continue
            archivo_comprimido = f
        if lf.endswith(".mkv") or lf.endswith(".mp4") or lf.endswith(".avi"):
            archivo_video = f

    # Extracción
    se_ha_extraido = False
    if archivo_comprimido and not archivo_video:
        print(f"      [EXTRAER] {archivo_comprimido}")
        ruta_rar = os.path.join(carpeta_destino, archivo_comprimido)
        subprocess.run(["7z", "x", ruta_rar, f"-o{carpeta_destino}", "-y"], stdout=subprocess.DEVNULL)
        se_ha_extraido = True
        
        # Refrescar búsqueda de video
        for f in os.listdir(carpeta_destino):
             if f.lower().endswith(".mkv") or f.lower().endswith(".mp4"):
                 archivo_video = f
                 break

    # Limpieza de comprimidos
    if se_ha_extraido or archivo_comprimido:
        patrones_basura = ["*.rar", "*.zip", "*.7z", "*.r??", "*.part*", "*.001", "*.iso"]
        print("      [LIMPIEZA] Borrando archivos comprimidos...")
        for pat in patrones_basura:
            for f_basura in glob.glob(os.path.join(carpeta_destino, pat)):
                try: os.remove(f_basura)
                except: pass

    # Renombrado
    if archivo_video:
        ruta_video = os.path.join(carpeta_destino, archivo_video)
        return renombrar_archivo_final(ruta_video, titulo_peli, formato_res, titulo_original)
        
    return False
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
    t = titulo_original.upper()
    f = formato_foro.upper()
    
    if "2160P" in t or "4K" in t or "UHD" in t: return "2160p"
    if "M1080P" in t or "MICRO" in t: return "m1080p"
    if "1080P" in t or "FULLHD" in t or "FHD" in t: return "1080p"
    if "720P" in t or "HD" in t: return "720p"
    
    if "2160" in f or "4K" in f: return "2160p"
    if "M1080" in f or "MICRO" in f: return "m1080p"
    if "1080" in f: return "1080p"
    if "720" in f: return "720p"
    
    return "1080p"

# --- 2. DATOS TÉCNICOS ---

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

# --- 3. GESTIÓN INTELIGENTE DE COMPRIMIDOS ---

def encontrar_archivo_cabecera(carpeta):
    """
    Busca el archivo 'maestro' que inicia la descompresión.
    Prioridad: part01.rar > .001 > .rar (simple) > .zip
    """
    archivos = os.listdir(carpeta)
    archivos.sort() # Ordenar para asegurar que part01 salga antes que part02
    
    candidato = None
    
    for f in archivos:
        lf = f.lower()
        
        # 1. Prioridad Máxima: Archivos explícitos "part1" o "part01"
        # Ejemplo: peli.part01.rar, peli.part1.rar
        if ".part" in lf and ".rar" in lf:
            if "part1." in lf or "part01." in lf or "part001." in lf:
                return f # Encontrado el líder indiscutible
            continue # Si es part02, part03... lo ignoramos
            
        # 2. Archivos divididos numéricos (.001)
        if lf.endswith(".001"):
            return f
            
        # 3. Archivos RAR estándar (Cuidado con no coger subs o partes .r00)
        if lf.endswith(".rar"):
            # Si no tiene "part" en el nombre, podría ser un RAR único o un .rar de un set antiguo
            # Nos lo guardamos como candidato si no encontramos nada mejor
            if "part" not in lf:
                candidato = f

        # 4. Archivos ZIP
        if lf.endswith(".zip"):
             if "part" not in lf or ("part1" in lf or "part01" in lf):
                 candidato = f

    return candidato

# --- 4. UTILIDADES DE SISTEMA ---

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
        
        match_anio = re.search(r'\((\d{4})\)', titulo_peli)
        anio_str = f"({match_anio.group(1)})" if match_anio else ""
        titulo_solo = titulo_peli.replace(anio_str, "").strip()

        source = extraer_fuente_del_titulo(titulo_original)
        resolucion = extraer_resolucion_del_texto(titulo_original, formato_foro)
        tech = obtener_datos_tecnicos(ruta_archivo)
        
        codec_raw = tech.get("codec", "").upper()
        es_x265 = "HEVC" in codec_raw or "X265" in titulo_original.upper()
        codec_str = "HEVC" if es_x265 else "AVC"
        
        bits_str = f"{tech.get('bits')}bit" if tech.get("bits") in ["10", "12"] else ""
        
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
    # 1. Búsqueda de VIDEO existente (por si ya se extrajo o no estaba comprimido)
    archivo_video = None
    for f in os.listdir(carpeta_destino):
        lf = f.lower()
        if lf.endswith((".mkv", ".mp4", ".avi")):
            archivo_video = f
            break

    # 2. Búsqueda y Extracción INTELIGENTE
    if not archivo_video:
        archivo_cabecera = encontrar_archivo_cabecera(carpeta_destino)
        
        if archivo_cabecera:
            print(f"      [EXTRAER] Detectado archivo maestro: {archivo_cabecera}")
            ruta_rar = os.path.join(carpeta_destino, archivo_cabecera)
            
            # Usamos subprocess.run sin ocultar errores críticos para debug,
            # pero mantenemos stdout limpio.
            try:
                subprocess.run(["7z", "x", ruta_rar, f"-o{carpeta_destino}", "-y"], 
                               check=True, stdout=subprocess.DEVNULL)
                print("      [OK] Descompresión finalizada correctamente.")
            except subprocess.CalledProcessError:
                print("      [ERROR] Falló la descompresión. El archivo puede estar corrupto.")
                return False

            # Refrescar búsqueda de video tras extraer
            for f in os.listdir(carpeta_destino):
                 if f.lower().endswith((".mkv", ".mp4", ".avi")):
                     archivo_video = f
                     break
        else:
            # No hay video ni comprimidos reconocibles
            pass

    # 3. Limpieza de comprimidos (Solo si tenemos video final)
    if archivo_video:
        patrones_basura = ["*.rar", "*.zip", "*.7z", "*.r??", "*.part*", "*.001", "*.iso", "*.z??"]
        print("      [LIMPIEZA] Borrando archivos comprimidos y basura...")
        for pat in patrones_basura:
            for f_basura in glob.glob(os.path.join(carpeta_destino, pat)):
                try: os.remove(f_basura)
                except: pass
        
        # Renombrado Final
        ruta_video = os.path.join(carpeta_destino, archivo_video)
        return renombrar_archivo_final(ruta_video, titulo_peli, formato_res, titulo_original)
    else:
        print("      [!] No se encontró archivo de video válido tras el procesado.")
        
    return False
import os
import re
import subprocess
import json
import glob
from config import PUID, PGID, RAR_PASSWORD
from utils import sanitizar_nombre

# --- 1. EXTRACCIÓN BASADA EN TEXTO ---

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

# --- 3. GESTIÓN DE COMPRIMIDOS ---

def normalizar_nombres_rar(carpeta):
    print("      [NORMALIZAR] Estandarizando nombres de archivos...")
    archivos = os.listdir(carpeta)
    for f in archivos:
        path_old = os.path.join(carpeta, f)
        if os.path.isfile(path_old):
            if any(x in f.lower() for x in [".rar", ".zip", ".00", ".part"]):
                nuevo_nombre = f.lower()
                if f != nuevo_nombre:
                    path_new = os.path.join(carpeta, nuevo_nombre)
                    try: os.rename(path_old, path_new)
                    except Exception as e: print(f"      [!] No se pudo renombrar {f}: {e}")

def encontrar_archivo_cabecera(carpeta):
    archivos = sorted(os.listdir(carpeta))
    for f in archivos:
        lf = f.lower()
        if re.search(r'\.part0*1\.rar$', lf): return f
        if lf.endswith(".rar") and ".part" not in lf: return f
        if lf.endswith(".001"): return f
    return None

def fijar_permisos(ruta_archivo):
    try:
        os.chown(ruta_archivo, PUID, PGID)
        os.chmod(ruta_archivo, 0o666)
    except: pass

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
        
        # Datos del codec
        codec_raw = tech.get("codec", "").upper()
        es_x265 = "HEVC" in codec_raw or "X265" in titulo_original.upper()
        codec_str = "HEVC" if es_x265 else "AVC"
        
        # --- CAMBIO AQUI: FORMATO BITS (10b en vez de 10bit) ---
        bits_val = tech.get('bits')
        bits_str = f"{bits_val}b" if bits_val in ["10", "12"] else ""
        
        # Criterio de tamaño para x265 1080p
        if es_x265 and ("1080" in resolucion or resolucion == "m1080p"):
            try:
                tamanho_bytes = os.path.getsize(ruta_archivo)
                tamanho_gb = tamanho_bytes / (1024 * 1024 * 1024)
                
                if tamanho_gb >= 6.5:
                    resolucion = "1080p"
                else:
                    resolucion = "m1080p"
                    
                print(f"      [INFO] Archivo x265 de {tamanho_gb:.2f} GB -> Clasificado como {resolucion}")
            except: pass

        tags = [t for t in [source, resolucion, codec_str, bits_str] if t]
        etiquetas = " ".join(tags)
        
        nombre_base_limpio = sanitizar_nombre(titulo_solo)
        
        nuevo_nombre = f"{nombre_base_limpio} {anio_str} [{etiquetas}]{ext}"
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
    print(f"   [POST] Iniciando procesado en: {carpeta_destino}")

    archivo_video = None
    for f in os.listdir(carpeta_destino):
        if f.lower().endswith((".mkv", ".mp4", ".avi")):
            archivo_video = f
            break

    if not archivo_video:
        normalizar_nombres_rar(carpeta_destino)
        archivo_cabecera = encontrar_archivo_cabecera(carpeta_destino)
        
        if archivo_cabecera:
            ruta_rar = os.path.join(carpeta_destino, archivo_cabecera)
            print(f"      [EXTRAER] Archivo maestro detectado: {archivo_cabecera}")
            
            cmd = ["7z", "x", ruta_rar, f"-o{carpeta_destino}", "-y", f"-p{RAR_PASSWORD}"]
            
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    print("      [OK] Descompresión exitosa.")
                else:
                    print(f"      [ERROR 7-ZIP] Código: {res.returncode}")
                    if "Wrong password" in res.stderr:
                        print("      [!] Contraseña incorrecta.")
                    elif "No more files" in res.stderr or "Break" in res.stderr:
                         print("      [!] Error de cadena: Faltan partes o están corruptas.")
                    else:
                        print(f"      [LOG] {res.stderr[-300:]}")
                    return False
            except Exception as e:
                print(f"      [!] Excepción: {e}")
                return False

            for f in os.listdir(carpeta_destino):
                 if f.lower().endswith((".mkv", ".mp4", ".avi")):
                     archivo_video = f
                     break
        else:
            print("      [INFO] No se detectaron archivos comprimidos válidos (part1).")

    if archivo_video:
        patrones_basura = ["*.rar", "*.zip", "*.7z", "*.r??", "*.part*", "*.001", "*.iso", "*.z??"]
        print("      [LIMPIEZA] Eliminando archivos comprimidos...")
        for pat in patrones_basura:
            for f_basura in glob.glob(os.path.join(carpeta_destino, pat)):
                try: os.remove(f_basura)
                except: pass
        
        ruta_video = os.path.join(carpeta_destino, archivo_video)
        return renombrar_archivo_final(ruta_video, titulo_peli, formato_res, titulo_original)
    
    return False
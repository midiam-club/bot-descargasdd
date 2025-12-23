import os
import shutil
import subprocess
import config
from utils import sanitizar_nombre
from pymediainfo import MediaInfo

# Extensiones de video soportadas
VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.iso')

def extraer_rar(ruta_rar, destino):
    """
    Extrae un archivo RAR en el destino usando 'unrar'.
    Retorna True si tuvo éxito.
    """
    try:
        # x: extraer con estructura completa (o e para flat)
        # -o+: sobrescribir si existe
        # -pPASSWORD: contraseña si la hay
        cmd = ["unrar", "x", "-o+", f"-p{config.RAR_PASSWORD}", ruta_rar, destino]
        
        # Ejecutamos silenciando la salida para no ensuciar logs, salvo error
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        if result.returncode == 0:
            return True
        else:
            print(f"      [ERROR UNRAR] Código {result.returncode}: {result.stderr.decode('utf-8')}")
            return False
    except Exception as e:
        print(f"      [EXCEPCIÓN UNRAR] {e}")
        return False

def buscar_video_principal(carpeta):
    """
    Busca el archivo de video más grande dentro de la carpeta (recursivo).
    """
    archivo_mayor = None
    tamano_mayor = 0
    
    for root, dirs, files in os.walk(carpeta):
        for f in files:
            if f.lower().endswith(VIDEO_EXT):
                ruta_completa = os.path.join(root, f)
                try:
                    size = os.path.getsize(ruta_completa)
                    if size > tamano_mayor:
                        tamano_mayor = size
                        archivo_mayor = ruta_completa
                except: pass
                
    return archivo_mayor

def limpiar_carpeta(carpeta, conservar_archivo):
    """
    Borra todo lo que haya en la carpeta excepto el archivo de video final.
    """
    for root, dirs, files in os.walk(carpeta, topdown=False):
        for f in files:
            ruta = os.path.join(root, f)
            if ruta != conservar_archivo:
                try: os.remove(ruta)
                except: pass
        for d in dirs:
            ruta_dir = os.path.join(root, d)
            try: os.rmdir(ruta_dir)
            except: pass

def analizar_video_tecnico(ruta_video):
    """
    Usa MediaInfo para analizar el archivo de video.
    Devuelve una tupla: (codec_tag, hdr_tag)
    Ejemplos: ("HEVC", "DV"), ("AVC", ""), ("HEVC", "HDR10+")
    """
    codec_tag = ""
    hdr_tag = ""
    
    try:
        media_info = MediaInfo.parse(ruta_video)
        
        for track in media_info.tracks:
            if track.track_type == "Video":
                
                # --- 1. CODEC ---
                # track.format suele ser 'HEVC', 'AVC', 'MPEG-4 Visual', etc.
                fmt = track.format
                if fmt == "HEVC":
                    codec_tag = "HEVC"
                elif fmt == "AVC":
                    codec_tag = "AVC" # Opcional, si quieres etiquetar x264
                
                # --- 2. HDR / DOLBY VISION ---
                # track.hdr_format contiene cadenas como:
                # "Dolby Vision, Version 1.0, dvhe.05.06..."
                # "SMPTE ST 2094 App 4, Version 1, HDR10+ Profile B..."
                # "SMPTE ST 2086, HDR10 compatible"
                
                hdr_info = track.hdr_format
                
                if hdr_info:
                    hdr_upper = hdr_info.upper()
                    
                    # Prioridad 1: Dolby Vision
                    if "DOLBY" in hdr_upper and "VISION" in hdr_upper:
                        hdr_tag = "DV"
                    
                    # Prioridad 2: HDR10+ (Samsung) - Suele aparecer como SMPTE ST 2094 App 4
                    elif "HDR10+" in hdr_upper or "SMPTE ST 2094" in hdr_upper:
                        hdr_tag = "HDR10+"
                    
                    # Prioridad 3: HDR Estándar (HDR10)
                    elif "HDR" in hdr_upper or "SMPTE ST 2086" in hdr_upper:
                        hdr_tag = "HDR"
                
                # Si encontramos la pista de video, paramos de buscar (asumimos 1 pista de video principal)
                break
                
    except Exception as e:
        print(f"      [MEDIAINFO ERROR] No se pudo analizar {os.path.basename(ruta_video)}: {e}")
        
    return codec_tag, hdr_tag

def procesar_carpeta_final(carpeta_destino, titulo, formato_descarga, titulo_original):
    """
    1. Extrae RARs.
    2. Busca video principal.
    3. Analiza video con MediaInfo (Codec y HDR).
    4. Renombra usando metadatos reales.
    5. Limpia.
    """
    print(f"   [POST] Procesando carpeta: {carpeta_destino}")
    
    # 1. BUSCAR Y EXTRAER RARS
    rars = [f for f in os.listdir(carpeta_destino) if f.lower().endswith('.rar')]
    
    if rars:
        rars.sort()
        rar_a_extraer = os.path.join(carpeta_destino, rars[0])
        print(f"      [UNRAR] Extrayendo: {rars[0]}...")
        if not extraer_rar(rar_a_extraer, carpeta_destino):
            print("      [ERROR] La extracción falló. Se aborta post-procesado.")
            return False

    # 2. LOCALIZAR VIDEO
    video_final = buscar_video_principal(carpeta_destino)
    
    if not video_final:
        print("      [ERROR] No se encontró ningún archivo de video válido.")
        return False
    
    nombre_archivo_original = os.path.basename(video_final)
    ext = os.path.splitext(nombre_archivo_original)[1]
    
    # 3. ANÁLISIS TÉCNICO (MediaInfo)
    print(f"      [MEDIAINFO] Analizando metadatos de: {nombre_archivo_original}...")
    codec_real, hdr_real = analizar_video_tecnico(video_final)
    
    # 4. CONSTRUCCIÓN DEL NOMBRE
    # Empezamos con el formato que sabemos que descargamos (ej: 2160p, 1080p)
    # A veces MediaInfo devuelve dimensiones (Width/Height) pero 'formato_descarga' ya lo tenemos limpio.
    etiquetas = [formato_descarga]
    
    # Añadimos Codec si MediaInfo lo detectó como HEVC
    # (Si quieres forzar que ponga HEVC si la descarga era 'x265' aunque mediainfo falle, puedes añadir un 'or')
    if codec_real == "HEVC":
        etiquetas.append("HEVC")
    elif formato_descarga == "x265" and not codec_real: 
        # Fallback: si mediainfo falla pero sabemos que bajamos x265
        etiquetas.append("HEVC")

    # Añadimos Rango Dinámico (DV, HDR10+, HDR) solo si se detectó
    if hdr_real:
        etiquetas.append(hdr_real)
        
    tag_final = " ".join(etiquetas) # Ej: "2160p HEVC DV"
    
    nuevo_nombre = f"{sanitizar_nombre(titulo)} [{tag_final}]{ext}"
    ruta_nueva = os.path.join(carpeta_destino, nuevo_nombre)
    
    # 5. RENOMBRADO Y LIMPIEZA
    try:
        shutil.move(video_final, ruta_nueva)
        print(f"      [RENOMBRE] {nombre_archivo_original} -> {nuevo_nombre}")
        
        limpiar_carpeta(carpeta_destino, ruta_nueva)
        return True
        
    except Exception as e:
        print(f"      [ERROR] Fallo al renombrar/mover final: {e}")
        return False
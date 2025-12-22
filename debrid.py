import os
import time
import requests
import re
from urllib.parse import unquote
import config
from utils import debe_aplicar_limite

# --- FUNCIONES DE SOPORTE ---

def determinar_debrid(enlace):
    """
    Decide si usar Real-Debrid (RD) o DebridLink (DL) basándose en 
    la configuración de HOSTER_PREFS en config.py.
    """
    for dominio, servicio in config.HOSTER_PREFS.items():
        if dominio in enlace.lower():
            return servicio
    return "RD" # Por defecto intentamos RD si no está en la lista

def obtener_nombre_archivo_de_url(url):
    """Intenta extraer el nombre del archivo de la URL"""
    try:
        path = unquote(url.split("?")[0])
        nombre = os.path.basename(path)
        if nombre and "." in nombre:
            return nombre
    except: pass
    return "archivo_desconocido.dat"

# --- FUNCIONES API (Devuelven Tupla: URL, Nombre) ---

def unrestrict_rd(link):
    """Desbloquea enlace con Real-Debrid"""
    if not config.RD_TOKEN: return None, None
    print(f"   [API] Solicitando a Real-Debrid: {link[:40]}...")
    try:
        url = "https://api.real-debrid.com/rest/1.0/unrestrict/link"
        headers = {"Authorization": f"Bearer {config.RD_TOKEN}"}
        r = requests.post(url, headers=headers, data={"link": link}, timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            # Retornamos URL de descarga y el nombre del fichero detectado por RD
            return data.get("download"), data.get("filename")
        elif r.status_code == 503:
            print("   [API] Real-Debrid en mantenimiento.")
        else:
            print(f"   [API] Error RD ({r.status_code}): {r.text}")
    except Exception as e: 
        print(f"   [API] Excepción conectando a RD: {e}")
    return None, None

def unrestrict_dl(link):
    """Desbloquea enlace con Debrid-Link"""
    if not config.DL_TOKEN: return None, None
    print(f"   [API] Solicitando a Debrid-Link: {link[:40]}...")
    try:
        url = "https://debrid-link.com/api/v2/downloader/add"
        headers = {"Authorization": f"Bearer {config.DL_TOKEN}"}
        r = requests.post(url, headers=headers, data={"url": link}, timeout=30)
        
        if r.status_code == 200:
            res = r.json()
            if res.get("success"):
                # DL devuelve una lista, cogemos el primer elemento
                val = res["value"][0]
                return val.get("downloadUrl"), val.get("name")
            else:
                print(f"   [API] Error DL: {res.get('error')}")
        else:
            print(f"   [API] Error HTTP DL: {r.status_code}")
    except Exception as e:
        print(f"   [API] Excepción conectando a DL: {e}")
    return None, None

def obtener_enlace_premium(link):
    """
    Orquestador principal: Decide qué servicio usar, lo intenta, 
    y si falla prueba el otro (Fallback).
    Devuelve: (url_descarga, nombre_archivo)
    """
    servicio_preferido = determinar_debrid(link)
    
    # 1. Intento Principal
    if servicio_preferido == "RD":
        url, name = unrestrict_rd(link)
        if url: return url, name
        # Si falla y tenemos DL configurado, probamos fallback
        if config.DL_TOKEN:
            print("   [INFO] Falló RD. Probando fallback con Debrid-Link...")
            return unrestrict_dl(link)
            
    elif servicio_preferido == "DL":
        url, name = unrestrict_dl(link)
        if url: return url, name
        # Si falla y tenemos RD configurado, probamos fallback
        if config.RD_TOKEN:
            print("   [INFO] Falló DL. Probando fallback con Real-Debrid...")
            return unrestrict_rd(link)
            
    return None, None

# --- FUNCIÓN DE DESCARGA (Con Limitador) ---

def descargar_archivo(url, carpeta_destino, titulo_referencia):
    """
    Descarga el archivo a la carpeta destino aplicando limitador de velocidad
    si corresponde según hora y configuración.
    """
    if not os.path.exists(carpeta_destino):
        os.makedirs(carpeta_destino)
        
    # Nombre temporal basado en la URL final premium
    nombre_archivo = obtener_nombre_archivo_de_url(url)
    ruta_temp = os.path.join(carpeta_destino, nombre_archivo + ".part")
    ruta_final = os.path.join(carpeta_destino, nombre_archivo)
    
    # Si ya existe el final, asumimos descargado
    if os.path.exists(ruta_final):
        print(f"   [SKIP] Archivo ya existe: {nombre_archivo}")
        return ruta_final

    print(f"   [DOWNLOAD] Iniciando: {nombre_archivo}")
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # stream=True es vital para descargas grandes y control de velocidad
        with requests.get(url, stream=True, allow_redirects=True, headers=headers, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            with open(ruta_temp, 'wb') as f:
                start_time = time.time()
                descargado = 0
                chunk_size = 1024 * 1024 # 1 MB buffer
                
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        descargado += len(chunk)
                        
                        # --- LÓGICA DEL LIMITADOR DE VELOCIDAD ---
                        # Solo entramos si el interruptor (ENABLE) está ON 
                        # Y estamos en hora (debe_aplicar_limite)
                        if config.SPEED_LIMIT_MB > 0 and debe_aplicar_limite():
                            
                            # Tiempo que deberíamos haber tardado para respetar el límite
                            # Ejemplo: 1MB / 5MBs = 0.2 segundos
                            tiempo_esperado = len(chunk) / (config.SPEED_LIMIT_MB * 1024 * 1024)
                            
                            # Tiempo que hemos tardado realmente (CPU + Red)
                            tiempo_real = time.time() - start_time
                            
                            # Si hemos ido muy rápido (real < esperado), dormimos la diferencia
                            sleep_time = tiempo_esperado - tiempo_real
                            if sleep_time > 0:
                                time.sleep(sleep_time)
                            
                            # Reseteamos el reloj para medir el siguiente bloque limpiamente
                            start_time = time.time()
                        else:
                            # Si no hay límite, actualizamos start_time para que el cálculo 
                            # no acumule errores si de repente entra el límite luego.
                            start_time = time.time()

        # Al finalizar, renombramos quitando el .part
        os.rename(ruta_temp, ruta_final)
        print(f"   [OK] Descarga completada: {nombre_archivo}")
        return ruta_final

    except Exception as e:
        print(f"   [ERROR] Fallo en descarga de {nombre_archivo}: {e}")
        if os.path.exists(ruta_temp):
            try: os.remove(ruta_temp)
            except: pass
        return None
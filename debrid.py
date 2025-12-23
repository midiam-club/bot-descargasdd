import os
import time
import requests
import config
from urllib.parse import unquote
from utils import debe_aplicar_limite, sanitizar_nombre
from monitor import state 

def determinar_debrid(enlace):
    for dominio, servicio in config.HOSTER_PREFS.items():
        if dominio in enlace.lower():
            return servicio
    return "RD" 

def obtener_nombre_archivo_de_url(url):
    try:
        path = unquote(url.split("?")[0])
        nombre = os.path.basename(path)
        if nombre and "." in nombre:
            return sanitizar_nombre(nombre)
    except: pass
    return "archivo_desconocido.dat"

def unrestrict_rd(link):
    if not config.RD_TOKEN: return None, None
    print(f"   [API] Solicitando a Real-Debrid: {link[:40]}...")
    try:
        url = "https://api.real-debrid.com/rest/1.0/unrestrict/link"
        headers = {"Authorization": f"Bearer {config.RD_TOKEN}"}
        r = requests.post(url, headers=headers, data={"link": link}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            return data.get("download"), sanitizar_nombre(data.get("filename"))
        elif r.status_code == 503:
            print("   [API] Real-Debrid en mantenimiento.")
        else:
            print(f"   [API] Error RD ({r.status_code}): {r.text}")
    except Exception as e: 
        print(f"   [API] Excepción conectando a RD: {e}")
    return None, None

def unrestrict_dl(link):
    if not config.DL_TOKEN: return None, None
    print(f"   [API] Solicitando a Debrid-Link: {link[:40]}...")
    try:
        url = "https://debrid-link.com/api/v2/downloader/add"
        headers = {"Authorization": f"Bearer {config.DL_TOKEN}"}
        r = requests.post(url, headers=headers, data={"url": link}, timeout=30)
        if r.status_code == 200:
            res = r.json()
            if res.get("success"):
                val = res["value"][0]
                return val.get("downloadUrl"), sanitizar_nombre(val.get("name"))
            else:
                print(f"   [API] Error DL: {res.get('error')}")
        else:
            print(f"   [API] Error HTTP DL: {r.status_code}")
    except Exception as e:
        print(f"   [API] Excepción conectando a DL: {e}")
    return None, None

def obtener_enlace_premium(link):
    servicio_preferido = determinar_debrid(link)
    
    if servicio_preferido == "RD":
        url, name = unrestrict_rd(link)
        if url: return url, name, "RD"
        
        if config.DL_TOKEN: # Fallback
            print("   [INFO] Falló RD. Probando fallback con Debrid-Link...")
            url, name = unrestrict_dl(link)
            if url: return url, name, "DL"
            
    elif servicio_preferido == "DL":
        url, name = unrestrict_dl(link)
        if url: return url, name, "DL"
        
        if config.RD_TOKEN: # Fallback
            print("   [INFO] Falló DL. Probando fallback con Real-Debrid...")
            url, name = unrestrict_rd(link)
            if url: return url, name, "RD"
            
    return None, None, None

def descargar_archivo(url, carpeta_destino, titulo_referencia, host_original=None, debrid_source=None, formato_peli=None):
    if not os.path.exists(carpeta_destino):
        os.makedirs(carpeta_destino)
        
    nombre_archivo = obtener_nombre_archivo_de_url(url)
    ruta_temp = os.path.join(carpeta_destino, nombre_archivo + ".part")
    ruta_final = os.path.join(carpeta_destino, nombre_archivo)
    
    if os.path.exists(ruta_final):
        print(f"   [SKIP] Archivo ya existe: {nombre_archivo}")
        return ruta_final

    # Bloqueo SEMÁFORO
    print(f"   [ESPERA] Esperando slot de descarga para: {nombre_archivo}...")
    state.acquire_download_slot()

    print(f"   [DOWNLOAD] Iniciando: {nombre_archivo} ({host_original}) via {debrid_source}")
    
    try:
        headers = {"User-Agent": config.DEFAULT_USER_AGENT}
        with requests.get(url, stream=True, allow_redirects=True, headers=headers, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            
            chunk_size = 8 * 1024 * 1024 
            
            with open(ruta_temp, 'wb') as f:
                start_time = time.time()
                descargado = 0
                
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        descargado += len(chunk)
                        
                        current_time = time.time()
                        elapsed = current_time - start_time
                        speed_mb = 0.0
                        if elapsed > 0:
                            speed_mb = (descargado / (1024 * 1024)) / elapsed
                        
                        # Actualizamos estado con formato incluido
                        state.update_download(
                            titulo_referencia, 
                            nombre_archivo, 
                            descargado, 
                            total_size, 
                            speed_mb, 
                            host=host_original, 
                            debrid=debrid_source,
                            formato=formato_peli
                        )

                        if config.SPEED_LIMIT_MB > 0 and config.ENABLE_SPEED_LIMIT: 
                             if debe_aplicar_limite():
                                if speed_mb > config.SPEED_LIMIT_MB:
                                    time.sleep(0.5)

        end_time = time.time()
        total_time = end_time - start_time
        avg_speed = (total_size / (1024 * 1024)) / total_time if total_time > 0 else 0
        
        m, s = divmod(total_time, 60)
        h, m = divmod(m, 60)
        duration_str = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

        os.rename(ruta_temp, ruta_final)
        
        state.release_download_slot()
        
        # IMPORTANTE: Pasamos formato_peli para que monitor separe el historial
        state.finish_download(titulo_referencia, nombre_archivo, avg_speed, duration_str, formato=formato_peli)
        
        return ruta_final

    except Exception as e:
        print(f"   [ERROR] Falló la descarga de {nombre_archivo}: {e}")
        state.release_download_slot()
        state.remove_download(titulo_referencia, nombre_archivo)
        if os.path.exists(ruta_temp):
            try: os.remove(ruta_temp)
            except: pass
        return None
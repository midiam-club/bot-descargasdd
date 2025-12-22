import os
import time
import re
import config
import database as db
import debrid
import post_procesado as post
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
import threading 
from web_server import run_web_server 
from monitor import state
from urllib.parse import urlparse

def obtener_contexto_navegador(browser):
    if os.path.exists(config.SESSION_FILE):
        try:
            return browser.new_context(storage_state=config.SESSION_FILE)
        except:
            return browser.new_context(user_agent=config.DEFAULT_USER_AGENT)
    return browser.new_context(user_agent=config.DEFAULT_USER_AGENT)

def guardar_sesion(context):
    try: context.storage_state(path=config.SESSION_FILE)
    except: pass

def extraer_numero_parte(filename):
    fn = filename.lower()
    match = re.search(r'(?:part|pt)\.?\s*(\d+)', fn)
    if match: return int(match.group(1))
    match_ext = re.search(r'\.(?:z|r|)(\d{2,3})$', fn)
    if match_ext: 
        if fn.endswith((".mkv", ".mp4", ".avi", ".iso")): return 1
        return int(match_ext.group(1))
    return 1

# --- LÓGICA DE DESCARGA MODIFICADA ---
def intentar_descarga(variante, titulo):
    fmt = variante["formato"]
    raw_links = [l.strip() for l in variante["enlaces"].split('\n') if l.strip()]
    titulo_orig = variante["titulo_orig"]
    if not raw_links: return False
    
    print(f"   [ANÁLISIS] Resolviendo metadatos de {len(raw_links)} enlaces para {fmt}...")
    mapa_partes = {}
    
    for link in raw_links:
        # AHORA OBTENEMOS 3 VALORES
        url_prem, nombre_fichero, debrid_used = debrid.obtener_enlace_premium(link)
        
        if not url_prem or not nombre_fichero: continue
        
        # Extraemos host limpio (ej: 1fichier.com)
        try:
            parsed = urlparse(link)
            host_clean = parsed.netloc.replace("www.", "")
        except: 
            host_clean = "desconocido"

        num_parte = extraer_numero_parte(nombre_fichero)
        prioridad = 999
        for idx, dom in enumerate(config.PRIORIDAD_DOMINIOS):
            if dom.lower() in link.lower():
                prioridad = idx
                break
        
        if num_parte not in mapa_partes: mapa_partes[num_parte] = []
        mapa_partes[num_parte].append({
            "url": url_prem, 
            "name": nombre_fichero, 
            "prio": prioridad,
            "host": host_clean,      # Guardamos el host
            "debrid": debrid_used    # Guardamos el debrid usado (RD/DL)
        })

    if not mapa_partes: return False

    carpeta = os.path.join(config.DOWNLOAD_DIR, f"{titulo} [{fmt}]")
    if not os.path.exists(carpeta): os.makedirs(carpeta)
    
    total_partes = len(mapa_partes)
    partes_descargadas = 0
    
    for num_parte in sorted(mapa_partes.keys()):
        candidatos = sorted(mapa_partes[num_parte], key=lambda x: x["prio"])
        exito_parte = False
        for cand in candidatos:
            # PASAMOS LA INFO A LA DESCARGA
            ruta_final = debrid.descargar_archivo(
                cand["url"], 
                carpeta, 
                titulo, 
                host_original=cand["host"], 
                debrid_source=cand["debrid"]
            )
            
            if ruta_final:
                partes_descargadas += 1
                exito_parte = True
                break 
        if not exito_parte: return False

    if partes_descargadas == total_partes:
        return post.procesar_carpeta_final(carpeta, titulo, fmt, titulo_orig)
    return False

def worker_wrapper(pid, datos_peli):
    try: worker_descarga_pelicula(pid, datos_peli)
    except Exception as e: print(f"[Worker Error] Fallo en película ID {pid}: {e}")

def worker_descarga_pelicula(pid, datos_peli):
    titulo = datos_peli["titulo"]
    variantes = datos_peli["variantes"]
    mapa = {v["formato"]: v for v in variantes}
    print(f"[Worker {pid}] 🚀 Iniciando análisis para: {titulo}")
    
    orden_hd = ["x265", "1080p", "m1080p"]
    hd_descargada = False
    for fmt in orden_hd:
        if fmt in mapa:
            if intentar_descarga(mapa[fmt], titulo):
                db.marcar_cascada_descargado(pid, fmt)
                state.mark_completed(titulo) 
                hd_descargada = True
                break 
    if "2160p" in mapa:
        if intentar_descarga(mapa["2160p"], titulo):
            db.marcar_cascada_descargado(pid, "2160p")
            state.mark_completed(titulo)
    print(f"[Worker {pid}] 🏁 Tarea finalizada para: {titulo}")

def flujo_descargas():
    print("\n[*] --- BUSCANDO TAREAS PENDIENTES ---")
    conn = db.get_connection()
    cur = conn.cursor()
    pendientes_raw = db.obtener_pendientes(cur)
    cur.close()
    conn.close()
    if not pendientes_raw:
        print("[*] No hay descargas pendientes.")
        return
    data_map = {}
    for r in pendientes_raw:
        did, pid, tit, fmt, lnk, torig = r
        if pid not in data_map: data_map[pid] = {"titulo": tit, "variantes": []}
        data_map[pid]["variantes"].append({"id": did, "formato": fmt, "enlaces": lnk, "titulo_orig": torig})
    cola_de_trabajo = list(data_map.items())
    hilos_activos = []
    print(f"[*] Se encontraron {len(cola_de_trabajo)} películas para procesar.")
    while cola_de_trabajo or hilos_activos:
        hilos_activos = [t for t in hilos_activos if t.is_alive()]
        limite_gestores_pelicula = 5 
        while len(hilos_activos) < limite_gestores_pelicula and cola_de_trabajo:
            pid, datos = cola_de_trabajo.pop(0)
            print(f"[Gestor] Iniciando hilo para: {datos['titulo']} (Activos: {len(hilos_activos)+1}/{limite_gestores_pelicula})")
            t = threading.Thread(target=worker_wrapper, args=(pid, datos))
            t.daemon = True
            t.start()
            hilos_activos.append(t)
        time.sleep(2)

def main():
    db.init_db()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = obtener_contexto_navegador(browser)
        page = context.new_page()
        print("[*] Bot iniciado. Comprobando foro...")
        flujo_descargas()
        browser.close()

if __name__ == "__main__":
    print("[SYSTEM] Arrancando servidor web en puerto 8000...")
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    while True:
        try: main()
        except Exception as e:
            print(f"[CRASH] Error principal: {e}")
            time.sleep(30)
        print(f"[*] Durmiendo {config.CHECK_INTERVAL} segundos...")
        time.sleep(config.CHECK_INTERVAL)
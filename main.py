import os
import time
import re
import threading
import config
import database as db
import debrid
import post_procesado as post
from playwright.sync_api import sync_playwright
from web_server import run_web_server
from monitor import state
from utils import sanitizar_nombre # <--- IMPORTANTE

# --- GESTIÓN DE SESIÓN ---
def obtener_contexto_navegador(browser):
    if os.path.exists(config.SESSION_FILE):
        print(f"   [SESIÓN] Cargando cookies desde: {config.SESSION_FILE}")
        try:
            return browser.new_context(storage_state=config.SESSION_FILE)
        except:
            return browser.new_context()
    return browser.new_context()

def guardar_sesion(context):
    try: context.storage_state(path=config.SESSION_FILE)
    except: pass

# --- UTILIDADES ---
def extraer_numero_parte(filename):
    fn = filename.lower()
    match = re.search(r'(?:part|pt)\.?\s*(\d+)', fn)
    if match: return int(match.group(1))
    match_ext = re.search(r'\.(?:z|r|)(\d{2,3})$', fn)
    if match_ext: 
        if fn.endswith((".mkv", ".mp4", ".avi", ".iso")): return 1
        return int(match_ext.group(1))
    return 1

# --- LÓGICA DE DESCARGA ---
def intentar_descarga(variante, titulo):
    fmt = variante["formato"]
    raw_links = [l.strip() for l in variante["enlaces"].split('\n') if l.strip()]
    titulo_orig = variante["titulo_orig"]
    
    if not raw_links: return False
    
    mapa_partes = {}
    for link in raw_links:
        url_prem, nombre_fichero = debrid.obtener_enlace_premium(link)
        if not url_prem or not nombre_fichero: continue
            
        num_parte = extraer_numero_parte(nombre_fichero)
        prioridad = 999
        for idx, dom in enumerate(config.PRIORIDAD_DOMINIOS):
            if dom.lower() in link.lower():
                prioridad = idx
                break
        
        if num_parte not in mapa_partes: mapa_partes[num_parte] = []
        mapa_partes[num_parte].append({
            "url": url_prem, "name": nombre_fichero, "prio": prioridad
        })

    if not mapa_partes: return False

    # --- CAMBIO AQUÍ: SANITIZAR NOMBRE DE CARPERTA ---
    titulo_limpio_win = sanitizar_nombre(titulo)
    carpeta = os.path.join(config.DOWNLOAD_DIR, f"{titulo_limpio_win} [{fmt}]")
    
    if not os.path.exists(carpeta): os.makedirs(carpeta)
    
    total_partes = len(mapa_partes)
    partes_descargadas = 0
    
    for num_parte in sorted(mapa_partes.keys()):
        candidatos = sorted(mapa_partes[num_parte], key=lambda x: x["prio"])
        exito_parte = False
        for cand in candidatos:
            ruta_final = debrid.descargar_archivo(cand["url"], carpeta, titulo)
            if ruta_final:
                partes_descargadas += 1
                exito_parte = True
                break
        
        if not exito_parte: return False

    if partes_descargadas == total_partes:
        return post.procesar_carpeta_final(carpeta, titulo, fmt, titulo_orig)
    return False

# --- WORKER WRAPPER ---
def worker_wrapper(pid, datos_peli):
    try:
        worker_descarga_pelicula(pid, datos_peli)
    except Exception as e:
        print(f"[Worker Error] Fallo en película ID {pid}: {e}")

def worker_descarga_pelicula(pid, datos_peli):
    titulo = datos_peli["titulo"]
    variantes = datos_peli["variantes"]
    mapa = {v["formato"]: v for v in variantes}
    
    print(f"[Worker] 🚀 Analizando: {titulo}")
    
    orden_hd = ["x265", "1080p", "m1080p"]
    hd_descargada = False
    for fmt in orden_hd:
        if fmt in mapa:
            if intentar_descarga(mapa[fmt], titulo):
                db.marcar_cascada_descargado(pid, fmt)
                hd_descargada = True
                break
    
    if "2160p" in mapa:
        if intentar_descarga(mapa["2160p"], titulo):
            db.marcar_cascada_descargado(pid, "2160p")
    
    print(f"[Worker] 🏁 Finalizado: {titulo}")

# --- FLUJO DINÁMICO ---
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
        if pid not in data_map: 
            data_map[pid] = {"titulo": tit, "variantes": []}
        data_map[pid]["variantes"].append({
            "id": did, "formato": fmt, "enlaces": lnk, "titulo_orig": torig
        })
    
    cola_de_trabajo = list(data_map.items())
    hilos_activos = []

    print(f"[*] Se encontraron {len(cola_de_trabajo)} películas para procesar.")

    while cola_de_trabajo or hilos_activos:
        hilos_activos = [t for t in hilos_activos if t.is_alive()]
        
        # --- CAMBIO IMPORTANTE ---
        # No usamos state.get_max_parallel() aquí.
        # Ponemos un límite fijo alto de "Gestores de Película" (ej: 5)
        # Esto permite que hasta 5 películas se preparen/descompriman a la vez,
        # pero el límite de DESCARGA REAL lo controla debrid.py
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
        try:
            main()
        except Exception as e:
            print(f"[CRASH] Error principal: {e}")
            time.sleep(30)
        print(f"[*] Durmiendo {config.CHECK_INTERVAL} segundos...")
        time.sleep(config.CHECK_INTERVAL)
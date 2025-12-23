import os
import time
import re
import threading
import config
import database as db
import debrid
import post_procesado as post
import scraper 
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
from web_server import run_web_server
from monitor import state
from urllib.parse import urlparse
from utils import sanitizar_nombre 

# --- NAVEGADOR (LIMPIO, SIN SESIÓN PREVIA) ---

def obtener_contexto_navegador(browser):
    """
    Crea un contexto de navegador totalmente nuevo y limpio.
    No carga cookies ni sesiones anteriores.
    """
    print("   [NAVEGADOR] Iniciando sesión limpia (Incógnito)...")
    return browser.new_context(user_agent=config.DEFAULT_USER_AGENT)

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

# --- DESCARGA ---

def _descargar_parte_wrapper(candidatos, carpeta, titulo, fmt):
    for cand in candidatos:
        print(f"      [INTENTO] Parte {cand['part_num']} usando {cand['host']} (Prio: {cand['prio']})")
        ruta = debrid.descargar_archivo(
            cand["url"], 
            carpeta, 
            titulo, 
            host_original=cand["host"], 
            debrid_source=cand["debrid"],
            formato_peli=fmt
        )
        if ruta: return True
    return False

def intentar_descarga(variante, titulo):
    fmt = variante["formato"]
    raw_links = [l.strip() for l in variante["enlaces"].split('\n') if l.strip()]
    titulo_orig = variante["titulo_orig"]
    
    if not raw_links: return False
    
    print(f"   [ANÁLISIS] Resolviendo {len(raw_links)} enlaces para {fmt}...")
    
    mapa_partes = {}
    for link in raw_links:
        url_prem, nombre_fichero, debrid_used = debrid.obtener_enlace_premium(link)
        if not url_prem or not nombre_fichero: continue
        
        try:
            parsed = urlparse(link)
            host_clean = parsed.netloc.replace("www.", "")
        except: host_clean = "desconocido"

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
            "host": host_clean, 
            "debrid": debrid_used,
            "part_num": num_parte
        })

    if not mapa_partes: return False

    titulo_limpio = sanitizar_nombre(titulo)
    carpeta = os.path.join(config.DOWNLOAD_DIR, f"{titulo_limpio} [{fmt}]")
    if not os.path.exists(carpeta): os.makedirs(carpeta)
    
    total_partes = len(mapa_partes)
    partes_exitosas = 0
    
    print(f"   [LANZAMIENTO] Descarga paralela ({total_partes} partes) para: {titulo_limpio}")
    state.init_movie(titulo, total_partes)

    with ThreadPoolExecutor(max_workers=len(mapa_partes) + 2) as executor:
        futures = []
        for num_parte in mapa_partes:
            candidatos_ordenados = sorted(mapa_partes[num_parte], key=lambda x: x["prio"])
            futures.append(executor.submit(_descargar_parte_wrapper, candidatos_ordenados, carpeta, titulo, fmt))
        
        for future in as_completed(futures):
            if future.result(): partes_exitosas += 1

    if partes_exitosas == total_partes:
        print(f"   [POST] Descarga de [{fmt}] completa. Iniciando extracción INMEDIATA...")
        state.update_extraction(titulo, 0)
        res = post.procesar_carpeta_final(carpeta, titulo, fmt, titulo_orig)
        state.purge_movie(titulo)
        return res
    else:
        print(f"   [ERROR] Incompleto: {partes_exitosas}/{total_partes} partes.")
        state.purge_movie(titulo)
        return False

# --- WORKERS ---

def worker_wrapper(pid, datos_peli):
    try: worker_descarga_pelicula(pid, datos_peli)
    except Exception as e:
        print(f"[Worker Error] ID {pid}: {e}")
        state.purge_movie(datos_peli["titulo"])

def worker_descarga_pelicula(pid, datos_peli):
    titulo = datos_peli["titulo"]
    variantes = datos_peli["variantes"]
    mapa = {v["formato"]: v for v in variantes}
    
    print(f"[Worker {pid}] 🚀 Iniciando flujo para: {titulo}")
    
    orden_hd = ["x265", "1080p", "m1080p"]
    for fmt in orden_hd:
        if fmt in mapa:
            if intentar_descarga(mapa[fmt], titulo):
                db.marcar_cascada_descargado(pid, fmt)
                state.mark_completed(titulo, fmt)
                return 
    
    if "2160p" in mapa:
        if intentar_descarga(mapa["2160p"], titulo):
            db.marcar_cascada_descargado(pid, "2160p")
            state.mark_completed(titulo, "2160p")

    print(f"[Worker {pid}] 🏁 Finalizado flujo para: {titulo}")

# --- MAIN LOOP ---

def flujo_descargas(context):
    
    print("\n[*] --- FASE 1: SCRAPING Y REPARACIÓN ---")
    try:
        # Ya no hay guardado de sesión, solo ejecución directa
        scraper.ejecutar(context) 
    except Exception as e:
        print(f"[!] Error Scraper: {e}")

    # Actualizar Dashboard
    ultimas = db.obtener_ultimas_novedades(12)
    det = []
    if ultimas:
        for r in ultimas:
            t = sanitizar_nombre(r[0])
            det.append({"titulo": t, "anio": "", "formato": r[1]})
    state.set_detected_movies(det)

    print("[*] --- FASE 2: GESTOR DE DESCARGAS ---")
    conn = db.get_connection()
    cur = conn.cursor()
    pendientes = db.obtener_pendientes(cur)
    cur.close()
    conn.close()

    if not pendientes:
        print("[*] No hay descargas listas (con enlaces).")
        return

    data_map = {}
    for r in pendientes:
        did, pid, tit, fmt, lnk, torig = r
        if pid not in data_map: 
            data_map[pid] = {"titulo": tit, "variantes": []}
        data_map[pid]["variantes"].append({
            "id": did, "formato": fmt, "enlaces": lnk, "titulo_orig": torig
        })
    
    cola_de_trabajo = list(data_map.items())
    hilos_activos = []

    print(f"[*] Procesando {len(cola_de_trabajo)} películas...")

    while cola_de_trabajo or hilos_activos:
        hilos_activos = [t for t in hilos_activos if t.is_alive()]
        
        while len(hilos_activos) < config.MAX_WORKERS and cola_de_trabajo:
            pid, datos = cola_de_trabajo.pop(0)
            print(f"[Gestor] Iniciando: {datos['titulo']}")
            t = threading.Thread(target=worker_wrapper, args=(pid, datos)) 
            t.daemon = True
            t.start()
            hilos_activos.append(t)
            
        time.sleep(2)

def main():
    db.init_db()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        # Contexto siempre limpio
        context = obtener_contexto_navegador(browser)
        flujo_descargas(context)
        # Eliminado guardar_sesion(context) al final
        browser.close()

if __name__ == "__main__":
    print("[SYSTEM] Servidor web en puerto 8000...")
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    
    while True:
        try: main()
        except Exception as e:
            print(f"[CRASH] Error principal: {e}")
            time.sleep(30)
        print(f"[*] Durmiendo {config.CHECK_INTERVAL} segundos...")
        time.sleep(config.CHECK_INTERVAL)
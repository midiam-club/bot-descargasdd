import os
import time
import re
import config
import database as db
import debrid
import post_procesado as post
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
import threading # Necesario para los hilos
from web_server import run_web_server # Importamos la función que arranca FastAPI

# --- GESTIÓN DE SESIÓN (PERSISTENCIA) ---

def obtener_contexto_navegador(browser):
    """
    Carga la sesión persistente desde /config/config.json si existe.
    Si no, crea un contexto virgen.
    """
    if os.path.exists(config.SESSION_FILE):
        print(f"   [SESIÓN] Cargando cookies desde: {config.SESSION_FILE}")
        try:
            context = browser.new_context(storage_state=config.SESSION_FILE)
            return context
        except Exception as e:
            print(f"   [!] Error cargando sesión (fichero corrupto): {e}")
            return browser.new_context()
    else:
        print("   [SESIÓN] No existe fichero previo. Se creará uno nuevo.")
        return browser.new_context()

def guardar_sesion(context):
    """
    Guarda las cookies en la carpeta persistente para sobrevivir reinicios.
    """
    try:
        context.storage_state(path=config.SESSION_FILE)
        print(f"   [SESIÓN] Guardada correctamente en: {config.SESSION_FILE}")
    except Exception as e:
        print(f"   [!] Error guardando sesión: {e}")

# --- UTILIDADES DE ARCHIVOS ---

def extraer_numero_parte(filename):
    """
    Detecta si el archivo es una parte de un RAR (part1, .z01, .001, etc.)
    Devuelve el número de parte (int) o 1 si parece un archivo único.
    """
    fn = filename.lower()
    
    # Patrones comunes: .part01.rar, .part1.rar
    match = re.search(r'(?:part|pt)\.?\s*(\d+)', fn)
    if match: return int(match.group(1))
    
    # Patrón extensión numerada: archivo.z01, archivo.001
    match_ext = re.search(r'\.(?:z|r|)(\d{2,3})$', fn)
    if match_ext: 
        # Excluir extensiones de video que terminan en número si las hubiera
        if fn.endswith((".mkv", ".mp4", ".avi", ".iso")): return 1
        return int(match_ext.group(1))
        
    return 1 # Si no detecta parte, asumimos que es archivo único

# --- LÓGICA DE DESCARGA (Smart Parts & Priority) ---

def intentar_descarga(variante, titulo):
    fmt = variante["formato"]
    raw_links = [l.strip() for l in variante["enlaces"].split('\n') if l.strip()]
    titulo_orig = variante["titulo_orig"]
    
    if not raw_links: return False
    
    print(f"   [ANÁLISIS] Resolviendo metadatos de {len(raw_links)} enlaces para {fmt}...")
    
    # 1. OBTENER METADATOS Y AGRUPAR POR PARTES
    # Estructura: { numero_parte: [ {url, nombre, prioridad}, ... ] }
    mapa_partes = {}
    
    for link in raw_links:
        # Obtenemos URL premium y NOMBRE REAL (debrid.py devuelve tupla)
        url_prem, nombre_fichero = debrid.obtener_enlace_premium(link)
        
        if not url_prem or not nombre_fichero:
            continue
            
        # Detectamos qué parte es (1, 2, 3...)
        num_parte = extraer_numero_parte(nombre_fichero)
        
        # Calculamos prioridad del servidor según config.py (0 es mejor)
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
            "orig_link": link
        })

    if not mapa_partes:
        print("   [!] No se pudieron resolver enlaces válidos.")
        return False

    # 2. GESTOR DE DESCARGAS (Mix & Match)
    carpeta = os.path.join(config.DOWNLOAD_DIR, f"{titulo} [{fmt}]")
    if not os.path.exists(carpeta): os.makedirs(carpeta)
    
    total_partes = len(mapa_partes)
    partes_descargadas = 0
    
    print(f"   [INFO] Detectadas {total_partes} partes únicas necesarias.")

    # Iteramos las partes en orden (1, 2, 3...)
    for num_parte in sorted(mapa_partes.keys()):
        candidatos = mapa_partes[num_parte]
        
        # Ordenamos candidatos por prioridad de servidor (Menor es mejor)
        candidatos.sort(key=lambda x: x["prio"])
        
        exito_parte = False
        for cand in candidatos:
            print(f"   [⬇️] Bajando Parte {num_parte}: {cand['name']} (Prio: {cand['prio']})")
            
            # Descargar archivo (control de velocidad interno en debrid.py/utils.py)
            ruta_final = debrid.descargar_archivo(cand["url"], carpeta, titulo)
            
            if ruta_final:
                print(f"      ✅ Parte {num_parte} completada.")
                partes_descargadas += 1
                exito_parte = True
                break # Pasamos a la siguiente parte
            else:
                print(f"      ❌ Falló descarga. Probando siguiente espejo...")
        
        if not exito_parte:
            print(f"   [ERROR CRÍTICO] No se pudo descargar la Parte {num_parte}. Abortando versión.")
            return False

    # 3. FINALIZAR Y POST-PROCESAR
    if partes_descargadas == total_partes:
        print("   [ÉXITO] Todas las partes bajadas. Iniciando post-procesado...")
        return post.procesar_carpeta_final(carpeta, titulo, fmt, titulo_orig)
    
    return False

# --- WORKER (LÓGICA HD vs 4K) ---

def worker_descarga_pelicula(pid, datos_peli):
    titulo = datos_peli["titulo"]
    variantes = datos_peli["variantes"]
    mapa = {v["formato"]: v for v in variantes}
    
    print(f"[Worker {pid}] 🚀 Iniciando análisis para: {titulo}")
    
    # ---------------------------------------------------------
    # CARRIL 1: ALTA DEFINICIÓN (HD) - Exclusivo (Solo una)
    # Prioridad: x265 > 1080p > m1080p
    # ---------------------------------------------------------
    orden_hd = ["x265", "1080p", "m1080p"]
    hd_descargada = False
    
    for fmt in orden_hd:
        if fmt in mapa:
            print(f"[Worker {pid}]    -> [HD] Probando calidad {fmt}...")
            
            if intentar_descarga(mapa[fmt], titulo):
                print(f"[Worker {pid}]    -> ¡Éxito en {fmt}!")
                
                # Cascada: Si baja x265, marca x265, 1080p y m1080p como OK
                db.marcar_cascada_descargado(pid, fmt)
                
                hd_descargada = True
                break # STOP: Ya tenemos una versión HD, no bajamos las peores
    
    if not hd_descargada:
        print(f"[Worker {pid}]    -> [HD] No se encontró/pudo descargar ninguna versión HD.")

    # ---------------------------------------------------------
    # CARRIL 2: ULTRA ALTA DEFINICIÓN (4K) - Independiente
    # Se descarga SIEMPRE si está disponible, tenga HD o no.
    # ---------------------------------------------------------
    if "2160p" in mapa:
        print(f"[Worker {pid}]    -> [4K] Buscando versión 2160p...")
        if intentar_descarga(mapa["2160p"], titulo):
            print(f"[Worker {pid}]    -> ¡Éxito en 2160p!")
            db.marcar_cascada_descargado(pid, "2160p")
    
    print(f"[Worker {pid}] 🏁 Tarea finalizada para: {titulo}")
    return (pid, None, None)

# --- FLUJO PRINCIPAL ---

def flujo_descargas():
    print(f"\n[*] --- INICIANDO DESCARGAS PARALELAS ({config.MAX_WORKERS} Workers) ---")
    conn = db.get_connection()
    cur = conn.cursor()
    pendientes = db.obtener_pendientes(cur)
    cur.close()
    conn.close()
    
    if not pendientes:
        print("[*] No hay descargas pendientes.")
        return

    # Agrupar variantes por película
    data_map = {}
    for r in pendientes:
        did, pid, tit, fmt, lnk, torig = r
        if pid not in data_map: 
            data_map[pid] = {"titulo": tit, "variantes": []}
        data_map[pid]["variantes"].append({
            "id": did, 
            "formato": fmt, 
            "enlaces": lnk, 
            "titulo_orig": torig
        })
    
    # Ejecución paralela
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as exe:
        futures = {exe.submit(worker_descarga_pelicula, pid, d): pid for pid, d in data_map.items()}
        
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e: 
                print(f"❌ Error crítico en un worker: {e}")

# --- PUNTO DE ENTRADA ---

def main():
    db.init_db()
    
    with sync_playwright() as p:
        # Lanzamos navegador (Headless = True para prod)
        browser = p.chromium.launch(headless=True)
        
        # Usamos la función de sesión persistente
        context = obtener_contexto_navegador(browser)
        page = context.new_page()

        print("[*] Bot iniciado. Comprobando acceso al foro...")
        
        # --- AQUÍ IRÍA TU LÓGICA DE SCRAPING ---
        # Como no has compartido el código de scraping específico (selectores, login),
        # mantengo la estructura genérica. 
        # Asegúrate de llamar a 'guardar_sesion(context)' después del Login.
        
        try:
            # Ejemplo simplificado de flujo:
            # 1. page.goto(URL_FORO)
            # 2. Si no login -> Loguear -> guardar_sesion(context)
            # 3. Escanear temas -> db.insertar_pelicula(...)
            pass 
        except Exception as e:
            print(f"[!] Error en scraping: {e}")

        # Ejecutamos las descargas tras el escaneo
        flujo_descargas()
        
        browser.close()

if __name__ == "__main__":
    
    # 1. ARRANCAR EL SERVIDOR WEB EN SEGUNDO PLANO
    print("[SYSTEM] Arrancando servidor web en puerto 8000...")
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    
    # 2. BUCLE DEL BOT (Igual que antes)
    while True:
        try:
            main()
        except Exception as e:
            print(f"[CRASH] El bot falló: {e}")
        
        print(f"[*] Durmiendo {config.CHECK_INTERVAL} segundos...")
        time.sleep(config.CHECK_INTERVAL)
import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

# Importamos nuestros módulos
import config
import database as db
import scraper
import utils
import debrid
import post_procesado as post
from config import PRIORIDAD_DOMINIOS

# --- WORKER DE DESCARGA ---
def worker_descarga_pelicula(pid, datos_peli):
    titulo = datos_peli["titulo"]
    variantes = datos_peli["variantes"]
    mapa = {v["formato"]: v for v in variantes}
    
    print(f"[Worker {pid}] 🚀 Iniciando análisis para: {titulo}")
    
    # A. Ruta 4K (Independiente)
    if "2160p" in mapa:
        v = mapa["2160p"]
        if intentar_descarga(v, titulo):
            print(f"[Worker {pid}]    -> ¡4K Descargada!")
            # Si descargamos 4K, marcamos 4K y seguimos (puede querer también 1080p)
            # Pero como la función main espera un retorno único para marcar, 
            # hacemos la actualización aquí directo para el 4K.
            db.marcar_cascada_descargado(pid, "2160p")
            
    # B. Ruta HD (x265 > 1080p > m1080p)
    orden = []
    if "x265" in mapa: orden.append(mapa["x265"])
    if "1080p" in mapa: orden.append(mapa["1080p"])
    if "m1080p" in mapa: orden.append(mapa["m1080p"])
    
    for cand in orden:
        print(f"[Worker {pid}]    -> Probando calidad {cand['formato']}...")
        if intentar_descarga(cand, titulo):
            print(f"[Worker {pid}]    -> ¡Éxito en {cand['formato']}!")
            # Devolvemos el formato exitoso para hacer la cascada
            return (pid, cand["id"], cand["formato"])
            
    print(f"[Worker {pid}] 💀 Fin del hilo.")
    return (pid, None, None)

def extraer_numero_parte(filename):
    """
    Detecta si el archivo es una parte de un RAR (part1, .z01, .001, etc.)
    Devuelve el número de parte (int) o 1 si parece un archivo único.
    """
    fn = filename.lower()
    
    # Patrones comunes: .part01.rar, .part1.rar, .z01, .001
    match = re.search(r'(?:part|pt)\.?\s*(\d+)', fn)
    if match: return int(match.group(1))
    
    # Patrón extensión numerada: archivo.z01, archivo.001
    match_ext = re.search(r'\.(?:z|r|)(\d{2,3})$', fn)
    if match_ext: 
        # Cuidado con .mkv o .mp4, no son partes
        if fn.endswith((".mkv", ".mp4", ".avi", ".iso")): return 1
        return int(match_ext.group(1))
        
    return 1 # Si no detecta parte, asumimos que es archivo único

def intentar_descarga(variante, titulo):
    fmt = variante["formato"]
    raw_links = [l.strip() for l in variante["enlaces"].split('\n') if l.strip()]
    titulo_orig = variante["titulo_orig"]
    
    if not raw_links: return False
    
    print(f"   [ANÁLISIS] Resolviendo metadatos de {len(raw_links)} enlaces...")
    
    # 1. OBTENER METADATOS DE TODOS LOS LINKS (Sin descargar aún)
    # Estructura: diccionario { numero_parte: [ {url, nombre, prioridad}, ... ] }
    mapa_partes = {}
    
    for link in raw_links:
        # Obtenemos URL premium y NOMBRE REAL
        url_prem, nombre_fichero = debrid.obtener_enlace_premium(link)
        
        if not url_prem or not nombre_fichero:
            continue
            
        # Detectamos qué parte es (1, 2, 3...)
        num_parte = extraer_numero_parte(nombre_fichero)
        
        # Calculamos prioridad del servidor (0 es mejor)
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

    # 2. GESTOR DE DESCARGAS INTELIGENTE
    carpeta = os.path.join(config.DOWNLOAD_DIR, f"{titulo} [{fmt}]")
    if not os.path.exists(carpeta): os.makedirs(carpeta)
    
    total_partes = len(mapa_partes)
    partes_descargadas = 0
    
    print(f"   [INFO] Detectadas {total_partes} partes únicas necesarias.")

    # Ordenamos las partes (1, 2, 3...) para bajar en orden
    for num_parte in sorted(mapa_partes.keys()):
        candidatos = mapa_partes[num_parte]
        
        # Ordenamos candidatos: Menor número de prioridad es mejor
        candidatos.sort(key=lambda x: x["prio"])
        
        exito_parte = False
        for cand in candidatos:
            print(f"   [⬇️] Bajando Parte {num_parte}: {cand['name']} (Prio: {cand['prio']})")
            
            # Llamamos a descargar (OJO: descargar_archivo en debrid.py debe aceptar la URL directa)
            ruta_final = debrid.descargar_archivo(cand["url"], carpeta, titulo)
            
            if ruta_final:
                print(f"      ✅ Parte {num_parte} completada.")
                partes_descargadas += 1
                exito_parte = True
                break # Pasamos a la siguiente parte (número)
            else:
                print(f"      ❌ Falló descarga. Probando siguiente espejo...")
        
        if not exito_parte:
            print(f"   [ERROR CRÍTICO] No se pudo descargar la Parte {num_parte}. La película estará incompleta.")
            # Si falta una parte, abortamos para no dejar basura a medias? 
            # O seguimos? Generalmente mejor abortar si es un RAR.
            return False

    # 3. FINALIZAR
    if partes_descargadas == total_partes:
        print("   [ÉXITO] Todas las partes descargadas. Iniciando post-procesado.")
        return post.procesar_carpeta_final(carpeta, titulo, fmt, titulo_orig)
    
    return False

# --- FLUJOS PRINCIPALES ---

def flujo_scraping():
    # Ahora toda la lógica compleja está en scraper.py para poder depurarla mejor
    conn = db.get_connection()
    scraper.ejecutar_scraping_completo(conn)
    conn.close()

def flujo_descargas():
    print(f"\n[*] --- INICIANDO DESCARGAS PARALELAS ({config.MAX_WORKERS} Workers) ---")
    conn = db.get_connection()
    cur = conn.cursor()
    pendientes = db.obtener_pendientes(cur)
    cur.close()
    conn.close() # Cerramos aquí, el worker abre la suya
    
    # Agrupar
    data_map = {}
    for r in pendientes:
        did, pid, tit, fmt, lnk, torig = r
        if pid not in data_map: data_map[pid] = {"titulo": tit, "variantes": []}
        data_map[pid]["variantes"].append({"id": did, "formato": fmt, "enlaces": lnk, "titulo_orig": torig})
    
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as exe:
        futures = {exe.submit(worker_descarga_pelicula, pid, d): pid for pid, d in data_map.items()}
        
        for fut in as_completed(futures):
            try:
                # Recibimos el triplete
                pid, did_exito, fmt_exito = fut.result()
                
                if did_exito and fmt_exito:
                    # AQUÍ ESTÁ EL CAMBIO: Llamamos a la cascada
                    db.marcar_cascada_descargado(pid, fmt_exito)
                    
            except Exception as e: 
                print(f"Error worker: {e}")
            
    conn.close()

if __name__ == "__main__":
    # CICLO INFINITO (Modo Servicio)
    while True:
        print("\n" + "="*50)
        print(f"⏰ INICIANDO CICLO: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*50)

        # 1. FASE SCRAPING (Login + Buscar pelis)
        try:
            print("\n🔍 --- FASE 1: SCRAPING Y BÚSQUEDA ---")
            flujo_scraping()
        except Exception as e:
            print(f"❌ Error crítico en Scraping: {e}")

        # 2. FASE DESCARGA (Bajar lo encontrado)
        try:
            print("\n⬇️ --- FASE 2: GESTOR DE DESCARGAS ---")
            flujo_descargas()
        except Exception as e:
            print(f"❌ Error crítico en Descargas: {e}")

        # 3. ESPERA (Dormir X tiempo antes de volver a buscar)
        # Por ejemplo: 4 horas (4 * 60 * 60 = 14400 segundos)
        TIEMPO_ESPERA = 14400 
        print(f"\n💤 Ciclo terminado. Durmiendo {TIEMPO_ESPERA/3600} horas...")
        time.sleep(TIEMPO_ESPERA)
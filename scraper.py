import time
import re
import random
import config
import database as db
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# --- CONSTANTES ---
URL_BASE = "https://descargasdd.org"

SELECTOR_LOGOUT = "text=Finalizar sesión"
SELECTOR_USER = "input[name='vb_login_username']"
SELECTOR_PASS = "input[name='vb_login_password']"
SELECTOR_LOGIN_BTN = "input[value='Iniciar sesión']"
SELECTOR_USER_ALT = "input[name='username']"
SELECTOR_PASS_ALT = "input[name='password']"

# --- UTILIDADES ---

def espera_humana():
    time.sleep(random.uniform(1.0, 2.5))

def limpiar_texto(txt):
    if not txt: return ""
    return txt.strip()

def analizar_titulo(titulo_hilo):
    titulo_hilo = titulo_hilo.replace(":", " ") 
    match_anio = re.search(r'\((\d{4})\)', titulo_hilo)
    anio = match_anio.group(1) if match_anio else ""
    
    formato = "1080p" 
    upper_tit = titulo_hilo.upper()
    if "2160P" in upper_tit or "4K" in upper_tit or "UHD" in upper_tit: formato = "2160p"
    elif "X265" in upper_tit or "HEVC" in upper_tit: formato = "x265"
    elif "M1080P" in upper_tit or "MICRO" in upper_tit: formato = "m1080p"
    
    if anio:
        parts = titulo_hilo.split(f"({anio})")
        titulo_base = parts[0].strip()
    else:
        titulo_base = titulo_hilo.split('[')[0].strip()

    return titulo_base, anio, formato

def extraer_enlaces_post(contenido_html):
    enlaces_encontrados = []
    urls = re.findall(r'https?://[^\s<>"\'\]]+', contenido_html)
    for url in urls:
        for dominio in config.HOSTER_PREFS.keys():
            if dominio in url.lower():
                enlaces_encontrados.append(url)
                break
    return list(set(enlaces_encontrados)) 

# --- NAVEGACIÓN Y SESIÓN ---

def validar_sesion(page):
    print("   [SCRAPER] Verificando estado de la sesión...")
    try:
        page.goto(URL_BASE, timeout=60000, wait_until="domcontentloaded")
        if page.locator(SELECTOR_LOGOUT).is_visible(timeout=5000):
            print("   [SCRAPER] ✅ Sesión VÁLIDA.")
            return True
        print("   [SCRAPER] ⚠️ Sesión NO VÁLIDA.")
        return False
    except: return False

def realizar_login(page):
    print("   [SCRAPER] Iniciando login...")
    url_login = f"{URL_BASE}/login.php?do=login"
    try:
        page.goto(url_login, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(SELECTOR_USER, state="visible", timeout=10000)
            page.fill(SELECTOR_USER, config.FORO_USER)
            page.fill(SELECTOR_PASS, config.FORO_PASS)
        except:
            page.fill(SELECTOR_USER_ALT, config.FORO_USER)
            page.fill(SELECTOR_PASS_ALT, config.FORO_PASS)
        espera_humana()
        try: page.click(SELECTOR_LOGIN_BTN, timeout=5000)
        except: page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded")
        
        if page.locator(SELECTOR_LOGOUT).is_visible(timeout=10000):
            print("   [SCRAPER] ✅ Login EXITOSO.")
            return True
        else:
            print("   [SCRAPER] ❌ Login FALLIDO.")
            page.screenshot(path=f"{config.DOWNLOAD_DIR}/debug_login_error.png")
            return False
    except Exception as e:
        print(f"   [!] Excepción login: {e}")
        return False

# --- LOGICA DE PROCESADO ---

def procesar_hilo(page, url_hilo, titulo_raw, foro_id):
    try:
        titulo_base, anio, formato = analizar_titulo(titulo_raw)
        
        for palabra in config.PALABRAS_EXCLUIDAS:
            if palabra in titulo_raw.upper(): return

        conn = db.get_connection()
        cur = conn.cursor()
        
        meta = db.buscar_pelicula_meta(cur, titulo_base)
        if meta: peli_id = meta[0]
        else: peli_id = db.insertar_pelicula_meta(conn, cur, titulo_base)
        
        match_id = re.search(r't=(\d+)', url_hilo)
        hilo_id = match_id.group(1) if match_id else "0"
        
        descarga_existente = db.buscar_descarga(cur, hilo_id)
        
        # Si ya existe Y tiene enlaces, no hacemos nada (asumimos OK)
        if descarga_existente and descarga_existente[0] and len(descarga_existente[0]) > 10:
            cur.close()
            conn.close()
            return

        print(f"      [ENTRANDO] Extrayendo enlaces: {titulo_raw[:40]}...")
        page.goto(url_hilo, wait_until="domcontentloaded")
        
        content_html = page.inner_html("div.postcontent", timeout=5000)
        enlaces = extraer_enlaces_post(content_html)
        
        if enlaces:
            str_enlaces = "\n".join(enlaces)
            if descarga_existente:
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                print(f"      [UPDATE] Enlaces actualizados: {len(enlaces)} encontrados.")
            else:
                db.insertar_descarga_hueco(conn, cur, peli_id, foro_id, hilo_id, formato, titulo_raw)
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                print(f"      [NUEVO] Guardado: {titulo_base} [{formato}] ({len(enlaces)} links)")
        
        cur.close()
        conn.close()
        espera_humana()

    except Exception as e:
        print(f"      [!] Error en hilo {url_hilo}: {e}")

def procesar_foro(page, foro_id):
    url_foro = f"{URL_BASE}/forumdisplay.php?f={foro_id}&order=desc"
    print(f"   [SCRAPER] Escaneando Índice del Foro ID {foro_id}...")
    try:
        page.goto(url_foro, wait_until="domcontentloaded")
        hilos = page.locator("li.threadbit").all()
        print(f"   [DEBUG] Se han detectado {len(hilos)} hilos en la primera página.")

        count = 0
        max_hilos = 15 
        for hilo in hilos:
            if count >= max_hilos: break
            try:
                if not hilo.is_visible(): continue
                elemento_titulo = hilo.locator("a.title")
                if elemento_titulo.count() == 0: continue

                texto_titulo = elemento_titulo.inner_text().strip()
                href_parcial = elemento_titulo.get_attribute("href")
                
                if "adhierido" in texto_titulo.lower() or "importante" in texto_titulo.lower():
                    continue

                url_completa = f"{URL_BASE}/{href_parcial}"
                procesar_hilo(page, url_completa, texto_titulo, foro_id)
                count += 1
            except Exception: continue
    except Exception as e:
        print(f"   [!] Error leyendo foro {foro_id}: {e}")

# --- REPARACIÓN DE ENLACES ---

def reparar_hilos_rotos(page):
    """
    Busca en DB películas sin enlaces y visita sus hilos específicamente.
    """
    rotas = db.obtener_descargas_sin_enlaces()
    if not rotas:
        return

    print(f"\n   [REPARACIÓN] Detectadas {len(rotas)} descargas sin enlaces. Intentando reparar...")
    
    for item in rotas:
        hilo_id = item[0]
        titulo = item[1]
        
        # Construimos URL directa al hilo
        url_hilo = f"{URL_BASE}/showthread.php?t={hilo_id}"
        
        print(f"      [REPARAR] Visitando hilo {hilo_id}: {titulo[:30]}...")
        try:
            page.goto(url_hilo, wait_until="domcontentloaded", timeout=60000)
            
            # Usamos la misma lógica de extracción
            content_html = page.inner_html("div.postcontent", timeout=5000)
            enlaces = extraer_enlaces_post(content_html)
            
            if enlaces:
                str_enlaces = "\n".join(enlaces)
                conn = db.get_connection()
                cur = conn.cursor()
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                cur.close()
                conn.close()
                print(f"      [OK] ¡Reparado! {len(enlaces)} enlaces encontrados.")
            else:
                print("      [FAIL] No se encontraron enlaces (posiblemente caído o formato desconocido).")
            
            espera_humana()
            
        except Exception as e:
            print(f"      [!] Error intentando reparar hilo {hilo_id}: {e}")


# --- PUNTO DE ENTRADA ---

def ejecutar(context):
    page = context.new_page()
    try:
        if not validar_sesion(page):
            if not realizar_login(page):
                print("   [SCRAPER] ABORTANDO: Fallo login.")
                page.close()
                return 

        # 1. FASE DE REPARACIÓN (Primero arreglamos lo roto)
        reparar_hilos_rotos(page)

        # 2. FASE DE ESCANEO NORMAL
        if hasattr(config, 'FOROS_PROCESAR'):
            for fid in config.FOROS_PROCESAR:
                procesar_foro(page, fid)
                espera_humana()
        
    except Exception as e:
        print(f"   [!] Error CRÍTICO en scraper: {e}")
    finally:
        try: page.close()
        except: pass
import time
import re
import random
import config
import database as db
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

URL_BASE = "https://descargasdd.org"

# SELECTORES (Incluye fallback por si vBulletin cambia el ID)
SELECTOR_LOGOUT = "text=Finalizar sesión"
SELECTOR_USER = "input[name='vb_login_username']"
SELECTOR_PASS = "input[name='vb_login_password']"
SELECTOR_LOGIN_BTN = "input[value='Iniciar sesión']"
# Fallback genérico estándar HTML
SELECTOR_USER_ALT = "input[name='username']"
SELECTOR_PASS_ALT = "input[name='password']"

def espera_humana():
    time.sleep(random.uniform(1.5, 3.0))

def analizar_titulo(titulo_hilo):
    titulo_hilo = titulo_hilo.replace(":", " ") 
    match_anio = re.search(r'\((\d{4})\)', titulo_hilo)
    anio = match_anio.group(1) if match_anio else ""
    
    formato = "1080p" 
    upper = titulo_hilo.upper()
    if "2160P" in upper or "4K" in upper or "UHD" in upper: formato = "2160p"
    elif "X265" in upper or "HEVC" in upper: formato = "x265"
    elif "M1080P" in upper or "MICRO" in upper: formato = "m1080p"
    
    if anio: parts = titulo_hilo.split(f"({anio})") ; titulo_base = parts[0].strip()
    else: titulo_base = titulo_hilo.split('[')[0].strip()
    return titulo_base, anio, formato

def extraer_enlaces_post(contenido_html):
    enlaces = []
    urls = re.findall(r'(https?://[^\s<>"\'\]]+)', contenido_html)
    for url in urls:
        for dominio in config.HOSTER_PREFS.keys():
            if dominio in url.lower():
                enlaces.append(url)
                break
    return list(set(enlaces))

# --- LOGIN OBLIGATORIO ---

def realizar_login(page):
    print("   [SCRAPER] Iniciando login (Sesión limpia)...")
    url_login = f"{URL_BASE}/login.php?do=login"
    try:
        page.goto(url_login, wait_until="domcontentloaded", timeout=60000)
        
        # Estrategia de rellenado robusta
        try:
            # Intento 1: Selector específico de vBulletin
            page.wait_for_selector(SELECTOR_USER, state="visible", timeout=5000)
            page.fill(SELECTOR_USER, config.FORO_USER)
            page.fill(SELECTOR_PASS, config.FORO_PASS)
        except:
            print("   [SCRAPER] Falló selector vBulletin, probando genérico...")
            # Intento 2: Selector genérico 'username' (el que dio timeout en tu log anterior)
            # Si este también falla, saltará la excepción general y hará screenshot.
            page.fill(SELECTOR_USER_ALT, config.FORO_USER)
            page.fill(SELECTOR_PASS_ALT, config.FORO_PASS)
            
        espera_humana()
        
        # Enviar formulario
        try: page.click(SELECTOR_LOGIN_BTN, timeout=5000)
        except: page.keyboard.press("Enter")
        
        page.wait_for_load_state("domcontentloaded")
        
        # Verificación final
        if page.locator(SELECTOR_LOGOUT).is_visible(timeout=10000):
            print("   [SCRAPER] ✅ Login EXITOSO.")
            return True
        
        print("   [SCRAPER] ❌ Login FALLIDO. Generando captura de debug...")
        page.screenshot(path=f"{config.DOWNLOAD_DIR}/debug_login_fail.png")
        return False

    except Exception as e:
        print(f"   [!] Excepción crítica en login: {e}")
        try: page.screenshot(path=f"{config.DOWNLOAD_DIR}/debug_login_crash.png")
        except: pass
        return False

# --- REPARACIÓN ---

def reparar_hilos_rotos(page):
    rotas = db.obtener_descargas_sin_enlaces()
    if not rotas: return

    print(f"\n   [REPARACIÓN] Detectadas {len(rotas)} descargas rotas. Reparando...")
    
    for item in rotas:
        hilo_id = item[0]
        titulo = item[1] or "Sin titulo"
        
        if not hilo_id or hilo_id == '0': continue

        url_hilo = f"{URL_BASE}/showthread.php?t={hilo_id}"
        print(f"      [REPARAR] {hilo_id}: {titulo[:20]}...")
        
        try:
            page.goto(url_hilo, wait_until="domcontentloaded", timeout=60000)
            try: content_html = page.inner_html("div.postcontent", timeout=5000)
            except: content_html = page.content()

            enlaces = extraer_enlaces_post(content_html)
            
            if enlaces:
                str_enlaces = "\n".join(enlaces)
                conn = db.get_connection()
                cur = conn.cursor()
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                cur.close()
                conn.close()
                print(f"      [OK] Recuperados {len(enlaces)} enlaces.")
            else:
                print("      [FAIL] Sin enlaces. Debug guardado.")
                page.screenshot(path=f"{config.DOWNLOAD_DIR}/debug_repair_fail_{hilo_id}.png")
            
            espera_humana()
        except Exception as e:
            print(f"      [ERROR] Reparación fallida: {e}")

# --- PROCESADO ---

def procesar_hilo(page, url_hilo, titulo_raw, foro_id):
    try:
        titulo_base, anio, formato = analizar_titulo(titulo_raw)
        
        for palabra in config.PALABRAS_EXCLUIDAS:
            if palabra in titulo_raw.upper(): return

        conn = db.get_connection()
        cur = conn.cursor()
        
        match_id = re.search(r't=(\d+)', url_hilo)
        hilo_id = match_id.group(1) if match_id else "0"
        
        descarga_existente = db.buscar_descarga(cur, hilo_id)
        if descarga_existente and descarga_existente[0] and len(descarga_existente[0]) > 10:
            cur.close(); conn.close(); return

        meta = db.buscar_pelicula_meta(cur, titulo_base)
        if meta: peli_id = meta[0]
        else: peli_id = db.insertar_pelicula_meta(conn, cur, titulo_base)

        print(f"      [NUEVO] {titulo_base}")
        page.goto(url_hilo, wait_until="domcontentloaded")
        
        content_html = page.inner_html("div.postcontent", timeout=5000)
        enlaces = extraer_enlaces_post(content_html)
        
        if enlaces:
            str_enlaces = "\n".join(enlaces)
            if descarga_existente: db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
            else:
                db.insertar_descarga_hueco(conn, cur, peli_id, foro_id, hilo_id, formato, titulo_raw)
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
        else:
            if not descarga_existente:
                db.insertar_descarga_hueco(conn, cur, peli_id, foro_id, hilo_id, formato, titulo_raw)

        cur.close()
        conn.close()
        espera_humana()
    except: pass

def procesar_foro(page, foro_id):
    print(f"   [SCRAPER] Escaneando Foro {foro_id}...")
    try:
        page.goto(f"{URL_BASE}/forumdisplay.php?f={foro_id}&order=desc", wait_until="domcontentloaded")
        hilos = page.locator("li.threadbit").all()
        print(f"   [DEBUG] Encontrados {len(hilos)} temas.")
        
        count = 0
        for hilo in hilos:
            if count >= 10: break
            try:
                if not hilo.is_visible(): continue
                el = hilo.locator("a.title")
                if el.count() == 0: continue
                txt = el.inner_text().strip()
                if "adhierido" in txt.lower(): continue
                href = el.get_attribute("href")
                
                procesar_hilo(page, f"{URL_BASE}/{href}", txt, foro_id)
                count += 1
            except: continue
    except Exception as e:
        print(f"   [!] Error foro {foro_id}: {e}")

# --- EJECUCIÓN PRINCIPAL ---

def ejecutar(context):
    page = context.new_page()
    try:
        # SIEMPRE LOGIN
        if not realizar_login(page):
            print("   [SCRAPER] ABORTANDO: Fallo login.")
            page.close()
            return 

        reparar_hilos_rotos(page)

        if hasattr(config, 'FOROS_PROCESAR'):
            for fid in config.FOROS_PROCESAR:
                procesar_foro(page, fid)
                espera_humana()
                
    except Exception as e:
        print(f"   [!] Error Scraper: {e}")
    finally:
        try: page.close()
        except: pass
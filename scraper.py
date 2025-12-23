import time
import re
import random
import config
import database as db
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# --- CONSTANTES ---
URL_BASE = "https://descargasdd.org"
SELECTOR_LOGOUT = "text=Finalizar sesión"
SELECTOR_USER = "input[name='username']"
SELECTOR_PASS = "input[name='password']"
SELECTOR_LOGIN_BTN = "input[value='Iniciar sesión']"

# --- UTILIDADES ---

def espera_humana():
    time.sleep(random.uniform(1.0, 2.5))

def limpiar_texto(txt):
    if not txt: return ""
    return txt.strip()

# --- PARSEO DE TÍTULOS ---

def analizar_titulo(titulo_hilo):
    """
    Intenta extraer Título, Año y Formato del asunto del hilo.
    Ej: "Dune: Parte Dos (2024) [BluRay 1080p X265 10bit]..."
    """
    titulo_hilo = titulo_hilo.replace(":", " ") # Limpieza básica
    
    # 1. Extraer AÑO
    match_anio = re.search(r'\((\d{4})\)', titulo_hilo)
    anio = match_anio.group(1) if match_anio else ""
    
    # 2. Extraer FORMATO (Lógica simple basada en keywords)
    formato = "1080p" # Default
    upper_tit = titulo_hilo.upper()
    
    if "2160P" in upper_tit or "4K" in upper_tit or "UHD" in upper_tit:
        formato = "2160p"
    elif "X265" in upper_tit or "HEVC" in upper_tit:
        formato = "x265"
    elif "M1080P" in upper_tit or "MICRO" in upper_tit:
        formato = "m1080p"
    
    # 3. Limpiar TÍTULO (Quitar lo que hay después del año o corchetes)
    # Si encontramos el año, cortamos ahí
    if anio:
        parts = titulo_hilo.split(f"({anio})")
        titulo_base = parts[0].strip()
    else:
        # Si no hay año, intentamos cortar en el primer corchete
        titulo_base = titulo_hilo.split('[')[0].strip()

    return titulo_base, anio, formato

def extraer_enlaces_post(contenido_html):
    """
    Busca enlaces de los hosters soportados dentro del HTML del post.
    """
    enlaces_encontrados = []
    # Regex simple para buscar URLs http/https
    urls = re.findall(r'https?://[^\s<>"\'\]]+', contenido_html)
    
    for url in urls:
        # Filtramos solo dominios que nos interesan (definidos en config)
        for dominio in config.HOSTER_PREFS.keys():
            if dominio in url.lower():
                enlaces_encontrados.append(url)
                break
    
    return list(set(enlaces_encontrados)) # Eliminar duplicados

# --- NAVEGACIÓN Y SESIÓN ---

def validar_sesion(page):
    print("   [SCRAPER] Verificando estado de la sesión...")
    try:
        page.goto(URL_BASE, timeout=60000, wait_until="domcontentloaded")
        if page.locator(SELECTOR_LOGOUT).is_visible(timeout=5000):
            print("   [SCRAPER] ✅ Sesión VÁLIDA. Saltando login.")
            return True
        print("   [SCRAPER] ⚠️ Sesión CADUCADA o INEXISTENTE.")
        return False
    except: return False

def realizar_login(page):
    print("   [SCRAPER] Iniciando proceso de login...")
    try:
        if "login" not in page.url:
            page.goto(f"{URL_BASE}/login.php", wait_until="domcontentloaded")

        page.fill(SELECTOR_USER, config.FORO_USER)
        espera_humana()
        page.fill(SELECTOR_PASS, config.FORO_PASS)
        espera_humana()
        page.click(SELECTOR_LOGIN_BTN)
        page.wait_for_load_state("domcontentloaded")
        
        if page.locator(SELECTOR_LOGOUT).is_visible():
            print("   [SCRAPER] ✅ Login EXITOSO.")
            return True
        else:
            print("   [SCRAPER] ❌ Login FALLIDO.")
            return False
    except Exception as e:
        print(f"   [!] Excepción login: {e}")
        return False

# --- PROCESADO DE HILOS ---

def procesar_hilo(page, url_hilo, titulo_raw, foro_id):
    """Entra en un hilo, extrae enlaces y guarda en DB"""
    try:
        # 1. Analizar título
        titulo_base, anio, formato = analizar_titulo(titulo_raw)
        
        # Filtros de exclusión (Blacklist)
        for palabra in config.PALABRAS_EXCLUIDAS:
            if palabra in titulo_raw.upper():
                # print(f"      [SKIP] Excluido por palabra clave: {palabra}")
                return

        # 2. Gestión de IDs en DB
        conn = db.get_connection()
        cur = conn.cursor()
        
        # Verificar si la peli base ya existe en metadatos
        meta = db.buscar_pelicula_meta(cur, titulo_base)
        if meta:
            peli_id = meta[0]
        else:
            # Insertar nueva peli
            print(f"      [NUEVA PELI] {titulo_base} ({anio})")
            peli_id = db.insertar_pelicula_meta(conn, cur, titulo_base)
        
        # Extraer ID del hilo desde la URL (ej: showthread.php?t=12345)
        match_id = re.search(r't=(\d+)', url_hilo)
        hilo_id = match_id.group(1) if match_id else "0"
        
        # Verificar si ya tenemos esta descarga específica (por hilo_id)
        descarga_existente = db.buscar_descarga(cur, hilo_id)
        
        # Si ya existe y tiene enlaces, pasamos (asumimos procesada)
        if descarga_existente and descarga_existente[0] and len(descarga_existente[0]) > 10:
            cur.close()
            conn.close()
            return

        # 3. Entrar al hilo y extraer enlaces
        # print(f"      [SCRAP] Procesando hilo: {titulo_raw[:40]}...")
        page.goto(url_hilo, wait_until="domcontentloaded")
        
        # Selector del contenido del primer post
        content_html = page.inner_html("div.postcontent", timeout=5000)
        enlaces = extraer_enlaces_post(content_html)
        
        if enlaces:
            str_enlaces = "\n".join(enlaces)
            # Guardamos o actualizamos en DB
            if descarga_existente:
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                print(f"      [UPDATE] Enlaces actualizados para: {titulo_base} [{formato}]")
            else:
                db.insertar_descarga_hueco(conn, cur, peli_id, foro_id, hilo_id, formato, titulo_raw)
                db.actualizar_enlaces(conn, cur, hilo_id, str_enlaces)
                print(f"      [GUARDADO] {titulo_base} [{formato}] ({len(enlaces)} enlaces)")
        
        cur.close()
        conn.close()
        espera_humana()

    except Exception as e:
        print(f"      [!] Error procesando hilo {url_hilo}: {e}")

def procesar_foro(page, foro_id):
    """Recorre la lista de hilos de un subforo"""
    url_foro = f"{URL_BASE}/forumdisplay.php?f={foro_id}&order=desc"
    print(f"   [SCRAPER] Entrando al Foro ID {foro_id}...")
    
    try:
        page.goto(url_foro, wait_until="domcontentloaded")
        
        # Selectores para vBulletin 4 (común en DD)
        # Buscamos los elementos de la lista de temas
        # Ajusta el selector "li.threadbit" si el theme cambia
        hilos = page.locator("li.threadbit").all()
        
        # Limitamos a los primeros 10-15 hilos para no saturar en cada pasada
        count = 0
        max_hilos = 15 
        
        for hilo in hilos:
            if count >= max_hilos: break
            
            try:
                # Extraer título y URL sin navegar aún
                elemento_titulo = hilo.locator("a.title")
                if not elemento_titulo.is_visible(): continue
                
                texto_titulo = elemento_titulo.inner_text().strip()
                href_parcial = elemento_titulo.get_attribute("href")
                
                if "adhierido" in texto_titulo.lower() or "importante" in texto_titulo.lower():
                    continue

                url_completa = f"{URL_BASE}/{href_parcial}"
                
                # Procesamos el hilo individualmente
                procesar_hilo(page, url_completa, texto_titulo, foro_id)
                count += 1
                
            except Exception as e:
                continue

    except Exception as e:
        print(f"   [!] Error leyendo el índice del foro {foro_id}: {e}")

# --- PUNTO DE ENTRADA ---

def ejecutar(context):
    page = context.new_page()
    try:
        # 1. Login Inteligente
        if not validar_sesion(page):
            if not realizar_login(page):
                page.close()
                return 

        # 2. Iterar Foros
        if hasattr(config, 'FOROS_PROCESAR'):
            for fid in config.FOROS_PROCESAR:
                procesar_foro(page, fid)
                espera_humana()
        
    except Exception as e:
        print(f"   [!] Error CRÍTICO en scraper: {e}")
    finally:
        try: page.close()
        except: pass
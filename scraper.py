import time
import re
import requests
from playwright.sync_api import sync_playwright
# Importamos configuración y utilidades
from config import FORO_USER, FORO_PASS, FLARESOLVERR_URL, SESSION_FILE, FOROS_PROCESAR, IDS_IGNORADOS, PALABRAS_EXCLUIDAS
from utils import extraer_hilo_id, limpiar_titulo, detectar_formato
import database as db

def obtener_cookies_flaresolverr(url):
    print(f"[*] FlareSolverr solicitando acceso para: {url}")
    try:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        res = requests.post(FLARESOLVERR_URL, json=payload, timeout=70).json()
        if res.get("status") == "ok":
            return res["solution"]["cookies"], res["solution"]["userAgent"]
    except Exception as e: 
        print(f"   [DEBUG] Excepción FlareSolverr: {e}")
    return None, None

def login(page, context):
    print("[DEBUG] Verificando Login...")
    try:
        page.goto("https://descargasdd.org/index.php", wait_until="commit")
        time.sleep(2)
        
        try:
            if page.query_selector(f"text='{FORO_USER}'") or page.query_selector('a[href*="logout"]'): 
                print(f"   [DEBUG] ✅ Ya estamos logueados.")
                return True
        except: pass
        
        print("[!] Intentando login manual...")
        page.wait_for_selector('#navbar_username', state="visible", timeout=5000)
        page.fill('#navbar_username', FORO_USER)
        page.click('#navbar_password_hint')
        page.fill('#navbar_password', FORO_PASS)
        page.check('#cb_cookieuser_navbar')
        page.click('input.loginbutton')
        page.wait_for_timeout(5000)
        
        if page.query_selector(f"text='{FORO_USER}'") or page.query_selector('a[href*="logout"]'):
            print("   [DEBUG] ✅ Login EXITOSO.")
            context.storage_state(path=SESSION_FILE)
            return True
        else:
            print("   [DEBUG] ❌ Login FALLIDO.")
            return False
    except Exception as e: 
        print(f"   [DEBUG] Excepción Login: {e}")
        return False

def extraer_enlaces_agresivo(contenedor):
    links = set()
    try:
        html_content = contenedor.inner_html()
        patron = r'https?://[^\s"<>\)\]]+'
        encontrados = re.findall(patron, html_content)
        
        for l in encontrados:
            l = l.strip()
            if "descargasdd.org" in l: continue
            if "flaresolverr" in l: continue
            if l.endswith((".png", ".jpg", ".gif", ".jpeg", ".bmp")): continue
            links.add(l)
    except: pass
    return links

def procesar_detalle_hilo(page, url_hilo):
    print(f"      [HILO] Analizando: {url_hilo}")
    try:
        page.goto(url_hilo, wait_until="domcontentloaded")
        links_totales = set()
        
        elementos = page.query_selector_all('div[id^="post_message_"]')
        if not elementos: return None
        ids = [el.get_attribute("id").replace("post_message_", "") for el in elementos][:1]
        
        for post_id in ids:
            xpath = f"//div[@id='post_message_{post_id}']/ancestor::li[contains(@class,'postbit')] | //div[@id='post_message_{post_id}']/.."
            contenedor = page.locator(xpath).first
            
            btn = page.locator(f"#post_thanks_button_{post_id}")
            if btn.is_visible():
                try:
                    btn.click()
                    page.wait_for_timeout(2000)
                    texto = contenedor.inner_text().lower()
                    if "contenido oculto" in texto or "bloqueado" in texto:
                        page.reload()
                        page.wait_for_timeout(3000)
                        contenedor = page.locator(xpath).first
                except: pass
            
            links = extraer_enlaces_agresivo(contenedor)
            if links: links_totales.update(links)

        return "\n".join(links_totales) if links_totales else None
    except: return None

# --- FUNCIÓN PRINCIPAL RESTAURADA CON PAGINACIÓN ---
def ejecutar_scraping_completo(conn):
    cookies, ua = obtener_cookies_flaresolverr("https://descargasdd.org/index.php")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=ua if ua else "Mozilla/5.0")
        if cookies:
            context.add_cookies([{"name": c["name"], "value": c["value"], "domain": c["domain"].lstrip('.'), "path": c["path"], "secure": True} for c in cookies])
            
        page = context.new_page()
        if not login(page, context):
            print("[CRITICAL] Login fallido. Abortando.")
            return

        cur = conn.cursor()

        for foro_act in FOROS_PROCESAR:
            print(f"\n[*] --- ESCANEANDO FORO {foro_act} ---")
            pagina_actual = 1
            
            # BUCLE DE PAGINACIÓN (WHILE TRUE)
            while True:
                url_foro = f"https://descargasdd.org/forumdisplay.php?f={foro_act}&page={pagina_actual}"
                print(f"    > Procesando Página {pagina_actual}...")
                
                try:
                    page.goto(url_foro, wait_until="domcontentloaded")
                except: 
                    print("    [!] Error cargando página. Saltando foro.")
                    break

                # Detectar hilos
                hilos = page.query_selector_all('a[id^="thread_title_"]')
                if not hilos:
                    print("    [!] No se detectaron hilos (Fin o bloqueo).")
                    break
                
                lista_candidatos = []
                for el in hilos:
                    try:
                        t = el.inner_text().strip()
                        href = el.get_attribute("href")
                        hid = extraer_hilo_id(href)
                        
                        # Filtros (Palabras negras y 720p)
                        t_upper = t.upper()
                        if any(bad in t_upper for bad in PALABRAS_EXCLUIDAS): continue
                        
                        lista_candidatos.append({"t": t, "u": f"https://descargasdd.org/{href}", "id": hid})
                    except: pass

                # Procesar candidatos de esta página
                nuevos_en_esta_pagina = 0
                for item in lista_candidatos:
                    # 1. Comprobar si ya existe con enlaces válidos
                    res = db.buscar_descarga(cur, item["id"])
                    if res and res[0] and len(res[0]) > 5:
                        # Ya lo tenemos, saltamos
                        continue
                    
                    nuevos_en_esta_pagina += 1
                    
                    # 2. Insertar Metadatos
                    t_limpio = limpiar_titulo(item["t"])
                    pid_res = db.buscar_pelicula_meta(cur, t_limpio)
                    if pid_res: pid = pid_res[0]
                    else: pid = db.insertar_pelicula_meta(conn, cur, t_limpio)
                    
                    fmt = detectar_formato(item["t"], foro_act)
                    db.insertar_descarga_hueco(conn, cur, pid, foro_act, item["id"], fmt, item["t"])
                    
                    # 3. Entrar y sacar enlaces
                    enlaces = procesar_detalle_hilo(page, item["u"])
                    if enlaces:
                        db.actualizar_enlaces(conn, cur, item["id"], enlaces)
                        print(f"      [DB] Guardado: {t_limpio}")
                    
                    time.sleep(0.5) # Pequeña pausa entre hilos

                print(f"    > Página {pagina_actual} completada. Nuevos procesados: {nuevos_en_esta_pagina}")

                # COMPROBACIÓN "SIGUIENTE PÁGINA"
                # Buscamos el botón 'Siguiente' o 'Next' (suele tener rel="next")
                try:
                    siguiente = page.query_selector('a[rel="next"]')
                    if siguiente:
                        pagina_actual += 1
                        time.sleep(1) # Pausa entre páginas del foro
                    else:
                        print("    [FIN] No hay más páginas en este foro.")
                        break
                except:
                    break

        cur.close()
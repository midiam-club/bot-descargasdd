import time
import psycopg2
import config

# Diccionario de conexión
DB_CONFIG = {
    "dbname": config.DB_NAME,
    "user": config.DB_USER,
    "password": config.DB_PASSWORD,
    "host": config.DB_HOST,
    "port": config.DB_PORT
}

def get_connection():
    """
    Intenta conectar a la base de datos con reintentos infinitos.
    Esto evita que el contenedor muera si la DB tarda en arrancar.
    """
    while True:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            # Autocommit para evitar bloqueos
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            print(f"[DB] ⚠️ Esperando a la base de datos en '{config.DB_HOST}'... ({e})")
            time.sleep(5)
        except Exception as e:
            print(f"[DB] ❌ Error crítico de conexión: {e}")
            time.sleep(10)

def init_db():
    print("[DB] Verificando conexión inicial...")
    conn = get_connection()
    conn.close()
    print("[DB] Conexión establecida correctamente.")

# --- FUNCIONES DE GESTIÓN ---

def buscar_pelicula_meta(cur, titulo_limpio):
    cur.execute("SELECT id FROM peliculas_meta WHERE LOWER(titulo_base)=LOWER(%s)", (titulo_limpio,))
    return cur.fetchone()

def insertar_pelicula_meta(conn, cur, titulo_limpio):
    cur.execute("INSERT INTO peliculas_meta (titulo_base) VALUES (%s) RETURNING id", (titulo_limpio,))
    pid = cur.fetchone()[0]
    conn.commit()
    return pid

def buscar_descarga(cur, hilo_id):
    cur.execute("SELECT enlaces FROM descargas WHERE hilo_id = %s", (hilo_id,))
    return cur.fetchone()

def insertar_descarga_hueco(conn, cur, peli_id, foro_id, hilo_id, formato, titulo_raw):
    try:
        cur.execute("""
            INSERT INTO descargas (pelicula_id, foro_id, hilo_id, formato, titulo_original, descargado)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (hilo_id) DO NOTHING;
        """, (peli_id, int(foro_id), hilo_id, formato, titulo_raw, False)) 
        conn.commit()
    except: conn.rollback()

def actualizar_enlaces(conn, cur, hilo_id, enlaces):
    try:
        cur.execute("UPDATE descargas SET enlaces = %s WHERE hilo_id = %s", (enlaces, hilo_id))
        conn.commit()
    except: conn.rollback()

def marcar_como_descargado(did):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE descargas SET descargado = TRUE WHERE id = %s", (did,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB Error] Update fallido: {e}")
        return False

def obtener_pendientes(cur):
    query = """
        SELECT d.id, m.id as pid, m.titulo_base, d.formato, d.enlaces, d.titulo_original
        FROM descargas d
        JOIN peliculas_meta m ON d.pelicula_id = m.id
        WHERE d.descargado = FALSE 
          AND d.enlaces IS NOT NULL 
          AND length(d.enlaces) > 10
    """
    cur.execute(query)
    resultados = cur.fetchall()
    
    if not resultados:
        cur.execute("SELECT count(*) FROM descargas WHERE descargado = FALSE")
        total = cur.fetchone()[0]
        if total > 0:
            pass # Silenciamos logs para no saturar
            
    return resultados

def obtener_descargas_sin_enlaces():
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT hilo_id, titulo_original 
            FROM descargas 
            WHERE descargado = FALSE 
              AND (enlaces IS NULL OR length(enlaces) < 10)
        """
        cur.execute(query)
        return cur.fetchall()
    except Exception as e:
        print(f"[DB Error] Buscando rotas: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def marcar_cascada_descargado(pid, formato_descargado):
    try:
        conn = get_connection()
        cur = conn.cursor()
        target_formats = [formato_descargado]
        if formato_descargado == "x265": target_formats.extend(["1080p", "m1080p"])
        elif formato_descargado == "1080p": target_formats.extend(["m1080p"])
            
        cur.execute("""
            UPDATE descargas 
            SET descargado = TRUE 
            WHERE pelicula_id = %s AND formato = ANY(%s)
        """, (pid, target_formats))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except: return False

def obtener_ultimas_novedades(limit=12):
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT m.titulo_base, d.formato, d.titulo_original
            FROM descargas d
            JOIN peliculas_meta m ON d.pelicula_id = m.id
            ORDER BY d.id DESC
            LIMIT %s
        """
        cur.execute(query, (limit,))
        return cur.fetchall()
    except: return []
    finally:
        cur.close()
        conn.close()
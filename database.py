import psycopg2
from config import DB_CONFIG

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

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
    # Esta función abre su propia conexión porque se llama desde hilos (workers)
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
    cur.execute("""
        SELECT d.id, m.id as pid, m.titulo_base, d.formato, d.enlaces, d.titulo_original
        FROM descargas d
        JOIN peliculas_meta m ON d.pelicula_id = m.id
        WHERE d.descargado = FALSE AND d.enlaces IS NOT NULL AND length(d.enlaces) > 10
    """)
    return cur.fetchall()

def marcar_cascada_descargado(pid, formato_descargado):
    """
    Marca como descargado el formato actual Y las versiones inferiores
    para evitar duplicados, según la jerarquía de calidad.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        target_formats = [formato_descargado]
        
        # Jerarquía de anulación
        # Si bajo x265, ya no quiero ni 1080p normal ni micro
        if formato_descargado == "x265":
            target_formats.extend(["1080p", "m1080p"])
            
        # Si bajo 1080p, ya no quiero micro
        elif formato_descargado == "1080p":
            target_formats.extend(["m1080p"])
            
        # Nota: 2160p y m1080p solo se anulan a sí mismos (ya añadido en target_formats)

        # Ejecutamos la actualización masiva para esta película
        # Usamos ANY para pasar la lista de formatos
        cur.execute("""
            UPDATE descargas 
            SET descargado = TRUE 
            WHERE pelicula_id = %s AND formato = ANY(%s)
        """, (pid, target_formats))
        
        conn.commit()
        count = cur.rowcount
        cur.close()
        conn.close()
        
        print(f"      [DB] Actualizados {count} registros (Cascada para {formato_descargado})")
        return True
        
    except Exception as e:
        print(f"[DB Error] Cascada fallida: {e}")
        return False
import re
import os
import config
from datetime import datetime

def sanitizar_nombre(nombre):
    """
    Elimina caracteres no válidos para sistemas de archivos (Windows/Linux).
    Reemplaza : < > " / \ | ? * por nada o guiones.
    """
    if not nombre: return "sin_titulo"
    
    # 1. Reemplazar dos puntos por espacio-guión para mantener legibilidad
    nombre = nombre.replace(":", " -")
    
    # 2. Eliminar caracteres estrictamente prohibidos
    nombre = re.sub(r'[<>:"/\\|?*]', '', nombre)
    
    # 3. Eliminar espacios dobles y espacios al final/inicio
    nombre = re.sub(r'\s+', ' ', nombre).strip()
    
    # 4. Evitar nombres reservados en Windows
    nombre = re.sub(r'^(CON|PRN|AUX|NUL|COM\d|LPT\d)$', r'\1_', nombre, flags=re.IGNORECASE)

    # 5. Evitar puntos finales
    nombre = nombre.strip('.')

    return nombre

def formatear_tamano(size_in_mb):
    """Convierte MB a GB/MB string para el frontend"""
    if not size_in_mb: return "0 MB"
    if size_in_mb >= 1024:
        return f"{size_in_mb/1024:.2f} GB"
    return f"{size_in_mb:.1f} MB"

def debe_aplicar_limite():
    """
    Comprueba si la hora actual está dentro del rango definido en config
    para aplicar el límite de velocidad.
    """
    if not config.ENABLE_SPEED_LIMIT:
        return False
        
    now = datetime.now().time()
    start = config.LIMIT_START_TIME
    end = config.LIMIT_END_TIME
    
    # Caso 1: Rango en el mismo día (Ej: 08:00 a 20:00)
    if start < end:
        return start <= now <= end
    # Caso 2: Rango cruza la medianoche (Ej: 22:00 a 08:00)
    else:
        return now >= start or now <= end
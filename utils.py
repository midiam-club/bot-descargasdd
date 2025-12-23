import re
import os

def sanitizar_nombre(nombre):
    """
    Elimina caracteres no válidos para sistemas de archivos (Windows/Linux).
    Reemplaza : < > " / \ | ? * por nada o guiones.
    """
    if not nombre: return "sin_titulo"
    
    # 1. Reemplazar dos puntos por espacio-guión para mantener legibilidad (ej: "Misión: Imposible" -> "Misión - Imposible")
    nombre = nombre.replace(":", " -")
    
    # 2. Eliminar caracteres estrictamente prohibidos
    # < > : " / \ | ? *
    nombre = re.sub(r'[<>:"/\\|?*]', '', nombre)
    
    # 3. Eliminar espacios dobles y espacios al final/inicio
    nombre = re.sub(r'\s+', ' ', nombre).strip()
    
    # 4. Evitar nombres reservados en Windows (NUL, COM1, etc) - Opcional pero recomendado
    nombre = re.sub(r'^(CON|PRN|AUX|NUL|COM\d|LPT\d)$', r'\1_', nombre, flags=re.IGNORECASE)

    # 5. Evitar que empiece o termine con punto
    nombre = nombre.strip('.')

    return nombre

def formatear_tamano(size_in_mb):
    """Convierte MB a GB/MB string"""
    if not size_in_mb: return "0 MB"
    if size_in_mb >= 1024:
        return f"{size_in_mb/1024:.2f} GB"
    return f"{size_in_mb:.1f} MB"
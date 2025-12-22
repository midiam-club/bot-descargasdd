# 1. Usamos Python 3.11 Slim (Debian optimizado, muy ligero)
FROM python:3.11-slim

# Evita que Python genere archivos .pyc y fuerza logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 2. Instalamos dependencias del sistema y herramientas (7zip, MediaInfo)
# - curl/gnupg: necesarios para descargar dependencias
# - p7zip-full: para descomprimir
# - mediainfo: para renombrado
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    p7zip-full \
    mediainfo \
    && rm -rf /var/lib/apt/lists/*

# 3. Directorio de trabajo
WORKDIR /app

# 4. Copiar y instalar librerías de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. INSTALACIÓN OPTIMIZADA DE PLAYWRIGHT
# En lugar de usar la imagen gigante de Microsoft, instalamos
# Playwright y LUEGO solo el navegador Chromium y sus dependencias del sistema.
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# 6. Copiar el código fuente del bot (todos los ficheros .py)
COPY . .

# 7. Comando de ejecución
CMD ["python", "-u", "main.py"]
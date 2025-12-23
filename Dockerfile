# 1. Usamos Python 3.11 Slim (Debian optimizado, muy ligero)
FROM python:3.11-slim

# Evita que Python genere archivos .pyc y fuerza logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo
WORKDIR /app

# 2. Instalamos dependencias del sistema y herramientas de compilación
#    - wget, make, g++: NECESARIOS para compilar unrar
#    - p7zip-full, mediainfo: Herramientas del bot
#    - Librerías extra: Dependencias comunes para que Chromium/Playwright no fallen en la versión slim
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    wget \
    make \
    g++ \
    mediainfo \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 3. --- INSTALACIÓN UNRAR (RARLAB) ---
# Descargamos, compilamos e instalamos la versión oficial que soporta contraseñas y RAR5.
# Esto genera el binario 'unrar' en /usr/bin/unrar que usará tu script.
RUN wget https://www.rarlab.com/rar/unrarsrc-6.2.12.tar.gz && \
    tar -xvf unrarsrc-6.2.12.tar.gz && \
    cd unrar && \
    make -f makefile && \
    install -v -m755 unrar /usr/bin/unrar && \
    cd .. && \
    rm -rf unrar unrarsrc-6.2.12.tar.gz

# 4. Copiar e instalar librerías de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. INSTALACIÓN OPTIMIZADA DE PLAYWRIGHT
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# 6. Copiar el código fuente del bot
COPY . .

# 7. Comando de ejecución
CMD ["python", "-u", "main.py"]
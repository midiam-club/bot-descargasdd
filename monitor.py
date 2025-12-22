import time
from threading import Lock

class DownloadMonitor:
    def __init__(self):
        self._lock = Lock()
        # Estructura: { "Nombre Pelicula": { "archivo.rar": { "progress": 50, "speed": "2 MB/s", "size": "1GB" } } }
        self.active_downloads = {}
        self.total_speed = 0.0 # MB/s

    def update_download(self, pelicula, archivo, leido_bytes, total_bytes, velocidad_mb):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            
            porcentaje = (leido_bytes / total_bytes) * 100 if total_bytes > 0 else 0
            
            self.active_downloads[pelicula][archivo] = {
                "progress": round(porcentaje, 1),
                "speed": round(velocidad_mb, 2),
                "downloaded": round(leido_bytes / (1024*1024), 2),
                "total": round(total_bytes / (1024*1024), 2)
            }
            self._recalculate_total_speed()

    def remove_download(self, pelicula, archivo):
        with self._lock:
            if pelicula in self.active_downloads:
                if archivo in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula][archivo]
                # Si la peli se queda sin archivos bajando, borramos la entrada
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]
            self._recalculate_total_speed()

    def _recalculate_total_speed(self):
        # Suma la velocidad de todas las descargas activas
        total = 0.0
        for peli in self.active_downloads.values():
            for datos in peli.values():
                total += datos["speed"]
        self.total_speed = round(total, 2)

    def get_status(self):
        with self._lock:
            return {
                "downloads": self.active_downloads,
                "total_speed": self.total_speed
            }

# Instancia global (Singleton)
state = DownloadMonitor()
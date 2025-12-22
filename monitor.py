import time
from threading import Lock
import config 

class DownloadMonitor:
    def __init__(self):
        self._lock = Lock()
        self.active_downloads = {}
        self.history = {}
        self.total_speed = 0.0
        # Configuración dinámica en memoria
        self.dynamic_config = {
            "max_parallel": config.MAX_WORKERS, # Inicia con el valor del .env
            "limit_enabled": config.ENABLE_SPEED_LIMIT,
            "limit_value": config.SPEED_LIMIT_MB
        }

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

    def finish_download(self, pelicula, archivo, avg_speed, duration_str):
        with self._lock:
            if pelicula in self.active_downloads:
                if archivo in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula][archivo]
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]
            
            if pelicula not in self.history:
                self.history[pelicula] = []
            
            self.history[pelicula].append({
                "archivo": archivo,
                "avg_speed": round(avg_speed, 2),
                "duration": duration_str,
                "timestamp": time.strftime("%H:%M:%S")
            })
            self._recalculate_total_speed()

    def remove_download(self, pelicula, archivo):
        with self._lock:
            if pelicula in self.active_downloads:
                if archivo in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula][archivo]
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]
            self._recalculate_total_speed()

    def _recalculate_total_speed(self):
        total = 0.0
        for peli in self.active_downloads.values():
            for datos in peli.values():
                total += datos["speed"]
        self.total_speed = round(total, 2)

    def set_speed_limit(self, enabled, limit_mb):
        with self._lock:
            self.dynamic_config["limit_enabled"] = enabled
            self.dynamic_config["limit_value"] = float(limit_mb)
        # Actualizamos config global para que lo lean otros módulos
        config.ENABLE_SPEED_LIMIT = enabled
        config.SPEED_LIMIT_MB = float(limit_mb)

    def set_max_parallel(self, n):
        """Actualiza el límite de concurrencia"""
        with self._lock:
            val = int(n)
            if val < 1: val = 1
            self.dynamic_config["max_parallel"] = val

    def get_max_parallel(self):
        """Lectura segura para el bucle principal"""
        with self._lock:
            return self.dynamic_config["max_parallel"]

    def get_status(self):
        with self._lock:
            return {
                "downloads": self.active_downloads,
                "history": self.history,
                "total_speed": self.total_speed,
                "config": self.dynamic_config
            }

state = DownloadMonitor()
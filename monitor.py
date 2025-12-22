import time
from threading import Lock, Condition
import config 

class DownloadMonitor:
    def __init__(self):
        self._lock = Lock()
        self.active_downloads = {}
        self.history = {}
        self.total_speed = 0.0
        
        # --- NUEVO: TÍTULOS COMPLETADOS ---
        self.completed_titles = set()
        
        # Gestión de Slots
        self.download_condition = Condition()
        self.current_downloading_files = 0
        
        self.dynamic_config = {
            "max_parallel": config.MAX_WORKERS, 
            "limit_enabled": config.ENABLE_SPEED_LIMIT,
            "limit_value": config.SPEED_LIMIT_MB
        }

    # --- NUEVO MÉTODO: MARCAR COMO COMPLETADO ---
    def mark_completed(self, titulo):
        with self._lock:
            self.completed_titles.add(titulo)

    # --- SEMÁFORO ---
    def acquire_download_slot(self):
        with self.download_condition:
            while self.current_downloading_files >= self.dynamic_config["max_parallel"]:
                self.download_condition.wait()
            self.current_downloading_files += 1

    def release_download_slot(self):
        with self.download_condition:
            if self.current_downloading_files > 0:
                self.current_downloading_files -= 1
            self.download_condition.notify_all()

    # --- RESTO DE MÉTODOS (Iguales) ---
    def update_download(self, pelicula, archivo, leido_bytes, total_bytes, velocidad_mb):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            
            porcentaje = (leido_bytes / total_bytes) * 100 if total_bytes > 0 else 0
            
            self.active_downloads[pelicula][archivo] = {
                "progress": round(porcentaje, 1),
                "speed": round(velocidad_mb, 2),
                "downloaded": round(leido_bytes / (1024*1024), 2),
                "total": round(total_bytes / (1024*1024), 2),
                "status": "downloading"
            }
            self._recalculate_total_speed()

    def update_extraction(self, pelicula, porcentaje):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            clave_fake = "📦 Descomprimiendo..."
            self.active_downloads[pelicula][clave_fake] = {
                "progress": round(porcentaje, 1),
                "speed": 0,
                "downloaded": 0,
                "total": 0,
                "status": "extracting"
            }

    def clean_extraction(self, pelicula):
        with self._lock:
            if pelicula in self.active_downloads:
                if "📦 Descomprimiendo..." in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]["📦 Descomprimiendo..."]
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]

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
                if datos.get("status") == "downloading":
                    total += datos["speed"]
        self.total_speed = round(total, 2)

    def set_speed_limit(self, enabled, limit_mb):
        with self._lock:
            self.dynamic_config["limit_enabled"] = enabled
            self.dynamic_config["limit_value"] = float(limit_mb)
        config.ENABLE_SPEED_LIMIT = enabled
        config.SPEED_LIMIT_MB = float(limit_mb)

    def set_max_parallel(self, n):
        with self.download_condition:
            val = int(n)
            if val < 1: val = 1
            self.dynamic_config["max_parallel"] = val
            self.download_condition.notify_all()

    def get_max_parallel(self):
        with self._lock:
            return self.dynamic_config["max_parallel"]

    def get_status(self):
        with self._lock:
            return {
                "downloads": self.active_downloads,
                "history": self.history,
                "total_speed": self.total_speed,
                "config": self.dynamic_config,
                # Enviamos la lista de completados al frontend
                "completed": list(self.completed_titles)
            }

state = DownloadMonitor()
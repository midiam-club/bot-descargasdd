import time
from threading import Lock, Condition
import config 

class DownloadMonitor:
    def __init__(self):
        self._lock = Lock()
        
        # Diccionarios de estado
        self.active_downloads = {}
        self.history = {}
        self.completed_titles = set()
        self.movie_formats = {}
        self.total_speed = 0.0
        
        # Gestión de Novedades Detectadas
        self.detected_movies = [] 
        
        # Gestión de Slots
        self.download_condition = Condition()
        self.current_downloading_files = 0
        
        # DEBUG: Log para ver qué configuración está cargando realmente
        print(f"[MONITOR] Configuración cargada: Max Parallel={config.MAX_WORKERS}, Limit Enabled={config.ENABLE_SPEED_LIMIT}")

        # Configuración dinámica
        self.dynamic_config = {
            "max_parallel": int(config.MAX_WORKERS), 
            "limit_enabled": getattr(config, 'ENABLE_SPEED_LIMIT', True),
            "limit_value": float(config.SPEED_LIMIT_MB)
        }

    # ... RESTO DEL CÓDIGO IGUAL QUE EN EL PASO ANTERIOR ...
    # (Para no saturar la respuesta, el resto de métodos son idénticos al monitor.py que te pasé en el Turno #16)
    # Solo asegúrate de copiar la clase entera del Turno #16 y añadir el print en el __init__
    
    # --- GESTIÓN DE DETECTADAS ---
    def set_detected_movies(self, movies_list):
        with self._lock:
            self.detected_movies = movies_list

    # --- GESTIÓN DE ESTADO FINAL ---
    def mark_completed(self, titulo, formato=None):
        with self._lock:
            key = f"{titulo} [{formato}]" if formato else titulo
            self.completed_titles.add(key)

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

    # --- UPDATE ---
    def update_download(self, pelicula, archivo, leido_bytes, total_bytes, velocidad_mb, host=None, debrid=None, formato=None):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            
            if formato:
                self.movie_formats[pelicula] = formato
            
            porcentaje = (leido_bytes / total_bytes) * 100 if total_bytes > 0 else 0
            
            datos_previos = self.active_downloads[pelicula].get(archivo, {})
            if datos_previos.get("status") == "completed":
                return

            host_final = host if host else datos_previos.get("host", "?")
            debrid_final = debrid if debrid else datos_previos.get("debrid", "?")

            self.active_downloads[pelicula][archivo] = {
                "progress": round(porcentaje, 1),
                "speed": round(velocidad_mb, 2),
                "downloaded": round(leido_bytes / (1024*1024), 2),
                "total": round(total_bytes / (1024*1024), 2),
                "status": "downloading",
                "host": host_final,
                "debrid": debrid_final
            }
            self._recalculate_total_speed()

    def finish_download(self, pelicula, archivo, avg_speed, duration_str, formato=None):
        with self._lock:
            final_size_mb = 0
            if pelicula in self.active_downloads and archivo in self.active_downloads[pelicula]:
                final_size_mb = self.active_downloads[pelicula][archivo].get("total", 0)

            if pelicula in self.active_downloads and archivo in self.active_downloads[pelicula]:
                file_data = self.active_downloads[pelicula][archivo]
                file_data["status"] = "completed"
                file_data["progress"] = 100.0
                file_data["speed"] = 0.0
                file_data["downloaded"] = file_data["total"] 
            
            fmt_real = formato if formato else self.movie_formats.get(pelicula, "")
            history_key = f"{pelicula} [{fmt_real}]" if fmt_real else pelicula

            if history_key not in self.history:
                self.history[history_key] = []
            
            self.history[history_key].append({
                "archivo": archivo,
                "avg_speed": round(avg_speed, 2),
                "duration": duration_str,
                "timestamp": time.strftime("%H:%M:%S"),
                "formato": fmt_real,
                "size": final_size_mb
            })
            self._recalculate_total_speed()

    def purge_movie(self, pelicula):
        with self._lock:
            if pelicula in self.active_downloads:
                del self.active_downloads[pelicula]
            if pelicula in self.movie_formats:
                del self.movie_formats[pelicula]
            self._recalculate_total_speed()

    def remove_download(self, pelicula, archivo):
        with self._lock:
            if pelicula in self.active_downloads:
                if archivo in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula][archivo]
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]
            self._recalculate_total_speed()

    def update_extraction(self, pelicula, porcentaje):
        with self._lock:
            if pelicula not in self.active_downloads: self.active_downloads[pelicula] = {}
            if "__meta__" not in self.active_downloads[pelicula]:
                self.active_downloads[pelicula]["__meta__"] = {"total_parts": 1}

            clave_fake = "📦 Descomprimiendo..."
            self.active_downloads[pelicula][clave_fake] = {
                "progress": round(porcentaje, 1),
                "speed": 0, "downloaded": 0, "total": 0,
                "status": "extracting", "host": "Local", "debrid": "System"
            }

    def clean_extraction(self, pelicula):
        with self._lock:
            if pelicula in self.active_downloads:
                if "📦 Descomprimiendo..." in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]["📦 Descomprimiendo..."]

    def init_movie(self, titulo, total_parts):
        with self._lock:
            if titulo not in self.active_downloads:
                self.active_downloads[titulo] = {}
            self.active_downloads[titulo]["__meta__"] = {
                "total_parts": total_parts,
                "created_at": time.time()
            }

    def _recalculate_total_speed(self):
        total = 0.0
        for peli in self.active_downloads.values():
            for key, datos in peli.items():
                if key == "__meta__": continue
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
                "completed": list(self.completed_titles),
                "formats": self.movie_formats,
                "detected": self.detected_movies 
            }

state = DownloadMonitor()
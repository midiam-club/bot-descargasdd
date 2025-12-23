import time
from threading import Lock, Condition
import config 

class DownloadMonitor:
    def __init__(self):
        self._lock = Lock()
        
        # Diccionarios de estado
        self.active_downloads = {}
        self.history = {}
        self.completed_titles = set() # Para el Flag verde en historial
        self.total_speed = 0.0
        
        # Gestión de Slots (Semáforo de descargas simultáneas)
        self.download_condition = Condition()
        self.current_downloading_files = 0
        
        # Configuración dinámica
        self.dynamic_config = {
            "max_parallel": config.MAX_WORKERS, 
            "limit_enabled": config.ENABLE_SPEED_LIMIT,
            "limit_value": config.SPEED_LIMIT_MB
        }

    # --- GESTIÓN DE ESTADO FINAL ---
    def mark_completed(self, titulo):
        """Marca un título como totalmente finalizado (Flag Verde)"""
        with self._lock:
            self.completed_titles.add(titulo)

    # --- SEMÁFORO (Control de concurrencia real) ---
    def acquire_download_slot(self):
        """Bloquea el hilo hasta que haya un hueco libre según la config"""
        with self.download_condition:
            while self.current_downloading_files >= self.dynamic_config["max_parallel"]:
                self.download_condition.wait()
            self.current_downloading_files += 1

    def release_download_slot(self):
        """Libera un hueco y avisa a los hilos en espera"""
        with self.download_condition:
            if self.current_downloading_files > 0:
                self.current_downloading_files -= 1
            self.download_condition.notify_all()

    # --- ACTUALIZACIÓN DE DESCARGAS ---
    def update_download(self, pelicula, archivo, leido_bytes, total_bytes, velocidad_mb, host=None, debrid=None):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            
            porcentaje = (leido_bytes / total_bytes) * 100 if total_bytes > 0 else 0
            
            # Recuperamos datos previos para no machacar info si llega parcial
            datos_previos = self.active_downloads[pelicula].get(archivo, {})
            
            # Si el archivo ya se marcó como completado, ignoramos actualizaciones tardías de red
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

    def finish_download(self, pelicula, archivo, avg_speed, duration_str):
        """
        Marca el archivo como completado PERO NO LO BORRA de active_downloads.
        Esto permite que la barra de progreso total siga contabilizando el 100% de este archivo
        mientras se descargan las otras partes.
        """
        with self._lock:
            if pelicula in self.active_downloads and archivo in self.active_downloads[pelicula]:
                # Actualizamos a estado final visual
                file_data = self.active_downloads[pelicula][archivo]
                file_data["status"] = "completed"
                file_data["progress"] = 100.0
                file_data["speed"] = 0.0
                file_data["downloaded"] = file_data["total"] # Asegurar consistencia visual
            
            # Añadimos al historial para persistencia
            if pelicula not in self.history:
                self.history[pelicula] = []
            
            self.history[pelicula].append({
                "archivo": archivo,
                "avg_speed": round(avg_speed, 2),
                "duration": duration_str,
                "timestamp": time.strftime("%H:%M:%S")
            })
            self._recalculate_total_speed()

    def purge_movie(self, pelicula):
        """
        Borra la película entera de la lista de 'Activas'.
        Se debe llamar SOLO cuando todo el proceso (descarga paralelela + extracción) ha terminado.
        """
        with self._lock:
            if pelicula in self.active_downloads:
                del self.active_downloads[pelicula]
            self._recalculate_total_speed()

    def remove_download(self, pelicula, archivo):
        """Borrado forzoso de un archivo individual (usado en errores)"""
        with self._lock:
            if pelicula in self.active_downloads:
                if archivo in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula][archivo]
                if not self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]
            self._recalculate_total_speed()

    # --- GESTIÓN DE EXTRACCIÓN ---
    def update_extraction(self, pelicula, porcentaje):
        with self._lock:
            if pelicula not in self.active_downloads:
                self.active_downloads[pelicula] = {}
            
            # Usamos una clave especial para representar la extracción
            clave_fake = "📦 Descomprimiendo..."
            
            self.active_downloads[pelicula][clave_fake] = {
                "progress": round(porcentaje, 1),
                "speed": 0,
                "downloaded": 0,
                "total": 0,
                "status": "extracting",
                "host": "Local",
                "debrid": "System"
            }

    def clean_extraction(self, pelicula):
        with self._lock:
            if pelicula in self.active_downloads:
                if "📦 Descomprimiendo..." in self.active_downloads[pelicula]:
                    del self.active_downloads[pelicula]["📦 Descomprimiendo..."]

    # --- CÁLCULOS Y CONFIG ---
    def _recalculate_total_speed(self):
        total = 0.0
        for peli in self.active_downloads.values():
            for datos in peli.values():
                # Solo sumamos velocidad si está descargando activamente
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
            # Notificamos a los hilos bloqueados por si el límite ha aumentado
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
                "completed": list(self.completed_titles)
            }

state = DownloadMonitor()
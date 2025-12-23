import os
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from monitor import state
import config

# Definimos rutas base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Servir archivos ESTÁTICOS (Imágenes, CSS, JS)
        if self.path.startswith('/static/'):
            # Limpiamos la ruta para evitar trucos de '..'
            clean_path = os.path.normpath(self.path).lstrip('/')
            # Si el path empieza con static/, quitamos esa parte para buscar en la carpeta
            if clean_path.startswith('static'):
                parts = clean_path.split(os.sep)
                if len(parts) > 1:
                    filename = parts[1] # Tomamos el nombre del archivo
                    file_path = os.path.join(STATIC_DIR, filename)
                    
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        # Adivinar el tipo MIME (png, jpg, ico, etc)
                        mime_type, _ = mimetypes.guess_type(file_path)
                        self.send_response(200)
                        self.send_header('Content-type', mime_type or 'application/octet-stream')
                        self.end_headers()
                        with open(file_path, 'rb') as f:
                            self.wfile.write(f.read())
                        return
            
            # Si no encuentra el archivo
            self.send_response(404)
            self.end_headers()
            return

        # 2. Servir la API de estado
        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = state.get_status()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return

        # 3. Servir el Dashboard (HTML)
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            try:
                with open(os.path.join(TEMPLATE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
                    self.wfile.write(f.read().encode('utf-8'))
            except Exception as e:
                self.wfile.write(f"<h1>Error cargando plantilla: {e}</h1>".encode('utf-8'))
            return

        # 4. Cualquier otra cosa -> 404
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # API para cambiar configuración
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            if self.path == '/api/settings/limit':
                enabled = data.get('enabled', True)
                limit = data.get('limit', 0)
                state.set_speed_limit(enabled, limit)
                self.send_response(200)
            
            elif self.path == '/api/settings/parallel':
                max_p = data.get('max_parallel', 1)
                state.set_max_parallel(max_p)
                self.send_response(200)
            
            else:
                self.send_response(404)
        
        except Exception as e:
            print(f"Error en POST: {e}")
            self.send_response(500)
            
        self.end_headers()

    def log_message(self, format, *args):
        # Silenciar logs de cada petición HTTP para no ensuciar la consola del bot
        return

def run_web_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, RequestHandler)
    # print("Servidor web iniciado en puerto 8000") 
    httpd.serve_forever()
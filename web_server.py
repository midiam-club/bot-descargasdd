# web_server.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn
from monitor import state
import os

app = FastAPI()

# Configuración de templates (HTML)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/status")
async def get_status():
    """Endpoint que consume el frontend cada segundo"""
    return state.get_status()

def run_web_server():
    # Ejecuta el servidor en el puerto 8000
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
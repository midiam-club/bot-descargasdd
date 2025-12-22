from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
from monitor import state
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

class LimitConfig(BaseModel):
    enabled: bool
    limit: float

class ParallelConfig(BaseModel):
    max_parallel: int

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/status")
async def get_status():
    return state.get_status()

@app.post("/api/settings/limit")
async def set_limit(conf: LimitConfig):
    state.set_speed_limit(conf.enabled, conf.limit)
    return {"status": "ok"}

@app.post("/api/settings/parallel")
async def set_parallel(conf: ParallelConfig):
    state.set_max_parallel(conf.max_parallel)
    return {"status": "ok"}

def run_web_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
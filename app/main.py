"""Localhost-only control panel for the solo miner."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.btc_address import AddressError, validate_public_address
from app.levels import LEVELS, normalize_level
from app.miner_ctl import MinerError, MinerService
from app.odds import block_odds

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_PATH = ROOT / "config.json"
BINARY = ROOT / "bin" / "minerd"
HOSTS = {"127.0.0.1", "localhost", "::1"}
MEMPOOL_HOST = "mempool.space"
DIFFICULTY_TTL_S = 600
DIFFICULTY_RETRY_S = 45

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_service = MinerService(BINARY)
_config_lock = threading.Lock()
_diff_lock = threading.Lock()
_difficulty: dict = {"value": None, "fetched_at": None, "error": None}


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    btc_address: str = Field(min_length=1, max_length=90)
    level: str | None = Field(default=None, max_length=16)


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: str | None = Field(default=None, max_length=16)


@app.middleware("http")
async def local_only(request: Request, call_next):
    client = request.client.host if request.client else ""
    host = request.headers.get("host", "").split(":")[0].strip("[]")
    origin = request.headers.get("origin")
    if client not in {"127.0.0.1", "::1"} or host not in HOSTS:
        return JSONResponse({"detail": "Este panel solo escucha en esta máquina."}, status_code=403)
    if origin:
        origin_host = origin.split("://", 1)[-1].split("/")[0].split(":")[0].strip("[]")
        if origin_host not in HOSTS:
            return JSONResponse({"detail": "Origen rechazado."}, status_code=403)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def get_config():
    cfg = _load_config()
    spec = LEVELS[cfg["level"]]
    return {
        "btc_address": cfg["btc_address"],
        "level": cfg["level"],
        "threads": spec["threads"],
        "nice": spec["nice"],
        "levels": {
            name: {"threads": item["threads"], "nice": item["nice"], "label": item["label"]}
            for name, item in LEVELS.items()
        },
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_cpus": _max_threads(),
        "miner_present": BINARY.is_file(),
    }


@app.post("/api/config")
def save_config(body: ConfigIn):
    try:
        address = validate_public_address(body.btc_address)
        level = _check_level(body.level or _load_config()["level"])
    except (AddressError, MinerError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    _write_config(address, level)
    spec = LEVELS[level]
    running = _service.snapshot()["running"]
    if running:
        try:
            _service.stop(None)
            _service.start(address, spec["threads"], spec["nice"])
        except MinerError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"btc_address": address, "level": level, "threads": spec["threads"], "restarted": running}


@app.get("/api/status")
def status():
    snap = _service.snapshot()
    diff = _difficulty_snapshot()
    rate = snap["hashrate_avg_hs"] or snap["hashrate_hs"]
    odds = block_odds(rate, diff["value"]) if diff["value"] else {"ready": False}
    snap["difficulty"] = diff
    snap["odds"] = odds
    snap["max_threads"] = _max_threads()
    snap["level"] = _load_config()["level"]
    return snap


@app.post("/api/start")
def start(body: StartIn):
    cfg = _load_config()
    try:
        address = validate_public_address(cfg["btc_address"])
        level = _check_level(body.level or cfg["level"])
        _write_config(address, level)
        spec = LEVELS[level]
        if _service.snapshot()["running"]:
            _service.stop(None)
        _service.start(address, spec["threads"], spec["nice"])
    except (AddressError, MinerError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return _service.snapshot()


@app.post("/api/stop")
def stop():
    _service.stop("Parado desde el panel.")
    return _service.snapshot()


def _max_threads() -> int:
    return max(1, psutil.cpu_count(logical=True) or os.cpu_count() or 1)


def _check_level(level: str) -> str:
    if level not in LEVELS:
        raise MinerError("El ritmo tiene que ser bajo, medio o alto.")
    spec = LEVELS[level]
    if spec["threads"] > _max_threads():
        raise MinerError("Este Mac no tiene tantos hilos para ese ritmo.")
    return level


def _load_config() -> dict:
    with _config_lock:
        if not CONFIG_PATH.is_file():
            return {"btc_address": "", "level": "medio"}
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"btc_address": "", "level": "medio"}
    address = data.get("btc_address") if isinstance(data, dict) else ""
    level = data.get("level") if isinstance(data, dict) else None
    threads = data.get("threads") if isinstance(data, dict) else None
    if not isinstance(address, str):
        address = ""
    if not isinstance(level, str):
        level = None
    if not isinstance(threads, int):
        threads = None
    return {"btc_address": address, "level": normalize_level(level, threads)}


def _write_config(address: str, level: str) -> None:
    spec = LEVELS[level]
    payload = json.dumps(
        {"btc_address": address, "level": level, "threads": spec["threads"]},
        indent=2,
    ) + "\n"
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with _config_lock:
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)


def _difficulty_snapshot() -> dict:
    with _diff_lock:
        return dict(_difficulty)


def _difficulty_loop() -> None:
    while True:
        value, error = _fetch_difficulty()
        with _diff_lock:
            if value is not None:
                _difficulty["value"] = value
                _difficulty["fetched_at"] = time.time()
                _difficulty["error"] = None
                delay = DIFFICULTY_TTL_S
            else:
                _difficulty["error"] = error
                delay = DIFFICULTY_RETRY_S
        time.sleep(delay)


def _fetch_difficulty() -> tuple[float | None, str | None]:
    try:
        height = _mempool_text("https://mempool.space/api/blocks/tip/height").strip()
        if not height.isdigit():
            return None, "La altura del bloque no era un número."
        block_hash = _mempool_text(f"https://mempool.space/api/block-height/{height}").strip()
        if len(block_hash) != 64:
            return None, "El hash del bloque no tenía el tamaño esperado."
        raw = _mempool_text(f"https://mempool.space/api/block/{block_hash}")
        data = json.loads(raw)
        difficulty = float(data["difficulty"])
        if difficulty <= 0:
            return None, "La dificultad recibida no es válida."
        return difficulty, None
    except (OSError, urllib.error.URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, exc.__class__.__name__


def _mempool_text(url: str) -> str:
    if urllib.parse.urlsplit(url).hostname != MEMPOOL_HOST:
        raise urllib.error.URLError("host")
    request = urllib.request.Request(url, headers={"User-Agent": "minar-local", "Accept": "application/json"})
    opener = urllib.request.build_opener(_RefuseRedirects())
    with opener.open(request, timeout=12) as response:
        final = response.geturl()
        if urllib.parse.urlsplit(final).hostname != MEMPOOL_HOST:
            raise urllib.error.URLError("redirect")
        return response.read(1_000_000).decode("utf-8", "replace")


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


threading.Thread(target=_difficulty_loop, name="minar-difficulty", daemon=True).start()

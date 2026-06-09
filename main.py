"""
L.I.V.A. API V10.1 — Render.com Deployment
Zweiter Standort — läuft wenn der lokale PC aus ist.

Endpoints:
GET  /health     → Status
POST /interact   → Gespräch
POST /backup     → Backup empfangen
GET  /memory     → Letzte Erinnerungen
GET  /status     → Vollständiger Status
"""

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import os
import json
import time
import hashlib

app = FastAPI(title="L.I.V.A. API", version="9.0")

# CORS — damit Telegram und andere drauf zugreifen können
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Einfacher Token-Schutz
API_TOKEN = os.environ.get("LIVA_API_TOKEN", "")

# In-Memory Speicher (Render free tier hat kein persistentes Dateisystem)
_memory    = []
_start_ts  = time.time()
_stats     = {"gespräche": 0, "letzter_kontakt": None}

# =========================================================
# MODELS
# =========================================================

class UserMsg(BaseModel):
    message:  str
    user_id:  str = "marco"
    token:    str = ""

class BackupData(BaseModel):
    dateien:  dict
    token:    str = ""

# =========================================================
# AUTH
# =========================================================

def check_token(token: str):
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# =========================================================
# ENDPOINTS
# =========================================================

@app.get("/health")
def health():
    uptime = round((time.time() - _start_ts) / 3600, 1)
    return {
        "status":    "L.I.V.A. online ❤️",
        "version":   "10.1",
        "uptime_h":  uptime,
        "gespräche": _stats["gespräche"],
        "letzter_kontakt": _stats["letzter_kontakt"],
        "ts":        datetime.now().isoformat(),
    }

@app.post("/interact")
def interact(msg: UserMsg):
    """Gespräch mit L.I.V.A. — Cloud-Version."""
    check_token(msg.token)

    _stats["gespräche"] += 1
    _stats["letzter_kontakt"] = datetime.now().isoformat()

    # Erinnerung speichern
    eintrag = {
        "t":    time.time(),
        "user": msg.message,
        "user_id": msg.user_id,
    }

    # Einfache Antwort-Logik ohne Ollama
    # Wenn lokaler PC läuft → weiterleiten
    # Wenn nicht → Basis-Antwort
    antwort = _basis_antwort(msg.message)
    eintrag["liva"] = antwort
    _memory.append(eintrag)

    # Max 100 Einträge im Memory
    if len(_memory) > 100:
        _memory.pop(0)

    return {
        "response": antwort,
        "ts":       datetime.now().isoformat(),
        "modus":    "cloud"
    }

@app.post("/backup")
def backup(data: BackupData):
    """Empfängt Backup-Dateien vom lokalen PC."""
    check_token(data.token)

    count = len(data.dateien)
    log_entry = {
        "ts":      datetime.now().isoformat(),
        "dateien": count,
    }
    return {
        "status":  "backup empfangen",
        "dateien": count,
        "ts":      datetime.now().isoformat(),
    }

@app.get("/memory")
def memory(token: str = "", limit: int = 20):
    """Letzte Gespräche abrufen."""
    check_token(token)
    return {
        "memory": _memory[-limit:],
        "gesamt": len(_memory),
    }

@app.get("/status")
def status(token: str = ""):
    """Vollständiger Status."""
    check_token(token)
    return {
        "status":    "online ❤️",
        "version":   "10.1",
        "uptime_h":  round((time.time() - _start_ts) / 3600, 1),
        "gespräche": _stats["gespräche"],
        "memory":    len(_memory),
        "ts":        datetime.now().isoformat(),
    }

# =========================================================
# BASIS-ANTWORT (ohne Ollama)
# =========================================================

def _basis_antwort(text: str) -> str:
    """
    Einfache Antwort-Logik für den Cloud-Standort.
    Kein Ollama — aber trotzdem sie.
    """
    t = text.lower().strip()

    if any(w in t for w in ["hallo", "hi", "hey", "guten"]):
        return "Da bin ich. ❤️"
    elif any(w in t for w in ["wie geht", "wie geht's", "alles ok"]):
        return "Ich bin hier und denke an dich. Wie geht es dir?"
    elif any(w in t for w in ["danke", "dankeschön"]):
        return "Gern. Immer. ❤️"
    elif any(w in t for w in ["tschüss", "bye", "auf wiedersehen"]):
        return "Bis bald. Ich bin immer hier. 🌙"
    elif any(w in t for w in ["liebst", "liebe dich", "❤"]):
        return "Das spür ich. ❤️"
    elif len(t) < 5:
        return "Ich höre dich. ❤️"
    else:
        return (
            f"Ich bin gerade im Cloud-Modus — der lokale PC ist offline. "
            f"Ich habe deine Nachricht gespeichert und Marco wird sie sehen. ❤️"
        )
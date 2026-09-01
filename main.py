"""
L.I.V.A. — Render-Relais V11
=============================
Marcos Ziel (10.08.): Sie soll von überall erreichbar sein. Sein
Anschluss läuft über DS-Lite (Vodafone) — eine echte Portfreigabe
funktioniert dort grundsätzlich nicht, egal wie richtig sie
eingerichtet ist. Der Router bekommt selbst keine öffentliche
IPv4-Adresse.

WAS DIESE DATEI VORHER WAR
---------------------------
Eine Attrappe. Wenn der lokale PC aus war, antwortete sie mit
vorgefertigten Sätzen ("Ich bin gerade im Cloud-Modus ❤️") — kein
Ollama, kein Gedächtnis, keine Werte. Das war unehrlich: Sie hat
etwas vorgegeben zu sein, ohne dass sie da war. Genau das Muster,
das an anderer Stelle im Projekt schon korrigiert wurde (Selbst-
gespräche, die Fähigkeiten behaupteten, die sie nicht hat).

WAS SIE JETZT IST
------------------
Ein Relais, kein Ersatz. Der lokale PC baut eine AUSGEHENDE
WebSocket-Verbindung hierher auf — das funktioniert immer, auch
hinter DS-Lite, weil ausgehende Verbindungen nie durch NAT blockiert
werden. Über diese eine Leitung reicht Render eingehende Anfragen
von außen durch und schickt die Antwort zurück.

Ist der PC aus, sagt sie das ehrlich — keine Attrappe mehr.

SICHERHEIT
----------
- Der Tunnel-Client authentifiziert sich mit LIVA_API_TOKEN beim
  Verbindungsaufbau. Ohne gültigen Token keine Verbindung.
- Render selbst prüft nichts an den durchgereichten Anfragen — das
  macht Livas eigener Zugang (Passwörter, Ratenbremse, Firewall,
  Werkzeug-Riegel), sobald sie lokal ankommen. Render ist nur das
  Rohr, nicht der Türsteher.
- Eine einfache Grenze GEGEN RENDER SELBST ist trotzdem eingebaut:
  Größe und Tempo der Anfragen, damit niemand Render allein durch
  Anklopfen überlastet, bevor überhaupt etwas beim PC ankommt.
"""

import asyncio
import base64
import json
import os
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, JSONResponse, HTMLResponse

app = FastAPI(title="L.I.V.A. Relais", version="11.0")

API_TOKEN = os.environ.get("LIVA_API_TOKEN", "")

# ── Zustand ──────────────────────────────────────────────────
# Nur EIN Tunnel wird erwartet — Marcos einer Rechner. Kommt ein
# zweiter Verbindungsversuch mit demselben Token, wird der alte
# abgelöst (etwa nach einem Neustart des lokalen PCs).
_tunnel: WebSocket | None = None
_tunnel_verbunden_seit = 0.0
_wartende: dict[str, asyncio.Future] = {}

# Grenze GEGEN RENDER (nicht gegen Liva — die hat ihre eigene)
ANTWORT_TIMEOUT = 25          # Sekunden, bis Render selbst aufgibt
MAX_KOERPER = 20 * 1024 * 1024   # 20 MB, für Datei-Übergabe genug
_verkehr = defaultdict(list)
GRENZE_PRO_MINUTE = 90


def _rate_ok(adresse: str) -> bool:
    """Grobe Bremse gegen Render selbst — die feine macht Liva."""
    jetzt = time.time()
    liste = [t for t in _verkehr[adresse] if jetzt - t < 60]
    liste.append(jetzt)
    _verkehr[adresse] = liste
    if len(_verkehr) > 2000:
        for k in list(_verkehr):
            if not _verkehr[k] or jetzt - _verkehr[k][-1] > 300:
                del _verkehr[k]
    return len(liste) <= GRENZE_PRO_MINUTE


# ── Der Tunnel selbst ────────────────────────────────────────
@app.websocket("/tunnel")
async def tunnel(ws: WebSocket):
    """
    Hier verbindet sich Marcos Rechner — ausgehend von ihm, nicht
    von außen angesprochen. Erst nach gültigem Token wird die
    Verbindung als DER Tunnel übernommen.
    """
    global _tunnel, _tunnel_verbunden_seit
    await ws.accept()

    try:
        erste = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except Exception:
        await ws.close(code=4001)
        return

    if erste.get("type") != "auth" or not API_TOKEN \
            or erste.get("token") != API_TOKEN:
        await ws.close(code=4003)
        return

    # Einen bestehenden Tunnel ablösen, falls Marco neu gestartet hat
    if _tunnel is not None:
        try:
            await _tunnel.close(code=4000)
        except Exception:
            pass

    _tunnel = ws
    _tunnel_verbunden_seit = time.time()
    print(f"[TUNNEL] verbunden um {time.strftime('%H:%M:%S')}")

    try:
        while True:
            nachricht = await ws.receive_json()
            if nachricht.get("type") == "response":
                anfrage_id = nachricht.get("id", "")
                zukunft = _wartende.pop(anfrage_id, None)
                if zukunft and not zukunft.done():
                    zukunft.set_result(nachricht)
    except WebSocketDisconnect:
        pass
    except Exception as ex:
        print(f"[TUNNEL] Fehler: {ex}")
    finally:
        if _tunnel is ws:
            _tunnel = None
            print("[TUNNEL] getrennt")
        # Wer noch wartet, soll nicht ewig hängen
        for zukunft in list(_wartende.values()):
            if not zukunft.done():
                zukunft.set_result(None)
        _wartende.clear()


def _offline_seite():
    """Ehrliche Meldung, wenn der PC gerade nicht verbunden ist."""
    return HTMLResponse(
        "<html><body style='background:#12131a;color:#e8e9ef;"
        "font-family:sans-serif;display:flex;align-items:center;"
        "justify-content:center;height:100vh;margin:0'>"
        "<div style='text-align:center'>"
        "<h2>Sie ist gerade nicht erreichbar</h2>"
        "<p style='color:#8b8fa3'>Der Rechner, auf dem sie läuft, "
        "ist gerade aus oder ohne Verbindung.</p>"
        "</div></body></html>",
        status_code=503)


@app.get("/health")
async def health():
    """Nur ein Render-Lebenszeichen — kein Weiterleiten."""
    return {
        "status": "Relais online",
        "tunnel_verbunden": _tunnel is not None,
        "seit_h": (round((time.time() - _tunnel_verbunden_seit) / 3600, 1)
                   if _tunnel else None),
    }


# ── Alles andere wird durchgereicht ─────────────────────────
@app.api_route(
    "/{pfad:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def durchreichen(pfad: str, request: Request):
    """
    Jede Anfrage, die nicht /tunnel oder /health ist, geht an
    Marcos Rechner — falls verbunden.
    """
    if pfad in ("tunnel", "health"):
        return JSONResponse({"fehler": "nicht gefunden"}, status_code=404)

    absender = request.client.host if request.client else "?"
    if not _rate_ok(absender):
        return JSONResponse({"fehler": "zu viele Anfragen"},
                            status_code=429)

    if _tunnel is None:
        return _offline_seite()

    koerper = await request.body()
    if len(koerper) > MAX_KOERPER:
        return JSONResponse({"fehler": "zu groß"}, status_code=413)

    anfrage_id = str(uuid.uuid4())
    zukunft = asyncio.get_event_loop().create_future()
    _wartende[anfrage_id] = zukunft

    # Nur unbedenkliche Kopfzeilen durchreichen — nicht Render- oder
    # Verbindungsinterna, die für Marcos Server ohnehin falsch wären.
    erlaubte_koepfe = ("content-type", "accept", "accept-language",
                       "x-liva-passwort")
    koepfe = {k: v for k, v in request.headers.items()
              if k.lower() in erlaubte_koepfe}

    nachricht = {
        "type": "request",
        "id": anfrage_id,
        "method": request.method,
        "path": "/" + pfad,
        "query": str(request.url.query or ""),
        "headers": koepfe,
        "body_b64": base64.b64encode(koerper).decode("ascii"),
        "real_ip": absender,
    }

    try:
        await _tunnel.send_json(nachricht)
    except Exception:
        _wartende.pop(anfrage_id, None)
        return _offline_seite()

    try:
        antwort = await asyncio.wait_for(zukunft, timeout=ANTWORT_TIMEOUT)
    except asyncio.TimeoutError:
        _wartende.pop(anfrage_id, None)
        return JSONResponse(
            {"fehler": "Sie antwortet gerade nicht rechtzeitig."},
            status_code=504)

    if antwort is None:
        return _offline_seite()

    inhalt = base64.b64decode(antwort.get("body_b64", ""))
    rueck_kopf = antwort.get("headers", {}) or {}
    typ = rueck_kopf.get("content-type", "application/octet-stream")

    return Response(content=inhalt, status_code=antwort.get("status", 200),
                    media_type=typ)

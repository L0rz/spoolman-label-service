"""
Spoolman → Phomemo Label Service
Empfängt Webhooks von Spoolman und druckt automatisch Labels auf dem Phomemo M110.
Port: 7913
"""

import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [LABEL] %(message)s")
log = logging.getLogger("label")

app = FastAPI(title="Spoolman Label Service")

PHOMEMO_API = os.getenv("PHOMEMO_API", "http://192.168.130.138:8080")
LABEL_SIZE  = os.getenv("LABEL_SIZE", "40x30")   # 40x30mm Standard
AUTO_PRINT  = os.getenv("AUTO_PRINT", "false").lower() == "true"

# ─── Label Template ───────────────────────────────────────────────────────────

def build_label(spool: dict) -> str:
    """Erstellt den Label-Text aus Spoolman-Daten."""
    filament = spool.get("filament", {})
    vendor   = filament.get("vendor", {}) or {}

    name      = filament.get("name", "Unbekannt")
    vendor_n  = vendor.get("name", "")
    material  = filament.get("material", "")
    color_hex = filament.get("color_hex", "")
    weight    = filament.get("weight", "")
    diameter  = filament.get("diameter", 1.75)
    temp_e    = filament.get("extruder_temp", "")
    temp_b    = filament.get("bed_temp", "")
    spool_id  = spool.get("id", "")
    remaining = spool.get("remaining_weight")

    # QR-Code mit Spoolman-URL für direkten Zugriff
    spoolman_url = f"http://192.168.130.123:7912/spoolman/spool/{spool_id}"

    lines = []
    lines.append(f"**{vendor_n}**" if vendor_n else "")
    lines.append(f"# {name}")
    if material:
        lines.append(f"**{material}** | ⌀{diameter}mm")
    if temp_e or temp_b:
        temps = []
        if temp_e: temps.append(f"E:{temp_e}°C")
        if temp_b: temps.append(f"B:{temp_b}°C")
        lines.append(" | ".join(temps))
    if remaining is not None:
        lines.append(f"Rest: {remaining:.0f}g / {weight}g" if weight else f"Rest: {remaining:.0f}g")
    elif weight:
        lines.append(f"{weight}g")
    if color_hex:
        lines.append(f"#{color_hex.upper()}")

    lines.append(f"ID: {spool_id}")

    return "\n".join(l for l in lines if l)


def build_qr_label(spool: dict) -> str:
    """Erstellt das QR-Label (nur QR-Code + Name)."""
    filament  = spool.get("filament", {})
    vendor    = filament.get("vendor", {}) or {}
    name      = filament.get("name", "Unbekannt")
    vendor_n  = vendor.get("name", "")
    spool_id  = spool.get("id", "")
    spoolman_url = f"http://192.168.130.123:7912/spoolman/spool/{spool_id}"

    lines = []
    lines.append(f"#qr#{spoolman_url}#qr#")
    lines.append(f"**{vendor_n}** {name}" if vendor_n else name)
    lines.append(f"ID: {spool_id}")
    return "\n".join(lines)


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <h2>🏷️ Spoolman Label Service</h2>
    <p>Webhook-Endpoint: <code>POST /webhook/spool</code></p>
    <p>Manuell drucken: <code>POST /print/{spool_id}</code></p>
    <p>Vorschau: <code>GET /preview/{spool_id}</code></p>
    """

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/spool")
async def spoolman_webhook(request: Request):
    """Empfängt Spoolman Webhooks."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Kein gültiges JSON")

    event = data.get("event", "")
    spool = data.get("payload", {})

    log.info("Webhook: %s | Spool-ID: %s", event, spool.get("id"))

    # Nur bei neuer Spule oder explizitem Druck-Event
    if event in ("spool_added", "spool_label_print"):
        if AUTO_PRINT:
            await _do_print(spool)
            return {"status": "printed", "spool_id": spool.get("id")}
        else:
            log.info("AUTO_PRINT deaktiviert — kein Druck")
            return {"status": "received", "auto_print": False}

    return {"status": "ignored", "event": event}


@app.post("/print/{spool_id}")
async def print_label(spool_id: int):
    """Label für eine Spule manuell drucken."""
    # Spool-Daten von Spoolman holen
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://localhost:7912/api/v1/spool/{spool_id}")
        if resp.status_code != 200:
            raise HTTPException(404, f"Spule {spool_id} nicht gefunden")
        spool = resp.json()

    await _do_print(spool)
    return {"status": "printed", "spool_id": spool_id}


@app.get("/preview/{spool_id}")
async def preview_label(spool_id: int):
    """Label-Vorschau als Bild."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://localhost:7912/api/v1/spool/{spool_id}")
        if resp.status_code != 200:
            raise HTTPException(404, f"Spule {spool_id} nicht gefunden")
        spool = resp.json()

    label_text = build_label(spool)
    log.info("Preview für Spule %d", spool_id)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{PHOMEMO_API}/api/preview-text-with-codes",
            data={"text": label_text, "label_size": LABEL_SIZE, "immediate": "true"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise HTTPException(500, f"Phomemo Preview Fehler: {resp.text}")

    from fastapi.responses import Response
    return Response(content=resp.content, media_type="image/png")


@app.get("/spools")
async def list_spools():
    """Alle Spulen aus Spoolman — für manuelle Label-Auswahl."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:7912/api/v1/spool?limit=100")
    spools = resp.json()
    return [
        {
            "id": s["id"],
            "name": s["filament"]["name"],
            "vendor": (s["filament"].get("vendor") or {}).get("name", ""),
            "material": s["filament"].get("material", ""),
            "remaining_weight": s.get("remaining_weight"),
        }
        for s in spools
    ]


# ─── Interner Druck ───────────────────────────────────────────────────────────

async def _do_print(spool: dict):
    """Druckt 2 Labels: 1x Textinfo, 1x QR-Code."""
    label_text = build_label(spool)
    qr_text    = build_qr_label(spool)
    log.info("Drucke 2 Labels für Spule %s", spool.get("id"))

    async with httpx.AsyncClient() as client:
        # Label 1: Textinfos
        r1 = await client.post(
            f"{PHOMEMO_API}/api/print-text-with-codes",
            data={"text": label_text, "label_size": LABEL_SIZE, "immediate": "true"},
            timeout=30,
        )
        if r1.status_code == 200:
            log.info("✅ Label 1 (Text) gedruckt")
        else:
            log.error("❌ Label 1 Fehler: %s", r1.text)

        # Label 2: QR-Code
        await asyncio.sleep(2)  # kurze Pause zwischen den Labels
        r2 = await client.post(
            f"{PHOMEMO_API}/api/print-text-with-codes",
            data={"text": qr_text, "label_size": LABEL_SIZE, "immediate": "true"},
            timeout=30,
        )
        if r2.status_code == 200:
            log.info("✅ Label 2 (QR) gedruckt")
        else:
            log.error("❌ Label 2 Fehler: %s", r2.text)

    return r2


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7913)

# ─── Spool Watcher (Auto-Print neue Spulen) ───────────────────────────────────

_known_spool_ids: set[int] = set()
KNOWN_IDS_FILE = "/home/pi/.spoolman_known_ids.json"


def _load_known_ids():
    """Lädt persistent gespeicherte Spulen-IDs."""
    import json
    try:
        with open(KNOWN_IDS_FILE) as f:
            ids = json.load(f)
            _known_spool_ids.update(ids)
            log.info("Gespeicherte IDs geladen: %d Spulen bekannt", len(_known_spool_ids))
    except FileNotFoundError:
        log.info("Keine gespeicherten IDs gefunden — hole von Spoolman")


def _save_known_ids():
    """Speichert bekannte IDs persistent."""
    import json
    with open(KNOWN_IDS_FILE, "w") as f:
        json.dump(list(_known_spool_ids), f)


async def _init_known_spools():
    """Beim Start: erst Datei laden, dann Spoolman abfragen."""
    # Zuerst gespeicherte IDs laden (überlebt Neustarts)
    _load_known_ids()

    # Dann aktuell vorhandene Spulen als bekannt markieren
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:7912/api/v1/spool?limit=1000")
            spools = r.json()
            for s in spools:
                _known_spool_ids.add(s["id"])
        _save_known_ids()
        log.info("Spool-Watcher initialisiert: %d bekannte Spulen", len(_known_spool_ids))
    except Exception as e:
        log.warning("Spool-Watcher Init fehlgeschlagen: %s", e)


async def _watch_spools():
    """Pollt Spoolman alle 10s auf neue Spulen und druckt automatisch Labels."""
    await _init_known_spools()
    while True:
        await asyncio.sleep(10)
        if not AUTO_PRINT:
            continue
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get("http://localhost:7912/api/v1/spool?limit=1000")
                spools = r.json()
            for s in spools:
                if s["id"] not in _known_spool_ids:
                    _known_spool_ids.add(s["id"])
                    log.info("🆕 Neue Spule erkannt: ID %d — %s", s["id"], s["filament"]["name"])
                    _save_known_ids()
                    await _do_print(s)
        except Exception as e:
            log.warning("Spool-Watcher Fehler: %s", e)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_watch_spools())
    log.info("Spool-Watcher gestartet (AUTO_PRINT=%s)", AUTO_PRINT)

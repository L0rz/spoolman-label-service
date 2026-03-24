# 🏷️ Spoolman Label Service (Phomemo M110)

Automatischer Label-Druck für neue Filamentspulen via Phomemo M110.

## Was es macht

Sobald eine neue Spule in Spoolman eingetragen wird, druckt der Phomemo M110 automatisch **2 Labels**:
- **Label 1:** Textinfo (Hersteller, Name, Material, Temperaturen, Restgewicht, Farbcode, ID)
- **Label 2:** QR-Code (verlinkt direkt zur Spule in Spoolman) + Kurzname

## Infrastruktur

| Komponente | Host | Port |
|---|---|---|
| Spoolman | 192.168.130.123 (klipper) | 7912 |
| Label Service | 192.168.130.123 (klipper) | 7913 |
| Phomemo M110 API | 192.168.130.138 (printer01) | 8080 |

## Installation

```bash
# Auf dem Klipper-Pi
cp spoolman-label-service.py /home/pi/
sudo cp spoolman-labels.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable spoolman-labels
sudo systemctl start spoolman-labels
```

## Konfiguration

In `/etc/systemd/system/spoolman-labels.service`:

```ini
Environment=PHOMEMO_API=http://192.168.130.138:8080
Environment=LABEL_SIZE=40x30
Environment=AUTO_PRINT=true   # false = nur manuell
```

## API Endpoints

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/health` | GET | Health Check |
| `/spools` | GET | Alle Spulen auflisten |
| `/print/{id}` | POST | Label manuell drucken |
| `/preview/{id}` | GET | Vorschau als PNG |
| `/webhook/spool` | POST | Webhook-Empfänger |

## Manuell drucken

```bash
# Spule ID 5 drucken
curl -X POST http://192.168.130.123:7913/print/5

# Vorschau
curl http://192.168.130.123:7913/preview/5 -o preview.png

# Alle Spulen anzeigen
curl http://192.168.130.123:7913/spools
```

## Service verwalten

```bash
sudo systemctl status spoolman-labels
sudo systemctl restart spoolman-labels
sudo journalctl -u spoolman-labels -f
```

## Troubleshooting

| Problem | Lösung |
|---|---|
| Kein Druck bei neuer Spule | AUTO_PRINT=true prüfen, Service neu starten |
| Phomemo antwortet nicht | `curl http://192.168.130.138:8080/api/status` |
| Job failed in Queue | `immediate=true` ist gesetzt — kein Queue-Problem mehr |
| QR-Code abgeschnitten | QR ist auf eigenem Label (Label 2), sollte nicht vorkommen |

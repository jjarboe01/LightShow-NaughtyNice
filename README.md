# 🎄 LightShow-NaughtyNice

An interactive Christmas light show display where parents submit their child's name and a photo, and the result is shown live on a P5 LED matrix — complete with a "breaking news" overlay announcing whether they made the **Nice** or **Naughty** list.

---

## Architecture Overview

```
Internet / Kiosk Browser
        │  HTTP
        ▼
 ┌─────────────────┐
 │  F5 BIG-IP ASM  │  WAF policy, rate limiting, URL allowlist
 └────────┬────────┘
          │  HTTP (pool member)
          ▼
 ┌─────────────────┐
 │  nginx (Docker) │  Static file serving, reverse proxy, 6 MB body limit
 └────────┬────────┘
          │  HTTP :8000
          ▼
 ┌─────────────────┐
 │ Flask/Gunicorn  │  Form handling, image processing, FPP API calls
 │    (Docker)     │
 └────────┬────────┘
          │  REST API (HTTP, internal VLAN)
          ▼
 ┌─────────────────┐
 │ Falcon Player   │  Raspberry Pi 5 — sequence playback + pixel overlays
 │   (Pi 5)        │
 └────────┬────────┘
          │  HUB75
          ▼
 ┌─────────────────┐
 │  P5 LED Matrix  │  3×6 panels — 192 × 192 px total
 └─────────────────┘
```

### Network Layout

| Network | Subnet | Hosts |
|---|---|---|
| Lab LAN (VLAN 100) | `192.168.1.0/24` | Proxmox host, Docker VM |
| LightShow (VLAN 200) | `192.168.200.0/24` | Pi 5 at `.10` (alt `.11`) |

Inter-VLAN routing is handled by the firewall. The Docker container calls FPP at `192.168.200.10:80` server-side — no inbound access from VLAN 200 is required.

---

## Hardware

| Component | Details |
|---|---|
| Controller | Raspberry Pi 5 running Falcon Player (FPP) |
| Panels | P5 HUB75 LED panels, 64 × 32 px each |
| Layout | 3 panels wide × 6 panels tall |
| Total resolution | **192 × 192 px** |
| Display zones | PhotoZone: 192 × 140 px (top) · TickerZone: 192 × 52 px (bottom) |

---

## How It Works

1. A parent opens the web form (served via Docker → nginx → F5 ASM).
2. They enter their child's name, select Boy/Girl and Nice/Naughty, and optionally upload a photo.
3. Flask validates and processes the submission:
   - If a photo is uploaded it is resized/cropped to 192 × 140 px.
   - If no photo, a boy or girl silhouette is used instead.
4. Three FPP API calls are made in sequence:
   - **Break-in playlist** — triggers the `breaking_news` playlist via `startNow` (FPP returns to the main show when it finishes).
   - **Photo overlay** — pushes RGBA pixel data to the `PhotoZone` overlay model.
   - **Ticker text** — fires the FPP `Scrolling Text` effect on `TickerZone` with the child's name and Nice/Naughty status (green text for Nice, red for Naughty).
5. The browser redirects to a thank-you page confirming the submission.

---

## Project Structure

```
LightShow-NaughtyNice/
├── app/
│   ├── app.py               # Flask routes: /, /submit, /thanks, /health
│   ├── config.py            # All config via environment variables
│   ├── fpp_client.py        # FPP REST API client (playlist, overlays, ticker)
│   ├── image_processor.py   # Resize/crop upload or fall back to silhouette
│   ├── static/
│   │   ├── style.css
│   │   └── silhouettes/
│   │       ├── boy.png      # 192×140 px fallback silhouette
│   │       └── girl.png
│   └── templates/
│       ├── form.html        # Submission form
│       └── thanks.html      # Confirmation page
├── nginx/
│   └── default.conf         # Reverse proxy + static file config
├── assets/
│   └── breaking_news_bg.png # Background image for the breaking news sequence
├── docs/
│   ├── fpp_setup.md         # FPP channel output, overlay models, playlist setup
│   └── f5_asm_checklist.md  # F5 BIG-IP ASM policy configuration guide
├── Dockerfile               # Python 3.12-alpine + Pillow + gunicorn
├── docker-compose.yml       # web (gunicorn) + nginx services
├── requirements.txt
└── .env.example             # Template for all required environment variables
```

---

## Quick Start

### Prerequisites

- Docker + Docker Compose on the host VM
- Falcon Player running on the Pi 5 with overlay models and playlist configured (see [`docs/fpp_setup.md`](docs/fpp_setup.md))
- F5 BIG-IP ASM policy applied (see [`docs/f5_asm_checklist.md`](docs/f5_asm_checklist.md)) — or bypass F5 for local testing

### 1. Clone and configure

```bash
git clone https://github.com/jjarboe01/LightShow-NaughtyNice.git
cd LightShow-NaughtyNice
cp .env.example .env
# Edit .env — set FPP_HOST and SECRET_KEY at minimum
```

### 2. Build and start

```bash
docker compose up -d --build
```

### 3. Verify

```bash
# App health check (also checks FPP reachability)
curl http://localhost/health
# Expected: {"status":"ok","fpp":true}

# Open in browser
open http://localhost
```

### 4. Tail logs

```bash
docker compose logs -f web
```

---

## Environment Variables

Copy `.env.example` to `.env` and set these values before running:

| Variable | Default | Description |
|---|---|---|
| `FPP_HOST` | `192.168.200.10` | IP address of the Falcon Player Pi |
| `FPP_PORT` | `80` | FPP web UI / REST API port |
| `FPP_TIMEOUT` | `5` | Seconds before FPP API calls time out |
| `FPP_PHOTO_MODEL` | `PhotoZone` | FPP overlay model name for the photo area |
| `FPP_TICKER_MODEL` | `TickerZone` | FPP overlay model name for the scrolling text |
| `FPP_BASE_PLAYLIST` | `breaking_news` | FPP playlist triggered on each submission |
| `SECRET_KEY` | *(required)* | Flask session secret — set a long random string |
| `UPLOAD_MAX_BYTES` | `5242880` | Max photo upload size (5 MB) |
| `MATRIX_WIDTH` | `192` | Total matrix width in pixels |
| `MATRIX_HEIGHT` | `192` | Total matrix height in pixels |
| `PHOTO_ZONE_HEIGHT` | `140` | Height of the photo display zone |
| `TICKER_ZONE_HEIGHT` | `52` | Height of the scrolling text zone |

---

## FPP Setup Summary

Full details in [`docs/fpp_setup.md`](docs/fpp_setup.md). Key steps:

1. **Channel Output** — configure HUB75 for 3×6 panels (192×192 px, 110,592 channels total).
2. **Overlay Models** — create `PhotoZone` (192×140) and `TickerZone` (192×52) in FPP's Pixel Overlay Manager. Enable both.
3. **Playlist** — create a playlist named exactly `breaking_news`. **Do not set it to loop** — it must finish and hand control back to the main show.
4. **Silhouettes** — place `boy.png` and `girl.png` (192×140 px) in `app/static/silhouettes/`.

---

## F5 ASM Policy Summary

Full details in [`docs/f5_asm_checklist.md`](docs/f5_asm_checklist.md). Key settings:

- Allowed URLs: `GET /`, `POST /submit`, `GET /thanks`, `GET /health`, `GET /static/*` — block everything else.
- Max request body on `/submit`: **6 MB** (photo uploads).
- Allowed upload file types: `jpg`, `jpeg`, `png`.
- Rate limit `/submit` to ~10 req/min/IP to prevent form spam.
- Point the BIG-IP health monitor at `GET /health` — returns `503` when FPP is unreachable so F5 can pull the pool member.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Submission form |
| `POST` | `/submit` | Process submission, push to FPP, redirect to `/thanks` |
| `GET` | `/thanks` | Confirmation page (`?name=&status=`) |
| `GET` | `/health` | JSON health check — `200` if FPP reachable, `503` if not |

---

## Development Notes

- The Flask app talks to FPP **server-side** — the browser never touches FPP directly.
- FPP API failures are logged but do **not** surface an error to the user (the thank-you page still shows).
- The `upload_tmp` Docker volume is ephemeral — uploaded photos are deleted immediately after the FPP overlay is pushed.
- To run without Docker for local dev: `pip install -r requirements.txt && python app/app.py` (set env vars first).

---

## License

Personal/hobbyist project — no license applied.

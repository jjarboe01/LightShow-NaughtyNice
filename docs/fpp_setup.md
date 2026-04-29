# FPP Setup Checklist — Pi 5 / P5 Matrix

## Network topology

```
192.168.1.0/24   — Lab LAN (Proxmox, Docker host)
192.168.200.0/24 — Light show VLAN (Pi 5, panels, controllers)
                   Pi is 192.168.200.10 (alt .11)
```

**Routing is handled by the firewall — no additional VM or container config needed.**
HomeNet (VLAN100, 192.168.1.0/24) routes to LightShowNet (VLAN200, 192.168.200.0/24)
through the firewall. The Proxmox VM sits on VLAN100 and can reach the Pi at
192.168.200.10 (or .11) via that inter-VLAN route.

Ensure the firewall permits:
- Source: Proxmox VM IP (192.168.1.x) → Destination: 192.168.200.10, TCP port 80
- No return rule needed beyond stateful tracking (firewall handles it)

No inbound access from LightShowNet back into HomeNet is required by this app.

---


## Matrix facts
- Panel size: 64 × 32 px each
- Layout: 3 wide × 6 tall
- **Total resolution: 192 × 192 px**

---

## 1. Channel Output — HUB75 Matrix

In FPP: **Settings → Channel Outputs → Add Output → HUB75**

| Field | Value |
|---|---|
| Panel Width | 64 |
| Panel Height | 32 |
| Panels Wide | 3 |
| Panels Tall | 6 |
| Output Resolution | 192 × 192 |
| Zigzag / Snake | Match your physical wiring |
| Color Order | Match your panels (usually RGB) |

Set starting channel to 1.  Total channels = 192 × 192 × 3 = **110,592**.

---

## 2. Pixel Overlay Models

In FPP: **Content Setup → Pixel Overlay Models → Add Model**

### PhotoZone
| Field | Value |
|---|---|
| Name | `PhotoZone` |
| Type | Matrix |
| Start Channel | 1 |
| Width | 192 |
| Height | 140 |
| Pixels | 26,880 |
| Channel Count | 80,640 |

### TickerZone
| Field | Value |
|---|---|
| Name | `TickerZone` |
| Type | Matrix |
| Start Channel | 80,641 ← (192 × 140 × 3) + 1 |
| Width | 192 |
| Height | 52 |
| Pixels | 9,984 |
| Channel Count | 29,952 |

> **Note:** Starting channels assume sequential pixel ordering from the HUB75 output.
> Verify by using the "Test Mode" in FPP and checking which rows light up.

Enable both models: toggle the **Enabled** switch on each.

---

## 3. Base Playlist — `breaking_news`

In FPP: **Content Setup → Playlists → Add Playlist** — name it exactly `breaking_news`.

Suggested playlist content:
- A single FSEQ sequence long enough to display the photo + scrolling text
  (typically 15–30 seconds). Dark background with red/gold border; the pixel
  overlays fill in the photo and ticker text on top.
- Or a solid-colour "black" FSEQ if you want the overlay to be the only content.

**CRITICAL — do NOT set this playlist to loop.**
The Flask app triggers it via FPP's `startNow` (break-in) endpoint. When the
playlist finishes its single pass, FPP automatically returns to the master show
that was playing before the break-in. If the playlist is set to loop it will
never hand control back to the main show.

---

## 4. Scrolling Text Overlay Effect

The Flask app triggers FPP's built-in **Scrolling Text** effect on `TickerZone` via:
```
POST /api/command
{
  "command": "Overlay Model Effect",
  "args": {
    "Model":           "TickerZone",
    "Effect":          "Scrolling Text",
    "Enabled":         "true",
    "Color":           "#00FF00",   ← green for NICE, red for NAUGHTY
    "Text":            "  BREAKING: Emma is on the NICE LIST!  ",
    "Font":            "Helvetica",
    "FontSize":        "16",
    "PixelsPerSecond": "30",
    "Direction":       "R2L"
  }
}
```

Verify available fonts on your Pi with:
```bash
ls /usr/share/fonts/truetype/
```
Update `FPP_TICKER_FONT` in the Flask config if needed.

---

## 5. FPP API quick-test commands

From any host that can reach the Pi:

```bash
# Health check
curl http://<FPP_HOST>/api/status

# Break into current show with breaking_news (returns to show when done)
curl http://<FPP_HOST>/api/playlists/breaking_news/startNow

# Plain start (no break-in, use only for isolated testing when no show is running)
curl http://<FPP_HOST>/api/playlists/breaking_news/start

# List overlay models
curl http://<FPP_HOST>/api/overlays/models

# Enable PhotoZone
curl -X POST http://<FPP_HOST>/api/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"Overlay Model State","args":{"Model":"PhotoZone","State":"Enabled"}}'
```

---

## 6. Silhouette images

Place two silhouette PNG files in `app/static/silhouettes/`:
- `boy.png`  — 192 × 140 px, transparent or dark background
- `girl.png` — 192 × 140 px, transparent or dark background

These are used when a parent does not upload a photo.

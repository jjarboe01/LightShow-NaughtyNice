"""
FPP REST API client — FPP 9.x compatible.

Handles all communication between the Flask app and Falcon Player on the Pi 5.
FPP API docs: http://<fpp-host>/api/help

Changes vs original (FPP 6.x assumptions):
- Playlist start: GET /api/playlist/{name}/start  (singular; /playlists/ plural → 404)
- Command API: args must be an ARRAY, not a dict
- Photo display: composite PIL image onto background, upload via /jqUpload → Image playlist entry
- Ticker text: "Text" effect (not "Scrolling Text"), correct field names
"""

import io
import logging
import os
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

_DISPLAY_FILENAME = "current_display.png"

# Breaking news overlay dimensions (PhotoZone is 192×140)
_HEADER_H   = 20   # red "BREAKING NEWS" bar at top
_LOWER_Y    = 118  # y-start of lower third chyron
_LOWER_H    = 22   # height of lower third (118–139)
_BADGE_X    = 122  # x-start of NICE/NAUGHTY status badge in lower third

_COLOR_RED      = (204,   0,   0)
_COLOR_NAVY     = (  0,  20,  90)
_COLOR_NICE     = (  0, 160,  40)
_COLOR_NAUGHTY  = (200,   0,   0)
_COLOR_WHITE    = (255, 255, 255)

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for base in ("/usr/share/fonts/truetype/dejavu",
                 "/usr/share/fonts/dejavu",
                 "/usr/share/fonts/TTF"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_text_centered(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                        x0: int, y0: int, x1: int, y1: int, color: tuple) -> None:
    """Draw text centered inside the rectangle (x0,y0)–(x1,y1)."""
    bb = font.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = x0 + ((x1 - x0) - tw) // 2
    y = y0 + ((y1 - y0) - th) // 2
    draw.text((x, y), text, fill=color, font=font)


class FPPClient:
    def __init__(self, base_url: str, photo_model: str, ticker_model: str,
                 playlist: str, timeout: int = 5):
        self.base_url     = base_url.rstrip("/")
        self.photo_model  = photo_model   # kept for compat; no longer used for pixel push
        self.ticker_model = ticker_model
        self.playlist     = playlist
        self.timeout      = timeout

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    def is_alive(self) -> bool:
        """Quick health check against FPP /api/status."""
        try:
            r = requests.get(f"{self.base_url}/api/status", timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException as exc:
            log.warning("FPP health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Playlist control
    # ------------------------------------------------------------------

    def break_in_playlist(self, name: Optional[str] = None) -> bool:
        """
        Start the named playlist on FPP.

        On a Remote-mode instance this breaks in from whatever is currently
        synced and playing; FPP resumes normal sync when the playlist ends.

        FPP 9.x: GET /api/playlist/{name}/start  (SINGULAR — /api/playlists/ is list-only)
        """
        target = name or self.playlist
        url = f"{self.base_url}/api/playlist/{target}/start"
        try:
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200:
                log.info("Started FPP playlist: %s", target)
                return True
            log.error("break_in_playlist %s -> HTTP %s: %s", target, r.status_code, r.text[:200])
            return False
        except requests.RequestException as exc:
            log.error("break_in_playlist exception: %s", exc)
            return False

    def stop_playlist(self) -> bool:
        """Gracefully stop whatever is currently playing."""
        try:
            r = requests.get(f"{self.base_url}/api/playlists/stop", timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Photo: composite onto background and upload to FPP images dir
    # ------------------------------------------------------------------

    def push_photo_overlay(self, photo: Image.Image,
                           child_name: str, status: str) -> bool:
        """
        Composite the photo onto a 192×192 canvas with breaking-news overlays,
        then upload to FPP as 'current_display.png'.

        Overlay layout (PhotoZone = top 192×140; TickerZone owns rows 140–191):
          rows  0–19  : red "BREAKING NEWS" header bar
          rows 20–117 : photo (visible between header and lower third)
          rows 118–139: lower third chyron — name left, NICE/NAUGHTY badge right
          rows 140–191: black (TickerZone overlay handles these)

        photo     : PIL Image (RGBA, 192×140) from image_processor.
        child_name: submitted child name for lower third chyron.
        status    : "nice" or "naughty" — controls badge color.
        """
        try:
            # 192×192 black canvas
            canvas = Image.new("RGB", (192, 192), (0, 0, 0))

            # Paste photo as base layer (fills rows 0–139)
            canvas.paste(photo.convert("RGB"), (0, 0))

            draw = ImageDraw.Draw(canvas)

            # ── Header bar (rows 0–19) ──────────────────────────────────────
            draw.rectangle([(0, 0), (191, _HEADER_H - 1)], fill=_COLOR_RED)
            # Small white accent bar on left edge
            draw.rectangle([(0, 0), (3, _HEADER_H - 1)], fill=_COLOR_WHITE)
            font_header = _get_font(11, bold=True)
            _draw_text_centered(draw, "BREAKING NEWS", font_header,
                                6, 0, 191, _HEADER_H, _COLOR_WHITE)

            # ── Lower third chyron (rows 118–139) ──────────────────────────
            draw.rectangle([(0, _LOWER_Y), (191, _LOWER_Y + _LOWER_H - 1)],
                           fill=_COLOR_NAVY)

            # Status badge (right side)
            badge_color = _COLOR_NICE if status == "nice" else _COLOR_NAUGHTY
            draw.rectangle([(_BADGE_X, _LOWER_Y), (191, _LOWER_Y + _LOWER_H - 1)],
                           fill=badge_color)

            # Child name (left side, truncated to fit)
            font_name   = _get_font(10)
            font_status = _get_font(10, bold=True)

            name_display = child_name.upper()
            # Truncate if name is too wide for the left panel
            while font_name.getbbox(name_display)[2] > (_BADGE_X - 8) and len(name_display) > 1:
                name_display = name_display[:-1]

            draw.text((4, _LOWER_Y + 5), name_display,
                      fill=_COLOR_WHITE, font=font_name)

            status_text = "NICE" if status == "nice" else "NAUGHTY"
            _draw_text_centered(draw, status_text, font_status,
                                _BADGE_X, _LOWER_Y, 191, _LOWER_Y + _LOWER_H,
                                _COLOR_WHITE)

            # Encode to PNG bytes
            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            buf.seek(0)
        except Exception as exc:
            log.error("push_photo_overlay image processing error: %s", exc)
            return False

        # Upload via FPP REST API: POST /api/file/images/{filename} with raw PNG body.
        # MapExtention(.png) → images directory → /home/fpp/media/images/
        url = f"{self.base_url}/api/file/images/{_DISPLAY_FILENAME}"
        try:
            r = requests.post(
                url,
                data=buf.read(),
                headers={"Content-Type": "image/png"},
                timeout=max(self.timeout, 15),
            )
            if r.status_code in (200, 204):
                log.info("Uploaded %s to FPP", _DISPLAY_FILENAME)
                return True
            log.error("push_photo_overlay upload -> HTTP %s: %s", r.status_code, r.text[:200])
            return False
        except requests.RequestException as exc:
            log.error("push_photo_overlay upload exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Ticker text via Overlay Model Effect
    # ------------------------------------------------------------------

    def push_ticker_text(self, child_name: str, status: str) -> bool:
        """
        Trigger FPP's built-in 'Text' overlay effect on TickerZone.

        FPP 9.x command API: args MUST be an array (not a dict).

        "Overlay Model Effect" / "Text" array arg order:
          [Models, AutoEnable, Effect, Color, Font, FontSize,
           FontAntiAlias, Position, Speed, Duration, Text]
        """
        label   = status.upper()           # NICE or NAUGHTY
        color   = "#00FF00" if status == "nice" else "#FF0000"
        message = f"  BREAKING: {child_name} is on the {label} LIST!  "

        payload = {
            "command": "Overlay Model Effect",
            "args": [
                self.ticker_model,  # Models
                "Enabled",          # AutoEnable
                "Text",             # Effect  (NOT "Scrolling Text")
                color,              # Color
                "DejaVuSans",       # Font  (Helvetica has no font file on Pi; DejaVuSans does)
                "16",               # FontSize
                "false",            # FontAntiAlias
                "Right to Left",    # Position
                "30",               # Speed  (NOT "PixelsPerSecond")
                "0",                # Duration (0 = run indefinitely)
                message,            # Text
            ],
        }
        try:
            r = requests.post(
                f"{self.base_url}/api/command",
                json=payload,
                timeout=self.timeout,
            )
            if r.status_code in (200, 204):
                log.info("Ticker text pushed: %s", message.strip())
                return True
            log.error("push_ticker_text -> HTTP %s: %s", r.status_code, r.text[:200])
            return False
        except requests.RequestException as exc:
            log.error("push_ticker_text exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Overlay enable / disable  (used for TickerZone if needed standalone)
    # ------------------------------------------------------------------

    def enable_overlay(self, model_name: str) -> bool:
        return self._set_overlay_state(model_name, "Enabled")

    def disable_overlay(self, model_name: str) -> bool:
        return self._set_overlay_state(model_name, "Disabled")

    def _set_overlay_state(self, model_name: str, state: str) -> bool:
        """
        FPP 9.x: command API args must be an array, not a dict.
        e.g. {"command": "Overlay Model State", "args": ["TickerZone", "Enabled"]}
        """
        payload = {
            "command": "Overlay Model State",
            "args": [model_name, state],   # array — NOT {"Model": ..., "State": ...}
        }
        try:
            r = requests.post(
                f"{self.base_url}/api/command",
                json=payload,
                timeout=self.timeout,
            )
            return r.status_code in (200, 204)
        except requests.RequestException as exc:
            log.error("_set_overlay_state exception: %s", exc)
            return False

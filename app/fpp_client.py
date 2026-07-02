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
from PIL import Image

log = logging.getLogger(__name__)

# Background image path inside container: /app/static/breaking_news_bg.png
_BG_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "static", "breaking_news_bg.png")
_DISPLAY_FILENAME = "current_display.png"


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

    def push_photo_overlay(self, photo: Image.Image) -> bool:
        """
        Composite the photo zone image onto the full-matrix background, then
        upload the result to FPP as 'current_display.png'.

        The breaking_news playlist's Image entry references this filename from
        /home/fpp/media/images/ — FPP's /jqUpload endpoint moves uploaded PNGs
        there automatically.

        photo: PIL Image (RGBA, MATRIX_WIDTH × PHOTO_ZONE_HEIGHT) from image_processor.
        """
        # Load 192×192 background
        try:
            bg = Image.open(_BG_IMAGE_PATH).convert("RGBA")
        except Exception as exc:
            log.error("Could not load background image %s: %s", _BG_IMAGE_PATH, exc)
            return False

        try:
            # Paste photo (192×140) onto the top of the background at (0, 0)
            photo_rgba = photo.convert("RGBA")
            bg.paste(photo_rgba, (0, 0), photo_rgba)

            # Encode to PNG bytes (convert to RGB — LED matrix has no alpha)
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, format="PNG")
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

"""
FPP REST API client.

Handles all communication between the Flask app and Falcon Player running
on the Pi 5.  FPP API docs: http://<fpp-host>/api/help

Key overlay model names and the sequence name must be configured in FPP
before this client is called -- see docs/fpp_setup.md.
"""

import base64
import logging
from typing import Optional

import requests
from PIL import Image
import io

log = logging.getLogger(__name__)


class FPPClient:
    def __init__(self, base_url: str, photo_model: str, ticker_model: str,
                 playlist: str, timeout: int = 5):
        self.base_url    = base_url.rstrip("/")
        self.photo_model = photo_model
        self.ticker_model = ticker_model
        self.playlist    = playlist
        self.timeout     = timeout

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
        Interrupt whatever FPP is currently playing and immediately start
        the named playlist.  When the playlist finishes, FPP returns to
        whatever was playing before (the main show sequence).

        Uses /api/playlists/{name}/startNow which is the FPP 6.x break-in
        endpoint.  Falls back to a regular /start if startNow returns 404
        (older FPP builds).
        """
        target = name or self.playlist

        # Try break-in endpoint first
        url = f"{self.base_url}/api/playlists/{target}/startNow"
        try:
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200:
                log.info("Break-in started FPP playlist: %s", target)
                return True
            if r.status_code == 404:
                log.warning("startNow not found, falling back to /start for %s", target)
                return self._start_playlist_basic(target)
            log.error("break_in_playlist %s -> HTTP %s: %s", target, r.status_code, r.text)
            return False
        except requests.RequestException as exc:
            log.error("break_in_playlist exception: %s", exc)
            return False

    def _start_playlist_basic(self, name: str) -> bool:
        """Plain playlist start — used as fallback if startNow is unavailable."""
        url = f"{self.base_url}/api/playlists/{name}/start"
        try:
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200:
                log.info("Started (basic) FPP playlist: %s", name)
                return True
            log.error("_start_playlist_basic %s -> HTTP %s: %s", name, r.status_code, r.text)
            return False
        except requests.RequestException as exc:
            log.error("_start_playlist_basic exception: %s", exc)
            return False

    def stop_playlist(self) -> bool:
        """Gracefully stop whatever is currently playing."""
        try:
            r = requests.get(f"{self.base_url}/api/playlists/stop", timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Pixel overlay: photo zone
    # ------------------------------------------------------------------

    def push_photo_overlay(self, image: Image.Image) -> bool:
        """
        Push a PIL Image to the FPP 'PhotoZone' pixel overlay model.

        image should already be sized to exactly (MATRIX_WIDTH, PHOTO_ZONE_HEIGHT).
        FPP expects the pixel data as a base64-encoded RGBA byte string.
        """
        try:
            rgba = image.convert("RGBA")
            raw  = rgba.tobytes()            # width * height * 4 bytes
            b64  = base64.b64encode(raw).decode()

            payload = {"data": b64}
            url = f"{self.base_url}/api/overlays/models/{self.photo_model}/data"
            r   = requests.post(url, json=payload, timeout=self.timeout)

            if r.status_code in (200, 204):
                log.info("Photo overlay pushed to model '%s'", self.photo_model)
                return True
            log.error("push_photo_overlay -> HTTP %s: %s", r.status_code, r.text)
            return False
        except requests.RequestException as exc:
            log.error("push_photo_overlay exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Pixel overlay: ticker text
    # ------------------------------------------------------------------

    def push_ticker_text(self, child_name: str, status: str) -> bool:
        """
        Trigger FPP's built-in 'Scrolling Text' effect on the TickerZone
        overlay model with dynamic name + status text.

        status: 'nice' | 'naughty'
        """
        label   = status.upper()          # NICE or NAUGHTY
        color   = "#00FF00" if status == "nice" else "#FF0000"
        message = f"  BREAKING: {child_name} is on the {label} LIST!  "

        payload = {
            "command": "Overlay Model Effect",
            "args": {
                "Model":           self.ticker_model,
                "Effect":          "Scrolling Text",
                "Enabled":         "true",
                "Color":           color,
                "Text":            message,
                "Font":            "Helvetica",       # font available on Pi
                "FontSize":        "16",
                "PixelsPerSecond": "30",
                "Direction":       "R2L",             # right-to-left scroll
                "Position":        "Centered",
                "Antialiased":     "false",
            }
        }
        try:
            url = f"{self.base_url}/api/command"
            r   = requests.post(url, json=payload, timeout=self.timeout)
            if r.status_code in (200, 204):
                log.info("Ticker text pushed: %s", message.strip())
                return True
            log.error("push_ticker_text -> HTTP %s: %s", r.status_code, r.text)
            return False
        except requests.RequestException as exc:
            log.error("push_ticker_text exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Overlay enable / disable
    # ------------------------------------------------------------------

    def enable_overlay(self, model_name: str) -> bool:
        return self._set_overlay_state(model_name, "Enabled")

    def disable_overlay(self, model_name: str) -> bool:
        return self._set_overlay_state(model_name, "Disabled")

    def _set_overlay_state(self, model_name: str, state: str) -> bool:
        payload = {
            "command": "Overlay Model State",
            "args": {"Model": model_name, "State": state}
        }
        try:
            r = requests.post(f"{self.base_url}/api/command",
                              json=payload, timeout=self.timeout)
            return r.status_code in (200, 204)
        except requests.RequestException as exc:
            log.error("_set_overlay_state exception: %s", exc)
            return False

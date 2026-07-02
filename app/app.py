"""
LightShow-NaughtyNice  — Flask entry point.

Route summary:
  GET  /          → submission form
  POST /submit    → process form, push to FPP, redirect to /thanks
  GET  /thanks    → confirmation page
  GET  /health    → JSON health check (for F5 / Docker healthcheck)
"""

import os
import uuid
import logging
import threading
import time
from pathlib import Path

from flask import Flask, request, render_template, redirect, url_for, jsonify, flash
from werkzeug.utils import secure_filename

from config import Config
from content_filter import contains_profanity
from fpp_client import FPPClient
from image_processor import prepare_display_image

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Create upload dir if it doesn't exist
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

# FPP client singleton
fpp = FPPClient(
    base_url      = Config.FPP_BASE_URL,
    photo_model   = Config.FPP_PHOTO_MODEL,
    ticker_model  = Config.FPP_TICKER_MODEL,
    playlist      = Config.FPP_BASE_PLAYLIST,
    timeout       = Config.FPP_TIMEOUT,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext in app.config["ALLOWED_EXTENSIONS"]


def save_upload(file_storage) -> str | None:
    """Validate and save an uploaded file; return the saved path or None."""
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        log.warning("Rejected file with disallowed extension: %s", file_storage.filename)
        return None

    # Check size via stream without reading whole file into memory
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > app.config["UPLOAD_MAX_BYTES"]:
        log.warning("Rejected oversized upload: %d bytes", size)
        return None

    stem    = secure_filename(file_storage.filename)
    unique  = f"{uuid.uuid4().hex}_{stem}"
    path    = os.path.join(app.config["UPLOAD_FOLDER"], unique)
    file_storage.save(path)
    log.info("Saved upload: %s (%d bytes)", path, size)
    return path


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    fpp_ok = fpp.is_alive()
    status = "ok" if fpp_ok else "fpp_unreachable"
    code   = 200 if fpp_ok else 503
    return jsonify({"status": status, "fpp": fpp_ok}), code


@app.get("/")
def index():
    return render_template("form.html")


@app.post("/submit")
def submit():
    # --- Collect & validate form fields ---
    child_name = request.form.get("child_name", "").strip()
    gender     = request.form.get("gender", "").strip().lower()
    status     = request.form.get("status", "").strip().lower()

    errors = []
    if not child_name:
        errors.append("Child's name is required.")
    if len(child_name) > 40:
        errors.append("Name must be 40 characters or fewer.")
    if child_name and contains_profanity(child_name):
        errors.append("Please enter an appropriate name.")
    if gender not in ("boy", "girl"):
        errors.append("Please select Boy or Girl.")
    if status not in ("nice", "naughty"):
        errors.append("Please select Nice or Naughty.")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("form.html"), 422

    # --- Handle optional photo ---
    upload_path = None
    photo_file  = request.files.get("photo")
    if photo_file and photo_file.filename:
        upload_path = save_upload(photo_file)
        if upload_path is None:
            flash("Photo could not be accepted (wrong type or too large). "
                  "We'll use a silhouette instead.", "warning")

    # --- Prepare display image ---
    display_img = prepare_display_image(
        upload_path = upload_path,
        gender      = gender,
        target_w    = Config.MATRIX_WIDTH,
        target_h    = Config.PHOTO_ZONE_HEIGHT,
    )

    # --- Push to FPP ---
    fpp_ok = True

    # 1. Composite photo onto background and upload to FPP *before* starting
    #    the playlist, so current_display.png is ready when FPP reads it.
    if not fpp.push_photo_overlay(display_img, child_name, status):
        log.error("Could not upload photo image to FPP")
        fpp_ok = False

    # 2. Break into the current show and play the "breaking news" playlist.
    #    The Image entry in that playlist displays current_display.png on P5Large.
    #    FPP returns to the main show sequence when the playlist finishes.
    if not fpp.break_in_playlist():
        log.error("Could not break-in FPP playlist '%s'", Config.FPP_BASE_PLAYLIST)
        fpp_ok = False

    # 3. Start scrolling ticker text after a short delay so it syncs with the
    #    image appearing on the matrix (show_display_image.py has a 3s startup
    #    delay to let the upload settle before reading the file).
    def _deferred_ticker():
        time.sleep(3)
        if not fpp.push_ticker_text(child_name, status):
            log.error("Deferred ticker text push failed for %s", child_name)

    threading.Thread(target=_deferred_ticker, daemon=True).start()

    # --- Clean up temp upload ---
    if upload_path:
        try:
            os.unlink(upload_path)
        except OSError:
            pass

    if not fpp_ok:
        # Don't surface FPP failures to the public — log and continue
        log.warning("One or more FPP calls failed for submission: %s / %s / %s",
                    child_name, gender, status)

    return redirect(url_for("thanks",
                            name=child_name,
                            status=status))


@app.get("/thanks")
def thanks():
    name   = request.args.get("name", "")
    status = request.args.get("status", "nice")
    return render_template("thanks.html", name=name, status=status)


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

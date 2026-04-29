"""
Image processing for the photo/silhouette overlay zone.

Takes a raw uploaded file (or None) and returns a PIL Image sized to
exactly (MATRIX_WIDTH × PHOTO_ZONE_HEIGHT) ready to push to FPP.

Silhouette PNGs live in static/silhouettes/boy.png and girl.png.
They should be pre-sized to (MATRIX_WIDTH × PHOTO_ZONE_HEIGHT) or
will be resized to fit here.
"""

import os
import logging
from typing import Optional

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

SILHOUETTE_DIR = os.path.join(os.path.dirname(__file__), "static", "silhouettes")


def prepare_display_image(
    upload_path: Optional[str],
    gender: str,          # 'boy' | 'girl'
    target_w: int,
    target_h: int,
) -> Image.Image:
    """
    Return a PIL Image (RGBA, target_w × target_h) for the photo zone.

    If upload_path is provided and valid: resize/crop the uploaded photo.
    Otherwise fall back to the appropriate silhouette.
    """
    img: Optional[Image.Image] = None

    if upload_path:
        try:
            img = Image.open(upload_path)
            log.info("Loaded uploaded photo: %s", upload_path)
        except Exception as exc:
            log.warning("Could not open uploaded photo (%s), falling back to silhouette", exc)
            img = None

    if img is None:
        img = _load_silhouette(gender, target_w, target_h)

    return _fit_to_zone(img, target_w, target_h)


def _load_silhouette(gender: str, fallback_w: int, fallback_h: int) -> Image.Image:
    """Load the boy or girl silhouette PNG, creating a placeholder if missing."""
    filename = "boy.png" if gender == "boy" else "girl.png"
    path = os.path.join(SILHOUETTE_DIR, filename)

    if os.path.exists(path):
        try:
            return Image.open(path)
        except Exception as exc:
            log.error("Failed to load silhouette %s: %s", path, exc)

    # Absolute last resort: solid coloured placeholder
    log.warning("Silhouette file not found: %s — using placeholder", path)
    color = (30, 60, 200, 255) if gender == "boy" else (200, 30, 120, 255)
    return Image.new("RGBA", (fallback_w, fallback_h), color)


def _fit_to_zone(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Scale the image to fill the target zone while preserving aspect ratio,
    then centre-crop to exact dimensions.  Returns RGBA.
    """
    img = img.convert("RGBA")
    img = ImageOps.fit(img, (target_w, target_h), method=Image.LANCZOS)
    return img

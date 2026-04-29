import os

class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "changeme-in-production")

    # File upload
    UPLOAD_FOLDER = "/app/uploads"
    UPLOAD_MAX_BYTES = int(os.environ.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024))  # 5 MB
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

    # FPP connection
    FPP_HOST = os.environ.get("FPP_HOST", "192.168.1.100")
    FPP_PORT = int(os.environ.get("FPP_PORT", 80))
    FPP_BASE_URL = f"http://{FPP_HOST}:{FPP_PORT}"
    FPP_TIMEOUT = int(os.environ.get("FPP_TIMEOUT", 5))  # seconds

    # FPP overlay model names (must match names defined in FPP UI)
    FPP_PHOTO_MODEL = os.environ.get("FPP_PHOTO_MODEL", "PhotoZone")
    FPP_TICKER_MODEL = os.environ.get("FPP_TICKER_MODEL", "TickerZone")

    # FPP playlist to trigger (must exist in FPP)
    FPP_BASE_PLAYLIST = os.environ.get("FPP_BASE_PLAYLIST", "breaking_news")

    # Matrix dimensions (3 panels × 64px wide, 6 panels × 32px high)
    MATRIX_WIDTH  = int(os.environ.get("MATRIX_WIDTH", 192))
    MATRIX_HEIGHT = int(os.environ.get("MATRIX_HEIGHT", 192))

    # Zone split: top photo area / bottom ticker strip
    PHOTO_ZONE_HEIGHT  = int(os.environ.get("PHOTO_ZONE_HEIGHT", 140))
    TICKER_ZONE_HEIGHT = int(os.environ.get("TICKER_ZONE_HEIGHT", 52))

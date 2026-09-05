"""
utils.py
Shared helper functions used across GeoNizam modules:
password hashing, timestamps, image helpers, threading helpers, dialogs,
distance math, and free OpenStreetMap Nominatim reverse geocoding (for
Live GPS Tracking -- see gps_realtime.py for the actual device-GPS
capture, which uses the browser's HTML5 Geolocation API).
"""

import os
import hashlib
import math
import secrets
import threading
import datetime
import io
import json
import time
import urllib.request
import urllib.parse

import numpy as np
import cv2
from PIL import Image

import config


# ----------------------------------------------------------------------
# DISTANCE MATH (used for jump-filtering, smoothing and update throttling
# in gps_realtime.py -- no external dependency needed for this)
# ----------------------------------------------------------------------
_EARTH_RADIUS_M = 6371000.0


def haversine_distance_meters(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in meters between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


# ----------------------------------------------------------------------
# REVERSE GEOCODING (free, keyless OpenStreetMap Nominatim)
# ----------------------------------------------------------------------
# Module-level lock + timestamp enforce Nominatim's usage-policy request
# rate (max ~1 req/sec) across every caller in this process. A small
# in-memory cache (rounded to ~11m grid cells) avoids re-querying the
# same spot repeatedly while an employee is stationary.
_nominatim_lock = threading.Lock()
_nominatim_last_call = 0.0
_nominatim_cache = {}
_NOMINATIM_CACHE_MAX = 500


def reverse_geocode(lat: float, lon: float, timeout: float = 5.0) -> dict:
    """
    Resolves a human-readable address (town/village/street/city) for a
    real GPS coordinate using the free OpenStreetMap Nominatim service.
    Never raises -- network or service failures just return
    success=False so callers can show the raw coordinates instead of
    crashing. Returns:
        {"success": bool, "address": str, "raw": dict|None, "message": str}
    """
    cache_key = (round(lat, 4), round(lon, 4))  # ~11m grid
    if cache_key in _nominatim_cache:
        return _nominatim_cache[cache_key]

    with _nominatim_lock:
        global _nominatim_last_call
        wait = config.NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - _nominatim_last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            params = urllib.parse.urlencode({
                "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                "format": "jsonv2", "zoom": "18", "addressdetails": "1",
            })
            req = urllib.request.Request(
                f"{config.NOMINATIM_REVERSE_URL}?{params}",
                headers={"User-Agent": config.NOMINATIM_USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _nominatim_last_call = time.monotonic()

            address = data.get("display_name")
            if not address:
                result = {"success": False, "address": None, "raw": None,
                           "message": "Reverse geocoding returned no address."}
            else:
                result = {"success": True, "address": address, "raw": data.get("address", {}),
                           "message": "Address resolved."}
        except Exception as exc:
            _nominatim_last_call = time.monotonic()
            result = {"success": False, "address": None, "raw": None,
                      "message": f"Reverse geocoding unavailable: {exc}"}

    if result["success"] and len(_nominatim_cache) < _NOMINATIM_CACHE_MAX:
        _nominatim_cache[cache_key] = result
    return result


# ----------------------------------------------------------------------
# PASSWORD HASHING (PBKDF2-HMAC-SHA256, offline, no external deps)
# ----------------------------------------------------------------------
def hash_password(password: str, salt: bytes = None) -> str:
    """Return 'salt$hash' hex string. Generates a new salt if not supplied."""
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored 'salt$hash' string."""
    try:
        salt_hex, hash_hex = stored_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ----------------------------------------------------------------------
# TIMESTAMPS
# ----------------------------------------------------------------------
def now_str() -> str:
    return datetime.datetime.now().strftime(config.DATETIME_FORMAT)


def today_str() -> str:
    return datetime.datetime.now().strftime(config.DATE_FORMAT)


def elapsed_seconds(start_iso: str, end_iso: str = None) -> float:
    """Compute elapsed seconds between two DATETIME_FORMAT strings."""
    fmt = config.DATETIME_FORMAT
    start_dt = datetime.datetime.strptime(start_iso, fmt)
    end_dt = datetime.datetime.strptime(end_iso, fmt) if end_iso else datetime.datetime.now()
    return max(0.0, (end_dt - start_dt).total_seconds())


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ----------------------------------------------------------------------
# IMAGE HELPERS
# ----------------------------------------------------------------------
def cv2_to_pil(frame_bgr: np.ndarray) -> Image.Image:
    """Convert an OpenCV BGR frame to a PIL RGB image."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def save_bgr_image(frame_bgr: np.ndarray, path: str) -> str:
    """Persist an OpenCV BGR frame as a PNG file on disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, frame_bgr)
    return path


def embedding_to_blob(embedding: np.ndarray) -> bytes:
    """Serialize a float32 embedding vector to bytes for SQLite BLOB storage."""
    return np.asarray(embedding, dtype=np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    """Deserialize bytes back into a float32 embedding vector."""
    return np.frombuffer(blob, dtype=np.float32).copy()


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Return cosine similarity in range [-1, 1] between two vectors."""
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def similarity_to_percentage(cos_sim: float) -> float:
    """
    Map cosine similarity (typically 0.0 - 1.0 for normalized ArcFace embeddings
    of the same identity, can be negative for very dissimilar faces) to a
    0-100 percentage scale for display and threshold comparison.
    """
    pct = ((cos_sim + 1.0) / 2.0) * 100.0
    return max(0.0, min(100.0, pct))


def chi_square_distance(hist_a: np.ndarray, hist_b: np.ndarray, eps: float = 1e-6) -> float:
    """
    Normalized Chi-square distance between two non-negative histogram
    vectors (each already expected to sum to ~1 per cell). This is the
    standard comparison metric for LBP-histogram face descriptors (see
    Ahonen et al., "Face Recognition with Local Binary Patterns") and
    separates genuine/impostor identities far better than cosine
    similarity does on raw histogram counts, since it penalizes
    differences proportionally to how small the bins are instead of
    treating every bin's magnitude the same way.
    Returns a value >= 0 (0 = identical histograms).
    """
    a = np.asarray(hist_a, dtype=np.float64)
    b = np.asarray(hist_b, dtype=np.float64)
    numer = (a - b) ** 2
    denom = a + b + eps
    return float(np.sum(numer / denom))


# ----------------------------------------------------------------------
# IMAGE QUALITY HELPERS (enrollment + verification frame gating)
# ----------------------------------------------------------------------
def sharpness_variance(gray: np.ndarray) -> float:
    """Variance of the Laplacian -- a standard, cheap focus/blur metric.
    Low values indicate a blurry / out-of-focus / low-detail (e.g. photo
    of a photo, or a screen replay) capture."""
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def mean_brightness(gray: np.ndarray) -> float:
    """Mean grayscale intensity, used to reject frames that are too dark
    or blown out (glare) for a reliable embedding."""
    return float(np.mean(gray))


# ----------------------------------------------------------------------
# THREADING HELPERS
# ----------------------------------------------------------------------
class ThreadSafeCounter:
    """A simple thread-safe counter used to track open dashboard windows."""

    def __init__(self, initial=0):
        self._value = initial
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1
            return self._value

    def decrement(self):
        with self._lock:
            self._value = max(0, self._value - 1)
            return self._value

    @property
    def value(self):
        with self._lock:
            return self._value


def run_in_thread(target, args=(), daemon=True):
    """Launch a target function in a background daemon thread."""
    t = threading.Thread(target=target, args=args, daemon=daemon)
    t.start()
    return t


# ----------------------------------------------------------------------
# VALIDATION HELPERS
# ----------------------------------------------------------------------
def wipe_data_files():
    """Delete every captured biometric/attendance image on disk (used by the
    Admin 'Reset All Data' feature) and recreate the empty directories so the
    app is left in the same state as a fresh install."""
    import shutil
    for directory in (config.BIOMETRICS_DIR, config.ATTENDANCE_CAPTURES_DIR):
        if os.path.isdir(directory):
            shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory, exist_ok=True)


def is_blank(value: str) -> bool:
    return value is None or str(value).strip() == ""


def clamp(value, low, high):
    return max(low, min(high, value))


# ----------------------------------------------------------------------
# CAMERA STREAM HELPER (used by Admin biometric capture & Employee attendance)
# ----------------------------------------------------------------------
class CameraStream:
    """Thin wrapper around cv2.VideoCapture for use inside a Tk .after() loop."""

    def __init__(self, camera_index: int = None, width: int = None, height: int = None):
        self.camera_index = camera_index if camera_index is not None else config.CAMERA_INDEX
        self.width = width or config.CAMERA_FRAME_WIDTH
        self.height = height or config.CAMERA_FRAME_HEIGHT
        self._cap = None

    def start(self) -> bool:
        """Returns True if the camera opened successfully. Never raises --
        any backend/driver exception (e.g. device busy, no permission,
        no camera present) is caught and treated as a normal failure so
        the UI can show a message instead of crashing."""
        try:
            cap = cv2.VideoCapture(self.camera_index)
            if self.width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            if self.height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            opened = cap.isOpened()
        except Exception:
            opened = False
            cap = None

        if not opened:
            # Don't leak a half-open handle if isOpened() was False or
            # construction raised partway through.
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            self._cap = None
            return False

        self._cap = cap
        return True

    def read(self):
        """Returns (success: bool, frame_bgr: np.ndarray|None). Never
        raises -- a read error (camera unplugged mid-stream, etc.) is
        treated as a failed read rather than crashing the caller."""
        if self._cap is None:
            return False, None
        try:
            ok, frame = self._cap.read()
        except Exception:
            return False, None
        if not ok or frame is None:
            return False, None
        try:
            frame = cv2.flip(frame, 1)  # mirror for a natural selfie preview
        except Exception:
            return False, None
        return True, frame

    def stop(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

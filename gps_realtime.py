"""
gps_realtime.py
Real device-GPS capture for GeoNizam's Live GPS Tracking feature.

Root cause of the old "always shows Lahore" bug
-------------------------------------------------
The previous implementation (utils.lookup_ip_location) resolved the
employee's location from their machine's *public IP address* via
ip-api.com. IP geolocation only knows which city an ISP's netblock is
*registered* to -- for most Pakistani ISPs that is the ISP's head
office/NOC, not the subscriber's actual location, so an employee on a
mobile-data or broadband connection in Okara was reported as "Lahore"
every single time, regardless of where they physically were. There is
no accuracy fix for that approach; it had to be replaced entirely.

New approach: real browser GPS, zero paid services
----------------------------------------------------
GeoNizam is a desktop (customtkinter) application, so there is no
in-process "browser tab" to call `navigator.geolocation` from directly.
Instead, each Employee dashboard process starts a tiny local-only HTTP
server (bound to 127.0.0.1, stdlib `http.server` -- no new dependency)
and opens it in the employee's own default web browser. That page uses
the REAL browser HTML5 Geolocation API (`navigator.geolocation.
watchPosition`, `enableHighAccuracy: true`, `maximumAge: 0`) to obtain
the device's actual GPS/Wi-Fi/cell-based fix after the employee grants
permission, and streams every fix back to this local server, which is
the only place GeoNizam ever reads coordinates from now on.

This module owns:
  - GPSCaptureServer   -- the local HTTP server + the in-memory "latest
                           known fix" state for one employee.
  - _LocationFilter    -- jump filtering (rejects GPS noise/teleports)
                           and accuracy-weighted smoothing.
  - _should_persist     -- update throttling (distance/time thresholds)
                           so SQLite and the realtime hub aren't flooded.
"""

import json
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import utils
import realtime_hub


# ------------------------------------------------------------------
# The page served to the employee's browser. Plain HTML/JS, no
# external scripts, no build step -- keeps this a free, dependency-free
# "sensor" for the desktop app to read real GPS from.
# ------------------------------------------------------------------
_PAGE_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GeoNizam Live GPS - {employee_name}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0E1712; color:#EAF7EF;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .card {{ background:#16261B; border-radius:16px; padding:32px 40px; max-width:480px; text-align:center; }}
  h1 {{ font-size:20px; color:#4ADE80; margin:0 0 12px; }}
  #status {{ font-size:15px; margin:14px 0; line-height:1.5; }}
  .ok {{ color:#4ADE80; }} .warn {{ color:#F2B705; }} .err {{ color:#E53935; }}
  small {{ color:#8CA598; }}
</style></head>
<body>
  <div class="card">
    <h1>GeoNizam &mdash; Live GPS Tracking</h1>
    <p>Keep this tab open while you're online. It sends your device's real
       GPS location to GeoNizam so your Admin can see your live position.</p>
    <div id="status" class="warn">Requesting location permission&hellip;</div>
    <small>Powered by your browser's HTML5 Geolocation API. Nothing paid,
      nothing external besides free OpenStreetMap reverse geocoding.</small>
  </div>
<script>
const REPORT_URL = "/report";
const ERROR_URL = "/error";
let lastSent = null;      // {{lat, lon, t}}
const MIN_INTERVAL_MS = 2000;
const MIN_DISTANCE_M = 5;

function haversine(lat1, lon1, lat2, lon2) {{
  const R = 6371000, toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}}

function setStatus(text, cls) {{
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = cls;
}}

function post(url, body) {{
  fetch(url, {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(body)}})
    .catch(() => {{ setStatus("Cannot reach GeoNizam (is the app still open?)", "err"); }});
}}

function onSuccess(pos) {{
  const c = pos.coords;
  const now = Date.now();
  // Client-side throttle: only send when meaningfully moved or enough
  // time has passed -- reduces battery/network use before it even
  // reaches the server-side throttle in gps_realtime.py.
  if (lastSent) {{
    const dist = haversine(lastSent.lat, lastSent.lon, c.latitude, c.longitude);
    if (dist < MIN_DISTANCE_M && (now - lastSent.t) < MIN_INTERVAL_MS) return;
  }}
  lastSent = {{lat: c.latitude, lon: c.longitude, t: now}};
  post(REPORT_URL, {{
    lat: c.latitude, lon: c.longitude, accuracy: c.accuracy,
    speed: c.speed, heading: c.heading, timestamp: pos.timestamp,
  }});
  setStatus(
    `Live \u2014 accuracy \u00b1${{Math.round(c.accuracy)}}m` +
    (c.speed ? `, speed ${{(c.speed*3.6).toFixed(1)}} km/h` : ""),
    "ok"
  );
}}

function onError(err) {{
  const messages = {{
    1: "Location permission denied. Enable it in your browser settings to be tracked.",
    2: "Position unavailable (weak/no GPS signal).",
    3: "Location request timed out. Retrying...",
  }};
  const text = messages[err.code] || err.message || "Unknown geolocation error.";
  setStatus(text, "err");
  post(ERROR_URL, {{code: err.code, message: err.message}});
}}

if (!navigator.geolocation) {{
  setStatus("This browser does not support geolocation.", "err");
  post(ERROR_URL, {{code: 0, message: "geolocation_unsupported"}});
}} else if (!navigator.onLine) {{
  setStatus("No internet connection detected.", "err");
}} else {{
  navigator.geolocation.watchPosition(onSuccess, onError, {{
    enableHighAccuracy: {enable_high_accuracy},
    timeout: {timeout_ms},
    maximumAge: {maximum_age_ms},
  }});
}}
</script>
</body></html>
"""


class _LocationFilter:
    """Per-employee jump filter + accuracy-weighted smoothing, kept only
    in memory (each Employee dashboard process tracks exactly one
    employee, so this never needs to be shared across employees)."""

    def __init__(self):
        self.smoothed_lat = None
        self.smoothed_lon = None
        self.last_raw = None  # (lat, lon, monotonic_time)

    def accept(self, lat: float, lon: float, accuracy):
        """Returns (accepted: bool, lat, lon, reason) after filtering an
        implausible jump and applying smoothing to a plausible one."""
        now = time.monotonic()

        if self.last_raw is not None:
            plat, plon, ptime = self.last_raw
            dist_m = utils.haversine_distance_meters(plat, plon, lat, lon)
            dt = max(now - ptime, 0.001)
            implied_kmh = (dist_m / dt) * 3.6
            if implied_kmh > config.GPS_MAX_PLAUSIBLE_SPEED_KMH:
                # Almost certainly GPS noise/multipath, not real movement
                # -- discard the point but keep the previous fix as-is.
                return False, self.smoothed_lat, self.smoothed_lon, "implausible_jump"

        self.last_raw = (lat, lon, now)

        if self.smoothed_lat is None:
            self.smoothed_lat, self.smoothed_lon = lat, lon
            return True, lat, lon, "first_fix"

        # Accuracy-weighted EMA: a precise fix (small `accuracy` radius)
        # moves the smoothed point almost all the way there; a noisy fix
        # only nudges it, so jitter is damped without lagging behind
        # genuine movement.
        acc = accuracy if accuracy is not None else config.GPS_SMOOTHING_ACCURACY_CEILING_M
        acc = max(config.GPS_SMOOTHING_ACCURACY_FLOOR_M,
                  min(acc, config.GPS_SMOOTHING_ACCURACY_CEILING_M))
        span = config.GPS_SMOOTHING_ACCURACY_CEILING_M - config.GPS_SMOOTHING_ACCURACY_FLOOR_M
        confidence = 1 - ((acc - config.GPS_SMOOTHING_ACCURACY_FLOOR_M) / span if span else 0)
        alpha = config.GPS_SMOOTHING_MIN_ALPHA + confidence * (
            config.GPS_SMOOTHING_MAX_ALPHA - config.GPS_SMOOTHING_MIN_ALPHA
        )

        self.smoothed_lat += alpha * (lat - self.smoothed_lat)
        self.smoothed_lon += alpha * (lon - self.smoothed_lon)
        return True, self.smoothed_lat, self.smoothed_lon, "smoothed"


def _find_free_port() -> int:
    lo, hi = config.GPS_LOCAL_SERVER_PORT_RANGE
    for port in range(lo, hi):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((config.GPS_LOCAL_SERVER_HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free local port available for GPS capture server.")


class GPSCaptureServer:
    """
    Owns the local HTTP server for exactly one employee's dashboard.
    Usage:
        gps = GPSCaptureServer(employee_id, employee_name, db)
        gps.start()          # background thread, non-blocking
        gps.open_browser()   # opens the real HTML5-geolocation page
        gps.latest           # thread-safe dict snapshot of last known fix
        gps.stop()
    """

    def __init__(self, employee_id: int, employee_name: str, db, on_update=None):
        self.employee_id = employee_id
        self.employee_name = employee_name
        self.db = db
        self.on_update = on_update  # optional callback(latest_dict)

        self._lock = threading.Lock()
        self._filter = _LocationFilter()
        self._last_persisted_at = 0.0
        self._last_persisted_lat = None
        self._last_persisted_lon = None
        self._last_geocode_at = 0.0
        self._last_geocode_lat = None
        self._last_geocode_lon = None

        self.port = _find_free_port()
        self._httpd = None
        self._thread = None

        # The single piece of shared state the Tkinter UI thread reads.
        self.latest = {
            "status": "waiting",     # waiting | active | error | stopped
            "lat": None, "lon": None, "accuracy": None, "speed": None,
            "heading": None, "address": None, "updated_at": None,
            "error_message": None,
        }

    # -- lifecycle ----------------------------------------------------
    def start(self):
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # keep the console clean; errors surface in the UI instead

            def do_GET(self):
                if self.path not in ("/", ""):
                    self.send_response(404)
                    self.end_headers()
                    return
                body = _PAGE_TEMPLATE.format(
                    employee_name=capture.employee_name,
                    enable_high_accuracy="true" if config.GPS_ENABLE_HIGH_ACCURACY else "false",
                    timeout_ms=config.GPS_POSITION_TIMEOUT_MS,
                    maximum_age_ms=config.GPS_MAXIMUM_AGE_MS,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {}
                if self.path == "/report":
                    capture._handle_report(payload)
                elif self.path == "/error":
                    capture._handle_error(payload)
                self.send_response(204)
                self.end_headers()

        self._httpd = ThreadingHTTPServer((config.GPS_LOCAL_SERVER_HOST, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def open_browser(self):
        webbrowser.open(f"http://{config.GPS_LOCAL_SERVER_HOST}:{self.port}/")

    def stop(self):
        with self._lock:
            self.latest["status"] = "stopped"
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass

    # -- incoming data from the browser page ---------------------------
    def _handle_report(self, payload: dict):
        try:
            lat = float(payload["lat"])
            lon = float(payload["lon"])
        except (KeyError, TypeError, ValueError):
            return
        accuracy = payload.get("accuracy")
        speed = payload.get("speed")       # meters/second, may be null
        heading = payload.get("heading")

        accepted, s_lat, s_lon, reason = self._filter.accept(lat, lon, accuracy)
        if not accepted:
            return  # discarded GPS noise/teleport -- keep showing the last good fix

        with self._lock:
            self.latest.update({
                "status": "active", "lat": s_lat, "lon": s_lon,
                "accuracy": accuracy, "speed": speed, "heading": heading,
                "updated_at": utils.now_str(), "error_message": None,
            })
            snapshot = dict(self.latest)

        if self.on_update:
            try:
                self.on_update(snapshot)
            except Exception:
                pass

        self._maybe_persist(s_lat, s_lon, accuracy, speed, heading)

    def _handle_error(self, payload: dict):
        code = payload.get("code")
        message = payload.get("message") or "Unknown geolocation error."
        friendly = {
            1: "Location permission denied by the employee.",
            2: "GPS signal unavailable (weak/no signal).",
            3: "Location request timed out.",
            0: "This browser does not support geolocation.",
        }.get(code, message)
        with self._lock:
            self.latest.update({"status": "error", "error_message": friendly})
            snapshot = dict(self.latest)
        if self.on_update:
            try:
                self.on_update(snapshot)
            except Exception:
                pass

    # -- persistence throttle (prevents DB flooding) --------------------
    def _maybe_persist(self, lat, lon, accuracy, speed, heading):
        now = time.monotonic()
        moved_far_enough = True
        if self._last_persisted_lat is not None:
            dist = utils.haversine_distance_meters(
                self._last_persisted_lat, self._last_persisted_lon, lat, lon
            )
            moved_far_enough = dist >= config.GPS_MIN_UPDATE_DISTANCE_METERS
        long_enough = (now - self._last_persisted_at) >= config.GPS_MIN_UPDATE_INTERVAL_SECONDS

        if self._last_persisted_lat is not None and not moved_far_enough and not long_enough:
            return  # duplicate/near-duplicate update -- skip to avoid flooding SQLite

        address = self._maybe_reverse_geocode(lat, lon)
        with self._lock:
            self.latest["address"] = address or self.latest.get("address")

        self.db.upsert_employee_location(
            self.employee_id, lat, lon,
            location_label=address, online=True,
            accuracy=accuracy, speed=speed, heading=heading,
            address=address, source="gps",
        )
        self._last_persisted_at = now
        self._last_persisted_lat, self._last_persisted_lon = lat, lon

        # Push instantly to the Admin dashboard via the local realtime
        # hub (WebSocket/SSE-equivalent for this desktop app) so the map
        # updates without waiting for the next poll.
        realtime_hub.publish({
            "type": "location_update", "employee_id": self.employee_id,
            "lat": lat, "lon": lon, "accuracy": accuracy,
        })

    def _maybe_reverse_geocode(self, lat, lon):
        now = time.monotonic()
        if self._last_geocode_lat is not None:
            dist = utils.haversine_distance_meters(self._last_geocode_lat, self._last_geocode_lon, lat, lon)
            if (dist < config.GPS_REVERSE_GEOCODE_MIN_DISTANCE_METERS
                    and (now - self._last_geocode_at) < config.GPS_REVERSE_GEOCODE_MIN_INTERVAL_SECONDS):
                return self.latest.get("address")

        result = utils.reverse_geocode(lat, lon)
        self._last_geocode_at = now
        self._last_geocode_lat, self._last_geocode_lon = lat, lon
        return result["address"] if result["success"] else None

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self.latest)

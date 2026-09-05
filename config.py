"""
config.py
Central configuration for GeoNizam.
Holds paths, constants, default settings and color theme.
"""

import os
import sys

# ----------------------------------------------------------------------
# BASE PATHS
# ----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DATA_DIR = os.path.join(BASE_DIR, "data")
BIOMETRICS_DIR = os.path.join(DATA_DIR, "biometrics")
ATTENDANCE_CAPTURES_DIR = os.path.join(DATA_DIR, "attendance_captures")
DB_PATH = os.path.join(DATA_DIR, "geonizam.db")
SPLASH_IMAGE_PATH = os.path.join(ASSETS_DIR, "Splash.png")

for _p in (ASSETS_DIR, DATA_DIR, BIOMETRICS_DIR, ATTENDANCE_CAPTURES_DIR):
    os.makedirs(_p, exist_ok=True)

# ----------------------------------------------------------------------
# FIXED CREDENTIALS
# ----------------------------------------------------------------------
# Legacy/default Admin account -- seeded once into the `admins` table the
# first time the app runs, so existing installs keep working with the
# same login. After seeding, this account is a normal row in `admins`
# (editable/removable by the Super Admin like any other, subject to the
# same MAX_ADMINS cap).
ADMIN_USERNAME = "admin123"
ADMIN_PASSWORD = "admin123"

# The Super Admin account is a single, fixed, non-database identity (there
# is only ever one Super Admin) -- analogous to how the Admin account used
# to work before multi-admin support was added.
SUPER_ADMIN_USERNAME = "superadmin"
SUPER_ADMIN_PASSWORD = "superadmin123"

# ----------------------------------------------------------------------
# APPLICATION LIMITS
# ----------------------------------------------------------------------
MAX_EMPLOYEE_DASHBOARDS = 7
MAX_ADMINS = 3                                   # Super Admin can create at most this many Admins
MAX_EMPLOYEES_PER_ADMIN = 7                      # Each Admin can create at most this many Employees
MAX_EMPLOYEES_TOTAL = MAX_ADMINS * MAX_EMPLOYEES_PER_ADMIN   # 21
MAX_ADMIN_DASHBOARDS = MAX_ADMINS                # concurrently open Admin dashboard processes
MAX_ADMIN_LIMIT_MESSAGE = "Maximum Admin Limit Reached."
MAX_EMPLOYEE_LIMIT_MESSAGE = "Maximum Employee Limit Reached."
SPLASH_DURATION_SECONDS = 5

# ----------------------------------------------------------------------
# ADMIN PERMISSION FEATURES (toggled per-Admin by the Super Admin)
# ----------------------------------------------------------------------
# (feature_key, display_label) -- feature_key is what's stored in SQLite,
# display_label is what the Super Admin's permission-toggle UI shows.
ADMIN_PERMISSION_FEATURES = [
    ("add_employee", "Add Employee"),
    ("remove_employee", "Remove Employee"),
    ("edit_employee", "Edit Employee"),
    ("track_employee", "Track Employee"),
    ("gps_tracking", "Live GPS Tracking"),
    ("ai_attendance", "AI Attendance"),
    ("task_assignment", "Task Assignment"),
    ("task_approval", "Task Approval"),
    ("daily_reports", "Daily Reports"),
    ("notifications", "Notifications"),
    ("employee_requests", "Employee Requests"),
    ("attendance_reports", "Attendance Reports"),
    ("activity_monitoring", "Activity Monitoring"),
    ("employee_management", "Employee Management"),
]
ADMIN_PERMISSION_KEYS = [key for key, _label in ADMIN_PERMISSION_FEATURES]
# All features are ON by default for a newly created Admin.
DEFAULT_ADMIN_PERMISSIONS = {key: True for key in ADMIN_PERMISSION_KEYS}

# Maps each Admin-dashboard sidebar view to the permission feature(s) that
# gate it. A view with an empty tuple is always visible (no gate). A view
# gated by more than one key is visible if ANY one of them is enabled
# (the keys are alternate/overlapping labels for the same underlying view).
ADMIN_NAV_PERMISSION_MAP = {
    "home": ("employee_requests",),
    "add_employee": ("add_employee",),
    "attendance_control": ("ai_attendance", "attendance_reports"),
    "task_management": ("task_assignment", "task_approval"),
    "notifications": ("notifications",),
    "calculate_salary": (),
    "remove_employee": ("remove_employee", "employee_management"),
    "live_activity": ("activity_monitoring", "daily_reports"),
    "gps_tracking": ("gps_tracking", "track_employee"),
    "reset_data": (),
}

# ----------------------------------------------------------------------
# SELFIE ATTENDANCE SETTINGS
# ----------------------------------------------------------------------
# GeoNizam no longer performs any AI face-matching. Attendance is a plain
# selfie capture that is queued for the Admin to manually Approve/Reject.
# The capture button is only enabled while the Admin has the attendance
# window switched to "Open" -- this is surfaced in the Employee dashboard
# as: "Selfie attendance only takes when it is open".
ATTENDANCE_CLOSED_MESSAGE = "Selfie attendance only takes when it is open"

# Haar cascade frontal-face detector -- kept only as an optional "is a
# face visible" sanity check before letting the employee submit a selfie
# (no matching/recognition is performed with it any more).
FACE_CASCADE_FILE = "haarcascade_frontalface_default.xml"
FACE_DETECT_SCALE_FACTOR = 1.1
FACE_DETECT_MIN_NEIGHBORS = 6

# ----------------------------------------------------------------------
# LIVE GPS TRACKING (free/open technology -- no API key, no paid tiers)
# ----------------------------------------------------------------------
# Map tiles: OpenStreetMap standard tile server via the open-source
# "tkintermapview" widget (MIT licensed, no API key required).
GPS_MAP_TILE_SERVER = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
GPS_DEFAULT_ZOOM = 16
GPS_DEFAULT_LAT = 24.8607     # fallback map center (used only until any
GPS_DEFAULT_LON = 67.0011     # employee location has ever been reported)

# ---- Real device GPS capture (replaces the old IP-based lookup) ------
# IP geolocation (e.g. ip-api.com) only resolves the city/region a
# subscriber's IP block is *registered* to, not the device's physical
# position -- in Pakistan this routinely resolves an Okara/mobile-data
# connection to "Lahore" because that's where the ISP's netblock is
# registered, regardless of where the handset actually is. GeoNizam no
# longer uses IP geolocation for anything. Instead, each Employee
# dashboard starts a small local-only HTTP server (127.0.0.1, stdlib
# `http.server` -- no new dependency, no external service) that serves
# one page using the browser's real HTML5 Geolocation API
# (`navigator.geolocation.watchPosition`). The employee's own browser
# asks the OS for a GPS/Wi-Fi/cell fix after the employee grants
# permission, and posts each fix back to the local server, which is the
# only source of coordinates GeoNizam stores from now on.
GPS_LOCAL_SERVER_HOST = "127.0.0.1"
# Each Employee dashboard process picks the first free port in this
# range so up to 7 concurrent employee dashboards never collide.
GPS_LOCAL_SERVER_PORT_RANGE = (8731, 8761)
# High-accuracy HTML5 geolocation options handed straight to the browser.
GPS_ENABLE_HIGH_ACCURACY = True
GPS_POSITION_TIMEOUT_MS = 15000
GPS_MAXIMUM_AGE_MS = 0            # never accept a cached browser fix

# ---- Free reverse geocoding (OpenStreetMap Nominatim) -----------------
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
# Nominatim's usage policy requires a descriptive User-Agent and caps
# unauthenticated use at ~1 request/second -- both are honoured in utils.py.
NOMINATIM_USER_AGENT = "GeoNizam-EmployeeManagement/1.0 (self-hosted, contact: admin@example.local)"
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1
# Only re-run reverse geocoding once the employee has moved at least this
# far from the last address lookup (keeps GeoNizam well inside the free
# usage policy and avoids blocking the UI on every single GPS tick).
GPS_REVERSE_GEOCODE_MIN_DISTANCE_METERS = 30
GPS_REVERSE_GEOCODE_MIN_INTERVAL_SECONDS = 8

# ---- Accuracy / noise filtering ---------------------------------------
# A "jump" between two consecutive fixes implying a faster speed than
# this is treated as GPS noise and discarded rather than shown as a
# teleport on the map.
GPS_MAX_PLAUSIBLE_SPEED_KMH = 250
# Smoothing: the marker position is an accuracy-weighted moving average
# of recent fixes so jitter from a weak signal doesn't make the marker
# twitch, while genuine movement (a fix far from the smoothed point)
# still passes through close to full-strength.
GPS_SMOOTHING_MIN_ALPHA = 0.30     # weight given to a low-confidence fix
GPS_SMOOTHING_MAX_ALPHA = 1.0      # weight given to a high-confidence / big-movement fix
GPS_SMOOTHING_ACCURACY_FLOOR_M = 5     # fixes at least this accurate get full weight
GPS_SMOOTHING_ACCURACY_CEILING_M = 75  # fixes at least this poor get minimum weight

# ---- Update throttling (prevents DB flooding / battery drain) --------
# A new fix is only persisted to SQLite (and broadcast) if the employee
# moved at least this far, OR this much time has passed since the last
# stored point -- whichever comes first.
GPS_MIN_UPDATE_DISTANCE_METERS = 5
GPS_MIN_UPDATE_INTERVAL_SECONDS = 3

# How often each Employee dashboard reports its location while online.
# Kept for the "Offline" cutoff below; the browser tab itself pushes
# updates continuously via watchPosition rather than polling.
LOCATION_HEARTBEAT_SECONDS = 30
# If an employee's last location report is older than this, the Admin's
# Live GPS Tracking screen treats them as Offline.
LOCATION_ONLINE_TIMEOUT_SECONDS = 90

# ---- Real-time push (local pub/sub, free, no external broker) --------
# A tiny loopback TCP hub (stdlib `socket`, one line of JSON per event)
# that Employee processes publish location updates to and the Admin
# dashboard subscribes to, so the map updates the instant a new fix
# arrives instead of waiting for the next poll -- this is GeoNizam's
# free, dependency-free equivalent of a WebSocket/SSE channel for a
# desktop app. Polling is kept as a low-frequency safety net in case the
# hub isn't reachable.
REALTIME_HUB_HOST = "127.0.0.1"
REALTIME_HUB_PORT = 8765

# ----------------------------------------------------------------------
# UI THEME -- GeoNizam Green
# ----------------------------------------------------------------------
APP_NAME = "GeoNizam"
APP_TAGLINE = "Selfie Attendance & Live GPS Workforce Management"
APPEARANCE_MODE = "Dark"       # "System", "Dark", "Light"
COLOR_THEME = "green"          # customtkinter built-in green theme

WINDOW_BG = "#0E1712"
SIDEBAR_BG = "#122016"
CARD_BG = "#16261B"

PRIMARY_GREEN = "#1DB954"
PRIMARY_GREEN_DARK = "#14532D"
PRIMARY_GREEN_LIGHT = "#4ADE80"

ACCENT_COLOR = PRIMARY_GREEN
ACCENT_HOVER = "#17A34A"
DANGER_COLOR = "#E53935"
DANGER_HOVER = "#B23129"
WARNING_COLOR = "#F2B705"
INFO_COLOR = "#22C55E"
OFFLINE_COLOR = "#6B7280"

LOGIN_WINDOW_SIZE = "480x600"
DASHBOARD_WINDOW_SIZE = "1200x740"

# ----------------------------------------------------------------------
# CAMERA SETTINGS
# ----------------------------------------------------------------------
CAMERA_INDEX = 0
CAMERA_FRAME_WIDTH = 640
CAMERA_FRAME_HEIGHT = 480
CAMERA_FPS_PREVIEW_DELAY_MS = 15

# ----------------------------------------------------------------------
# MISC
# ----------------------------------------------------------------------
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# GeoNizam

Offline-first desktop attendance, task and activity-management application
built with CustomTkinter, SQLite and OpenCV.

GeoNizam replaces old-style AI face-matching attendance with a simpler,
fully human-reviewed flow:

- **Selfie Attendance** -- the employee just takes a selfie and submits it.
  There is no face recognition/matching of any kind. Capture is only
  possible while the Admin has the attendance window switched to **Open**;
  otherwise the employee sees:
  > "Selfie attendance only takes when it is open"
- **Admin Approve / Reject** -- every submitted selfie lands in the Admin's
  "Attendance Control" queue with a thumbnail and the employee's real GPS
  location (captured from their device, never estimated from IP address),
  for a manual Approve or Reject decision.
- **Live GPS Tracking** -- a dedicated Admin screen shows each employee's
  live, real device location (from their browser's HTML5 Geolocation API)
  on an interactive map while they are online, updated in real time, or a
  **"The Employee is currently Offline"** overlay on the map background
  when they are not.

## 1. Requirements

- Python 3.11.9
- A working webcam
- A device with GPS/Wi-Fi/cell location support and a default web browser
  (used once per login to grant real location permission)
- An internet connection for: (a) map tiles in Live GPS Tracking, and
  (b) the free OpenStreetMap Nominatim reverse-geocoding lookup. The rest
  of the app (login, database, tasks, notifications, attendance review)
  works fully offline.

## 2. Install dependencies

```bash
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Add your splash image

Replace `assets/Splash.png` with your own branding image. The app displays
it for 5 seconds on launch.

## 4. Run the application

```bash
python Main.py
```

- **Super Admin login:** username `superadmin`, password `superadmin123`
- **Admin login:** username `admin123`, password `admin123` (seeded automatically
  on first run so existing installs keep working; counts as Admin 1 of 3)
- **Employee login:** created by an Admin via "Add Employee"

The Login window stays open after each login so multiple people can sign in
from the same machine: 1 Super Admin + up to 3 Admin dashboards + up to 7
Employee dashboards can run simultaneously, each as its own independent
process/window, all reading and writing the same permanent local SQLite
database (`data/geonizam.db`).

### Roles at a glance

| Role | Created by | Limit | Manages |
|---|---|---|---|
| Super Admin | fixed account (see above) | 1 | Admins, their permissions, system-wide stats |
| Admin | Super Admin, via "Add Admin" | 3 total | Up to 7 Employees each (21 max system-wide) |
| Employee | their Admin, via "Add Employee" | 7 per Admin | Their own attendance/tasks/requests |

The Super Admin's **Manage Admin Permissions** screen lets you flip any of
14 features (Add/Remove/Edit Employee, Live GPS Tracking, AI Attendance,
Task Assignment/Approval, Notifications, Attendance/Daily Reports, Activity
Monitoring, etc.) ON/OFF per Admin. Permissions are stored in SQLite and
enforced the next time that Admin logs in: disabled sidebar items are shown
locked, and opening one anyway shows "Permission Denied."

## 5. How Selfie Attendance works

1. Admin opens **Attendance Control** and clicks **Open Attendance**.
2. Employees go to **Selfie Attendance**, click **Start Camera**, then
   **Capture Selfie**, review it, and **Submit for Approval**.
   - If the window is closed, the capture flow is disabled and the
     employee sees: "Selfie attendance only takes when it is open".
3. The selfie (plus the employee's real GPS location captured at submit
   time) is queued as **Pending** in the Admin's Attendance Control screen.
4. The Admin reviews the thumbnail and **Approves** or **Rejects** it.
   There is no automatic accept/reject -- every decision is manual.

No biometric enrollment, face embeddings, or match-percentage thresholds
are used anywhere in this flow.

## 6. How Live GPS Tracking works (free technology only, real device GPS)

Earlier versions estimated an employee's location from their machine's
public IP address (`ip-api.com`). IP geolocation only knows which city an
ISP's netblock is *registered* to, not where the device physically is --
for many Pakistani ISPs that registration point is Lahore, so an employee
in Okara (or anywhere else on that ISP) was always shown as "Lahore"
regardless of their real position. GeoNizam no longer does this anywhere.

- **Employee position:** when an Employee dashboard opens, it starts a
  small local-only HTTP server (`gps_realtime.py`, `127.0.0.1`, built on
  the Python standard library -- no new dependency) and opens it in the
  employee's own browser. That page uses the browser's real HTML5
  Geolocation API (`navigator.geolocation.watchPosition`, high accuracy,
  zero cache age) to obtain the device's actual GPS/Wi-Fi/cell fix after
  the employee grants permission, and streams it back to the app
  continuously. A persistent status bar in the dashboard shows whether
  tracking is active, and clearly explains permission-denied, weak-signal,
  timeout, unsupported-browser, and offline errors instead of silently
  falling back to anything approximate.
- **Noise filtering & smoothing:** implausible jumps (e.g. an instant
  "teleport" across the country) are detected from the implied speed
  between fixes and discarded as GPS noise; accepted fixes are smoothed
  with an accuracy-weighted moving average so a weak signal doesn't make
  the marker twitch, while genuine movement still comes through quickly.
- **Update throttling:** a fix is only written to SQLite (and pushed live)
  once the employee has moved a few meters or a few seconds have passed --
  this keeps the database and network usage low without dropping real
  movement.
- **Reverse geocoding:** the free, keyless OpenStreetMap Nominatim service
  resolves each stored fix to a human-readable town/street/city address,
  rate-limited and cached so it stays well within Nominatim's usage policy.
- **Real-time push to the Admin:** `realtime_hub.py` is a tiny local
  pub/sub broker (loopback TCP, one process on the machine becomes the
  hub automatically) that every Employee process publishes updates to and
  the Admin dashboard subscribes to -- GeoNizam's free, dependency-free
  equivalent of a WebSocket/SSE channel for a desktop app. The map updates
  the instant a new fix arrives; a slow poll every 10 seconds is kept only
  as a safety net in case a push is missed.
- **Admin view:** select an employee from the roster to see their live
  marker plus latitude, longitude, accuracy (m), speed, last update time,
  and full reverse-geocoded address. If they are Offline (or their last
  report is older than `config.LOCATION_ONLINE_TIMEOUT_SECONDS`), the map
  stays visible in the background with a **"The Employee is currently
  Offline"** overlay.

If `tkintermapview` is not installed, the rest of the dashboard still
works; the map area shows an install hint instead of crashing.

## 7. Data storage

All application data (Super Admin-managed Admins and their permissions,
Employees, password hashes, attendance selfies + real GPS metadata, live
locations, tasks, notifications, requests, activity sessions) is stored
permanently in `data/geonizam.db` and the `data/attendance_captures/` image
folder. Nothing is sent to any GeoNizam server, because there isn't one --
the only outbound network calls are the free map-tile and Nominatim
reverse-geocoding requests described above, plus the loopback-only local
GPS capture server and realtime hub, neither of which ever leaves the
employee's own machine.

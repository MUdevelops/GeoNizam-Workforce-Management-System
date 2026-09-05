"""
database.py
Thread-safe SQLite persistence layer for GeoNizam.
A single shared connection (check_same_thread=False) guarded by a global
RLock is used since the desktop app runs at most 1 admin + 7 employee
dashboards concurrently -- write contention is low and this keeps behaviour
fully consistent (no WAL fragmentation, no per-thread connection drift).
"""

import sqlite3
import threading
import os

import config
import utils


class Database:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: str = None):
        if self._initialized:
            return
        self.db_path = db_path or config.DB_PATH
        self._lock = threading.RLock()
        # timeout gives SQLite's own locking mechanism time to resolve
        # cross-process contention (Admin + up to 7 Employee OS processes
        # all writing to the same file); WAL journal mode allows concurrent
        # readers while a writer is active, which suits this multi-process
        # desktop deployment much better than the default rollback journal.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.row_factory = sqlite3.Row
        self._create_schema()
        self._initialized = True

    # ------------------------------------------------------------------
    # SCHEMA
    # ------------------------------------------------------------------
    def _create_schema(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    username        TEXT NOT NULL UNIQUE,
                    password_hash   TEXT NOT NULL,
                    active          INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS admin_permissions (
                    admin_id        INTEGER NOT NULL,
                    feature_key     TEXT NOT NULL,
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (admin_id, feature_key),
                    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS employees (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    username        TEXT NOT NULL UNIQUE,
                    password_hash   TEXT NOT NULL,
                    active          INTEGER NOT NULL DEFAULT 1,
                    admin_id        INTEGER,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS biometrics (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id     INTEGER NOT NULL,
                    embedding       BLOB NOT NULL,
                    image_path      TEXT,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS attendance_sessions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    is_open         INTEGER NOT NULL DEFAULT 0,
                    threshold       INTEGER NOT NULL DEFAULT 70,
                    opened_at       TEXT,
                    closed_at       TEXT
                );

                CREATE TABLE IF NOT EXISTS attendance_records (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id         INTEGER NOT NULL,
                    session_id          INTEGER NOT NULL,
                    match_percentage    REAL NOT NULL DEFAULT 0,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    image_path          TEXT,
                    latitude            REAL,
                    longitude           REAL,
                    location_label      TEXT,
                    reviewed_at         TEXT,
                    timestamp           TEXT NOT NULL,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                    FOREIGN KEY (session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS employee_locations (
                    employee_id     INTEGER PRIMARY KEY,
                    latitude        REAL,
                    longitude       REAL,
                    location_label  TEXT,
                    accuracy        REAL,
                    speed           REAL,
                    heading         REAL,
                    address         TEXT,
                    source          TEXT,
                    online          INTEGER NOT NULL DEFAULT 0,
                    updated_at      TEXT,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    title           TEXT NOT NULL,
                    description     TEXT,
                    assigned_to     INTEGER,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (assigned_to) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS task_assignments (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id         INTEGER NOT NULL,
                    employee_id     INTEGER NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    start_time      TEXT,
                    finish_time     TEXT,
                    total_seconds   REAL NOT NULL DEFAULT 0,
                    last_resume     TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    title           TEXT NOT NULL,
                    message         TEXT NOT NULL,
                    target          TEXT NOT NULL,
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_reads (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id     INTEGER NOT NULL,
                    employee_id          INTEGER NOT NULL,
                    read_at              TEXT,
                    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS requests (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id     INTEGER NOT NULL,
                    subject         TEXT NOT NULL,
                    message         TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TEXT NOT NULL,
                    resolved_at     TEXT,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS activity_sessions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id     INTEGER NOT NULL,
                    label           TEXT,
                    status          TEXT NOT NULL DEFAULT 'running',
                    start_time      TEXT NOT NULL,
                    finish_time     TEXT,
                    total_seconds   REAL NOT NULL DEFAULT 0,
                    last_resume     TEXT,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS activity_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id     INTEGER NOT NULL,
                    event_type      TEXT NOT NULL,
                    description     TEXT,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
                );

                -- Indexes for the lookups the UI/reporting layer actually performs
                -- (employee-scoped history lists, "today" filtering, task lookups).
                CREATE INDEX IF NOT EXISTS idx_biometrics_employee ON biometrics(employee_id);
                CREATE INDEX IF NOT EXISTS idx_attendance_employee ON attendance_records(employee_id);
                CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance_records(session_id);
                CREATE INDEX IF NOT EXISTS idx_attendance_timestamp ON attendance_records(timestamp);
                CREATE INDEX IF NOT EXISTS idx_task_assignments_employee ON task_assignments(employee_id);
                CREATE INDEX IF NOT EXISTS idx_task_assignments_task ON task_assignments(task_id);
                CREATE INDEX IF NOT EXISTS idx_notification_reads_emp ON notification_reads(employee_id);
                CREATE INDEX IF NOT EXISTS idx_requests_employee ON requests(employee_id);
                CREATE INDEX IF NOT EXISTS idx_activity_sessions_employee ON activity_sessions(employee_id);
                CREATE INDEX IF NOT EXISTS idx_activity_log_employee ON activity_log(employee_id);
                CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at);
                CREATE INDEX IF NOT EXISTS idx_employees_admin ON employees(admin_id);
                CREATE INDEX IF NOT EXISTS idx_admin_permissions_admin ON admin_permissions(admin_id);
                """
            )
            self._conn.commit()

            # ---- MIGRATION: older databases created before multi-admin
            # support was added won't have the `admin_id` column on
            # `employees` yet (CREATE TABLE IF NOT EXISTS does not alter an
            # already-existing table) -- add it in-place so no data is lost.
            existing_cols = {row["name"] for row in cur.execute("PRAGMA table_info(employees);").fetchall()}
            if "admin_id" not in existing_cols:
                cur.execute("ALTER TABLE employees ADD COLUMN admin_id INTEGER REFERENCES admins(id);")
                self._conn.commit()

            # ---- MIGRATION: older databases created before real-GPS
            # tracking was added won't have the accuracy/speed/heading/
            # address/source columns on `employee_locations` yet -- add
            # them in-place so no existing location history is lost.
            loc_cols = {row["name"] for row in cur.execute("PRAGMA table_info(employee_locations);").fetchall()}
            for col_name, col_type in (
                ("accuracy", "REAL"), ("speed", "REAL"), ("heading", "REAL"),
                ("address", "TEXT"), ("source", "TEXT"),
            ):
                if col_name not in loc_cols:
                    cur.execute(f"ALTER TABLE employee_locations ADD COLUMN {col_name} {col_type};")
            self._conn.commit()

            # Ensure exactly one attendance_sessions control row exists (id=1)
            cur.execute("SELECT COUNT(*) AS c FROM attendance_sessions;")
            if cur.fetchone()["c"] == 0:
                cur.execute(
                    "INSERT INTO attendance_sessions (is_open, threshold, opened_at, closed_at) "
                    "VALUES (0, 0, NULL, NULL);"
                )
                self._conn.commit()

            # ---- SEED: preserve backward compatibility -- if no Admin
            # accounts exist yet (fresh install, or an upgrade from a
            # pre-multi-admin database), create one from the legacy fixed
            # admin123/admin123 credentials so existing docs/logins keep
            # working. It counts toward MAX_ADMINS like any other Admin.
            cur.execute("SELECT COUNT(*) AS c FROM admins;")
            if cur.fetchone()["c"] == 0:
                cur.execute(
                    "INSERT INTO admins (name, username, password_hash, active, created_at) "
                    "VALUES (?, ?, ?, 1, ?);",
                    ("Admin", config.ADMIN_USERNAME, utils.hash_password(config.ADMIN_PASSWORD), utils.now_str()),
                )
                self._conn.commit()
                seed_admin_id = cur.lastrowid
                self._seed_default_permissions(cur, seed_admin_id)
                # Any pre-existing employees created before admin_id existed
                # are attributed to this seeded admin so the per-admin
                # employee cap has a consistent owner for them.
                cur.execute("UPDATE employees SET admin_id = ? WHERE admin_id IS NULL;", (seed_admin_id,))
                self._conn.commit()

    def _seed_default_permissions(self, cur, admin_id: int):
        for key in config.ADMIN_PERMISSION_KEYS:
            cur.execute(
                "INSERT OR IGNORE INTO admin_permissions (admin_id, feature_key, enabled) VALUES (?, ?, 1);",
                (admin_id, key),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # GENERIC EXEC HELPERS
    # ------------------------------------------------------------------
    def execute(self, query: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(query, params)
            self._conn.commit()
            return cur

    def query_one(self, query: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(query, params)
            return cur.fetchone()

    def query_all(self, query: str, params: tuple = ()):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(query, params)
            return cur.fetchall()

    # ------------------------------------------------------------------
    # EMPLOYEES
    # ------------------------------------------------------------------
    def add_employee(self, name: str, username: str, password: str, admin_id: int = None) -> int:
        pw_hash = utils.hash_password(password)
        cur = self.execute(
            "INSERT INTO employees (name, username, password_hash, active, admin_id, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?);",
            (name.strip(), username.strip(), pw_hash, admin_id, utils.now_str()),
        )
        return cur.lastrowid

    def get_employee_by_username(self, username: str):
        return self.query_one(
            "SELECT * FROM employees WHERE username = ? AND active = 1;", (username,)
        )

    def get_employee_by_id(self, employee_id: int):
        return self.query_one("SELECT * FROM employees WHERE id = ?;", (employee_id,))

    def list_employees(self, active_only: bool = True):
        if active_only:
            return self.query_all("SELECT * FROM employees WHERE active = 1 ORDER BY name;")
        return self.query_all("SELECT * FROM employees ORDER BY name;")

    def list_employees_for_admin(self, admin_id: int, active_only: bool = True):
        if active_only:
            return self.query_all(
                "SELECT * FROM employees WHERE admin_id = ? AND active = 1 ORDER BY name;", (admin_id,)
            )
        return self.query_all(
            "SELECT * FROM employees WHERE admin_id = ? ORDER BY name;", (admin_id,)
        )

    def count_employees_for_admin(self, admin_id: int, active_only: bool = True) -> int:
        if active_only:
            row = self.query_one(
                "SELECT COUNT(*) AS c FROM employees WHERE admin_id = ? AND active = 1;", (admin_id,)
            )
        else:
            row = self.query_one("SELECT COUNT(*) AS c FROM employees WHERE admin_id = ?;", (admin_id,))
        return row["c"] if row else 0

    def count_all_employees(self, active_only: bool = True) -> int:
        if active_only:
            row = self.query_one("SELECT COUNT(*) AS c FROM employees WHERE active = 1;")
        else:
            row = self.query_one("SELECT COUNT(*) AS c FROM employees;")
        return row["c"] if row else 0

    def username_exists(self, username: str) -> bool:
        """Checks for a username collision across Employees AND Admins,
        since both roles now share one login namespace in the same app."""
        if self.query_one("SELECT id FROM employees WHERE username = ?;", (username,)) is not None:
            return True
        if self.query_one("SELECT id FROM admins WHERE username = ?;", (username,)) is not None:
            return True
        return username == config.SUPER_ADMIN_USERNAME

    def remove_employee(self, employee_id: int):
        # Soft delete keeps historical attendance/task/activity records intact,
        # while excluding the employee from login and active lists.
        self.execute("UPDATE employees SET active = 0 WHERE id = ?;", (employee_id,))

    def hard_delete_employee(self, employee_id: int):
        self.execute("DELETE FROM employees WHERE id = ?;", (employee_id,))

    # ------------------------------------------------------------------
    # BIOMETRICS
    # ------------------------------------------------------------------
    def add_biometric(self, employee_id: int, embedding_blob: bytes, image_path: str) -> int:
        cur = self.execute(
            "INSERT INTO biometrics (employee_id, embedding, image_path, created_at) "
            "VALUES (?, ?, ?, ?);",
            (employee_id, embedding_blob, image_path, utils.now_str()),
        )
        return cur.lastrowid

    def get_biometrics_for_employee(self, employee_id: int):
        return self.query_all(
            "SELECT * FROM biometrics WHERE employee_id = ? ORDER BY created_at DESC;",
            (employee_id,),
        )

    def get_all_biometrics(self):
        return self.query_all(
            "SELECT biometrics.*, employees.name AS employee_name, employees.username AS employee_username "
            "FROM biometrics JOIN employees ON biometrics.employee_id = employees.id "
            "WHERE employees.active = 1;"
        )

    def delete_biometrics_for_employee(self, employee_id: int):
        self.execute("DELETE FROM biometrics WHERE employee_id = ?;", (employee_id,))

    # ------------------------------------------------------------------
    # ADMINS (managed by the Super Admin)
    # ------------------------------------------------------------------
    def count_admins(self, active_only: bool = True) -> int:
        if active_only:
            row = self.query_one("SELECT COUNT(*) AS c FROM admins WHERE active = 1;")
        else:
            row = self.query_one("SELECT COUNT(*) AS c FROM admins;")
        return row["c"] if row else 0

    def add_admin(self, name: str, username: str, password: str) -> int:
        """Creates a new Admin with the default (all-ON) permission set.
        Callers must check count_admins() < config.MAX_ADMINS themselves
        before calling this, so the UI can show the proper limit message."""
        pw_hash = utils.hash_password(password)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO admins (name, username, password_hash, active, created_at) "
                "VALUES (?, ?, ?, 1, ?);",
                (name.strip(), username.strip(), pw_hash, utils.now_str()),
            )
            self._conn.commit()
            admin_id = cur.lastrowid
            self._seed_default_permissions(cur, admin_id)
            return admin_id

    def get_admin_by_id(self, admin_id: int):
        return self.query_one("SELECT * FROM admins WHERE id = ?;", (admin_id,))

    def get_admin_by_username(self, username: str):
        return self.query_one("SELECT * FROM admins WHERE username = ? AND active = 1;", (username,))

    def list_admins(self, active_only: bool = True):
        if active_only:
            return self.query_all("SELECT * FROM admins WHERE active = 1 ORDER BY name;")
        return self.query_all("SELECT * FROM admins ORDER BY name;")

    def update_admin(self, admin_id: int, name: str = None, username: str = None, password: str = None):
        set_clauses, params = [], []
        if name is not None:
            set_clauses.append("name = ?")
            params.append(name.strip())
        if username is not None:
            set_clauses.append("username = ?")
            params.append(username.strip())
        if password is not None:
            set_clauses.append("password_hash = ?")
            params.append(utils.hash_password(password))
        if not set_clauses:
            return
        params.append(admin_id)
        self.execute(f"UPDATE admins SET {', '.join(set_clauses)} WHERE id = ?;", tuple(params))

    def remove_admin(self, admin_id: int):
        """Soft delete: deactivates the Admin (keeps historical records/audit
        trail intact) and unassigns their Employees rather than deleting them,
        so no Employee data is ever lost when an Admin is removed."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE admins SET active = 0 WHERE id = ?;", (admin_id,))
            cur.execute("UPDATE employees SET admin_id = NULL WHERE admin_id = ?;", (admin_id,))
            self._conn.commit()

    def hard_delete_admin(self, admin_id: int):
        self.execute("DELETE FROM admins WHERE id = ?;", (admin_id,))

    # ------------------------------------------------------------------
    # ADMIN PERMISSIONS (per-feature ON/OFF toggles, set by the Super Admin)
    # ------------------------------------------------------------------
    def get_admin_permissions(self, admin_id: int) -> dict:
        """Returns {feature_key: bool} for every known feature. Any feature
        key missing a row (e.g. added to config.ADMIN_PERMISSION_FEATURES
        after this Admin was created) defaults to enabled=True."""
        rows = self.query_all(
            "SELECT feature_key, enabled FROM admin_permissions WHERE admin_id = ?;", (admin_id,)
        )
        stored = {row["feature_key"]: bool(row["enabled"]) for row in rows}
        return {key: stored.get(key, True) for key in config.ADMIN_PERMISSION_KEYS}

    def set_admin_permission(self, admin_id: int, feature_key: str, enabled: bool):
        self.execute(
            "INSERT INTO admin_permissions (admin_id, feature_key, enabled) VALUES (?, ?, ?) "
            "ON CONFLICT(admin_id, feature_key) DO UPDATE SET enabled = excluded.enabled;",
            (admin_id, feature_key, 1 if enabled else 0),
        )

    def set_admin_permissions_bulk(self, admin_id: int, permissions: dict):
        """permissions: {feature_key: bool}. Applied as a single transaction."""
        with self._lock:
            cur = self._conn.cursor()
            for key, enabled in permissions.items():
                cur.execute(
                    "INSERT INTO admin_permissions (admin_id, feature_key, enabled) VALUES (?, ?, ?) "
                    "ON CONFLICT(admin_id, feature_key) DO UPDATE SET enabled = excluded.enabled;",
                    (admin_id, key, 1 if enabled else 0),
                )
            self._conn.commit()

    def admin_has_permission(self, admin_id: int, feature_key: str) -> bool:
        row = self.query_one(
            "SELECT enabled FROM admin_permissions WHERE admin_id = ? AND feature_key = ?;",
            (admin_id, feature_key),
        )
        return bool(row["enabled"]) if row is not None else True

    # ------------------------------------------------------------------
    # SYSTEM STATISTICS (Super Admin "View System Statistics")
    # ------------------------------------------------------------------
    def get_system_statistics(self) -> dict:
        admins = self.count_admins(active_only=True)
        employees = self.count_all_employees(active_only=True)
        pending_requests = self.query_one("SELECT COUNT(*) AS c FROM requests WHERE status = 'pending';")
        pending_attendance = self.query_one("SELECT COUNT(*) AS c FROM attendance_records WHERE status = 'pending';")
        total_tasks = self.query_one("SELECT COUNT(*) AS c FROM tasks;")
        online_employees = self.query_one("SELECT COUNT(*) AS c FROM employee_locations WHERE online = 1;")
        return {
            "admins": admins,
            "max_admins": config.MAX_ADMINS,
            "employees": employees,
            "max_employees": config.MAX_EMPLOYEES_TOTAL,
            "pending_requests": pending_requests["c"] if pending_requests else 0,
            "pending_attendance": pending_attendance["c"] if pending_attendance else 0,
            "total_tasks": total_tasks["c"] if total_tasks else 0,
            "online_employees": online_employees["c"] if online_employees else 0,
        }

    # ------------------------------------------------------------------
    # ATTENDANCE SESSION CONTROL
    # ------------------------------------------------------------------
    def open_attendance(self, threshold: int):
        self.execute(
            "UPDATE attendance_sessions SET is_open = 1, threshold = ?, opened_at = ?, closed_at = NULL "
            "WHERE id = 1;",
            (threshold, utils.now_str()),
        )

    def close_attendance(self):
        self.execute(
            "UPDATE attendance_sessions SET is_open = 0, closed_at = ? WHERE id = 1;",
            (utils.now_str(),),
        )

    def get_attendance_session(self):
        return self.query_one("SELECT * FROM attendance_sessions WHERE id = 1;")

    def add_attendance_record(self, employee_id, session_id, status, image_path,
                               latitude=None, longitude=None, location_label=None,
                               match_percentage=0.0):
        cur = self.execute(
            "INSERT INTO attendance_records (employee_id, session_id, match_percentage, status, "
            "image_path, latitude, longitude, location_label, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (employee_id, session_id, match_percentage, status, image_path,
             latitude, longitude, location_label, utils.now_str()),
        )
        return cur.lastrowid

    def list_attendance_records(self, employee_id: int = None):
        if employee_id is not None:
            return self.query_all(
                "SELECT ar.*, e.name AS employee_name FROM attendance_records ar "
                "JOIN employees e ON ar.employee_id = e.id "
                "WHERE ar.employee_id = ? ORDER BY ar.timestamp DESC;",
                (employee_id,),
            )
        return self.query_all(
            "SELECT ar.*, e.name AS employee_name FROM attendance_records ar "
            "JOIN employees e ON ar.employee_id = e.id ORDER BY ar.timestamp DESC;"
        )

    def list_pending_attendance(self):
        return self.query_all(
            "SELECT ar.*, e.name AS employee_name FROM attendance_records ar "
            "JOIN employees e ON ar.employee_id = e.id "
            "WHERE ar.status = 'pending' ORDER BY ar.timestamp ASC;"
        )

    def review_attendance_record(self, record_id: int, status: str):
        """status = 'approved' or 'rejected'."""
        self.execute(
            "UPDATE attendance_records SET status = ?, reviewed_at = ? WHERE id = ?;",
            (status, utils.now_str(), record_id),
        )

    def has_pending_or_approved(self, employee_id: int, session_id: int) -> bool:
        row = self.query_one(
            "SELECT id FROM attendance_records WHERE employee_id = ? AND session_id = ? "
            "AND status IN ('approved', 'pending');",
            (employee_id, session_id),
        )
        return row is not None

    # ------------------------------------------------------------------
    # LIVE GPS TRACKING
    # ------------------------------------------------------------------
    def upsert_employee_location(self, employee_id: int, latitude, longitude,
                                  location_label: str = None, online: bool = True,
                                  accuracy=None, speed=None, heading=None,
                                  address: str = None, source: str = "gps"):
        """
        Stores the latest verified device-GPS fix for an employee.
        `source` records where the coordinate came from ("gps" for a real
        browser HTML5 Geolocation fix -- the only source GeoNizam writes
        from now on) so historical rows can always be told apart from
        anything captured before this redesign.
        """
        self.execute(
            "INSERT INTO employee_locations (employee_id, latitude, longitude, location_label, "
            "accuracy, speed, heading, address, source, online, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(employee_id) DO UPDATE SET latitude = excluded.latitude, "
            "longitude = excluded.longitude, location_label = excluded.location_label, "
            "accuracy = excluded.accuracy, speed = excluded.speed, heading = excluded.heading, "
            "address = excluded.address, source = excluded.source, "
            "online = excluded.online, updated_at = excluded.updated_at;",
            (employee_id, latitude, longitude, location_label, accuracy, speed, heading,
             address, source, 1 if online else 0, utils.now_str()),
        )

    def set_employee_offline(self, employee_id: int):
        self.execute(
            "INSERT INTO employee_locations (employee_id, online, updated_at) VALUES (?, 0, ?) "
            "ON CONFLICT(employee_id) DO UPDATE SET online = 0, updated_at = excluded.updated_at;",
            (employee_id, utils.now_str()),
        )

    def get_employee_location(self, employee_id: int):
        return self.query_one(
            "SELECT * FROM employee_locations WHERE employee_id = ?;", (employee_id,)
        )

    def list_employee_locations(self):
        return self.query_all(
            "SELECT e.id AS employee_id, e.name AS employee_name, el.latitude, el.longitude, "
            "el.location_label, el.accuracy, el.speed, el.heading, el.address, el.source, "
            "el.online, el.updated_at FROM employees e "
            "LEFT JOIN employee_locations el ON el.employee_id = e.id "
            "WHERE e.active = 1 ORDER BY e.name;"
        )

    # ------------------------------------------------------------------
    # TASKS
    # ------------------------------------------------------------------
    def add_task(self, title: str, description: str, assigned_to=None) -> int:
        cur = self.execute(
            "INSERT INTO tasks (title, description, assigned_to, created_at) VALUES (?, ?, ?, ?);",
            (title.strip(), description.strip(), assigned_to, utils.now_str()),
        )
        task_id = cur.lastrowid

        if assigned_to is None:
            employees = self.list_employees(active_only=True)
        else:
            emp = self.get_employee_by_id(assigned_to)
            employees = [emp] if emp else []

        for emp in employees:
            self.execute(
                "INSERT INTO task_assignments (task_id, employee_id, status) VALUES (?, ?, 'pending');",
                (task_id, emp["id"]),
            )
        return task_id

    def list_tasks(self):
        return self.query_all("SELECT * FROM tasks ORDER BY created_at DESC;")

    def list_task_assignments_for_employee(self, employee_id: int):
        return self.query_all(
            "SELECT ta.*, t.title, t.description FROM task_assignments ta "
            "JOIN tasks t ON ta.task_id = t.id "
            "WHERE ta.employee_id = ? ORDER BY ta.id DESC;",
            (employee_id,),
        )

    def list_all_task_assignments(self):
        return self.query_all(
            "SELECT ta.*, t.title, t.description, e.name AS employee_name FROM task_assignments ta "
            "JOIN tasks t ON ta.task_id = t.id "
            "JOIN employees e ON ta.employee_id = e.id "
            "ORDER BY ta.id DESC;"
        )

    def get_task_assignment(self, assignment_id: int):
        return self.query_one("SELECT * FROM task_assignments WHERE id = ?;", (assignment_id,))

    def update_task_assignment_status(self, assignment_id: int, status: str, **fields):
        allowed = {"start_time", "finish_time", "total_seconds", "last_resume"}
        set_clauses = ["status = ?"]
        params = [status]
        for key, value in fields.items():
            if key in allowed:
                set_clauses.append(f"{key} = ?")
                params.append(value)
        params.append(assignment_id)
        query = f"UPDATE task_assignments SET {', '.join(set_clauses)} WHERE id = ?;"
        self.execute(query, tuple(params))

    # ------------------------------------------------------------------
    # NOTIFICATIONS
    # ------------------------------------------------------------------
    def add_notification(self, title: str, message: str, target: str) -> int:
        """target = 'all' or an employee_id string."""
        cur = self.execute(
            "INSERT INTO notifications (title, message, target, created_at) VALUES (?, ?, ?, ?);",
            (title.strip(), message.strip(), str(target), utils.now_str()),
        )
        return cur.lastrowid

    def list_notifications_for_employee(self, employee_id: int):
        return self.query_all(
            "SELECT * FROM notifications WHERE target = 'all' OR target = ? "
            "ORDER BY created_at DESC;",
            (str(employee_id),),
        )

    def list_all_notifications(self):
        return self.query_all("SELECT * FROM notifications ORDER BY created_at DESC;")

    # ------------------------------------------------------------------
    # REQUESTS (Employee -> Admin)
    # ------------------------------------------------------------------
    def add_request(self, employee_id: int, subject: str, message: str) -> int:
        cur = self.execute(
            "INSERT INTO requests (employee_id, subject, message, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?);",
            (employee_id, subject.strip(), message.strip(), utils.now_str()),
        )
        return cur.lastrowid

    def list_requests(self, status: str = None):
        if status:
            return self.query_all(
                "SELECT r.*, e.name AS employee_name FROM requests r "
                "JOIN employees e ON r.employee_id = e.id "
                "WHERE r.status = ? ORDER BY r.created_at DESC;",
                (status,),
            )
        return self.query_all(
            "SELECT r.*, e.name AS employee_name FROM requests r "
            "JOIN employees e ON r.employee_id = e.id ORDER BY r.created_at DESC;"
        )

    def update_request_status(self, request_id: int, status: str):
        self.execute(
            "UPDATE requests SET status = ?, resolved_at = ? WHERE id = ?;",
            (status, utils.now_str(), request_id),
        )

    # ------------------------------------------------------------------
    # LIVE ACTIVITY TRACKING
    # ------------------------------------------------------------------
    def start_activity(self, employee_id: int, label: str = None) -> int:
        cur = self.execute(
            "INSERT INTO activity_sessions (employee_id, label, status, start_time, last_resume) "
            "VALUES (?, ?, 'running', ?, ?);",
            (employee_id, label, utils.now_str(), utils.now_str()),
        )
        return cur.lastrowid

    def get_active_activity(self, employee_id: int):
        return self.query_one(
            "SELECT * FROM activity_sessions WHERE employee_id = ? AND status IN ('running', 'paused') "
            "ORDER BY id DESC LIMIT 1;",
            (employee_id,),
        )

    def update_activity(self, activity_id: int, status: str, **fields):
        allowed = {"finish_time", "total_seconds", "last_resume"}
        set_clauses = ["status = ?"]
        params = [status]
        for key, value in fields.items():
            if key in allowed:
                set_clauses.append(f"{key} = ?")
                params.append(value)
        params.append(activity_id)
        query = f"UPDATE activity_sessions SET {', '.join(set_clauses)} WHERE id = ?;"
        self.execute(query, tuple(params))

    def list_activity_sessions(self, employee_id: int = None):
        if employee_id is not None:
            return self.query_all(
                "SELECT * FROM activity_sessions WHERE employee_id = ? ORDER BY id DESC;",
                (employee_id,),
            )
        return self.query_all(
            "SELECT a.*, e.name AS employee_name FROM activity_sessions a "
            "JOIN employees e ON a.employee_id = e.id ORDER BY a.id DESC;"
        )

    # ------------------------------------------------------------------
    # LIVE ACTIVITY REPORT (employee event timeline for the admin dashboard)
    # ------------------------------------------------------------------
    def log_event(self, employee_id: int, event_type: str, description: str = None):
        """Append one row to the always-on employee activity timeline.
        Used for Login/Logout/Attendance Taken/Task Started.../etc so the
        admin's Live Activity Report has a complete, timestamped history."""
        self.execute(
            "INSERT INTO activity_log (employee_id, event_type, description, created_at) "
            "VALUES (?, ?, ?, ?);",
            (employee_id, event_type, description, utils.now_str()),
        )

    def list_activity_log(self, employee_id: int = None, limit: int = 500):
        if employee_id is not None:
            return self.query_all(
                "SELECT al.*, e.name AS employee_name FROM activity_log al "
                "JOIN employees e ON al.employee_id = e.id "
                "WHERE al.employee_id = ? ORDER BY al.id DESC LIMIT ?;",
                (employee_id, limit),
            )
        return self.query_all(
            "SELECT al.*, e.name AS employee_name FROM activity_log al "
            "JOIN employees e ON al.employee_id = e.id "
            "ORDER BY al.id DESC LIMIT ?;",
            (limit,),
        )

    def get_last_event(self, employee_id: int):
        return self.query_one(
            "SELECT * FROM activity_log WHERE employee_id = ? ORDER BY id DESC LIMIT 1;",
            (employee_id,),
        )

    def get_last_login_time(self, employee_id: int):
        row = self.query_one(
            "SELECT created_at FROM activity_log WHERE employee_id = ? AND event_type = 'login' "
            "ORDER BY id DESC LIMIT 1;",
            (employee_id,),
        )
        return row["created_at"] if row else None

    def get_today_working_seconds(self, employee_id: int) -> float:
        """Sum of finished + in-progress task time for today, used by the
        Current Activity Monitor's 'Working time today' figure."""
        today = utils.now_str()[:10]
        rows = self.query_all(
            "SELECT total_seconds, status, last_resume FROM task_assignments "
            "WHERE employee_id = ? AND (start_time LIKE ? OR finish_time LIKE ?);",
            (employee_id, f"{today}%", f"{today}%"),
        )
        total = 0.0
        for r in rows:
            secs = r["total_seconds"] or 0.0
            if r["status"] == "in_progress" and r["last_resume"]:
                secs += utils.elapsed_seconds(r["last_resume"])
            total += secs
        return total

    # ------------------------------------------------------------------
    # RESET ALL DATA (return the application to a fresh-install state)
    # ------------------------------------------------------------------
    def reset_all_data(self):
        """Wipes every table and reinitializes system counters/defaults.
        Does NOT touch files on disk (biometrics/attendance capture images) --
        callers should also remove those directories; see utils.wipe_data_files()."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF;")
            tables = [
                "activity_log", "activity_sessions", "task_assignments", "tasks",
                "notification_reads", "notifications", "requests",
                "attendance_records", "attendance_sessions", "employee_locations",
                "biometrics", "employees",
            ]
            for t in tables:
                cur.execute(f"DELETE FROM {t};")
                cur.execute("DELETE FROM sqlite_sequence WHERE name = ?;", (t,))
            cur.execute(
                "INSERT INTO attendance_sessions (is_open, threshold, opened_at, closed_at) "
                "VALUES (0, 0, NULL, NULL);"
            )
            self._conn.commit()
            cur.execute("PRAGMA foreign_keys = ON;")

    def close(self):
        with self._lock:
            self._conn.close()


# Convenience singleton accessor used throughout the app
def get_db() -> Database:
    return Database()

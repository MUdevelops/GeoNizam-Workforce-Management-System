"""
Main.py
Entry point for GeoNizam.

Flow:
    1. Show Splash.png for SPLASH_DURATION_SECONDS.
    2. Show the Login window (stays alive/responsive for further logins).
    3. Admin login -> spawns the Admin dashboard as its own OS process
       (max 1 concurrent). Employee login -> spawns an Employee dashboard
       as its own OS process (max 7 concurrent).
    4. The Login window keeps running so multiple people can log in from
       the same machine session without restarting the app.

Each dashboard runs in its own process (not just a thread) because Tkinter/
CustomTkinter mainloops are not safe to run concurrently on multiple threads
in the same process. Running each dashboard as an independent process gives
every window its own GUI event loop, while all of them share the same
permanent SQLite database on disk.
"""

import os
import subprocess
import sys

import customtkinter as ctk
from PIL import Image

import config
from database import get_db


# ----------------------------------------------------------------------
# SPLASH SCREEN
# ----------------------------------------------------------------------
def show_splash(root_window):
    splash = ctk.CTkToplevel(root_window)
    splash.overrideredirect(True)
    splash.attributes("-topmost", True)

    width, height = 640, 400
    img = None
    if os.path.exists(config.SPLASH_IMAGE_PATH):
        try:
            img = Image.open(config.SPLASH_IMAGE_PATH)
            width, height = img.size
        except Exception:
            img = None
    else:
        img = None

    screen_w = splash.winfo_screenwidth()
    screen_h = splash.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    splash.geometry(f"{width}x{height}+{x}+{y}")

    if img is not None:
        try:
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
            label = ctk.CTkLabel(splash, image=ctk_img, text="")
            label.pack(fill="both", expand=True)
        except Exception:
            splash.configure(fg_color=config.WINDOW_BG)
            label = ctk.CTkLabel(
                splash, text=config.APP_NAME,
                font=ctk.CTkFont(size=36, weight="bold"),
            )
            label.pack(fill="both", expand=True)
    else:
        splash.configure(fg_color=config.WINDOW_BG)
        label = ctk.CTkLabel(
            splash, text=config.APP_NAME,
            font=ctk.CTkFont(size=36, weight="bold"),
        )
        label.pack(fill="both", expand=True)

    splash.update_idletasks()
    delay_ms = int(config.SPLASH_DURATION_SECONDS * 1000)
    root_window.after(delay_ms, lambda: [splash.destroy(), root_window.deiconify()])


# ----------------------------------------------------------------------
# DASHBOARD PROCESS STARTERS
# ----------------------------------------------------------------------
def _launch_dashboard_process(script_name: str, *args: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    command = [sys.executable, os.path.join(base_dir, script_name)] + list(args)
    return subprocess.Popen(command, cwd=base_dir)


# ----------------------------------------------------------------------
# LOGIN WINDOW
# ----------------------------------------------------------------------
class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.APP_NAME} - Login")
        self.geometry(config.LOGIN_WINDOW_SIZE)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.db = get_db()

        self.super_admin_process = None      # single subprocess.Popen or None
        self.admin_processes = []            # list of subprocess.Popen (up to config.MAX_ADMINS)
        self.employee_processes = []         # list of subprocess.Popen

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        container = ctk.CTkFrame(self, corner_radius=16)
        container.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(
            container, text=config.APP_NAME,
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(pady=(30, 4))
        ctk.CTkLabel(
            container, text="Selfie Attendance & Live GPS Workforce Management",
            font=ctk.CTkFont(size=13), text_color="gray70",
        ).pack(pady=(0, 24))

        self.role_var = ctk.StringVar(value="Employee")
        role_frame = ctk.CTkFrame(container, fg_color="transparent")
        role_frame.pack(pady=(0, 16))
        ctk.CTkRadioButton(role_frame, text="Employee", variable=self.role_var,
                            value="Employee").grid(row=0, column=0, padx=10)
        ctk.CTkRadioButton(role_frame, text="Admin", variable=self.role_var,
                            value="Admin").grid(row=0, column=1, padx=10)
        ctk.CTkRadioButton(role_frame, text="Super Admin", variable=self.role_var,
                            value="Super Admin").grid(row=0, column=2, padx=10)

        self.username_entry = ctk.CTkEntry(container, placeholder_text="Username", width=280)
        self.username_entry.pack(pady=8)

        self.password_entry = ctk.CTkEntry(container, placeholder_text="Password", show="*", width=280)
        self.password_entry.pack(pady=8)
        self.password_entry.bind("<Return>", lambda e: self.handle_login())

        self.status_label = ctk.CTkLabel(container, text="", text_color=config.DANGER_COLOR)
        self.status_label.pack(pady=(4, 0))

        ctk.CTkButton(container, text="Login", width=280, height=40,
                      command=self.handle_login).pack(pady=(16, 6))

        self.info_label = ctk.CTkLabel(
            container,
            text=f"Active dashboards: Super Admin 0/1 | Admin 0/{config.MAX_ADMIN_DASHBOARDS} | "
                 f"Employees 0/{config.MAX_EMPLOYEE_DASHBOARDS}",
            font=ctk.CTkFont(size=11), text_color="gray60",
        )
        self.info_label.pack(pady=(20, 0))

    # ------------------------------------------------------------------
    def _refresh_process_lists(self):
        if self.super_admin_process is not None and self.super_admin_process.poll() is not None:
            self.super_admin_process = None
        self.admin_processes = [p for p in self.admin_processes if p.poll() is None]
        self.employee_processes = [p for p in self.employee_processes if p.poll() is None]

    def _update_info_label(self):
        self._refresh_process_lists()
        super_admin_count = 1 if self.super_admin_process is not None else 0
        self.info_label.configure(
            text=f"Active dashboards: Super Admin {super_admin_count}/1 | "
                 f"Admin {len(self.admin_processes)}/{config.MAX_ADMIN_DASHBOARDS} | "
                 f"Employees {len(self.employee_processes)}/{config.MAX_EMPLOYEE_DASHBOARDS}"
        )

    # ------------------------------------------------------------------
    def handle_login(self):
        role = self.role_var.get()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        self.status_label.configure(text="")

        if not username or not password:
            self.status_label.configure(text="Please enter both username and password.")
            return

        if role == "Super Admin":
            self._handle_super_admin_login(username, password)
        elif role == "Admin":
            self._handle_admin_login(username, password)
        else:
            self._handle_employee_login(username, password)

    def _handle_super_admin_login(self, username, password):
        self._refresh_process_lists()
        if username != config.SUPER_ADMIN_USERNAME or password != config.SUPER_ADMIN_PASSWORD:
            self.status_label.configure(text="Invalid Super Admin credentials.")
            return
        if self.super_admin_process is not None:
            self.status_label.configure(text="Super Admin dashboard is already open.")
            return

        try:
            proc = _launch_dashboard_process("SuperAdmin.py")
        except Exception as exc:
            self.status_label.configure(text=f"Failed to launch Super Admin dashboard: {exc}")
            return
        self.super_admin_process = proc
        self.status_label.configure(text="Super Admin dashboard launched.", text_color=config.ACCENT_COLOR)
        self._clear_fields()
        self._update_info_label()

    def _handle_admin_login(self, username, password):
        self._refresh_process_lists()
        import utils
        admin = self.db.get_admin_by_username(username)
        if admin is None or not utils.verify_password(password, admin["password_hash"]):
            self.status_label.configure(text="Invalid admin credentials.")
            return

        already_open = any(getattr(p, "admin_id", None) == admin["id"] for p in self.admin_processes)
        if already_open:
            self.status_label.configure(text="This admin dashboard is already open.")
            return
        if len(self.admin_processes) >= config.MAX_ADMIN_DASHBOARDS:
            self.status_label.configure(
                text=f"Maximum of {config.MAX_ADMIN_DASHBOARDS} admin dashboards already open."
            )
            return

        try:
            proc = _launch_dashboard_process("Admin.py", str(admin["id"]), admin["name"])
        except Exception as exc:
            self.status_label.configure(text=f"Failed to launch admin dashboard: {exc}")
            return
        proc.admin_id = admin["id"]
        self.admin_processes.append(proc)
        self.status_label.configure(text="Admin dashboard launched.", text_color=config.ACCENT_COLOR)
        self._clear_fields()
        self._update_info_label()

    def _handle_employee_login(self, username, password):
        self._refresh_process_lists()
        import utils
        employee = self.db.get_employee_by_username(username)
        if employee is None or not utils.verify_password(password, employee["password_hash"]):
            self.status_label.configure(text="Invalid employee credentials.")
            return

        if len(self.employee_processes) >= config.MAX_EMPLOYEE_DASHBOARDS:
            self.status_label.configure(
                text=f"Maximum of {config.MAX_EMPLOYEE_DASHBOARDS} employee dashboards already open."
            )
            return

        already_open = any(
            getattr(p, "employee_id", None) == employee["id"] for p in self.employee_processes
        )
        if already_open:
            self.status_label.configure(text="This employee dashboard is already open.")
            return

        proc = None
        try:
            proc = _launch_dashboard_process(
                "Employee.py",
                str(employee["id"]),
                employee["name"],
            )
        except Exception as exc:
            self.status_label.configure(text=f"Failed to launch employee dashboard: {exc}")
            return
        proc.employee_id = employee["id"]
        self.employee_processes.append(proc)
        try:
            self.db.log_event(employee["id"], "login", f"{employee['name']} logged in")
        except Exception:
            pass  # activity logging must never block a successful login
        self.status_label.configure(text="Employee dashboard launched.", text_color=config.ACCENT_COLOR)
        self._clear_fields()
        self._update_info_label()

    def _clear_fields(self):
        self.username_entry.delete(0, "end")
        self.password_entry.delete(0, "end")

    # ------------------------------------------------------------------
    def on_close(self):
        # Closing the login window does not force-close already-open
        # dashboards; they continue to run independently as their own
        # processes until the user logs out / closes them.
        self.destroy()


# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------
def main():
    ctk.set_appearance_mode(config.APPEARANCE_MODE)
    ctk.set_default_color_theme(config.COLOR_THEME)

    # Ensure schema/singleton DB is initialized before any dashboards spawn.
    get_db()

    app = LoginWindow()
    app.withdraw()
    show_splash(app)
    app.mainloop()


if __name__ == "__main__":
    main()

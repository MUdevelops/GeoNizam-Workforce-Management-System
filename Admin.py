"""
Admin.py
Admin Dashboard for GeoNizam. Runs as its own OS process (launched from
Main.py) so it has its own independent Tkinter/CustomTkinter event loop.

Sections:
    Home                 - view & resolve incoming employee requests
    Add Employee         - create employee login (Name, Username, Password)
    Attendance Control   - open/close the selfie-attendance window and
                           Approve/Reject each submitted selfie (no AI
                           face-matching -- plain photographic review)
    Task Management      - create tasks (Title, Description) for all/one
    Notifications        - send to all or a specific employee
    Calculate Salary     - quick base + bonus% - tax% salary calculator
    Remove Employee       - deactivate an employee account
    Live GPS Tracking    - live map of each employee's real device GPS
                           location (captured via the employee's browser
                           HTML5 Geolocation API, free OpenStreetMap
                           tiles via tkintermapview); shows "The Employee is
                           currently Offline" when they are not online
    Logout               - closes this dashboard process
"""

import os
import sys
import threading

import customtkinter as ctk
from tkinter import messagebox
import cv2
from PIL import Image

import config
import utils
import realtime_hub
from database import get_db
from attendance import get_attendance_engine
from task_engine import get_task_engine
from notification_engine import get_notification_engine


class AdminDashboard(ctk.CTk):
    def __init__(self, admin_id: int = None, admin_name: str = None):
        super().__init__()
        self.db = get_db()

        # Resolve the logged-in Admin's identity. Falls back to the seeded
        # legacy Admin account if launched without arguments (keeps direct
        # `python Admin.py` invocation, e.g. in tests, working).
        self.admin_id = admin_id
        self.admin_name = admin_name
        if self.admin_id is None:
            legacy = self.db.get_admin_by_username(config.ADMIN_USERNAME)
            if legacy is not None:
                self.admin_id = legacy["id"]
                self.admin_name = legacy["name"]

        self.permissions = (
            self.db.get_admin_permissions(self.admin_id)
            if self.admin_id is not None
            else dict(config.DEFAULT_ADMIN_PERMISSIONS)
        )

        self.title(f"{config.APP_NAME} - Admin Dashboard" + (f" ({self.admin_name})" if self.admin_name else ""))
        self.geometry(config.DASHBOARD_WINDOW_SIZE)
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.attendance_engine = None
        self.task_engine = None
        self.notification_engine = None

        self._build_layout()
        self.show_view("home")

    # ------------------------------------------------------------------
    # PERMISSIONS
    # ------------------------------------------------------------------
    def _view_is_permitted(self, key: str) -> bool:
        """A view is permitted if it has no permission gate, or if ANY one
        of its gating feature keys is currently enabled for this Admin."""
        gate_keys = config.ADMIN_NAV_PERMISSION_MAP.get(key, ())
        if not gate_keys:
            return True
        return any(self.permissions.get(k, True) for k in gate_keys)

    # ------------------------------------------------------------------
    # LAYOUT
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text=config.APP_NAME, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=config.PRIMARY_GREEN_LIGHT).pack(pady=(24, 2))
        ctk.CTkLabel(sidebar, text="Admin Panel", font=ctk.CTkFont(size=13), text_color="gray70").pack(
            pady=(0, 20)
        )

        nav_items = [
            ("Home (Requests)", "home"),
            ("Add Employee", "add_employee"),
            ("Attendance Control", "attendance_control"),
            ("Task Management", "task_management"),
            ("Send Notifications", "notifications"),
            ("Calculate Salary", "calculate_salary"),
            ("Remove Employee", "remove_employee"),
            ("Live Activity Report", "live_activity"),
            ("Live GPS Tracking", "gps_tracking"),
            ("Reset All Data", "reset_data"),
        ]
        self.nav_buttons = {}
        for label, key in nav_items:
            permitted = self._view_is_permitted(key)
            btn_kwargs = dict(
                text=label if permitted else f"{label} (Locked)",
                anchor="w", fg_color="transparent",
                command=lambda k=key: self.show_view(k),
            )
            if not permitted:
                btn_kwargs["text_color"] = "gray45"
            btn = ctk.CTkButton(sidebar, **btn_kwargs)
            btn.pack(fill="x", padx=14, pady=4)
            self.nav_buttons[key] = btn

        ctk.CTkButton(
            sidebar, text="Logout", fg_color=config.DANGER_COLOR,
            hover_color="#8E2A20", command=self.on_close,
        ).pack(side="bottom", fill="x", padx=14, pady=20)

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nswe")

        self.views = {}
        self._init_view_home()
        self._init_view_add_employee()
        self._init_view_attendance_control()
        self._init_view_task_management()
        self._init_view_notifications()
        self._init_view_calculate_salary()
        self._init_view_remove_employee()
        self._init_view_live_activity()
        self._init_view_gps_tracking()
        self._init_view_reset_data()

    def show_view(self, key):
        if not self._view_is_permitted(key):
            for view_key, frame in self.views.items():
                if hasattr(frame, "on_hide"):
                    frame.on_hide()
                frame.pack_forget()
            messagebox.showwarning(
                "Permission Denied",
                "Your Super Admin has disabled this feature for your account.",
            )
            return
        for view_key, frame in self.views.items():
            if view_key == key:
                frame.pack(fill="both", expand=True, padx=24, pady=20)
                if hasattr(frame, "on_show"):
                    frame.on_show()
            else:
                if hasattr(frame, "on_hide"):
                    frame.on_hide()
                frame.pack_forget()

    # ==================================================================
    # HOME / REQUESTS
    # ==================================================================
    def _init_view_home(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["home"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Employee Requests", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )
        ctk.CTkButton(header, text="Refresh", width=100, command=lambda: self._load_requests()).pack(
            side="right"
        )

        self.requests_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.requests_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_requests

    def _ensure_engines(self):
        if self.attendance_engine is None:
            self.attendance_engine = get_attendance_engine()
        if self.task_engine is None:
            self.task_engine = get_task_engine()
        if self.notification_engine is None:
            self.notification_engine = get_notification_engine()
      

    def _load_requests(self):
        self._ensure_engines()
        for widget in self.requests_scroll.winfo_children():
            widget.destroy()

        requests = self.notification_engine.list_requests()
        if not requests:
            ctk.CTkLabel(self.requests_scroll, text="No requests yet.").pack(pady=10)
            return

        for req in requests:
            card = ctk.CTkFrame(self.requests_scroll, corner_radius=10)
            card.pack(fill="x", pady=6, padx=4)

            header = f"{req['employee_name']}  -  {req['subject']}  [{req['status'].upper()}]"
            ctk.CTkLabel(card, text=header, font=ctk.CTkFont(size=14, weight="bold")).pack(
                anchor="w", padx=12, pady=(10, 2)
            )
            ctk.CTkLabel(card, text=req["message"], wraplength=780, justify="left").pack(
                anchor="w", padx=12, pady=(0, 6)
            )
            ctk.CTkLabel(
                card, text=f"Submitted: {req['created_at']}", font=ctk.CTkFont(size=11),
                text_color="gray60",
            ).pack(anchor="w", padx=12, pady=(0, 8))

            if req["status"] == "pending":
                btn_row = ctk.CTkFrame(card, fg_color="transparent")
                btn_row.pack(anchor="w", padx=12, pady=(0, 10))
                ctk.CTkButton(
                    btn_row, text="Approve", width=100, fg_color=config.ACCENT_COLOR,
                    command=lambda r=req["id"]: self._resolve_request(r, "approved"),
                ).grid(row=0, column=0, padx=4)
                ctk.CTkButton(
                    btn_row, text="Reject", width=100, fg_color=config.DANGER_COLOR,
                    command=lambda r=req["id"]: self._resolve_request(r, "rejected"),
                ).grid(row=0, column=1, padx=4)

    def _resolve_request(self, request_id, status):
        self._ensure_engines()
        if status == "approved":
            self.notification_engine.approve_request(request_id)
        else:
            self.notification_engine.reject_request(request_id)
        self._load_requests()

    # ==================================================================
    # ADD EMPLOYEE
    # ==================================================================
    def _init_view_add_employee(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["add_employee"] = frame

        ctk.CTkLabel(frame, text="Add Employee", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 20)
        )

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(anchor="w", fill="x")

        self.emp_name_entry = ctk.CTkEntry(form, placeholder_text="Full Name", width=320)
        self.emp_name_entry.pack(padx=20, pady=(20, 10))
        self.emp_username_entry = ctk.CTkEntry(form, placeholder_text="Username", width=320)
        self.emp_username_entry.pack(padx=20, pady=10)
        self.emp_password_entry = ctk.CTkEntry(form, placeholder_text="Password", show="*", width=320)
        self.emp_password_entry.pack(padx=20, pady=10)

        self.add_employee_status = ctk.CTkLabel(form, text="")
        self.add_employee_status.pack(padx=20, pady=(4, 0))

        ctk.CTkButton(form, text="Create Employee", width=320, command=self._create_employee).pack(
            padx=20, pady=(10, 20)
        )

    def _create_employee(self):
        name = self.emp_name_entry.get().strip()
        username = self.emp_username_entry.get().strip()
        password = self.emp_password_entry.get().strip()

        if utils.is_blank(name) or utils.is_blank(username) or utils.is_blank(password):
            self.add_employee_status.configure(text="All fields are required.", text_color=config.DANGER_COLOR)
            return
        if self.db.username_exists(username):
            self.add_employee_status.configure(text="Username already exists.", text_color=config.DANGER_COLOR)
            return
        if self.admin_id is not None and self.db.count_employees_for_admin(self.admin_id) >= config.MAX_EMPLOYEES_PER_ADMIN:
            self.add_employee_status.configure(text=config.MAX_EMPLOYEE_LIMIT_MESSAGE, text_color=config.DANGER_COLOR)
            return
        if self.db.count_all_employees() >= config.MAX_EMPLOYEES_TOTAL:
            self.add_employee_status.configure(text=config.MAX_EMPLOYEE_LIMIT_MESSAGE, text_color=config.DANGER_COLOR)
            return

        self.db.add_employee(name, username, password, admin_id=self.admin_id)
        self.add_employee_status.configure(text=f"Employee '{name}' created successfully.",
                                            text_color=config.ACCENT_COLOR)
        self.emp_name_entry.delete(0, "end")
        self.emp_username_entry.delete(0, "end")
        self.emp_password_entry.delete(0, "end")
        self._refresh_employee_dropdowns()

    def _refresh_employee_dropdowns(self):
        employees = self.db.list_employees(active_only=True)
        display = [f"{e['id']} - {e['name']} ({e['username']})" for e in employees]
        for combo in (
            getattr(self, "task_employee_combo", None),
            getattr(self, "notify_employee_combo", None),
            getattr(self, "salary_employee_combo", None),
            getattr(self, "remove_employee_combo", None),
            getattr(self, "activity_employee_combo", None),
        ):
            if combo is not None:
                combo.configure(values=display)

    @staticmethod
    def _parse_employee_id(display_value: str):
        if not display_value:
            return None
        try:
            return int(display_value.split(" - ")[0])
        except (ValueError, IndexError):
            return None

    def _render_frame_to_label(self, frame_bgr, label_widget, size=(480, 360)):
        pil_img = utils.cv2_to_pil(cv2.resize(frame_bgr, size))
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        label_widget.configure(image=ctk_img, text="")
        label_widget.image = ctk_img

    # ==================================================================
    # ATTENDANCE CONTROL (Selfie queue -> Approve / Reject)
    # ==================================================================
    def _init_view_attendance_control(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["attendance_control"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(header, text="Attendance Control", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )
        ctk.CTkButton(header, text="Refresh", width=100,
                      command=lambda: self._load_attendance_status_and_records()).pack(side="right")

        control_card = ctk.CTkFrame(frame, corner_radius=12)
        control_card.pack(fill="x", pady=(0, 16))

        self.attendance_state_label = ctk.CTkLabel(
            control_card, text="Status: Unknown", font=ctk.CTkFont(size=16, weight="bold")
        )
        self.attendance_state_label.pack(anchor="w", padx=20, pady=(16, 6))

        ctk.CTkLabel(
            control_card,
            text=f'When CLOSED, employees see: "{config.ATTENDANCE_CLOSED_MESSAGE}"',
            text_color="gray60", wraplength=600, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 6))

        btn_row = ctk.CTkFrame(control_card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=20, pady=(10, 20))
        ctk.CTkButton(btn_row, text="Open Attendance", fg_color=config.ACCENT_COLOR,
                      hover_color=config.ACCENT_HOVER,
                      command=self._open_attendance).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btn_row, text="Close Attendance", fg_color=config.DANGER_COLOR,
                      hover_color=config.DANGER_HOVER,
                      command=self._close_attendance).grid(row=0, column=1, padx=6)

        ctk.CTkLabel(frame, text="Pending Selfies -- Approve / Reject",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(6, 6))
        self.pending_attendance_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent", height=260)
        self.pending_attendance_scroll.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(frame, text="Reviewed History", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(6, 6)
        )
        self.attendance_records_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.attendance_records_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_attendance_status_and_records

    def _open_attendance(self):
        self._ensure_engines()
        self.attendance_engine.open_attendance()
        self._load_attendance_status_and_records()

    def _close_attendance(self):
        self._ensure_engines()
        self.attendance_engine.close_attendance()
        self._load_attendance_status_and_records()

    def _load_attendance_status_and_records(self):
        self._ensure_engines()
        session = self.attendance_engine.get_status()
        if session:
            state = "OPEN" if session["is_open"] == 1 else "CLOSED"
            color = config.ACCENT_COLOR if session["is_open"] == 1 else config.DANGER_COLOR
            self.attendance_state_label.configure(text=f"Status: {state}", text_color=color)

        # --- Pending queue ---
        for widget in self.pending_attendance_scroll.winfo_children():
            widget.destroy()
        pending = self.attendance_engine.list_pending()
        if not pending:
            ctk.CTkLabel(self.pending_attendance_scroll, text="No selfies waiting for review.").pack(pady=8)
        for rec in pending:
            row = ctk.CTkFrame(self.pending_attendance_scroll, corner_radius=10)
            row.pack(fill="x", pady=4, padx=2)

            thumb_label = ctk.CTkLabel(row, text="", width=70, height=70, cursor="hand2")
            thumb_label.pack(side="left", padx=10, pady=10)
            try:
                if rec["image_path"] and os.path.exists(rec["image_path"]):
                    pil_img = Image.open(rec["image_path"]).resize((70, 70))
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(70, 70))
                    thumb_label.configure(image=ctk_img)
                    thumb_label.image = ctk_img
            except Exception:
                pass
            thumb_label.bind("<Button-1>", lambda e, r=rec: self._open_selfie_preview(r))

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=(4, 10), pady=10)
            ctk.CTkLabel(info, text=f"{rec['employee_name']}  |  {rec['timestamp']}",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
            loc_text = (f"GPS: {rec['location_label']} ({rec['latitude']:.3f}, {rec['longitude']:.3f})"
                        if rec["latitude"] is not None else "GPS: unavailable")
            ctk.CTkLabel(info, text=loc_text, text_color="gray60", font=ctk.CTkFont(size=11)).pack(anchor="w")

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=10)
            ctk.CTkButton(btns, text="View Full Screen", width=130,
                          fg_color="transparent", border_width=1,
                          command=lambda r=rec: self._open_selfie_preview(r)
                          ).pack(pady=2)
            action_row = ctk.CTkFrame(btns, fg_color="transparent")
            action_row.pack(pady=(4, 0))
            ctk.CTkButton(action_row, text="Approve", width=90, fg_color=config.ACCENT_COLOR,
                          hover_color=config.ACCENT_HOVER,
                          command=lambda rid=rec["id"]: self._review_attendance(rid, "approved")
                          ).pack(side="left", padx=(0, 4))
            ctk.CTkButton(action_row, text="Reject", width=90, fg_color=config.DANGER_COLOR,
                          hover_color=config.DANGER_HOVER,
                          command=lambda rid=rec["id"]: self._review_attendance(rid, "rejected")
                          ).pack(side="left")

        # --- Reviewed history ---
        for widget in self.attendance_records_scroll.winfo_children():
            widget.destroy()
        records = [r for r in self.attendance_engine.all_history() if r["status"] != "pending"]
        if not records:
            ctk.CTkLabel(self.attendance_records_scroll, text="No reviewed records yet.").pack(pady=8)
            return
        for rec in records[:200]:
            is_approved = rec["status"] == "approved"
            color = config.ACCENT_COLOR if is_approved else config.DANGER_COLOR
            display_status = "APPROVED" if is_approved else "REJECTED"
            row = ctk.CTkFrame(self.attendance_records_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)

            thumb_label = ctk.CTkLabel(row, text="", width=40, height=40, cursor="hand2")
            thumb_label.pack(side="left", padx=(10, 4), pady=6)
            try:
                if rec["image_path"] and os.path.exists(rec["image_path"]):
                    pil_img = Image.open(rec["image_path"]).resize((40, 40))
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(40, 40))
                    thumb_label.configure(image=ctk_img)
                    thumb_label.image = ctk_img
            except Exception:
                pass
            thumb_label.bind("<Button-1>", lambda e, r=rec: self._open_selfie_preview(r))

            text = f"{rec['employee_name']}  |  {rec['timestamp']}  |  {display_status}"
            ctk.CTkLabel(row, text=text, text_color=color).pack(side="left", padx=(4, 12), pady=8)
            ctk.CTkButton(row, text="View Full Screen", width=130, height=26,
                          fg_color="transparent", border_width=1,
                          command=lambda r=rec: self._open_selfie_preview(r)
                          ).pack(side="right", padx=10, pady=4)

    def _review_attendance(self, record_id: int, status: str):
        self._ensure_engines()
        if status == "approved":
            self.attendance_engine.approve(record_id)
        else:
            self.attendance_engine.reject(record_id)
        self._load_attendance_status_and_records()

    def _open_selfie_preview(self, rec):
        """Opens the submitted selfie in a full-screen preview window,
        showing the exact capturing time, employee and GPS details.
        Works for both pending and already-reviewed records."""
        if not rec["image_path"] or not os.path.exists(rec["image_path"]):
            messagebox.showinfo("Selfie Preview", "This selfie image could not be found on disk.")
            return

        try:
            pil_img = Image.open(rec["image_path"])
        except Exception:
            messagebox.showinfo("Selfie Preview", "This selfie image could not be opened.")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Selfie Preview -- {rec['employee_name']}")
        win.configure(fg_color="#000000")
        win.attributes("-fullscreen", True)
        win.lift()
        win.focus_force()

        status = str(rec["status"]).upper() if "status" in rec.keys() else ""
        status_color = {
            "APPROVED": config.ACCENT_COLOR,
            "PENDING": config.WARNING_COLOR,
            "REJECTED": config.DANGER_COLOR,
        }.get(status, "gray70")

        top_bar = ctk.CTkFrame(win, fg_color="#0E1712", height=64, corner_radius=0)
        top_bar.pack(fill="x", side="top")
        top_bar.pack_propagate(False)

        info_col = ctk.CTkFrame(top_bar, fg_color="transparent")
        info_col.pack(side="left", padx=20, pady=6)
        ctk.CTkLabel(info_col, text=rec["employee_name"],
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(info_col, text=f"Captured at: {rec['timestamp']}",
                     font=ctk.CTkFont(size=13), text_color=config.PRIMARY_GREEN_LIGHT).pack(anchor="w")

        if status:
            ctk.CTkLabel(top_bar, text=status, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=status_color).pack(side="left", padx=10)

        ctk.CTkButton(top_bar, text="Close (Esc)", width=110, fg_color=config.DANGER_COLOR,
                      hover_color=config.DANGER_HOVER, command=win.destroy).pack(side="right", padx=20, pady=12)

        try:
            loc_text = (f"GPS: {rec['location_label']} "
                        f"({rec['latitude']:.5f}, {rec['longitude']:.5f})"
                        if rec["latitude"] is not None else "GPS: unavailable")
        except Exception:
            loc_text = "GPS: unavailable"
        ctk.CTkLabel(win, text=loc_text, text_color="gray60",
                     font=ctk.CTkFont(size=12)).pack(side="top", anchor="w", padx=20, pady=(6, 0))

        image_holder = ctk.CTkFrame(win, fg_color="#000000")
        image_holder.pack(fill="both", expand=True)

        image_label = ctk.CTkLabel(image_holder, text="")
        image_label.pack(expand=True)

        def render_scaled(event=None):
            max_w = max(win.winfo_width() - 80, 200)
            max_h = max(win.winfo_height() - 180, 200)
            img_w, img_h = pil_img.size
            scale = min(max_w / img_w, max_h / img_h)
            new_size = (max(int(img_w * scale), 1), max(int(img_h * scale), 1))
            resized = pil_img.resize(new_size)
            ctk_img = ctk.CTkImage(light_image=resized, dark_image=resized, size=new_size)
            image_label.configure(image=ctk_img)
            image_label.image = ctk_img

        win.after(80, render_scaled)

        def exit_fullscreen(event=None):
            win.destroy()

        win.bind("<Escape>", exit_fullscreen)

    # ==================================================================
    # TASK MANAGEMENT
    # ==================================================================
    def _init_view_task_management(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["task_management"] = frame

        ctk.CTkLabel(frame, text="Task Management", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 16)
        )

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(fill="x", pady=(0, 16))

        self.task_title_entry = ctk.CTkEntry(form, placeholder_text="Task Title", width=400)
        self.task_title_entry.pack(anchor="w", padx=20, pady=(20, 10))

        self.task_description_box = ctk.CTkTextbox(form, width=400, height=90)
        self.task_description_box.pack(anchor="w", padx=20, pady=10)

        assign_row = ctk.CTkFrame(form, fg_color="transparent")
        assign_row.pack(anchor="w", padx=20, pady=10)
        ctk.CTkLabel(assign_row, text="Assign to:").grid(row=0, column=0, padx=(0, 8))
        self.task_employee_combo = ctk.CTkComboBox(assign_row, values=["All Employees"], width=280)
        self.task_employee_combo.set("All Employees")
        self.task_employee_combo.grid(row=0, column=1)

        self.task_status_label = ctk.CTkLabel(form, text="")
        self.task_status_label.pack(anchor="w", padx=20)

        ctk.CTkButton(form, text="Create Task", width=200, command=self._create_task).pack(
            anchor="w", padx=20, pady=(10, 20)
        )

        ctk.CTkLabel(frame, text="Task Progress", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(6, 6)
        )
        self.task_progress_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.task_progress_scroll.pack(fill="both", expand=True)

        frame.on_show = self._on_task_view_show

    def _on_task_view_show(self):
        self._refresh_employee_dropdowns()
        current_values = list(self.task_employee_combo.cget("values"))
        if "All Employees" not in current_values:
            self.task_employee_combo.configure(values=["All Employees"] + current_values)
        self._load_task_progress()

    def _create_task(self):
        self._ensure_engines()
        title = self.task_title_entry.get().strip()
        description = self.task_description_box.get("1.0", "end").strip()
        target = self.task_employee_combo.get()

        if utils.is_blank(title):
            self.task_status_label.configure(text="Task title is required.", text_color=config.DANGER_COLOR)
            return

        assigned_to = None if target == "All Employees" else self._parse_employee_id(target)
        self.task_engine.create_task(title, description, assigned_to)
        self.task_status_label.configure(text="Task created and assigned.", text_color=config.ACCENT_COLOR)
        self.task_title_entry.delete(0, "end")
        self.task_description_box.delete("1.0", "end")
        self._load_task_progress()

    def _load_task_progress(self):
        self._ensure_engines()
        for widget in self.task_progress_scroll.winfo_children():
            widget.destroy()

        assignments = self.task_engine.list_all_assignments()
        if not assignments:
            ctk.CTkLabel(self.task_progress_scroll, text="No tasks yet.").pack(pady=8)
            return

        for a in assignments:
            duration = utils.format_duration(self.task_engine.live_elapsed_seconds(a))
            row = ctk.CTkFrame(self.task_progress_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)
            text = (f"{a['title']}  |  {a['employee_name']}  |  {a['status'].upper()}  |  "
                    f"Time: {duration}")
            ctk.CTkLabel(row, text=text, wraplength=800, justify="left").pack(anchor="w", padx=12, pady=8)



    # ==================================================================
    # NOTIFICATIONS
    # ==================================================================
    def _init_view_notifications(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["notifications"] = frame

        ctk.CTkLabel(frame, text="Send Notifications", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 16)
        )

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(fill="x", pady=(0, 16))

        self.notify_title_entry = ctk.CTkEntry(form, placeholder_text="Notification Title", width=400)
        self.notify_title_entry.pack(anchor="w", padx=20, pady=(20, 10))

        self.notify_message_box = ctk.CTkTextbox(form, width=400, height=90)
        self.notify_message_box.pack(anchor="w", padx=20, pady=10)

        target_row = ctk.CTkFrame(form, fg_color="transparent")
        target_row.pack(anchor="w", padx=20, pady=10)
        self.notify_target_var = ctk.StringVar(value="all")
        ctk.CTkRadioButton(target_row, text="All Employees", variable=self.notify_target_var,
                           value="all").grid(row=0, column=0, padx=(0, 16))
        ctk.CTkRadioButton(target_row, text="Specific Employee", variable=self.notify_target_var,
                           value="specific").grid(row=0, column=1, padx=(0, 8))
        self.notify_employee_combo = ctk.CTkComboBox(target_row, values=[], width=240)
        self.notify_employee_combo.grid(row=0, column=2)

        self.notify_status_label = ctk.CTkLabel(form, text="")
        self.notify_status_label.pack(anchor="w", padx=20)

        ctk.CTkButton(form, text="Send Notification", width=200, command=self._send_notification).pack(
            anchor="w", padx=20, pady=(10, 20)
        )

        ctk.CTkLabel(frame, text="Sent Notifications", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(6, 6)
        )
        self.notify_history_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.notify_history_scroll.pack(fill="both", expand=True)

        frame.on_show = self._on_notifications_view_show

    def _on_notifications_view_show(self):
        self._refresh_employee_dropdowns()
        self._load_notification_history()

    def _send_notification(self):
        self._ensure_engines()
        title = self.notify_title_entry.get().strip()
        message = self.notify_message_box.get("1.0", "end").strip()
        if utils.is_blank(title) or utils.is_blank(message):
            self.notify_status_label.configure(text="Title and message are required.",
                                                text_color=config.DANGER_COLOR)
            return

        if self.notify_target_var.get() == "all":
            self.notification_engine.send_to_all(title, message)
        else:
            employee_id = self._parse_employee_id(self.notify_employee_combo.get())
            if employee_id is None:
                self.notify_status_label.configure(text="Select an employee.", text_color=config.DANGER_COLOR)
                return
            self.notification_engine.send_to_employee(title, message, employee_id)

        self.notify_status_label.configure(text="Notification sent.", text_color=config.ACCENT_COLOR)
        self.notify_title_entry.delete(0, "end")
        self.notify_message_box.delete("1.0", "end")
        self._load_notification_history()

    def _load_notification_history(self):
        self._ensure_engines()
        for widget in self.notify_history_scroll.winfo_children():
            widget.destroy()

        notifications = self.notification_engine.list_all()
        if not notifications:
            ctk.CTkLabel(self.notify_history_scroll, text="No notifications sent yet.").pack(pady=8)
            return

        for n in notifications:
            target_text = "All Employees" if n["target"] == "all" else f"Employee #{n['target']}"
            row = ctk.CTkFrame(self.notify_history_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(
                row, text=f"{n['title']}  -> {target_text}  ({n['created_at']})",
                font=ctk.CTkFont(weight="bold"),
            ).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=n["message"], wraplength=800, justify="left").pack(
                anchor="w", padx=12, pady=(0, 8)
            )

    # ==================================================================
    # CALCULATE SALARY (simple base + bonus% - tax% calculator; no
    # persistence, purely a calculation helper as requested)
    # ==================================================================
    def _init_view_calculate_salary(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["calculate_salary"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(header, text="Calculate Salary", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(anchor="w", fill="x")

        ctk.CTkLabel(form, text="Employee (optional):").grid(
            row=0, column=0, sticky="w", padx=20, pady=(20, 8)
        )
        self.salary_employee_combo = ctk.CTkComboBox(form, values=[], width=300)
        self.salary_employee_combo.grid(row=0, column=1, sticky="w", padx=(0, 20), pady=(20, 8))

        ctk.CTkLabel(form, text="Base Salary:").grid(row=1, column=0, sticky="w", padx=20, pady=8)
        self.salary_base_entry = ctk.CTkEntry(form, placeholder_text="e.g. 50000", width=300)
        self.salary_base_entry.grid(row=1, column=1, sticky="w", padx=(0, 20), pady=8)

        ctk.CTkLabel(form, text="Bonus (%):").grid(row=2, column=0, sticky="w", padx=20, pady=8)
        self.salary_bonus_entry = ctk.CTkEntry(form, placeholder_text="e.g. 10", width=300)
        self.salary_bonus_entry.grid(row=2, column=1, sticky="w", padx=(0, 20), pady=8)

        ctk.CTkLabel(form, text="Tax (%):").grid(row=3, column=0, sticky="w", padx=20, pady=8)
        self.salary_tax_entry = ctk.CTkEntry(form, placeholder_text="e.g. 12", width=300)
        self.salary_tax_entry.grid(row=3, column=1, sticky="w", padx=(0, 20), pady=8)

        self.salary_status_label = ctk.CTkLabel(form, text="", wraplength=520, justify="left")
        self.salary_status_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=20, pady=(4, 0))

        ctk.CTkButton(form, text="Calculate", width=200, command=self._calculate_salary).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=20, pady=(10, 20)
        )

        result_card = ctk.CTkFrame(frame, corner_radius=12)
        result_card.pack(fill="x", pady=(16, 0))
        ctk.CTkLabel(
            result_card, text="Total Salary", font=ctk.CTkFont(size=14), text_color="gray70"
        ).pack(anchor="w", padx=20, pady=(16, 2))
        self.salary_result_label = ctk.CTkLabel(
            result_card, text="--", font=ctk.CTkFont(size=28, weight="bold")
        )
        self.salary_result_label.pack(anchor="w", padx=20, pady=(0, 18))

        frame.on_show = self._refresh_employee_dropdowns

    def _calculate_salary(self):
        base_text = self.salary_base_entry.get().strip()
        bonus_text = self.salary_bonus_entry.get().strip() or "0"
        tax_text = self.salary_tax_entry.get().strip() or "0"

        try:
            base = float(base_text)
            bonus_pct = float(bonus_text)
            tax_pct = float(tax_text)
        except ValueError:
            self.salary_status_label.configure(
                text="Enter valid numbers for Base Salary, Bonus % and Tax %.",
                text_color=config.DANGER_COLOR,
            )
            self.salary_result_label.configure(text="--")
            return

        if base < 0 or bonus_pct < 0 or tax_pct < 0:
            self.salary_status_label.configure(
                text="Values cannot be negative.", text_color=config.DANGER_COLOR
            )
            self.salary_result_label.configure(text="--")
            return

        bonus_amount = base * (bonus_pct / 100.0)
        tax_amount = base * (tax_pct / 100.0)
        total = base + bonus_amount - tax_amount

        employee_display = self.salary_employee_combo.get().strip()
        who = employee_display if employee_display else "Employee"

        self.salary_status_label.configure(
            text=(f"Base: {base:,.2f}   +   Bonus ({bonus_pct:g}%): {bonus_amount:,.2f}   -   "
                  f"Tax ({tax_pct:g}%): {tax_amount:,.2f}"),
            text_color="gray70",
        )
        self.salary_result_label.configure(text=f"{who}  -  {total:,.2f}")

    # ==================================================================
    # REMOVE EMPLOYEE
    # ==================================================================
    def _init_view_remove_employee(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["remove_employee"] = frame

        ctk.CTkLabel(frame, text="Remove Employee", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 16)
        )

        row = ctk.CTkFrame(frame, corner_radius=12)
        row.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(row, text="Select Employee:").pack(side="left", padx=(20, 8), pady=20)
        self.remove_employee_combo = ctk.CTkComboBox(row, values=[], width=300)
        self.remove_employee_combo.pack(side="left", pady=20)
        ctk.CTkButton(row, text="Remove", fg_color=config.DANGER_COLOR,
                      command=self._remove_employee).pack(side="left", padx=20, pady=20)

        self.remove_status_label = ctk.CTkLabel(frame, text="")
        self.remove_status_label.pack(anchor="w")

        ctk.CTkLabel(frame, text="Active Employees", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(16, 6)
        )
        self.employee_list_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.employee_list_scroll.pack(fill="both", expand=True)

        frame.on_show = self._on_remove_employee_view_show

    def _on_remove_employee_view_show(self):
        self._refresh_employee_dropdowns()
        self._load_employee_list()

    def _load_employee_list(self):
        for widget in self.employee_list_scroll.winfo_children():
            widget.destroy()

        employees = self.db.list_employees(active_only=True)
        if not employees:
            ctk.CTkLabel(self.employee_list_scroll, text="No employees yet.").pack(pady=8)
            return

        for e in employees:
            row = ctk.CTkFrame(self.employee_list_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(row, text=f"{e['name']}  (@{e['username']})  |  since {e['created_at']}").pack(
                anchor="w", padx=12, pady=8
            )

    def _remove_employee(self):
        employee_id = self._parse_employee_id(self.remove_employee_combo.get())
        if employee_id is None:
            self.remove_status_label.configure(text="Select an employee to remove.",
                                                text_color=config.DANGER_COLOR)
            return
        employee = self.db.get_employee_by_id(employee_id)
        confirm = messagebox.askyesno(
            "Confirm Removal",
            f"Are you sure you want to remove '{employee['name']}'? "
            "Their historical records will be preserved.",
        )
        if not confirm:
            return
        self.db.remove_employee(employee_id)
        self.remove_status_label.configure(text=f"Employee '{employee['name']}' removed.",
                                            text_color=config.ACCENT_COLOR)
        self._refresh_employee_dropdowns()
        self._load_employee_list()

    # ==================================================================
    # LIVE ACTIVITY REPORT + CURRENT ACTIVITY MONITOR
    # ==================================================================
    _EVENT_ICON = {
        "login": "Logged In", "logout": "Logged Out",
        "attendance_taken": "Attendance", "task_started": "Task Started",
        "task_paused": "Task Paused", "task_resumed": "Task Resumed",
        "task_completed": "Task Completed",
    }
    _LIVE_ACTIVITY_REFRESH_MS = 3000

    def _init_view_live_activity(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["live_activity"] = frame
        self._live_activity_refresh_job = None

        ctk.CTkLabel(frame, text="Live Activity Report", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ctk.CTkLabel(
            frame, text="Updates automatically every few seconds -- no restart needed.",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(anchor="w", pady=(0, 14))

        # ---- Current Activity Monitor ----
        monitor = ctk.CTkFrame(frame, corner_radius=12)
        monitor.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(monitor, text="Current Activity Monitor", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 6)
        )
        ctk.CTkLabel(monitor, text="Select Employee:").grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        self.activity_employee_combo = ctk.CTkComboBox(
            monitor, values=[], width=280, command=self._on_activity_employee_selected
        )
        self.activity_employee_combo.grid(row=1, column=1, sticky="w", pady=(0, 12))

        self.activity_monitor_labels = {}
        fields = [
            "Current Status", "Current Task", "Current Session Duration", "Login Time",
            "Attendance Status", "Working Time Today", "Pause Duration", "Last Activity",
        ]
        monitor_grid = ctk.CTkFrame(monitor, fg_color="transparent")
        monitor_grid.grid(row=2, column=0, columnspan=2, sticky="we", padx=16, pady=(0, 16))
        for i, field in enumerate(fields):
            r, c = divmod(i, 2)
            cell = ctk.CTkFrame(monitor_grid, corner_radius=8)
            cell.grid(row=r, column=c, sticky="we", padx=6, pady=6)
            monitor_grid.grid_columnconfigure(c, weight=1)
            ctk.CTkLabel(cell, text=field, font=ctk.CTkFont(size=11), text_color="gray60").pack(
                anchor="w", padx=12, pady=(8, 0)
            )
            value_label = ctk.CTkLabel(cell, text="-", font=ctk.CTkFont(size=14, weight="bold"))
            value_label.pack(anchor="w", padx=12, pady=(0, 8))
            self.activity_monitor_labels[field] = value_label

        # ---- Live Activity Report table ----
        ctk.CTkLabel(frame, text="Employee Activity Timeline", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(4, 6)
        )
        self.activity_log_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.activity_log_scroll.pack(fill="both", expand=True)

        frame.on_show = self._on_live_activity_view_show
        frame.on_hide = self._on_live_activity_view_hide

    def _on_live_activity_view_show(self):
        self._refresh_employee_dropdowns()
        self._refresh_live_activity()

    def _on_live_activity_view_hide(self):
        if self._live_activity_refresh_job is not None:
            self.after_cancel(self._live_activity_refresh_job)
            self._live_activity_refresh_job = None

    def _refresh_live_activity(self):
        self._load_activity_log()
        self._update_activity_monitor()
        # reschedule only while this view is the one on screen
        self._live_activity_refresh_job = self.after(
            self._LIVE_ACTIVITY_REFRESH_MS, self._refresh_live_activity
        )

    def _load_activity_log(self):
        for widget in self.activity_log_scroll.winfo_children():
            widget.destroy()

        rows = self.db.list_activity_log(limit=300)
        if not rows:
            ctk.CTkLabel(self.activity_log_scroll, text="No activity recorded yet.").pack(pady=10)
            return

        header = ctk.CTkFrame(self.activity_log_scroll, fg_color="transparent")
        header.pack(fill="x", padx=4)
        for text, w in (("Time", 150), ("Employee", 180), ("Event", 140), ("Description", 320)):
            ctk.CTkLabel(header, text=text, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color="gray60", width=w, anchor="w").pack(side="left", padx=4)

        for row in rows:
            line = ctk.CTkFrame(self.activity_log_scroll, corner_radius=6)
            line.pack(fill="x", pady=2, padx=2)
            ctk.CTkLabel(line, text=row["created_at"], width=150, anchor="w").pack(
                side="left", padx=4, pady=6
            )
            ctk.CTkLabel(line, text=row["employee_name"], width=180, anchor="w").pack(
                side="left", padx=4, pady=6
            )
            ctk.CTkLabel(
                line, text=self._EVENT_ICON.get(row["event_type"], row["event_type"]),
                width=140, anchor="w",
            ).pack(side="left", padx=4, pady=6)
            ctk.CTkLabel(line, text=row["description"] or "-", width=320, anchor="w").pack(
                side="left", padx=4, pady=6
            )

    def _on_activity_employee_selected(self, _value=None):
        self._update_activity_monitor()

    def _update_activity_monitor(self):
        employee_id = self._parse_employee_id(self.activity_employee_combo.get())
        labels = self.activity_monitor_labels
        if employee_id is None:
            for v in labels.values():
                v.configure(text="-")
            return

        self._ensure_engines()

        # Current task (in-progress or paused assignment, if any)
        assignments = self.db.list_task_assignments_for_employee(employee_id)
        current = next((a for a in assignments if a["status"] == "in_progress"), None)
        paused_task = next((a for a in assignments if a["status"] == "paused"), None)
        active_assignment = current or paused_task

        # Login/logout -> current status
        last_login = self.db.get_last_login_time(employee_id)
        last_event = self.db.get_last_event(employee_id)
        logged_in = last_event is not None and last_event["event_type"] != "logout"

        if not logged_in:
            status_text = "Offline"
        elif current is not None:
            status_text = "Working"
        elif paused_task is not None:
            status_text = "Paused"
        else:
            status_text = "Idle (Logged In)"

        labels["Current Status"].configure(text=status_text)
        labels["Current Task"].configure(
            text=active_assignment["title"] if active_assignment else "None"
        )

        if active_assignment is not None:
            duration = self.task_engine.live_elapsed_seconds(active_assignment)
            labels["Current Session Duration"].configure(text=utils.format_duration(duration))
        else:
            labels["Current Session Duration"].configure(text="-")

        labels["Login Time"].configure(text=last_login or "-")

        today_records = self.db.list_attendance_records(employee_id)
        today = utils.today_str()
        today_attendance = next(
            (r for r in today_records if r["timestamp"].startswith(today)), None
        )
        if today_attendance is not None:
            labels["Attendance Status"].configure(
                text=f"{today_attendance['status'].upper()}"
            )
        else:
            labels["Attendance Status"].configure(text="Not marked today")

        working_seconds = self.db.get_today_working_seconds(employee_id)
        labels["Working Time Today"].configure(text=utils.format_duration(working_seconds))

        paused_seconds = paused_task["total_seconds"] if paused_task else 0.0
        labels["Pause Duration"].configure(
            text=utils.format_duration(paused_seconds) if paused_task else "-"
        )

        labels["Last Activity"].configure(
            text=f"{last_event['created_at']} - {self._EVENT_ICON.get(last_event['event_type'], last_event['event_type'])}"
            if last_event else "-"
        )

    # ==================================================================
    # LIVE GPS TRACKING (free OpenStreetMap tiles via tkintermapview --
    # no API key, no paid tier)
    # ==================================================================
    # Real-time pushes (realtime_hub) update the map instantly; this
    # interval is only a low-frequency safety net in case a push is
    # missed (e.g. hub briefly unreachable), so it no longer needs to be
    # a fast poll.
    _GPS_REFRESH_MS = 10000

    def _init_view_gps_tracking(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["gps_tracking"] = frame
        self._gps_refresh_job = None
        self._gps_hub_subscriber = None
        self._gps_roster_signature = None

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Live GPS Tracking", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )
        ctk.CTkButton(header, text="Refresh", width=100,
                      command=self._refresh_gps_tracking).pack(side="right")

        ctk.CTkLabel(
            frame,
            text="Real device GPS location, captured via each employee's browser (HTML5 "
                 "Geolocation API -- never estimated from IP address) and shown on free "
                 "OpenStreetMap map tiles. Updates live, pushed the instant a new fix "
                 "arrives -- no manual refresh needed.",
            text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True)

        # --- Left: employee list with online/offline indicator ---
        roster = ctk.CTkFrame(body, width=260, corner_radius=12)
        roster.pack(side="left", fill="y", padx=(0, 16), pady=4)
        roster.pack_propagate(False)
        ctk.CTkLabel(roster, text="Employees", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=14, pady=(14, 8)
        )
        self.gps_roster_scroll = ctk.CTkScrollableFrame(roster, fg_color="transparent")
        self.gps_roster_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 10))

        # --- Right: map area / offline overlay ---
        map_area = ctk.CTkFrame(body, corner_radius=12, fg_color=config.CARD_BG)
        map_area.pack(side="left", fill="both", expand=True, pady=4)

        self.gps_selected_label = ctk.CTkLabel(
            map_area, text="Select an employee to view their live location.",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.gps_selected_label.pack(anchor="w", padx=16, pady=(14, 6))

        # NOTE: tkintermapview's canvas reads its parent's background color
        # directly (for its rounded-corner drawing) -- CustomTkinter's
        # "transparent" is a virtual concept that plain Tk canvases don't
        # understand, which raises `_tkinter.TclError: unknown color name
        # "transparent"` the moment the map widget is created. Use a solid
        # color (matching the card behind it) instead of "transparent".
        self.gps_map_container = ctk.CTkFrame(map_area, fg_color=config.CARD_BG)
        self.gps_map_container.pack(fill="both", expand=True, padx=10, pady=(0, 14))

        self.gps_map_widget = None
        self.gps_offline_overlay = None
        self._gps_selected_employee_id = None
        self._init_map_widget()

        frame.on_show = self._on_gps_view_show
        frame.on_hide = self._on_gps_view_hide

    def _on_gps_view_show(self):
        self._refresh_gps_tracking()
        if self._gps_hub_subscriber is None:
            self._gps_hub_subscriber = realtime_hub.Subscriber(self._on_gps_push_event)

    def _on_gps_view_hide(self):
        if self._gps_refresh_job is not None:
            self.after_cancel(self._gps_refresh_job)
            self._gps_refresh_job = None
        if self._gps_hub_subscriber is not None:
            self._gps_hub_subscriber.stop()
            self._gps_hub_subscriber = None

    def _on_gps_push_event(self, event: dict):
        """Called from the hub Subscriber's background thread whenever any
        employee's location changes -- marshal onto the Tkinter main
        thread before touching any widgets."""
        if event.get("type") == "location_update":
            self.after(0, self._refresh_gps_tracking)

    def _init_map_widget(self):
        """Creates the tkintermapview widget (free/open OpenStreetMap tiles).
        Falls back to a friendly message if the optional package isn't
        installed, instead of crashing the dashboard."""
        try:
            import tkintermapview
        except ImportError:
            ctk.CTkLabel(
                self.gps_map_container,
                text="Live map view requires the free 'tkintermapview' package.\n"
                     "Install it with:  pip install tkintermapview",
                text_color=config.WARNING_COLOR, justify="center",
            ).pack(expand=True, fill="both")
            return

        self.gps_map_widget = tkintermapview.TkinterMapView(
            self.gps_map_container, corner_radius=10
        )
        self.gps_map_widget.set_tile_server(config.GPS_MAP_TILE_SERVER, max_zoom=19)
        self.gps_map_widget.set_position(config.GPS_DEFAULT_LAT, config.GPS_DEFAULT_LON)
        self.gps_map_widget.set_zoom(config.GPS_DEFAULT_ZOOM)
        self.gps_map_widget.pack(fill="both", expand=True)

        # Offline overlay label, stacked on top of the map, shown/hidden as needed.
        self.gps_offline_overlay = ctk.CTkLabel(
            self.gps_map_container, text="The Employee is currently Offline",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="white",
            fg_color="#1A1A1A", corner_radius=10,
        )

    def _is_online(self, loc_row) -> bool:
        if loc_row is None or loc_row["online"] != 1 or loc_row["updated_at"] is None:
            return False
        age = utils.elapsed_seconds(loc_row["updated_at"])
        return age <= config.LOCATION_ONLINE_TIMEOUT_SECONDS

    def _refresh_gps_tracking(self):
        if self._gps_refresh_job is not None:
            self.after_cancel(self._gps_refresh_job)
            self._gps_refresh_job = None

        rows = self.db.list_employee_locations()

        # Only tear down and rebuild the roster widgets when something
        # actually changed (name/online-status/updated_at) -- avoids
        # flicker on every safety-net poll tick, which is what a "no full
        # page refresh" live view should feel like in a desktop app.
        signature = tuple(
            (r["employee_id"], r["employee_name"], self._is_online(r), r["updated_at"]) for r in rows
        )
        if signature != self._gps_roster_signature:
            self._gps_roster_signature = signature
            for widget in self.gps_roster_scroll.winfo_children():
                widget.destroy()

            if not rows:
                ctk.CTkLabel(self.gps_roster_scroll, text="No employees yet.").pack(pady=8)
            for row in rows:
                online = self._is_online(row)
                dot_color = config.ACCENT_COLOR if online else config.OFFLINE_COLOR
                status_text = "Online" if online else "Offline"
                item = ctk.CTkFrame(self.gps_roster_scroll, corner_radius=8, cursor="hand2")
                item.pack(fill="x", pady=3, padx=2)
                ctk.CTkLabel(item, text="\u25CF", text_color=dot_color, width=16).pack(side="left", padx=(8, 2), pady=8)
                label = ctk.CTkLabel(item, text=f"{row['employee_name']}\n{status_text}",
                                      justify="left", anchor="w", font=ctk.CTkFont(size=12))
                label.pack(side="left", fill="x", expand=True, pady=6)
                for widget in (item, label):
                    widget.bind("<Button-1>", lambda e, eid=row["employee_id"]: self._select_gps_employee(eid))

        if self._gps_selected_employee_id is not None:
            self._select_gps_employee(self._gps_selected_employee_id)

        # Reschedule as a low-frequency safety net only -- real-time
        # pushes from realtime_hub.Subscriber drive most updates instantly.
        self._gps_refresh_job = self.after(self._GPS_REFRESH_MS, self._refresh_gps_tracking)

    def _select_gps_employee(self, employee_id: int):
        self._gps_selected_employee_id = employee_id
        emp = self.db.get_employee_by_id(employee_id)
        loc = self.db.get_employee_location(employee_id)
        online = self._is_online(loc)
        name = emp["name"] if emp else "Employee"

        if online:
            details = []
            if loc["address"] or loc["location_label"]:
                details.append(loc["address"] or loc["location_label"])
            if loc["latitude"] is not None:
                details.append(f"{loc['latitude']:.5f}, {loc['longitude']:.5f}")
            if loc["accuracy"] is not None:
                details.append(f"\u00b1{loc['accuracy']:.0f}m")
            if loc["speed"]:
                details.append(f"{loc['speed'] * 3.6:.1f} km/h")
            details.append(f"updated {loc['updated_at']}")
            self.gps_selected_label.configure(
                text=f"{name} -- Online -- " + "  |  ".join(details),
                text_color=config.ACCENT_COLOR,
            )
        else:
            self.gps_selected_label.configure(
                text=f"{name} -- Offline", text_color=config.OFFLINE_COLOR,
            )

        if self.gps_map_widget is None:
            return  # tkintermapview not installed; roster + status text still work

        if online and loc["latitude"] is not None and loc["longitude"] is not None:
            if self.gps_offline_overlay is not None:
                self.gps_offline_overlay.place_forget()
            self.gps_map_widget.delete_all_marker()
            self.gps_map_widget.set_position(loc["latitude"], loc["longitude"])
            self.gps_map_widget.set_zoom(config.GPS_DEFAULT_ZOOM)
            marker_text = name
            if loc["address"] or loc["location_label"]:
                marker_text += f" ({loc['address'] or loc['location_label']})"
            self.gps_map_widget.set_marker(loc["latitude"], loc["longitude"], text=marker_text)
        else:
            # Employee offline: keep the map visible as a background and
            # overlay the required offline message on top of it.
            self.gps_map_widget.delete_all_marker()
            if self.gps_offline_overlay is not None:
                self.gps_offline_overlay.place(relx=0.5, rely=0.5, anchor="center")

    # ==================================================================
    # RESET ALL DATA
    # ==================================================================
    def _init_view_reset_data(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["reset_data"] = frame

        ctk.CTkLabel(frame, text="Reset All Data", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=config.DANGER_COLOR).pack(anchor="w", pady=(0, 10))

        warning_box = ctk.CTkFrame(frame, corner_radius=12, fg_color="#2A1414")
        warning_box.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(
            warning_box,
            text=(
                "WARNING\n\n"
                "This action will permanently delete:\n"
                "  - Employees\n"
                "  - Attendance\n"
                "  - Tasks\n"
                "  - Activity Logs\n"
                "  - Notifications\n"
                "  - AI Face Profiles\n"
                "  - Reports\n\n"
                "The database and system counters will be reinitialized, returning\n"
                "the software to its initial setup state. This cannot be undone."
            ),
            justify="left", anchor="w", text_color="#E1A9A0",
        ).pack(anchor="w", padx=20, pady=20)

        self.reset_status_label = ctk.CTkLabel(frame, text="")
        self.reset_status_label.pack(anchor="w", pady=(0, 10))

        ctk.CTkButton(
            frame, text="Reset All Data", fg_color=config.DANGER_COLOR, hover_color="#8E2A20",
            width=220, height=44, command=self._perform_reset_all_data,
        ).pack(anchor="w")

    def _perform_reset_all_data(self):
        confirm = messagebox.askyesno(
            "Confirm Reset",
            "This action will permanently delete ALL employees, attendance, tasks, "
            "activity logs, notifications, AI face profiles and reports, and cannot "
            "be undone.\n\nContinue?",
            icon="warning",
        )
        if not confirm:
            return

        try:
            self.db.reset_all_data()
            utils.wipe_data_files()
        except Exception as exc:
            self.reset_status_label.configure(
                text=f"Reset failed: {exc}", text_color=config.DANGER_COLOR
            )
            return

        self.reset_status_label.configure(
            text="All data has been reset. The application is back to its initial setup state.",
            text_color=config.ACCENT_COLOR,
        )
        # Every list/dropdown in this session may reference now-deleted rows --
        # refresh everything currently loaded so the UI never shows stale data.
        self._refresh_employee_dropdowns()
        for key in ("home", "remove_employee", "task_management", "notifications", "live_activity"):
            view = self.views.get(key)
            if view is not None and hasattr(view, "on_show"):
                view.on_show()

    # ==================================================================
    # CLOSE / LOGOUT
    # ==================================================================
    def on_close(self):
        self._on_live_activity_view_hide()
        self._on_gps_view_hide()
        self.destroy()
        sys.exit(0)


def launch_admin_dashboard(admin_id: int = None, admin_name: str = None):
    ctk.set_appearance_mode(config.APPEARANCE_MODE)
    ctk.set_default_color_theme(config.COLOR_THEME)
    app = AdminDashboard(admin_id=admin_id, admin_name=admin_name)
    app.mainloop()


if __name__ == "__main__":
    _admin_id, _admin_name = None, None
    if len(sys.argv) >= 3:
        try:
            _admin_id = int(sys.argv[1])
            _admin_name = sys.argv[2]
        except (ValueError, IndexError):
            _admin_id, _admin_name = None, None
    launch_admin_dashboard(admin_id=_admin_id, admin_name=_admin_name)

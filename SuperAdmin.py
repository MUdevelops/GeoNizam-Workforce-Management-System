"""
SuperAdmin.py
Super Admin Dashboard for GeoNizam. Runs as its own OS process (launched
from Main.py), exactly like Admin.py and Employee.py, so it has its own
independent Tkinter/CustomTkinter event loop while sharing the same
permanent SQLite database on disk.

The Super Admin has complete control over the Admin layer of the system:

    Dashboard Home         - headline counters (Admins, Employees, pending
                              work) across the whole system
    Profile                - read-only identity card for the Super Admin
    Notifications           - broadcast a notification to every Employee
    Add Admin               - create a new Admin account (max 3 total)
    Remove Admin             - deactivate an Admin (their Employees are
                              unassigned, never deleted)
    Edit Admin               - change an Admin's name / username / password
    Manage Admin Permissions - per-Admin ON/OFF feature toggles, saved to
                              SQLite and enforced live by Admin.py
    View System Statistics  - Admins/Employees/requests/attendance/tasks
    View All Employees      - every Employee in the system, with which
                              Admin manages them
    Logout                  - closes this dashboard process (its own OS
                              process, so there is no "back button" into it
                              once closed)
"""

import sys

import customtkinter as ctk
from tkinter import messagebox

import config
from database import get_db
from notification_engine import get_notification_engine


class SuperAdminDashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.APP_NAME} - Super Admin Dashboard")
        self.geometry(config.DASHBOARD_WINDOW_SIZE)
        self.minsize(1080, 680)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.db = get_db()
        self.notification_engine = None

        self.selected_admin_id = None  # currently selected Admin in Manage Permissions / Edit Admin

        self._build_layout()
        self.show_view("home")

    # ------------------------------------------------------------------
    # LAYOUT
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text=config.APP_NAME, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=config.PRIMARY_GREEN_LIGHT).pack(pady=(24, 2))
        ctk.CTkLabel(sidebar, text="Super Admin Panel", font=ctk.CTkFont(size=13), text_color="gray70").pack(
            pady=(0, 20)
        )

        nav_items = [
            ("Dashboard Home", "home"),
            ("Profile", "profile"),
            ("Notifications", "notifications"),
            ("Add Admin", "add_admin"),
            ("Edit Admin", "edit_admin"),
            ("Remove Admin", "remove_admin"),
            ("Manage Admin Permissions", "permissions"),
            ("View System Statistics", "statistics"),
            ("View All Employees", "all_employees"),
        ]
        self.nav_buttons = {}
        for label, key in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", fg_color="transparent",
                command=lambda k=key: self.show_view(k),
            )
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
        self._init_view_profile()
        self._init_view_notifications()
        self._init_view_add_admin()
        self._init_view_edit_admin()
        self._init_view_remove_admin()
        self._init_view_permissions()
        self._init_view_statistics()
        self._init_view_all_employees()

    def show_view(self, key):
        for view_key, frame in self.views.items():
            if view_key == key:
                frame.pack(fill="both", expand=True, padx=24, pady=20)
                if hasattr(frame, "on_show"):
                    frame.on_show()
            else:
                if hasattr(frame, "on_hide"):
                    frame.on_hide()
                frame.pack_forget()

    def _ensure_engines(self):
        if self.notification_engine is None:
            self.notification_engine = get_notification_engine()

    # ==================================================================
    # DASHBOARD HOME
    # ==================================================================
    def _init_view_home(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["home"] = frame

        ctk.CTkLabel(frame, text="Dashboard Home", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 20)
        )

        self.home_cards_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.home_cards_frame.pack(fill="x")

        frame.on_show = self._refresh_home
        self._home_card_labels = {}

    def _stat_card(self, parent, title, value, column):
        card = ctk.CTkFrame(parent, corner_radius=12, width=220, height=110)
        card.grid(row=0, column=column, padx=10, pady=6, sticky="nswe")
        card.grid_propagate(False)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=13), text_color="gray70").pack(
            anchor="w", padx=16, pady=(16, 2)
        )
        value_label = ctk.CTkLabel(card, text=str(value), font=ctk.CTkFont(size=28, weight="bold"),
                                    text_color=config.PRIMARY_GREEN_LIGHT)
        value_label.pack(anchor="w", padx=16)
        return value_label

    def _refresh_home(self):
        for widget in self.home_cards_frame.winfo_children():
            widget.destroy()
        stats = self.db.get_system_statistics()
        self._stat_card(self.home_cards_frame, f"Admins (max {stats['max_admins']})", stats["admins"], 0)
        self._stat_card(self.home_cards_frame, f"Employees (max {stats['max_employees']})", stats["employees"], 1)
        self._stat_card(self.home_cards_frame, "Pending Requests", stats["pending_requests"], 2)
        self._stat_card(self.home_cards_frame, "Pending Attendance", stats["pending_attendance"], 3)

    # ==================================================================
    # PROFILE
    # ==================================================================
    def _init_view_profile(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["profile"] = frame

        ctk.CTkLabel(frame, text="Profile", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 20)
        )

        card = ctk.CTkFrame(frame, corner_radius=12)
        card.pack(anchor="w", fill="x")

        for label_text, value_text in (
            ("Role", "Super Admin"),
            ("Username", config.SUPER_ADMIN_USERNAME),
            ("Admin Limit", f"{config.MAX_ADMINS} Admins"),
            ("Employee Limit", f"{config.MAX_EMPLOYEES_PER_ADMIN} per Admin "
                                f"({config.MAX_EMPLOYEES_TOTAL} total)"),
        ):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=8)
            ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(size=13, weight="bold"), width=140,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value_text, anchor="w").pack(side="left")

    # ==================================================================
    # NOTIFICATIONS (broadcast to all Employees)
    # ==================================================================
    def _init_view_notifications(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["notifications"] = frame

        ctk.CTkLabel(frame, text="Send Notification (All Employees)",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", pady=(0, 20))

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(anchor="w", fill="x")

        self.notif_title_entry = ctk.CTkEntry(form, placeholder_text="Title", width=420)
        self.notif_title_entry.pack(padx=20, pady=(20, 10))
        self.notif_message_box = ctk.CTkTextbox(form, width=420, height=100)
        self.notif_message_box.pack(padx=20, pady=10)

        self.notif_status = ctk.CTkLabel(form, text="")
        self.notif_status.pack(padx=20, pady=(4, 0))

        ctk.CTkButton(form, text="Send Notification", width=420, command=self._send_notification).pack(
            padx=20, pady=(10, 20)
        )

    def _send_notification(self):
        self._ensure_engines()
        title = self.notif_title_entry.get().strip()
        message = self.notif_message_box.get("1.0", "end").strip()
        if not title or not message:
            self.notif_status.configure(text="Title and message are required.", text_color=config.DANGER_COLOR)
            return
        self.notification_engine.send_to_all(title, message)
        self.notif_status.configure(text="Notification sent to all Employees.", text_color=config.ACCENT_COLOR)
        self.notif_title_entry.delete(0, "end")
        self.notif_message_box.delete("1.0", "end")

    # ==================================================================
    # ADD ADMIN
    # ==================================================================
    def _init_view_add_admin(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["add_admin"] = frame

        ctk.CTkLabel(frame, text="Add Admin", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 4)
        )
        self.add_admin_limit_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=12), text_color="gray70")
        self.add_admin_limit_label.pack(anchor="w", pady=(0, 16))

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(anchor="w", fill="x")

        self.admin_name_entry = ctk.CTkEntry(form, placeholder_text="Full Name", width=320)
        self.admin_name_entry.pack(padx=20, pady=(20, 10))
        self.admin_username_entry = ctk.CTkEntry(form, placeholder_text="Username", width=320)
        self.admin_username_entry.pack(padx=20, pady=10)
        self.admin_password_entry = ctk.CTkEntry(form, placeholder_text="Password", show="*", width=320)
        self.admin_password_entry.pack(padx=20, pady=10)

        self.add_admin_status = ctk.CTkLabel(form, text="")
        self.add_admin_status.pack(padx=20, pady=(4, 0))

        self.add_admin_btn = ctk.CTkButton(form, text="Create Admin", width=320, command=self._create_admin)
        self.add_admin_btn.pack(padx=20, pady=(10, 20))

        frame.on_show = self._refresh_add_admin_limit

    def _refresh_add_admin_limit(self):
        count = self.db.count_admins(active_only=True)
        self.add_admin_limit_label.configure(text=f"Admins: {count}/{config.MAX_ADMINS}")
        if count >= config.MAX_ADMINS:
            self.add_admin_btn.configure(state="disabled")
            self.add_admin_status.configure(text=config.MAX_ADMIN_LIMIT_MESSAGE, text_color=config.DANGER_COLOR)
        else:
            self.add_admin_btn.configure(state="normal")
            self.add_admin_status.configure(text="")

    def _create_admin(self):
        import utils
        name = self.admin_name_entry.get().strip()
        username = self.admin_username_entry.get().strip()
        password = self.admin_password_entry.get().strip()

        if utils.is_blank(name) or utils.is_blank(username) or utils.is_blank(password):
            self.add_admin_status.configure(text="All fields are required.", text_color=config.DANGER_COLOR)
            return
        if self.db.count_admins(active_only=True) >= config.MAX_ADMINS:
            self.add_admin_status.configure(text=config.MAX_ADMIN_LIMIT_MESSAGE, text_color=config.DANGER_COLOR)
            return
        if self.db.username_exists(username):
            self.add_admin_status.configure(text="Username already exists.", text_color=config.DANGER_COLOR)
            return

        self.db.add_admin(name, username, password)
        self.add_admin_status.configure(text=f"Admin '{name}' created successfully.",
                                         text_color=config.ACCENT_COLOR)
        self.admin_name_entry.delete(0, "end")
        self.admin_username_entry.delete(0, "end")
        self.admin_password_entry.delete(0, "end")
        self._refresh_add_admin_limit()

    # ==================================================================
    # EDIT ADMIN
    # ==================================================================
    def _init_view_edit_admin(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["edit_admin"] = frame

        ctk.CTkLabel(frame, text="Edit Admin", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 20)
        )

        picker = ctk.CTkFrame(frame, fg_color="transparent")
        picker.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(picker, text="Select Admin:").pack(side="left", padx=(0, 10))
        self.edit_admin_var = ctk.StringVar(value="")
        self.edit_admin_menu = ctk.CTkOptionMenu(picker, variable=self.edit_admin_var, values=["-"],
                                                   command=self._on_edit_admin_selected, width=260)
        self.edit_admin_menu.pack(side="left")

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(anchor="w", fill="x")

        self.edit_admin_name_entry = ctk.CTkEntry(form, placeholder_text="Full Name", width=320)
        self.edit_admin_name_entry.pack(padx=20, pady=(20, 10))
        self.edit_admin_username_entry = ctk.CTkEntry(form, placeholder_text="Username", width=320)
        self.edit_admin_username_entry.pack(padx=20, pady=10)
        self.edit_admin_password_entry = ctk.CTkEntry(
            form, placeholder_text="New Password (leave blank to keep current)", show="*", width=320
        )
        self.edit_admin_password_entry.pack(padx=20, pady=10)

        self.edit_admin_status = ctk.CTkLabel(form, text="")
        self.edit_admin_status.pack(padx=20, pady=(4, 0))

        ctk.CTkButton(form, text="Save Changes", width=320, command=self._save_admin_edits).pack(
            padx=20, pady=(10, 20)
        )

        self._edit_admin_lookup = {}  # display label -> admin_id
        frame.on_show = self._refresh_edit_admin_list

    def _refresh_edit_admin_list(self):
        admins = self.db.list_admins(active_only=True)
        self._edit_admin_lookup = {f"{a['name']} ({a['username']})": a["id"] for a in admins}
        values = list(self._edit_admin_lookup.keys()) or ["No Admins yet"]
        self.edit_admin_menu.configure(values=values)
        if values and values[0] != "No Admins yet":
            self.edit_admin_var.set(values[0])
            self._on_edit_admin_selected(values[0])
        else:
            self.edit_admin_var.set(values[0])
            self.edit_admin_name_entry.delete(0, "end")
            self.edit_admin_username_entry.delete(0, "end")

    def _on_edit_admin_selected(self, label):
        admin_id = self._edit_admin_lookup.get(label)
        if admin_id is None:
            return
        admin = self.db.get_admin_by_id(admin_id)
        if admin is None:
            return
        self.edit_admin_name_entry.delete(0, "end")
        self.edit_admin_name_entry.insert(0, admin["name"])
        self.edit_admin_username_entry.delete(0, "end")
        self.edit_admin_username_entry.insert(0, admin["username"])
        self.edit_admin_password_entry.delete(0, "end")
        self.edit_admin_status.configure(text="")

    def _save_admin_edits(self):
        import utils
        label = self.edit_admin_var.get()
        admin_id = self._edit_admin_lookup.get(label)
        if admin_id is None:
            self.edit_admin_status.configure(text="Select an Admin first.", text_color=config.DANGER_COLOR)
            return

        name = self.edit_admin_name_entry.get().strip()
        username = self.edit_admin_username_entry.get().strip()
        password = self.edit_admin_password_entry.get().strip()

        if utils.is_blank(name) or utils.is_blank(username):
            self.edit_admin_status.configure(text="Name and username are required.", text_color=config.DANGER_COLOR)
            return

        current = self.db.get_admin_by_id(admin_id)
        if username != current["username"] and self.db.username_exists(username):
            self.edit_admin_status.configure(text="Username already exists.", text_color=config.DANGER_COLOR)
            return

        self.db.update_admin(admin_id, name=name, username=username,
                              password=password if password else None)
        self.edit_admin_status.configure(text="Admin updated successfully.", text_color=config.ACCENT_COLOR)
        self.edit_admin_password_entry.delete(0, "end")
        self._refresh_edit_admin_list()

    # ==================================================================
    # REMOVE ADMIN
    # ==================================================================
    def _init_view_remove_admin(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["remove_admin"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Remove Admin", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Refresh", width=100, command=lambda: self._load_remove_admin_list()).pack(
            side="right"
        )

        self.remove_admin_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.remove_admin_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_remove_admin_list

    def _load_remove_admin_list(self):
        for widget in self.remove_admin_scroll.winfo_children():
            widget.destroy()

        admins = self.db.list_admins(active_only=True)
        if not admins:
            ctk.CTkLabel(self.remove_admin_scroll, text="No Admins yet.").pack(pady=10)
            return

        for admin in admins:
            emp_count = self.db.count_employees_for_admin(admin["id"])
            card = ctk.CTkFrame(self.remove_admin_scroll, corner_radius=10)
            card.pack(fill="x", pady=6, padx=4)

            ctk.CTkLabel(
                card, text=f"{admin['name']}  ({admin['username']})  -  {emp_count} Employee(s)",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(side="left", padx=12, pady=12)

            ctk.CTkButton(
                card, text="Remove", width=100, fg_color=config.DANGER_COLOR, hover_color="#8E2A20",
                command=lambda a=admin: self._confirm_remove_admin(a),
            ).pack(side="right", padx=12, pady=12)

    def _confirm_remove_admin(self, admin):
        confirmed = messagebox.askyesno(
            "Remove Admin",
            f"Remove Admin '{admin['name']}'? Their Employees will be unassigned "
            f"(kept, not deleted) and can be reassigned to another Admin later.",
        )
        if not confirmed:
            return
        self.db.remove_admin(admin["id"])
        self._load_remove_admin_list()
        self._refresh_add_admin_limit()

    # ==================================================================
    # MANAGE ADMIN PERMISSIONS
    # ==================================================================
    def _init_view_permissions(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["permissions"] = frame

        ctk.CTkLabel(frame, text="Manage Admin Permissions", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 20)
        )

        picker = ctk.CTkFrame(frame, fg_color="transparent")
        picker.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(picker, text="Select Admin:").pack(side="left", padx=(0, 10))
        self.perm_admin_var = ctk.StringVar(value="")
        self.perm_admin_menu = ctk.CTkOptionMenu(picker, variable=self.perm_admin_var, values=["-"],
                                                   command=self._on_permissions_admin_selected, width=260)
        self.perm_admin_menu.pack(side="left")

        self.perm_toggles_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent", height=380)
        self.perm_toggles_frame.pack(fill="both", expand=True, pady=(10, 10))

        self.perm_status = ctk.CTkLabel(frame, text="")
        self.perm_status.pack(anchor="w")

        ctk.CTkButton(frame, text="Save Permissions", width=220, command=self._save_permissions).pack(
            anchor="w", pady=(10, 0)
        )

        self._perm_admin_lookup = {}
        self._perm_switches = {}  # feature_key -> CTkSwitch
        frame.on_show = self._refresh_permissions_admin_list

    def _refresh_permissions_admin_list(self):
        admins = self.db.list_admins(active_only=True)
        self._perm_admin_lookup = {f"{a['name']} ({a['username']})": a["id"] for a in admins}
        values = list(self._perm_admin_lookup.keys()) or ["No Admins yet"]
        self.perm_admin_menu.configure(values=values)
        if values and values[0] != "No Admins yet":
            self.perm_admin_var.set(values[0])
            self._on_permissions_admin_selected(values[0])
        else:
            self.perm_admin_var.set(values[0])
            self._render_permission_switches(None)

    def _on_permissions_admin_selected(self, label):
        admin_id = self._perm_admin_lookup.get(label)
        self._render_permission_switches(admin_id)

    def _render_permission_switches(self, admin_id):
        for widget in self.perm_toggles_frame.winfo_children():
            widget.destroy()
        self._perm_switches = {}
        self.selected_admin_id = admin_id
        self.perm_status.configure(text="")

        if admin_id is None:
            ctk.CTkLabel(self.perm_toggles_frame, text="No Admin selected.").pack(pady=10)
            return

        permissions = self.db.get_admin_permissions(admin_id)
        for feature_key, display_label in config.ADMIN_PERMISSION_FEATURES:
            row = ctk.CTkFrame(self.perm_toggles_frame, fg_color="transparent")
            row.pack(fill="x", pady=4, padx=4)
            switch_var = ctk.BooleanVar(value=permissions.get(feature_key, True))
            switch = ctk.CTkSwitch(row, text=display_label, variable=switch_var,
                                    onvalue=True, offvalue=False)
            switch.pack(anchor="w")
            self._perm_switches[feature_key] = switch_var

    def _save_permissions(self):
        if self.selected_admin_id is None:
            self.perm_status.configure(text="Select an Admin first.", text_color=config.DANGER_COLOR)
            return
        permissions = {key: var.get() for key, var in self._perm_switches.items()}
        self.db.set_admin_permissions_bulk(self.selected_admin_id, permissions)
        self.perm_status.configure(
            text="Permissions saved. Changes apply the next time this Admin logs in.",
            text_color=config.ACCENT_COLOR,
        )

    # ==================================================================
    # VIEW SYSTEM STATISTICS
    # ==================================================================
    def _init_view_statistics(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["statistics"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="System Statistics", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Refresh", width=100, command=lambda: self._refresh_statistics()).pack(
            side="right"
        )

        self.stats_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.stats_scroll.pack(fill="both", expand=True)

        frame.on_show = self._refresh_statistics

    def _refresh_statistics(self):
        for widget in self.stats_scroll.winfo_children():
            widget.destroy()
        stats = self.db.get_system_statistics()
        rows = [
            ("Admins", f"{stats['admins']} / {stats['max_admins']}"),
            ("Employees", f"{stats['employees']} / {stats['max_employees']}"),
            ("Employees Currently Online", stats["online_employees"]),
            ("Pending Employee Requests", stats["pending_requests"]),
            ("Pending Attendance Reviews", stats["pending_attendance"]),
            ("Total Tasks Created", stats["total_tasks"]),
        ]
        for label, value in rows:
            card = ctk.CTkFrame(self.stats_scroll, corner_radius=10)
            card.pack(fill="x", pady=5, padx=4)
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=14)).pack(side="left", padx=16, pady=12)
            ctk.CTkLabel(card, text=str(value), font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=config.PRIMARY_GREEN_LIGHT).pack(side="right", padx=16, pady=12)

    # ==================================================================
    # VIEW ALL EMPLOYEES
    # ==================================================================
    def _init_view_all_employees(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["all_employees"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="All Employees", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Refresh", width=100, command=lambda: self._refresh_all_employees()).pack(
            side="right"
        )

        self.all_employees_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.all_employees_scroll.pack(fill="both", expand=True)

        frame.on_show = self._refresh_all_employees

    def _refresh_all_employees(self):
        for widget in self.all_employees_scroll.winfo_children():
            widget.destroy()

        employees = self.db.list_employees(active_only=True)
        if not employees:
            ctk.CTkLabel(self.all_employees_scroll, text="No Employees yet.").pack(pady=10)
            return

        admin_names = {a["id"]: a["name"] for a in self.db.list_admins(active_only=False)}
        for emp in employees:
            managed_by = admin_names.get(emp["admin_id"], "Unassigned")
            card = ctk.CTkFrame(self.all_employees_scroll, corner_radius=10)
            card.pack(fill="x", pady=4, padx=4)
            ctk.CTkLabel(
                card, text=f"{emp['name']}  ({emp['username']})  -  managed by {managed_by}",
                font=ctk.CTkFont(size=13),
            ).pack(anchor="w", padx=14, pady=10)

    # ==================================================================
    # CLOSE / LOGOUT
    # ==================================================================
    def on_close(self):
        # Each dashboard is its own OS process (see Main.py), so closing
        # this window fully terminates the process -- there is no way to
        # navigate back into it afterwards without logging in again.
        self.destroy()
        sys.exit(0)


def launch_super_admin_dashboard():
    ctk.set_appearance_mode(config.APPEARANCE_MODE)
    ctk.set_default_color_theme(config.COLOR_THEME)
    app = SuperAdminDashboard()
    app.mainloop()


if __name__ == "__main__":
    launch_super_admin_dashboard()

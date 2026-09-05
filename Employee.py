"""
Employee.py
Employee Dashboard for GeoNizam. Runs as its own OS process (launched from
Main.py), one process per logged-in employee (max 7 concurrent).

Sections:
    Home              - view notifications sent by admin
    Selfie Attendance - plain selfie capture (no AI face-matching). Only
                        enabled while the Admin has the attendance window
                        OPEN -- "Selfie attendance only takes when it is
                        open". Submitted selfies + the employee's real
                        GPS location are queued for the Admin to Approve
                        or Reject.
    Tasks             - Start / Pause / Resume / Finish assigned tasks
    Send Requests     - submit a request to the admin
    Logout            - closes this dashboard process

While this dashboard is open, a local-only HTTP server (gps_realtime.py)
opens a page in the employee's own browser that uses the real HTML5
Geolocation API to continuously stream the device's actual GPS position
back into the app (never estimated from IP address), so the Admin's Live
GPS Tracking screen shows this employee's true location; on logout the
employee is marked Offline.
"""

import os
import sys
import threading
import time

import customtkinter as ctk
from tkinter import messagebox
import cv2

import config
import utils
import gps_realtime
from database import get_db
from attendance import get_attendance_engine
from task_engine import get_task_engine
from notification_engine import get_notification_engine
from activity_engine import get_activity_engine


class EmployeeDashboard(ctk.CTk):
    def __init__(self, employee_id: int, employee_name: str):
        super().__init__()
        self.employee_id = employee_id
        self.employee_name = employee_name

        self.title(f"{config.APP_NAME} - {employee_name}")
        self.geometry(config.DASHBOARD_WINDOW_SIZE)
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.db = get_db()
        self.attendance_engine = None
        self.task_engine = None
        self.notification_engine = None
        self.activity_engine = None

        # camera / capture state for the Selfie Attendance view
        self.camera = None
        self.camera_running = False
        self.live_frame = None
        self.final_frame = None  # frozen selfie awaiting submit/retake

        self._build_layout()
        self.show_view("home")

        # Real device-GPS capture: starts a local-only HTTP server and
        # opens it in the employee's browser, which uses the real HTML5
        # Geolocation API (navigator.geolocation.watchPosition) to stream
        # the device's actual GPS fix back into this process. This is the
        # only source of location GeoNizam uses now -- see gps_realtime.py
        # for the full explanation of why the old IP-based lookup always
        # showed the wrong city.
        self.gps = gps_realtime.GPSCaptureServer(
            self.employee_id, self.employee_name, self.db,
            on_update=self._on_gps_update,
        )
        self.gps.start()
        self.gps.open_browser()
        self._gps_ui_job = self.after(1000, self._refresh_gps_status_ui)

    # ------------------------------------------------------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text=config.APP_NAME, font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=config.PRIMARY_GREEN_LIGHT).pack(pady=(24, 2))
        ctk.CTkLabel(sidebar, text=self.employee_name, font=ctk.CTkFont(size=13),
                     text_color="gray70", wraplength=180).pack(pady=(0, 20))

        nav_items = [
            ("Home (Notifications)", "home"),
            ("Selfie Attendance", "attendance"),
            ("Tasks", "tasks"),
            ("Send Requests", "requests"),
        ]
        for label, key in nav_items:
            ctk.CTkButton(
                sidebar, text=label, anchor="w", fg_color="transparent",
                command=lambda k=key: self.show_view(k),
            ).pack(fill="x", padx=14, pady=4)

        ctk.CTkButton(
            sidebar, text="Logout", fg_color=config.DANGER_COLOR,
            hover_color="#8E2A20", command=self.on_close,
        ).pack(side="bottom", fill="x", padx=14, pady=20)

        self.content_wrap = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content_wrap.grid(row=0, column=1, sticky="nswe")
        self.content_wrap.grid_columnconfigure(0, weight=1)
        self.content_wrap.grid_rowconfigure(1, weight=1)

        # Persistent Live GPS status strip, visible on every view -- shows
        # the real device-GPS state (waiting / active / error) so the
        # employee always knows whether they're actually being tracked.
        self.gps_status_bar = ctk.CTkFrame(self.content_wrap, corner_radius=10, fg_color=config.CARD_BG)
        self.gps_status_bar.grid(row=0, column=0, sticky="we", padx=24, pady=(16, 0))
        self.gps_status_label = ctk.CTkLabel(
            self.gps_status_bar, text="Live GPS: starting...", anchor="w",
            font=ctk.CTkFont(size=12), text_color="gray70",
        )
        self.gps_status_label.pack(side="left", fill="x", expand=True, padx=14, pady=8)
        ctk.CTkButton(
            self.gps_status_bar, text="Open Location Tab", width=140, height=26,
            fg_color="transparent", border_width=1, font=ctk.CTkFont(size=11),
            command=lambda: self.gps.open_browser(),
        ).pack(side="right", padx=10, pady=6)

        self.content = ctk.CTkFrame(self.content_wrap, corner_radius=0, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nswe")

        self.views = {}
        self._init_view_home()
        self._init_view_attendance()
        self._init_view_tasks()
        self._init_view_requests()

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

    # ==================================================================
    # LIVE GPS STATUS (real HTML5-geolocation fixes from gps_realtime.py)
    # ==================================================================
    def _on_gps_update(self, snapshot: dict):
        """Called from the local GPS HTTP server's thread -- never touch
        Tkinter widgets directly here, just hand off to the main thread."""
        self.after(0, lambda: self._render_gps_status(snapshot))

    def _refresh_gps_status_ui(self):
        self._render_gps_status(self.gps.get_latest())
        self._gps_ui_job = self.after(2000, self._refresh_gps_status_ui)

    def _render_gps_status(self, snapshot: dict):
        status = snapshot.get("status")
        if status == "active" and snapshot.get("lat") is not None:
            parts = [f"Live GPS: \u00b1{round(snapshot['accuracy'])}m" if snapshot.get("accuracy") else "Live GPS: active"]
            if snapshot.get("speed"):
                parts.append(f"{snapshot['speed'] * 3.6:.1f} km/h")
            if snapshot.get("address"):
                parts.append(snapshot["address"])
            elif snapshot.get("lat") is not None:
                parts.append(f"({snapshot['lat']:.5f}, {snapshot['lon']:.5f})")
            if snapshot.get("updated_at"):
                parts.append(f"updated {snapshot['updated_at']}")
            self.gps_status_label.configure(text="  |  ".join(parts), text_color=config.PRIMARY_GREEN_LIGHT)
        elif status == "error":
            self.gps_status_label.configure(
                text=f"Live GPS: {snapshot.get('error_message') or 'error'} "
                     f"-- click \"Open Location Tab\" and allow permission.",
                text_color=config.WARNING_COLOR,
            )
        elif status == "stopped":
            self.gps_status_label.configure(text="Live GPS: stopped", text_color="gray60")
        else:
            self.gps_status_label.configure(
                text="Live GPS: waiting for the browser tab to grant location permission...",
                text_color="gray60",
            )

    def _init_view_home(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["home"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Notifications", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )
        ctk.CTkButton(header, text="Refresh", width=100, command=self._load_notifications).pack(
            side="right"
        )

        self.notifications_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.notifications_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_notifications

    def _ensure_engines(self):
        if self.attendance_engine is None:
            self.attendance_engine = get_attendance_engine()
        if self.task_engine is None:
            self.task_engine = get_task_engine()
        if self.notification_engine is None:
            self.notification_engine = get_notification_engine()
        if self.activity_engine is None:
            self.activity_engine = get_activity_engine()

    def _load_notifications(self):
        self._ensure_engines()
        for widget in self.notifications_scroll.winfo_children():
            widget.destroy()

        notifications = self.notification_engine.list_for_employee(self.employee_id)
        if not notifications:
            ctk.CTkLabel(self.notifications_scroll, text="No notifications yet.").pack(pady=10)
            return

        for n in notifications:
            card = ctk.CTkFrame(self.notifications_scroll, corner_radius=10)
            card.pack(fill="x", pady=6, padx=4)
            ctk.CTkLabel(card, text=n["title"], font=ctk.CTkFont(size=15, weight="bold")).pack(
                anchor="w", padx=14, pady=(10, 2)
            )
            ctk.CTkLabel(card, text=n["message"], wraplength=780, justify="left").pack(
                anchor="w", padx=14, pady=(0, 6)
            )
            ctk.CTkLabel(card, text=n["created_at"], font=ctk.CTkFont(size=11), text_color="gray60").pack(
                anchor="w", padx=14, pady=(0, 10)
            )

    # ==================================================================
    # SELFIE ATTENDANCE (plain photo capture -> Admin Approve/Reject)
    # ==================================================================
    def _init_view_attendance(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["attendance"] = frame

        ctk.CTkLabel(frame, text="Selfie Attendance", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ctk.CTkLabel(
            frame, text="Capture a plain selfie and submit it -- no AI face matching is "
                        "performed. The Admin reviews and Approves or Rejects every submission.",
            wraplength=760, justify="left", text_color="gray70",
        ).pack(anchor="w", pady=(0, 8))

        self.attendance_session_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.attendance_session_label.pack(anchor="w", pady=(0, 12))

        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True)

        self.attendance_video_label = ctk.CTkLabel(body, text="Camera preview will appear here",
                                                     width=480, height=360, fg_color="#132018")
        self.attendance_video_label.pack(side="left", padx=(0, 20), pady=6)

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.pack(side="left", fill="y", pady=6)

        self.attendance_guidance_label = ctk.CTkLabel(
            controls, text="Camera not started.", wraplength=280, justify="left",
            font=ctk.CTkFont(size=12), text_color="gray70",
        )
        self.attendance_guidance_label.pack(anchor="w", pady=(0, 10))

        self.attendance_location_label = ctk.CTkLabel(
            controls, text="Location: not captured yet", wraplength=280, justify="left",
            font=ctk.CTkFont(size=12), text_color="gray60",
        )
        self.attendance_location_label.pack(anchor="w", pady=(0, 14))

        self.start_camera_btn = ctk.CTkButton(controls, text="Start Camera",
                                               fg_color=config.ACCENT_COLOR,
                                               hover_color=config.ACCENT_HOVER,
                                               command=self._start_attendance_camera)
        self.start_camera_btn.pack(fill="x", pady=6)

        self.capture_btn = ctk.CTkButton(controls, text="Capture Selfie", state="disabled",
                                          fg_color=config.ACCENT_COLOR,
                                          hover_color=config.ACCENT_HOVER,
                                          command=self._capture_final_selfie)
        self.capture_btn.pack(fill="x", pady=6)

        self.retake_btn = ctk.CTkButton(controls, text="Retake", state="disabled",
                                         fg_color="transparent", border_width=1,
                                         command=self._retake_selfie)
        self.retake_btn.pack(fill="x", pady=6)

        self.submit_btn = ctk.CTkButton(controls, text="Submit for Approval", state="disabled",
                                         fg_color=config.ACCENT_COLOR,
                                         hover_color=config.ACCENT_HOVER,
                                         command=self._submit_attendance)
        self.submit_btn.pack(fill="x", pady=6)

        self.attendance_result_label = ctk.CTkLabel(controls, text="", wraplength=280, justify="left")
        self.attendance_result_label.pack(pady=(12, 0))

        ctk.CTkLabel(frame, text="My Recent Attendance", font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", pady=(18, 6)
        )
        self.my_attendance_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent", height=140)
        self.my_attendance_scroll.pack(fill="x")

        frame.on_show = self._on_attendance_view_show
        frame.on_hide = self._stop_attendance_camera

    def _on_attendance_view_show(self):
        self._ensure_engines()
        session = self.attendance_engine.get_status()
        window_open = bool(session and session["is_open"] == 1)
        if window_open:
            self.attendance_session_label.configure(
                text="Attendance window is OPEN -- you may capture and submit a selfie.",
                text_color=config.ACCENT_COLOR,
            )
        else:
            self.attendance_session_label.configure(
                text=config.ATTENDANCE_CLOSED_MESSAGE, text_color=config.DANGER_COLOR,
            )
        self.start_camera_btn.configure(state="normal" if window_open else "disabled")
        self._load_my_attendance()

    def _load_my_attendance(self):
        self._ensure_engines()
        for widget in self.my_attendance_scroll.winfo_children():
            widget.destroy()
        records = self.attendance_engine.history_for_employee(self.employee_id)
        if not records:
            ctk.CTkLabel(self.my_attendance_scroll, text="No attendance submitted yet.").pack(pady=6)
            return
        status_colors = {
            "pending": config.WARNING_COLOR,
            "approved": config.ACCENT_COLOR,
            "rejected": config.DANGER_COLOR,
        }
        for rec in records[:30]:
            color = status_colors.get(rec["status"], "gray70")
            row = ctk.CTkFrame(self.my_attendance_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)
            text = f"{rec['timestamp']}  |  {rec['status'].upper()}"
            if rec["location_label"]:
                text += f"  |  {rec['location_label']}"
            ctk.CTkLabel(row, text=text, text_color=color).pack(anchor="w", padx=12, pady=6)

    def _start_attendance_camera(self):
        self._ensure_engines()
        session = self.attendance_engine.get_status()
        if not (session and session["is_open"] == 1):
            self.attendance_guidance_label.configure(text=config.ATTENDANCE_CLOSED_MESSAGE,
                                                       text_color=config.DANGER_COLOR)
            return
        if self.camera_running:
            return
        self.camera = utils.CameraStream()
        if not self.camera.start():
            self.attendance_guidance_label.configure(text="Unable to access camera.")
            return
        self.camera_running = True
        self.final_frame = None
        self.attendance_guidance_label.configure(text="Camera started. Frame your face and capture.",
                                                   text_color="gray70")
        self._reset_capture_buttons()
        self._update_attendance_preview()

    def _update_attendance_preview(self):
        if not self.camera_running or self.camera is None:
            return
        if self.final_frame is not None:
            self.after(config.CAMERA_FPS_PREVIEW_DELAY_MS, self._update_attendance_preview)
            return

        ok, frame = self.camera.read()
        if ok:
            self.live_frame = frame
            self._render_frame_to_label(frame, self.attendance_video_label)
        else:
            self.attendance_guidance_label.configure(
                text="Camera read failed. Try stopping and restarting the camera."
            )
        self.after(config.CAMERA_FPS_PREVIEW_DELAY_MS, self._update_attendance_preview)

    def _render_frame_to_label(self, frame_bgr, label_widget, size=(480, 360)):
        pil_img = utils.cv2_to_pil(cv2.resize(frame_bgr, size))
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        label_widget.configure(image=ctk_img, text="")
        label_widget.image = ctk_img

    def _capture_final_selfie(self):
        if self.live_frame is None:
            self.attendance_result_label.configure(
                text="Start the camera first.", text_color=config.DANGER_COLOR
            )
            return
        self.final_frame = self.live_frame.copy()
        self._render_frame_to_label(self.final_frame, self.attendance_video_label)
        self.retake_btn.configure(state="normal")
        self.submit_btn.configure(state="normal")
        self.capture_btn.configure(state="disabled")
        self.attendance_result_label.configure(
            text="Selfie captured. Review it, then Retake or Submit for Approval.",
            text_color="gray80",
        )

    def _retake_selfie(self):
        self.final_frame = None
        self._reset_capture_buttons()
        self.attendance_result_label.configure(text="")

    def _reset_capture_buttons(self):
        self.retake_btn.configure(state="disabled")
        self.submit_btn.configure(state="disabled")
        self.capture_btn.configure(state="normal")

    def _submit_attendance(self):
        self._ensure_engines()
        if self.final_frame is None:
            return
        self.submit_btn.configure(state="disabled")
        self.attendance_location_label.configure(text="Reading location...")

        def worker():
            # Use the last verified real GPS fix from gps_realtime.py --
            # never estimated from IP address. If the employee hasn't
            # granted browser location permission yet, this is honestly
            # reported as unavailable rather than guessed.
            snap = self.gps.get_latest()
            if snap.get("status") == "active" and snap.get("lat") is not None:
                loc = {"success": True, "lat": snap["lat"], "lon": snap["lon"],
                       "label": snap.get("address") or f"{snap['lat']:.5f}, {snap['lon']:.5f}"}
            else:
                loc = {"success": False, "lat": None, "lon": None, "label": None}
            self.after(0, lambda: self._finish_submit_attendance(loc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_submit_attendance(self, loc):
        if self.final_frame is None:
            return
        lat = loc["lat"] if loc["success"] else None
        lon = loc["lon"] if loc["success"] else None
        label = loc["label"] if loc["success"] else None
        self.attendance_location_label.configure(
            text=f"Location: {label} ({lat:.3f}, {lon:.3f})" if loc["success"]
            else "Location: unavailable (submitted without GPS)"
        )
        result = self.attendance_engine.submit_selfie(
            self.employee_id, self.final_frame,
            latitude=lat, longitude=lon, location_label=label,
        )
        color = config.ACCENT_COLOR if result["success"] else config.DANGER_COLOR
        self.attendance_result_label.configure(text=result["message"], text_color=color)
        try:
            self.db.log_event(self.employee_id, "attendance_taken",
                               f"Selfie attendance submitted: {result['message']}")
        except Exception:
            pass
        self.final_frame = None
        self._reset_capture_buttons()
        self._load_my_attendance()

    def _stop_attendance_camera(self):
        self.camera_running = False
        self.final_frame = None
        if self.camera is not None:
            self.camera.stop()
            self.camera = None

    # TASKS
    # ==================================================================
    def _init_view_tasks(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["tasks"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="My Tasks", font=ctk.CTkFont(size=22, weight="bold")).pack(
            side="left"
        )
        ctk.CTkButton(header, text="Refresh", width=100, command=self._load_tasks).pack(
            side="right"
        )

        self.tasks_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.tasks_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_tasks

    def _load_tasks(self):
        self._ensure_engines()
        for widget in self.tasks_scroll.winfo_children():
            widget.destroy()

        assignments = self.task_engine.list_assignments_for_employee(self.employee_id)
        if not assignments:
            ctk.CTkLabel(self.tasks_scroll, text="No tasks assigned yet.").pack(pady=10)
            return

        for a in assignments:
            card = ctk.CTkFrame(self.tasks_scroll, corner_radius=10)
            card.pack(fill="x", pady=6, padx=4)

            ctk.CTkLabel(card, text=a["title"], font=ctk.CTkFont(size=15, weight="bold")).pack(
                anchor="w", padx=14, pady=(10, 2)
            )
            ctk.CTkLabel(card, text=a["description"] or "", wraplength=780, justify="left").pack(
                anchor="w", padx=14, pady=(0, 4)
            )
            duration = utils.format_duration(self.task_engine.live_elapsed_seconds(a))
            ctk.CTkLabel(
                card, text=f"Status: {a['status'].upper()}   |   Time spent: {duration}",
                font=ctk.CTkFont(size=12), text_color="gray70",
            ).pack(anchor="w", padx=14, pady=(0, 8))

            btn_row = ctk.CTkFrame(card, fg_color="transparent")
            btn_row.pack(anchor="w", padx=14, pady=(0, 12))

            status = a["status"]
            ctk.CTkButton(
                btn_row, text="Start", width=90,
                state="normal" if status == "pending" else "disabled",
                command=lambda aid=a["id"], title=a["title"]: self._task_action("start", aid, title),
            ).grid(row=0, column=0, padx=4)
            ctk.CTkButton(
                btn_row, text="Pause", width=90,
                state="normal" if status == "in_progress" else "disabled",
                command=lambda aid=a["id"], title=a["title"]: self._task_action("pause", aid, title),
            ).grid(row=0, column=1, padx=4)
            ctk.CTkButton(
                btn_row, text="Resume", width=90,
                state="normal" if status == "paused" else "disabled",
                command=lambda aid=a["id"], title=a["title"]: self._task_action("resume", aid, title),
            ).grid(row=0, column=2, padx=4)
            ctk.CTkButton(
                btn_row, text="Finish", width=90, fg_color=config.DANGER_COLOR,
                state="normal" if status in ("in_progress", "paused") else "disabled",
                command=lambda aid=a["id"], title=a["title"]: self._task_action("finish", aid, title),
            ).grid(row=0, column=3, padx=4)

    _TASK_EVENT_LABEL = {
        "start": ("task_started", "Started task: {title}"),
        "pause": ("task_paused", "Paused task: {title}"),
        "resume": ("task_resumed", "Resumed task: {title}"),
        "finish": ("task_completed", "Completed task: {title}"),
    }

    def _task_action(self, action, assignment_id, task_title=""):
        self._ensure_engines()
        method = {
            "start": self.task_engine.start_task,
            "pause": self.task_engine.pause_task,
            "resume": self.task_engine.resume_task,
            "finish": self.task_engine.finish_task,
        }[action]
        ok, msg = method(assignment_id)
        if not ok:
            messagebox.showwarning("Task Update", msg)
        else:
            try:
                event_type, template = self._TASK_EVENT_LABEL[action]
                self.db.log_event(self.employee_id, event_type, template.format(title=task_title))
            except Exception:
                pass
        self._load_tasks()

    # ==================================================================
    # SEND REQUESTS
    # ==================================================================
    def _init_view_requests(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.views["requests"] = frame

        ctk.CTkLabel(frame, text="Send Request to Admin", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 16)
        )

        form = ctk.CTkFrame(frame, corner_radius=12)
        form.pack(fill="x", pady=(0, 16))

        self.request_subject_entry = ctk.CTkEntry(form, placeholder_text="Subject", width=400)
        self.request_subject_entry.pack(anchor="w", padx=20, pady=(20, 10))

        self.request_message_box = ctk.CTkTextbox(form, width=400, height=100)
        self.request_message_box.pack(anchor="w", padx=20, pady=10)

        self.request_status_label = ctk.CTkLabel(form, text="")
        self.request_status_label.pack(anchor="w", padx=20)

        ctk.CTkButton(form, text="Send Request", width=200, command=self._send_request).pack(
            anchor="w", padx=20, pady=(10, 20)
        )

        ctk.CTkLabel(frame, text="My Requests", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", pady=(6, 6)
        )
        self.my_requests_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.my_requests_scroll.pack(fill="both", expand=True)

        frame.on_show = self._load_my_requests

    def _send_request(self):
        self._ensure_engines()
        subject = self.request_subject_entry.get().strip()
        message = self.request_message_box.get("1.0", "end").strip()
        if utils.is_blank(subject) or utils.is_blank(message):
            self.request_status_label.configure(text="Subject and message are required.",
                                                 text_color=config.DANGER_COLOR)
            return
        self.notification_engine.send_request(self.employee_id, subject, message)
        self.request_status_label.configure(text="Request sent to admin.", text_color=config.ACCENT_COLOR)
        self.request_subject_entry.delete(0, "end")
        self.request_message_box.delete("1.0", "end")
        self._load_my_requests()

    def _load_my_requests(self):
        self._ensure_engines()
        for widget in self.my_requests_scroll.winfo_children():
            widget.destroy()

        requests = [r for r in self.notification_engine.list_requests()
                    if r["employee_id"] == self.employee_id]
        if not requests:
            ctk.CTkLabel(self.my_requests_scroll, text="You haven't sent any requests yet.").pack(pady=8)
            return

        for r in requests:
            row = ctk.CTkFrame(self.my_requests_scroll, corner_radius=8)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(
                row, text=f"{r['subject']}  [{r['status'].upper()}]  -  {r['created_at']}",
                font=ctk.CTkFont(weight="bold"),
            ).pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=r["message"], wraplength=800, justify="left").pack(
                anchor="w", padx=12, pady=(0, 8)
            )

    # ==================================================================
    # CLOSE / LOGOUT
    # ==================================================================
    def on_close(self):
        try:
            self.db.log_event(self.employee_id, "logout", f"{self.employee_name} logged out")
        except Exception:
            pass  # never block shutdown on a logging failure
        if getattr(self, "_gps_ui_job", None) is not None:
            try:
                self.after_cancel(self._gps_ui_job)
            except Exception:
                pass
        try:
            self.gps.stop()
        except Exception:
            pass
        try:
            self.db.set_employee_offline(self.employee_id)
        except Exception:
            pass
        self._stop_attendance_camera()
        self.destroy()
        sys.exit(0)


def launch_employee_dashboard(employee_id: int, employee_name: str):
    ctk.set_appearance_mode(config.APPEARANCE_MODE)
    ctk.set_default_color_theme(config.COLOR_THEME)
    app = EmployeeDashboard(employee_id, employee_name)
    app.mainloop()


if __name__ == "__main__":
    employee_id = 1
    employee_name = "Test Employee"
    if len(sys.argv) >= 3:
        try:
            employee_id = int(sys.argv[1])
            employee_name = sys.argv[2]
        except ValueError:
            pass
    launch_employee_dashboard(employee_id, employee_name)

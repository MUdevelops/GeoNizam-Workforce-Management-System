"""
attendance.py
Business logic for GeoNizam attendance:
  - Admin: open/close the attendance window, approve/reject queued selfies.
  - Employee: capture a plain selfie (no AI face-matching) and submit it
    for Admin review. Capture is only permitted while the Admin has the
    attendance window OPEN -- see config.ATTENDANCE_CLOSED_MESSAGE.

Each submitted selfie also carries the employee's approximate GPS
coordinates (captured at submit-time) so the Admin can see where
attendance was marked from.
"""

import os
import threading

import numpy as np

import config
import utils
from database import get_db

_attendance_lock = threading.Lock()


class AttendanceEngine:
    def __init__(self):
        self.db = get_db()

    # ------------------------------------------------------------------
    # ADMIN CONTROL
    # ------------------------------------------------------------------
    def open_attendance(self):
        with _attendance_lock:
            self.db.open_attendance(0)

    def close_attendance(self):
        with _attendance_lock:
            self.db.close_attendance()

    def get_status(self):
        """Returns sqlite3.Row with is_open, opened_at, closed_at."""
        return self.db.get_attendance_session()

    def list_pending(self):
        return self.db.list_pending_attendance()

    def approve(self, record_id: int):
        self.db.review_attendance_record(record_id, "approved")

    def reject(self, record_id: int):
        self.db.review_attendance_record(record_id, "rejected")

    # ------------------------------------------------------------------
    # EMPLOYEE CAPTURE / SUBMIT
    # ------------------------------------------------------------------
    def submit_selfie(self, employee_id: int, frame_bgr: np.ndarray,
                       latitude=None, longitude=None, location_label=None):
        """
        Saves the employee's selfie and queues it as a 'pending' record
        for the Admin to Approve/Reject. Performs NO face recognition --
        this is a plain photographic attendance capture.
        """
        session = self.get_status()
        if session is None or session["is_open"] != 1:
            return {"success": False, "message": config.ATTENDANCE_CLOSED_MESSAGE}

        if self.db.has_pending_or_approved(employee_id, session["id"]):
            return {"success": False,
                    "message": "You already have a pending or approved attendance "
                               "entry for this session."}

        image_path = os.path.join(
            config.ATTENDANCE_CAPTURES_DIR,
            f"emp{employee_id}_session{session['id']}_"
            f"{utils.now_str().replace(':', '-').replace(' ', '_')}.png",
        )
        utils.save_bgr_image(frame_bgr, image_path)

        self.db.add_attendance_record(
            employee_id, session["id"], "pending", image_path,
            latitude=latitude, longitude=longitude, location_label=location_label,
        )
        return {"success": True,
                "message": "Selfie submitted. Waiting for Admin approval."}

    def history_for_employee(self, employee_id: int):
        return self.db.list_attendance_records(employee_id)

    def all_history(self):
        return self.db.list_attendance_records()


_attendance_engine_instance = None
_attendance_engine_lock = threading.Lock()


def get_attendance_engine() -> AttendanceEngine:
    global _attendance_engine_instance
    with _attendance_engine_lock:
        if _attendance_engine_instance is None:
            _attendance_engine_instance = AttendanceEngine()
    return _attendance_engine_instance

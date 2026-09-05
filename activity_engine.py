"""
activity_engine.py
Live activity tracking for employees, controlled/monitored by the admin
dashboard in real time (polled on demand -- no automatic background refresh,
per spec). Tracks start/pause/resume/finish transitions and elapsed time,
and generates simple textual/tabular reports.
"""

import threading

import utils
from database import get_db

_activity_lock = threading.Lock()


class ActivityEngine:
    def __init__(self):
        self.db = get_db()

    # ------------------------------------------------------------------
    # EMPLOYEE-SIDE CONTROLS
    # ------------------------------------------------------------------
    def start(self, employee_id: int, label: str = None):
        with _activity_lock:
            existing = self.db.get_active_activity(employee_id)
            if existing is not None:
                return False, "An activity session is already active.", None
            activity_id = self.db.start_activity(employee_id, label)
            return True, "Activity started.", activity_id

    def pause(self, employee_id: int):
        with _activity_lock:
            activity = self.db.get_active_activity(employee_id)
            if activity is None or activity["status"] != "running":
                return False, "No running activity to pause."
            elapsed = utils.elapsed_seconds(activity["last_resume"])
            new_total = activity["total_seconds"] + elapsed
            self.db.update_activity(activity["id"], "paused", total_seconds=new_total)
            return True, "Activity paused."

    def resume(self, employee_id: int):
        with _activity_lock:
            activity = self.db.get_active_activity(employee_id)
            if activity is None or activity["status"] != "paused":
                return False, "No paused activity to resume."
            now = utils.now_str()
            self.db.update_activity(activity["id"], "running", last_resume=now)
            return True, "Activity resumed."

    def finish(self, employee_id: int):
        with _activity_lock:
            activity = self.db.get_active_activity(employee_id)
            if activity is None:
                return False, "No active activity to finish."
            total = activity["total_seconds"]
            if activity["status"] == "running":
                total += utils.elapsed_seconds(activity["last_resume"])
            now = utils.now_str()
            self.db.update_activity(activity["id"], "finished", finish_time=now, total_seconds=total)
            return True, "Activity finished."

    def get_active(self, employee_id: int):
        return self.db.get_active_activity(employee_id)

    def live_elapsed_seconds(self, activity) -> float:
        total = activity["total_seconds"]
        if activity["status"] == "running" and activity["last_resume"]:
            total += utils.elapsed_seconds(activity["last_resume"])
        return total

    # ------------------------------------------------------------------
    # ADMIN-SIDE MONITORING / REPORTS
    # ------------------------------------------------------------------
    def list_all_sessions(self):
        return self.db.list_activity_sessions()

    def list_sessions_for_employee(self, employee_id: int):
        return self.db.list_activity_sessions(employee_id)

    def generate_report_rows(self):
        """
        Returns a list of formatted dict rows suitable for a report table:
        employee, label, status, start, finish, duration.
        """
        rows = []
        for session in self.list_all_sessions():
            duration = self.live_elapsed_seconds(session)
            rows.append({
                "employee_name": session["employee_name"],
                "label": session["label"] or "-",
                "status": session["status"],
                "start_time": session["start_time"],
                "finish_time": session["finish_time"] or "-",
                "duration": utils.format_duration(duration),
            })
        return rows


_activity_engine_instance = None
_activity_engine_lock = threading.Lock()


def get_activity_engine() -> ActivityEngine:
    global _activity_engine_instance
    with _activity_engine_lock:
        if _activity_engine_instance is None:
            _activity_engine_instance = ActivityEngine()
    return _activity_engine_instance

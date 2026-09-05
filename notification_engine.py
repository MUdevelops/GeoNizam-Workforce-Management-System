"""
notification_engine.py
Admin -> Employee notifications (broadcast or targeted) and
Employee -> Admin requests, persisted permanently in SQLite.
"""

import threading

from database import get_db

_notify_lock = threading.Lock()


class NotificationEngine:
    def __init__(self):
        self.db = get_db()

    # ------------------------------------------------------------------
    # ADMIN -> EMPLOYEE NOTIFICATIONS
    # ------------------------------------------------------------------
    def send_to_all(self, title: str, message: str) -> int:
        with _notify_lock:
            return self.db.add_notification(title, message, "all")

    def send_to_employee(self, title: str, message: str, employee_id: int) -> int:
        with _notify_lock:
            return self.db.add_notification(title, message, str(employee_id))

    def list_for_employee(self, employee_id: int):
        return self.db.list_notifications_for_employee(employee_id)

    def list_all(self):
        return self.db.list_all_notifications()

    # ------------------------------------------------------------------
    # EMPLOYEE -> ADMIN REQUESTS
    # ------------------------------------------------------------------
    def send_request(self, employee_id: int, subject: str, message: str) -> int:
        with _notify_lock:
            return self.db.add_request(employee_id, subject, message)

    def list_requests(self, status: str = None):
        return self.db.list_requests(status)

    def approve_request(self, request_id: int):
        self.db.update_request_status(request_id, "approved")

    def reject_request(self, request_id: int):
        self.db.update_request_status(request_id, "rejected")


_notification_engine_instance = None
_notification_engine_lock = threading.Lock()


def get_notification_engine() -> NotificationEngine:
    global _notification_engine_instance
    with _notification_engine_lock:
        if _notification_engine_instance is None:
            _notification_engine_instance = NotificationEngine()
    return _notification_engine_instance

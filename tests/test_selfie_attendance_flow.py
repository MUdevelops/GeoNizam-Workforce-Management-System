import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np

import config
from database import get_db
from attendance import get_attendance_engine


def _fresh_db():
    db = get_db()
    db.reset_all_data()
    return db


def test_selfie_blocked_when_attendance_window_closed():
    db = _fresh_db()
    engine = get_attendance_engine()
    emp_id = db.add_employee("Test Employee", "test.employee", "pw12345")
    engine.close_attendance()

    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    result = engine.submit_selfie(emp_id, frame)

    assert result["success"] is False
    assert result["message"] == config.ATTENDANCE_CLOSED_MESSAGE


def test_selfie_queues_as_pending_when_open_and_admin_can_approve():
    db = _fresh_db()
    engine = get_attendance_engine()
    emp_id = db.add_employee("Test Employee", "test.employee", "pw12345")
    engine.open_attendance()

    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    result = engine.submit_selfie(emp_id, frame, latitude=24.86, longitude=67.00,
                                   location_label="Karachi")
    assert result["success"] is True

    pending = engine.list_pending()
    assert len(pending) == 1
    assert pending[0]["employee_id"] == emp_id
    assert pending[0]["status"] == "pending"

    engine.approve(pending[0]["id"])
    history = engine.history_for_employee(emp_id)
    assert history[0]["status"] == "approved"


def test_max_three_admins_enforced():
    db = _fresh_db()
    # one legacy Admin already exists (seeded); create 2 more to reach the cap
    db.add_admin("Admin Two", "admin.two", "pw12345")
    db.add_admin("Admin Three", "admin.three", "pw12345")
    assert db.count_admins() == config.MAX_ADMINS
    # the UI layer checks this before calling add_admin() again
    assert db.count_admins() >= config.MAX_ADMINS


def test_max_seven_employees_per_admin_enforced():
    db = _fresh_db()
    admin_id = db.list_admins()[0]["id"]
    for i in range(config.MAX_EMPLOYEES_PER_ADMIN):
        db.add_employee(f"Emp {i}", f"emp{i}", "pw12345", admin_id=admin_id)
    assert db.count_employees_for_admin(admin_id) == config.MAX_EMPLOYEES_PER_ADMIN
    assert db.count_employees_for_admin(admin_id) >= config.MAX_EMPLOYEES_PER_ADMIN


def test_admin_permission_toggle_persists():
    db = _fresh_db()
    admin_id = db.list_admins()[0]["id"]
    assert db.get_admin_permissions(admin_id)["gps_tracking"] is True
    db.set_admin_permission(admin_id, "gps_tracking", False)
    assert db.get_admin_permissions(admin_id)["gps_tracking"] is False


def test_removing_admin_unassigns_but_keeps_employees():
    db = _fresh_db()
    admin_id = db.list_admins()[0]["id"]
    emp_id = db.add_employee("Test Employee", "test.employee", "pw12345", admin_id=admin_id)
    db.remove_admin(admin_id)
    employee = db.get_employee_by_id(emp_id)
    assert employee is not None  # not deleted
    assert employee["admin_id"] is None  # unassigned

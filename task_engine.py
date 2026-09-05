"""
task_engine.py
Task management: admin creates tasks (assigned to all or one employee),
employees start/pause/resume/finish their assignment with accurate
elapsed-time tracking stored permanently in SQLite.
"""

import threading

import utils
from database import get_db

_task_lock = threading.Lock()


class TaskEngine:
    def __init__(self):
        self.db = get_db()

    # ------------------------------------------------------------------
    # ADMIN
    # ------------------------------------------------------------------
    def create_task(self, title: str, description: str, assigned_to=None) -> int:
        with _task_lock:
            return self.db.add_task(title, description, assigned_to)

    def list_tasks(self):
        return self.db.list_tasks()

    def list_all_assignments(self):
        return self.db.list_all_task_assignments()

    # ------------------------------------------------------------------
    # EMPLOYEE
    # ------------------------------------------------------------------
    def list_assignments_for_employee(self, employee_id: int):
        return self.db.list_task_assignments_for_employee(employee_id)

    def start_task(self, assignment_id: int):
        with _task_lock:
            assignment = self.db.get_task_assignment(assignment_id)
            if assignment is None or assignment["status"] not in ("pending",):
                return False, "Task cannot be started from its current state."
            now = utils.now_str()
            self.db.update_task_assignment_status(
                assignment_id, "in_progress", start_time=now, last_resume=now
            )
            return True, "Task started."

    def pause_task(self, assignment_id: int):
        with _task_lock:
            assignment = self.db.get_task_assignment(assignment_id)
            if assignment is None or assignment["status"] != "in_progress":
                return False, "Task is not currently in progress."
            elapsed = utils.elapsed_seconds(assignment["last_resume"])
            new_total = assignment["total_seconds"] + elapsed
            self.db.update_task_assignment_status(assignment_id, "paused", total_seconds=new_total)
            return True, "Task paused."

    def resume_task(self, assignment_id: int):
        with _task_lock:
            assignment = self.db.get_task_assignment(assignment_id)
            if assignment is None or assignment["status"] != "paused":
                return False, "Task is not currently paused."
            now = utils.now_str()
            self.db.update_task_assignment_status(assignment_id, "in_progress", last_resume=now)
            return True, "Task resumed."

    def finish_task(self, assignment_id: int):
        with _task_lock:
            assignment = self.db.get_task_assignment(assignment_id)
            if assignment is None or assignment["status"] not in ("in_progress", "paused"):
                return False, "Task cannot be finished from its current state."
            total = assignment["total_seconds"]
            if assignment["status"] == "in_progress":
                total += utils.elapsed_seconds(assignment["last_resume"])
            now = utils.now_str()
            self.db.update_task_assignment_status(
                assignment_id, "completed", finish_time=now, total_seconds=total
            )
            return True, "Task marked as completed."

    def live_elapsed_seconds(self, assignment) -> float:
        """Compute the current running total for display, including in-progress time."""
        total = assignment["total_seconds"]
        if assignment["status"] == "in_progress" and assignment["last_resume"]:
            total += utils.elapsed_seconds(assignment["last_resume"])
        return total


_task_engine_instance = None
_task_engine_lock = threading.Lock()


def get_task_engine() -> TaskEngine:
    global _task_engine_instance
    with _task_engine_lock:
        if _task_engine_instance is None:
            _task_engine_instance = TaskEngine()
    return _task_engine_instance

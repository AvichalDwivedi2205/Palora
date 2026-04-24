from __future__ import annotations

from typing import Any


class WritebackService:
    def __init__(self, db: Any) -> None:
        self.db = db

    def record_turn(self, trace_id: str, event_type: str, subject_id: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO audit_events (
              id, trace_id, event_type, subject_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                self.db.make_id("audit"),
                trace_id,
                event_type,
                subject_id,
                self.db.json_dumps(payload),
            ),
        )

    def record_action_run(self, action_plan_id: str, adapter_name: str, request: dict[str, Any], result: dict[str, Any]) -> str:
        run_id = self.db.make_id("run")
        self.db.execute(
            """
            INSERT INTO action_runs (
              id, action_plan_id, adapter_name, request_json, result_json, rollback_json,
              started_at, finished_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
            """,
            (
                run_id,
                action_plan_id,
                adapter_name,
                self.db.json_dumps(request),
                self.db.json_dumps(result),
                self.db.json_dumps(None),
                result.get("status", "completed"),
            ),
        )
        return run_id

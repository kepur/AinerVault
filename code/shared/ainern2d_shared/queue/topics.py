from __future__ import annotations


class SYSTEM_TOPICS:
	TASK_SUBMITTED = "task.submitted"
	JOB_DISPATCH = "job.dispatch"
	JOB_STATUS = "job.status"
	WORKER_DETAIL = "worker.detail"
	# Backward-compatible alias for legacy worker callback publisher paths.
	WORKER_CALLBACK = WORKER_DETAIL
	COMPOSE_DISPATCH = "compose.dispatch"
	COMPOSE_STATUS = "compose.status"
	SKILL_EVENTS = "skill.events"
	ALERT_EVENTS = "alert.events"

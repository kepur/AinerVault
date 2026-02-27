#!/usr/bin/env python3
"""Real RabbitMQ smoke/storm validator for message-chain E2E.

Chain under test:
  job.created -> worker.detail -> job.status -> orchestrator stage(update)

This script uses isolated queue names (with a unique scope suffix) so it can be
run safely without consuming the shared system queues.

Usage:
  DATABASE_URL=... RABBITMQ_URL=... \
    python3 code/scripts/validate_mq_smoke_storm_e2e.py --mode smoke

  DATABASE_URL=... RABBITMQ_URL=... \
    python3 code/scripts/validate_mq_smoke_storm_e2e.py --mode storm --jobs 300
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "apps" / "ainern2d-studio-api"))

import pika
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun, WorkflowEvent
from ainern2d_shared.config.setting import settings
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.worker import WorkerResult


@dataclass(frozen=True)
class JobCase:
    run_id: str
    job_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str


class MQHarness:
    def __init__(self, rabbitmq_url: str, scope: str) -> None:
        self.dispatch_q = f"job.dispatch.e2e.{scope}"
        self.worker_detail_q = f"worker.detail.e2e.{scope}"
        self.job_status_q = f"job.status.e2e.{scope}"

        self._conn = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        self._ch = self._conn.channel()
        for q in (self.dispatch_q, self.worker_detail_q, self.job_status_q):
            self._ch.queue_declare(queue=q, durable=True)
            self._ch.queue_purge(queue=q)

    def publish(self, queue: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._ch.basic_publish(
            exchange="",
            routing_key=queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2),
        )

    def get_one(self, queue: str) -> dict[str, Any] | None:
        method, _props, body = self._ch.basic_get(queue=queue, auto_ack=False)
        if method is None:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}
        self._ch.basic_ack(delivery_tag=method.delivery_tag)
        return payload

    def close(self) -> None:
        if self._conn and not self._conn.is_closed:
            self._conn.close()


def _upsert_seed(db, tenant_id: str, project_id: str, novel_id: str, chapter_id: str) -> None:
    novel = db.get(Novel, novel_id)
    if novel is None:
        novel = Novel(
            id=novel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            title=f"mq_e2e_{novel_id}",
            summary="mq e2e seed",
            default_language_code="zh",
        )
        db.add(novel)
        # Explicit flush to satisfy FK insert order for Chapter.
        db.flush()

    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        db.add(
            Chapter(
                id=chapter_id,
                tenant_id=tenant_id,
                project_id=project_id,
                novel_id=novel_id,
                chapter_no=1,
                language_code="zh",
                title="mq e2e chapter",
                raw_text="mq e2e seed",
            )
        )
    db.commit()


def _create_cases(
    db,
    *,
    tenant_id: str,
    project_id: str,
    chapter_id: str,
    scope: str,
    jobs: int,
) -> list[JobCase]:
    out: list[JobCase] = []
    now_ms = int(time.time() * 1000)
    for i in range(jobs):
        run_id = f"RUN_MQ_E2E_{scope}_{i:04d}"
        job_id = f"JOB_MQ_E2E_{scope}_{i:04d}"
        idem = f"idem_mq_{scope}_{i:04d}"
        trace = f"tr_mq_{scope}_{i:04d}"
        corr = f"co_mq_{scope}_{i:04d}"

        run = db.get(RenderRun, run_id)
        if run is None:
            run = RenderRun(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                chapter_id=chapter_id,
                status=RunStatus.running,
                stage=RenderStage.ingest,
                progress=0,
                trace_id=trace,
                correlation_id=corr,
                idempotency_key=f"{idem}:run",
                config_json={"e2e_mq_scope": scope, "created_at_ms": now_ms},
            )
            db.add(run)
            # Explicit flush to satisfy FK insert order for Job.
            db.flush()

        job = db.get(Job, job_id)
        if job is None:
            db.add(
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    chapter_id=chapter_id,
                    job_type=JobType.render_video,
                    stage=RenderStage.execute,
                    status=JobStatus.enqueued,
                    priority=0,
                    trace_id=trace,
                    correlation_id=corr,
                    idempotency_key=idem,
                    payload_json={"scope": scope, "i": i, "kind": "mq_storm_e2e"},
                )
            )

        out.append(
            JobCase(
                run_id=run_id,
                job_id=job_id,
                idempotency_key=idem,
                trace_id=trace,
                correlation_id=corr,
            )
        )
    db.commit()
    return out


def _job_created_event(case: JobCase, tenant_id: str, project_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type="job.created",
        producer="mq-e2e-harness",
        occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        tenant_id=tenant_id,
        project_id=project_id,
        idempotency_key=f"{case.idempotency_key}:created",
        run_id=case.run_id,
        job_id=case.job_id,
        trace_id=case.trace_id,
        correlation_id=case.correlation_id,
        payload={"worker_type": "worker-video", "scope": "mq_storm_e2e"},
    )


def _worker_result_for(case: JobCase) -> WorkerResult:
    return WorkerResult(
        job_id=case.job_id,
        run_id=case.run_id,
        worker_type="worker-video",
        status="succeeded",
        artifact_uri=f"s3://ainer-artifacts/{case.run_id}/{case.job_id}.mp4",
        metrics={"source": "mq-e2e-harness"},
    )


def _worker_detail_to_job_status_event(result: WorkerResult) -> EventEnvelope:
    db = SessionLocal()
    try:
        job = db.get(Job, result.job_id)
        if job is None:
            raise LookupError(f"job {result.job_id} not found")

        if result.status.lower() == "succeeded":
            job.status = JobStatus.success
            event_type = "job.succeeded"
        else:
            job.status = JobStatus.failed
            event_type = "job.failed"

        job.result_json = result.model_dump(mode="json")
        db.commit()

        return EventEnvelope(
            event_type=event_type,
            producer="mq-e2e-harness",
            occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            idempotency_key=f"{job.idempotency_key}:worker_detail:{event_type}",
            run_id=result.run_id,
            job_id=result.job_id,
            trace_id=job.trace_id or f"tr_{result.job_id}",
            correlation_id=job.correlation_id or f"cr_{result.job_id}",
            payload={
                "worker_type": result.worker_type,
                "artifact_uri": result.artifact_uri,
                "metrics": result.metrics,
            },
        )
    finally:
        db.close()


def _run_stage(run_id: str) -> str | None:
    db = SessionLocal()
    try:
        run = db.get(RenderRun, run_id)
        return run.stage.value if run and run.stage else None
    finally:
        db.close()


def _apply_orchestrator_job_status(payload: dict[str, Any]) -> None:
    """Apply job.status payload to run stage (orchestrator-equivalent behavior)."""
    event = EventEnvelope.model_validate(payload)
    db = SessionLocal()
    try:
        run = db.get(RenderRun, event.run_id) if event.run_id else None
        if run is not None:
            if event.event_type == "job.claimed":
                run.status = RunStatus.running
                run.stage = RenderStage.execute
                run.progress = max(run.progress, 15)
            elif event.event_type == "job.succeeded":
                run.status = RunStatus.running
                run.stage = RenderStage.compose
                run.progress = max(run.progress, 70)
            elif event.event_type == "job.failed":
                run.status = RunStatus.failed
                run.stage = RenderStage.execute
                run.error_code = (event.payload or {}).get("error_code", "WORKER-EXEC-002")
                run.error_message = (event.payload or {}).get("error_message", "job failed")

        db.add(
            WorkflowEvent(
                id=event.event_id,
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                trace_id=event.trace_id,
                correlation_id=event.correlation_id,
                idempotency_key=event.idempotency_key,
                run_id=event.run_id,
                job_id=event.job_id,
                event_type=event.event_type,
                event_version=event.event_version,
                producer=event.producer,
                occurred_at=event.occurred_at,
                payload_json=event.payload,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()


def _workflow_event_count(*, tenant_id: str, project_id: str, run_ids: list[str], event_type: str) -> int:
    db = SessionLocal()
    try:
        stmt = select(WorkflowEvent).where(
            WorkflowEvent.tenant_id == tenant_id,
            WorkflowEvent.project_id == project_id,
            WorkflowEvent.run_id.in_(run_ids),
            WorkflowEvent.event_type == event_type,
            WorkflowEvent.deleted_at.is_(None),
        )
        return len(db.execute(stmt).scalars().all())
    finally:
        db.close()


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.95) - 1))
    return sorted_vals[idx]


def run(args: argparse.Namespace) -> int:
    rabbitmq_url = os.getenv("RABBITMQ_URL", settings.rabbitmq_url)
    scope = (args.scope or uuid.uuid4().hex[:10]).upper()

    tenant_id = f"t_mq_{scope.lower()}"
    project_id = f"p_mq_{scope.lower()}"
    novel_id = f"NOVEL_MQ_{scope}"
    chapter_id = f"CH_MQ_{scope}"
    jobs = args.jobs if args.jobs is not None else (1 if args.mode == "smoke" else 200)

    db = SessionLocal()
    try:
        _upsert_seed(db, tenant_id, project_id, novel_id, chapter_id)
        cases = _create_cases(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            chapter_id=chapter_id,
            scope=scope,
            jobs=jobs,
        )
    finally:
        db.close()

    by_job_id = {c.job_id: c for c in cases}
    publish_ts: dict[str, float] = {}
    compose_ts: dict[str, float] = {}

    mq = MQHarness(rabbitmq_url, scope)
    t0 = time.perf_counter()
    try:
        # 1) enqueue burst: job.created
        for c in cases:
            evt = _job_created_event(c, tenant_id, project_id)
            mq.publish(mq.dispatch_q, evt.model_dump(mode="json"))
            publish_ts[c.run_id] = time.perf_counter()

        deadline = time.perf_counter() + args.timeout_seconds
        dispatch_count = 0
        worker_detail_count = 0
        status_count = 0

        while len(compose_ts) < len(cases) and time.perf_counter() < deadline:
            progressed = False

            # 2) dispatch queue -> simulated runtime emits worker.detail
            while True:
                payload = mq.get_one(mq.dispatch_q)
                if payload is None:
                    break
                progressed = True
                dispatch_count += 1
                event = EventEnvelope.model_validate(payload)
                if event.event_type != "job.created" or not event.job_id:
                    continue
                case = by_job_id.get(event.job_id)
                if case is None:
                    continue
                result = _worker_result_for(case)
                mq.publish(mq.worker_detail_q, result.model_dump(mode="json"))

            # 3) worker.detail -> bridge emits job.status
            while True:
                payload = mq.get_one(mq.worker_detail_q)
                if payload is None:
                    break
                progressed = True
                worker_detail_count += 1
                result = WorkerResult.model_validate(payload)
                status_event = _worker_detail_to_job_status_event(result)
                mq.publish(mq.job_status_q, status_event.model_dump(mode="json"))

            # 4) job.status -> orchestrator stage update
            while True:
                payload = mq.get_one(mq.job_status_q)
                if payload is None:
                    break
                progressed = True
                status_count += 1
                event = EventEnvelope.model_validate(payload)
                _apply_orchestrator_job_status(payload)
                if event.run_id and event.event_type == "job.succeeded":
                    stage = _run_stage(event.run_id)
                    if stage == RenderStage.compose.value and event.run_id not in compose_ts:
                        compose_ts[event.run_id] = time.perf_counter()

            if not progressed:
                time.sleep(0.01)

        latencies = [compose_ts[rid] - publish_ts[rid] for rid in compose_ts.keys()]
        elapsed = time.perf_counter() - t0
        throughput = (len(compose_ts) / elapsed) if elapsed > 0 else 0.0

        succeeded_events = _workflow_event_count(
            tenant_id=tenant_id,
            project_id=project_id,
            run_ids=[c.run_id for c in cases],
            event_type="job.succeeded",
        )

        summary = {
            "mode": args.mode,
            "scope": scope,
            "jobs_target": len(cases),
            "jobs_composed_stage": len(compose_ts),
            "dispatch_count": dispatch_count,
            "worker_detail_count": worker_detail_count,
            "job_status_count": status_count,
            "workflow_job_succeeded_events": succeeded_events,
            "latency_p50_s": round(median(latencies), 4) if latencies else 0.0,
            "latency_p95_s": round(_p95(latencies), 4) if latencies else 0.0,
            "throughput_jobs_per_s": round(throughput, 2),
            "elapsed_s": round(elapsed, 3),
            "timeout_s": args.timeout_seconds,
            "queues": {
                "dispatch": mq.dispatch_q,
                "worker_detail": mq.worker_detail_q,
                "job_status": mq.job_status_q,
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        passed = (
            len(compose_ts) == len(cases)
            and succeeded_events >= len(cases)
        )
        if passed:
            print(
                "VALIDATION_RESULT: PASS "
                f"scope={scope} jobs={len(cases)} throughput={summary['throughput_jobs_per_s']}"
            )
            return 0
        print(
            "VALIDATION_RESULT: FAIL "
            f"scope={scope} jobs_composed={len(compose_ts)}/{len(cases)} "
            f"succeeded_events={succeeded_events}"
        )
        return 1
    finally:
        mq.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate real MQ smoke/storm e2e chain.")
    parser.add_argument("--mode", choices=("smoke", "storm"), default="smoke")
    parser.add_argument("--jobs", type=int, default=None, help="Override job count")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--scope", type=str, default=None, help="Optional fixed scope suffix")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))

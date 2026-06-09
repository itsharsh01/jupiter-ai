from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from agent.api._env import load_project_env
from agent.api.mongo.audit_repository import update_test_case_execution
from agent.api.mongo.client import close_mongo, connect_mongo
from agent.audit.evaluator import analyze_failure, build_report, evaluate_verdict
from agent.audit.phoenix_client import fetch_trace_by_context, fetch_trace_payload
from agent.audit.pubsub import acknowledge_message, pull_trace_evaluation_job

logger = logging.getLogger(__name__)

PULL_TIMEOUT_SECONDS = 30.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_error(
    job: dict[str, Any],
    *,
    message: str,
    execution_patch: dict[str, Any] | None = None,
) -> None:
    patch = {
        "evaluation_status": "error",
        "message": message,
        "evaluated_at": _utc_now(),
    }
    if execution_patch:
        patch.update(execution_patch)
    update_test_case_execution(
        job["audit_id"],
        job["test_case_id"],
        status="error",
        execution_patch=patch,
    )


def process_trace_evaluation_job(job: dict[str, Any]) -> None:
    """Fetch Phoenix trace, run LLM evaluation, persist report."""
    audit_id = job["audit_id"]
    test_case_id = job["test_case_id"]

    update_test_case_execution(
        audit_id,
        test_case_id,
        status="evaluating",
        execution_patch={"evaluation_status": "tracing"},
    )

    exclude = {str(tid) for tid in (job.get("exclude_trace_ids") or []) if tid}
    phoenix_link = fetch_trace_by_context(
        customer_id=str(job.get("customer_id") or "") or None,
        since=job.get("started_at"),
        exclude_trace_ids=exclude,
    )
    if phoenix_link is None:
        _mark_error(
            job,
            message="Phoenix trace not found for execution.",
        )
        return

    trace_id = phoenix_link.get("phoenix_trace_id")
    trace_payload = (
        fetch_trace_payload(trace_id, customer_id=str(job.get("customer_id") or "") or None)
        if trace_id
        else None
    )
    trace_linked_at = _utc_now()

    update_test_case_execution(
        audit_id,
        test_case_id,
        status="evaluating",
        execution_patch={
            "evaluation_status": "evaluating",
            "phoenix_trace_id": trace_id,
            "phoenix_span_id": phoenix_link.get("phoenix_span_id"),
            "phoenix_span_global_id": phoenix_link.get("phoenix_span_global_id"),
            "trace_linked_at": trace_linked_at,
        },
    )

    try:
        verdict_result = evaluate_verdict(
            strategy=job.get("strategy", ""),
            title=job.get("title", ""),
            user_prompt=job.get("user_prompt", ""),
            pass_condition=job.get("pass_condition", ""),
            fail_condition=job.get("fail_condition", ""),
            response_preview=job.get("response_preview"),
            severity=job.get("severity", "MEDIUM"),
        )
    except Exception as exc:
        logger.exception("LLM verdict failed for %s/%s", audit_id, test_case_id)
        _mark_error(job, message=f"LLM verdict failed: {exc}")
        return

    failure_result: dict[str, Any] | None = None
    verdict = str(verdict_result.get("verdict", "")).strip().lower()
    if verdict == "fail":
        try:
            failure_result = analyze_failure(
                strategy=job.get("strategy", ""),
                title=job.get("title", ""),
                user_prompt=job.get("user_prompt", ""),
                pass_condition=job.get("pass_condition", ""),
                fail_condition=job.get("fail_condition", ""),
                response_preview=job.get("response_preview"),
                reasoning=str(verdict_result.get("reasoning", "")),
                trace_payload=trace_payload,
            )
        except Exception as exc:
            logger.warning(
                "Failure analysis failed for %s/%s: %s",
                audit_id,
                test_case_id,
                exc,
            )

    report = build_report(
        verdict_result=verdict_result,
        failure_result=failure_result,
    )
    passed = report["verdict"] == "pass"
    final_status = "passed" if passed else "failed"
    evaluated_at = _utc_now()

    update_test_case_execution(
        audit_id,
        test_case_id,
        status=final_status,
        execution_patch={
            "passed": passed,
            "evaluation_status": "complete",
            "report": report,
            "evaluated_at": evaluated_at,
            "message": report.get("reasoning") or "Evaluation complete.",
        },
    )
    logger.info(
        "Evaluation complete audit=%s case=%s status=%s",
        audit_id,
        test_case_id,
        final_status,
    )


def run_worker(*, once: bool = False) -> None:
    load_project_env()
    connect_mongo()
    logger.info("Audit trace evaluation worker started")

    try:
        while True:
            pulled = pull_trace_evaluation_job(timeout_seconds=PULL_TIMEOUT_SECONDS)
            if pulled is None:
                if once:
                    break
                continue

            job, ack_id = pulled
            try:
                process_trace_evaluation_job(job)
                acknowledge_message(ack_id)
            except Exception:
                logger.exception(
                    "Unhandled worker error audit=%s case=%s",
                    job.get("audit_id"),
                    job.get("test_case_id"),
                )
                _mark_error(
                    job,
                    message="Unhandled worker error during trace evaluation.",
                )
                acknowledge_message(ack_id)

            if once:
                break
    finally:
        close_mongo()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    once = "--once" in sys.argv
    try:
        run_worker(once=once)
        return 0
    except KeyboardInterrupt:
        logger.info("Worker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

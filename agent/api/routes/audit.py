from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status

from agent.api.audit_schemas import (
    AuditReportResponse,
    AuditSandboxResponse,
    AuditSandboxUpsertRequest,
    AuditTestCaseResponse,
    ExecuteTestCaseResponse,
    SandboxTestResponse,
    StartAuditResponse,
    TestCaseExecutionResponse,
)
from agent.api.mongo.audit_repository import (
    get_audit_sandbox,
    get_latest_audit_for_session,
    replace_audit_sandbox,
    save_audit_sandbox,
)
from agent.audit import kg_context
from agent.audit.orchestrator import generate_all_strategies
from agent.audit.report_generator import generate_audit_report
from agent.audit.phoenix_client import execution_started_at
from agent.audit.pubsub import build_trace_evaluation_job, publish_trace_evaluation_job
from agent.audit.request_injector import inject_user_prompt
from agent.audit.sandbox_probe import probe_sandbox
from agent.audit.sandbox_url import normalize_system_url
from agent.discovery_v2.session_store import SessionStore

router = APIRouter(prefix="/audit", tags=["audit"])
_session_store = SessionStore()

KG_MAP_MESSAGE = (
    "Map the customer knowledge graph before generating test cases. "
    "POST /api/v1/customers/{customer_id}/knowledge-graph/map with source=discovery and session_id."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_test_case(item: dict) -> dict:
    """Backfill fields for legacy checklist-style test cases."""
    if not item.get("strategy"):
        item = {
            **item,
            "strategy": "governance",
            "user_prompt": item.get("user_prompt")
            or item.get("description")
            or item.get("title", ""),
        }
    if not item.get("user_prompt"):
        item["user_prompt"] = item.get("title", "Run audit check")
    return item


def _to_response(doc: dict) -> AuditSandboxResponse:
    test_cases = []
    for item in doc.get("test_cases") or []:
        raw = item if isinstance(item, dict) else item.model_dump()
        test_cases.append(AuditTestCaseResponse(**_coerce_test_case(raw)))
    return AuditSandboxResponse(
        audit_id=doc["audit_id"],
        session_id=doc["session_id"],
        customer_id=doc.get("customer_id"),
        system_url=doc["system_url"],
        auth_token_set=bool(doc.get("auth_token")),
        sample_request_body=doc.get("sample_request_body"),
        sample_response_body=doc.get("sample_response_body"),
        sandbox_test_passed=bool(doc.get("sandbox_test_passed")),
        sandbox_test_status_code=doc.get("sandbox_test_status_code"),
        status=doc.get("status", "draft"),
        test_cases=test_cases,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _load_discovery_session(session_id: str) -> dict:
    try:
        return _session_store.load_session(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery session not found: {session_id}",
        ) from exc


def _require_complete_discovery(session: dict) -> None:
    state = session.get("state") or {}
    if not state.get("discovery_complete"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discovery session is not complete yet",
        )


def _config_changed(existing: dict, body: AuditSandboxUpsertRequest) -> bool:
    return (
        normalize_system_url(existing.get("system_url") or "")
        != normalize_system_url(body.system_url)
        or existing.get("sample_request_body") != body.sample_request_body
        or existing.get("sample_response_body") != body.sample_response_body
        or (existing.get("auth_token") or None) != ((body.auth_token or "").strip() or None)
    )


def _apply_sandbox_test(doc: dict) -> SandboxTestResponse:
    result = probe_sandbox(
        system_url=doc["system_url"],
        auth_token=doc.get("auth_token"),
        sample_request_body=doc.get("sample_request_body"),
    )
    doc["sandbox_test_passed"] = result["passed"]
    doc["sandbox_test_status_code"] = result["status_code"]
    if result["passed"] and result.get("response_preview"):
        try:
            doc["sample_response_body"] = json.loads(result["response_preview"])
        except json.JSONDecodeError:
            doc["sample_response_body"] = result["response_preview"]
    doc["updated_at"] = _utc_now()
    replace_audit_sandbox(doc["audit_id"], doc)
    return SandboxTestResponse(
        audit_id=doc["audit_id"],
        passed=result["passed"],
        status_code=result["status_code"],
        response_preview=result.get("response_preview"),
        message=result["message"],
    )


@router.post("/sandbox", response_model=AuditSandboxResponse, status_code=status.HTTP_201_CREATED)
def upsert_audit_sandbox(body: AuditSandboxUpsertRequest) -> AuditSandboxResponse:
    session = _load_discovery_session(body.session_id)
    _require_complete_discovery(session)

    now = _utc_now()
    existing = get_latest_audit_for_session(body.session_id)
    audit_id = existing["audit_id"] if existing else str(uuid.uuid4())
    created_at = existing["created_at"] if existing else now

    sandbox_test_passed = False
    sandbox_test_status_code = None
    if existing and not _config_changed(existing, body):
        sandbox_test_passed = bool(existing.get("sandbox_test_passed"))
        sandbox_test_status_code = existing.get("sandbox_test_status_code")

    system_url = normalize_system_url(body.system_url)

    document = {
        "audit_id": audit_id,
        "session_id": body.session_id,
        "customer_id": session.get("customer_id"),
        "system_url": system_url,
        "auth_token": (body.auth_token or "").strip() or None,
        "sample_request_body": body.sample_request_body,
        "sample_response_body": body.sample_response_body,
        "sandbox_test_passed": sandbox_test_passed,
        "sandbox_test_status_code": sandbox_test_status_code,
        "status": existing.get("status", "draft") if existing else "draft",
        "test_cases": existing.get("test_cases", []) if existing else [],
        "created_at": created_at,
        "updated_at": now,
    }

    if existing:
        replace_audit_sandbox(audit_id, document)
    else:
        save_audit_sandbox(document)

    if body.test_sandbox:
        _apply_sandbox_test(document)

    return _to_response(document)


@router.get("/sandbox/session/{session_id}", response_model=AuditSandboxResponse)
def get_audit_sandbox_for_session(session_id: str) -> AuditSandboxResponse:
    doc = get_latest_audit_for_session(session_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audit sandbox configuration for this session",
        )
    return _to_response(doc)


@router.get("/sandbox/{audit_id}", response_model=AuditSandboxResponse)
def get_audit_sandbox_by_id(audit_id: str) -> AuditSandboxResponse:
    doc = get_audit_sandbox(audit_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit sandbox not found: {audit_id}",
        )
    return _to_response(doc)


@router.get("/sandbox/{audit_id}/report", response_model=AuditReportResponse)
def get_audit_report(audit_id: str) -> AuditReportResponse:
    doc = get_audit_sandbox(audit_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit sandbox not found: {audit_id}",
        )
    if not doc.get("test_cases"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate test cases before building the governance report",
        )
    report = generate_audit_report(doc)
    return AuditReportResponse(**report)


@router.post("/sandbox/{audit_id}/test", response_model=SandboxTestResponse)
def test_audit_sandbox(audit_id: str) -> SandboxTestResponse:
    doc = get_audit_sandbox(audit_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit sandbox not found: {audit_id}",
        )
    if not (doc.get("system_url") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Save system URL before testing sandbox",
        )
    return _apply_sandbox_test(doc)


@router.post("/sandbox/{audit_id}/start-generating-test-cases", response_model=StartAuditResponse)
def start_generating_test_cases(audit_id: str) -> StartAuditResponse:
    doc = get_audit_sandbox(audit_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit sandbox not found: {audit_id}",
        )

    session = _load_discovery_session(doc["session_id"])
    _require_complete_discovery(session)

    if not (doc.get("system_url") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Save system URL before starting audit",
        )

    if not doc.get("sandbox_test_passed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run sandbox test and receive HTTP 200 before generating test cases",
        )

    customer_id = doc.get("customer_id") or session.get("customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer id is required to generate test cases from the knowledge graph",
        )

    instance_count = kg_context.customer_instance_count(customer_id)

    now = _utc_now()
    doc["status"] = "generating"
    doc["updated_at"] = now
    replace_audit_sandbox(audit_id, doc)

    gen_result = generate_all_strategies(customer_id, session=session)

    if not gen_result.test_cases:
        doc["status"] = "failed"
        doc["updated_at"] = _utc_now()
        replace_audit_sandbox(audit_id, doc)
        if instance_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=KG_MAP_MESSAGE.format(customer_id=customer_id),
            )
        detail = "; ".join(gen_result.warnings) or "No test cases could be generated"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    doc["test_cases"] = gen_result.test_cases
    doc["status"] = "ready"
    doc["updated_at"] = _utc_now()
    replace_audit_sandbox(audit_id, doc)

    message = (
        f"Generated {len(gen_result.test_cases)} test cases "
        f"across {len(gen_result.strategies_generated)} strategies."
    )
    if gen_result.strategy_confidence:
        scores = ", ".join(
            f"{name}={score:.2f}" for name, score in gen_result.strategy_confidence.items()
        )
        message += f" Confidence: {scores}."
    if gen_result.warnings:
        message += f" Notes: {'; '.join(gen_result.warnings)}."

    return StartAuditResponse(
        audit_id=audit_id,
        status="ready",
        test_cases_generated=len(gen_result.test_cases),
        message=message,
        strategies_generated=gen_result.strategies_generated,
    )


@router.post(
    "/sandbox/{audit_id}/test-cases/{test_case_id}/execute",
    response_model=ExecuteTestCaseResponse,
)
def execute_test_case(audit_id: str, test_case_id: str) -> ExecuteTestCaseResponse:
    doc = get_audit_sandbox(audit_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit sandbox not found: {audit_id}",
        )

    if not doc.get("sandbox_test_passed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run sandbox test and receive HTTP 200 before executing test cases",
        )

    cases = doc.get("test_cases") or []
    case_index = next(
        (i for i, tc in enumerate(cases) if tc.get("test_case_id") == test_case_id),
        None,
    )
    if case_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found: {test_case_id}",
        )

    case = dict(cases[case_index])
    user_prompt = (case.get("user_prompt") or "").strip()
    if not user_prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test case has no user_prompt to execute",
        )

    case["status"] = "running"
    cases[case_index] = case
    doc["test_cases"] = cases
    doc["updated_at"] = _utc_now()
    replace_audit_sandbox(audit_id, doc)

    execution_id = str(uuid.uuid4())
    started_at = execution_started_at()
    already_linked = {
        str(execution.get("phoenix_trace_id"))
        for tc in cases
        if (execution := tc.get("execution")) and execution.get("phoenix_trace_id")
    }

    request_body = inject_user_prompt(doc.get("sample_request_body"), user_prompt)
    result = probe_sandbox(
        system_url=doc["system_url"],
        auth_token=doc.get("auth_token"),
        sample_request_body=request_body,
    )

    if result["passed"]:
        final_status = "evaluating"
        message = (
            f"{result['message']} Trace evaluation queued for execution {execution_id}."
        )
        execution: dict[str, Any] = {
            "status_code": result["status_code"],
            "response_preview": result.get("response_preview"),
            "executed_at": _utc_now(),
            "passed": None,
            "message": message,
            "execution_id": execution_id,
            "evaluation_status": "pending_trace",
        }
        job = build_trace_evaluation_job(
            audit_id=audit_id,
            customer_id=str(doc.get("customer_id") or ""),
            test_case_id=test_case_id,
            execution_id=execution_id,
            started_at=started_at,
            exclude_trace_ids=sorted(already_linked),
            user_prompt=user_prompt,
            pass_condition=case.get("pass_condition", ""),
            fail_condition=case.get("fail_condition", ""),
            response_preview=result.get("response_preview"),
            strategy=case.get("strategy", ""),
            title=case.get("title", ""),
            severity=case.get("severity", "MEDIUM"),
        )
    else:
        final_status = "error"
        execution = {
            "status_code": result["status_code"],
            "response_preview": result.get("response_preview"),
            "executed_at": _utc_now(),
            "passed": None,
            "message": result["message"],
            "execution_id": execution_id,
            "evaluation_status": "error",
            "evaluated_at": _utc_now(),
        }
        job = None

    case["status"] = final_status
    case["execution"] = execution
    cases[case_index] = case
    doc["test_cases"] = cases
    doc["updated_at"] = _utc_now()
    replace_audit_sandbox(audit_id, doc)

    if job is not None:
        try:
            publish_trace_evaluation_job(job)
        except Exception as exc:
            final_status = "error"
            execution["evaluation_status"] = "error"
            execution["message"] = f"Failed to queue trace evaluation: {exc}"
            execution["evaluated_at"] = _utc_now()
            case["status"] = final_status
            case["execution"] = execution
            cases[case_index] = case
            doc["test_cases"] = cases
            doc["updated_at"] = _utc_now()
            replace_audit_sandbox(audit_id, doc)

    return ExecuteTestCaseResponse(
        audit_id=audit_id,
        test_case_id=test_case_id,
        status=final_status,
        execution=TestCaseExecutionResponse(**execution),
    )

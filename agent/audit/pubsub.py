from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

EVENT_TYPE = "audit.trace_evaluation"


@dataclass(frozen=True)
class PubSubConfig:
    project_id: str
    topic_id: str
    subscription_id: str


def pubsub_configured() -> bool:
    return bool(_load_config())


def _load_config() -> PubSubConfig | None:
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    topic_id = os.getenv("GCP_TOPIC_ID", "").strip()
    subscription_id = os.getenv("GCP_SUBSCRIPTION_ID", "").strip()
    if not project_id or not topic_id or not subscription_id:
        return None
    return PubSubConfig(
        project_id=project_id,
        topic_id=topic_id,
        subscription_id=subscription_id,
    )


def _topic_path(config: PubSubConfig) -> str:
    return f"projects/{config.project_id}/topics/{config.topic_id}"


def _subscription_path(config: PubSubConfig) -> str:
    return f"projects/{config.project_id}/subscriptions/{config.subscription_id}"


def build_trace_evaluation_job(
    *,
    audit_id: str,
    customer_id: str,
    test_case_id: str,
    execution_id: str,
    started_at: str,
    exclude_trace_ids: list[str],
    user_prompt: str,
    pass_condition: str,
    fail_condition: str,
    response_preview: str | None,
    strategy: str,
    title: str,
    severity: str,
) -> dict[str, Any]:
    return {
        "event_type": EVENT_TYPE,
        "audit_id": audit_id,
        "customer_id": customer_id,
        "test_case_id": test_case_id,
        "execution_id": execution_id,
        "started_at": started_at,
        "exclude_trace_ids": exclude_trace_ids,
        "user_prompt": user_prompt,
        "pass_condition": pass_condition,
        "fail_condition": fail_condition,
        "response_preview": response_preview,
        "strategy": strategy,
        "title": title,
        "severity": severity,
    }


def publish_trace_evaluation_job(job: dict[str, Any]) -> str:
    """Publish a trace evaluation job; returns Pub/Sub message ID."""
    config = _load_config()
    if config is None:
        raise RuntimeError(
            "Pub/Sub not configured. Set GCP_PROJECT_ID, GCP_TOPIC_ID, GCP_SUBSCRIPTION_ID."
        )

    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    payload = json.dumps(job, default=str).encode("utf-8")
    future = publisher.publish(
        _topic_path(config),
        payload,
        event_type=EVENT_TYPE,
        audit_id=str(job.get("audit_id", "")),
        execution_id=str(job.get("execution_id", "")),
    )
    message_id = future.result(timeout=30)
    logger.info(
        "Published trace evaluation job audit=%s case=%s message_id=%s",
        job.get("audit_id"),
        job.get("test_case_id"),
        message_id,
    )
    return message_id


def pull_trace_evaluation_job(*, timeout_seconds: float = 30.0) -> tuple[dict[str, Any], str] | None:
    """Pull one trace evaluation message; returns (job, ack_id) or None."""
    config = _load_config()
    if config is None:
        raise RuntimeError("Pub/Sub not configured")

    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    response = subscriber.pull(
        request={
            "subscription": _subscription_path(config),
            "max_messages": 1,
        },
        timeout=timeout_seconds,
    )
    if not response.received_messages:
        return None

    received = response.received_messages[0]
    job = json.loads(received.message.data.decode("utf-8"))
    if job.get("event_type") != EVENT_TYPE:
        logger.warning("Ignoring unknown Pub/Sub event_type: %s", job.get("event_type"))
        subscriber.acknowledge(
            request={
                "subscription": _subscription_path(config),
                "ack_ids": [received.ack_id],
            }
        )
        return None
    return job, received.ack_id


def acknowledge_message(ack_id: str) -> None:
    config = _load_config()
    if config is None:
        raise RuntimeError("Pub/Sub not configured")

    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    subscriber.acknowledge(
        request={
            "subscription": _subscription_path(config),
            "ack_ids": [ack_id],
        }
    )

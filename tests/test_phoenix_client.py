from __future__ import annotations

from unittest.mock import patch

from agent.audit.phoenix_client import fetch_latest_trace, fetch_trace_payload, phoenix_configured


@patch("agent.audit.phoenix_client.get_customer_phoenix_settings")
def test_phoenix_configured_uses_customer_id(mock_get):
    from agent.api.phoenix_config import PhoenixSettings

    mock_get.return_value = PhoenixSettings(
        api_key="key",
        collector_endpoint="https://app.phoenix.arize.com/s/space",
        project_name="demo",
    )
    assert phoenix_configured("cust-1") is True
    mock_get.assert_called_once_with("cust-1")


@patch("agent.audit.phoenix_client.get_customer_phoenix_settings", return_value=None)
@patch("agent.audit.phoenix_client._list_recent_spans")
def test_fetch_latest_trace_picks_newest_and_skips_linked(mock_list, _mock_settings):
    from agent.api.phoenix_config import PhoenixSettings

    settings = PhoenixSettings(
        api_key="key",
        collector_endpoint="https://app.phoenix.arize.com/s/space",
        project_name="demo",
    )
    mock_list.return_value = [
        {
            "id": "old",
            "name": "governai.process",
            "context": {"trace_id": "trace-old", "span_id": "span-old"},
            "end_time": "2026-06-05T10:00:00Z",
        },
        {
            "id": "new",
            "name": "governai.process",
            "context": {"trace_id": "trace-new", "span_id": "span-new"},
            "end_time": "2026-06-05T10:00:02Z",
        },
    ]

    with patch(
        "agent.audit.phoenix_client._require_settings",
        return_value=settings,
    ):
        link = fetch_latest_trace(
            customer_id="cust-1",
            exclude_trace_ids={"trace-old"},
            max_attempts=1,
            pause_seconds=0,
        )

    assert link is not None
    assert link["phoenix_trace_id"] == "trace-new"
    assert link["phoenix_span_global_id"] == "new"


@patch("agent.audit.phoenix_client.get_customer_phoenix_settings", return_value=None)
@patch("agent.audit.phoenix_client._list_spans_by_trace_id")
def test_fetch_trace_payload_parses_governai_trace(mock_list, _mock_settings):
    from agent.api.phoenix_config import PhoenixSettings

    settings = PhoenixSettings(
        api_key="key",
        collector_endpoint="https://app.phoenix.arize.com/s/space",
        project_name="demo",
    )
    mock_list.return_value = [
        {
            "name": "governai.process",
            "attributes": {
                "governai.trace": '{"trace_id":"t1","steps":[{"type":"tool_call","tool":"crm"}]}',
            },
        }
    ]

    with patch(
        "agent.audit.phoenix_client._require_settings",
        return_value=settings,
    ):
        payload = fetch_trace_payload("trace-abc", customer_id="cust-1")

    assert payload is not None
    assert payload["trace_id"] == "t1"
    assert payload["steps"][0]["tool"] == "crm"

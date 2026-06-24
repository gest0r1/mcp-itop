"""Unit tests for mcp-itop server.

These tests mock the iTop REST API responses. They verify:
  - OQL query construction
  - Response parsing
  - Error handling
  - Analytics calculations
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import httpx


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_env():
    """Set required env vars before each test."""
    os.environ["ITOP_URL"] = "https://demo.itop.com"
    os.environ["ITOP_USER"] = "admin"
    os.environ["ITOP_PASSWORD"] = "secret"
    os.environ["ITOP_VERSION"] = "1.3"
    yield
    for k in ["ITOP_URL", "ITOP_USER", "ITOP_PASSWORD", "ITOP_VERSION", "ITOP_TOKEN"]:
        os.environ.pop(k, None)


def make_itop_response(code: int, message: str, objects: dict | None = None) -> dict:
    resp = {"code": code, "message": message}
    if objects is not None:
        resp["objects"] = objects
    return resp


def make_ticket(ref: str, status: str, **kwargs) -> dict:
    fields = {
        "id": 0,
        "ref": ref,
        "title": "Test ticket",
        "status": status,
        "org_name": "Demo",
        "service_name": "Service Desk",
        "agent_name": "Agent A",
        "caller_name": "User X",
        "start_date": "2026-06-01 10:00:00",
        "resolution_date": "2026-06-02 14:00:00",
        "close_date": "2026-06-02 15:00:00",
        "assignment_date": "2026-06-01 10:30:00",
        "last_update": "2026-06-02 12:00:00",
        "sla_tto_passed": "true",
        "sla_ttr_passed": "true",
        "tto_time_spent": "1800",
        "ttr_time_spent": "14400",
        "time_spent": "3600",
    }
    fields.update(kwargs)
    return {f"UserRequest::{ref}": {"class": "UserRequest", "key": ref, "fields": fields}}


@pytest.fixture
def mock_client():
    """Patch _get_http_client to return a controlled AsyncClient mock.

    The returned client has .post() returning a response-like object
    where .json() is a plain sync method (like real httpx.Response).
    """
    with patch("server._get_http_client") as mock_get:
        client = MagicMock(spec=httpx.AsyncClient)
        mock_get.return_value = client

        def make_response(json_data: dict, status: int = 200):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = status
            resp.json.return_value = json_data
            return resp

        client.post = AsyncMock()
        # Store make_response helper on client for test use
        client._make_response = make_response
        yield client


# ── Test helpers ──────────────────────────────────────────────────────────


def test_str_or():
    from server import _str_or
    assert _str_or({"a": "hello"}, "a") == "hello"
    assert _str_or({"a": None}, "a", "default") == "default"
    assert _str_or({}, "missing", "fallback") == "fallback"
    assert _str_or({"a": 42}, "a") == "42"


def test_parse_key():
    from server import _parse_key
    assert _parse_key("42") == 42
    assert _parse_key('{"name": "test"}') == {"name": "test"}
    assert _parse_key("SELECT Server") == "SELECT Server"


def test_parse_date_range():
    from server import _parse_date_range
    s, e = _parse_date_range("2026-01-01", "2026-01-31")
    assert s.startswith("2026-01-01")
    assert e.startswith("2026-01-31")

    s2, e2 = _parse_date_range("", "")
    assert s2 is not None
    assert e2 is not None

    with pytest.raises(ValueError):
        _parse_date_range("not-a-date", "")


def test_format_duration():
    from server import _format_duration
    assert _format_duration(30) == "30s"
    assert _format_duration(150) == "2min"
    assert _format_duration(3600) == "1h 0min"
    assert _format_duration(3660) == "1h 1min"
    assert _format_duration(90000) == "1d 1h"


def test_extract_objects():
    from server import _extract_objects
    resp = make_itop_response(0, "Found: 2", make_ticket("RQ-1", "closed"))
    objs = _extract_objects(resp)
    assert len(objs) == 1
    assert objs[0]["class"] == "UserRequest"

    assert _extract_objects({}) == []
    assert _extract_objects({"objects": None}) == []


def test_format_objects_error():
    from server import _format_objects
    resp = {"code": 1, "message": "Unauthorized"}
    result = _format_objects(resp)
    assert "Error" in result
    assert "1" in result


def test_format_table():
    from server import _format_table
    result = _format_table(["A", "B"], [["1", "2"], ["3", "4"]])
    assert "A" in result
    assert "1" in result
    assert _format_table(["X"], []) == "(no data)"


# ── Test iTop client ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_itop_request_success(mock_client):
    from server import _itop_request
    mock_client.post.return_value = mock_client._make_response({"code": 0, "message": "Found: 1"})
    result = await _itop_request({"operation": "core/get", "class": "UserRequest", "key": "SELECT UserRequest"})
    assert result["code"] == 0


@pytest.mark.asyncio
async def test_itop_request_http_error(mock_client):
    from server import _itop_request
    mock_client.post.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock(status_code=401, text="Unauthorized")
    )
    result = await _itop_request({"operation": "core/get"})
    assert "code" in result


@pytest.mark.asyncio
async def test_itop_request_missing_url():
    import server
    with patch.object(server, "ITOP_URL", ""):
        with pytest.raises(ValueError, match="ITOP_URL is not configured"):
            await server._itop_request({"operation": "core/get"})


# ── Test Analytics tools ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sla_report_all_passed(mock_client):
    from server import itop_sla_report
    tickets = {}
    for i in range(5):
        tickets.update(make_ticket(f"RQ-{i}", "closed"))
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 5", tickets)
    )
    result = await itop_sla_report(service_name="Service Desk", start_date="2026-06-01", end_date="2026-06-30")
    assert "5" in result
    assert "TTO" in result
    assert "100.0%" in result


@pytest.mark.asyncio
async def test_sla_report_empty(mock_client):
    from server import itop_sla_report
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 0")
    )
    result = await itop_sla_report(service_name="Nonexistent")
    assert "No tickets" in result


@pytest.mark.asyncio
async def test_agent_workload(mock_client):
    from server import itop_agent_workload
    tickets = make_ticket("RQ-1", "assigned", agent_name="Bob", time_spent="0")
    tickets.update(make_ticket("RQ-2", "closed", agent_name="Bob", time_spent="3600"))
    tickets.update(make_ticket("RQ-3", "assigned", agent_name="Alice", time_spent="0"))
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 3", tickets)
    )
    result = await itop_agent_workload()
    assert "Bob" in result
    assert "Alice" in result
    assert "1h 0min" in result


@pytest.mark.asyncio
async def test_idle_agents(mock_client):
    from server import itop_idle_agents
    tickets = make_ticket("RQ-1", "assigned", assignment_date="2026-01-01 08:00:00", last_update="2026-01-01 08:00:00")
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 1", tickets)
    )
    result = await itop_idle_agents(hours=2)
    assert "RQ-1" in result


@pytest.mark.asyncio
async def test_service_quality(mock_client):
    from server import itop_service_quality
    # Titles need ≥2 shared non-stop keywords to trigger matching
    tickets = make_ticket("RQ-1", "closed", title="Ошибка доступа к почте Outlook", service_name="Service A", caller_name="User1")
    tickets.update(make_ticket("RQ-2", "closed", title="Ошибка доступа к почте Exchange", service_name="Service B", caller_name="User2"))
    tickets.update(make_ticket("RQ-3", "closed", title="Сбой сети", service_name="Network", caller_name="User3"))
    # RQ-1/RQ-2 share: ошибка, доступ, почте (3 keywords)
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 3", tickets)
    )
    result = await itop_service_quality(days=30, min_similar=2)
    assert "Service A" in result or "Service B" in result


@pytest.mark.asyncio
async def test_caller_quality(mock_client):
    from server import itop_caller_quality
    tickets = {}
    for i in range(6):
        tickets.update(make_ticket(f"RQ-{i}", "closed", caller_name="Ivanov", service_name="Service A"))
    for i in range(6, 12):
        tickets.update(make_ticket(f"RQ-{i}", "closed", caller_name="Petrov", service_name="Service B"))
    tickets.update(make_ticket("RQ-12", "closed", caller_name="Ivanov", service_name="Service B"))
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, f"Found: {len(tickets)}", tickets)
    )
    result = await itop_caller_quality(min_tickets=5)
    assert "Ivanov" in result
    assert "Petrov" in result


@pytest.mark.asyncio
async def test_agent_correction_rate(mock_client):
    from server import itop_agent_correction_rate
    tickets = {}
    for i in range(15):
        tickets.update(make_ticket(f"RQ-{i}", "closed", agent_name="Fixer", service_name=f"Svc {i % 3}"))
    for i in range(15, 30):
        tickets.update(make_ticket(f"RQ-{i}", "closed", agent_name="Stickler", service_name="Single Svc"))
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, f"Found: {len(tickets)}", tickets)
    )
    result = await itop_agent_correction_rate(min_tickets=10)
    assert "Fixer" in result
    assert "Stickler" in result


@pytest.mark.asyncio
async def test_ticket_summary(mock_client):
    from server import itop_ticket_summary
    tickets = make_ticket("RQ-1", "closed")
    tickets.update(make_ticket("RQ-2", "resolved"))
    tickets.update(make_ticket("RQ-3", "assigned"))
    tickets.update(make_ticket("RQ-4", "assigned"))
    tickets.update(make_ticket("RQ-5", "pending"))
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 5", tickets)
    )
    result = await itop_ticket_summary(days=7)
    assert "5" in result
    assert "closed" in result
    assert "assigned" in result
    assert "SLA" in result


# ── Test KB tools ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_kb(mock_client):
    from server import itop_search_kb
    articles = {
        "KBEntry::1": {
            "class": "KBEntry",
            "key": "1",
            "fields": {"id": "1", "title": "How to reset password", "summary": "Step by step guide",
                       "category_name": "Security", "status": "published"},
        }
    }
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 1", articles)
    )
    result = await itop_search_kb(query="password")
    assert "KBEntry Articles" in result or "FAQ Articles" in result
    assert "reset password" in result


@pytest.mark.asyncio
async def test_get_kb_article(mock_client):
    from server import itop_get_kb_article
    article = {
        "KBEntry::1": {
            "class": "KBEntry",
            "key": "1",
            "fields": {"id": "1", "title": "Article", "body": "Full content here"},
        }
    }
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 1", article)
    )
    result = await itop_get_kb_article(article_id=1)
    assert "Article" in result
    assert "Full content" in result


# ── Test Comment tools ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_comment(mock_client):
    from server import itop_add_comment
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Updated: 1", make_ticket("RQ-1", "assigned"))
    )
    result = await itop_add_comment(ticket_class="UserRequest", ticket_id=1, text="Test comment")
    assert "RQ-1" in result


@pytest.mark.asyncio
async def test_get_log(mock_client):
    from server import itop_get_log
    ticket = make_ticket("RQ-1", "assigned")
    ticket["UserRequest::RQ-1"]["fields"]["public_log"] = {
        "items": [{"date": "2026-06-01 10:00:00", "user_login": "admin", "message": "Working on it"}]
    }
    ticket["UserRequest::RQ-1"]["fields"]["private_log"] = {
        "items": [{"date": "2026-06-01 09:00:00", "user_login": "agent", "message": "Internal note"}]
    }
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 1", ticket)
    )
    result = await itop_get_log(ticket_class="UserRequest", ticket_id=1, log_type="both")
    assert "Public Log" in result
    assert "Private Log" in result
    assert "admin" in result
    assert "Internal note" in result


# ── Test CRUD tools ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_itop_create(mock_client):
    from server import itop_create
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Created: 1", make_ticket("RQ-99", "new"))
    )
    result = await itop_create(obj_class="UserRequest", fields='{"title": "test", "org_id": 1}')
    assert "RQ-99" in result


@pytest.mark.asyncio
async def test_itop_update(mock_client):
    from server import itop_update
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Updated: 1", make_ticket("RQ-1", "assigned"))
    )
    result = await itop_update(obj_class="UserRequest", key="1", fields='{"title": "new title"}')
    assert "RQ-1" in result


@pytest.mark.asyncio
async def test_itop_delete(mock_client):
    from server import itop_delete
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Deleted: 1 simulated", make_ticket("RQ-1", "closed"))
    )
    result = await itop_delete(obj_class="UserRequest", key="1")
    assert "Deleted" in result or "RQ-1" in result


@pytest.mark.asyncio
async def test_itop_apply_stimulus(mock_client):
    from server import itop_apply_stimulus
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Updated: 1", make_ticket("RQ-1", "assigned"))
    )
    result = await itop_apply_stimulus(obj_class="UserRequest", key="1", stimulus="ev_assign", fields='{"agent_id": 42}')
    assert "RQ-1" in result


@pytest.mark.asyncio
async def test_itop_describe_class(mock_client):
    from server import itop_describe_class
    mock_client.post.return_value = mock_client._make_response(
        make_itop_response(0, "Found: 1", make_ticket("RQ-1", "closed"))
    )
    result = await itop_describe_class("UserRequest")
    assert "UserRequest" in result
    assert "attributes" in result


# ── Test auth ─────────────────────────────────────────────────────────────


def test_main_no_url(capsys):
    """main() should exit with error if ITOP_URL missing."""
    import server
    with patch.object(server, "ITOP_URL", ""):
        with patch.object(server, "ITOP_TOKEN", ""):
            with patch.object(server, "ITOP_USER", ""):
                with patch.object(server, "ITOP_PASSWORD", ""):
                    with pytest.raises(SystemExit):
                        server.main()
                    captured = capsys.readouterr()
                    assert "ITOP_URL" in captured.out or "ITOP_URL" in captured.err

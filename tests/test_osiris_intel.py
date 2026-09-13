"""Tests for OSIRIS (Know the World) intelligence and 3D globe tools."""

import pytest
from unittest.mock import patch, MagicMock
from axon.core import Axon
from axon.security import PermissionLevel
from axon.tools.osiris import (
    osiris_status,
    osiris_briefing,
    osiris_get_layer,
    osiris_search_region,
    osiris_open_globe,
    LAYER_ROUTES,
)


def test_osiris_tools_registered_in_axon():
    """Verify that Axon registers all OSIRIS tools on startup."""
    axon = Axon().start()
    tools = axon.registry.list()
    assert "osiris.briefing" in tools
    assert "osiris.get_layer" in tools
    assert "osiris.search_region" in tools
    assert "osiris.open_globe" in tools
    assert "osiris.status" in tools
    axon.shutdown()


from axon.security import PermissionLevel, SecurityPolicyEngine


def test_osiris_security_policy_safe():
    """Verify that OSIRIS tools are classified as SAFE read-only intelligence."""
    policy = SecurityPolicyEngine()
    for tool_name in ("osiris.briefing", "osiris.get_layer", "osiris.search_region", "osiris.status"):
        decision = policy.evaluate(tool_name, {})
        assert decision.level == PermissionLevel.SAFE


def test_osiris_get_layer_unknown():
    """Verify error handling for unknown layer."""
    res = osiris_get_layer("unknown_layer_xyz")
    assert res["status"] == "error"
    assert "Unknown OSIRIS layer" in res["error"]


def test_osiris_search_region_empty():
    """Verify error handling for empty region query."""
    res = osiris_search_region("   ")
    assert res["status"] == "error"
    assert "cannot be empty" in res["error"]


def test_osiris_status_offline():
    """Verify offline handling when OSIRIS is not running."""
    res = osiris_status()
    assert res["status"] in ("online", "offline")
    assert "url" in res
    assert len(res["available_layers"]) > 0


def test_osiris_briefing_mocked():
    """Verify briefing synthesis with mocked API responses."""
    mock_news = [{"id": "n1", "name": "Global News 24"}]
    mock_conflicts = [{"id": "c1", "label": "Region A", "severity": "high"}]

    def mock_fetch(endpoint, params=None, timeout=4.0):
        if endpoint == "/api/live-news":
            return {"status": "success", "data": mock_news}
        elif endpoint == "/api/conflicts":
            return {"status": "success", "data": mock_conflicts}
        elif endpoint == "/api/earthquakes":
            return {"status": "success", "data": []}
        elif endpoint == "/api/malware":
            return {"status": "success", "data": []}
        return {"status": "offline", "error": "not found"}

    with patch("axon.tools.osiris._fetch_osiris_json", side_effect=mock_fetch):
        briefing = osiris_briefing()
        assert briefing["status"] == "success"
        assert len(briefing["news"]) == 1
        assert len(briefing["conflicts"]) == 1
        assert "OSIRIS World Briefing:" in briefing["summary"]


def test_osiris_get_layer_mocked():
    """Verify layer retrieval with mocked API response."""
    mock_data = [{"id": "cam1", "city": "Tokyo", "url": "https://example.com/stream"}]

    with patch("axon.tools.osiris._fetch_osiris_json") as mock_fetch:
        mock_fetch.return_value = {"status": "success", "data": mock_data}
        res = osiris_get_layer("cctv", limit=5)
        assert res["status"] == "success"
        assert res["layer"] == "cctv"
        assert res["count"] == 1
        assert res["data"][0]["city"] == "Tokyo"


def test_osiris_open_globe_mocked():
    """Verify open globe URL construction and browser dispatch."""
    with patch("webbrowser.open") as mock_open:
        res = osiris_open_globe(target="Tokyo", lat=35.6895, lng=139.6917)
        assert res["status"] == "success"
        assert "lat=35.6895" in res["url"]
        assert "lng=139.6917" in res["url"]
        assert "target=Tokyo" in res["url"]
        mock_open.assert_called_once_with(res["url"])

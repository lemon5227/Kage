"""
Round 15 Unit Tests - TASK-5: Server Fat Controller Route Modularization
Verifies modular APIRouters in core/routes/* mounted on app,
backward-compatible function re-exports, and standard HTTP response schemas.
"""

from fastapi.testclient import TestClient
import pytest
import core.server as srv
from core.routes.system import router as system_router
from core.routes.models import router as models_router
from core.routes.memory import router as memory_router


@pytest.fixture
def client():
    return TestClient(srv.app)


class TestModularRoutes:
    def test_system_router_endpoints(self, client):
        # Health check
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert "mode" in data

        # Config get
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

        # Runtime status
        resp = client.get("/api/runtime/status")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_models_router_endpoints(self, client):
        # Downloads list
        resp = client.get("/api/models/download")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        # Models list
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "managed" in data
        assert "hf_cache" in data

        # Llama status
        resp = client.get("/api/models/llama/status")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_memory_router_endpoints_without_server(self, client):
        # When server instance is not running, gracefully returns error response
        resp = client.get("/api/memory/stats")
        assert resp.status_code == 200
        assert "error" in resp.json()

        resp = client.get("/api/memory/entries")
        assert resp.status_code == 200
        assert "error" in resp.json()

        resp = client.get("/api/memory/profile")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_backward_compatible_reexports_on_server_module(self):
        # Ensure callers importing functions directly from core.server still work
        assert callable(getattr(srv, "health", None))
        assert callable(getattr(srv, "get_config", None))
        assert callable(getattr(srv, "set_config", None))
        assert callable(getattr(srv, "list_models", None))
        assert callable(getattr(srv, "delete_model", None))
        assert callable(getattr(srv, "memory_stats", None))
        assert callable(getattr(srv, "memory_entries", None))
        assert callable(getattr(srv, "get_hybrid_settings", None))

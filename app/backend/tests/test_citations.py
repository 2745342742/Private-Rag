from __future__ import annotations


def test_platform_app_imports():
    from app.main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/health" in paths
    assert "/api/v1/auth/login" in paths
    assert "/health" in paths
    assert "/knowledge/chatkit" not in paths

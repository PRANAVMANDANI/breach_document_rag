from app.main import app


def test_app_metadata():
    assert app.title == "BREACH API"
    assert app.version == "1.0.0"


def test_health_route_registered():
    paths = {route.path for route in app.routes}
    assert "/health" in paths


def test_document_and_query_routers_mounted():
    paths = {route.path for route in app.routes}
    assert "/api/documents/" in paths
    assert "/api/query/" in paths

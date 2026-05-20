from fastapi.testclient import TestClient

from banyan_platform.app import create_app
from banyan_platform.config import DatabaseConfig


def test_rest_create_and_get_term():
    app = create_app(DatabaseConfig(dialect="sqlite", sqlite_path=":memory:"))
    client = TestClient(app)

    create_response = client.post("/api/v1/terms", json={"name": "beta", "description": "second"})
    assert create_response.status_code == 201
    term_id = create_response.json()["id"]

    get_response = client.get(f"/api/v1/terms/{term_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "beta"

import pytest

from banyan_platform.config import DatabaseConfig
from banyan_platform.persistence.connection import create_database
from banyan_platform.persistence.ddl import bootstrap
from banyan_platform.services.taxonomy_service import BanyanService

ACTOR = "test-agent"


@pytest.fixture(scope="function")
def db():
    """Fresh in-memory DuckDB instance, fully bootstrapped, per test."""
    cfg = DatabaseConfig(dialect="duckdb", duckdb_path=":memory:")
    database = create_database(cfg)
    bootstrap(database)
    return database


@pytest.fixture(scope="function")
def service(db):
    return BanyanService(db)


@pytest.fixture(scope="function")
def client(db):
    from fastapi.testclient import TestClient
    from banyan_platform.app import create_app
    from banyan_platform.config import DatabaseConfig as Cfg
    # Re-use the already-bootstrapped db by wiring it directly into a service
    # and bypassing create_app's own bootstrap so we share state across calls.
    from banyan_platform.api.rest import build_rest_router
    from fastapi import FastAPI

    svc = BanyanService(db)
    app = FastAPI()
    app.include_router(build_rest_router(svc))
    return TestClient(app)

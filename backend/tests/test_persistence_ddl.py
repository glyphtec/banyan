from banyan_platform.persistence.ddl import ddl_for


def test_postgres_ddl_contains_serial_pk():
    ddl = ddl_for("postgres")
    assert "SERIAL PRIMARY KEY" in ddl


def test_sqlite_ddl_contains_autoincrement_pk():
    ddl = ddl_for("sqlite")
    assert "AUTOINCREMENT" in ddl

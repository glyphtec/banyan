from fastapi.testclient import TestClient

from banyan_platform.app import create_app
from banyan_platform.config import DatabaseConfig


def test_graphql_mutation_and_query_term():
    app = create_app(DatabaseConfig(dialect="sqlite", sqlite_path=":memory:"))
    client = TestClient(app)

    mutation = {
        "query": "mutation { createTerm(name: \"gamma\", description: \"third\") { id name description } }"
    }
    mutation_response = client.post("/graphql", json=mutation)
    assert mutation_response.status_code == 200
    term_id = mutation_response.json()["data"]["createTerm"]["id"]

    query = {"query": f"query {{ term(termId: {term_id}) {{ id name description }} }}"}
    query_response = client.post("/graphql", json=query)
    assert query_response.status_code == 200
    assert query_response.json()["data"]["term"]["name"] == "gamma"

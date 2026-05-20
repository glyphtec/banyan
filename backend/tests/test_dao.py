from banyan_platform.config import DatabaseConfig
from banyan_platform.dao.taxonomy_dao import TaxonomyDAO
from banyan_platform.persistence.connection import Database


def test_taxonomy_dao_create_and_get_term():
    config = DatabaseConfig(dialect="sqlite", sqlite_path=":memory:")
    dao = TaxonomyDAO(Database(config), "sqlite")
    dao.initialize_schema()

    term_id = dao.create_term("alpha", "first term")
    term = dao.get_term(term_id)

    assert term == {"id": term_id, "name": "alpha", "description": "first term"}

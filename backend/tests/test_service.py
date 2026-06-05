import pytest

from banyan_platform.config import DatabaseConfig
from banyan_platform.dao.taxonomy_dao import TaxonomyDAO
from banyan_platform.persistence.connection import Database
from banyan_platform.services.taxonomy_service import TaxonomyService


def test_taxonomy_service_raises_for_missing_term():
    config = DatabaseConfig(dialect="sqlite", sqlite_path=":memory:")
    service = TaxonomyService(TaxonomyDAO(Database(config), "sqlite"))
    service.initialize()

    with pytest.raises(KeyError):
        service.get_term(999)

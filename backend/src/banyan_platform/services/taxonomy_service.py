from banyan_platform.dao.taxonomy_dao import TaxonomyDAO


class TaxonomyService:
    def __init__(self, dao: TaxonomyDAO):
        self.dao = dao

    def initialize(self) -> None:
        self.dao.initialize_schema()

    def register_term(self, name: str, description: str | None = None) -> dict:
        term_id = self.dao.create_term(name=name, description=description)
        return self.get_term(term_id)

    def get_term(self, term_id: int) -> dict:
        term = self.dao.get_term(term_id)
        if not term:
            raise KeyError(f"Term {term_id} not found")
        return term

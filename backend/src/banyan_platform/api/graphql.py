import strawberry
from strawberry.fastapi import GraphQLRouter

from banyan_platform.services.taxonomy_service import TaxonomyService


@strawberry.type
class Term:
    id: int
    name: str
    description: str | None


def build_graphql_router(service: TaxonomyService) -> GraphQLRouter:
    @strawberry.type
    class Query:
        @strawberry.field
        def term(self, term_id: int) -> Term:
            return Term(**service.get_term(term_id))

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create_term(self, name: str, description: str | None = None) -> Term:
            return Term(**service.register_term(name=name, description=description))

    schema = strawberry.Schema(query=Query, mutation=Mutation)
    return GraphQLRouter(schema, path="/graphql")

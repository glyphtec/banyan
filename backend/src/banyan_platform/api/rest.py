from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from banyan_platform.services.taxonomy_service import TaxonomyService


class TermCreate(BaseModel):
    name: str
    description: str | None = None


class TermResponse(BaseModel):
    id: int
    name: str
    description: str | None = None


def build_rest_router(service: TaxonomyService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["terms"])

    @router.post("/terms", response_model=TermResponse, status_code=201)
    def create_term(payload: TermCreate):
        return service.register_term(payload.name, payload.description)

    @router.get("/terms/{term_id}", response_model=TermResponse)
    def get_term(term_id: int):
        try:
            return service.get_term(term_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router

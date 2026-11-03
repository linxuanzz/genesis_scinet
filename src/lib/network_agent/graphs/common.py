"""Pieces shared by the branches of graph A."""

from collections.abc import Callable, Mapping
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..schemas import ErrorResponse

M = TypeVar("M", bound=BaseModel)


def on_error(target_if_ok: str, target_if_error: str = "respond") -> Callable[[Mapping], str]:
    """A conditional edge: go to target_if_error once some node has put an ``error`` into state, else go on."""
    def route(state: Mapping) -> str:
        return target_if_error if "error" in state else target_if_ok
    return route


def parse_request(model: type[M], raw: object, id_field: str = "request_id") -> M | ErrorResponse:
    """Validate a raw message into ``model``; if it is malformed, an invalid_request error addressed to
    whatever id the raw message carries."""
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        request_id = raw.get(id_field) if isinstance(raw, dict) else None
        return ErrorResponse(request_id=str(request_id or "unknown"), code="invalid_request",
                             detail="; ".join(err["msg"] for err in e.errors()))

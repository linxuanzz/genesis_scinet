"""Pieces shared by the branches of graph A."""

from collections.abc import Callable, Mapping


def on_error(target_if_ok: str, target_if_error: str = "respond") -> Callable[[Mapping], str]:
    """A conditional edge: go to target_if_error once some node has put an ``error`` into state, else go on."""
    def route(state: Mapping) -> str:
        return target_if_error if "error" in state else target_if_ok
    return route

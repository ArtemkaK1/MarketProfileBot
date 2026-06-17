from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    detail: str
    order_id: int | None = None

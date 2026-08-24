"""Logical model catalog exposed via GET /v1/models.

Nexcoder asks for logical ids (nexa-code, nexa-general, nexa-agent); Nexa
owns the mapping to concrete provider models. Static defaults here can be
augmented by the ai_model_catalog table.
"""

from __future__ import annotations

from dataclasses import dataclass

from nexa.config import Settings


@dataclass(frozen=True)
class LogicalModel:
    id: str
    display_name: str
    capabilities: list[str]
    description: str


CATALOG: list[LogicalModel] = [
    LogicalModel(
        id="nexa-code",
        display_name="Nexa Code",
        capabilities=["chat", "code", "streaming", "tools"],
        description="Optimized for coding assistance and edits",
    ),
    LogicalModel(
        id="nexa-general",
        display_name="Nexa General",
        capabilities=["chat", "streaming"],
        description="Fast general-purpose assistant",
    ),
    LogicalModel(
        id="nexa-agent",
        display_name="Nexa Agent",
        capabilities=["chat", "code", "streaming", "tools", "agentic"],
        description="Agentic workloads with tool orchestration",
    ),
]

_CAPABILITY_TO_PLAN: dict[str, frozenset[str]] = {}  # reserved for per-model gating


def known_logical_model(model_id: str) -> bool:
    return any(m.id == model_id for m in CATALOG)


def catalog_payload(settings: Settings) -> dict:
    models = []
    for m in CATALOG:
        models.append(
            {
                "id": m.id,
                "display_name": m.display_name,
                "capabilities": m.capabilities,
                "description": m.description,
                "object": "model",
                "owned_by": "nexa",
            }
        )
    return {"models": models, "data": models}

"""Model catalog exposed via GET /v1/models.

Models are identified by their real NVIDIA NIM ids end-to-end: clients send
the same id they see here, and Nexa routes it to the provider unchanged
(unless an explicit override exists in NEXA_MODEL_ROUTES).
"""

from __future__ import annotations

from dataclasses import dataclass

from nexa.config import Settings


@dataclass(frozen=True)
class CatalogModel:
    id: str
    display_name: str
    capabilities: list[str]
    description: str


CATALOG: list[CatalogModel] = [
    CatalogModel(
        id="stepfun-ai/step-3.7-flash",
        display_name="Step 3.7 Flash",
        capabilities=["chat", "code", "streaming", "vision"],
        description="Fast general-purpose model with vision input",
    ),
    CatalogModel(
        id="nvidia/nemotron-3-ultra-550b-a55b",
        display_name="Nemotron 3 Ultra",
        capabilities=["chat", "code", "streaming", "tools", "reasoning"],
        description="Flagship reasoning model for complex agentic workloads",
    ),
    CatalogModel(
        id="nvidia/nemotron-3-super-120b-a12b",
        display_name="Nemotron 3 Super",
        capabilities=["chat", "code", "streaming", "tools"],
        description="Balanced speed and capability for daily coding",
    ),
    CatalogModel(
        id="deepseek-ai/deepseek-v4-flash-0731",
        display_name="DeepSeek V4 Flash",
        capabilities=["chat", "code", "streaming"],
        description="Efficient coding-focused model",
    ),
    CatalogModel(
        id="stealth/ox-alpha",
        display_name="Ox Alpha",
        capabilities=["chat", "code", "streaming", "reasoning"],
        description="Anonymous third-party model. Provider retains request data.",
    ),
]

# Models served by providers other than the default NVIDIA route.
PROVIDER_ROUTES: dict[str, str] = {
    "stealth/ox-alpha": "openrouter",
}

_CATALOG_IDS = frozenset(m.id for m in CATALOG)

DEFAULT_MODEL = "stepfun-ai/step-3.7-flash"


def known_model(model_id: str) -> bool:
    return model_id in _CATALOG_IDS


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

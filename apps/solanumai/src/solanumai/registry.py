"""
@File - registry.py
@Author - MdMunimul.Islam@teagasc.ie
@Created - 28/07/2026

The models SolanumAI offers, as users see them: name, description, status, output range, unit.

What a model IS (its pipeline and its feature lists) is not defined here. It comes from MLflow,
together with the exact version being served (model_catalog.py reads the run's model_schema.json).
So a retrained model with a new feature never disagrees with a list kept by hand, and nothing
here reads files.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ModelEntry:
    key: str
    display_name: str
    description: str
    status: Literal["live", "coming_soon"]
    target_range: tuple[float, float] = (0, 9)
    unit: str = ""
    registered_model: str | None = None  # name in the MLflow registry


REGISTRY = {
    "oa": ModelEntry(
        key="oa",
        display_name="Overall Appearance Score",
        description="Predicts overall appearance (0–9) from trait measurements.",
        status="live",
        target_range=(0, 9),
        unit="/ 9",
        registered_model="oa_xgb_prod",
    ),
}


def verify_schema_alignment(key: str, model_features: set[str], input_model) -> None:
    """The form (schemas.py) must match the features of the model version being served.
    Called by model_catalog.py after loading; a mismatch hides the model instead of
    letting it predict from the wrong inputs."""
    form_features = {f.alias or n for n, f in input_model.model_fields.items()}
    missing = model_features - form_features
    extra = form_features - model_features
    if missing or extra:
        raise RuntimeError(
            f"{key}: form/model mismatch. "
            f"in model not in form: {sorted(missing)}; in form not in model: {sorted(extra)}"
        )

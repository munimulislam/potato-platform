"""
Loads the ML models once at start and keeps them in memory.

Where a model comes from is configuration (Settings.uri_for_model):
- now:   an MLflow-format folder under MODELS_DIR, mounted read-only into the container;
- later: models:/<name>@champion from the MLflow registry. Same code, different URI.
"""

import logging
from dataclasses import dataclass
from typing import Any

import joblib
import pandas as pd

from solanumai import explain
from solanumai.registry import REGISTRY, verify_schema_alignment
from solanumai.schemas import INPUT_SCHEMAS
from solanumai.settings import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    key: str
    entry: Any  # registry entry: name, feature order, numeric/categorical columns, target range
    model: Any  # fitted scikit-learn pipeline


def _load(uri: str) -> Any:
    # A plain joblib file still works, so current models can be used before they're re-saved in MLflow format.
    if uri.endswith((".joblib", ".pkl")):
        return joblib.load(uri)
    import mlflow.sklearn  # imported here: slow to import, and only needed at start

    return mlflow.sklearn.load_model(uri)


def _build_explainer(settings: Settings, lm: LoadedModel) -> None:
    """Explanations are optional: without a background sample the model still predicts."""
    sample_path = settings.models_dir / lm.key / "sample.csv"
    try:
        sample = pd.read_csv(sample_path)
        explain.build_explainer(
            lm.key,
            lm.model,
            lm.entry.feature_order,
            sample,
            numeric_cols=lm.entry.numeric,
        )
    except Exception:
        log.warning(
            "No explainer for %s (sample: %s)", lm.key, sample_path, exc_info=True
        )


def load_live_models(settings: Settings) -> dict[str, LoadedModel]:
    """Load every model marked 'live' in the registry.
    Fails at start if one can't load: a clear start-up error beats a 500 on the first prediction.
    """
    loaded: dict[str, LoadedModel] = {}

    for key, entry in REGISTRY.items():
        if entry.status != "live":
            continue
        if key not in INPUT_SCHEMAS:
            raise RuntimeError(
                f"Model '{key}' is live but has no input schema in schemas.py"
            )

        verify_schema_alignment(entry, INPUT_SCHEMAS[key])

        uri = settings.uri_for_model(key)
        log.info("Loading model %s from %s", key, uri)
        lm = LoadedModel(key=key, entry=entry, model=_load(uri))
        _build_explainer(settings, lm)
        loaded[key] = lm

    return loaded

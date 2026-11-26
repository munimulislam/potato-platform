import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mlflow
import mlflow.sklearn
import pandas as pd
from fastapi import Request
from mlflow import MlflowClient

from solanumai import explain
from solanumai.contracts import ModelStatus
from solanumai.registry import REGISTRY, ModelEntry, verify_schema_alignment
from solanumai.schemas import INPUT_SCHEMAS
from solanumai.settings import Settings

log = logging.getLogger(__name__)

SCHEMA_ARTIFACT = (
    "model_schema.json"  # logged by the training run: target and feature lists
)
SAMPLE_ARTIFACT = (
    "explainer/sample.csv"  # logged by the training run: SHAP background sample
)


@dataclass(frozen=True)
class LoadedModel:
    key: str
    entry: ModelEntry
    model: Any
    version: str  # MLflow model version
    feature_order: list[str]
    numeric: list[str]
    categorical: list[str]


def _live_keys() -> list[str]:
    return [key for key, entry in REGISTRY.items() if entry.status == "live"]


class ModelCatalog:
    def __init__(self, settings: Settings):
        self._settings = settings
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        self._client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
        self._loaded: dict[str, LoadedModel] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()  # requests read while the loader thread writes
        self._stop = threading.Event()

    def get(self, key: str) -> LoadedModel | None:
        with self._lock:
            return self._loaded.get(key)

    def status(self) -> list[ModelStatus]:
        with self._lock:
            return [
                ModelStatus(
                    key=key,
                    loaded=key in self._loaded,
                    version=self._loaded[key].version if key in self._loaded else None,
                    error=self._errors.get(key),
                )
                for key in _live_keys()
            ]

    # ---------- loading (background thread) ----------

    def start(self) -> None:
        threading.Thread(target=self._run, name="model-loader", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            for key in _live_keys():
                if self._stop.is_set():
                    return
                if self.get(key) is None:
                    self._load(key)
            if all(self.get(key) is not None for key in _live_keys()):
                log.info("All live models loaded")
                return
            self._stop.wait(self._settings.model_retry_seconds)

    def _download(self, run_id: str, artifact_path: str) -> Path:
        return Path(
            mlflow.artifacts.download_artifacts(
                run_id=run_id,
                artifact_path=artifact_path,
                tracking_uri=self._settings.mlflow_tracking_uri,
            )
        )

    def _load(self, key: str) -> None:
        entry = REGISTRY[key]
        name = self._settings.registry_name_for(
            key, default=entry.registered_model or key
        )
        alias = self._settings.model_alias

        try:
            if key not in INPUT_SCHEMAS:
                raise RuntimeError("no input schema in schemas.py")

            version = self._client.get_model_version_by_alias(name, alias)
            if not version.run_id:
                raise RuntimeError(
                    "model version has no run: can't read model_schema.json"
                )

            # The feature lists of THIS model version, as logged by its training run
            schema = json.loads(
                self._download(version.run_id, SCHEMA_ARTIFACT).read_text(
                    encoding="utf-8"
                )
            )
            features = schema["features"]

            # Load the exact version the alias pointed to, even if the alias moves meanwhile
            model = mlflow.sklearn.load_model(f"models:/{name}/{version.version}")

            loaded = LoadedModel(
                key=key,
                entry=entry,
                model=model,
                version=str(version.version),
                feature_order=list(features["feature_cols_order"]),
                numeric=list(features["numeric"]),
                categorical=list(features["categorical"]),
            )
            verify_schema_alignment(
                key, set(loaded.numeric) | set(loaded.categorical), INPUT_SCHEMAS[key]
            )
            self._build_explainer(loaded, version.run_id)
        except Exception as e:
            with self._lock:
                self._errors[key] = f"{type(e).__name__}: {e}"
            log.warning(
                "Model %s (%s@%s) not available, retrying in %ss: %s",
                key,
                name,
                alias,
                self._settings.model_retry_seconds,
                e,
            )
            return

        with self._lock:
            self._loaded[key] = loaded
            self._errors.pop(key, None)
        log.info("Model %s loaded: %s v%s", key, name, loaded.version)

    def _build_explainer(self, loaded: LoadedModel, run_id: str) -> None:
        """Optional: a failure here never stops the model from serving predictions."""
        try:
            sample = pd.read_csv(self._download(run_id, SAMPLE_ARTIFACT))
            explain.build_explainer(
                loaded.key,
                loaded.model,
                loaded.feature_order,
                sample,
                numeric_cols=loaded.numeric,
            )
        except Exception:
            log.warning(
                "No explainer for %s v%s", loaded.key, loaded.version, exc_info=True
            )


def get_catalog(request: Request) -> ModelCatalog:
    return request.app.state.catalog

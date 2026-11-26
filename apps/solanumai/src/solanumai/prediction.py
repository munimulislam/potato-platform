"""
Prediction logic, separate from the web layer: plain functions that take data and return results.
Testable without a web server; the routes stay thin.
"""

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd
from potato_core.column_naming import (
    clean_column_name,
)

from solanumai import explain
from solanumai.model_catalog import LoadedModel


class InvalidExcelError(ValueError):
    """The upload is not a readable Excel file."""


class MissingColumnsError(ValueError):
    def __init__(self, columns: list[str]):
        super().__init__(f"Missing required columns: {columns}")
        self.columns = columns


@dataclass(frozen=True)
class SinglePrediction:
    value: float
    n_missing: int
    explanation: dict | None


def build_frame(loaded: LoadedModel, data: dict) -> pd.DataFrame:
    """One-row frame in the model's exact feature order. Empty numeric -> NaN (the pipeline imputes it)."""
    row = {}
    for col in loaded.feature_order:
        value = data.get(col)
        if col in loaded.numeric:
            row[col] = float(value) if value not in (None, "") else np.nan
        else:
            row[col] = value if value not in (None, "") else None
    return pd.DataFrame([row])[loaded.feature_order]


def predict_one(loaded: LoadedModel, data: dict) -> SinglePrediction:
    X = build_frame(loaded, data)
    lo, hi = loaded.entry.target_range
    explanation = None
    if explain.has_explainer(loaded.key):
        explanation = explain.explain_instance(
            loaded.key, X, target_range=loaded.entry.target_range
        )
        value = float(explanation["prediction"])
    else:
        value = float(np.clip(loaded.model.predict(X)[0], lo, hi))
    n_missing = int(sum(1 for col in loaded.numeric if pd.isna(X.iloc[0][col])))
    return SinglePrediction(value=value, n_missing=n_missing, explanation=explanation)


def predict_batch(loaded: LoadedModel, excel_bytes: bytes) -> bytes:
    """Excel in; the same sheet plus a prediction column out."""
    try:
        df = pd.read_excel(io.BytesIO(excel_bytes))
    except Exception as e:
        raise InvalidExcelError(str(e)) from e

    df.columns = [clean_column_name(c) for c in df.columns]

    needed = loaded.numeric + loaded.categorical
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise MissingColumnsError(missing)

    X = df.reindex(columns=loaded.feature_order)
    for col in loaded.numeric:
        X[col] = pd.to_numeric(
            X[col], errors="coerce"
        )  # "n/a" -> NaN instead of a crash

    lo, hi = loaded.entry.target_range
    df["prediction"] = np.round(np.clip(loaded.model.predict(X), lo, hi), 2)
    n_missing = X[loaded.numeric].isna().sum(axis=1)
    total = len(loaded.numeric)
    df["explainability"] = [
        f"coming soon ({total - m}/{total} traits given)" for m in n_missing
    ]
    df["model_version"] = loaded.version

    out = io.BytesIO()
    df.to_excel(out, index=False)
    return out.getvalue()

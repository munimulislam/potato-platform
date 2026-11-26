"""
Prediction logic
"""

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd
from potato_core.column_naming import (
    clean_column_name,
)

from solanumai import explain
from solanumai.model_store import LoadedModel


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


def build_frame(lm: LoadedModel, data: dict) -> pd.DataFrame:
    """One-row frame in the model's exact feature order. Empty numeric -> NaN (the pipeline imputes it)."""
    row = {}

    for col in lm.entry.feature_order:
        value = data.get(col)
        if col in lm.entry.numeric:
            row[col] = float(value) if value not in (None, "") else np.nan
        else:
            row[col] = value if value not in (None, "") else None

    return pd.DataFrame([row])[lm.entry.feature_order]


def predict_one(lm: LoadedModel, data: dict) -> SinglePrediction:
    X = build_frame(lm, data)
    lo, hi = lm.entry.target_range
    explanation = None

    if explain.has_explainer(lm.key):
        explanation = explain.explain_instance(
            lm.key, X, target_range=lm.entry.target_range
        )
        value = float(explanation["prediction"])
    else:
        value = float(np.clip(lm.model.predict(X)[0], lo, hi))

    n_missing = int(sum(1 for col in lm.entry.numeric if pd.isna(X.iloc[0][col])))
    return SinglePrediction(value=value, n_missing=n_missing, explanation=explanation)


def predict_batch(lm: LoadedModel, excel_bytes: bytes) -> bytes:
    """Excel in, the same Excel plus a prediction column out."""
    try:
        df = pd.read_excel(io.BytesIO(excel_bytes))
    except Exception as e:
        raise InvalidExcelError(str(e)) from e

    df.columns = [clean_column_name(c) for c in df.columns]

    needed = lm.entry.numeric + lm.entry.categorical
    missing = [c for c in needed if c not in df.columns]

    if missing:
        raise MissingColumnsError(missing)

    X = df.reindex(columns=lm.entry.feature_order)  #

    for col in lm.entry.numeric:
        X[col] = pd.to_numeric(
            X[col], errors="coerce"
        )  # text such as "n/a" -> NaN instead of a crash

    lo, hi = lm.entry.target_range
    df["prediction"] = np.round(np.clip(lm.model.predict(X), lo, hi), 2)
    n_missing = X[lm.entry.numeric].isna().sum(axis=1)
    total = len(lm.entry.numeric)
    df["explainability"] = [
        f"coming soon ({total - m}/{total} traits given)" for m in n_missing
    ]

    out = io.BytesIO()
    df.to_excel(out, index=False)
    return out.getvalue()

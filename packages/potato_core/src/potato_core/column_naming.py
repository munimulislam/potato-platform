"""Column-name cleaning shared by the pipeline (training data) and SolanumAI (uploads).
One function, so the names a model was trained on always match the names it is given."""

import re

SYMBOL_MAP = {
    ">=": "gte ",
    "<=": "lte ",
    ">": "gt ",
    "<": "lt ",
    "%": "percent ",
    "#": "hash ",
}


def clean_column_name(name: str) -> str:
    c = str(name).strip().lower()
    c = re.sub(r"\s+", " ", c)

    for symbol, text in SYMBOL_MAP.items():
        c = c.replace(symbol, text)

    c = re.sub(r"[^a-z0-9]+", "_", c)
    c = c.strip("_")

    if not c:
        return "val"
    if not c[0].isalpha():
        return f"val_{c}"
    return c

"""Prediction endpoints"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from solanumai import explain
from solanumai.auth import require_login
from solanumai.model_catalog import LoadedModel, ModelCatalog, get_catalog
from solanumai.prediction import (
    InvalidExcelError,
    MissingColumnsError,
    predict_batch,
    predict_one,
)
from solanumai.schemas import INPUT_SCHEMAS
from solanumai.settings import get_settings
from solanumai.store import PredictionStore, get_prediction_store
from solanumai.templating import templates
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["predict"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _loaded(catalog: ModelCatalog, model_key: str) -> LoadedModel:
    loaded = catalog.get(model_key)
    if loaded is None:
        raise HTTPException(404, "This model is not available right now")
    return loaded


@router.post("/model/{model_key}/predict", response_class=HTMLResponse)
async def predict(
    request: Request,
    model_key: str,
    user: dict = Depends(require_login),
    catalog: ModelCatalog = Depends(get_catalog),
    predictions: PredictionStore = Depends(get_prediction_store),
):
    loaded = _loaded(catalog, model_key)
    form = await request.form()
    raw = {k: (v if v != "" else None) for k, v in form.items()}

    # Validate through the model's Pydantic schema: clear field errors instead of crashes.
    try:
        model_in = INPUT_SCHEMAS[model_key](**raw)
    except ValidationError as e:
        errors = [
            f"{'.'.join(str(x) for x in err['loc']) or 'form'}: {err['msg']}"
            for err in e.errors()
        ]
        return templates.TemplateResponse(
            request, "_result.html", {"model": loaded.entry, "errors": errors}
        )

    data = model_in.model_dump(by_alias=True)

    result = await run_in_threadpool(predict_one, loaded, data)
    pred_id = await run_in_threadpool(
        predictions.save_prediction,
        model_key,
        loaded.version,
        user["id"],
        data,
        result.value,
        result.n_missing,
    )

    expl = result.explanation

    return templates.TemplateResponse(
        request,
        "_result.html",
        {
            "model": loaded.entry,
            "score": round(result.value, 2),
            "n_missing": result.n_missing,
            "pred_id": pred_id,
            "explain_text": expl["text"] if expl else None,
            "explain_svg": explain.svg_bars(expl["bars"]) if expl else None,
        },
    )


@router.post("/model/{model_key}/predict-excel")
async def predict_excel(
    model_key: str,
    file: UploadFile = File(...),
    catalog: ModelCatalog = Depends(get_catalog),
):
    loaded = _loaded(catalog, model_key)

    max_mb = get_settings().max_upload_mb
    content = await file.read(max_mb * 1024 * 1024 + 1)

    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {max_mb} MB)")

    try:
        result = await run_in_threadpool(predict_batch, loaded, content)
    except InvalidExcelError:
        raise HTTPException(
            400, "Could not read the file. Please upload an .xlsx Excel file."
        ) from None
    except MissingColumnsError as e:
        raise HTTPException(
            400, f"The file is missing required columns: {', '.join(e.columns)}"
        ) from None

    return Response(
        content=result,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="predictions_{model_key}_v{loaded.version}.xlsx"'
        },
    )


@router.post("/feedback/{pred_id}/{value}", response_class=HTMLResponse)
def feedback(
    pred_id: UUID,
    value: Literal["like", "dislike"],
    predictions: PredictionStore = Depends(get_prediction_store),
):
    if not predictions.save_feedback(pred_id, value):
        raise HTTPException(404, "Prediction not found")
    return HTMLResponse('<span class="muted text-sm">Thanks for your feedback.</span>')

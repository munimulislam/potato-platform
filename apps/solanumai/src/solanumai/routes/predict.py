"""Prediction endpoints"""

from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from solanumai import explain, store
from solanumai.model_store import LoadedModel
from solanumai.prediction import (
    InvalidExcelError,
    MissingColumnsError,
    predict_batch,
    predict_one,
)
from solanumai.schemas import INPUT_SCHEMAS
from solanumai.settings import get_settings
from solanumai.templating import templates
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["predict"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _loaded(request: Request, model_key: str) -> LoadedModel:
    lm = request.app.state.models.get(model_key)
    if lm is None:
        raise HTTPException(404, "Unknown or unavailable model")
    return lm


@router.post("/model/{model_key}/predict", response_class=HTMLResponse)
async def predict(request: Request, model_key: str):
    lm = _loaded(request, model_key)
    form = await request.form()
    raw = {k: (v if v != "" else None) for k, v in form.items()}

    try:
        model_in = INPUT_SCHEMAS[model_key](**raw)
    except ValidationError as e:
        errors = [
            f"{'.'.join(str(x) for x in err['loc']) or 'form'}: {err['msg']}"
            for err in e.errors()
        ]
        return templates.TemplateResponse(
            request, "_result.html", {"model": lm.entry, "errors": errors}
        )

    data = model_in.model_dump(by_alias=True)

    result = await run_in_threadpool(predict_one, lm, data)
    pred_id = await run_in_threadpool(
        store.log_prediction, model_key, data, result.value, result.n_missing
    )

    expl = result.explanation
    return templates.TemplateResponse(
        request,
        "_result.html",
        {
            "model": lm.entry,
            "score": round(result.value, 2),
            "n_missing": result.n_missing,
            "pred_id": pred_id,
            "explain_text": expl["text"] if expl else None,
            "explain_svg": explain.svg_bars(expl["bars"]) if expl else None,
        },
    )


@router.post("/model/{model_key}/predict-excel")
async def predict_excel(request: Request, model_key: str, file: UploadFile = File(...)):
    lm = _loaded(request, model_key)

    limit = get_settings().max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)

    if len(content) > limit:
        raise HTTPException(
            413, f"File too large (max {get_settings().max_upload_mb} MB)"
        )

    try:
        result = await run_in_threadpool(predict_batch, lm, content)
    except InvalidExcelError:
        raise HTTPException(
            400, "Could not read the file. Please upload an .xlsx Excel file."
        ) from None
    except MissingColumnsError as e:
        raise HTTPException(
            400, f"Uploaded file is missing required columns: {e.columns}"
        ) from None

    return Response(
        content=result,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="predictions_{model_key}.xlsx"'
        },
    )


@router.post("/feedback/{pred_id}/{value}", response_class=HTMLResponse)
def feedback(pred_id: str, value: Literal["like", "dislike"]):  # any other value -> 422
    store.set_feedback(pred_id, value)
    icon = "👍" if value == "like" else "👎"
    return HTMLResponse(
        f'<span class="text-success font-semibold">{icon} Thank you for your feedback</span>'
    )

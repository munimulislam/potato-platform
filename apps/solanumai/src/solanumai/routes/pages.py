"""Full HTML pages."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from solanumai import store
from solanumai.auth import require_login
from solanumai.registry import REGISTRY
from solanumai.schemas import INPUT_SCHEMAS, form_fields
from solanumai.templating import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: dict = Depends(require_login)):
    return templates.TemplateResponse(
        request, "home.html", {"models": list(REGISTRY.values()), "user": user}
    )


@router.get("/model/{model_key}", response_class=HTMLResponse)
def model_page(
    request: Request,
    model_key: str,
    tab: Literal["predict", "performance"] = "predict",  # anything else -> 422
    user: dict = Depends(require_login),
):
    entry = REGISTRY.get(model_key)

    if entry is None:
        raise HTTPException(404, "Unknown model")
    if entry.status == "coming_soon":
        return templates.TemplateResponse(
            request, "coming_soon.html", {"model": entry, "user": user}
        )

    ctx = {
        "model": entry,
        "tab": tab,
        "fields": form_fields(INPUT_SCHEMAS[model_key]),
        "user": user,
    }

    if tab == "performance":
        ctx["stats"] = store.monitoring(model_key)
        ctx["history"] = store.recent(model_key, limit=25)

    return templates.TemplateResponse(request, "model_page.html", ctx)

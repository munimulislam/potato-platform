"""Full HTML pages."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from solanumai.auth import require_login
from solanumai.model_catalog import ModelCatalog, get_catalog
from solanumai.registry import REGISTRY
from solanumai.schemas import INPUT_SCHEMAS, form_fields
from solanumai.store import PredictionStore, get_prediction_store
from solanumai.templating import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: dict = Depends(require_login),
    catalog: ModelCatalog = Depends(get_catalog),
):
    cards = []
    for key, entry in REGISTRY.items():
        loaded = catalog.get(key)
        if loaded is not None:
            cards.append(
                {
                    "key": key,
                    "entry": entry,
                    "available": True,
                    "version": loaded.version,
                }
            )
        elif entry.status == "coming_soon":
            cards.append(
                {"key": key, "entry": entry, "available": False, "version": None}
            )
        # a live model that isn't loaded is hidden until it loads
    return templates.TemplateResponse(
        request, "home.html", {"user": user, "cards": cards, "active": "models"}
    )


@router.get("/model/{model_key}", response_class=HTMLResponse)
def model_page(
    request: Request,
    model_key: str,
    tab: Literal["predict", "performance"] = "predict",
    user: dict = Depends(require_login),
    catalog: ModelCatalog = Depends(get_catalog),
    predictions: PredictionStore = Depends(get_prediction_store),
):
    entry = REGISTRY.get(model_key)
    if entry is None:
        raise HTTPException(404, "Unknown model")
    if entry.status == "coming_soon":
        return templates.TemplateResponse(
            request,
            "coming_soon.html",
            {"user": user, "model": entry, "active": "models"},
        )

    loaded = catalog.get(model_key)
    if loaded is None:
        raise HTTPException(404, "This model is not available right now")

    ctx = {
        "user": user,
        "active": "models",
        "key": model_key,
        "model": entry,
        "version": loaded.version,
        "lm_numeric": loaded.numeric,  # the served version's features (for the Excel hint)
        "lm_categorical": loaded.categorical,
        "tab": tab,
        "fields": form_fields(INPUT_SCHEMAS[model_key]),
    }
    if tab == "performance":
        ctx["stats"] = predictions.monitoring(model_key)
        ctx["history"] = predictions.recent(model_key, limit=25)
    return templates.TemplateResponse(request, "model_page.html", ctx)


@router.get("/explorer", response_class=HTMLResponse)
def explorer_page(request: Request, user: dict = Depends(require_login)):
    return templates.TemplateResponse(
        request, "explorer.html", {"user": user, "active": "explorer"}
    )


@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, user: dict = Depends(require_login)):
    return templates.TemplateResponse(
        request, "chat.html", {"user": user, "active": "chat"}
    )

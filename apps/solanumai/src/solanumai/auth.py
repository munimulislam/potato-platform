"""
Login for SolanumAI.

Two modes (AUTH_MODE):
- password: one shared password from a secrets file. For local use and the handover only.
- entra:    Microsoft sign-in (Entra ID, OpenID Connect), the target for Teagasc.
            Needs an app registration from Teagasc IT (tenant ID, client ID, client secret,
            redirect URI .../auth/callback, "assignment required" = yes).

The signed-in user is kept in a signed session cookie (SessionMiddleware, see main.py).
"""

import logging
import secrets

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from solanumai.settings import Settings, get_settings
from solanumai.templating import templates

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])
oauth = OAuth()


class NotAuthenticated(Exception):
    """Raised by require_login; not_authenticated_handler turns it into the right response."""


def configure_auth(settings: Settings) -> None:
    """Register the Entra ID client once at start (entra mode only)."""
    if settings.auth_mode != "entra":
        return

    oauth.register(
        name="entra",
        # Tenant-specific metadata: only accounts of this tenant (Teagasc) can sign in,
        # and the token's issuer is checked against it.
        server_metadata_url=(
            f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0/.well-known/openid-configuration"
        ),
        client_id=settings.entra_client_id,
        client_secret=settings.entra_client_secret.get_secret_value(),
        client_kwargs={"scope": "openid profile email"},
    )


def require_login(request: Request) -> dict:
    """Returns the current signed-in user."""
    user = request.session.get("user")

    if not user:
        raise NotAuthenticated()

    return user


async def not_authenticated_handler(
    request: Request, exc: NotAuthenticated
) -> Response:
    if request.headers.get("HX-Request") == "true":
        # Redirects HTMX to /login.
        return Response(status_code=401, headers={"HX-Redirect": "/login"})

    if request.url.path.startswith("/api/"):
        #  JSON response for API endpoints.
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    return RedirectResponse("/login", status_code=303)


def _start_session(request: Request, user: dict) -> None:
    # A fresh session on every login: nothing from before the login carries over (session fixation).
    request.session.clear()
    request.session["user"] = user


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_with_password(request: Request):
    settings = get_settings()

    if settings.auth_mode != "password":
        raise HTTPException(404)

    form = await request.form()
    username = str(form.get("username") or "").strip()[:64] or "guest"
    password = str(form.get("password") or "")
    expected = settings.app_login_password.get_secret_value()

    if secrets.compare_digest(password.encode(), expected.encode()):
        # The username is only a display label: in password mode everyone shares one password.
        _start_session(request, {"name": username, "email": None, "method": "password"})
        return RedirectResponse("/", status_code=303)

    log.warning("Failed password login (username=%r)", username)

    return templates.TemplateResponse(
        request, "login.html", {"error": "Wrong password"}, status_code=401
    )


@router.get("/auth/entra")
async def login_with_entra(request: Request):
    if get_settings().auth_mode != "entra":
        raise HTTPException(404)
    # This URL must match the redirect URI registered in Entra exactly (scheme, host, port, path).
    # Behind a reverse proxy, run uvicorn with --proxy-headers so it builds the https URL.
    redirect_uri = str(request.url_for("auth_callback"))
    return await oauth.entra.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    if get_settings().auth_mode != "entra":
        raise HTTPException(404)
    try:
        # Exchanges the code for tokens and validates the ID token (signature, issuer, audience).
        token = await oauth.entra.authorize_access_token(request)
    except OAuthError as e:
        log.warning("Entra sign-in failed: %s", e.error)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Microsoft sign-in failed. Please try again."},
            status_code=401,
        )

    info = token.get("userinfo") or {}

    _start_session(
        request,
        {
            "name": info.get("name"),
            "email": info.get("preferred_username"),
            "oid": info.get(
                "oid"
            ),  # stable Entra user ID: use this, not the email, as a key
            "method": "entra",
        },
    )

    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    # Ends the SolanumAI session only. The Microsoft session stays, so signing in again is one click.
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

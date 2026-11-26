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
    if not settings.microsoft_enabled:
        return

    oauth.register(
        name="microsoft",
        server_metadata_url=f"https://login.microsoftonline.com/{settings.ms_tenant}/v2.0/.well-known/openid-configuration",
        client_id=settings.ms_client_id,
        client_secret=settings.ms_client_secret.get_secret_value(),
        client_kwargs={"scope": "openid profile email"},
    )


def require_login(request: Request) -> dict:
    """Dependency for every protected route. Returns the signed-in user."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


async def not_authenticated_handler(
    request: Request, exc: NotAuthenticated
) -> Response:
    # HTMX swaps responses into part of the page; HX-Redirect makes it load /login as a full page.
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    # API clients (explorer, chat) get JSON; their JavaScript sends the browser to /login.
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def _start_session(request: Request, user: dict) -> None:
    # A fresh session on every sign-in: nothing from before carries over (session fixation).
    request.session.clear()
    request.session["user"] = user


def _login_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request, "login.html", {"error": error}, status_code=status_code
    )


@router.get("/login")
def login_page(request: Request):
    return _login_page(request)


@router.post("/login")
async def login_with_password(request: Request):
    settings = get_settings()
    if not settings.auth_password_enabled:
        raise HTTPException(404)

    form = await request.form()
    username = str(form.get("username") or "").strip()[:64] or "guest"
    password = str(form.get("password") or "")
    expected = settings.app_login_password.get_secret_value()

    # compare_digest takes the same time wherever the first wrong character is:
    # the password can't be guessed from response times.
    if secrets.compare_digest(password.encode(), expected.encode()):
        # Display label only: in password mode everyone shares one password.
        _start_session(
            request,
            {
                "id": f"password:{username.lower()}",
                "name": username,
                "email": None,
                "provider": "password",
            },
        )
        return RedirectResponse("/", status_code=303)

    log.warning("Failed password sign-in (username=%r)", username)
    return _login_page(request, "Wrong password.", status_code=401)


@router.get("/auth/microsoft")
async def login_with_microsoft(request: Request):
    if not get_settings().microsoft_enabled:
        raise HTTPException(404)
    # Must match the redirect URI in the app registration exactly (scheme, host, port, path).
    # Behind a reverse proxy, run uvicorn with --proxy-headers so this becomes https.
    redirect_uri = str(request.url_for("microsoft_callback"))
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@router.get("/auth/microsoft/callback", name="microsoft_callback")
async def microsoft_callback(request: Request):
    settings = get_settings()
    if not settings.microsoft_enabled:
        raise HTTPException(404)
    try:
        token = await oauth.microsoft.authorize_access_token(
            request
        )  # validates the ID token
    except OAuthError as e:
        log.warning("Microsoft sign-in failed: %s", e.error)
        return _login_page(
            request, "Microsoft sign-in failed. Please try again.", status_code=401
        )

    info = token.get("userinfo") or {}
    email = str(info.get("email") or info.get("preferred_username") or "").lower()

    allowed = settings.allowed_email_set
    if allowed and email not in allowed:
        log.warning("Microsoft sign-in refused for %s (not in ALLOWED_EMAILS)", email)
        return _login_page(
            request, "This account doesn't have access to SolanumAI.", status_code=403
        )

    # oid: stable user ID across apps; sub: stable for this app. Never use the email as the key.
    stable_id = info.get("oid") or info["sub"]
    _start_session(
        request,
        {
            "id": f"microsoft:{stable_id}",
            "name": info.get("name") or email,
            "email": email,
            "provider": "microsoft",
        },
    )
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    # Ends the SolanumAI session. The Microsoft session stays, so signing in again is one click.
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

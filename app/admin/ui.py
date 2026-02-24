import hashlib
import hmac
import yaml
import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from app.core.config import settings
from app.admin.session import (
    create_admin_session,
    require_admin_session,
    session_cookie,
    session_backend,
    get_session_id,
)
from app.services.auth.login_rate_limit import (
    check_login_rate_limit,
    get_client_ip,
    reset_login_attempts,
)


router = APIRouter(prefix="/admin-ui", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/admin/templates")


async def require_login(request: Request) -> RedirectResponse | None:
    session = await require_admin_session(request)
    if not session:
        return RedirectResponse(url="/admin-ui/login", status_code=303)
    return None


def _api_headers() -> dict:
    headers = {}
    if settings.admin_api_key:
        headers["X-Admin-Key"] = settings.admin_api_key
    return headers


def _api_url(path: str) -> str:
    return f"{settings.admin_ui_api_base}{path}"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    client_ip = get_client_ip(request)
    if not check_login_rate_limit(client_ip):
        return RedirectResponse(url="/admin-ui/login?error=rate_limit", status_code=303)

    password_ok = False
    hash_sha = settings.admin_ui_password_hash_sha256 or settings.admin_ui_password_hash
    if hash_sha:
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        password_ok = hmac.compare_digest(digest, hash_sha)
    else:
        password_ok = hmac.compare_digest(password, settings.admin_ui_password)

    if username == settings.admin_ui_username and password_ok:
        reset_login_attempts(client_ip)
        session_id = await create_admin_session(username)
        response = RedirectResponse(url="/admin-ui", status_code=303)
        session_cookie.attach_to_response(response, session_id)
        return response
    return RedirectResponse(url="/admin-ui/login?error=1", status_code=303)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    session_id = await get_session_id(request)
    if session_id:
        await session_backend.delete(session_id)
    response = RedirectResponse(url="/admin-ui/login", status_code=303)
    session_cookie.delete_from_response(response)
    return response


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/cleanup", response_class=HTMLResponse)
async def cleanup_page(request: Request) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("cleanup.html", {"request": request})


@router.get("/telemetry", response_class=HTMLResponse)
async def telemetry_page(request: Request) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    window_hours = int(request.query_params.get("window_hours", 24))
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(
            _api_url(f"/admin/telemetry?window_hours={window_hours}"),
            headers=_api_headers()
        )
        data = resp.json() if resp.status_code < 300 else {}
    return templates.TemplateResponse(
        "telemetry.html",
        {"request": request, "data": data, "admin_api_key": settings.admin_api_key or ""}
    )


@router.post("/cleanup")
async def run_cleanup(request: Request, older_than_hours: int = Form(...)) -> RedirectResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout_long) as client:
        await client.post(
            _api_url("/admin/cleanup"),
            headers=_api_headers(),
            params={"older_than_hours": older_than_hours},
        )
    return RedirectResponse(url="/admin-ui/cleanup?ok=1", status_code=303)


@router.get("/prompts", response_class=HTMLResponse)
async def list_prompts(request: Request) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url("/admin/prompts"), headers=_api_headers())
        prompts = resp.json() if resp.status_code < 300 else []
    return templates.TemplateResponse(
        "prompts_list.html",
        {"request": request, "prompts": prompts, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/prompts/{name}", response_class=HTMLResponse)
async def edit_prompt(request: Request, name: str) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url(f"/admin/prompts/{name}"), headers=_api_headers())
        prompt = resp.json() if resp.status_code < 300 else {"name": name}
    raw_yaml = yaml.safe_dump(prompt, allow_unicode=True, sort_keys=False)
    return templates.TemplateResponse(
        "prompt_edit.html",
        {"request": request, "name": name, "raw_yaml": raw_yaml, "admin_api_key": settings.admin_api_key or ""}
    )


@router.post("/prompts/{name}")
async def update_prompt(request: Request, name: str, raw_yaml: str = Form(...)) -> RedirectResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    payload = yaml.safe_load(raw_yaml) or {}
    payload.pop("name", None)
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        await client.put(
            _api_url(f"/admin/prompts/{name}"),
            headers=_api_headers(),
            json=payload,
        )
    return RedirectResponse(url=f"/admin-ui/prompts/{name}", status_code=303)


@router.get("/trend-prompts", response_class=HTMLResponse)
async def list_trend_prompts(request: Request) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url("/admin/trend-prompts"), headers=_api_headers())
        prompts = resp.json() if resp.status_code < 300 else []
    return templates.TemplateResponse(
        "trend_prompts_list.html",
        {"request": request, "prompts": prompts, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/trend-prompts/{trend_id}", response_class=HTMLResponse)
async def edit_trend_prompt(request: Request, trend_id: str) -> HTMLResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url(f"/admin/trend-prompts/{trend_id}"), headers=_api_headers())
        prompt = resp.json() if resp.status_code < 300 else {"name": trend_id}
    raw_yaml = yaml.safe_dump(prompt, allow_unicode=True, sort_keys=False)
    return templates.TemplateResponse(
        "prompt_edit.html",
        {"request": request, "name": trend_id, "raw_yaml": raw_yaml, "admin_api_key": settings.admin_api_key or ""}
    )


@router.post("/trend-prompts/{trend_id}")
async def update_trend_prompt(request: Request, trend_id: str, raw_yaml: str = Form(...)) -> RedirectResponse:
    redirect = await require_login(request)
    if redirect:
        return redirect
    payload = yaml.safe_load(raw_yaml) or {}
    payload.pop("name", None)
    payload.pop("trend_id", None)
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        await client.put(
            _api_url(f"/admin/trend-prompts/{trend_id}"),
            headers=_api_headers(),
            json=payload,
        )
    return RedirectResponse(url=f"/admin-ui/trend-prompts/{trend_id}", status_code=303)


@router.get("/trends", response_class=HTMLResponse)
async def trends_list(request: Request) -> HTMLResponse:
    """List all trends."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "trends_list.html",
        {"request": request, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/trends/new", response_class=HTMLResponse)
async def trend_new(request: Request) -> HTMLResponse:
    """Create new trend page."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "trend_edit.html",
        {"request": request, "trend": None, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/trends/{trend_id}", response_class=HTMLResponse)
async def trend_edit(request: Request, trend_id: str) -> HTMLResponse:
    """Edit trend page."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url(f"/admin/trends/{trend_id}"), headers=_api_headers())
        if resp.status_code >= 300:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Тренд не найден"},
                status_code=404
            )
        trend = resp.json()
    return templates.TemplateResponse(
        "trend_edit.html",
        {"request": request, "trend": trend, "admin_api_key": settings.admin_api_key or ""}
    )


@router.post("/trends/{trend_id}")
async def trend_update_post(request: Request, trend_id: str) -> RedirectResponse:
    """Update trend via form POST."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    # This is handled by JavaScript in the template
    return RedirectResponse(url=f"/admin-ui/trends/{trend_id}", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request) -> HTMLResponse:
    """List all users."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "users_list.html",
        {"request": request, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/users/{telegram_id}", response_class=HTMLResponse)
async def user_detail(request: Request, telegram_id: str) -> HTMLResponse:
    """User detail page."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url(f"/admin/users/{telegram_id}"), headers=_api_headers())
        user = resp.json() if resp.status_code < 300 else None
        if not user:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Пользователь не найден"},
                status_code=404
            )
    return templates.TemplateResponse(
        "user_detail.html",
        {"request": request, "user": user, "admin_api_key": settings.admin_api_key or ""}
    )


@router.post("/users/{telegram_id}")
async def update_user_post(request: Request, telegram_id: str) -> RedirectResponse:
    """Update user via form POST."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    form = await request.form()
    payload = {
        "token_balance": int(form.get("token_balance", 0)),
        "subscription_active": form.get("subscription_active") == "true",
    }
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        await client.put(
            _api_url(f"/admin/users/{telegram_id}"),
            headers=_api_headers(),
            json=payload,
        )
    return RedirectResponse(url=f"/admin-ui/users/{telegram_id}?updated=1", status_code=303)


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request) -> HTMLResponse:
    """List all jobs."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "jobs_list.html",
        {"request": request, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str) -> HTMLResponse:
    """Job detail page."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    async with httpx.AsyncClient(timeout=settings.http_client_timeout) as client:
        resp = await client.get(_api_url(f"/admin/jobs/{job_id}"), headers=_api_headers())
        job = resp.json() if resp.status_code < 300 else None
        if not job:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Задача не найдена"},
                status_code=404
            )
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job, "admin_api_key": settings.admin_api_key or ""}
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit_list(request: Request) -> HTMLResponse:
    """List audit logs."""
    redirect = await require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "audit_list.html",
        {"request": request, "admin_api_key": settings.admin_api_key or ""}
    )

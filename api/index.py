"""FastAPI application for the portfolio, admin, inquiry inbox, and content APIs."""

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from lib.admin_backend import MAX_BODY_BYTES, handle_admin_request, handle_inquiry_request
from lib.platform_backend import handle_platform_request

app = FastAPI(title="Blessson Studio API", docs_url=None, redoc_url=None, openapi_url=None)


def _as_response(result):
    status, headers, content = result
    response = Response(content=content, status_code=status)
    for name, value in headers:
        response.headers.append(name, value)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store, max-age=0")
    return response


@app.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@app.api_route("/api/{api_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def api_router(request: Request, api_path: str = ""):
    content_length = request.headers.get("content-length", "0")
    try:
        too_large = int(content_length) > MAX_BODY_BYTES
    except ValueError:
        too_large = True
    if too_large:
        return Response('{"error":"Request is too large."}', status_code=413, media_type="application/json", headers={"Cache-Control": "no-store"})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response('{"error":"Request is too large."}', status_code=413, media_type="application/json", headers={"Cache-Control": "no-store"})

    path = request.url.path
    headers = request.headers
    production = bool(__import__("os").environ.get("VERCEL"))
    if path == "/api/admin":
        result = await run_in_threadpool(handle_admin_request, request.method, request.url.path + ("?" + request.url.query if request.url.query else ""), headers, body, production)
    elif path == "/api/inquiries":
        result = await run_in_threadpool(handle_inquiry_request, request.method, path, headers, body, production)
    else:
        result = await run_in_threadpool(handle_platform_request, request.method, request.url.path + ("?" + request.url.query if request.url.query else ""), headers, body, production)
    return _as_response(result)

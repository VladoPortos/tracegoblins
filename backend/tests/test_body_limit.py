import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.security.body_limit import RequestBodyLimitMiddleware


def _limited_app() -> FastAPI:
    app = FastAPI()

    @app.post("/ordinary")
    async def ordinary(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/runs")
    async def runs(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/projects/{project_id}/uploads")
    async def project_upload(project_id: str, request: Request):
        return {"project_id": project_id, "size": len(await request.body())}

    app.add_middleware(
        RequestBodyLimitMiddleware,
        default_max_bytes=8,
        run_max_bytes=16,
        project_upload_max_bytes=24,
    )
    return app


@pytest.mark.parametrize("size", [9, 64])
async def test_default_request_body_limit_rejects_content_length(size):
    async with AsyncClient(
        transport=ASGITransport(app=_limited_app()), base_url="http://test"
    ) as client:
        response = await client.post("/ordinary", content=b"x" * size)

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


async def test_request_body_limit_counts_streamed_chunks_without_content_length():
    async def chunks():
        yield b"12345"
        yield b"67890"

    async with AsyncClient(
        transport=ASGITransport(app=_limited_app()), base_url="http://test"
    ) as client:
        response = await client.post("/ordinary", content=chunks())

    assert response.status_code == 413


async def test_upload_routes_receive_only_their_explicit_larger_limits():
    async with AsyncClient(
        transport=ASGITransport(app=_limited_app()), base_url="http://test"
    ) as client:
        ordinary = await client.post("/ordinary", content=b"x" * 12)
        run = await client.post("/api/runs", content=b"x" * 12)
        project = await client.post(
            "/api/projects/00000000-0000-0000-0000-000000000000/uploads",
            content=b"x" * 20,
        )

    assert ordinary.status_code == 413
    assert run.status_code == 200
    assert project.status_code == 200

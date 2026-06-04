import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, static_dir: str) -> None:
    """Serve the built Vite SPA. Call AFTER all API routers are registered.

    No-ops if the build dir / index.html is absent (e.g. backend unit tests).
    """
    dist = Path(static_dir)
    index_file = dist / "index.html"
    if not index_file.is_file():
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Real, canonical root of the SPA build. All served files must live under it.
    root = dist.resolve(strict=True)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        if full_path.startswith("api/") or full_path == "openapi.json":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Resolve the user-supplied path and confirm it is contained within the
        # SPA root before serving it. os.path.commonpath() rejects any "../"
        # traversal (and prefix tricks like "<root>-evil") that escape the dir;
        # anything outside falls through to the SPA's index.html.
        candidate = (root / full_path).resolve()
        try:
            contained = os.path.commonpath([root, candidate]) == str(root)
        except ValueError:
            contained = False  # different drive / mixed abs+rel -> not contained
        if contained and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)

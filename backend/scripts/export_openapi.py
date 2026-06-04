"""Dump the FastAPI OpenAPI schema to ../frontend/openapi.json for the SPA's typed client."""
import json
import pathlib

from app.main import app

out = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")

import subprocess
import sys


def test_signature_imports_no_db_or_web():
    # Import the normalizer in a FRESH interpreter (no conftest pre-loading sqlalchemy/
    # fastapi/app.models) and assert none of the forbidden modules got pulled in.
    # An in-process delta-of-sys.modules check would miss a forbidden import that
    # conftest already loaded, so we isolate in a subprocess. (Same pattern as the
    # M2 logparser purity test: backend/tests/logparser/test_purity.py.)
    code = (
        "import sys\n"
        "import app.kb.signature\n"
        "forbidden = {'sqlalchemy', 'fastapi', 'starlette', 'asyncpg', "
        "'app.db', 'app.models'}\n"
        "leaked = sorted(forbidden & set(sys.modules))\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, (
        f"app.kb.signature must stay pure; leaked: {result.stdout.strip()}\n{result.stderr}"
    )

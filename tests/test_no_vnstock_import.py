"""Không phụ thuộc vnstock khi chạy workflow (vnstocks.com ngừng phát hành 4.x
từ 10/11/2026; requirements.txt không còn vnstock).

Chạy trong tiến trình con có `sys.modules['vnstock'] = None` để mọi
`import vnstock...` ném ImportError, giống môi trường CI cài từ requirements."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_BLOCK = (
    "import sys\n"
    "for m in ('vnstock', 'vnai'):\n"
    "    sys.modules[m] = None\n"
)


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _BLOCK + code], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def test_entrypoint_import_duoc_khi_khong_co_vnstock():
    r = _run("import build_warehouse, alert_events, backfill\n"
             "from src import ingest, ingest_market, warehouse\n")
    assert r.returncode == 0, r.stderr[-2000:]


def test_requirements_khong_con_vnstock():
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().splitlines()
    req = "\n".join(ln for ln in lines if not ln.strip().startswith("#"))
    assert "vnstock" not in req
    assert "vnstocks.com" not in req
    assert "openpyxl" in req

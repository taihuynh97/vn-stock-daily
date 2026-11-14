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


# Script chẩn đoán/thăm dò một lần còn gọi vnstock trực tiếp — chuyển hoặc xoá
# ở PR 3 (Task 9). Không workflow định kỳ nào chạy chúng.
_CHUA_CHUYEN = {"scripts/diagnose_api.py", "scripts/probe_news_id_stability.py",
                "scripts/probe_event_id_stability.py", "scripts/probe_statement_row_stability.py"}


def test_import_vnstock_trong_ham_deu_duoc_boc_try():
    """Import vnstock nằm TRONG hàm (vd `if key: from vnstock import vnai`) mà
    không bọc try/except ImportError sẽ làm sập job khi chạy tới — test
    import-cấp-module ở trên không bắt được (reconcile_warehouse, job monthly)."""
    files = [*ROOT.glob("*.py"), *ROOT.glob("src/**/*.py"), *ROOT.glob("scripts/**/*.py"),
             *ROOT.glob("mcp_server/**/*.py")]
    bad = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if rel in _CHUA_CHUYEN:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith(("from vnstock", "import vnstock")):
                before = [ln.strip() for ln in lines[max(0, i - 3):i]]
                if not any(b.startswith("try:") for b in before):
                    bad.append(f"{rel}:{i + 1}: {s}")
    assert not bad, "import vnstock không bọc try/except ImportError:\n" + "\n".join(bad)


def test_requirements_khong_con_vnstock():
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().splitlines()
    req = "\n".join(ln for ln in lines if not ln.strip().startswith("#"))
    assert "vnstock" not in req
    assert "vnstocks.com" not in req
    assert "openpyxl" in req

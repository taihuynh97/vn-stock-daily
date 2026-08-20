# C2 — Cảnh báo theo sự kiện Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Script `alert_events.py` chạy hằng ngày, gửi Telegram khi có sự kiện DN mới cho 5 mã trong `config/portfolio.yml`, không gửi lặp, không đụng hệ thống bot cũ.

**Architecture:** 1 bảng warehouse mới (`alert_sent_log`, chống lặp tin) + 1 script độc lập (đọc `stg_corporate_event` đã có từ B1, so với log, gửi qua `notify.send` có sẵn) + 1 workflow GitHub Actions mới. Không ingest mới, không đụng `main.py`/`digest.py`/`daily.yml`.

**Tech Stack:** Python 3.12 · DuckDB/MotherDuck · PyYAML · pytest

**Spec:** `docs/superpowers/specs/2026-08-19-c2-canh-bao-su-kien-design.md`

## Global Constraints

- **KHÔNG sửa `daily.yml`, `main.py`, `digest.py`, `signals.py`, `screener.py`, `storage.py`** — C2 xây dựng SONG SONG, không đụng hệ thống bot cũ.
- **KHÔNG dùng SQLite cục bộ (`storage.py`/`data/market.db`)** cho chống lặp tin — dùng bảng mới trên MotherDuck (`alert_sent_log`).
- **KHÔNG gọi LLM** — tin sự kiện DN là dữ kiện ngắn, không cần AI tổng hợp.
- **KHÔNG lọc theo `distribution_type`** — báo tất cả sự kiện của 5 mã portfolio.
- **Không nêu khuyến nghị mua/bán** trong nội dung tin nhắn.
- Toàn bộ docstring, comment, commit message viết bằng tiếng Việt.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`.
- Branch làm việc: `feat/c2-canh-bao-su-kien` (đã tạo từ `main`, đã có commit spec).
- Test KHÔNG được gọi Telegram thật — luôn mock `notify.send`.
- Nghiệm thu cuối chạy trên MotherDuck production thật (`WAREHOUSE_DB=md:vn_market`).

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/warehouse.py` | **Sửa.** DDL `alert_sent_log` + hàm `mark_events_alerted` | 1 |
| `alert_events.py` | **Mới.** Script chính: đọc portfolio, kiểm sự kiện mới, seed/gửi | 1 |
| `tests/test_warehouse_alerts.py` | **Mới.** Test DDL + `mark_events_alerted` | 1 |
| `tests/test_alert_events.py` | **Mới.** Test logic seed/gửi/dedup của `alert_events.py` | 1 |
| `.github/workflows/event-alerts.yml` | **Mới.** Workflow chạy hằng ngày | 2 |

---

## Task 1: Bảng `alert_sent_log` + script `alert_events.py`

**Files:**
- Modify: `src/warehouse.py`
- Create: `alert_events.py`
- Create: `tests/test_warehouse_alerts.py`
- Create: `tests/test_alert_events.py`

**Interfaces:**
- Consumes: `src.warehouse.get_conn()`, `src.warehouse.init_warehouse(con)`, `src.notify.send(text: str)` (hàm có sẵn, KHÔNG sửa).
- Produces:
  - `warehouse.mark_events_alerted(con, event_ids: list[str], symbol_by_id: dict[str, str]) -> int` — ghi vào `alert_sent_log`, trả số dòng ghi.
  - `alert_events.load_portfolio_symbols(path=None) -> list[str]` — đọc `config/portfolio.yml`.
  - `alert_events.fetch_unalerted_events(con, symbols: list[str]) -> list[dict]` — sự kiện của `symbols` chưa có trong `alert_sent_log`.
  - `alert_events.is_first_run(con, symbols: list[str]) -> bool` — `True` nếu `alert_sent_log` chưa có dòng nào cho `symbols`.
  - `alert_events.format_message(events: list[dict], run_date: str) -> str`.
  - `alert_events.main()` — điều phối toàn bộ.

> **Bối cảnh không có trong spec**: `stg_corporate_event` (view, B1) có sẵn các cột: `id, symbol, event_code, event_name_vi, event_title_vi, category_source, action_type_vi, exercise_ratio, value_per_share, public_date, issue_date, start_date, end_date, record_date, exright_date, listing_date, payout_date, ingested_at, distribution_type, is_distribution` (đọc `transforms/models/staging/stg_corporate_event.sql`). Chỉ cần `id, symbol, event_title_vi, distribution_type, exright_date, record_date, payout_date, public_date` cho C2. `src/warehouse.py`'s `init_warehouse(con)` (dòng 163-369) chứa toàn bộ DDL các bảng — khối cuối cùng hiện tại là `raw_financial_statement` (dòng 350-366), ngay trước `def upsert_symbols` (dòng 370). `get_conn()` (dòng 102-107) đọc biến môi trường `WAREHOUSE_DB`, mặc định file cục bộ nếu không đặt.

- [ ] **Step 1: Viết test thất bại cho `mark_events_alerted`**

Tạo `tests/test_warehouse_alerts.py`:

```python
"""Test cho alert_sent_log — bảng chống lặp tin của C2."""
import duckdb
import pytest

from src.warehouse import init_warehouse, mark_events_alerted


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def test_mark_events_alerted_ghi_dung_so_dong(con):
    n = mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})
    assert n == 2
    assert con.execute("SELECT count(*) FROM alert_sent_log").fetchone()[0] == 2


def test_mark_events_alerted_ghi_dung_symbol(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    row = con.execute(
        "SELECT symbol FROM alert_sent_log WHERE event_id = 'e1'"
    ).fetchone()
    assert row[0] == "HPG"


def test_mark_events_alerted_danh_sach_rong_tra_0(con):
    assert mark_events_alerted(con, [], {}) == 0


def test_mark_events_alerted_khong_the_ghi_trung_event_id(con):
    """event_id là PRIMARY KEY — ghi lại cùng id là lỗi logic (gọi hàm 2 lần
    cho cùng sự kiện là bug ở tầng gọi), không phải ghi đè hợp lệ."""
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    with pytest.raises(duckdb.ConstraintException):
        mark_events_alerted(con, ["e1"], {"e1": "HPG"})
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_warehouse_alerts.py -q`
Expected: FAIL — `ImportError: cannot import name 'mark_events_alerted' from 'src.warehouse'`

- [ ] **Step 3: Thêm DDL + hàm vào `src/warehouse.py`**

Thêm DDL vào cuối `init_warehouse` (ngay sau khối DDL `raw_financial_statement`, trước dòng `def upsert_symbols`):

```python
    # --- C2: chống lặp tin cảnh báo sự kiện ---
    # event_id = stg_corporate_event.id (khoá ổn định, PRIMARY KEY của
    # raw_corporate_event từ B1). KHÔNG dùng SQLite cục bộ (storage.py) —
    # cơ chế cache-based của nó tự nhận best-effort, có thể mất khi GitHub
    # Actions evict cache, gây gửi lặp lại toàn bộ sự kiện cũ.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_sent_log (
            event_id    VARCHAR PRIMARY KEY,
            symbol      VARCHAR,
            alerted_at  TIMESTAMP
        );
        """
    )
```

Thêm hàm (đặt sau `mark_backfill_error`, cuối file):

```python
def mark_events_alerted(con, event_ids: list[str], symbol_by_id: dict[str, str]) -> int:
    """Ghi các event_id đã gửi/đã biết vào alert_sent_log — chống lặp tin.

    event_id là PRIMARY KEY: gọi lại với cùng event_id là lỗi ở tầng gọi
    (một sự kiện chỉ được đánh dấu đã biết đúng 1 lần), không silently
    ignore — để lộ bug sớm thay vì che giấu.
    """
    if not event_ids:
        return 0
    now = datetime.now(timezone.utc)
    con.executemany(
        "INSERT INTO alert_sent_log (event_id, symbol, alerted_at) VALUES (?, ?, ?)",
        [(eid, symbol_by_id[eid], now) for eid in event_ids],
    )
    return len(event_ids)
```

**LƯU Ý cho implementer:** `datetime`/`timezone` đã được import sẵn ở đầu `src/warehouse.py` (dùng bởi `log_load`) — không cần import lại, chỉ cần xác nhận đúng tên import hiện có trước khi dùng.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_warehouse_alerts.py -q`
Expected: PASS — 4 passed

- [ ] **Step 5: Viết test thất bại cho các hàm trong `alert_events.py`**

Tạo `tests/test_alert_events.py`:

```python
"""Test cho alert_events.py — script cảnh báo sự kiện DN (C2)."""
from unittest.mock import patch

import duckdb
import pytest

import alert_events
from src.warehouse import init_warehouse, mark_events_alerted


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    # stg_corporate_event là VIEW trên raw_corporate_event thật (dbt) —
    # test dựng bảng GIẢ cùng tên/schema trực tiếp trên DuckDB in-memory,
    # không chạy dbt (đúng pattern conftest_mart.py toàn dự án).
    c.execute("""
        CREATE TABLE stg_corporate_event (
            id VARCHAR, symbol VARCHAR, event_title_vi VARCHAR,
            distribution_type VARCHAR, exright_date DATE,
            record_date DATE, payout_date DATE, public_date DATE
        );
        INSERT INTO stg_corporate_event VALUES
          ('e1','HPG','Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND',
           'CASH_DIVIDEND',DATE '2026-05-11',DATE '2026-05-12',DATE '2026-06-30',DATE '2026-04-01'),
          ('e2','VNR','Đại hội cổ đông thường niên 2026',
           'SHAREHOLDER_MEETING',NULL,NULL,NULL,DATE '2026-04-01'),
          ('e3','ZZZ','Sự kiện của mã KHÔNG nằm trong portfolio',
           'OTHER',NULL,NULL,NULL,DATE '2026-04-01');
    """)
    yield c
    c.close()


def test_fetch_unalerted_events_chi_lay_ma_trong_portfolio(con):
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    ids = {e["id"] for e in events}
    assert ids == {"e1", "e2"}
    assert "e3" not in ids


def test_fetch_unalerted_events_bo_qua_su_kien_da_bao(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    ids = {e["id"] for e in events}
    assert ids == {"e2"}


def test_is_first_run_true_khi_alert_sent_log_rong(con):
    assert alert_events.is_first_run(con, ["HPG", "VNR"]) is True


def test_is_first_run_false_sau_khi_da_seed(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    assert alert_events.is_first_run(con, ["HPG", "VNR"]) is False


def test_format_message_khong_co_markdown_co_du_thong_tin(con):
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    text = alert_events.format_message(events, "2026-08-19")
    assert "HPG" in text
    assert "Trả cổ tức bằng tiền mặt" in text
    assert "VNR" in text
    assert "*" not in text and "_" not in text  # không markdown


def test_main_lan_dau_khong_goi_notify_chi_seed(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_not_called()

    assert con.execute("SELECT count(*) FROM alert_sent_log").fetchone()[0] == 2


def test_main_lan_2_co_su_kien_moi_goi_notify_dung_1_lan(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    # Seed trước (mô phỏng lần chạy đầu tiên đã xong)
    mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})
    # Sự kiện MỚI xuất hiện sau đó
    con.execute("""
        INSERT INTO stg_corporate_event VALUES
          ('e4','HPG','Phát hành cổ phiếu thưởng tỉ lệ 20%','BONUS_SHARE',
           DATE '2026-09-01',NULL,NULL,DATE '2026-08-20');
    """)

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_called_once()
        sent_text = mock_notify.send.call_args[0][0]
        assert "Phát hành cổ phiếu thưởng" in sent_text

    assert con.execute(
        "SELECT count(*) FROM alert_sent_log WHERE event_id = 'e4'"
    ).fetchone()[0] == 1


def test_main_khong_co_gi_moi_khong_goi_notify(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_not_called()
```

- [ ] **Step 6: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_alert_events.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alert_events'`

- [ ] **Step 7: Viết `alert_events.py`**

Tạo file mới ở thư mục gốc dự án (cùng cấp `main.py`/`build_warehouse.py`):

```python
"""Cảnh báo sự kiện DN cho danh mục — thay dần bản tin hằng ngày (C2).

Chạy: python alert_events.py
Yêu cầu biến môi trường: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
WAREHOUSE_DB (đặt 'md:vn_market' để đọc MotherDuck), motherduck_token
(nếu dùng MotherDuck).

KHÔNG đụng main.py/digest.py/daily.yml — chạy song song, độc lập hoàn
toàn. Không dùng SQLite cục bộ (src/storage.py) để chống lặp tin — dùng
bảng alert_sent_log trên warehouse (bền hơn cơ chế cache-based của
storage.py, tự nhận là "best-effort" trong docstring của chính nó).
"""
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import notify
from src.warehouse import get_conn, init_warehouse, mark_events_alerted

load_dotenv()
ROOT = Path(__file__).resolve().parent
DEFAULT_PORTFOLIO_PATH = ROOT / "config" / "portfolio.yml"


def load_portfolio_symbols(path=None) -> list[str]:
    p = Path(path) if path else DEFAULT_PORTFOLIO_PATH
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [h["symbol"] for h in cfg["holdings"]]


def fetch_unalerted_events(con, symbols: list[str]) -> list[dict]:
    """Sự kiện DN của `symbols` CHƯA có trong alert_sent_log."""
    if not symbols:
        return []
    placeholders = ", ".join(["?"] * len(symbols))
    rows = con.execute(
        f"""
        SELECT id, symbol, event_title_vi, distribution_type,
               exright_date, record_date, payout_date, public_date
        FROM stg_corporate_event
        WHERE symbol IN ({placeholders})
          AND id NOT IN (SELECT event_id FROM alert_sent_log)
        ORDER BY symbol, public_date
        """,
        symbols,
    ).df()
    return rows.to_dict(orient="records")


def is_first_run(con, symbols: list[str]) -> bool:
    """True nếu alert_sent_log CHƯA có dòng nào cho các mã trong `symbols`."""
    if not symbols:
        return False
    placeholders = ", ".join(["?"] * len(symbols))
    n = con.execute(
        f"SELECT count(*) FROM alert_sent_log WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchone()[0]
    return n == 0


def format_message(events: list[dict], run_date: str) -> str:
    lines = [f"📅 Sự kiện DN mới ({run_date}):", ""]
    for e in events:
        lines.append(f"{e['symbol']} — {e['event_title_vi']}")
        if e.get("exright_date") is not None:
            lines.append(f"  GDKHQ: {e['exright_date']}")
        elif e.get("public_date") is not None:
            lines.append(f"  Ngày công bố: {e['public_date']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(portfolio_path=None):
    con = get_conn()
    init_warehouse(con)
    try:
        symbols = load_portfolio_symbols(portfolio_path)
        run_date = date.today().isoformat()

        if is_first_run(con, symbols):
            events = fetch_unalerted_events(con, symbols)
            event_ids = [e["id"] for e in events]
            symbol_by_id = {e["id"]: e["symbol"] for e in events}
            n = mark_events_alerted(con, event_ids, symbol_by_id)
            print(f"Lần đầu chạy alert_events — đã seed {n} sự kiện hiện có, KHÔNG gửi Telegram.")
            return

        events = fetch_unalerted_events(con, symbols)
        if not events:
            print("Không có sự kiện DN mới.")
            return

        text = format_message(events, run_date)
        notify.send(text)
        event_ids = [e["id"] for e in events]
        symbol_by_id = {e["id"]: e["symbol"] for e in events}
        mark_events_alerted(con, event_ids, symbol_by_id)
        print(f"Đã gửi cảnh báo {len(events)} sự kiện mới, đã ghi log.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_alert_events.py -q`
Expected: PASS — 8 passed

- [ ] **Step 9: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — tăng đúng số test mới so với baseline trước Task 1 (chạy `pytest tests/ -q` trước khi bắt đầu Task 1 để biết baseline chính xác), không mất test nào.

- [ ] **Step 10: Commit**

```bash
git add src/warehouse.py alert_events.py tests/test_warehouse_alerts.py tests/test_alert_events.py
git commit -m "feat(c2): bảng alert_sent_log + script alert_events.py

Chống lặp tin bằng MotherDuck (alert_sent_log), không dùng SQLite cục bộ
của storage.py (tự nhận best-effort, phụ thuộc GitHub Actions cache dễ
mất). Lần chạy đầu tiên chỉ seed, không gửi Telegram — tránh dội sự kiện
lịch sử khi mới bật tính năng. Không đụng main.py/digest.py/daily.yml.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Workflow GitHub Actions + nghiệm thu trên production thật

**Files:**
- Create: `.github/workflows/event-alerts.yml`

**Interfaces:**
- Consumes: `alert_events.main()` (Task 1).
- Produces: bằng chứng cho 5 tiêu chí hoàn thành trong spec §6.

> **Bối cảnh không có trong Task 1**: `.github/workflows/daily.yml`/`.github/workflows/warehouse-weekly.yml` là 2 file workflow hiện có, dùng làm template cấu trúc (checkout, setup-python, cache pip, chạy script với `env:`). Secret `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`MOTHERDUCK_TOKEN`/`VNSTOCK_API_KEY` đã cấu hình sẵn trong repo (đang dùng bởi `daily.yml`/`warehouse-monthly.yml`), dùng lại tên y hệt, KHÔNG cần tạo secret mới.

- [ ] **Step 1: Viết workflow**

Tạo `.github/workflows/event-alerts.yml`:

```yaml
name: event-alerts

on:
  schedule:
    # 09:00 UTC hằng ngày (T2-T6) — cùng giờ daily.yml, đọc dữ liệu warehouse
    # đã cập nhật từ job weekly/monthly (chạy riêng, không phụ thuộc job này).
    - cron: "0 9 * * 1-5"
  workflow_dispatch: {}

jobs:
  event-alerts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Cảnh báo sự kiện DN cho danh mục
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python alert_events.py
```

- [ ] **Step 2: Xác nhận YAML hợp lệ**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/event-alerts.yml'))" && echo "YAML hợp lệ"
```

- [ ] **Step 3: Chạy lần ĐẦU TIÊN thật trên production — xác nhận seed, KHÔNG gửi Telegram**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python alert_events.py
```

Expected: in ra dòng "Lần đầu chạy alert_events — đã seed N sự kiện hiện có, KHÔNG gửi Telegram." — **KIỂM TRA THỦ CÔNG: xác nhận Telegram KHÔNG nhận tin nào từ lệnh này** (mở app Telegram/kiểm log, không có cách tự động hoá bước xác nhận cuối này — ghi rõ trong báo cáo bạn ĐÃ kiểm tra bằng cách nào).

- [ ] **Step 4: Xác nhận đã seed đúng vào `alert_sent_log`**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market', read_only=True)
print(con.execute('SELECT count(*), count(DISTINCT symbol) FROM alert_sent_log').fetchone())
print(con.execute('SELECT symbol, count(*) FROM alert_sent_log GROUP BY 1').fetchall())
"
```

Expected: có dòng cho cả 5 mã portfolio (HPG, IDV, MLS, PHP, VNR) — hoặc ít hơn nếu 1 vài mã chưa có sự kiện DN nào trong `stg_corporate_event` (không phải lỗi, xác nhận bằng cách kiểm `stg_corporate_event` trực tiếp cho mã đó).

- [ ] **Step 5: Chạy LẦN THỨ HAI ngay sau đó — xác nhận KHÔNG gửi gì (không có sự kiện mới giữa 2 lần chạy sát nhau)**

```bash
.venv/bin/python alert_events.py
```

Expected: in ra "Không có sự kiện DN mới." — xác nhận cơ chế dedup hoạt động đúng trên dữ liệu thật, không chỉ trên fixture.

- [ ] **Step 6: Kiểm không đụng hệ thống bot cũ**

```bash
git diff --stat main...HEAD -- main.py src/digest.py src/signals.py src/screener.py src/storage.py .github/workflows/daily.yml
```

Expected: rỗng (không có dòng nào). Nếu có, dừng lại và báo controller.

- [ ] **Step 7: Chạy toàn bộ test lần cuối**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, không giảm so với baseline trước Task 2.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/event-alerts.yml
git commit -m "feat(c2): workflow event-alerts.yml, nghiệm thu trên production

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành C2 (đối chiếu spec §6)

| # | Tiêu chí | Task |
|---|---|---|
| 1 | Toàn bộ pytest pass, không hỏng test cũ | 1, 2 |
| 2 | Lần chạy đầu tiên trên production KHÔNG gửi Telegram, chỉ seed | 2 (Step 3-4) |
| 3 | `daily.yml`/`main.py`/`digest.py`/`storage.py` không bị đụng | 2 (Step 6) |
| 4 | Workflow mới chạy được thủ công (`workflow_dispatch`) | 2 (Step 1-2, cấu trúc đúng — xác nhận chạy thật qua Actions tab nếu muốn, không bắt buộc trong phạm vi task) |
| 5 | Chạy 2 lần liên tiếp trên production thật → lần 2 không gửi gì | 2 (Step 3, 5) |

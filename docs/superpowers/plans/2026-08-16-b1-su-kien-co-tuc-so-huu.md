# B1 — Sự kiện DN, phân phối & cơ cấu sở hữu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa sự kiện doanh nghiệp (cổ tức tiền mặt/cổ phiếu, phát hành, ĐHCĐ, giao dịch cổ đông lớn) và cơ cấu sở hữu vào warehouse, phân loại chính xác, và phơi ra qua 2 tool MCP — không đụng tới mart hay công thức chấm điểm hiện có.

**Architecture:** Ba bảng raw với **hai cơ chế ghi khác nhau** (sự kiện append-only theo `id` vì cửa sổ API trượt; sở hữu snapshot theo ngày vì là dữ liệu trạng thái) → tầng staging phân loại **hai tầng** (`event_code` có cấu trúc làm chính, chỉ đọc tiêu đề tự do cho nhánh `ISS`) → tầng intermediate cô đặc → 2 tool MCP trả **hai trục thời gian tách bạch**, không ép ghép.

**Tech Stack:** Python 3.12 · vnstock 4.0.4 (`vnstock.api.company.Company`) · DuckDB/MotherDuck · dbt-duckdb · FastMCP · pytest

**Spec:** `docs/superpowers/specs/2026-08-16-b1-su-kien-co-tuc-so-huu-design.md`

## Global Constraints

- **Không đụng `mart_stock_scorecard`**, không thêm cột vào mart hiện có, không đổi công thức chấm điểm, không sửa `int_dividend_history`. Tiêu chí nghiệm thu #8 là đối chiếu điểm số trước/sau phải **không đổi**.
- **Bảng nguồn bất khả xâm phạm:** không code nào được DROP/ALTER/ghi vào `raw_price_daily`, `raw_financial_ratio`, `raw_company_info`, `raw_index_daily`, `dim_symbols`, `dim_industry`, `etl_load_log`, `backfill_status`.
- **Toàn bộ docstring, comment, commit message, tên test viết bằng tiếng Việt.**
- **`is_distribution` chỉ true cho đúng 3 giá trị:** `CASH_DIVIDEND`, `STOCK_DIVIDEND`, `BONUS_SHARE`. Mọi thứ khác false — fail-closed.
- **Không đoán khi không khớp:** `ISS_KHAC` và `UNKNOWN_CODE` là nhãn hợp lệ, không phải lỗi cần né.
- **Ngưỡng cảnh báo phân loại:** `ISS_KHAC + UNKNOWN_CODE` ≤ **5%** tổng số sự kiện.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`. Baseline trước B1: **213 passed, 2 xfailed**.
- Branch làm việc: `feat/b1-events-ownership` (mỗi mảng một nhánh riêng, theo quy ước A1/A2/A3).
- Mọi tool MCP mới phải bọc `@_safe_tool`, trả `as_of`, đọc qua `db.run_query`.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `scripts/probe_event_id_stability.py` | **Mới.** Kiểm chứng `id` ổn định — chặn mọi việc còn lại | 1 |
| `src/warehouse.py` | **Sửa.** DDL 3 bảng mới + 3 hàm ghi + 3 hằng cột | 2, 3 |
| `src/ingest_market.py` | **Sửa.** 3 hàm fetch + 3 hàm normalize | 2, 3 |
| `build_warehouse.py` | **Sửa.** Nối sự kiện vào `weekly`, sở hữu vào `monthly` | 2, 3 |
| `transforms/models/staging/_sources.yml` | **Sửa.** Khai báo 3 source mới | 2, 3 |
| `transforms/models/staging/stg_corporate_event.sql` | **Mới.** Phân loại hai tầng | 4 |
| `transforms/models/staging/stg_shareholder.sql` | **Mới.** Chuẩn hoá cổ đông | 5 |
| `transforms/models/staging/stg_officer.sql` | **Mới.** Chuẩn hoá ban lãnh đạo | 5 |
| `transforms/models/staging/_staging.yml` | **Sửa.** Test schema cho 3 model mới | 4, 5 |
| `transforms/models/intermediate/int_distribution_event.sql` | **Mới.** Chỉ sự kiện phân phối | 5 |
| `transforms/models/intermediate/int_ownership_snapshot.sql` | **Mới.** Cô đặc sở hữu | 5 |
| `transforms/models/intermediate/_intermediate.yml` | **Sửa.** Test schema cho 2 model mới | 5 |
| `transforms/tests/assert_distribution_flag_only_three_types.sql` | **Mới.** Canh fail-closed | 4 |
| `transforms/tests/assert_event_classification_coverage.sql` | **Mới.** Canh parser xuống cấp | 4 |
| `transforms/tests/assert_cash_dividend_matches_ratio.sql` | **Mới.** Đối chiếu chéo hai nguồn | 5 |
| `mcp_server/tools.py` | **Sửa.** 2 hàm tool mới | 6 |
| `mcp_server/server.py` | **Sửa.** Đăng ký 2 tool | 6 |
| `tests/test_warehouse_events.py` | **Mới.** Test append-only + snapshot | 2, 3 |
| `tests/test_ingest_events.py` | **Mới.** Test normalize | 2, 3 |
| `tests/conftest_mart.py` | **Sửa.** Thêm bảng giả cho tool mới | 6 |
| `tests/test_mcp_tools.py` | **Sửa.** Test 2 tool mới | 6 |
| `tests/test_mcp_server.py` | **Sửa.** Test qua `mcp.call_tool()` | 6 |
| `scripts/check_mcp_tools.py` | **Sửa.** Nghiệm thu 9 tool | 7 |
| `README.md` | **Sửa.** Cập nhật kiến trúc | 7 |

---

## Task 1: Kiểm chứng `id` ổn định — CHẶN

**Files:**
- Create: `scripts/probe_event_id_stability.py`

**Interfaces:**
- Consumes: `vnstock.api.company.Company`
- Produces: kết luận đi/không đi cho toàn bộ plan. Không có code nào khác phụ thuộc file này.

> **Vì sao task này đứng riêng và đi trước:** toàn bộ cơ chế append-only của `raw_corporate_event` dựa vào giả định `id` ổn định giữa các lần gọi API. Nếu nguồn sinh `id` mới mỗi lần, dedup vỡ, bảng phình vô hạn mỗi tuần, và mọi thứ phía sau vô nghĩa. Chưa xác minh thì chưa xây.

- [ ] **Step 1: Viết script kiểm chứng**

```python
"""Kiểm chứng `id` của Company.events() có ổn định giữa các lần gọi không.

Toàn bộ cơ chế append-only của raw_corporate_event (B1) dựa vào giả định
này. Nếu nguồn sinh id mới mỗi lần gọi, dedup theo id sẽ vỡ và bảng phình
vô hạn sau mỗi lần chạy weekly.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_event_id_stability

Exit code 0 = id ổn định, dùng làm khoá dedup được.
Exit code 1 = id KHÔNG ổn định, phải đổi sang khoá thay thế.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.company import Company

# Mẫu cố tình trộn mã năng động sự kiện (MWG, HPG) với mã ít sự kiện (VNR),
# vì cửa sổ 50 sự kiện của hai nhóm này phủ khoảng thời gian rất khác nhau
# (đo 2026-08-16: MWG 1,0 năm, VNR 9,4 năm) nên cơ chế sinh id có thể khác.
SYMBOLS = ["HPG", "VNM", "VCB", "MWG", "VNR"]
SLEEP_BETWEEN_CALLS = 1.05      # khớp VNSTOCK_MIN_INTERVAL của job thật
SLEEP_BETWEEN_ROUNDS = 60       # đủ dài để lộ id sinh theo timestamp/session


def snapshot(symbol: str) -> dict[str, tuple[str, str]]:
    """Trả {id: (event_code, exright_date)} cho một mã."""
    df = Company(symbol=symbol, source="VCI").events()
    df.columns = [str(c).lower() for c in df.columns]
    return {
        str(row["id"]): (str(row.get("event_code")), str(row.get("exright_date")))
        for _, row in df.iterrows()
    }


def main() -> int:
    print(f"Vòng 1: gọi events() cho {len(SYMBOLS)} mã...")
    first = {}
    for sym in SYMBOLS:
        first[sym] = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu...")
    ok = True
    for sym in SYMBOLS:
        second = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[sym], second
        chung = set(a) & set(b)
        print(f"  {sym}: vòng 1 = {len(a)} id, vòng 2 = {len(b)} id, trùng = {len(chung)}")
        if not chung:
            print(f"    THẤT BẠI: không id nào trùng — id KHÔNG ổn định")
            ok = False
            continue
        lech = [k for k in chung if a[k] != b[k]]
        if lech:
            print(f"    THẤT BẠI: {len(lech)} id trùng nhưng nội dung khác — "
                  f"id bị tái sử dụng cho sự kiện khác")
            ok = False
        # Trùng < 90% nghĩa là id đổi phần lớn dù vẫn có một ít trùng —
        # vẫn coi là không ổn định, vì bảng sẽ phình gần như toàn bộ mỗi tuần.
        elif len(chung) < 0.9 * min(len(a), len(b)):
            print(f"    THẤT BẠI: chỉ {len(chung)}/{min(len(a), len(b))} id trùng "
                  f"(<90%) — id không đủ ổn định để dedup")
            ok = False

    print()
    if ok:
        print("KẾT LUẬN: id ỔN ĐỊNH — dùng làm khoá dedup append-only được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: id KHÔNG ổn định — PHẢI đổi khoá dedup sang hash của "
          "(symbol, event_code, exright_date, event_title_vi) trước khi đi tiếp. "
          "BÁO CONTROLLER, KHÔNG tự đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Chạy script trên API thật**

```bash
set -a && source .env && set +a
.venv/bin/python -m scripts.probe_event_id_stability
```

Expected: in ra kết quả từng mã và một dòng KẾT LUẬN. Script chạy ~2,5 phút (60 giây chờ + 10 lần gọi).

- [ ] **Step 3: Ghi kết quả vào báo cáo, dừng nếu thất bại**

Nếu exit code = 1: **DỪNG LẠI**, báo controller kèm output đầy đủ. Không tự đổi thiết kế sang khoá hash — đó là quyết định của controller vì nó ảnh hưởng schema bảng và mọi task sau.

Nếu exit code = 0: ghi vào báo cáo "id ổn định, xác minh trên 5 mã, N id trùng khớp hoàn toàn" kèm output, rồi tiếp Task 2.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_event_id_stability.py
git commit -m "test(b1): script kiểm chứng id sự kiện ổn định trước khi xây append-only

Toàn bộ cơ chế append-only của raw_corporate_event dựa vào giả định id ổn
định giữa các lần gọi Company.events(). Kiểm trước, chưa xong không xây.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `raw_corporate_event` — bảng, fetch, ghi append-only, nối vào weekly

**Files:**
- Modify: `src/warehouse.py` (thêm `EVENT_COLS`, DDL trong `init_warehouse`, hàm `insert_corporate_events`)
- Modify: `src/ingest_market.py` (thêm `fetch_corporate_events`, `_normalize_events`, `EVENT_DATE_COLS`)
- Modify: `build_warehouse.py` (nối vào nhánh `weekly`/`monthly`)
- Modify: `transforms/models/staging/_sources.yml`
- Create: `tests/test_warehouse_events.py`
- Create: `tests/test_ingest_events.py`

**Interfaces:**
- Consumes: `src.ingest._throttle()`, `src.dq.assert_columns`, `src.dq.SchemaError`, `src.dq.status_for`
- Produces:
  - `warehouse.EVENT_COLS: list[str]` — 17 tên cột, đúng thứ tự
  - `warehouse.insert_corporate_events(con, df) -> int` — trả **số dòng THỰC SỰ thêm mới** (không phải `len(df)`)
  - `ingest_market.fetch_corporate_events(symbols: list[str], source: str = "VCI") -> pd.DataFrame` — cột đúng `warehouse.EVENT_COLS`
  - Bảng `raw_corporate_event` với `id VARCHAR PRIMARY KEY`

- [ ] **Step 1: Viết test thất bại cho `insert_corporate_events`**

Tạo `tests/test_warehouse_events.py`:

```python
"""Test cho raw_corporate_event — cơ chế APPEND-ONLY.

Company.events() chỉ trả 50 sự kiện gần nhất và cửa sổ đó TRƯỢT theo thời
gian: đo trên 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm (MWG) tới 9,9
năm (AGX) tuỳ mã đó hoạt động sự kiện nhiều hay ít. Ghi đè bảng theo mỗi
lần fetch là mất vĩnh viễn phần đã rơi khỏi cửa sổ — đây là lý do bảng này
ghi append-only thay vì INSERT OR REPLACE như raw_price_daily.
"""
import duckdb
import pandas as pd
import pytest

from src.warehouse import EVENT_COLS, init_warehouse, insert_corporate_events


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _event_row(event_id: str, symbol: str = "AAA", code: str = "DIV", **kw) -> dict:
    row = {
        "id": event_id, "symbol": symbol, "event_code": code,
        "event_name_vi": "Trả cổ tức bằng tiền mặt",
        "event_title_vi": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND",
        "category": "DIVIDEND", "public_date": "2026-04-20",
        "issue_date": "2026-04-20", "start_date": None, "end_date": None,
        "record_date": "2026-05-12", "exright_date": "2026-05-11",
        "listing_date": None, "payout_date": "2026-06-30",
        "exercise_ratio": 0.05, "value_per_share": 500.0, "action_type_vi": None,
    }
    row.update(kw)
    return row


def test_insert_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_event_row("e1"), _event_row("e2")])[EVENT_COLS]
    assert insert_corporate_events(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0] == 2


def test_insert_lai_cung_id_khong_them_dong_nao(con):
    df = pd.DataFrame([_event_row("e1")])[EVENT_COLS]
    insert_corporate_events(con, df)
    assert insert_corporate_events(con, df) == 0
    assert con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0] == 1


def test_su_kien_cu_khong_bi_mat_khi_cua_so_truot(con):
    """Ca thật: lần fetch sau, sự kiện cũ nhất đã rơi khỏi cửa sổ 50 của API.

    Bảng PHẢI giữ lại nó. Đây chính là lý do tồn tại của append-only — nếu
    đổi sang INSERT OR REPLACE trên toàn bảng hoặc DELETE+INSERT thì test
    này đỏ.
    """
    lan_1 = pd.DataFrame([_event_row("cu"), _event_row("moi_1")])[EVENT_COLS]
    insert_corporate_events(con, lan_1)
    # Lần 2: "cu" đã rơi khỏi cửa sổ API, xuất hiện "moi_2"
    lan_2 = pd.DataFrame([_event_row("moi_1"), _event_row("moi_2")])[EVENT_COLS]
    assert insert_corporate_events(con, lan_2) == 1

    ids = {r[0] for r in con.execute("SELECT id FROM raw_corporate_event").fetchall()}
    assert ids == {"cu", "moi_1", "moi_2"}


def test_bo_qua_dong_id_null(con):
    df = pd.DataFrame([_event_row("e1"), _event_row(None)])[EVENT_COLS]
    assert insert_corporate_events(con, df) == 1


def test_df_rong_tra_0(con):
    assert insert_corporate_events(con, pd.DataFrame()) == 0
    assert insert_corporate_events(con, None) == 0
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_warehouse_events.py -q`
Expected: FAIL — `ImportError: cannot import name 'EVENT_COLS' from 'src.warehouse'`

- [ ] **Step 3: Thêm `EVENT_COLS` + DDL + `insert_corporate_events` vào `src/warehouse.py`**

Thêm hằng ngay sau khối `COMPANY_COLS` (khoảng dòng 66):

```python
# --- Cột raw_corporate_event (nguồn: Company.events, 22 cột) ---
# Không lấy: các cột *_en (event_name_en, event_title_en, action_type_en —
# trùng nghĩa với bản tiếng Việt), display_date1/display_date2 (ngữ nghĩa
# không rõ, nguồn không tài liệu hoá), ticker (trùng symbol).
EVENT_COLS = [
    "id", "symbol", "event_code", "event_name_vi", "event_title_vi", "category",
    "public_date", "issue_date", "start_date", "end_date",
    "record_date", "exright_date", "listing_date", "payout_date",
    "exercise_ratio", "value_per_share", "action_type_vi",
]
```

Thêm DDL vào cuối `init_warehouse` (sau khối `_ensure_columns` của `raw_company_info`):

```python
    # --- B1: sự kiện DN (append-only) ---
    # id là PRIMARY KEY: cửa sổ Company.events() chỉ 50 sự kiện gần nhất và
    # trượt theo thời gian, nên bảng này CỘNG DỒN chứ không thay thế. Xem
    # insert_corporate_events.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_corporate_event (
            id              VARCHAR PRIMARY KEY,
            symbol          VARCHAR,
            event_code      VARCHAR,
            event_name_vi   VARCHAR,
            event_title_vi  VARCHAR,
            category        VARCHAR,
            public_date     DATE,
            issue_date      DATE,
            start_date      DATE,
            end_date        DATE,
            record_date     DATE,
            exright_date    DATE,
            listing_date    DATE,
            payout_date     DATE,
            exercise_ratio  DOUBLE,
            value_per_share DOUBLE,
            action_type_vi  VARCHAR,
            ingested_at     TIMESTAMP
        );
        """
    )
```

Thêm hàm ghi (đặt ngay sau `upsert_company_info`):

```python
def insert_corporate_events(con, df) -> int:
    """Ghi sự kiện DN — APPEND-ONLY: chỉ chèn `id` chưa có, không ghi đè.

    KHÁC upsert_prices/upsert_financial_ratios (INSERT OR REPLACE) một cách
    có chủ đích. Company.events() chỉ trả 50 sự kiện GẦN NHẤT mỗi mã và cửa
    sổ đó TRƯỢT: đo trên 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm
    (MWG) tới 9,9 năm (AGX) tuỳ mã hoạt động sự kiện nhiều hay ít. Mã năng
    động rơi mất sự kiện cũ nhất sau mỗi lần công bố sự kiện mới — nếu bảng
    này thay thế theo mỗi mẻ fetch thì phần rơi khỏi cửa sổ mất vĩnh viễn.
    Cộng dồn thì ngược lại: chạy đều mỗi tuần, lịch sử dày lên theo thời
    gian bất kể giới hạn API.

    Trả về số dòng THỰC SỰ được thêm (không phải len(df)) — con số này vào
    thẳng etl_load_log để theo dõi tốc độ tích luỹ.
    """
    if df is None or df.empty:
        return 0
    before = con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0]
    cols = ", ".join(EVENT_COLS)
    con.register("df_ev", df)
    con.execute(
        f"""
        INSERT INTO raw_corporate_event ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_ev src
        WHERE src.id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM raw_corporate_event t WHERE t.id = src.id
          );
        """
    )
    con.unregister("df_ev")
    after = con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0]
    return after - before
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_warehouse_events.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Viết test thất bại cho `_normalize_events`**

Tạo `tests/test_ingest_events.py`:

```python
"""Test chuẩn hoá Company.events() -> schema raw_corporate_event."""
import pandas as pd
import pytest

from src import dq
from src.ingest_market import _normalize_events
from src.warehouse import EVENT_COLS


def _raw_df(**kw) -> pd.DataFrame:
    """Dựng DataFrame giống nguyên trạng nguồn trả về (22 cột, có cả cột *_en
    mà ta cố ý không lấy)."""
    row = {
        "id": 12345, "event_name_vi": "Trả cổ tức bằng tiền mặt",
        "event_name_en": "Cash dividend", "ticker": "HPG", "event_code": "DIV",
        "event_title_vi": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND",
        "event_title_en": "Cash dividend - FY2025 - 500 VND",
        "display_date1": "2026-05-11", "display_date2": "2026-05-12",
        "public_date": "2026-04-20", "issue_date": "2026-04-20",
        "category": "DIVIDEND", "start_date": None, "end_date": None,
        "action_type_vi": None, "action_type_en": None,
        "record_date": "2026-05-12", "exright_date": "2026-05-11",
        "listing_date": None, "exercise_ratio": 0.05,
        "payout_date": "2026-06-30", "value_per_share": 500.0,
    }
    row.update(kw)
    return pd.DataFrame([row])


def test_normalize_tra_dung_bo_cot():
    out = _normalize_events(_raw_df(), "HPG")
    assert list(out.columns) == EVENT_COLS


def test_id_ep_ve_chuoi_va_symbol_lay_tu_tham_so():
    """id nguồn là số nguyên; bảng đích khai VARCHAR PRIMARY KEY nên phải ép
    chuỗi ngay ở đây, không để DuckDB tự ép ngầm. symbol lấy từ tham số chứ
    không từ cột `ticker` — cùng lý do như các hàm fetch khác trong file:
    tham số là thứ ta chủ động kiểm soát, cột nguồn có thể vắng."""
    out = _normalize_events(_raw_df(), "hpg")
    assert out.loc[0, "id"] == "12345"
    assert out.loc[0, "symbol"] == "HPG"


def test_ngay_ep_ve_chuoi_iso():
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "exright_date"] == "2026-05-11"
    assert out.loc[0, "payout_date"] == "2026-06-30"


def test_ngay_null_giu_nguyen_none_khong_thanh_chuoi_nat():
    """Bài học A3 fix round 1: pandas NaT lọt qua guard kiểu float rồi
    isoformat() ra chuỗi literal 'NaT'. Cột ngày rỗng phải là None."""
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "start_date"] is None or pd.isna(out.loc[0, "start_date"])


def test_thieu_cot_bat_buoc_raise_schema_error():
    df = _raw_df().drop(columns=["event_code"])
    with pytest.raises(dq.SchemaError):
        _normalize_events(df, "HPG")


def test_gia_tri_so_giu_dung_kieu():
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "exercise_ratio"] == pytest.approx(0.05)
    assert out.loc[0, "value_per_share"] == pytest.approx(500.0)
```

- [ ] **Step 6: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_events.py -q`
Expected: FAIL — `ImportError: cannot import name '_normalize_events' from 'src.ingest_market'`

- [ ] **Step 7: Thêm `fetch_corporate_events` + `_normalize_events` vào `src/ingest_market.py`**

Thêm vào cuối file:

```python
_printed_event_cols = False

# Tám cột ngày của Company.events(). Ép về chuỗi ISO ở tầng normalize để
# DuckDB nhận đúng kiểu DATE, thay vì để pandas Timestamp đi thẳng vào
# INSERT (đúng lớp lỗi 'NaT' đã sửa ở A3 fix round 1).
EVENT_DATE_COLS = [
    "public_date", "issue_date", "start_date", "end_date",
    "record_date", "exright_date", "listing_date", "payout_date",
]

_EVENT_REQUIRED = ["id", "event_code", "event_title_vi"]


def fetch_corporate_events(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """Sự kiện DN (cổ tức, phát hành, ĐHCĐ, giao dịch cổ đông lớn) qua
    Company.events().

    Nguồn chỉ trả 50 SỰ KIỆN GẦN NHẤT mỗi mã, không có tham số mở rộng, và
    cửa sổ đó TRƯỢT theo thời gian — xem docstring
    warehouse.insert_corporate_events để biết vì sao bảng đích ghi
    append-only.

    Bắt dq.SchemaError theo TỪNG MÃ (cùng lý do như fetch_financials): một
    mã dị thường trong ~1.600 mã không được phép xoá sổ cả mẻ đang chạy
    (~28 phút fetch với _throttle 1,05s/call). Vẫn raise to nếu tỉ lệ mã
    lỗi vượt ngưỡng dq.status_for.
    """
    global _printed_event_cols
    frames, rejected = [], 0
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).events()
        except Exception as e:
            print(f"[events] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_event_cols:
            print(f"[events] cột thật ({symbol}): {list(df.columns)}")
            _printed_event_cols = True
        try:
            frames.append(_normalize_events(df, symbol))
        except dq.SchemaError as e:
            print(f"[events] {symbol}: {e}")
            rejected += 1
            continue
    if rejected and dq.status_for(len(frames), rejected) == "degraded":
        raise dq.SchemaError(
            f"[Company.events] {rejected}/{len(symbols)} mã sai schema "
            "— nguồn có thể đã đổi"
        )
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # drop_duplicates("id") trước khi ghi: NOT EXISTS trong
    # insert_corporate_events chỉ chống trùng với dòng ĐÃ CÓ trong bảng,
    # không chống trùng trong cùng một mẻ — mà id là PRIMARY KEY nên trùng
    # nội bộ mẻ sẽ ném ConstraintException giết cả job.
    return out.dropna(subset=["id"]).drop_duplicates("id").reset_index(drop=True)


def _normalize_events(df, symbol) -> pd.DataFrame:
    dq.assert_columns(df, _EVENT_REQUIRED, f"Company.events({symbol})")

    def text(col):
        if col not in df.columns:
            return None
        s = df[col]
        # astype(str) biến None thành chuỗi 'None' (đúng lỗi đã gặp ở
        # stg_financial_ratio) — where(notna) giữ None thật là None.
        return s.astype(str).str.strip().where(s.notna(), None)

    def num(col):
        return (pd.to_numeric(df[col], errors="coerce")
                if col in df.columns else float("nan"))

    out = pd.DataFrame({
        "id":              df["id"].astype(str).str.strip(),
        "symbol":          symbol.upper().strip(),
        "event_code":      text("event_code"),
        "event_name_vi":   text("event_name_vi"),
        "event_title_vi":  text("event_title_vi"),
        "category":        text("category"),
        "action_type_vi":  text("action_type_vi"),
        "exercise_ratio":  num("exercise_ratio"),
        "value_per_share": num("value_per_share"),
    })
    for col in EVENT_DATE_COLS:
        out[col] = _date_col(df, col)
    return out[warehouse.EVENT_COLS]


def _date_col(df, col):
    """Ép một cột ngày về chuỗi ISO, giữ None thật là None.

    KHÔNG dùng .astype(str) hay .dt.strftime() trần: cả hai biến NaT thành
    chuỗi literal 'NaT' — đúng lớp lỗi đã phải sửa ở A3 fix round 1, chỉ
    khác là lần đó xảy ra ở tầng đọc còn đây là tầng ghi.

    Task 3 dùng lại chính hàm này cho raw_shareholder/raw_officer.
    """
    if col not in df.columns:
        return None
    parsed = pd.to_datetime(df[col], errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), None)
```

- [ ] **Step 8: Chạy cả hai file test**

Run: `.venv/bin/python -m pytest tests/test_ingest_events.py tests/test_warehouse_events.py -q`
Expected: PASS — 11 passed

- [ ] **Step 9: Nối vào `build_warehouse.py`**

Chèn khối này ngay **trước** khối `# 4) Dim_industry ... monthly only`:

```python
    # 3b) Sự kiện doanh nghiệp (B1) — weekly và monthly.
    # Chạy tuần chứ không tháng: GDKHQ có ngày cụ thể, chạy tháng dễ lỡ sự
    # kiện vừa công bố vừa chốt quyền trong cùng tháng.
    if args.mode in ("weekly", "monthly"):
        print(f"Bắt đầu fetch sự kiện DN ({len(symbols)} mã)...")
        events = ingest_market.fetch_corporate_events(symbols, source)
        n_ev = warehouse.insert_corporate_events(con, events)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_corporate_event",
                           n_ev, "ok" if n_ev else "empty", watermark=run_date,
                           notes=f"append-only; fetch {len(events)} dong")
        print(f"raw_corporate_event: +{n_ev} dòng mới (fetch {len(events)})")
```

- [ ] **Step 10: Khai báo source cho dbt**

Trong `transforms/models/staging/_sources.yml`, thêm vào cuối danh sách `tables`:

```yaml
      - name: raw_corporate_event
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 10, period: day}
          error_after: {count: 20, period: day}
```

- [ ] **Step 11: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 224 passed, 2 xfailed (213 + 11 mới), không hỏng test cũ nào.

- [ ] **Step 12: Commit**

```bash
git add src/warehouse.py src/ingest_market.py build_warehouse.py \
        transforms/models/staging/_sources.yml \
        tests/test_warehouse_events.py tests/test_ingest_events.py
git commit -m "feat(b1): bảng raw_corporate_event ghi append-only + fetch sự kiện DN

Company.events() chỉ trả 50 sự kiện gần nhất và cửa sổ đó trượt theo thời
gian (đo 15 mã: 1,0 năm với MWG tới 9,9 năm với AGX). Ghi đè là mất vĩnh
viễn phần rơi khỏi cửa sổ, nên bảng này cộng dồn theo id thay vì
INSERT OR REPLACE như raw_price_daily.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `raw_shareholder` + `raw_officer` — snapshot theo ngày, nối vào monthly

**Files:**
- Modify: `src/warehouse.py` (thêm `SHAREHOLDER_COLS`, `OFFICER_COLS`, DDL, 2 hàm upsert)
- Modify: `src/ingest_market.py` (thêm `fetch_shareholders`, `fetch_officers`, 2 hàm normalize)
- Modify: `build_warehouse.py` (nối vào nhánh `monthly`)
- Modify: `transforms/models/staging/_sources.yml`
- Modify: `tests/test_warehouse_events.py` (thêm test snapshot)
- Modify: `tests/test_ingest_events.py` (thêm test normalize)

**Interfaces:**
- Consumes: `src.ingest._throttle()`, `src.dq.*`
- Produces:
  - `warehouse.SHAREHOLDER_COLS: list[str]` = `["symbol", "share_holder", "quantity", "share_own_percent", "update_date", "snapshot_date"]`
  - `warehouse.OFFICER_COLS: list[str]` = `["symbol", "officer_name", "officer_position", "officer_own_percent", "officer_own_quantity", "update_date", "snapshot_date"]`
  - `warehouse.upsert_shareholders(con, df) -> int`, `warehouse.upsert_officers(con, df) -> int`
  - `ingest_market.fetch_shareholders(symbols, source="VCI", snapshot_date: str) -> pd.DataFrame`
  - `ingest_market.fetch_officers(symbols, source="VCI", snapshot_date: str) -> pd.DataFrame`

> **Vì sao khác Task 2:** cổ đông là dữ liệu **trạng thái** ("ai đang nắm bao nhiêu hôm nay"), không phải dòng sự kiện. Nguồn không có `id` ổn định, và thứ có giá trị chính là *thay đổi theo thời gian*. Nên ghi **snapshot theo ngày**: chạy lại trong cùng tháng thì thay thế (idempotent), sang tháng sau thì thêm bản ghi mới.

- [ ] **Step 1: Viết test thất bại cho snapshot**

Thêm vào cuối `tests/test_warehouse_events.py`:

```python
from src.warehouse import (OFFICER_COLS, SHAREHOLDER_COLS,
                           upsert_officers, upsert_shareholders)


def _sh_row(holder: str, pct: float, snap: str, symbol: str = "AAA") -> dict:
    return {"symbol": symbol, "share_holder": holder, "quantity": 1000.0,
            "share_own_percent": pct, "update_date": "2026-07-01",
            "snapshot_date": snap}


def test_shareholder_chay_lai_cung_ngay_la_idempotent(con):
    df = pd.DataFrame([_sh_row("Ông A", 0.25, "2026-08-01")])[SHAREHOLDER_COLS]
    upsert_shareholders(con, df)
    upsert_shareholders(con, df)
    assert con.execute("SELECT count(*) FROM raw_shareholder").fetchone()[0] == 1


def test_shareholder_giu_lich_su_qua_cac_snapshot(con):
    """Đây là lý do tồn tại của snapshot: thấy được sở hữu ĐỔI theo thời gian.

    Nếu đổi khoá chính thành (symbol, share_holder) — bỏ snapshot_date —
    thì test này đỏ vì bản tháng 9 sẽ ghi đè bản tháng 8.
    """
    upsert_shareholders(
        con, pd.DataFrame([_sh_row("Ông A", 0.25, "2026-08-01")])[SHAREHOLDER_COLS])
    upsert_shareholders(
        con, pd.DataFrame([_sh_row("Ông A", 0.18, "2026-09-01")])[SHAREHOLDER_COLS])

    rows = con.execute(
        "SELECT snapshot_date, share_own_percent FROM raw_shareholder "
        "WHERE share_holder = 'Ông A' ORDER BY snapshot_date"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == pytest.approx(0.25)
    assert rows[1][1] == pytest.approx(0.18)


def test_officer_giu_lich_su_qua_cac_snapshot(con):
    def row(pct, snap):
        return {"symbol": "AAA", "officer_name": "Bà B",
                "officer_position": "Chủ tịch HĐQT", "officer_own_percent": pct,
                "officer_own_quantity": 500.0, "update_date": "2026-07-01",
                "snapshot_date": snap}

    upsert_officers(con, pd.DataFrame([row(0.05, "2026-08-01")])[OFFICER_COLS])
    upsert_officers(con, pd.DataFrame([row(0.07, "2026-09-01")])[OFFICER_COLS])
    assert con.execute("SELECT count(*) FROM raw_officer").fetchone()[0] == 2
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_warehouse_events.py -q`
Expected: FAIL — `ImportError: cannot import name 'SHAREHOLDER_COLS' from 'src.warehouse'`

- [ ] **Step 3: Thêm hằng cột, DDL và 2 hàm upsert vào `src/warehouse.py`**

Thêm hằng ngay sau `EVENT_COLS`:

```python
# --- Cột raw_shareholder / raw_officer (nguồn: Company.shareholders/officers) ---
# snapshot_date do JOB gán (không có ở nguồn): hai bảng này là TRẠNG THÁI,
# không phải dòng sự kiện — xem docstring upsert_shareholders.
SHAREHOLDER_COLS = [
    "symbol", "share_holder", "quantity", "share_own_percent",
    "update_date", "snapshot_date",
]
OFFICER_COLS = [
    "symbol", "officer_name", "officer_position",
    "officer_own_percent", "officer_own_quantity",
    "update_date", "snapshot_date",
]
```

Thêm DDL ngay sau khối `raw_corporate_event` trong `init_warehouse`:

```python
    # --- B1: cơ cấu sở hữu (snapshot theo ngày) ---
    # snapshot_date nằm trong PRIMARY KEY: chạy lại trong cùng ngày thì thay
    # thế (idempotent), sang kỳ sau thì thêm bản ghi mới — giữ được lịch sử
    # thay đổi sở hữu. Xem docstring upsert_shareholders.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_shareholder (
            symbol            VARCHAR,
            share_holder      VARCHAR,
            quantity          DOUBLE,
            share_own_percent DOUBLE,
            update_date       DATE,
            snapshot_date     DATE,
            ingested_at       TIMESTAMP,
            PRIMARY KEY (symbol, share_holder, snapshot_date)
        );
        CREATE TABLE IF NOT EXISTS raw_officer (
            symbol               VARCHAR,
            officer_name         VARCHAR,
            officer_position     VARCHAR,
            officer_own_percent  DOUBLE,
            officer_own_quantity DOUBLE,
            update_date          DATE,
            snapshot_date        DATE,
            ingested_at          TIMESTAMP,
            PRIMARY KEY (symbol, officer_name, snapshot_date)
        );
        """
    )
```

Thêm 2 hàm ngay sau `insert_corporate_events`:

```python
def upsert_shareholders(con, df) -> int:
    """Ghi snapshot cơ cấu cổ đông. INSERT OR REPLACE theo
    (symbol, share_holder, snapshot_date) → chạy lại trong cùng ngày an toàn.

    KHÁC insert_corporate_events (append-only theo id): cổ đông là dữ liệu
    TRẠNG THÁI, không phải dòng sự kiện. Nguồn không có id ổn định, và thứ
    có giá trị là THAY ĐỔI theo thời gian ("quỹ ngoại giảm từ 8% xuống
    5%"). Cộng dồn không phân biệt được "cổ đông mới xuất hiện" với "cổ
    đông cũ đổi tỉ lệ"; snapshot theo ngày thì phân biệt được cả hai.
    """
    if df is None or df.empty:
        return 0
    cols = ", ".join(SHAREHOLDER_COLS)
    con.register("df_sh", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_shareholder ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_sh;
        """
    )
    con.unregister("df_sh")
    return len(df)


def upsert_officers(con, df) -> int:
    """Ghi snapshot ban lãnh đạo + tỉ lệ sở hữu. Cùng cơ chế snapshot như
    upsert_shareholders (xem docstring hàm đó)."""
    if df is None or df.empty:
        return 0
    cols = ", ".join(OFFICER_COLS)
    con.register("df_of", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_officer ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_of;
        """
    )
    con.unregister("df_of")
    return len(df)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_warehouse_events.py -q`
Expected: PASS — 8 passed

- [ ] **Step 5: Viết test thất bại cho normalize sở hữu**

Thêm vào cuối `tests/test_ingest_events.py`:

```python
from src.ingest_market import _normalize_officers, _normalize_shareholders
from src.warehouse import OFFICER_COLS, SHAREHOLDER_COLS


def test_normalize_shareholders_tra_dung_bo_cot_va_gan_snapshot():
    raw = pd.DataFrame([
        {"symbol": "HPG", "share_holder": "Trần Đình Long", "quantity": 1.6e9,
         "share_own_percent": 0.2580, "update_date": "2026-07-15"},
    ])
    out = _normalize_shareholders(raw, "HPG", "2026-08-01")
    assert list(out.columns) == SHAREHOLDER_COLS
    assert out.loc[0, "snapshot_date"] == "2026-08-01"
    assert out.loc[0, "share_own_percent"] == pytest.approx(0.2580)


def test_normalize_shareholders_khu_trung_ten_co_dong():
    """PRIMARY KEY (symbol, share_holder, snapshot_date) — nguồn trả trùng
    tên trong cùng mã sẽ ném ConstraintException giết cả job monthly. Khử
    trùng ngay ở normalize."""
    raw = pd.DataFrame([
        {"symbol": "HPG", "share_holder": "Ông A", "quantity": 1.0,
         "share_own_percent": 0.10, "update_date": "2026-07-15"},
        {"symbol": "HPG", "share_holder": "Ông A", "quantity": 2.0,
         "share_own_percent": 0.20, "update_date": "2026-07-15"},
    ])
    out = _normalize_shareholders(raw, "HPG", "2026-08-01")
    assert len(out) == 1


def test_normalize_officers_tra_dung_bo_cot():
    raw = pd.DataFrame([
        {"symbol": "HPG", "officer_name": "Trần Đình Long",
         "officer_position": "Chủ tịch HĐQT", "officer_own_percent": 0.2580,
         "officer_own_quantity": 1.6e9, "update_date": "2026-07-15"},
    ])
    out = _normalize_officers(raw, "HPG", "2026-08-01")
    assert list(out.columns) == OFFICER_COLS
    assert out.loc[0, "officer_position"] == "Chủ tịch HĐQT"


def test_normalize_shareholders_thieu_cot_bat_buoc_raise():
    raw = pd.DataFrame([{"symbol": "HPG", "quantity": 1.0}])
    with pytest.raises(dq.SchemaError):
        _normalize_shareholders(raw, "HPG", "2026-08-01")
```

- [ ] **Step 6: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_events.py -q`
Expected: FAIL — `ImportError: cannot import name '_normalize_shareholders'`

- [ ] **Step 7: Thêm 2 hàm fetch + 2 hàm normalize vào `src/ingest_market.py`**

Thêm vào cuối file:

```python
_printed_shareholder_cols = False
_printed_officer_cols = False

_SHAREHOLDER_REQUIRED = ["share_holder", "share_own_percent"]
_OFFICER_REQUIRED = ["officer_name", "officer_position"]


def fetch_shareholders(symbols: list[str], source: str = "VCI",
                       snapshot_date: str = None) -> pd.DataFrame:
    """Cơ cấu cổ đông đã công bố qua Company.shareholders().

    LƯU Ý về ngữ nghĩa dữ liệu (đo 2026-08-16): tổng share_own_percent
    KHÔNG bằng 100% — HPG 51,9% (66 dòng), VNM 81,0% (93), VCB 91,0% (29),
    và có cả dòng 0,0002%. Đây là danh sách cổ đông ĐÃ CÔNG BỐ ở nhiều quy
    mô, không phải chỉ cổ đông lớn >5%. Phần thiếu là cổ đông không công bố
    và KHÔNG đồng nghĩa free float (raw_company_info.free_float_percentage
    là con số khác, từ nguồn khác).

    snapshot_date do JOB gán, mặc định hôm nay — xem docstring
    warehouse.upsert_shareholders để biết vì sao bảng này snapshot theo
    ngày thay vì cộng dồn.
    """
    global _printed_shareholder_cols
    snap = snapshot_date or date.today().isoformat()
    frames, rejected = [], 0
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).shareholders()
        except Exception as e:
            print(f"[shareholders] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_shareholder_cols:
            print(f"[shareholders] cột thật ({symbol}): {list(df.columns)}")
            _printed_shareholder_cols = True
        try:
            frames.append(_normalize_shareholders(df, symbol, snap))
        except dq.SchemaError as e:
            print(f"[shareholders] {symbol}: {e}")
            rejected += 1
            continue
    if rejected and dq.status_for(len(frames), rejected) == "degraded":
        raise dq.SchemaError(
            f"[Company.shareholders] {rejected}/{len(symbols)} mã sai schema "
            "— nguồn có thể đã đổi"
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_shareholders(df, symbol, snapshot_date: str) -> pd.DataFrame:
    dq.assert_columns(df, _SHAREHOLDER_REQUIRED,
                      f"Company.shareholders({symbol})")
    out = pd.DataFrame({
        "symbol":            symbol.upper().strip(),
        "share_holder":      df["share_holder"].astype(str).str.strip(),
        "quantity":          (pd.to_numeric(df["quantity"], errors="coerce")
                              if "quantity" in df.columns else float("nan")),
        "share_own_percent": pd.to_numeric(df["share_own_percent"], errors="coerce"),
        "update_date":       _date_col(df, "update_date"),
        "snapshot_date":     snapshot_date,
    })
    # Khử trùng theo tên: PRIMARY KEY là (symbol, share_holder, snapshot_date),
    # nguồn trả trùng tên sẽ ném ConstraintException giết cả job monthly.
    out = out.drop_duplicates(subset=["symbol", "share_holder"])
    return out[warehouse.SHAREHOLDER_COLS].reset_index(drop=True)


def fetch_officers(symbols: list[str], source: str = "VCI",
                   snapshot_date: str = None) -> pd.DataFrame:
    """Ban lãnh đạo + tỉ lệ sở hữu qua Company.officers(). Cùng cơ chế
    snapshot như fetch_shareholders."""
    global _printed_officer_cols
    snap = snapshot_date or date.today().isoformat()
    frames, rejected = [], 0
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).officers()
        except Exception as e:
            print(f"[officers] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_officer_cols:
            print(f"[officers] cột thật ({symbol}): {list(df.columns)}")
            _printed_officer_cols = True
        try:
            frames.append(_normalize_officers(df, symbol, snap))
        except dq.SchemaError as e:
            print(f"[officers] {symbol}: {e}")
            rejected += 1
            continue
    if rejected and dq.status_for(len(frames), rejected) == "degraded":
        raise dq.SchemaError(
            f"[Company.officers] {rejected}/{len(symbols)} mã sai schema "
            "— nguồn có thể đã đổi"
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_officers(df, symbol, snapshot_date: str) -> pd.DataFrame:
    dq.assert_columns(df, _OFFICER_REQUIRED, f"Company.officers({symbol})")
    out = pd.DataFrame({
        "symbol":               symbol.upper().strip(),
        "officer_name":         df["officer_name"].astype(str).str.strip(),
        "officer_position":     df["officer_position"].astype(str).str.strip(),
        "officer_own_percent":  (pd.to_numeric(df["officer_own_percent"], errors="coerce")
                                 if "officer_own_percent" in df.columns else float("nan")),
        "officer_own_quantity": (pd.to_numeric(df["officer_own_quantity"], errors="coerce")
                                 if "officer_own_quantity" in df.columns else float("nan")),
        "update_date":          _date_col(df, "update_date"),
        "snapshot_date":        snapshot_date,
    })
    out = out.drop_duplicates(subset=["symbol", "officer_name"])
    return out[warehouse.OFFICER_COLS].reset_index(drop=True)
```

> **Không định nghĩa lại `_date_col`** — hàm này đã được thêm ở Task 2 Step 7 và dùng chung cho cả ba hàm normalize của B1.

- [ ] **Step 8: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_events.py tests/test_warehouse_events.py -q`
Expected: PASS — 18 passed

- [ ] **Step 9: Nối vào `build_warehouse.py`**

Chèn vào **cuối** khối `if args.mode == "monthly":` (sau đoạn `dim_symbols.exchange`):

```python
        print(f"Bắt đầu fetch cơ cấu sở hữu ({len(symbols)} mã)...")
        sh = ingest_market.fetch_shareholders(symbols, source, run_date)
        n_sh = warehouse.upsert_shareholders(con, sh)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_shareholder",
                           n_sh, "ok" if n_sh else "empty", watermark=run_date,
                           notes=f"snapshot {run_date}")
        print(f"raw_shareholder: {n_sh} dòng (snapshot {run_date})")

        of = ingest_market.fetch_officers(symbols, source, run_date)
        n_of = warehouse.upsert_officers(con, of)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_officer",
                           n_of, "ok" if n_of else "empty", watermark=run_date,
                           notes=f"snapshot {run_date}")
        print(f"raw_officer: {n_of} dòng (snapshot {run_date})")
```

- [ ] **Step 10: Khai báo 2 source mới cho dbt**

Trong `transforms/models/staging/_sources.yml`, thêm vào cuối `tables`:

```yaml
      - name: raw_shareholder
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 40, period: day}
          error_after: {count: 70, period: day}
      - name: raw_officer
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 40, period: day}
          error_after: {count: 70, period: day}
```

- [ ] **Step 11: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 231 passed, 2 xfailed

- [ ] **Step 12: Commit**

```bash
git add src/warehouse.py src/ingest_market.py build_warehouse.py \
        transforms/models/staging/_sources.yml \
        tests/test_warehouse_events.py tests/test_ingest_events.py
git commit -m "feat(b1): bảng raw_shareholder/raw_officer ghi snapshot theo ngày

Cổ đông là dữ liệu trạng thái, không phải dòng sự kiện: nguồn không có id
ổn định và thứ có giá trị là thay đổi theo thời gian. Snapshot theo ngày
phân biệt được 'cổ đông mới' với 'cổ đông cũ đổi tỉ lệ', cộng dồn thì không.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: `stg_corporate_event` — phân loại hai tầng + 2 dbt test

**Files:**
- Create: `transforms/models/staging/stg_corporate_event.sql`
- Create: `transforms/tests/assert_distribution_flag_only_three_types.sql`
- Create: `transforms/tests/assert_event_classification_coverage.sql`
- Modify: `transforms/models/staging/_staging.yml`

**Interfaces:**
- Consumes: `source('warehouse', 'raw_corporate_event')` (Task 2)
- Produces: model `stg_corporate_event` với các cột `id`, `symbol`, `event_code`, `event_name_vi`, `event_title_vi`, `category_source`, `action_type_vi`, `exercise_ratio`, `value_per_share`, 8 cột ngày, `ingested_at`, **`distribution_type` VARCHAR**, **`is_distribution` BOOLEAN**

> **Vì sao không dùng cột `category` của nguồn:** khảo sát 564 sự kiện / 12 mã (2026-08-16) cho thấy nguồn gán **toàn bộ** 33 dòng `ISS` vào `category = 'DIVIDEND'`, trong đó 9 dòng là "Phát hành cho CBCNV" (ESOP) và 5 dòng "Phát hành riêng lẻ" — hai loại này **pha loãng** cổ đông hiện hữu, tác động kinh tế **ngược dấu** với phân phối.

- [ ] **Step 1: Viết model `stg_corporate_event.sql`**

```sql
{{ config(materialized='view') }}

-- Phân loại HAI TẦNG: `event_code` (có cấu trúc, tin được) làm tầng chính;
-- chỉ đọc tiêu đề tự do cho nhánh ISS, nơi event_code KHÔNG đủ phân biệt.
--
-- VÌ SAO KHÔNG DÙNG CỘT `category` CỦA NGUỒN: khảo sát 564 sự kiện / 12 mã
-- (2026-08-16) cho thấy nguồn gán TOÀN BỘ 33 dòng ISS vào
-- category='DIVIDEND', trong đó 9 dòng là "Phát hành cho CBCNV" (ESOP) và
-- 5 dòng "Phát hành riêng lẻ". Hai loại này PHA LOÃNG cổ đông hiện hữu —
-- tác động kinh tế NGƯỢC DẤU với phân phối. Tin `category` là đếm pha loãng
-- thành cổ tức. Giữ nguyên cột nguồn dưới tên `category_source` để truy vết,
-- nhưng KHÔNG dùng nó để suy diễn gì.
--
-- Nguyên tắc fail-closed: không khớp mẫu nào thì gán nhãn "không biết"
-- (ISS_KHAC / UNKNOWN_CODE) và is_distribution = false. Không đoán.
with typed as (
    select
        id,
        symbol,
        event_code,
        event_name_vi,
        event_title_vi,
        category as category_source,
        action_type_vi,
        exercise_ratio,
        value_per_share,
        public_date,
        issue_date,
        start_date,
        end_date,
        record_date,
        exright_date,
        listing_date,
        payout_date,
        ingested_at,
        lower(coalesce(event_title_vi, '')) as _title
    from {{ source('warehouse', 'raw_corporate_event') }}
),

classified as (
    select
        *,
        case
            when event_code = 'DIV' then 'CASH_DIVIDEND'
            when event_code = 'ISS' and _title like '%cổ tức bằng cổ phiếu%'
                then 'STOCK_DIVIDEND'
            when event_code = 'ISS' and _title like '%cổ phiếu thưởng%'
                then 'BONUS_SHARE'
            when event_code = 'ISS' and (
                     _title like '%cbcnv%' or _title like '%cbnv%'
                     or _title like '%esop%')
                then 'ESOP'
            when event_code = 'ISS' and _title like '%riêng lẻ%'
                then 'PRIVATE_PLACEMENT'
            when event_code = 'ISS' then 'ISS_KHAC'
            when event_code in ('DDIND', 'DDINS', 'DDRP') then 'INSIDER_TRADING'
            when event_code in ('AGME', 'AGMR', 'EGME') then 'SHAREHOLDER_MEETING'
            when event_code in ('AIS', 'OTHE', 'MOVE', 'NLIS', 'SUSP') then 'OTHER'
            else 'UNKNOWN_CODE'
        end as distribution_type
    from typed
)

-- Suy diễn cờ ở SELECT NGOÀI, không cùng bậc với case sinh ra
-- distribution_type: bài học A2 (`pb_meaningful` viết cùng bậc với nullif
-- khiến alias phân giải về cột raw, 1.797 dòng sai).
select
    id,
    symbol,
    event_code,
    event_name_vi,
    event_title_vi,
    category_source,
    action_type_vi,
    exercise_ratio,
    value_per_share,
    public_date,
    issue_date,
    start_date,
    end_date,
    record_date,
    exright_date,
    listing_date,
    payout_date,
    ingested_at,
    distribution_type,
    distribution_type in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE')
        as is_distribution
from classified
```

- [ ] **Step 2: Viết test fail-closed**

Tạo `transforms/tests/assert_distribution_flag_only_three_types.sql`:

```sql
-- Global Constraint B1: is_distribution chỉ true cho đúng 3 loại. ESOP và
-- phát hành riêng lẻ (9 + 5 dòng trong mẫu khảo sát 12 mã) PHA LOÃNG cổ
-- đông hiện hữu — đếm chúng là phân phối thì sai ngược dấu. Test này canh
-- đúng chiều đó: bất kỳ dòng nào có cờ true mà loại nằm ngoài 3 giá trị
-- cho phép đều là lỗi.
select id, symbol, distribution_type, is_distribution
from {{ ref('stg_corporate_event') }}
where is_distribution
  and distribution_type not in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE')
```

Tạo `transforms/tests/assert_event_classification_coverage.sql`:

```sql
-- Canh parser xuống cấp âm thầm. Ngưỡng 5% chọn từ mẫu khảo sát thật:
-- 564 sự kiện / 12 mã (2026-08-16) cho 0 dòng chưa phân loại (33/33 ISS
-- khớp một trong bốn mẫu tiêu đề), nên 5% là biên rất rộng — vượt qua
-- nghĩa là nguồn đã đổi format thật, không phải nhiễu.
--
-- Mở mẫu từ 1 mã (HPG) lên 12 mã đã lộ thêm 5 event_code chưa từng thấy
-- (AGMR, EGME, MOVE, NLIS, SUSP), nên gặp code lạ là chuyện chắc chắn xảy
-- ra — nhánh UNKNOWN_CODE tồn tại để nuốt chúng an toàn, còn test này để
-- báo khi số lượng vượt mức chấp nhận được.
with tally as (
    select
        count(*) as n_total,
        count(*) filter (
            where distribution_type in ('ISS_KHAC', 'UNKNOWN_CODE')
        ) as n_unclassified
    from {{ ref('stg_corporate_event') }}
)
select
    n_total,
    n_unclassified,
    n_unclassified::double / nullif(n_total, 0) as pct_unclassified
from tally
where n_total > 0
  and n_unclassified::double / n_total > 0.05
```

- [ ] **Step 3: Khai báo test schema trong `_staging.yml`**

Thêm vào cuối danh sách `models`:

```yaml
  - name: stg_corporate_event
    description: >
      Sự kiện DN đã phân loại hai tầng. distribution_type dùng event_code
      làm tầng chính, chỉ đọc tiêu đề cho nhánh ISS. KHÔNG dùng cột
      category của nguồn (sai ở 14/33 dòng ISS — gán ESOP và phát hành
      riêng lẻ vào DIVIDEND).
    columns:
      - name: id
        tests: [not_null, unique]
      - name: symbol
        tests: [not_null]
      - name: distribution_type
        tests:
          - not_null
          - accepted_values:
              values: ['CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE',
                       'ESOP', 'PRIVATE_PLACEMENT', 'ISS_KHAC',
                       'INSIDER_TRADING', 'SHAREHOLDER_MEETING', 'OTHER',
                       'UNKNOWN_CODE']
      - name: is_distribution
        tests: [not_null]
```

- [ ] **Step 4: Chạy dbt build cho model mới + test**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse \
  --select stg_corporate_event+ \
  --vars '{}' 2>&1 | tail -20
```

Expected: PASS — model `stg_corporate_event` chạy được, 2 singular test + 4 schema test đều PASS.

> **Bẫy đã biết:** `--no-partial-parse` là **bắt buộc**. `target/partial_parse.msgpack` từng tạo GREEN GIẢ ngay sau RED ở cả A2 Task 2 lẫn Task 6 — test mới bị âm thầm loại khỏi `dbt list`.

- [ ] **Step 5: Kiểm phân bố phân loại trên dữ liệu thật**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print(con.execute('''
  select distribution_type, is_distribution, count(*) as n
  from stg_corporate_event group by 1,2 order by n desc
''').df().to_string(index=False))
"
```

Expected: `CASH_DIVIDEND` và `INSIDER_TRADING` chiếm phần lớn; `ISS_KHAC` + `UNKNOWN_CODE` cộng lại **dưới 5%**. Ghi bảng phân bố này vào báo cáo — nếu `UNKNOWN_CODE` cao bất thường, báo controller kèm danh sách `event_code` lạ.

- [ ] **Step 6: Commit**

```bash
git add transforms/models/staging/stg_corporate_event.sql \
        transforms/models/staging/_staging.yml \
        transforms/tests/assert_distribution_flag_only_three_types.sql \
        transforms/tests/assert_event_classification_coverage.sql
git commit -m "feat(b1): stg_corporate_event phân loại hai tầng, fail-closed

Cột category của nguồn sai ở 14/33 sự kiện ISS: gán ESOP (9) và phát hành
riêng lẻ (5) vào DIVIDEND, trong khi hai loại này pha loãng cổ đông hiện
hữu — ngược dấu với phân phối. Dùng event_code làm tầng chính, chỉ đọc
tiêu đề cho nhánh ISS, không khớp thì gán ISS_KHAC/UNKNOWN_CODE chứ không
đoán.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Staging sở hữu + 2 model intermediate + test đối chiếu chéo

**Files:**
- Create: `transforms/models/staging/stg_shareholder.sql`
- Create: `transforms/models/staging/stg_officer.sql`
- Create: `transforms/models/intermediate/int_distribution_event.sql`
- Create: `transforms/models/intermediate/int_ownership_snapshot.sql`
- Create: `transforms/tests/assert_cash_dividend_matches_ratio.sql`
- Modify: `transforms/models/staging/_staging.yml`
- Modify: `transforms/models/intermediate/_intermediate.yml`

**Interfaces:**
- Consumes: `stg_corporate_event` (Task 4), `source('warehouse', 'raw_shareholder')`, `source('warehouse', 'raw_officer')` (Task 3), `ref('stg_financial_ratio')` (đã có)
- Produces:
  - `stg_shareholder`: `symbol`, `share_holder`, `quantity`, `share_own_percent`, `update_date`, `snapshot_date`
  - `stg_officer`: `symbol`, `officer_name`, `officer_position`, `officer_own_percent`, `officer_own_quantity`, `update_date`, `snapshot_date`
  - `int_distribution_event`: `symbol`, `event_id`, `exright_date`, `record_date`, `payout_date`, `distribution_type`, `cash_per_share`, `stock_ratio`, `event_title_vi`
  - `int_ownership_snapshot`: `symbol`, `snapshot_date`, `n_disclosed`, `total_disclosed_pct`, `top1_pct`, `top5_pct`, `insider_pct`

- [ ] **Step 1: Viết `stg_shareholder.sql`**

```sql
{{ config(materialized='view') }}

-- Cổ đông ĐÃ CÔNG BỐ, snapshot theo ngày.
--
-- NGỮ NGHĨA QUAN TRỌNG (đo 2026-08-16): tổng share_own_percent KHÔNG bằng
-- 100% — HPG 51,9% (66 dòng), VNM 81,0% (93), VCB 91,0% (29). Đây là danh
-- sách cổ đông đã công bố ở nhiều quy mô (có cả dòng 0,0002%), không phải
-- chỉ cổ đông lớn >5%. Phần thiếu là cổ đông không công bố và KHÔNG đồng
-- nghĩa free float — dim_stock.free_float_percentage là con số khác, từ
-- nguồn khác. Mọi tầng dùng bảng này phải phơi total_disclosed_pct chứ
-- không để người đọc tự suy ra "100% trừ đi".
select
    symbol,
    share_holder,
    quantity,
    share_own_percent,
    update_date,
    snapshot_date
from {{ source('warehouse', 'raw_shareholder') }}
where share_holder is not null
```

- [ ] **Step 2: Viết `stg_officer.sql`**

```sql
{{ config(materialized='view') }}

-- Ban lãnh đạo + tỉ lệ sở hữu, snapshot theo ngày. Cùng cảnh báo ngữ nghĩa
-- như stg_shareholder: đây là phần ĐÃ CÔNG BỐ, không phải toàn bộ.
select
    symbol,
    officer_name,
    officer_position,
    officer_own_percent,
    officer_own_quantity,
    update_date,
    snapshot_date
from {{ source('warehouse', 'raw_officer') }}
where officer_name is not null
```

- [ ] **Step 3: Viết `int_distribution_event.sql`**

```sql
{{ config(materialized='table') }}

-- CHỈ sự kiện phân phối cho cổ đông (is_distribution = true).
--
-- ESOP và PRIVATE_PLACEMENT bị loại ở đây nhưng VẪN nằm trong
-- stg_corporate_event — mảng C sẽ cần chúng để cảnh báo ("sắp phát hành
-- riêng lẻ" là tin đáng quan tâm, chỉ là không phải cổ tức).
--
-- Trục thời gian của model này là NGÀY GDKHQ (exright_date), KHÁC trục năm
-- tài chính của dividend_yield trong stg_financial_ratio: cổ tức "cả năm
-- 2021" của HPG chi trả ngày 17/06/2022. Không được cộng gộp hai trục.
select
    symbol,
    id as event_id,
    exright_date,
    record_date,
    payout_date,
    distribution_type,
    -- cash_per_share chỉ có nghĩa với cổ tức TIỀN MẶT. Cổ tức bằng cổ phiếu
    -- và cổ phiếu thưởng luôn NULL value_per_share ở nguồn (xác minh HPG:
    -- cả 4 sự kiện ISS đều value_per_share = NaN), nên gán NULL tường minh
    -- thay vì để lọt giá trị vô nghĩa.
    case when distribution_type = 'CASH_DIVIDEND'
         then value_per_share end as cash_per_share,
    -- stock_ratio chỉ có nghĩa với hai loại trả bằng cổ phiếu.
    case when distribution_type in ('STOCK_DIVIDEND', 'BONUS_SHARE')
         then exercise_ratio end as stock_ratio,
    event_title_vi
from {{ ref('stg_corporate_event') }}
where is_distribution
  and exright_date is not null
```

- [ ] **Step 4: Viết `int_ownership_snapshot.sql`**

```sql
{{ config(materialized='table') }}

-- Cô đặc cơ cấu sở hữu theo snapshot MỚI NHẤT mỗi mã.
--
-- total_disclosed_pct là cột BẮT BUỘC, không phải tuỳ chọn: tổng % công bố
-- không bằng 100% (HPG 51,9%, VNM 81,0%, VCB 91,0% — đo 2026-08-16), nên
-- nếu chỉ phơi top1/top5 mà giấu tổng thì người đọc rất dễ suy ra sai
-- "phần còn lại là free float". Đây đúng pattern "một con số cần được phơi
-- kèm bằng chứng đỡ nó" đã dùng bốn lần ở A2 (pe_quarters_used, n_pe,
-- *_weight_coverage, rejected_total).
with sh_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_shareholder') }}
    group by 1
),

sh as (
    select s.*
    from {{ ref('stg_shareholder') }} s
    join sh_latest l
      on s.symbol = l.symbol and s.snapshot_date = l.snapshot_date
),

ranked as (
    select
        *,
        row_number() over (
            partition by symbol order by share_own_percent desc nulls last
        ) as rn
    from sh
),

sh_agg as (
    select
        symbol,
        max(snapshot_date) as snapshot_date,
        count(*) as n_disclosed,
        sum(share_own_percent) as total_disclosed_pct,
        max(case when rn = 1 then share_own_percent end) as top1_pct,
        sum(case when rn <= 5 then share_own_percent end) as top5_pct
    from ranked
    group by 1
),

of_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_officer') }}
    group by 1
),

of_agg as (
    select
        o.symbol,
        sum(o.officer_own_percent) as insider_pct
    from {{ ref('stg_officer') }} o
    join of_latest l
      on o.symbol = l.symbol and o.snapshot_date = l.snapshot_date
    group by 1
)

select
    a.symbol,
    a.snapshot_date,
    a.n_disclosed,
    a.total_disclosed_pct,
    a.top1_pct,
    a.top5_pct,
    o.insider_pct
from sh_agg a
left join of_agg o on a.symbol = o.symbol
```

- [ ] **Step 5: Viết test đối chiếu chéo hai nguồn cổ tức**

Tạo `transforms/tests/assert_cash_dividend_matches_ratio.sql`:

```sql
-- Đối chiếu chéo HAI NGUỒN cổ tức tiền mặt độc lập nhau:
--   (1) stg_financial_ratio.dividend_yield (quarter=5) — theo NĂM TÀI CHÍNH
--   (2) int_distribution_event CASH_DIVIDEND     — theo NGÀY GDKHQ
--
-- Hai nguồn nằm trên hai trục thời gian nên KHÔNG so trực tiếp từng năm
-- được. Thứ so được là mệnh đề yếu hơn nhưng vẫn có giá trị: một mã có ÍT
-- NHẤT MỘT sự kiện cổ tức tiền mặt trong cửa sổ sự kiện thì PHẢI có ít nhất
-- một năm dividend_yield > 0 trong cùng khoảng thời gian đó (cộng đệm 1 năm
-- cho độ trễ chi trả — cổ tức "cả năm 2021" của HPG chi trả 17/06/2022).
--
-- Ngược lại KHÔNG đúng và cố ý không kiểm: dividend_yield > 0 mà không có
-- sự kiện là chuyện bình thường khi cửa sổ 50 sự kiện quá nông (VNM chỉ phủ
-- 1,5 năm trong khi dividend_yield có từ 2018).
with ev as (
    select
        symbol,
        min(year(exright_date)) as min_ev_year,
        max(year(exright_date)) as max_ev_year,
        count(*) as n_cash_events
    from {{ ref('int_distribution_event') }}
    where distribution_type = 'CASH_DIVIDEND'
    group by 1
),

ratio as (
    select symbol, year, dividend_yield
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5
)

select
    e.symbol,
    e.n_cash_events,
    e.min_ev_year,
    e.max_ev_year
from ev e
where e.n_cash_events > 0
  and not exists (
      select 1 from ratio r
      where r.symbol = e.symbol
        and r.dividend_yield > 0
        and r.year between e.min_ev_year - 1 and e.max_ev_year
  )
```

- [ ] **Step 6: Khai báo test schema**

Thêm vào cuối `models` của `transforms/models/staging/_staging.yml`:

```yaml
  - name: stg_shareholder
    description: >
      Cổ đông ĐÃ CÔNG BỐ, snapshot theo ngày. Tổng share_own_percent KHÔNG
      bằng 100% (HPG 51,9%, VNM 81,0%, VCB 91,0%) — phần thiếu là cổ đông
      không công bố, KHÔNG đồng nghĩa free float.
    columns:
      - name: symbol
        tests: [not_null]
      - name: share_holder
        tests: [not_null]
      - name: snapshot_date
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, share_holder, snapshot_date]

  - name: stg_officer
    columns:
      - name: symbol
        tests: [not_null]
      - name: officer_name
        tests: [not_null]
      - name: snapshot_date
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, officer_name, snapshot_date]
```

Thêm vào cuối `models` của `transforms/models/intermediate/_intermediate.yml`:

```yaml
  - name: int_distribution_event
    description: >
      Chỉ sự kiện PHÂN PHỐI cho cổ đông (tiền mặt, cổ tức cổ phiếu, cổ
      phiếu thưởng). Trục thời gian là NGÀY GDKHQ, khác trục năm tài chính
      của dividend_yield — không cộng gộp hai trục.
    columns:
      - name: symbol
        tests: [not_null]
      - name: event_id
        tests: [not_null, unique]
      - name: exright_date
        tests: [not_null]
      - name: distribution_type
        tests:
          - not_null
          - accepted_values:
              values: ['CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE']

  - name: int_ownership_snapshot
    description: >
      Cô đặc sở hữu theo snapshot mới nhất. total_disclosed_pct là cột bắt
      buộc — tổng % công bố không bằng 100%, giấu nó đi thì người đọc suy
      ra sai "phần còn lại là free float".
    columns:
      - name: symbol
        tests: [not_null, unique]
      - name: snapshot_date
        tests: [not_null]
      - name: total_disclosed_pct
        tests: [not_null]
```

- [ ] **Step 7: Chạy dbt build**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse \
  --select stg_shareholder stg_officer int_distribution_event int_ownership_snapshot \
  2>&1 | tail -25
```

Expected: PASS — 4 model + toàn bộ schema test.

- [ ] **Step 8: Chạy riêng test đối chiếu chéo**

```bash
cd transforms
dbt test --profiles-dir . --no-partial-parse \
  --select assert_cash_dividend_matches_ratio 2>&1 | tail -10
```

Expected: PASS. Nếu FAIL, in danh sách mã lệch và **báo controller** — đây là tín hiệu hai nguồn thật sự mâu thuẫn, không phải lỗi code, và cần điều tra trước khi đi tiếp.

- [ ] **Step 9: Chạy toàn bộ dbt build để chắc không hỏng gì**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse 2>&1 | tail -15
```

Expected: PASS, ERROR=0. Số node tăng đúng 4 model + 3 singular test mới so với trước B1.

- [ ] **Step 10: Commit**

```bash
git add transforms/models/staging/stg_shareholder.sql \
        transforms/models/staging/stg_officer.sql \
        transforms/models/staging/_staging.yml \
        transforms/models/intermediate/int_distribution_event.sql \
        transforms/models/intermediate/int_ownership_snapshot.sql \
        transforms/models/intermediate/_intermediate.yml \
        transforms/tests/assert_cash_dividend_matches_ratio.sql
git commit -m "feat(b1): staging sở hữu + int phân phối/sở hữu + đối chiếu chéo cổ tức

int_ownership_snapshot phơi total_disclosed_pct làm cột bắt buộc: tổng %
cổ đông công bố không bằng 100% (HPG 51,9%), giấu đi thì người đọc suy ra
sai 'phần còn lại là free float'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Hai tool MCP

**Files:**
- Modify: `mcp_server/tools.py` (thêm `get_distribution_history`, `get_ownership`)
- Modify: `mcp_server/server.py` (đăng ký 2 tool)
- Modify: `tests/conftest_mart.py` (thêm 4 bảng giả)
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp_server.db.run_query`, `mcp_server.db.as_of`, `mcp_server.tools._clean`, `mcp_server.tools._date_str`, model `int_distribution_event` + `int_ownership_snapshot` + `stg_financial_ratio` + `stg_shareholder` + `stg_officer`
- Produces:
  - `tools.get_distribution_history(con, symbol: str, years: int = 5) -> dict`
  - `tools.get_ownership(con, symbol: str) -> dict`

- [ ] **Step 1: Mở rộng fixture `tests/conftest_mart.py`**

Thêm vào cuối hàm `build_fake_mart`, ngay trước `con.close()`:

```python
    # --- B1: sự kiện phân phối + sở hữu ---
    # Fixture phải khớp schema thật (bài học A3 I2: fixture thiếu 3 cột
    # n_pe/n_pb/n_roe khiến lỗi lọt qua 4 task). Giá trị cố tình đặt
    # total_disclosed_pct < 1.0 để mô phỏng đúng ca thật (HPG 51,9%).
    con.execute("""
        CREATE TABLE int_distribution_event (
            symbol VARCHAR, event_id VARCHAR, exright_date DATE,
            record_date DATE, payout_date DATE, distribution_type VARCHAR,
            cash_per_share DOUBLE, stock_ratio DOUBLE, event_title_vi VARCHAR
        );
        INSERT INTO int_distribution_event VALUES
          ('AAA','e1',DATE '2026-05-11',DATE '2026-05-12',DATE '2026-06-30',
           'CASH_DIVIDEND',500.0,NULL,'Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND'),
          ('AAA','e2',DATE '2026-05-25',DATE '2026-05-26',NULL,
           'STOCK_DIVIDEND',NULL,0.10,'Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%'),
          ('AAA','e3',DATE '2022-06-17',DATE '2022-06-18',NULL,
           'BONUS_SHARE',NULL,0.30,'Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 30.0%');
        CREATE TABLE int_ownership_snapshot (
            symbol VARCHAR, snapshot_date DATE, n_disclosed BIGINT,
            total_disclosed_pct DOUBLE, top1_pct DOUBLE, top5_pct DOUBLE,
            insider_pct DOUBLE
        );
        INSERT INTO int_ownership_snapshot VALUES
          ('AAA',DATE '2026-08-01',66,0.5189,0.2580,0.3872,0.3105),
          ('VCB',DATE '2026-08-01',29,0.9101,0.7480,0.9096,0.0002);
        CREATE TABLE stg_shareholder (
            symbol VARCHAR, share_holder VARCHAR, quantity DOUBLE,
            share_own_percent DOUBLE, update_date DATE, snapshot_date DATE
        );
        INSERT INTO stg_shareholder VALUES
          ('AAA','Ông Nguyễn Văn A',1.6e9,0.2580,DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Bà Trần Thị B',4.2e8,0.0688,DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Quỹ ngoại C',1.7e8,0.0273,DATE '2026-07-15',DATE '2026-08-01');
        CREATE TABLE stg_officer (
            symbol VARCHAR, officer_name VARCHAR, officer_position VARCHAR,
            officer_own_percent DOUBLE, officer_own_quantity DOUBLE,
            update_date DATE, snapshot_date DATE
        );
        INSERT INTO stg_officer VALUES
          ('AAA','Ông Nguyễn Văn A','Chủ tịch HĐQT',0.2580,1.6e9,
           DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Bà Trần Thị B','Thành viên HĐQT',0.0525,3.2e8,
           DATE '2026-07-15',DATE '2026-08-01');
        CREATE TABLE stg_financial_ratio (
            symbol VARCHAR, year INTEGER, quarter INTEGER,
            dividend_yield DOUBLE
        );
        INSERT INTO stg_financial_ratio VALUES
          ('AAA',2025,5,0.0235),
          ('AAA',2024,5,0.0),
          ('AAA',2023,5,0.0),
          ('AAA',2022,5,0.0),
          ('AAA',2021,5,0.0278);
    """)
```

- [ ] **Step 2: Viết test thất bại**

Thêm vào cuối `tests/test_mcp_tools.py`:

```python
def test_get_distribution_history_tra_hai_khoi_tach_bach(con):
    """Hướng A của spec: KHÔNG ép ghép hai trục thời gian.

    dividend_yield gán theo NĂM TÀI CHÍNH, sự kiện gán theo NGÀY GDKHQ —
    cổ tức 'cả năm 2021' của HPG chi trả 17/06/2022. Trả hai khối riêng,
    mỗi khối ghi rõ trục của nó.
    """
    res = tools.get_distribution_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert "cash_dividend_by_fiscal_year" in res
    assert "distribution_events" in res
    assert len(res["distribution_events"]) == 3
    assert "KHÔNG cộng gộp" in res["note"]


def test_get_distribution_history_phan_biet_tien_mat_va_co_phieu(con):
    res = tools.get_distribution_history(con, "AAA", years=5)
    by_type = {e["distribution_type"]: e for e in res["distribution_events"]}
    assert by_type["CASH_DIVIDEND"]["cash_per_share"] == 500.0
    assert by_type["CASH_DIVIDEND"]["stock_ratio"] is None
    assert by_type["STOCK_DIVIDEND"]["stock_ratio"] == 0.10
    assert by_type["STOCK_DIVIDEND"]["cash_per_share"] is None


def test_get_distribution_history_phoi_do_sau_cua_so(con):
    """event_window_years là trường BẮT BUỘC — chính con số này phân biệt
    'VNM mới trả cổ tức 3 năm nay' (sai) với 'cửa sổ chỉ nhìn được 1,5 năm'
    (đúng)."""
    res = tools.get_distribution_history(con, "AAA", years=5)
    dq_block = res["data_quality"]
    assert "event_window_years" in dq_block
    assert "event_window_start" in dq_block
    assert dq_block["n_events"] == 3


def test_get_distribution_history_ngay_dung_dinh_dang_iso(con):
    """Bài học A3: cột DATE qua .df() thành Timestamp, isoformat() ra kèm
    'T00:00:00'."""
    res = tools.get_distribution_history(con, "AAA", years=5)
    assert res["distribution_events"][0]["exright_date"] == "2026-05-25"


def test_get_distribution_history_ma_khong_ton_tai(con):
    res = tools.get_distribution_history(con, "ZZZ", years=5)
    assert "error" in res
    assert "ZZZ" in res["error"]


def test_get_ownership_tra_co_dong_va_ban_lanh_dao(con):
    res = tools.get_ownership(con, "AAA")
    assert res["symbol"] == "AAA"
    assert len(res["major_shareholders"]) == 3
    assert res["major_shareholders"][0]["percent"] == 0.2580
    assert len(res["officers"]) == 2
    assert res["snapshot_date"] == "2026-08-01"


def test_get_ownership_phoi_tong_phan_tram_cong_bo(con):
    """total_disclosed_pct phải hiện rõ: tổng KHÔNG bằng 100%, giấu đi thì
    agent suy ra sai 'phần còn lại là free float'."""
    res = tools.get_ownership(con, "AAA")
    assert res["concentration"]["total_disclosed_pct"] == 0.5189
    assert res["concentration"]["n_disclosed"] == 66
    assert "free float" in res["note"]


def test_get_ownership_ma_khong_ton_tai(con):
    res = tools.get_ownership(con, "ZZZ")
    assert "error" in res
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL — `AttributeError: module 'mcp_server.tools' has no attribute 'get_distribution_history'`

- [ ] **Step 4: Thêm 2 hàm vào `mcp_server/tools.py`**

Thêm vào cuối file:

```python
def get_distribution_history(con, symbol: str, years: int = 5) -> dict:
    """Lịch sử phân phối cho cổ đông — HAI KHỐI trên HAI TRỤC THỜI GIAN.

    Cố ý KHÔNG ghép hai khối (hướng A của spec B1). `dividend_yield` gán
    theo NĂM TÀI CHÍNH; sự kiện gán theo NGÀY GDKHQ — cổ tức "cả năm 2021"
    của HPG chi trả ngày 17/06/2022. Ghép được cho cổ tức tiền mặt nhưng
    KHÔNG ghép được cho cổ tức bằng cổ phiếu (tiêu đề nguồn không ghi kỳ
    nào: "Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%") — tức đúng phần dữ liệu
    mới mà B1 sinh ra để lấy. Nên trả tách bạch, ghi rõ trục, để agent tự
    diễn giải.
    """
    sym = symbol.upper().strip()

    events = db.run_query(
        con,
        """
        SELECT event_id, exright_date, record_date, payout_date,
               distribution_type, cash_per_share, stock_ratio, event_title_vi
        FROM int_distribution_event
        WHERE symbol = ?
        ORDER BY exright_date DESC
        """,
        params=[sym],
        limit=4 * years + 20,
    )
    cash_year = db.run_query(
        con,
        """
        SELECT year, dividend_yield
        FROM stg_financial_ratio
        WHERE symbol = ? AND quarter = 5
        ORDER BY year DESC
        """,
        params=[sym],
        limit=years,
    )

    if not events and not cash_year:
        return {"error": f"Không có dữ liệu phân phối cho {sym}.", **db.as_of(con)}

    for r in events:
        for col in ("exright_date", "record_date", "payout_date"):
            r[col] = _date_str(r.get(col))

    window_start = min((r["exright_date"] for r in events if r["exright_date"]),
                       default=None)
    window_end = max((r["exright_date"] for r in events if r["exright_date"]),
                     default=None)
    window_years = None
    if window_start and window_end:
        window_years = round(
            (date.fromisoformat(window_end) - date.fromisoformat(window_start)).days / 365,
            1,
        )

    return {
        "symbol": sym,
        "cash_dividend_by_fiscal_year": _clean(cash_year),
        "distribution_events": _clean(events),
        "note": "Hai khối nằm trên HAI TRỤC THỜI GIAN khác nhau: "
                "cash_dividend_by_fiscal_year theo NĂM TÀI CHÍNH, "
                "distribution_events theo NGÀY GDKHQ (cổ tức 'cả năm 2021' "
                "chi trả 17/06/2022). KHÔNG cộng gộp hai khối.",
        # event_window_years là bằng chứng đỡ cho mọi phát biểu về chuỗi cổ
        # tức. Nguồn chỉ trả 50 sự kiện gần nhất và cửa sổ đó trượt: đo trên
        # 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm (MWG) tới 9,9 năm
        # (AGX). Không phơi con số này thì agent nhìn VNM thấy 3 sự kiện cổ
        # tức rồi kết luận "VNM mới trả cổ tức 3 năm gần đây", trong khi sự
        # thật là cửa sổ chỉ nhìn được 1,5 năm.
        "data_quality": {
            "event_window_start": window_start,
            "event_window_end": window_end,
            "event_window_years": window_years,
            "n_events": len(events),
        },
        **db.as_of(con),
    }


def get_ownership(con, symbol: str) -> dict:
    """Cơ cấu sở hữu đã công bố: cổ đông lớn, ban lãnh đạo, mức độ cô đặc."""
    sym = symbol.upper().strip()

    conc_rows = db.run_query(
        con,
        """
        SELECT snapshot_date, n_disclosed, total_disclosed_pct,
               top1_pct, top5_pct, insider_pct
        FROM int_ownership_snapshot
        WHERE symbol = ?
        """,
        params=[sym],
        limit=1,
    )
    if not conc_rows:
        return {"error": f"Không có dữ liệu sở hữu cho {sym}.", **db.as_of(con)}

    conc = conc_rows[0]
    snapshot_date = _date_str(conc.get("snapshot_date"))

    holders = db.run_query(
        con,
        """
        SELECT share_holder, quantity, share_own_percent
        FROM stg_shareholder
        WHERE symbol = ? AND snapshot_date = ?
        ORDER BY share_own_percent DESC NULLS LAST
        """,
        params=[sym, snapshot_date],
        limit=200,
    )
    officers = db.run_query(
        con,
        """
        SELECT officer_name, officer_position,
               officer_own_percent, officer_own_quantity
        FROM stg_officer
        WHERE symbol = ? AND snapshot_date = ?
        ORDER BY officer_own_percent DESC NULLS LAST
        """,
        params=[sym, snapshot_date],
        limit=100,
    )

    return {
        "symbol": sym,
        "major_shareholders": [
            {"name": h["share_holder"], "quantity": h["quantity"],
             "percent": h["share_own_percent"]}
            for h in _clean(holders)
        ],
        "officers": [
            {"name": o["officer_name"], "position": o["officer_position"],
             "own_percent": o["officer_own_percent"],
             "own_quantity": o["officer_own_quantity"]}
            for o in _clean(officers)
        ],
        "concentration": {
            "top1_pct": _clean(conc.get("top1_pct")),
            "top5_pct": _clean(conc.get("top5_pct")),
            "n_disclosed": _clean(conc.get("n_disclosed")),
            "total_disclosed_pct": _clean(conc.get("total_disclosed_pct")),
            "insider_pct": _clean(conc.get("insider_pct")),
        },
        "snapshot_date": snapshot_date,
        # Cảnh báo này bắt buộc: đo 2026-08-16, tổng % công bố là HPG 51,9%,
        # VNM 81,0%, VCB 91,0% — không phải 100%. Không nói rõ thì agent rất
        # dễ lấy 100% trừ đi rồi gọi phần dư là free float, trong khi
        # dim_stock.free_float_percentage là con số khác từ nguồn khác.
        "note": "Chỉ gồm cổ đông ĐÃ CÔNG BỐ — tổng total_disclosed_pct KHÔNG "
                "bằng 100%. Phần còn lại là cổ đông không công bố, KHÔNG đồng "
                "nghĩa free float (dùng get_stock_profile để lấy free float "
                "từ nguồn riêng).",
        **db.as_of(con),
    }
```

Thêm import `date` vào đầu file (`mcp_server/tools.py` hiện chỉ import `json`, `pandas as pd`):

```python
from datetime import date
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: PASS — 20 passed (12 cũ + 8 mới)

- [ ] **Step 6: Đăng ký 2 tool trong `mcp_server/server.py`**

Thêm vào cuối file, trước khối `if __name__ == "__main__":`:

```python
@mcp.tool()
@_safe_tool
def get_distribution_history(symbol: str, years: int = 5) -> dict:
    """Lịch sử phân phối cho cổ đông: cổ tức tiền mặt, cổ tức bằng cổ phiếu,
    cổ phiếu thưởng, kèm ngày giao dịch không hưởng quyền (GDKHQ).

    Trả HAI KHỐI trên HAI TRỤC THỜI GIAN khác nhau — đọc kỹ trường 'note'
    trước khi phát biểu. Luôn nêu data_quality.event_window_years khi nói về
    chuỗi cổ tức: nguồn chỉ nhìn được 50 sự kiện gần nhất, với mã năng động
    cửa sổ đó có thể chỉ 1-2 năm dù doanh nghiệp trả cổ tức đều hàng chục năm.
    """
    return tools.get_distribution_history(conn(), symbol, years)


@mcp.tool()
@_safe_tool
def get_ownership(symbol: str) -> dict:
    """Cơ cấu sở hữu đã công bố: cổ đông lớn, ban lãnh đạo, mức độ cô đặc.

    Tổng tỉ lệ công bố KHÔNG bằng 100% — không suy ra phần còn lại là free
    float.
    """
    return tools.get_ownership(conn(), symbol)
```

- [ ] **Step 7: Viết test qua `mcp.call_tool()` thật**

Thêm vào cuối `tests/test_mcp_server.py`:

```python
from tests.conftest_mart import build_fake_mart


@pytest.fixture
def b1_con(tmp_path):
    """Kết nối có đủ 4 bảng B1 + bảng mart tối thiểu cho as_of().

    CỐ Ý KHÔNG dùng fixture `full_con` sẵn có: nó chỉ dựng fct_price_daily,
    fct_financial_quarterly và bảng t — không có int_distribution_event hay
    int_ownership_snapshot. Tool gọi trên đó sẽ ném "table not found",
    _safe_tool nuốt thành {"error": ...}, và một assertion lỏng kiểu
    `assert content is not None` VẪN XANH — tức test không bao giờ đỏ được,
    đúng lỗi "test không thể đỏ" của A2 Task 11. Dùng build_fake_mart để
    fixture khớp schema thật (bài học A3 I2).
    """
    path = str(tmp_path / "b1.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path)
    yield c
    c.close()


def test_get_ownership_via_mcp_call_tool(b1_con, monkeypatch):
    """Bài học A3 I1: crash ở tầng serialize JSON của FastMCP xảy ra SAU khi
    hàm đã return, nên _safe_tool không bắt được và test gọi hàm Python trần
    không thấy. Phải gọi đúng qua mcp.call_tool().
    """
    monkeypatch.setattr(server, "conn", lambda: b1_con)

    content = asyncio.run(
        server.mcp.call_tool("get_ownership", {"symbol": "AAA"})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert payload["symbol"] == "AAA"
    assert len(payload["major_shareholders"]) == 3
    assert payload["concentration"]["total_disclosed_pct"] == 0.5189
    assert payload["snapshot_date"] == "2026-08-01"


def test_get_distribution_history_via_mcp_call_tool(b1_con, monkeypatch):
    """Cùng lý do như trên. Fixture cố tình có `payout_date` NULL thật (cổ
    tức bằng cổ phiếu không có ngày chi trả) và `cash_per_share` NULL —
    đúng loại giá trị làm serialize vỡ nếu không đi qua _clean/_date_str.
    """
    monkeypatch.setattr(server, "conn", lambda: b1_con)

    content = asyncio.run(
        server.mcp.call_tool("get_distribution_history",
                             {"symbol": "AAA", "years": 5})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert len(payload["distribution_events"]) == 3
    # NULL phải ra None, KHÔNG phải chuỗi "NaT" hay "NaN"
    stock_div = next(e for e in payload["distribution_events"]
                     if e["distribution_type"] == "STOCK_DIVIDEND")
    assert stock_div["cash_per_share"] is None
    assert stock_div["payout_date"] is None
    assert payload["data_quality"]["n_events"] == 3
```

> **Lưu ý cho implementer:** `monkeypatch.setattr(server, "conn", lambda: b1_con)` — patch hàm `conn`, **không** patch biến `_CON`. Đây là cách test A3 hiện có làm (`test_run_sql_via_mcp_call_tool_handles_null_date_column`); patch `_CON` không có tác dụng vì `conn()` chỉ đọc `_CON` khi nó là `None`. Kiểm `json` và `pytest` đã được import ở đầu file, thêm nếu thiếu.

- [ ] **Step 8: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 241 passed, 2 xfailed

- [ ] **Step 9: Commit**

```bash
git add mcp_server/tools.py mcp_server/server.py \
        tests/conftest_mart.py tests/test_mcp_tools.py tests/test_mcp_server.py
git commit -m "feat(b1): tool get_distribution_history và get_ownership

get_distribution_history trả hai khối tách bạch thay vì ép ghép: cổ tức
bằng cổ phiếu không có thông tin kỳ nào trong tiêu đề nguồn nên không quy
về năm tài chính được. data_quality.event_window_years là trường bắt buộc
— không có nó agent kết luận sai về độ dài chuỗi cổ tức.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Nghiệm thu đầu-cuối trên dữ liệu thật

**Files:**
- Modify: `scripts/check_mcp_tools.py`
- Modify: `README.md`
- Modify: `.github/workflows/warehouse-weekly.yml` (không đổi lệnh, chỉ ghi chú thời lượng)

**Interfaces:**
- Consumes: toàn bộ Task 1–6.
- Produces: bằng chứng cho 8 tiêu chí hoàn thành trong spec §9.

- [ ] **Step 1: Mở rộng script nghiệm thu**

Trong `scripts/check_mcp_tools.py`, thêm 2 dòng vào hàm `main()` ngay sau dòng `get_sector_snapshot`:

```python
    ok &= show("get_distribution_history(HPG)",
               tools.get_distribution_history(con, "HPG", years=5))
    ok &= show("get_ownership(HPG)", tools.get_ownership(con, "HPG"))
```

- [ ] **Step 2: Chạy ingest thật lần 1 trên production**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
export VNSTOCK_MIN_INTERVAL=1.05
.venv/bin/python build_warehouse.py --mode monthly
```

Expected: chạy ~85 phút (giá + ratios + company_info + events + shareholders + officers). In ra số dòng cho `raw_corporate_event`, `raw_shareholder`, `raw_officer`.

> Ghi lại số dòng của cả 3 bảng — Step 4 cần để đối chiếu.

- [ ] **Step 3: Chạy dbt build toàn bộ**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse 2>&1 | tail -20
```

Expected: PASS, ERROR=0.

- [ ] **Step 4: Chạy ingest lần 2, kiểm append-only và snapshot**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python build_warehouse.py --mode weekly
```

Rồi kiểm:

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print('raw_corporate_event:', con.execute('select count(*) from raw_corporate_event').fetchone()[0])
print('số snapshot_date của raw_shareholder:',
      con.execute('select count(distinct snapshot_date) from raw_shareholder').fetchone()[0])
print()
print('phân bố phân loại:')
print(con.execute('''
  select distribution_type, count(*) n from stg_corporate_event
  group by 1 order by n desc
''').df().to_string(index=False))
"
```

Expected: số dòng `raw_corporate_event` **≥** lần 1 (không giảm — đây là tiêu chí #4). `ISS_KHAC + UNKNOWN_CODE` dưới 5% tổng.

- [ ] **Step 5: Nghiệm thu 9 tool trên dữ liệu thật**

```bash
.venv/bin/python -m scripts.check_mcp_tools
```

Expected: `TẤT CẢ ĐẠT`, exit code 0, cả 9 tool trả dữ liệu (7 cũ + 2 mới).

- [ ] **Step 6: Kiểm tiêu chí #8 — điểm số KHÔNG đổi**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print(con.execute('''
  select symbol, value_score, quality_score, growth_score,
         dividend_score, safety_score
  from mart_stock_scorecard order by symbol limit 5
''').df().to_string(index=False))
print()
print('tổng số mã:', con.execute('select count(*) from mart_stock_scorecard').fetchone()[0])
"
```

Expected: khớp với giá trị trước B1. B1 chỉ **thêm** model mới, không sửa model nào đang nuôi `mart_stock_scorecard` — nếu số liệu đổi thì có gì đó đã lấn phạm vi, **báo controller ngay**.

- [ ] **Step 7: Cập nhật README**

Trong phần "Kiến trúc", đổi khối sơ đồ thành:

```
INGESTION (Python)                WAREHOUSE            CONSUMERS
build_warehouse.py --mode         raw_* (immutable)    ├─ MCP server (hội thoại)
  daily   → giá EOD + chỉ số        ↓ dbt              ├─ main.py (bản tin Telegram)
  weekly  → tỷ số + sự kiện DN    stg_* → int_*        └─ SQL ad-hoc
  monthly → hồ sơ DN + sở hữu       ↓
                                  mart_* ← nơi mọi phân tích query vào
```

Và đổi dòng mô tả `mcp_server/`:

```markdown
- `mcp_server/` — 9 tool read-only cho luồng hội thoại
```

- [ ] **Step 8: Ghi chú thời lượng vào workflow**

Trong `.github/workflows/warehouse-weekly.yml`, đổi tên bước ingest:

```yaml
      - name: Warehouse weekly (giá + financial ratios + sự kiện DN, ~56 phút)
```

Trong `.github/workflows/warehouse-monthly.yml`, đổi tương ứng tên bước ingest thành:

```yaml
      - name: Warehouse monthly (giá + ratios + hồ sơ DN + sở hữu, ~85 phút)
```

- [ ] **Step 9: Chạy toàn bộ test lần cuối**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 241 passed, 2 xfailed

- [ ] **Step 10: Commit**

```bash
git add scripts/check_mcp_tools.py README.md \
        .github/workflows/warehouse-weekly.yml \
        .github/workflows/warehouse-monthly.yml
git commit -m "feat(b1): nghiệm thu 9 tool + cập nhật README và thời lượng workflow

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành B1

| # | Tiêu chí | Cách kiểm | Task |
|---|---|---|---|
| 1 | `id` ổn định giữa hai lần gọi | `scripts/probe_event_id_stability.py` exit 0 | 1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` → 241 passed, 2 xfailed | 7 |
| 3 | 3 bảng raw có dữ liệu thật trên MotherDuck | Task 7 Step 2 | 7 |
| 4 | Chạy 2 lần: `raw_corporate_event` không giảm dòng; `raw_shareholder` có ≥2 snapshot sau 2 kỳ | Task 7 Step 4 | 7 |
| 5 | Không dòng nào `is_distribution = true` mà loại ngoài 3 giá trị | `assert_distribution_flag_only_three_types` | 4 |
| 6 | `ISS_KHAC + UNKNOWN_CODE` ≤ 5% tổng sự kiện | `assert_event_classification_coverage` | 4 |
| 7 | 9 tool trả dữ liệu thật | `scripts/check_mcp_tools.py` exit 0 | 7 |
| 8 | `mart_stock_scorecard` và điểm số **không đổi** | Task 7 Step 6 | 7 |

Tiêu chí #8 là phép thử cho ràng buộc "chỉ thêm, không đổi thứ đang chạy" — nếu điểm số đổi thì đã lấn phạm vi.

---

## Ngoài phạm vi (nhắc lại để không hiểu nhầm ở review)

Không đụng `mart_stock_scorecard` · không đổi công thức chấm điểm · không sửa `int_dividend_history` (đã xác minh đúng, xem spec §1.3) · không làm khối ngoại (không có nguồn, spec §1.1) · không làm BCTC chi tiết (để B2) · không làm cảnh báo/thông báo (để mảng C).

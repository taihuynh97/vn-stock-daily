# C1 — Luận điểm đầu tư định kỳ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm tool MCP thứ 11, `get_thesis_update(symbol, since_date)`, trả về những gì THAY ĐỔI kể từ một mốc thời gian (sự kiện phân phối mới, kỳ BCTC mới, thay đổi sở hữu, xu hướng tài chính gần nhất) để agent tự tổng hợp cập nhật luận điểm đầu tư.

**Architecture:** Thuần tool đọc — không ingest mới, không bảng/model dbt mới. 5 hàm helper nhỏ (mỗi hàm 1 khối dữ liệu) trong `mcp_server/tools.py`, lắp ráp bởi `get_thesis_update`, đăng ký qua `mcp_server/server.py` theo đúng pattern 10 tool hiện có.

**Tech Stack:** Python 3.12 · DuckDB/MotherDuck · FastMCP · pytest

**Spec:** `docs/superpowers/specs/2026-08-19-c1-luan-diem-dinh-ky-design.md`

## Global Constraints

- **Không tạo bảng/model dbt mới, không đổi 10 tool hiện có, không đụng `src/scoring.py`.**
- **`mart_stock_scorecard` KHÔNG có lịch sử** — chỉ dùng làm điểm số HIỆN TẠI (context), không diff.
- **`int_ownership_snapshot` KHÔNG dùng được cho diff** (chỉ giữ snapshot mới nhất) — `ownership_change` phải tự tính lại từ `stg_shareholder`/`stg_officer` ở 2 mốc `snapshot_date` cụ thể.
- **`period_type` của `fct_financial_quarterly`**: `"quarter"` (quarter 1-4) hoặc `"year"` (quarter=5) — PHẢI lọc `period_type = 'quarter'` khi tính xu hướng theo quý, nếu không dòng năm sẽ lẫn vào.
- **`new_statement_periods` phải đọc từ `raw_financial_statement`** (không phải `stg_financial_statement`) vì chỉ bảng raw có cột `ingested_at`.
- Toàn bộ docstring, comment, commit message viết bằng tiếng Việt.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`.
- Branch làm việc: `feat/c1-luan-diem-dinh-ky` (đã tạo từ `main`, đã có commit spec).
- Nghiệm thu cuối chạy trên MotherDuck production thật (`WAREHOUSE_DB=md:vn_market`).

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `mcp_server/tools.py` | **Sửa.** 5 hàm helper + `get_thesis_update` | 1 |
| `mcp_server/server.py` | **Sửa.** Đăng ký tool thứ 11 | 1 |
| `tests/conftest_mart.py` | **Sửa.** Thêm `period_type` vào `fct_financial_quarterly`, thêm bảng `raw_financial_statement`, thêm snapshot sở hữu thứ 2 | 1 |
| `tests/test_mcp_tools.py` | **Sửa.** Test từng helper + tool tổng hợp | 1 |
| `tests/test_mcp_server.py` | **Sửa.** Test qua `mcp.call_tool()` | 1 |
| `scripts/check_mcp_tools.py` | **Sửa.** Thêm gọi nghiệm thu tool thứ 11 | 2 |
| `README.md` | **Sửa.** Cập nhật số tool | 2 |

---

## Task 1: `get_thesis_update` — cài đặt đầy đủ TDD

**Files:**
- Modify: `tests/conftest_mart.py`
- Modify: `mcp_server/tools.py`
- Modify: `mcp_server/server.py`
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp_server.db.run_query(con, sql, params=None, limit=1000) -> list[dict]`, `mcp_server.db.as_of(con) -> dict`, `mcp_server.tools._clean(obj)`, `mcp_server.tools._date_str(v)`.
- Produces:
  - `tools._current_scores(con, sym: str) -> dict | None`
  - `tools._financial_trend(con, sym: str, since_date: str) -> dict`
  - `tools._new_distribution_events(con, sym: str, since_date: str) -> list[dict]`
  - `tools._new_statement_periods(con, sym: str, since_date: str) -> list[dict]`
  - `tools._ownership_change(con, sym: str, since_date: str) -> dict | None`
  - `tools.get_thesis_update(con, symbol: str, since_date: str | None = None) -> dict`

> **Bối cảnh không có trong spec**: fixture hiện tại (`tests/conftest_mart.py`) tạo `fct_financial_quarterly` KHÔNG có cột `period_type` (chỉ có `symbol, year, quarter, period_end_date, com_class, pe, pb, roe, revenue_ttm, earnings_ttm, revenue_yoy, earnings_yoy`) — lệch với schema thật (`transforms/models/marts/fct_financial_quarterly.sql` SELECT `f.period_type`, nguồn từ `src/ingest_market.py:311`: `period_type = "year" if quarter == 5 else "quarter"`). Fixture cũng CHƯA có bảng `raw_financial_statement` (chỉ có `stg_financial_statement`, không có cột `ingested_at`). Cả hai phải sửa/thêm ở bước đầu Task này TRƯỚC khi viết test, nếu không sẽ không viết được test đúng cho `_financial_trend`/`_new_statement_periods`.

- [ ] **Step 1: Sửa fixture — thêm `period_type` vào `fct_financial_quarterly`, thêm bảng `raw_financial_statement`, thêm snapshot sở hữu thứ 2 cho AAA**

Trong `tests/conftest_mart.py`, thay khối `fct_financial_quarterly`:

```python
        CREATE TABLE fct_financial_quarterly (
            symbol VARCHAR, year INTEGER, quarter INTEGER, period_end_date DATE,
            period_type VARCHAR, com_class VARCHAR, pe DOUBLE, pb DOUBLE, roe DOUBLE,
            revenue_ttm DOUBLE, earnings_ttm DOUBLE, revenue_yoy DOUBLE,
            earnings_yoy DOUBLE
        );
        INSERT INTO fct_financial_quarterly VALUES
          ('AAA',2026,2,DATE '2026-06-30','quarter','NONFIN',9.5,1.2,0.18,1e13,1e12,0.12,0.20),
          ('AAA',2026,1,DATE '2026-03-31','quarter','NONFIN',10.1,1.3,0.17,9.5e12,9e11,0.10,0.15),
          -- Dòng NĂM (quarter=5, period_type='year') — CÙNG period_end_date
          -- 31/12 như quarter=4 của năm trước đó nếu có, nhưng ở đây dùng
          -- năm riêng (2025) để không trùng period_end_date với 2 dòng quý
          -- trên. Mục đích: test _financial_trend PHẢI lọc period_type='quarter',
          -- nếu lọt dòng này vào kết quả thì test thất bại rõ ràng.
          ('AAA',2025,5,DATE '2025-12-31','year','NONFIN',8.8,1.1,0.16,8e12,7e11,0.08,0.10);
```

Thêm bảng `raw_financial_statement` mới (đặt sau khối `stg_financial_statement` hiện có, trong cùng lệnh `con.execute` của phần B2 hoặc một lệnh `con.execute` mới ngay sau đó):

```python
    # --- C1: raw_financial_statement (cần ingested_at, KHÔNG có trong
    # stg_financial_statement — _new_statement_periods phải đọc bảng raw).
    con.execute("""
        CREATE TABLE raw_financial_statement (
            symbol VARCHAR, statement_type VARCHAR, period_type VARCHAR,
            period_label VARCHAR, row_seq INTEGER, item_id VARCHAR,
            item_vi VARCHAR, item_en VARCHAR, value DOUBLE,
            ingested_at TIMESTAMP
        );
        INSERT INTO raw_financial_statement VALUES
          ('AAA','income_statement','quarter','2026-q1',0,'net_sales',
           'Doanh thu thuần','Net sales',90.0, TIMESTAMP '2026-05-01 00:00:00'),
          ('AAA','income_statement','quarter','2026-q2',0,'net_sales',
           'Doanh thu thuần','Net sales',100.0, TIMESTAMP '2026-08-18 00:00:00');
    """)
```

Thêm snapshot sở hữu THỨ HAI (sớm hơn) cho AAA — sửa khối `INSERT INTO stg_shareholder`/`stg_officer` hiện có bằng cách CHÈN THÊM (không xoá dòng cũ) các dòng sau, đặt trong cùng lệnh `con.execute` của phần B1 (ngay sau các `INSERT INTO stg_officer VALUES` hiện có, trước dấu `;` đóng câu lệnh — nối bằng `,` nếu cùng 1 câu `INSERT`, hoặc thêm `INSERT` riêng ngay sau):

```python
        -- C1: snapshot sở hữu THỨ HAI, sớm hơn (2026-05-01), cho AAA — để
        -- _ownership_change có 2 mốc THẬT để tính delta. Chỉ đổi tỉ lệ của
        -- Ông Nguyễn Văn A (0.2580 -> 0.2400) để tạo delta rõ ràng, dễ kiểm.
        INSERT INTO stg_shareholder VALUES
          ('AAA','Ông Nguyễn Văn A',1.5e9,0.2400,DATE '2026-04-15',DATE '2026-05-01'),
          ('AAA','Bà Trần Thị B',4.2e8,0.0688,DATE '2026-04-15',DATE '2026-05-01');
        INSERT INTO stg_officer VALUES
          ('AAA','Ông Nguyễn Văn A','Chủ tịch HĐQT',0.2400,1.5e9,
           DATE '2026-04-15',DATE '2026-05-01');
        -- GGG: CHỈ 1 snapshot duy nhất (baseline == latest) — ca "chưa đủ
        -- lịch sử để so sánh", delta phải ra 0 một cách hợp lệ, không lỗi.
        -- Đồng thời dùng GGG làm ca đối chiếu tiêu chí hoàn thành #2 (spec
        -- §7): int_ownership_snapshot.GGG bên dưới PHẢI là kết quả gộp
        -- ĐÚNG của các dòng stg_shareholder/stg_officer này (1 cổ đông +
        -- 1 officer, cùng người, 30%) — để test so sánh trực tiếp
        -- _ownership_change() với int_ownership_snapshot mà không đụng tới
        -- dòng AAA hiện có (dòng AAA trong int_ownership_snapshot được tạo
        -- cho mục đích khác từ B1, KHÔNG khớp số học với 3 dòng
        -- stg_shareholder của AAA — không dùng AAA để đối chiếu).
        INSERT INTO stg_shareholder VALUES
          ('GGG','Ông E',1.0e9,0.3000,DATE '2026-08-01',DATE '2026-08-01');
        INSERT INTO stg_officer VALUES
          ('GGG','Ông E','Chủ tịch HĐQT',0.3000,1.0e9,
           DATE '2026-08-01',DATE '2026-08-01');
        INSERT INTO int_ownership_snapshot VALUES
          ('GGG',DATE '2026-08-01',1,0.3000,0.3000,0.3000,0.3000,DATE '2026-08-01');
```

- [ ] **Step 2: Viết test thất bại cho `_current_scores`**

Thêm vào cuối `tests/test_mcp_tools.py`:

```python
def test_current_scores_khop_5_diem_thanh_phan(con):
    r = tools._current_scores(con, "AAA")
    assert r == {
        "value": 80.0, "quality": 70.0, "growth": 60.0,
        "dividend": 90.0, "safety": 50.0,
    }


def test_current_scores_ma_khong_ton_tai_tra_none(con):
    assert tools._current_scores(con, "ZZZ") is None
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k current_scores -q`
Expected: FAIL — `AttributeError: module 'mcp_server.tools' has no attribute '_current_scores'`

- [ ] **Step 4: Cài `_current_scores`**

Thêm vào cuối `mcp_server/tools.py`:

```python
def _current_scores(con, sym: str) -> dict | None:
    """Điểm số HIỆN TẠI (không phải diff — mart_stock_scorecard không có
    lịch sử, xem spec C1 §2)."""
    rows = db.run_query(
        con,
        """
        SELECT value_score, quality_score, growth_score,
               dividend_score, safety_score
        FROM mart_stock_scorecard
        WHERE symbol = ?
        """,
        params=[sym],
        limit=1,
    )
    if not rows:
        return None
    r = _clean(rows[0])
    return {
        "value": r["value_score"], "quality": r["quality_score"],
        "growth": r["growth_score"], "dividend": r["dividend_score"],
        "safety": r["safety_score"],
    }
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k current_scores -q`
Expected: PASS

- [ ] **Step 6: Viết test thất bại cho `_financial_trend`**

```python
def test_financial_trend_chi_tra_quy_sau_since_date_dung_thu_tu(con):
    r = tools._financial_trend(con, "AAA", "2026-01-01")
    assert r["n_new_quarters"] == 2
    quarters = r["quarters"]
    assert [(q["year"], q["quarter"]) for q in quarters] == [(2026, 1), (2026, 2)]


def test_financial_trend_loc_dung_since_date_cat_bot_qua_cu(con):
    r = tools._financial_trend(con, "AAA", "2026-04-01")
    assert r["n_new_quarters"] == 1
    assert [(q["year"], q["quarter"]) for q in r["quarters"]] == [(2026, 2)]


def test_financial_trend_khong_lan_dong_nam_quarter_5(con):
    """Dòng năm (quarter=5, period_type='year', period_end_date 2025-12-31)
    PHẢI bị loại dù since_date đủ cũ để bao trùm nó — bảo vệ đúng Global
    Constraint 'phải lọc period_type=quarter'."""
    r = tools._financial_trend(con, "AAA", "2020-01-01")
    assert r["n_new_quarters"] == 2
    assert all(q["quarter"] != 5 for q in r["quarters"])
```

- [ ] **Step 7: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k financial_trend -q`
Expected: FAIL — `AttributeError`

- [ ] **Step 8: Cài `_financial_trend`**

```python
def _financial_trend(con, sym: str, since_date: str) -> dict:
    """Xu hướng tài chính các quý MỚI kể từ since_date.

    PHẢI lọc period_type='quarter' — fct_financial_quarterly có cả dòng
    NĂM (quarter=5, period_type='year'), lẫn vào sẽ trộn 2 loại kỳ khác
    nhau (xem Global Constraint).
    """
    rows = db.run_query(
        con,
        """
        SELECT year, quarter, revenue_ttm, earnings_ttm, revenue_yoy, earnings_yoy
        FROM fct_financial_quarterly
        WHERE symbol = ? AND period_type = 'quarter' AND period_end_date > ?
        ORDER BY year, quarter
        """,
        params=[sym, since_date],
        limit=40,
    )
    quarters = _clean(rows)
    return {"quarters": quarters, "n_new_quarters": len(quarters)}
```

- [ ] **Step 9: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k financial_trend -q`
Expected: PASS

- [ ] **Step 10: Viết test thất bại cho `_new_distribution_events`**

```python
def test_new_distribution_events_loc_dung_since_date(con):
    r = tools._new_distribution_events(con, "AAA", "2026-05-01")
    assert len(r) == 2
    assert {e["event_title_vi"][:20] for e in r} == {
        "Trả cổ tức bằng tiề"[:20], "Phát hành cổ phiếu "[:20],
    }


def test_new_distribution_events_khong_co_gi_moi_tra_mang_rong(con):
    r = tools._new_distribution_events(con, "AAA", "2026-06-01")
    assert r == []
```

- [ ] **Step 11: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k new_distribution_events -q`
Expected: FAIL — `AttributeError`

- [ ] **Step 12: Cài `_new_distribution_events`**

```python
def _new_distribution_events(con, sym: str, since_date: str) -> list[dict]:
    """Sự kiện phân phối MỚI kể từ since_date — cùng nguồn/cột với
    get_distribution_history, thêm điều kiện exright_date > since_date."""
    rows = db.run_query(
        con,
        """
        SELECT exright_date, distribution_type, cash_per_share,
               stock_ratio, event_title_vi
        FROM int_distribution_event
        WHERE symbol = ? AND exright_date > ?
        ORDER BY exright_date DESC
        """,
        params=[sym, since_date],
        limit=50,
    )
    return [
        {**r, "exright_date": _date_str(r["exright_date"])}
        for r in _clean(rows)
    ]
```

- [ ] **Step 13: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k new_distribution_events -q`
Expected: PASS

- [ ] **Step 14: Viết test thất bại cho `_new_statement_periods`**

```python
def test_new_statement_periods_phat_hien_dung_ky_moi(con):
    r = tools._new_statement_periods(con, "AAA", "2026-06-01")
    assert len(r) == 1
    assert r[0]["period_label"] == "2026-q2"
    assert r[0]["statement_type"] == "income_statement"


def test_new_statement_periods_khong_co_gi_moi_tra_mang_rong(con):
    r = tools._new_statement_periods(con, "AAA", "2026-09-01")
    assert r == []
```

- [ ] **Step 15: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k new_statement_periods -q`
Expected: FAIL — `AttributeError`

- [ ] **Step 16: Cài `_new_statement_periods`**

```python
def _new_statement_periods(con, sym: str, since_date: str) -> list[dict]:
    """Kỳ BCTC MỚI xuất hiện kể từ since_date — đọc raw_financial_statement
    (KHÔNG phải stg_financial_statement, thiếu cột ingested_at)."""
    rows = db.run_query(
        con,
        """
        SELECT statement_type, period_type, period_label,
               max(ingested_at) as ingested_at
        FROM raw_financial_statement
        WHERE symbol = ? AND ingested_at > ?
        GROUP BY 1, 2, 3
        ORDER BY ingested_at DESC
        """,
        params=[sym, since_date],
        limit=50,
    )
    return [
        {**r, "ingested_at": str(r["ingested_at"])}
        for r in _clean(rows)
    ]
```

- [ ] **Step 17: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k new_statement_periods -q`
Expected: PASS

- [ ] **Step 18: Viết test thất bại cho `_ownership_change`**

```python
def test_ownership_change_tinh_dung_delta_khi_co_baseline_that(con):
    r = tools._ownership_change(con, "AAA", "2026-06-01")
    assert r["baseline_snapshot_date"] == "2026-05-01"
    assert r["latest_snapshot_date"] == "2026-08-01"
    assert r["baseline_is_fallback"] is False
    assert r["top1_pct"]["baseline"] == pytest.approx(0.2400)
    assert r["top1_pct"]["latest"] == pytest.approx(0.2580)
    assert r["top1_pct"]["delta"] == pytest.approx(0.0180, abs=1e-6)
    assert r["insider_pct"]["baseline"] == pytest.approx(0.2400)
    assert r["insider_pct"]["latest"] == pytest.approx(0.3105)


def test_ownership_change_fallback_khi_khong_co_snapshot_truoc_since_date(con):
    """since_date quá xa (2026-01-01) -> không có snapshot nào <= mốc đó ->
    dùng snapshot CŨ NHẤT hiện có (2026-05-01) làm baseline, đặt cờ fallback."""
    r = tools._ownership_change(con, "AAA", "2026-01-01")
    assert r["baseline_snapshot_date"] == "2026-05-01"
    assert r["baseline_is_fallback"] is True


def test_ownership_change_chi_1_snapshot_delta_bang_0(con):
    r = tools._ownership_change(con, "GGG", "2026-01-01")
    assert r["baseline_snapshot_date"] == r["latest_snapshot_date"] == "2026-08-01"
    assert r["top1_pct"]["delta"] == 0.0


def test_ownership_change_khop_int_ownership_snapshot(con):
    """Tiêu chí hoàn thành #2 (spec §7): _ownership_change tự tính lại phép
    gộp — phải khớp TUYỆT ĐỐI với int_ownership_snapshot (model dbt) khi
    cùng 1 mốc snapshot_date. Dùng GGG vì dữ liệu ở đây được dựng nhất quán
    giữa 2 bảng (xem comment ở fixture) — dòng AAA của int_ownership_snapshot
    KHÔNG dùng được cho so sánh này (tạo cho mục đích khác từ B1)."""
    r = tools._ownership_change(con, "GGG", "2026-01-01")
    expected = db.run_query(
        con,
        "SELECT total_disclosed_pct, top1_pct, top5_pct, insider_pct "
        "FROM int_ownership_snapshot WHERE symbol = 'GGG'",
        limit=1,
    )[0]
    assert r["total_disclosed_pct"]["latest"] == pytest.approx(expected["total_disclosed_pct"])
    assert r["top1_pct"]["latest"] == pytest.approx(expected["top1_pct"])
    assert r["top5_pct"]["latest"] == pytest.approx(expected["top5_pct"])
    assert r["insider_pct"]["latest"] == pytest.approx(expected["insider_pct"])


def test_ownership_change_ma_khong_co_du_lieu_so_huu_tra_none(con):
    assert tools._ownership_change(con, "ZZZ", "2026-01-01") is None
```

- [ ] **Step 19: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k ownership_change -q`
Expected: FAIL — `AttributeError`

- [ ] **Step 20: Cài `_ownership_change`**

```python
def _ownership_change(con, sym: str, since_date: str) -> dict | None:
    """So sánh cơ cấu sở hữu giữa 2 mốc snapshot_date: baseline (mốc gần
    since_date nhất, <= since_date; nếu không có mốc nào cũ vậy thì dùng
    mốc CŨ NHẤT hiện có, đặt baseline_is_fallback=True) và latest (mốc mới
    nhất).

    KHÔNG dùng int_ownership_snapshot (chỉ giữ bản mới nhất, không so sánh
    được) — tự tính lại đúng phép gộp mà int_ownership_snapshot.sql đang
    làm, cho CẢ HAI mốc, trực tiếp từ stg_shareholder/stg_officer.
    """
    all_dates = db.run_query(
        con,
        "SELECT DISTINCT snapshot_date FROM stg_shareholder WHERE symbol = ? ORDER BY snapshot_date",
        params=[sym], limit=1000,
    )
    if not all_dates:
        return None
    dates = [_date_str(r["snapshot_date"]) for r in all_dates]
    latest = dates[-1]
    before_or_eq = [d for d in dates if d <= since_date]
    baseline = before_or_eq[-1] if before_or_eq else dates[0]
    baseline_is_fallback = not before_or_eq

    def _agg(snapshot_date: str) -> dict:
        # _clean() TRƯỚC khi làm số học — db.run_query trả numpy scalar
        # (df.to_dict() của pandas), không phải float Python thuần; cộng/trừ
        # trên numpy.float64 rồi trả thẳng qua MCP từng gây lỗi thật (B2
        # final review, Important #3 tương tự) — luôn _clean() dữ liệu
        # trung gian trước khi tính, không chỉ _clean() kết quả cuối.
        sh = _clean(db.run_query(
            con,
            """
            SELECT share_own_percent
            FROM stg_shareholder
            WHERE symbol = ? AND snapshot_date = ?
            ORDER BY share_own_percent DESC NULLS LAST
            """,
            params=[sym, snapshot_date], limit=200,
        ))
        pct = [r["share_own_percent"] for r in sh if r["share_own_percent"] is not None]
        of = _clean(db.run_query(
            con,
            "SELECT officer_own_percent FROM stg_officer WHERE symbol = ? AND snapshot_date = ?",
            params=[sym, snapshot_date], limit=200,
        ))
        insider = sum(r["officer_own_percent"] for r in of if r["officer_own_percent"] is not None)
        return {
            "total_disclosed_pct": sum(pct),
            "top1_pct": pct[0] if pct else 0.0,
            "top5_pct": sum(pct[:5]),
            "insider_pct": insider,
        }

    b, l = _agg(baseline), _agg(latest)

    def _delta(key: str) -> dict:
        return {"baseline": b[key], "latest": l[key], "delta": l[key] - b[key]}

    return {
        "baseline_snapshot_date": baseline,
        "baseline_is_fallback": baseline_is_fallback,
        "latest_snapshot_date": latest,
        "top1_pct": _delta("top1_pct"),
        "top5_pct": _delta("top5_pct"),
        "total_disclosed_pct": _delta("total_disclosed_pct"),
        "insider_pct": _delta("insider_pct"),
    }
```

- [ ] **Step 21: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k ownership_change -q`
Expected: PASS

- [ ] **Step 22: Viết test thất bại cho `get_thesis_update` (lắp ráp)**

```python
def test_get_thesis_update_lap_rap_du_4_khoi(con):
    r = tools.get_thesis_update(con, "AAA", "2026-01-01")
    assert r["symbol"] == "AAA"
    assert r["since_date"] == "2026-01-01"
    assert r["current_scores"]["quality"] == 70.0
    assert r["financial_trend"]["n_new_quarters"] == 2
    assert len(r["new_distribution_events"]) == 2
    assert len(r["new_statement_periods"]) == 2
    assert r["ownership_change"]["baseline_is_fallback"] is True


def test_get_thesis_update_since_date_none_mac_dinh_90_ngay(con, monkeypatch):
    import datetime
    fixed_today = datetime.date(2026, 8, 19)

    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr(tools, "date", _FixedDate)
    r = tools.get_thesis_update(con, "AAA", None)
    assert r["since_date"] == "2026-05-21"


def test_get_thesis_update_ma_hoan_toan_khong_ton_tai_tra_error(con):
    r = tools.get_thesis_update(con, "ZZZ", "2026-01-01")
    assert "error" in r
```

- [ ] **Step 23: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k get_thesis_update -q`
Expected: FAIL — `AttributeError`

- [ ] **Step 24: Cài `get_thesis_update` — thêm import `date`/`timedelta` ở đầu file**

Thêm vào đầu `mcp_server/tools.py`, cạnh các import hiện có (`import json`, `import numpy as np`, `import pandas as pd`):

```python
from datetime import date, timedelta
```

Thêm hàm ở cuối file:

```python
def get_thesis_update(con, symbol: str, since_date: str | None = None) -> dict:
    """Những gì THAY ĐỔI kể từ một mốc thời gian — sự kiện phân phối mới,
    kỳ BCTC mới công bố, thay đổi cơ cấu sở hữu, xu hướng tài chính các quý
    mới — để agent tự tổng hợp cập nhật luận điểm đầu tư.

    KHÔNG sinh sẵn văn bản luận điểm (không gọi LLM) — trả dữ liệu cấu trúc,
    agent tự viết. current_scores là điểm số HIỆN TẠI (context), KHÔNG PHẢI
    diff — mart_stock_scorecard không lưu lịch sử, không so sánh được với
    quá khứ.

    since_date mặc định 90 ngày trước hôm nay nếu không truyền.
    """
    sym = symbol.upper().strip()
    if since_date is None:
        since_date = (date.today() - timedelta(days=90)).isoformat()

    scores = _current_scores(con, sym)
    trend = _financial_trend(con, sym, since_date)
    events = _new_distribution_events(con, sym, since_date)
    periods = _new_statement_periods(con, sym, since_date)
    ownership = _ownership_change(con, sym, since_date)

    if (scores is None and trend["n_new_quarters"] == 0 and not events
            and not periods and ownership is None):
        return {"error": f"Không tìm thấy mã {sym} trong warehouse.",
                **db.as_of(con)}

    return {
        "symbol": sym,
        "since_date": since_date,
        "current_scores": scores,
        "financial_trend": trend,
        "new_distribution_events": events,
        "new_statement_periods": periods,
        "ownership_change": ownership,
        **db.as_of(con),
    }
```

- [ ] **Step 25: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -k get_thesis_update -q`
Expected: PASS

- [ ] **Step 26: Đăng ký tool trong `mcp_server/server.py`**

Đọc 1-2 khối `@mcp.tool()` gần cuối file hiện có trước (ví dụ `get_financial_statement`) để bám đúng docstring style, rồi thêm vào cuối file, trước khối `if __name__ == "__main__":`:

```python
@mcp.tool()
@_safe_tool
def get_thesis_update(symbol: str, since_date: str | None = None) -> dict:
    """Những gì THAY ĐỔI kể từ một mốc thời gian, để cập nhật luận điểm
    đầu tư định kỳ (tháng/quý).

    since_date: chuỗi "YYYY-MM-DD". Mặc định 90 ngày trước hôm nay nếu
    không truyền.

    Trả 4 khối chênh lệch (sự kiện phân phối mới, kỳ BCTC mới công bố,
    thay đổi cơ cấu sở hữu, xu hướng tài chính các quý mới) cộng điểm số
    HIỆN TẠI làm ngữ cảnh — current_scores KHÔNG PHẢI so sánh với quá khứ,
    chỉ là trạng thái bây giờ (mart_stock_scorecard không lưu lịch sử).

    Không tự viết luận điểm — bạn (agent) tổng hợp từ dữ liệu này.
    """
    return tools.get_thesis_update(conn(), symbol, since_date)
```

- [ ] **Step 27: Viết + chạy test qua `mcp.call_tool()` thật**

Đọc `tests/test_mcp_server.py` hiện có trước để xác nhận đúng tên fixture (`con`, `b1_con`, hay tên khác đang dùng cho các test tool mới nhất — brief này giả định fixture tên `con` giống các test khác trong cùng file dùng `build_fake_mart`, dùng ĐÚNG tên thật nếu khác). Thêm vào cuối file:

```python
def test_get_thesis_update_via_mcp_call_tool(con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: con)

    content = asyncio.run(
        server.mcp.call_tool("get_thesis_update",
                             {"symbol": "AAA", "since_date": "2026-01-01"})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert payload["symbol"] == "AAA"
    assert payload["financial_trend"]["n_new_quarters"] == 2
    assert payload["ownership_change"]["baseline_is_fallback"] is True
```

- [ ] **Step 28: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — tăng đúng số test mới so với baseline trước Task 1 (chạy `pytest tests/ -q` trước khi bắt đầu Task 1 để biết baseline chính xác), không mất test nào.

- [ ] **Step 29: Commit**

```bash
git add mcp_server/tools.py mcp_server/server.py \
        tests/conftest_mart.py tests/test_mcp_tools.py tests/test_mcp_server.py
git commit -m "feat(c1): tool get_thesis_update — luận điểm đầu tư định kỳ

current_scores là ngữ cảnh (mart_stock_scorecard không có lịch sử), 4 khối
còn lại là chênh lệch thật kể từ since_date: sự kiện phân phối mới, kỳ BCTC
mới, thay đổi sở hữu (tự tính lại từ stg_shareholder/stg_officer ở 2 mốc,
không dùng int_ownership_snapshot vì chỉ giữ bản mới nhất), xu hướng tài
chính các quý mới.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Nghiệm thu trên dữ liệu production thật

**Files:**
- Modify: `scripts/check_mcp_tools.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: toàn bộ Task 1.
- Produces: bằng chứng cho 6 tiêu chí hoàn thành trong spec §7.

- [ ] **Step 1: Mở rộng script nghiệm thu**

Trong `scripts/check_mcp_tools.py`, thêm vào hàm `main()` ngay sau lần gọi `get_financial_statement`, trước `run_sql`:

```python
    ok &= show("get_thesis_update(HPG, since 90 ngày trước)",
               tools.get_thesis_update(con, "HPG"))
```

- [ ] **Step 2: Chạy nghiệm thu trên production thật**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -m scripts.check_mcp_tools
```

Expected: `TẤT CẢ ĐẠT`, exit code 0, cả 11 tool trả dữ liệu thật (10 tool cũ + `get_thesis_update`).

- [ ] **Step 3: Đối chiếu tay ≥1 con số mỗi khối cho 1 mã thật (HPG)**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market', read_only=True)
print('current_scores:', con.execute(\"select value_score, quality_score, growth_score, dividend_score, safety_score from mart_stock_scorecard where symbol='HPG'\").fetchone())
print('financial_trend 2 quý gần nhất:', con.execute(\"select year, quarter, period_type, revenue_ttm from fct_financial_quarterly where symbol='HPG' and period_type='quarter' order by year desc, quarter desc limit 2\").fetchall())
print('ownership snapshots HPG:', con.execute(\"select distinct snapshot_date from stg_shareholder where symbol='HPG' order by 1\").fetchall())
print('new_statement_periods (30 ngày gần nhất):', con.execute(\"select statement_type, period_type, period_label, max(ingested_at) from raw_financial_statement where symbol='HPG' and ingested_at > now() - interval 30 day group by 1,2,3\").fetchall())
"
```

Chạy `.venv/bin/python -c "from src import warehouse; from mcp_server import tools; con = warehouse.get_conn(); import json; print(json.dumps(tools.get_thesis_update(con, 'HPG'), default=str, indent=2, ensure_ascii=False)); con.close()"` (với `WAREHOUSE_DB=md:vn_market` đã export), đối chiếu từng khối trong output với các truy vấn tay ở trên — phải khớp.

- [ ] **Step 4: Kiểm 10 tool cũ không đổi hành vi**

```bash
git diff --stat main...HEAD -- mcp_server/tools.py mcp_server/server.py
```

Expected: chỉ thấy các dòng THÊM (hàm mới, khối đăng ký mới) — không có dòng sửa/xoá trong 10 hàm tool cũ. Nếu có, dừng lại và báo controller.

- [ ] **Step 5: Cập nhật README**

Trong phần "Kiến trúc", đổi dòng mô tả `mcp_server/`:

```markdown
- `mcp_server/` — 11 tool read-only cho luồng hội thoại
```

- [ ] **Step 6: Chạy toàn bộ test lần cuối**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, không giảm so với baseline trước Task 2.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_mcp_tools.py README.md
git commit -m "feat(c1): nghiệm thu 11 tool trên production + cập nhật README

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành C1 (đối chiếu spec §7)

| # | Tiêu chí | Task |
|---|---|---|
| 1 | Toàn bộ pytest pass, không hỏng test cũ | 1, 2 |
| 2 | `ownership_change` khớp `int_ownership_snapshot` khi baseline=latest | 1 (`test_ownership_change_chi_1_snapshot_delta_bang_0`) |
| 3 | `financial_trend` không lẫn dòng năm (`quarter=5`) | 1 (`test_financial_trend_khong_lan_dong_nam_quarter_5`) |
| 4 | Tool trả đúng cho mã thật (HPG), đối chiếu tay | 2 |
| 5 | 11/11 tool đạt qua `check_mcp_tools.py` trên production | 2 |
| 6 | Không đổi hành vi 10 tool cũ, không đụng bảng nguồn | 2 (Step 4) |

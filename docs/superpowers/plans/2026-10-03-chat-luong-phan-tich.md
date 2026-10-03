# Sửa lỗi chất lượng phân tích — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Ghi chú thực thi:** người dùng yêu cầu sửa và không trực tiếp theo dõi phiên này, nên kế hoạch được
> thực thi theo kiểu Native (executing-plans) bởi chính agent đã viết spec. Các bước mô tả hành vi và ca
> kiểm thử chính xác; code viết thẳng vào file khi thực thi để không chép hai lần.

**Goal:** Số liệu nền đúng, sàng lọc tất định, có cổng biến cố trước khi định giá, và mọi hạn chế còn lại được viết ra.

**Architecture:** Sửa tận gốc ở ingest (ánh xạ cột bảng giá), thêm lớp điều chỉnh giá và lợi nhuận quý thật ở dbt,
định giá theo giá hiện tại, mart cờ rủi ro; một phễu sàng lọc có cấu hình phiên bản dùng chung cho MCP; skill
bắt buộc đi qua phễu đó và cổng biến cố.

**Tech Stack:** Python 3.12, pandas, DuckDB 1.5.3 / MotherDuck, dbt-duckdb 1.11, vnstock 4.0.9 (VCI), MCP SDK, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-chat-luong-phan-tich-design.md`

## Global Constraints

- Không ghi lên `md:vn_market` từ nhánh này. Mọi build/chạy thử dùng bản sao cục bộ trong scratchpad.
- Mọi model phải chạy được trên cả DuckDB cục bộ lẫn MotherDuck (ràng buộc có sẵn của dự án).
- NULL ≠ 0 ở mọi chỉ tiêu mới; "không đo được" phải là NULL.
- Giữ tên cột cũ (`loss_quarters_12q`, `pe`, `pb`, `valuation_band`) để không vỡ truy vấn cũ; thêm cột mới bên cạnh.
- Ngôn ngữ: tiếng Việt cho tài liệu, chú thích, thông báo; tên kỹ thuật giữ tiếng Anh.
- Commit cuối mỗi task, message theo khuôn `fix(q): ...`/`feat(q): ...`/`docs(q): ...`.

## Review Focus

1. Bảng giá trả mã **không khớp lệnh** trong phiên (match_price 0/None, volume 0) → close = ref_price, volume 0, không ném lỗi hợp đồng OHLC.
2. Job chạy vào **ngày lễ** (trading_date của bảng giá ≠ ngày chạy) → không ghi dòng nào, log `skipped`.
3. Mã có **chia thưởng sau ngày sửa lịch sử** → chỉ dòng có ngày < GDKHQ và nạp trước GDKHQ bị nhân hệ số; dòng nạp bù sau đó không bị nhân lần hai.
4. Mã **không có BCTC quý** → `loss_quarters_*_actual` NULL, risk gate không được ra `qua` (cờ `khong_co_bctc_quy`).
5. P/E âm/NULL hoặc thiếu giá tại ngày chốt quý → `pe_current` NULL, phễu bỏ qua mã đó mà không lỗi.

---

### Task 1: Sửa ánh xạ bảng giá + hợp đồng OHLC + phát hiện ngày nghỉ

**Files:** Modify `src/ingest_market.py` (`_normalize_board`, `_find`→`_pick`, `fetch_eod_prices`, thêm `board_trading_date`),
`src/dq.py` (`assert_ohlc_consistent`), `src/warehouse.py` (cột mới + `upsert_prices`), `build_warehouse.py` (ngày nghỉ).
Test: create `tests/test_price_board_mapping.py`.

**Interfaces — Produces:**
- `ingest_market._pick(cols: list[str], *candidates: str) -> str | None` — khớp chính xác trước, rồi hậu tố `"." + cand`, theo thứ tự ứng viên.
- `ingest_market._normalize_board(df, trade_date) -> DataFrame` cột: `symbol, trade_date, open, high, low, close, volume, value, ref_price, foreign_buy_volume, foreign_sell_volume, foreign_buy_value, foreign_sell_value`.
- `ingest_market.board_trading_date(df) -> str | None` (ISO date, từ `listing.trading_date`).
- `dq.assert_ohlc_consistent(df, source, max_bad_ratio=0.05) -> None` (ném `dq.SchemaError`).
- `warehouse.PRICE_EXTRA_COLUMNS: dict[str, str]`; `upsert_prices` ghi đủ 13 cột + `loaded_at`.

- [ ] Viết test: DataFrame giả đúng thứ tự cột VCI thật (listing.* trước match.*) → close lấy `match.match_price` chứ không phải `listing.ref_price`; mã không khớp lệnh → close=ref, volume=0; `assert_ohlc_consistent` ném lỗi khi 6/10 dòng close ngoài [low,high], im lặng khi 0/10 hoặc khi dòng lệch chỉ là dòng volume 0; `board_trading_date` đọc được cả chuỗi ISO lẫn timestamp; `upsert_prices` trên DuckDB tạm lưu `ref_price` và khối ngoại; DataFrame thiếu cột khối ngoại vẫn ghi được (NULL).
- [ ] Chạy test → FAIL.
- [ ] Cài đặt; `build_warehouse.py`: nếu `board_trading_date(raw) != run_date` thì log `skipped` "ngày nghỉ (bảng giá ngày X)" và không ghi.
- [ ] Chạy test + toàn bộ suite → PASS. Commit.

### Task 2: Script sửa lịch sử giá

**Files:** Create `scripts/repair_price_history.py`, `tests/test_repair_price_history.py`.

**Interfaces — Produces:** `merge_history(con, hist: DataFrame, repaired_at: datetime) -> int`;
`phantom_sessions(con) -> DataFrame[trade_date, n_rows]`; `delete_phantom_sessions(con) -> int`;
`symbol_ranges(con, symbols=None) -> DataFrame[symbol, first_date]`; CLI `--db --symbols --limit --apply`.

- [ ] Test trên DuckDB tạm: dòng cũ có `value`, khối ngoại → sau `merge_history` OHLCV lấy từ lịch sử, `value`/khối ngoại giữ nguyên, `ref_price` NULL, `loaded_at` = `repaired_at`; dòng lịch sử mới (chưa có) được chèn; phiên ma = ngày không có trong VNINDEX mà nằm trong khoảng của chỉ số → được liệt kê và xoá; ngày sau phiên chỉ số cuối cùng không bị coi là phiên ma.
- [ ] FAIL → cài đặt (mặc định dry-run, `--apply` mới ghi) → PASS. Commit.

### Task 3: dbt — giá điều chỉnh

**Files:** Modify `transforms/models/staging/stg_price_daily.sql`, `intermediate/int_price_features.sql`, `marts/fct_price_daily.sql`, `staging/_staging.yml`, `marts/_marts.yml`;
create `intermediate/int_price_adjustment.sql`, tests `assert_adjusted_returns_within_limits.sql` (warn), `assert_ohlc_consistent_recent.sql` (warn, chỉ dòng có ref_price).

**Interfaces — Produces:** `int_price_adjustment(symbol, ex_date, factor)`; `int_price_features.adj_close` và mọi feature tính trên `adj_close`;
`fct_price_daily` thêm `adj_close, ref_price, foreign_buy_volume, foreign_sell_volume, foreign_buy_value, foreign_sell_value`.

Luật hệ số: sự kiện tại phiên D khi `ref_price(D)` không NULL, `close(phiên trước)` > 0 và `abs(ref/prev_close − 1) > 0.0005`;
`factor = ref/prev_close`. Hệ số của dòng t = `exp(sum(ln factor))` trên các sự kiện có `ex_date > t` **và** `ex_date > cast(loaded_at as date)` của dòng t.

- [ ] Build trên bản sao (chưa sửa lịch sử): toàn DAG xanh, `adj_close = close` mọi dòng (chưa có ref_price).
- [ ] Bản sao thứ hai với dữ liệu giả lập một sự kiện (pytest không cần; kiểm bằng `dbt show` trên dòng TRC sau Task 11). Commit.

### Task 4: dbt — lợi nhuận quý thật

**Files:** Create `intermediate/int_quarterly_profit.sql`; modify `int_fundamentals_ttm.sql` (không đổi), `marts/fct_financial_quarterly.sql`, `int_metric_long.sql` (thêm metric `loss_quarters_12q_actual`), `seeds/scoring_weights.csv` (safety dùng metric mới), `_intermediate.yml`, `_marts.yml`; test `assert_quarterly_profit_matches_statement.sql`.

**Interfaces — Produces:** `int_quarterly_profit(symbol, year, quarter, period_end_date, net_profit, profit_item_id, net_profit_yoy, is_loss_quarter, loss_quarters_4q_actual, loss_quarters_12q_actual, quarters_observed_12q)`.
Chọn dòng: ưu tiên `attributable_to_parent_company` → `net_profit_attributable_to_shareholders_of_the_group` → `net_profit_loss_after_tax` → `profit_after_tax`; trong mỗi item_id lấy `min(row_seq)`. `period_label` dạng `YYYY-qN`.

- [ ] Build; kiểm PNJ 2026-Q2 `is_loss_quarter = true`, `loss_quarters_4q_actual = 1`; đếm 103 mã đã đo nay có `loss_quarters_4q_actual ≥ 1`. Commit.

### Task 5: dbt — định giá theo giá hiện tại

**Files:** Create `intermediate/int_valuation_current.sql`; modify `int_metric_long.sql` (pe/pb hiện tại), `marts/mart_stock_scorecard.sql`, `_marts.yml`.

**Interfaces — Produces:** `int_valuation_current(symbol, ratio_period_end, price_date, price_ratio, pe_current, pb_current, market_cap_current, pe_pct_own_5y_current, pb_pct_own_5y_current, valuation_band_current)`.
`price_ratio = adj_close(phiên mới nhất) / adj_close(phiên cuối ≤ ratio_period_end)`, NULL nếu không có phiên trong 15 ngày trước ngày chốt.
Scorecard thêm các cột trên, `loss_quarters_4q_actual`, `loss_quarters_12q_actual`; `value_score` dùng phân vị hiện tại.

- [ ] Build; PNJ `pe_current` < `pe` (giá giảm từ 30/06); không mã nào có `pe_current` khi `pe` NULL. Commit.

### Task 6: dbt — cờ rủi ro, chỉ số, ảnh chụp scorecard

**Files:** Create `marts/mart_risk_flags.sql`, `marts/fct_index_daily.sql`, `marts/mart_scorecard_daily.sql` (incremental, `unique_key=['snapshot_date','symbol']`); update `_marts.yml`, `_sources.yml` không đổi.

**Interfaces — Produces:** `mart_risk_flags(symbol, risk_gate, n_severe, n_warn, flags JSON[{code, severity, text}], lo_quy_gan_day, loi_nhuan_quy_giam_manh, gia_giam_sau, pha_loang_von, noi_bo_dang_ky_ban, ty_so_cu, khong_co_bctc_quy, as_of)`;
`fct_index_daily(index_code, trade_date, open, high, low, close, volume, return_1m, return_3m, return_6m, return_12m, return_ytd)`.

- [ ] Build; PNJ `risk_gate = 'cho_bctc_ke_tiep'`; mọi mã trong scorecard có đúng một dòng risk flags; build hai lần liên tiếp không nhân đôi `mart_scorecard_daily`. Commit.

### Task 7: Sàng lọc tất định

**Files:** Modify `src/scoring.py` (khoá `exclude_recent_loss_quarters`, vũ trụ dùng `market_cap_current` nếu có), `config/scoring_profiles.yml`;
create `config/graham_screen.yml`, `src/graham_screen.py`; tests `tests/test_graham_screen.py`, mở rộng `tests/test_scoring.py`.

**Interfaces — Produces:** `graham_screen.load_config(path=None) -> dict`; `graham_screen.run(df: DataFrame, lens: str, cfg: dict) -> dict{lens, config_version, steps:[{step, label, remaining}], passed: DataFrame, waiting: DataFrame}`.
Cột đầu vào: cột của `mart_stock_scorecard` + `risk_gate`, `current_ratio`, `earnings_cagr_3y`, `revenue_cagr_3y`, `growth_consistency`.

- [ ] Test: hai lần `run` trên cùng DataFrame → bằng nhau tuyệt đối; mã có `loss_quarters_12q_actual = 1` bị loại ở bước có lãi; mã `pe_current` NULL bị loại không lỗi; mã BANK không bị loại ở bước thanh toán hiện hành; mã qua phễu nhưng `risk_gate ≠ qua` nằm ở `waiting`; lăng kính lạ → `ValueError`; thứ tự hoà điểm theo `symbol`.
- [ ] FAIL → cài đặt → PASS. Commit.

### Task 8: MCP

**Files:** Modify `mcp_server/tools.py`, `mcp_server/server.py`, `mcp_server/instructions.md`, `scripts/check_mcp_tools.py`, `tests/conftest_mart.py`, `tests/test_mcp_tools.py`, `tests/test_mcp_server.py`.

**Interfaces — Produces:** `tools.screen_graham(con, lens: str, limit: int = 30) -> dict`; `tools.get_risk_flags(con, symbol: str) -> dict`;
`get_stock_profile` thêm khối `valuation_current`, `loss_quarters` và `risk`.

- [ ] Test trên mart giả: `screen_graham('gia_tri')` trả `steps`, `phan_tich_tiep`, `cho`, `benchmark`, `config_version`, as_of; gọi hai lần giống hệt; `get_risk_flags` mã lạ → `error`; profile có `valuation_current`. Server đăng ký đủ 15 tool.
- [ ] FAIL → cài đặt → PASS. Commit.

### Task 9: Skill

**Files:** Modify `.claude/skills/graham-fundamental-analysis/SKILL.md`; create `docs/analyses/README.md`.

- [ ] Thêm Step −1 Intake, quy tắc sàng lọc chỉ qua `screen_graham`, cổng biến cố (risk flags + tin web) trước Step 5, luật "nghĩa vụ không trần → không định giá", luật kỳ hạn, luật rổ, ghi phân tích vào `docs/analyses/`, mục giới hạn nền tảng; sửa bảng "Where each Graham input comes from" (pe_current, fct_index_daily, loss quarters thật). Commit.

### Task 10: Tài liệu hạn chế + nghiệm thu

**Files:** Create `docs/han-che-nen-tang.md`, `docs/Q-ket-qua-va-no-ky-thuat.md`; modify `README.md` (mục "Những điểm cần biết").

- [ ] Viết sau Task 11 để điền số đo thật. Commit.

### Task 11: Nghiệm thu cục bộ

- [ ] Chạy `repair_price_history.py --db <bản sao> --symbols <rổ ~40 mã> --apply`.
- [ ] `dbt build` toàn DAG trên bản sao đã sửa; ghi PASS/WARN.
- [ ] So trước/sau: số mã đổi `value_score` > 10 điểm, ví dụ; PHR/TRC không còn bước nhảy; PNJ bị chặn.
- [ ] pytest toàn bộ; `screen_graham` hai lần giống hệt.
- [ ] Điền vào `docs/Q-ket-qua-va-no-ky-thuat.md`.

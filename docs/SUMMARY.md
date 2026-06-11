# SUMMARY.md — Tổng quan repo `vn-stock-daily`

> File này dùng làm **context nhanh** cho các phiên làm việc sau (Claude Code / con người).
> Khi có thay đổi lớn (schema, kiến trúc, trạng thái phase), cập nhật lại file này.
> Đọc thêm chi tiết ở: `docs/DESIGN.md` (kiến trúc), `docs/ROADMAP.md` (roadmap đầy đủ),
> `docs/PHASE1_TASKS.md` (spec Phase 1), `docs/learning/` (giải thích khái niệm DE).

---

## 1. Repo này làm gì

Nền tảng dữ liệu chứng khoán Việt Nam, gồm **2 pipeline độc lập** dùng chung
nguồn dữ liệu vnstock:

1. **News pipeline** (`main.py`) — đã chạy ổn định, KHÔNG sửa trừ khi Phase 2B.
   Mỗi ngày sau giờ đóng cửa: lấy giá + tin + chỉ số tài chính cho danh mục
   (`config/portfolio.yml`) và quét mã tiềm năng theo tiêu chí value+momentum
   (`config/screener.yml`), nhờ Claude diễn giải thành bản tin tiếng Việt, gửi Telegram.

2. **Warehouse pipeline** (`build_warehouse.py`) — đang phát triển (Phase 1–1.5 done,
   Phase 2A đã có code nhưng chưa có dữ liệu thật). Thu thập dữ liệu **toàn thị trường**
   (HOSE + HNX, ~1594 mã) vào DuckDB/MotherDuck để tái sử dụng cho mọi phân tích sau này.

> ⚠️ Dữ liệu vnstock là cuối phiên/có độ trễ — không dùng cho giao dịch trong ngày.
> Đây là công cụ tổng hợp + tín hiệu tham khảo, không phải lời khuyên đầu tư.

---

## 2. Cấu trúc code

```
main.py                 # entry point pipeline bản tin (KHÔNG sửa — xem mục 5)
build_warehouse.py      # entry point pipeline warehouse (--mode daily|weekly|monthly)
backfill.py             # entry point backfill lịch sử giá 1 lần (resumable)

src/
  ingest.py             # vnstock wrapper cho news pipeline (giá, tin, chỉ số TC, danh sách mã)
  signals.py            # RSI, MA20/50, P/L vs giá vốn, khối lượng đột biến (logic thuần)
  screener.py           # lọc value + momentum, chấm điểm & xếp hạng
  digest.py             # gọi Claude API diễn giải dữ liệu -> bản tin (KHÔNG bịa số)
  notify.py             # gửi Telegram
  storage.py            # SQLite: log bản tin + chống lặp tin (news pipeline)

  ingest_market.py      # vnstock wrapper cho warehouse: universe, giá EOD bulk,
                         # fetch_history_one (backfill), financials, company info,
                         # is_trading_day()
  warehouse.py          # lớp DuckDB/MotherDuck: schema, upsert, load log,
                         # fix_backfill_price_units, delete_trade_date, backfill_status CRUD

config/
  portfolio.yml         # danh mục đang giữ (mã, giá vốn, số lượng)
  screener.yml          # tiêu chí lọc value/momentum cho news pipeline
  warehouse.yml         # sàn cần thu (HOSE, HNX), nguồn (VCI), batch size

scripts/                # migration một lần (guard qua etl_load_log, an toàn chạy lại)
  fix_backfill_units.py     # đã chạy: sửa lệch đơn vị 1000x cho 1.18M dòng backfill cũ
  fix_phantom_sunday.py     # đã chạy: xoá 1.573 dòng phantom trade_date=2026-06-07

tests/                  # pytest, 43 test, TDD-first
.github/workflows/
  daily.yml                 # news pipeline, cron T2-T6 09:00 UTC, đọc warehouse MotherDuck
  warehouse.yml              # warehouse daily, cron T2-T6 08:30 UTC, ghi MotherDuck
  warehouse-weekly.yml        # --mode weekly, cron T7
  warehouse-monthly.yml       # --mode monthly, cron ngày 1 hằng tháng
```

---

## 3. Kiến trúc dữ liệu (warehouse)

```
INGESTION (theo cadence)              WAREHOUSE                 CONSUMERS
  job_daily    ──┐                    raw_*  (immutable)        ├─ digest/Telegram
  job_weekly   ──┼──►  upsert/append ─► stg_*  (dbt — CHƯA CÓ) ──► ├─ Streamlit (CHƯA CÓ)
  job_monthly  ──┘                     mart_* (dbt — CHƯA CÓ) ─► ├─ DBeaver ad-hoc
  job_backfill (1 lần, đã chạy)        control: dim_symbols,    └─ báo cáo / backtest
                                                etl_load_log
```

- DB: DuckDB, qua env `WAREHOUSE_DB`. Local mặc định `data/warehouse.duckdb`,
  production = `md:vn_market` (MotherDuck cloud, free tier — chú ý compute budget
  khi viết migration UPDATE/DELETE lớn).
- Token MotherDuck: env `motherduck_token` (lowercase, khác `MOTHERDUCK_TOKEN` trong `.env`).

### Bảng RAW hiện có (đã tạo, có dữ liệu)

| Bảng | PK | Trạng thái dữ liệu (MotherDuck, 2026-06-11) |
|---|---|---|
| `dim_symbols` | symbol | 1594 mã (HOSE+HNX) |
| `raw_price_daily` | (symbol, trade_date) | 1,185,297 dòng, 2016-07-20 → hiện tại |
| `etl_load_log` | — | 21 dòng (load log + 2 migration) |
| `backfill_status` | symbol | 1594/1594 `done` |
| `raw_financial_ratio` | (symbol, period, period_type) | **0 dòng** — code có (Phase 2A), chưa chạy `--mode weekly` thật |
| `raw_company_info` | symbol | **0 dòng** — code có (Phase 2A), chưa chạy `--mode monthly` thật |

### Lưu ý chất lượng dữ liệu quan trọng — `raw_price_daily`

(Chi tiết: `docs/DESIGN.md` §5.1.1, `docs/learning/03-warehouse-duckdb.md`)

1. **Đơn vị OHLC luôn là VNĐ** (không phải nghìn VNĐ). `Trading.price_board`
   (daily) trả VND, `Quote.history` (backfill) trả nghìn VNĐ — `fetch_history_one`
   nhân ×1000 để đồng nhất. Dữ liệu cũ đã sửa qua `scripts/fix_backfill_units.py`
   (1.18M dòng, đã chạy xong).
2. **`value` (giá trị khớp lệnh) NULL cho hầu hết dòng backfill** — `Quote.history`
   của VCI không trả field này. Đây là giới hạn API, **giữ nguyên NULL**, không tính xấp xỉ.
3. **`is_trading_day()`** (`src/ingest_market.py`) chỉ check Thứ 2–6, **chưa loại
   trừ ngày lễ VN**. `build_warehouse.py` bỏ qua nạp giá vào T7/CN. 1.573 dòng
   phantom của Chủ Nhật 2026-06-07 (trước khi có guard) đã bị xoá qua
   `scripts/fix_phantom_sunday.py`.

---

## 4. Trạng thái roadmap (xem `docs/ROADMAP.md` để biết task chi tiết)

| Phase | Trạng thái |
|---|---|
| Phase 1 — Warehouse nền (dim_symbols, raw_price_daily, etl_load_log) | ✅ Done, chạy production trên MotherDuck |
| Phase 1.5 — Backfill lịch sử giá (3 năm+, resumable) | ✅ Done — 1594/1594 mã `done`, dữ liệu từ 2016 |
| Phase 2A — ingestion weekly (financials) + monthly (company info) | ⚠️ Code đã có (`fetch_financials`, `fetch_company_info`, bảng đã tạo), **nhưng chưa chạy thật** — `raw_financial_ratio`/`raw_company_info` đang rỗng |
| Phase 2B — refactor news pipeline đọc từ warehouse | ❌ Chưa bắt đầu — `ingest.py`/`screener.py` vẫn gọi API trực tiếp |
| Phase 3 — dbt staging/mart + Streamlit dashboard | ❌ Chưa bắt đầu (không có thư mục `transforms/`, không có `app.py`) |
| Phase 4 — Prefect orchestration | ❌ Chưa bắt đầu |

---

## 5. Ràng buộc quan trọng khi làm việc trên repo

- **KHÔNG sửa** `main.py`, `src/ingest.py`, `src/signals.py`, `src/screener.py`,
  `src/digest.py`, `src/notify.py`, `src/storage.py` — trừ khi đang làm Phase 2B
  (refactor nguồn dữ liệu, giữ nguyên logic).
- Mọi ingestion mới: in cột thật lần đầu (`_printed_*_cols` pattern), map mềm qua
  `_find()`, bọc try/except, 1 mã lỗi không làm vỡ job.
- Mọi ghi DB: upsert idempotent (`INSERT OR REPLACE`) + ghi `etl_load_log`.
- Migration một lần (sửa dữ liệu cũ): đặt trong `scripts/`, guard chống chạy lại
  qua `etl_load_log` (job_name + status='ok'), in before/after để verify.
  MotherDuck free tier — cân nhắc chi phí compute của UPDATE/DELETE lớn.
- TDD: viết test đỏ trước → implement → xanh. Dùng
  `superpowers:systematic-debugging` cho bug — tìm root cause trước khi fix.
- Test local trước (`WAREHOUSE_DB` mặc định = file local), MotherDuck sau.

---

## 6. Việc đã làm gần đây (2026-06-11)

- Sửa lệch đơn vị OHLC 1000x giữa backfill và daily ingestion (code + migration
  data, 1.18M dòng).
- Thêm `is_trading_day()` guard trong `build_warehouse.py` để không nạp giá vào T7/CN.
- Xoá 1.573 dòng phantom `trade_date=2026-06-07` (dữ liệu Chủ Nhật không nhất quán).
- Cập nhật `docs/DESIGN.md` và `docs/learning/03-warehouse-duckdb.md` với các bài học
  data quality ở trên.

## 7. Việc còn tồn đọng / gợi ý bước tiếp theo

- Chạy thật `build_warehouse.py --mode weekly` và `--mode monthly` để có dữ liệu
  cho `raw_financial_ratio` / `raw_company_info` (Phase 2A đang dở).
- Cân nhắc thêm lịch nghỉ lễ VN vào `is_trading_day()` (hiện chỉ check thứ trong tuần).
- Phase 2B: refactor `ingest.py`/`screener.py` đọc từ warehouse thay vì gọi API
  trực tiếp mỗi lần chạy `main.py`.
- Một số thay đổi git chưa commit cần xử lý: `.env.example` bị xoá,
  `.github/workflows/daily.yml` có sửa đổi (pin version actions) — kiểm tra có
  cố ý không trước khi commit/revert.

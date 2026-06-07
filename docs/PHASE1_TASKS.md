# PHASE 1 — Warehouse Integration Tasks

> Spec để Claude Code (VS Code) thực thi. Đọc kỹ phần Bối cảnh trước, làm theo task,
> dừng lại và báo cáo ở T5. KHÔNG đụng vào pipeline bản tin.

---

## Bối cảnh

Repo `vn-stock-daily` có **2 pipeline độc lập**:

1. **Pipeline bản tin** (đã chạy ổn): `main.py` → `ingest / signals / screener / digest / notify`
   → gửi Telegram. Lưu tạm bằng SQLite (`storage.py`). **KHÔNG sửa nhóm file này.**

2. **Pipeline warehouse** (Phase 1 — đang tích hợp): `build_warehouse.py` → `ingest_market`
   → `warehouse` (DuckDB). Thu giá EOD **toàn thị trường** (HOSE + HNX), lưu để tái sử dụng.

Mục tiêu Phase 1: chạy được `build_warehouse.py` ở local, tạo file `data/warehouse.duckdb`
gồm 3 bảng `dim_symbols`, `raw_price_daily`, `etl_load_log`, và xác nhận tên cột thật của
`price_board`.

---

## Trạng thái file (đã đặt sẵn trong repo)

- `src/warehouse.py` — lớp DuckDB (schema + upsert + load log)
- `src/ingest_market.py` — thu universe + giá EOD bulk
- `build_warehouse.py` — entry point (gốc repo)
- `config/warehouse.yml` — cấu hình sàn + batch
- `.github/workflows/warehouse.yml` — cron daily (cloud)
- `requirements.txt` — đã thêm `duckdb>=1.0`

Nếu thiếu file nào, báo người dùng (đừng tự tạo lại từ trí nhớ).

---

## Task cho Claude Code

### T1 — Xác minh cấu trúc
- [ ] Kiểm tra 6 file trên tồn tại đúng vị trí.
- [ ] `requirements.txt` có dòng `duckdb`.
- Acceptance: đủ file, không thiếu.

### T2 — Cài đặt phụ thuộc
- [ ] Kích hoạt venv: `source .venv/bin/activate`
- [ ] `pip install -r requirements.txt`
- Acceptance: `python -c "import duckdb; print(duckdb.__version__)"` in ra version.

### T3 — Chạy thử local
- [ ] `python build_warehouse.py`
- Acceptance — output phải có:
  - `dim_symbols: N mã` với **N > 500**
  - `[price_board] cột thật: [...]`  ← **GHI LẠI nguyên dòng này**
  - `raw_price_daily: X/N mã có giá ...` với **X xấp xỉ N**
  - File `data/warehouse.duckdb` được tạo.

### T4 — Kiểm tra dữ liệu
Chạy (python hoặc `duckdb data/warehouse.duckdb`):
```sql
SELECT count(*) FROM dim_symbols;
SELECT count(*) FROM raw_price_daily;
SELECT * FROM raw_price_daily LIMIT 5;
SELECT * FROM etl_load_log;
```
- Acceptance: `raw_price_daily` có cột `close` **không null** cho phần lớn mã.
- Nếu `close`/`volume` null hàng loạt → mapping cột sai (xem Troubleshooting).

### T5 — Báo cáo (DỪNG ở đây, đưa cho người dùng)
Tổng hợp và đưa lại:
1. Nguyên dòng `[price_board] cột thật: [...]`
2. Số mã `dim_symbols`
3. Số dòng `raw_price_daily` + ví dụ 5 dòng đầu
4. Mọi lỗi batch/mã (nếu có)

---

## Task thủ công (người dùng làm — Claude Code KHÔNG làm được)

- [ ] Đăng ký MotherDuck tại motherduck.com → tạo database `vn_market` → lấy access token.
- [ ] Thêm GitHub repo secret: `MOTHERDUCK_TOKEN`.
- [ ] (Đã có) `VNSTOCK_API_KEY` trong `.env` và trong repo secrets.

Sau khi có token, chạy thử cloud ở local:
```bash
export WAREHOUSE_DB=md:vn_market
export motherduck_token=<token>
python build_warehouse.py
```

---

## Troubleshooting

- **Rate limit (Guest 20 req/phút):** kiểm tra `VNSTOCK_API_KEY` đã set trong `.env` chưa.
  `_throttle()` trong `ingest.py` đã giãn 3.1s/call nên không nên vượt; nếu vẫn vượt, tăng
  `_MIN_CALL_INTERVAL`.
- **`close`/`volume` null hàng loạt:** tên cột price_board thật khác với dò tự động. Đưa dòng
  `[price_board] cột thật: [...]` cho người dùng để chỉnh hàm `_normalize_board()` trong
  `src/ingest_market.py` (sửa danh sách khóa trong các lời gọi `_find(...)`).
- **`N` quá nhỏ (< 100):** cột exchange trong `all_symbols()` khác tên. Xem lại `refresh_universe()`.

## Ràng buộc
- KHÔNG sửa `main.py`, `ingest.py`, `signals.py`, `screener.py`, `digest.py`, `notify.py`, `storage.py`.
- Chỉ thao tác trong phạm vi các file Phase 1 liệt kê ở trên.

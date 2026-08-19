# C2 — Báo cáo fix wave sau final whole-branch review

> Vòng sửa DUY NHẤT được phép sau final review của kế hoạch C2 (cảnh báo
> theo sự kiện). Branch gốc: `feat/c2-canh-bao-su-kien`, commit xuất phát
> `0f5150f`. Không chạy `alert_events.py` thật, không kết nối MotherDuck —
> toàn bộ xác nhận qua DuckDB in-memory + mock `notify.send`.

## Ghi chú về vị trí commit

Worktree thực thi task này (`agent-a7c3eaf22aa6d3f77`) không thể checkout
trực tiếp `feat/c2-canh-bao-su-kien` vì branch đó đang được checkout ở
checkout dùng chung (`/Users/huynhhuutai/thcoding/vn-stock-daily`) —
git không cho phép 1 branch được checkout ở 2 worktree cùng lúc. Để
tránh đụng vào checkout dùng chung (có thể có tiến trình khác đang thao
tác), toàn bộ fix được thực hiện trên branch mới `c2-final-review-fix`,
tạo trực tiếp từ đúng commit `0f5150f`:

```
git checkout -b c2-final-review-fix 0f5150f
```

2 commit fix nằm NGAY SAU `0f5150f`, fast-forward thẳng được vào
`feat/c2-canh-bao-su-kien` (không có commit nào khác chen giữa):

```
0f5150f  feat(c2): workflow event-alerts.yml, nghiệm thu trên production   <- base, không đổi
0efe35a  fix(c2): mark_events_alerted ghi atomic — sửa sự cố seed dở dang production
8334e91  fix(c2): fallback event_name_vi khi event_title_vi NULL — không lộ "None" vào tin
```

Người điều phối cần fast-forward (hoặc merge) `feat/c2-canh-bao-su-kien`
tới `8334e91` từ checkout dùng chung.

## Tóm tắt 3 finding đã sửa

### IMPORTANT #1 — `event_title_vi` NULL rò rỉ literal "None" vào tin Telegram

- **File sửa:** `alert_events.py`
  - `fetch_unalerted_events`: thêm `event_name_vi` vào SELECT.
  - `format_message`: `title = e.get('event_title_vi') or e.get('event_name_vi') or '(không có tiêu đề)'`
    thay vì `e['event_title_vi']` trực tiếp.
- **Test mới** (`tests/test_alert_events.py`):
  - `test_format_message_dung_event_name_vi_khi_event_title_vi_null` —
    title NULL, name_vi có nội dung → tin dùng name_vi.
  - `test_format_message_placeholder_khi_ca_hai_title_deu_null` — cả hai
    NULL → placeholder tiếng Việt, không có chuỗi `"None"`.
  - Cả hai đã xác nhận **RED** trên code cũ (`AssertionError`, thực tế
    thấy đúng `"HPG — None"` trong output) trước khi sửa nguồn, **GREEN**
    sau khi sửa.
- Phát hiện phụ trong lúc test RED: NULL VARCHAR đi qua `.df()` cho ra
  Python `None` thuần (không phải `NaN`), khác với cột DATE NULL (ra
  `pandas.NaT`, đã xử lý ở fix round 1). Nên `or`-chaining hoạt động
  đúng cho ca này, không cần `pd.isna()` như với ngày tháng.

### IMPORTANT #2 — `mark_events_alerted` ghi partial khi lỗi giữa batch

- **File sửa:** `src/warehouse.py`, hàm `mark_events_alerted`.
- Đổi từ `con.executemany(...)` sang 1 câu `INSERT ... SELECT` atomic
  (qua `con.register(df) + INSERT INTO alert_sent_log SELECT ... FROM
  df_alert + con.unregister(...)`), đúng idiom mọi hàm ghi hàng loạt
  khác trong file (`insert_corporate_events`, `upsert_shareholders`,
  `upsert_prices`...).
- Hành vi PRIMARY KEY trùng: vẫn raise `duckdb.ConstraintException` —
  test cũ `test_mark_events_alerted_khong_the_ghi_trung_event_id` giữ
  nguyên, không sửa, vẫn pass.
- `split_symbols_by_seed_status` **không bị đụng** — đúng như lưu ý của
  reviewer (không đổi sang "so khớp số lượng", giữ nguyên logic "có mặt
  hay không" theo từng mã).

### IMPORTANT #3 — Thiếu test canh partial write

- **Test mới** (`tests/test_warehouse_alerts.py`):
  `test_mark_events_alerted_that_bai_giua_chung_khong_ghi_dong_nao` —
  seed trước `e2`, sau đó gọi batch `[e1, e2, e3]` (PK trùng ở GIỮA
  batch, không phải đầu/cuối) → assert `e1` KHÔNG được ghi.
- Xác nhận **RED** trên code cũ bằng cách `git stash` tạm file
  `src/warehouse.py` (quay lại bản `executemany`), chạy test: FAIL đúng
  như dự đoán —`assert 1 == 0` (thực tế `e1` VẪN được ghi trước khi gặp
  lỗi ở `e2`, xác nhận đúng cơ chế partial-write của `executemany`).
  `git stash pop` khôi phục fix, chạy lại: **GREEN**, 5/5 test pass.

## Trình tự thực hiện

1. Fix #2 (atomic write) trước — vì #3 phụ thuộc vào nó.
2. Fix #3 (test regression) — viết cùng lúc, xác nhận RED→GREEN qua
   `git stash`/`git stash pop`.
3. Commit nhóm #2+#3: `0efe35a`.
4. Fix #1 (event_title_vi fallback) — viết test trước, xác nhận RED
   trên code gốc, sửa nguồn, xác nhận GREEN.
5. Commit riêng cho #1: `8334e91`.
6. Chạy `pytest tests/ -q` toàn bộ sau MỖI nhóm thay đổi.

## Kết quả test

| Mốc | Kết quả |
|---|---|
| Baseline (`0f5150f`, trước khi sửa) | 331 passed, 2 xfailed |
| Sau fix #2 + #3 | 332 passed, 2 xfailed |
| Sau fix #1 | 334 passed, 2 xfailed |

Không có test nào bị mất hoặc bị sửa để "cho pass" — chỉ thêm mới.
`test_mark_events_alerted_khong_the_ghi_trung_event_id` (test cũ, canh
hành vi PRIMARY KEY) giữ nguyên 100%, vẫn pass sau khi đổi
`mark_events_alerted` sang atomic.

## Ràng buộc đã tuân thủ

- Không chạy `alert_events.py` thật ở bất kỳ bước nào trong task này.
- Không kết nối MotherDuck (`WAREHOUSE_DB`/`motherduck_token` không được
  set/dùng trong suốt quá trình sửa và test).
- Toàn bộ test chạy qua DuckDB in-memory (`duckdb.connect(":memory:")`)
  + mock `alert_events.notify`/`unittest.mock.patch`.
- Không đụng `split_symbols_by_seed_status` (đúng lưu ý của reviewer).
- Toàn bộ docstring/comment/commit message bằng tiếng Việt.

## Finding không xử lý được

Không có — cả 3 finding Important đều đã sửa, có test RED→GREEN xác
nhận, và toàn bộ test suite pass không hồi quy.

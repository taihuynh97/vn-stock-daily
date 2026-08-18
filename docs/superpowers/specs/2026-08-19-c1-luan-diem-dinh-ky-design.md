# C1 — Luận điểm đầu tư định kỳ (tool `get_thesis_update`)

> Thiết kế chốt ngày 2026-08-19. Tiếp nối mảng A (chấm điểm, MCP 7 tool) và
> mảng B — B1 (sự kiện DN/cổ tức/sở hữu), B2 (BCTC chi tiết) — cả hai đã
> merge vào `main`, tổng 10 tool MCP.
>
> Mảng C trong spec gốc (`2026-08-09-fundamental-analysis-platform-design.md`
> §2.2) gồm 2 phần: "báo cáo luận điểm đầu tư định kỳ" và "cảnh báo theo sự
> kiện thay bản tin hằng ngày". Tài liệu này đặc tả **C1** = báo cáo luận
> điểm định kỳ. Cảnh báo sự kiện (C2, thay `main.py`/`digest.py`/`daily.yml`)
> để dành spec riêng sau.

---

## 1. Bối cảnh & mục tiêu

Nền tảng hiện tại (10 tool MCP) cho phép agent hội thoại tra cứu ĐIỂM SỐ
hiện tại, LỊCH SỬ định giá, BCTC chi tiết, sự kiện DN, cơ cấu sở hữu — nhưng
mỗi tool trả về một LÁT CẮT (snapshot hiện tại hoặc chuỗi thời gian đầy đủ),
không có khái niệm "so với lần xem trước, cái gì MỚI". Với luồng sử dụng
"định kỳ" (người dùng hỏi lại về một mã mỗi quý/tháng), agent phải tự nhớ
lần hỏi trước là gì rồi tự so sánh — không có công cụ hỗ trợ.

**Mục tiêu C1:** một tool MCP mới, `get_thesis_update(symbol, since_date)`,
trả về CHÊNH LỆCH so với một mốc thời gian (mặc định 90 ngày trước) — sự
kiện/cổ tức mới, kỳ BCTC mới công bố, thay đổi cơ cấu sở hữu, xu hướng tài
chính gần nhất — để agent tổng hợp thành đoạn cập nhật luận điểm đầu tư.
**Không sinh sẵn văn bản** (agent tự viết dựa trên dữ liệu cấu trúc trả về —
đúng nguyên tắc "Fact có cấu trúc, chặn LLM bịa số" đã ghi trong spec gốc
§7.9, và đúng pattern của cả 10 tool hiện có).

---

## 2. Khảo sát nguồn — đã kiểm tra thật trước khi thiết kế

**Phát hiện quan trọng nhất: `mart_stock_scorecard` KHÔNG có lịch sử.**
Đọc `transforms/models/marts/mart_stock_scorecard.sql`: bảng
`materialized='table'`, build lại từ đầu mỗi lần `dbt build`, không có cột
snapshot/thời điểm — nó LUÔN là "hiện tại". Không có cơ chế dbt snapshot nào
lưu lịch sử điểm số qua thời gian (đã kiểm `find transforms -iname
"*snapshot*"` — chỉ có `mart_sector_snapshot`/`int_ownership_snapshot`, cả
hai đều là "mới nhất", không phải lịch sử SCD).

→ **C1 KHÔNG diff được điểm số** ("quality_score đổi từ X thành Y") — dữ
liệu đó không tồn tại, và tạo mới (lưu lịch sử điểm số) là một hệ thống
riêng, ngoài phạm vi C1 (xem §5 "Không làm"). C1 chỉ trả điểm số HIỆN TẠI
làm ngữ cảnh, còn phần "chênh lệch" tập trung vào những gì THẬT SỰ có mốc
thời gian trong dữ liệu đã ingest.

**Bốn nguồn có timestamp thật, dùng được cho "since_date":**

| Nguồn | Cột thời gian | Đã kiểm chứng |
|---|---|---|
| `fct_financial_quarterly` | `year`/`quarter`/`period_end_date` | Chuỗi quý thật, đo HPG: 2018 Q1 → 2026 Q2 liên tục, có `revenue_ttm`/`earnings_ttm`/tăng trưởng |
| `int_distribution_event` | `exright_date` | Đã dùng trong `get_distribution_history`, có sẵn pattern lọc theo ngày |
| `raw_financial_statement` (B2) | `ingested_at`, `period_label` | Mỗi lần ingest mới có `ingested_at` mới — lọc được "kỳ nào MỚI xuất hiện kể từ since_date" |
| `stg_shareholder`/`stg_officer` (B1) | `snapshot_date` | **Đo thật trên `md:vn_market` (2026-08-19): đã có ĐÚNG 2 snapshot (2026-08-17, 2026-08-18)** — đủ để tính chênh lệch thật, dù khoảng cách hiện tại còn ngắn (1 ngày, sẽ giãn ra theo nhịp monthly thật) |

**`int_ownership_snapshot` không dùng được trực tiếp** cho việc so sánh 2
mốc — đọc `transforms/models/intermediate/int_ownership_snapshot.sql`: model
này CỐ Ý chỉ lấy `max(snapshot_date)` mỗi mã (comment gốc: "Cô đặc cơ cấu sở
hữu theo snapshot MỚI NHẤT mỗi mã"). C1 phải tự tính lại phép gộp
(`top1_pct`/`top5_pct`/`total_disclosed_pct`/`insider_pct`) TRỰC TIẾP từ
`stg_shareholder`/`stg_officer` ở CẢ HAI mốc thời gian (baseline + latest),
không tái dùng `int_ownership_snapshot`.

**`get_stock_profile` là template đúng cho phần điểm số hiện tại:** đọc
`mcp_server/tools.py:180-193` — query thẳng
`mart_stock_scorecard WHERE symbol = ?` (không qua `scoring.screen()`/
`apply_universe()`, vốn áp bộ lọc universe theo PROFILE cụ thể và có thể
loại bỏ chính mã đang hỏi nếu nó không đạt tiêu chí profile đó). C1 dùng lại
đúng pattern trực tiếp này cho điểm số hiện tại — không gọi `scoring.screen`.

---

## 3. Phạm vi

**Trong phạm vi:**

- 1 tool MCP mới: `get_thesis_update(symbol, since_date=None) -> dict`.
- 4 khối "chênh lệch kể từ `since_date`": sự kiện phân phối mới, kỳ BCTC mới
  công bố, thay đổi cơ cấu sở hữu (baseline vs mới nhất), xu hướng tài chính
  các quý mới (từ `fct_financial_quarterly`).
- 1 khối điểm số HIỆN TẠI (context, không phải diff) — 5 điểm thành phần từ
  `mart_stock_scorecard`, cùng nguồn `get_stock_profile` đang dùng.
- `since_date` mặc định 90 ngày trước ngày hiện tại nếu không truyền vào
  (khớp nhịp "định kỳ tháng/quý").

**Không làm** (ghi rõ để không hiểu nhầm ở review):

- Không lưu lịch sử điểm số (không có bảng snapshot điểm mới) — đã xác nhận
  không cần thiết ở §2, để dành nếu sau này có nhu cầu cụ thể.
- Không sinh văn bản luận điểm (không gọi LLM server-side) — agent tự viết
  từ dữ liệu cấu trúc trả về.
- Không làm job định kỳ tự đẩy báo cáo (C1 là tool pull theo yêu cầu, không
  phải push theo lịch) — không đụng `main.py`/`digest.py`/`daily.yml`.
- Không đổi 10 tool hiện có, không đụng `src/scoring.py`, không đụng bất kỳ
  bảng nguồn/mart nào — C1 chỉ ĐỌC, không tạo bảng/model dbt mới.
- Không làm C2 (cảnh báo theo sự kiện) — spec riêng sau.

---

## 4. Kiến trúc

Không có ingest mới, không có bảng raw/staging mới, không có rủi ro ổn định
API cần kiểm trước (khác B1/B2) — toàn bộ dữ liệu C1 cần đã có sẵn trong
warehouse qua A1/A2/B1/B2. C1 thuần là 1 hàm Python mới trong
`mcp_server/tools.py` + 1 khối đăng ký trong `mcp_server/server.py`, đúng
pattern 10 tool hiện có.

### 4.1 Chữ ký & hợp đồng trả về

```
get_thesis_update(symbol: str, since_date: str | None = None) -> dict
```

`since_date`: chuỗi `"YYYY-MM-DD"`. Nếu `None`, mặc định = hôm nay trừ 90
ngày.

```json
{
  "symbol": "HPG",
  "since_date": "2026-05-21",
  "current_scores": {
    "value": 62.0, "quality": 74.5, "growth": 58.0,
    "dividend": 40.0, "safety": 66.0
  },
  "financial_trend": {
    "quarters": [
      {"year": 2026, "quarter": 1, "revenue_ttm": ..., "earnings_ttm": ..., "revenue_yoy": ..., "earnings_yoy": ...},
      {"year": 2026, "quarter": 2, "revenue_ttm": ..., "earnings_ttm": ..., "revenue_yoy": ..., "earnings_yoy": ...}
    ],
    "n_new_quarters": 2
  },
  "new_distribution_events": [
    {"exright_date": "2026-06-17", "distribution_type": "CASH_DIVIDEND",
     "cash_per_share": 1000, "stock_ratio": null, "event_title_vi": "..."}
  ],
  "new_statement_periods": [
    {"statement_type": "income_statement", "period_type": "quarter", "period_label": "2026-q2", "ingested_at": "2026-08-18T..."}
  ],
  "ownership_change": {
    "baseline_snapshot_date": "2026-08-17",
    "baseline_is_fallback": false,
    "latest_snapshot_date": "2026-08-18",
    "top1_pct": {"baseline": 34.0, "latest": 34.0, "delta": 0.0},
    "top5_pct": {"baseline": 51.9, "latest": 51.9, "delta": 0.0},
    "total_disclosed_pct": {"baseline": 51.9, "latest": 51.9, "delta": 0.0},
    "insider_pct": {"baseline": 12.1, "latest": 12.1, "delta": 0.0}
  },
  "data_quality": {
    "has_ownership_baseline": true,
    "n_snapshots_available": 2
  },
  "price_as_of": "...", "ratio_as_of": "..."
}
```

**`ownership_change.baseline_is_fallback`**: nếu KHÔNG có snapshot nào
`<= since_date` (ca thực tế hiện tại — chỉ có 2 snapshot cách nhau 1 ngày,
`since_date` mặc định 90 ngày trước chắc chắn không có snapshot nào cũ
bằng), dùng snapshot CŨ NHẤT hiện có làm baseline thay vì trả lỗi/rỗng, và
đặt cờ này `true` — agent biết đây không phải đúng "since_date" mà là "sớm
nhất có". Nếu chỉ có ĐÚNG 1 snapshot (baseline == latest), toàn bộ delta =
0 một cách hợp lệ (không phải lỗi) — không cần xử lý đặc biệt, phép trừ tự
nhiên ra 0.

**Mã không tồn tại hoặc không có dữ liệu nào ở CẢ 4 khối** (mã quá mới,
chưa từng ingest) → trả `{"error": f"Không tìm thấy mã {sym} trong
warehouse.", **db.as_of(con)}`, giống pattern các tool khác — không trả một
payload rỗng mập mờ.

### 4.2 Nguồn dữ liệu từng khối

- `current_scores`: `SELECT value_score, quality_score, growth_score,
  dividend_score, safety_score FROM mart_stock_scorecard WHERE symbol = ?`
  — copy nguyên pattern từ `get_stock_profile`.
- `financial_trend`: `SELECT year, quarter, revenue_ttm, earnings_ttm,
  revenue_yoy, earnings_yoy FROM fct_financial_quarterly WHERE symbol = ?
  AND period_type = 'quarter' AND period_end_date > ? ORDER BY year,
  quarter` (tham số = `since_date`).
- `new_distribution_events`: tái dùng đúng câu query của
  `get_distribution_history` (bảng `int_distribution_event`), thêm điều
  kiện `AND exright_date > ?`.
- `new_statement_periods`: `SELECT DISTINCT statement_type, period_type,
  period_label, max(ingested_at) as ingested_at FROM raw_financial_statement
  WHERE symbol = ? AND ingested_at > ? GROUP BY 1,2,3`.
- `ownership_change`: 2 truy vấn riêng vào `stg_shareholder`/`stg_officer`
  (không qua `int_ownership_snapshot`) — mỗi truy vấn nhận 1 `snapshot_date`
  cụ thể (baseline, latest), tính lại đúng phép gộp mà
  `int_ownership_snapshot.sql` đang làm (`sum(share_own_percent)`,
  `max` cho top1, `sum` top5 theo `row_number()`, `sum(officer_own_percent)`
  cho insider) — viết trực tiếp trong hàm Python, KHÔNG sửa model dbt.

---

## 5. Kiểm thử

| Test | Canh lỗi gì |
|---|---|
| `current_scores` khớp đúng `get_stock_profile` cho cùng mã | Sai lệch pattern truy vấn |
| `financial_trend` chỉ trả quý SAU `since_date`, đúng thứ tự | Lọc sai điều kiện thời gian |
| `new_distribution_events` lọc đúng `exright_date > since_date`, mã không có sự kiện mới trả mảng rỗng (không phải lỗi) | Nhầm "không có gì mới" với "lỗi" |
| `new_statement_periods` phát hiện đúng kỳ MỚI xuất hiện, không lặp kỳ cũ | Sai điều kiện `ingested_at` |
| `ownership_change` tính đúng delta khi CÓ snapshot trước `since_date` | Sai phép gộp thủ công so với `int_ownership_snapshot.sql` |
| `ownership_change` dùng fallback đúng khi KHÔNG có snapshot trước `since_date`, đặt `baseline_is_fallback=true` | Ca thực tế hiện tại (chỉ 2 snapshot gần nhau) — phải test đúng ca này, không giả định có snapshot cũ |
| `ownership_change` khi baseline == latest (chỉ 1 snapshot) trả delta = 0 hợp lệ | Chia/trừ lỗi khi 2 mốc trùng nhau |
| `since_date=None` mặc định đúng 90 ngày trước | Sai giá trị mặc định |
| Mã không tồn tại trả `error`, không trả payload rỗng mập mờ | Đúng pattern 10 tool hiện có |
| Gọi qua `mcp.call_tool()` thật, không chỉ hàm Python trần | Bài học A3 I1 — crash tầng serialize JSON chỉ lộ qua đường gọi thật |
| Fixture khớp đúng schema thật (đủ cột `stg_shareholder`/`stg_officer`/`fct_financial_quarterly`/`raw_financial_statement`) | Bài học A3 I2/B1/B2 — fixture sai khiến test luôn xanh |
| Đối chiếu tay ≥1 mã thật trên production (ví dụ HPG) — `financial_trend`/`ownership_change` khớp số liệu đã biết | Không dùng dữ liệu tổng hợp thay cho xác nhận thật khi có thể chạy được |

---

## 6. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Chỉ 2 snapshot sở hữu, cách nhau 1 ngày — `ownership_change` hiện tại gần như luôn delta≈0 | Đã biết, thấp | Không phải lỗi — cơ chế đúng, giá trị sẽ hiện rõ khi có nhiều snapshot monthly hơn theo thời gian. `baseline_is_fallback` giúp agent hiểu đúng tình trạng |
| Tự viết lại phép gộp ownership (không tái dùng `int_ownership_snapshot`) có thể lệch với model dbt nếu công thức đổi sau này | Trung bình | Test đối chiếu trực tiếp giữa kết quả tool (baseline=latest) và `int_ownership_snapshot` hiện có — phải khớp tuyệt đối |
| `fct_financial_quarterly` có cả dòng NĂM (`quarter=5`) lẫn dòng QUÝ — lọc sai `period_type` sẽ trộn hai loại | Thấp, đã có tiền lệ sửa (final review B2-adjacent) | Lọc rõ `period_type = 'quarter'`, viết test xác nhận không lẫn dòng năm |

---

## 7. Tiêu chí hoàn thành C1

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` |
| 2 | `ownership_change` khớp `int_ownership_snapshot` khi baseline=latest | Test đối chiếu |
| 3 | `financial_trend` không lẫn dòng năm (`quarter=5`) | Test lọc `period_type` |
| 4 | Tool trả đúng cho ≥1 mã thật trên production (ví dụ HPG), đối chiếu tay ≥1 con số cụ thể mỗi khối | Nghiệm thu cuối, gọi qua `mcp.call_tool()` |
| 5 | Tool 11/11 (cùng 10 tool cũ) đạt qua `scripts/check_mcp_tools.py` trên production thật | Nghiệm thu cuối |
| 6 | Không đổi hành vi 10 tool cũ, không đụng `mart_stock_scorecard`/`src/scoring.py`/bảng nguồn nào | Đối chiếu diff |

---

## 8. Sau C1

- **C2 — cảnh báo theo sự kiện**, thay `main.py`/`digest.py`/`daily.yml` —
  spec riêng, tận dụng `raw_corporate_event` (B1) làm nguồn trigger.
- **Lưu lịch sử điểm số** (nếu có nhu cầu cụ thể diff điểm số thật, không
  chỉ dữ liệu nền) — cân nhắc dbt snapshot hoặc bảng snapshot riêng, việc
  lớn hơn C1 nhiều, chỉ làm khi có use case rõ ràng cần nó.

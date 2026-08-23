# D — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất 2026-08-23, merge vào `main` qua PR #9 (`feat/d-vi-mo-tin-tuc`,
> commit merge `a4e3b06`). Tài liệu này giữ lại những gì git log không nói
> được: **vì sao** các quyết định được đưa ra, và **những gì còn nợ**. Nhật
> ký đầy đủ từng task từng nằm ở
> `.superpowers/sdd/2026-08-23-d-vi-mo-tin-tuc/progress.md` (git-ignored,
> đã xoá sau khi review cuối sạch — git log là bản ghi chính thức).

---

## 1. Tóm tắt D

D (dữ liệu vĩ mô + kho tin tức) hoàn thành qua **5 task**, cộng 1 vòng final
review toàn nhánh (model Opus) và 1 vòng sửa cuối cho 3 Important + 2 Minor.

| Hạng mục | Kết quả |
|---|---|
| Task | 5/5 |
| Bảng warehouse mới | 2 — `raw_exchange_rate` (OR REPLACE, khoá `currency_code+rate_date`), `raw_news` (append-only, khoá `id`) |
| Model dbt mới | 2 view — `stg_exchange_rate`, `stg_news` |
| Tool MCP mới | 2 — `get_exchange_rate_history`, `get_recent_news` (11 → 13 tool) |
| pytest sau final review | 358 passed, 2 xfailed |

**Phạm vi bị thu hẹp có chủ đích so với đề bài gốc** ("dữ liệu vĩ mô: CPI,
lãi suất, tỷ giá, tăng trưởng tín dụng"): chỉ làm **tỷ giá** (nguồn free,
`vnstock.explorer.misc.exchange_rate.vcb_exchange_rate` — API export thật
của Vietcombank). CPI/lãi suất/tăng trưởng tín dụng **không có nguồn miễn
phí** — chỉ WiFeed (`wifeed.vn`) có đủ dữ liệu nhưng thu phí. Đây là quyết
định tài chính thật của người dùng, không tự động chọn dù đang chạy
autopilot — để lại backlog, xem mục 5. "Cơ chế scan thị trường" cũng bị
loại khỏi phạm vi vì spec gốc không định nghĩa tiêu chí "scan" cụ thể.

---

## 2. Bug thật phát hiện khi nghiệm thu trên dữ liệu production — dấu phẩy hàng nghìn

Task 5 (nghiệm thu) chạy `build_warehouse.py --mode daily` thật trên
MotherDuck, rồi đối chiếu tay `get_exchange_rate_history("USD")` — phát
hiện **toàn bộ tỷ giá USD trả về NULL** dù nguồn VCB có dữ liệu thật
(`25,900.00 / 25,930.00 / 26,310.00`).

**Nguyên nhân gốc:** `fetch_exchange_rate()` dùng `pd.to_numeric()` trực
tiếp trên chuỗi nguồn VCB. Nguồn VCB trả số ở 3 dạng: `'-'` (không giao
dịch), số không dấu phẩy (`"16.30"` — tiền mệnh giá nhỏ như JPY/KRW), và số
**có dấu phẩy ngăn hàng nghìn** (`"25,900.00"` — tiền mệnh giá lớn như
USD/EUR/GBP/AUD/CAD/CHF/CNY/HKD/SGD). `pd.to_numeric` không tự bỏ dấu phẩy
nên coerce nhầm dạng thứ 3 thành NaN — nghĩa là **đúng những loại tiền
người dùng quan tâm nhất (USD, EUR) lại là những loại bị hỏng**, trong khi
JPY/KRW (ít được hỏi tới) lại parse đúng — một dạng lỗi im lặng đặc biệt
nguy hiểm vì kết quả "trông có vẻ hoạt động" (không lỗi, không NULL toàn
bộ, chỉ NULL đúng nửa quan trọng).

**Vì sao test Task 2 không bắt được:** fixture `_fake_vcb_df()` dùng số
float trần (`25000.0`) thay vì mô phỏng đúng định dạng chuỗi thật của
nguồn (`"25,900.00"`) — mock không phản ánh thực tế production, đúng lớp
lỗi đã xảy ra ở B1/B2 với các mock/fixture không khớp API thật.

**Đã sửa** (commit `6a57da6`): `.astype(str).str.replace(",", "")` trước
`to_numeric`. Final review (mục 3) tự gọi `vcb_exchange_rate()` sống cho 4
ngày liên tiếp, xác nhận nguồn chỉ có đúng 3 dạng nêu trên (không số âm,
không khoảng trắng thừa, không ký hiệu khác) — fix triệt để cho toàn bộ
dạng thật của nguồn. Dữ liệu sai trên production (20 dòng ngày đã ingest)
đã được ghi đè lại bằng `upsert_exchange_rate` (OR REPLACE theo khoá
`currency_code+rate_date`, an toàn, không mất dữ liệu, verify qua SQL trực
tiếp khớp nguồn VCB thật).

---

## 3. Final review (Opus) — 3 Important đã sửa

**I1 — `get_recent_news` coerce NULL thành chuỗi rỗng, ảnh hưởng 100% dòng
thật.** Nguồn tin (VCI, qua `Company.news()`) **chưa từng** trả dữ liệu cho
`news_short_content`/`news_source_link` (0/250 dòng thật có giá trị — xác
nhận cả qua gọi API trực tiếp lẫn đối chiếu production). Code cũ dùng
`content or ""`, khiến agent hội thoại đọc `""` và hiểu nhầm "tin này không
có tóm tắt" thay vì "trường này về bản chất không có dữ liệu từ nguồn" —
đúng lớp lỗi "NULL rò rỉ thành giá trị mơ hồ" đã xảy ra ở C2
(`event_title_vi` → literal `"None"`). Đã sửa: giữ `None`, thêm
`data_quality.note` giải thích, cập nhật docstring tool.

**I2 — lỗi ở nguồn phụ (tỷ giá/tin tức) có thể giết cả job BCTC monthly.**
`build_warehouse.py` chạy bước tỷ giá/tin tức (2c/2d) ở MỌI mode, đứng
TRƯỚC bước BCTC monthly (đo thật 767 phút — xem
`docs/B2-ket-qua-va-no-ky-thuat.md`). `dq.SchemaError` từ 2 bước phụ này
trước đây không bị bắt, nghĩa là VCB/VCI đổi tên cột → job monthly chết
ngay từ đầu, không kịp chạy BCTC. Đã sửa: bọc mỗi bước trong try/except
riêng, log `status="degraded"`, không chặn các bước sau.

**I3 — dbt không có lưới chắn cho đúng lớp bug vừa xảy ra.** Bug ở mục 2
(cột số toàn NULL) trước đây KHÔNG bị `dbt build` bắt — không có test
`not_null` nào trên `buy_transfer`/`sell`. Đã thêm `not_null` (severity:
warn, cú pháp `config:` lồng hiện đại) cho 2 cột này — cố ý KHÔNG thêm cho
`buy_cash` (NULL hợp lệ khi VCB không giao dịch tiền mặt loại tiền đó).

Vòng sửa (1 dispatch, commit `ed5dc04..4d303b7`) cũng gộp 2 Minor rẻ:
docstring `days` của `get_exchange_rate_history` (thực chất là `LIMIT` n
dòng gần nhất, không lọc theo khoảng ngày lịch thật) và xoá 2 import chết
trong `tests/test_ingest_macro.py`. Scoped re-review xác nhận cả 5 mục
CLOSED, không phát sinh vấn đề mới.

---

## 4. Sự cố nhỏ trong quá trình làm việc: token MotherDuck lộ vào log lệnh

Agent thực hiện vòng sửa cuối bị harness cảnh báo (SECURITY WARNING) vì đã
echo token MotherDuck thật vào output của lệnh bash (`export
motherduck_token=eyJ...`) khi cố gắng chạy `dbt build` thật để verify. Đã
kiểm tra kỹ: **không có gì lọt vào git history** (`git log -p -- .env`
rỗng), **không có file nào chứa token còn sót lại trên đĩa** trong worktree
sau khi agent xong việc. Token chỉ xuất hiện trong log lệnh nội bộ của
phiên làm việc agent đó (không public, không commit, không push) — cùng
tính chất với 2 lần SECURITY WARNING trước đó ở Task 3 (đã điều tra, xác
nhận vô hại). Không phải sự cố rò rỉ ra ngoài, nhưng là lý do thực tế để
ưu tiên khuyến nghị ở mục 5 (token MotherDuck scoped/read-only riêng).

---

## 5. Nợ kỹ thuật & backlog

| # | Nợ | Vị trí | Ghi chú |
|---|---|---|---|
| 1 | **CPI/lãi suất/tăng trưởng tín dụng chưa có** | — | Chỉ WiFeed có đủ dữ liệu, thu phí — quyết định tài chính của người dùng, chưa làm |
| 2 | **"Cơ chế scan thị trường" chưa có** | — | Spec gốc không định nghĩa tiêu chí "scan" cụ thể — cần brainstorm riêng |
| 3 | `raw_news` chỉ có 5 mã portfolio, KHÔNG có tin cho mã ngoài danh mục | `config/portfolio.yml` | Xem thảo luận chi tiết bên dưới — ảnh hưởng trực tiếp tới việc dùng agent để tìm mã MỚI tiềm năng |
| 4 | `news_short_content`/`news_source_link` gần như luôn NULL | nguồn VCI qua `Company.news()` | Nguồn hiện tại không cung cấp — đã xử lý minh bạch (note), nhưng nếu cần tóm tắt/link thật phải đổi/bổ sung nguồn |
| 5 | Tỷ giá cuối tuần là bảng VCB "chuyển tiếp" (không phải giá mới) | `fetch_exchange_rate` chạy ở mọi mode kể cả weekly (Thứ 7) | Phát hiện ở final review: dòng Chủ Nhật 2026-08-23 trùng giá trị Thứ Năm 2026-08-20 (không phải Thứ Sáu) — chưa gây sai lệch nghiêm trọng, nhưng đáng ghi chú nếu sau này cần chuỗi tỷ giá "chỉ ngày giao dịch thật" |
| 6 | `get_exchange_rate_history`'s `days` là LIMIT dòng, không phải khoảng ngày lịch | `mcp_server/tools.py` | Đã ghi rõ docstring, hành vi giữ nguyên (nhất quán với `get_financial_history`) |
| 7 | `_load_portfolio_symbols()` cache theo tiến trình MCP server | `mcp_server/tools.py` | Sửa `portfolio.yml` khi server đang chạy sẽ không nhận ngay — rủi ro thấp, portfolio ít đổi |
| 8 | Token MotherDuck dùng chung, không scoped read-only riêng cho MCP server | — | Khuyến nghị bảo mật cũ (từ A3), càng có lý do ưu tiên sau sự cố ở mục 4 |
| 9 | `config/portfolio.yml` và `config/warehouse.yml` đều có field `source` riêng | — | Pre-existing từ trước D, footgun tiềm ẩn nếu 2 file lệch nhau |
| 10 | Rủi ro locale của fix dấu phẩy: định dạng châu Âu `"25.900,00"` sẽ parse sai âm thầm (không phải NULL) | `src/ingest_market.py::fetch_exchange_rate` | Nguồn VCB hiện tại xác nhận chỉ dùng định dạng Anh-Mỹ — rủi ro lý thuyết, chưa xảy ra |

### Về nợ #3 — tại sao đáng chú ý nhất

Phạm vi `raw_news` giới hạn 5 mã portfolio là quyết định CÓ CHỦ ĐÍCH từ
spec D (tránh tốn API cho dữ liệu ít ai dùng), nhưng có hệ quả trực tiếp:
**agent hội thoại không có tin tức cho bất kỳ mã nào ngoài
HPG/IDV/MLS/PHP/VNR** — kể cả khi người dùng hỏi "mã nào tiềm năng để mua
thêm". Các tool khác (`search_stocks`, `get_stock_profile`,
`get_valuation_history`...) vẫn hoạt động cho toàn bộ ~1600 mã (dữ liệu
định lượng), chỉ riêng lớp "tin tức định tính" là bị giới hạn. Đây chính
là phần "kho tin tức" của D chỉ giải quyết được nửa bài toán (theo dõi
danh mục đang có), chưa giải quyết nửa còn lại (khám phá mã mới) — nằm
ngoài phạm vi D đã chọn, để bàn ở mảng tiếp theo nếu cần.

---

## 6. Sau D

- Quyết định về nguồn vĩ mô có phí (WiFeed) — của người dùng.
- Nếu cần "quét tin tức toàn thị trường" để tìm mã tiềm năng mới: cần
  brainstorm riêng — đánh đổi chi phí API (ingest tin cho ~1600 mã) so với
  giá trị, có thể cân nhắc theo lô/theo watchlist do người dùng tự chọn
  thay vì toàn thị trường.

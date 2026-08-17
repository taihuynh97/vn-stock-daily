# B1 — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất 2026-08-17. Tài liệu này giữ lại những gì git log không nói được:
> **vì sao** các quyết định được đưa ra, và **những gì còn nợ**.
> Nhật ký đầy đủ nằm ở `.superpowers/sdd/2026-08-16-b1-su-kien-co-tuc-so-huu/progress.md`
> (git-ignored, chỉ có trên máy local).

---

## 1. Tóm tắt B1

B1 (sự kiện doanh nghiệp, phân phối cho cổ đông & cơ cấu sở hữu) hoàn thành
qua **7 task** theo TDD từng bước, cộng 1 vòng final review toàn nhánh (model
Opus, đọc toàn bộ diff + tự query production thật) và 1 vòng sửa cuối cùng.

| Hạng mục | Kết quả |
|---|---|
| Task | 7/7, TDD từng bước |
| Tool MCP mới | 2 — `get_distribution_history`, `get_ownership` (tổng 9/9 tool trả dữ liệu thật) |
| Bảng raw mới | 3 — `raw_corporate_event` (append-only), `raw_shareholder`, `raw_officer` (snapshot theo ngày) |
| Tổng số dòng 3 bảng raw (đo trên `md:vn_market`) | `raw_corporate_event` **57.160** · `raw_shareholder` **26.008** · `raw_officer` **7.387** |
| pytest sau vòng sửa cuối | 251 passed, 2 xfailed |

Hai cơ chế ghi được tách bạch có chủ đích: `insert_corporate_events` là
append-only (`INSERT ... WHERE NOT EXISTS`, không `OR REPLACE`) vì nguồn
`Company.events()` chỉ trả 50 sự kiện gần nhất và cửa sổ đó **trượt** theo
thời gian — ghi đè sẽ mất vĩnh viễn phần đã rơi khỏi cửa sổ. Ngược lại,
`upsert_shareholders`/`upsert_officers` dùng `INSERT OR REPLACE` theo
`(symbol, khoá, snapshot_date)` vì cổ đông/ban lãnh đạo là dữ liệu **trạng
thái** snapshot theo ngày, không phải dòng sự kiện.

---

## 2. Nợ chất lượng dữ liệu A1/A2 phát hiện qua B1

Task 5 dựng test đối chiếu chéo giữa `int_distribution_event` (sự kiện cổ
tức tiền mặt thật, theo ngày GDKHQ) và `stg_financial_ratio.dividend_yield`
(theo năm tài chính). Chạy trên dữ liệu thật: **116/1.117 mã có cổ tức tiền
mặt (~10,4%)** có sự kiện `CASH_DIVIDEND` thật nhưng không có năm nào
`dividend_yield > 0` rơi vào đúng khoảng thời gian tương ứng (đã cộng đệm
1 năm cho độ trễ chi trả). Phân rã nguyên nhân: 54 mã hoàn toàn không có
dòng `dividend_yield` (quý 5) nào rơi vào khoảng năm liên quan; 8 mã có
dòng nhưng giá trị NULL; 54 mã có dòng và có giá trị nhưng luôn bằng 0.

Hai ví dụ cụ thể (từ ledger Task 5):

- **AMP** có sự kiện `CASH_DIVIDEND` 1.000đ/CP, GDKHQ 2017-08-09, nhưng
  `dividend_yield` = 0 ở **TẤT CẢ 23 dòng** lịch sử (2018-2026).
- **TDN** có 8 sự kiện cổ tức đều đặn 2017-2024 (200đ → 2.100đ/CP, tăng dần
  — rõ ràng là cổ tức thật) nhưng `dividend_yield` **NULL suốt 2018-2023**.

Đây là vấn đề chất lượng dữ liệu của `raw_financial_ratio` (thuộc phạm vi
A1/A2), **ngoài phạm vi B1** — B1 không được sửa
`raw_financial_ratio`/`int_dividend_history`. Ruling: test
`assert_cash_dividend_matches_ratio` giữ nguyên logic (byte-for-byte khớp
brief gốc, xác nhận độc lập ở final review), hạ xuống `severity: warn` kèm
trần `error_if = '>150'` — vẫn phơi 116 mã lệch mỗi lần build, không chặn
CI, nhưng chặn nếu mức lệch tăng vọt (ví dụ parser phân loại sai một mớ sự
kiện).

Danh sách đầy đủ 116 mã lệch (symbol, số sự kiện cổ tức tiền mặt, năm sớm
nhất/muộn nhất của sự kiện) được chép nguyên văn từ
`.superpowers/sdd/2026-08-16-b1-su-kien-co-tuc-so-huu/task-5-mismatched-symbols.csv`
(workspace SDD git-ignored, sẽ bị xoá khi đóng plan) sang đây để không mất
dữ liệu chẩn đoán:

```csv
symbol,n_cash_events,min_ev_year,max_ev_year
AGE,4,2020,2023
ALC,2,2023,2024
AMP,1,2017,2017
AMV,2,2021,2021
ANI,2,2025,2026
APC,1,2017,2017
ASG,1,2020,2020
AUM,2,2017,2018
BCO,2,2021,2022
BCR,1,2021,2021
BGE,1,2021,2021
BHI,1,2022,2022
BHT,1,2017,2017
BMF,2,2016,2017
BMK,4,2021,2025
BMS,1,2018,2018
BQB,1,2016,2016
BQP,1,2025,2025
BSG,1,2018,2018
CAB,2,2023,2024
CBS,5,2021,2025
CCS,2,2024,2025
CEE,2,2016,2017
CIP,1,2017,2017
CJC,2,2017,2018
CRV,7,2022,2025
DAG,3,2017,2018
DAH,2,2017,2018
DCL,1,2018,2018
DCV,4,2024,2026
DGT,1,2017,2017
DIC,2,2016,2017
DKW,3,2022,2024
DLM,1,2023,2023
DMX,1,2026,2026
DNM,2,2017,2018
DXS,2,2018,2019
DXV,1,2019,2019
DZM,1,2017,2017
EIN,1,2018,2018
EVG,1,2018,2018
FLC,1,2018,2018
GAB,1,2018,2018
GDH,3,2024,2026
GTK,2,2017,2018
HAF,1,2018,2018
HCD,1,2023,2023
HCI,1,2017,2017
HFC,1,2017,2017
HHG,1,2017,2017
HID,1,2020,2020
HLT,2,2017,2018
HLY,2,2017,2018
HMR,3,2020,2024
HOM,1,2017,2017
HPA,4,2023,2026
HPI,1,2016,2016
HTH,1,2022,2022
HTK,1,2020,2020
HUX,1,2021,2021
IPA,1,2018,2018
KAC,1,2018,2018
KHX,8,2018,2026
KLM,1,2016,2016
KTW,5,2022,2024
LCD,4,2016,2019
LIG,1,2020,2020
LQN,2,2017,2019
MBT,1,2024,2024
MCD,1,2023,2023
MIE,1,2022,2022
MKV,1,2023,2023
MTL,1,2016,2016
MZG,1,2022,2022
NCG,1,2023,2023
NED,1,2025,2025
NEM,1,2023,2023
NHD,5,2021,2026
NHP,1,2016,2016
NSG,5,2016,2018
NTT,1,2017,2017
PCN,1,2016,2016
PET,1,2026,2026
PND,2,2017,2018
PVE,2,2016,2018
PXS,1,2017,2017
QCG,2,2017,2018
RGG,1,2025,2025
RYG,1,2024,2024
SGB,1,2017,2017
SIC,3,2018,2020
SJS,3,2017,2019
SLD,3,2018,2020
SRT,2,2017,2019
SSM,2,2017,2017
STD,8,2020,2026
STH,1,2019,2019
SVL,2,2016,2018
TAG,1,2017,2017
TCX,2,2024,2026
TDN,8,2017,2024
TIE,1,2017,2017
TKC,3,2016,2019
TLI,2,2016,2017
TNM,1,2017,2017
TTH,2,2017,2019
TVG,6,2017,2025
UDC,1,2018,2018
ULG,4,2023,2026
VEC,2,2017,2018
VIS,1,2018,2018
VMI,1,2016,2016
VTJ,2,2017,2018
VUA,2,2021,2022
VVN,1,2017,2017
VXB,2,2017,2018
```

> Ngoài ra, final review toàn nhánh (2026-08-17) đo được thêm một nguồn góp
> phần thu hẹp `min_ev_year`/`max_ev_year` của một số mã trong danh sách
> trên: `int_distribution_event` tự nó cũng lọc mất 323/9.932 sự kiện phân
> phối (3,36%) vì thiếu `exright_date` (xem mục 3 bên dưới) — đáng kiểm khi
> ai đó xử lý nợ A1/A2 này.

---

## 3. Độ lệch spec→plan đã phát hiện, chưa vá (M3, final review)

Spec §6.1 liệt kê payload `data_quality` của `get_distribution_history` gồm
`event_window_start`, `event_window_years`, `n_events`, và
**`unclassified_events`**. Plan (khi thêm `event_window_end`, một cải tiến
tốt so với spec) đã bỏ sót `unclassified_events`, và code làm đúng theo
plan — nên trường này **chưa từng tồn tại trong 7 task**, không phải một
regression mới.

Đây là **độ lệch có ý thức, phát hiện ở review cuối**, không sửa trong B1 vì
mức độ thấp: tín hiệu hệ thống ("bao nhiêu % sự kiện phân phối rơi vào
`ISS_KHAC`/`UNKNOWN_CODE`") đã có test dbt ngưỡng 5% canh ở tầng
`stg_corporate_event` riêng. Để dành nếu B2 hoặc mảng C cần trường
per-symbol này cho một use case cụ thể.

---

## 4. Nợ tiêu chí #4 — đa-snapshot chưa quan sát được qua 2 kỳ thật

Tiêu chí hoàn thành B1 #4 đòi "chạy job 2 lần: không giảm dòng ở
`raw_corporate_event`; `raw_shareholder` có ≥2 snapshot sau 2 kỳ". Nửa đầu
(append-only không giảm dòng) đã xác nhận trên production thật (refetch 5
mã: 57.160 → 57.160, `+0` dòng). Nửa sau **chưa đạt được vì lý do cấu
trúc**: mới có đúng **một** lần ingest monthly thật đã chạy (Task 4), nên
cơ chế đa-snapshot mới được chứng minh bằng unit test local
(`test_shareholder_giu_lich_su_qua_cac_snapshot`,
`test_officer_giu_lich_su_qua_cac_snapshot`), chưa quan sát được trên dữ
liệu thật qua 2 kỳ.

**Mục kiểm sau merge:** sau lần chạy `warehouse-monthly` kế tiếp, chạy

```sql
select count(distinct snapshot_date) from raw_shareholder;
select count(distinct snapshot_date) from raw_officer;
```

Kỳ vọng **≥ 2** cho cả hai bảng. Nếu vẫn là 1, kiểm tra workflow monthly có
thực sự chạy đến bước fetch shareholders/officers hay bị lỗi/timeout trước
đó.

---

> Bài học chung của B1: hai lỗi Important nghiêm trọng nhất tìm được ở vòng
> review cuối (`get_ownership` lọc officer sai snapshot; `int_distribution_event`
> lặng lẽ bỏ 323 sự kiện) đều chỉ lộ ra khi **query dữ liệu production thật**,
> không lộ ra khi đọc code hay chạy pytest trên fixture. Fixture đúng schema
> vẫn có thể đúng schema mà sai *tình huống* — hai bảng có thể lệch ngày
> snapshot với nhau chỉ xảy ra sau nhiều tháng vận hành thật, không phải
> điều fixture tĩnh viết một lần nghĩ ra được.

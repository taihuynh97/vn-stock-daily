# Q — Kết quả nghiệm thu & Nợ kỹ thuật (sửa lỗi chất lượng phân tích)

> Nhánh `fix/chat-luong-phan-tich`, làm ngày 2026-10-03, **chưa merge**. Spec:
> `docs/superpowers/specs/2026-10-03-chat-luong-phan-tich-design.md`. Kế hoạch:
> `docs/superpowers/plans/2026-10-03-chat-luong-phan-tich.md`. Hạn chế còn lại:
> `docs/han-che-nen-tang.md`.
>
> Toàn bộ nghiệm thu chạy trên **bản sao cục bộ** của `md:vn_market` (chép ngày 03/10, giá đến
> 02/10). Không có gì được ghi lên production từ nhánh này.

---

## 1. Vì sao có mảng Q

Người dùng phản ánh hai điều: kết quả phân tích thay đổi mỗi lần hỏi (03/09 khu công nghiệp,
10/09 ngân hàng, 12/09 rổ 11 mã), và PNJ — được phân tích ngày 12/09 ở 38.200 đ với điểm 7/7 —
sụp xuống 23.050 đ ngày 02/10 sau khi công bố dự kiến lỗ cả năm ~6.271 tỷ.

Rà soát tìm ra ba nhóm nguyên nhân: **quy trình** (sàng lọc tự viết SQL mỗi lần, không có cổng
biến cố), **dữ liệu sai nhưng trông hợp lệ** (giá, quý lỗ, định giá đóng băng), và **không có trí
nhớ có cấu trúc** (không lưu scorecard, không ghi lại phân tích).

## 2. Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Commit | 15 trên nhánh (spec, plan, 13 commit code/tài liệu) |
| Model dbt mới | 6 — `int_price_adjustment`, `int_quarterly_profit`, `int_valuation_current`, `mart_risk_flags`, `fct_index_daily`, `mart_scorecard_daily` (incremental) |
| Tool MCP mới | 2 — `screen_graham`, `get_risk_flags` (13 → 15) |
| Script mới | `scripts/repair_price_history.py` |
| pytest | 358 → **399 passed**, 2 xfailed |
| `dbt build` main trên bản sao (mốc) | 163 node — PASS 162, WARN 1 (lần build cục bộ thật đầu tiên, đóng nợ N14 của A2) |
| `dbt build` nhánh trên bản sao đã sửa | 183 node — PASS 181, WARN 2 |

## 3. Lỗi tìm thấy và cách sửa

### 3.1 Giá đóng cửa hằng ngày là giá tham chiếu (nghiêm trọng nhất)

`_find()` trả cột **đầu tiên** chứa **bất kỳ** từ khoá nào; cột `listing.*` đứng trước `match.*`
trong bảng giá VCI nên từ khoá "price" khớp `listing.ref_price`. Từ 07/06/2026 mọi giá đóng cửa
hằng ngày là giá đóng cửa của **phiên trước**; ngày GDKHQ còn là giá đã điều chỉnh (TRC 15/09:
close 20.150 < low 21.100).

| Đo (dòng có khớp lệnh, có high/low) | Trước | Sau |
|---|---|---|
| Tháng 5/2026 | 0,00% | 0,00% |
| Tháng 6–10/2026, close ngoài [low, high] | 21,0–28,6% | 0,29–0,35% |

Tính cả dòng không khớp lệnh (high/low = 0) thì tỷ lệ trước sửa là 52–63%.

**Sửa:** `_pick()` ưu tiên theo thứ tự ứng viên, khớp chính xác rồi khớp hậu tố. Mã không khớp
lệnh: close = giá tham chiếu, volume 0, OHLC NULL. Lưu thêm `ref_price` và 4 cột khối ngoại.
`dq.assert_ohlc_consistent` làm đỏ job khi >5% dòng có khớp lệnh vi phạm — lớp lỗi này đã chạy im
lặng 4 tháng.

### 3.2 Phiên ma ngày lễ

`is_trading_day()` chỉ loại thứ Bảy, Chủ nhật. Ngày 31/08–02/09/2026 bảng giá vẫn mang phiên 28/08
và job ghi thành 3 phiên mới (4.637 dòng, 100% chép phiên trước). **Sửa:** ngày giao dịch lấy từ
`listing.trading_date` của bảng giá; khác ngày chạy → bỏ qua. Script sửa lịch sử xoá phiên ma.

### 3.3 Giá không điều chỉnh sau chia/thưởng cổ phiếu

Lịch sử nạp bù ngày 07/06 đã được nguồn điều chỉnh tới ngày đó; dòng hằng ngày thì không. Mọi sự
kiện sau 07/06 tạo bước nhảy giả (TRC −75%, PHR −47%) trong `return_*`, MA, đỉnh/đáy 52 tuần,
volatility.

**Sửa:** `int_price_adjustment` phát hiện sự kiện bằng giá tham chiếu của sàn, không bằng bảng sự
kiện doanh nghiệp (đợt thưởng của TRC và PHR có trong bảng sự kiện nhưng **thiếu ngày GDKHQ**).
Mọi chỉ báo giá tính trên `adj_close`. Dòng nạp bù sau sự kiện không bị nhân hai lần (điều kiện
`ex_date > ngày loaded_at`).

| Test `assert_adjusted_returns_within_limits` (ngưỡng theo sàn, 120 ngày) | Trước sửa | Sau sửa |
|---|---|---|
| Dòng vượt biên độ | 47 | 2 |

Hai dòng còn lại đều trên UPCoM: TSJ +48% (09/06) và VGR +47% (26/06), vượt cả biên độ phiên đầu ±40% — cần đối chiếu riêng, chưa kết luận là lỗi.

**Mô phỏng phiên tương lai** (vì sau khi sửa, mọi dòng đã được nguồn điều chỉnh sẵn): thêm FPT ngày
05/10 thường và 06/10 GDKHQ cổ tức cổ phiếu 15%. Mô hình bắt sự kiện với hệ số 0,8698; mọi phiên
trước, kể cả lịch sử đã sửa từ 2024, được nhân hệ số; phiên 06/10 tăng 0,4% thay vì giảm 12,7%.

### 3.4 Giá tham chiếu UPCoM (phát hiện ở bước rà code)

Trên UPCoM, giá tham chiếu là **bình quân gia quyền phiên trước** làm tròn 100 đ, không phải giá
đóng cửa. Đo 29/09–02/10/2026:

| Sàn | Khớp cách tính mới | Khớp nếu so giá đóng cửa |
|---|---|---|
| HOSE | 98,1% | 98,1% |
| HNX | 98,6% | 98,6% |
| UPCoM | 99,4% | 82,6% |

Phần lệch còn lại của HOSE/HNX là mã có sự kiện sau ngày D (lệch đều một hệ số mọi ngày), không
phải lỗi. UPCoM chỉ ghi nhận sự kiện khi lệch >15% (`upcom_adjustment_min_deviation`): 3/2.972 dòng
vượt 15% trong cửa sổ đo và đều thuộc một mã lệch đều.

### 3.5 "Quý lỗ" đo lợi nhuận lũy kế 4 quý

`is_loss_making = after_tax_profit_margin < 0`, mà biên này của nguồn là TTM. `loss_quarters_12q`
vì thế đếm quý có TTM âm. PNJ 2026-Q2 lỗ 739 tỷ trên BCTC gốc nhưng biên TTM +5,6%, cột ghi 0.
103 mã có quý lỗ thật trong 4 quý bị ghi 0, trong đó 11 mã đủ thanh khoản (STB, PLX, GEX, EIB,
PNJ, OIL, BAF, HHS, VDS, AAS, TIG). Đây là lý do PNJ lọt bước "không quý nào lỗ" ngày 12/09.

**Sửa:** `int_quarterly_profit` đọc LNST từng quý từ BCTC gốc. Thành phần safety dùng
`loss_quarters_12q_actual`. Cột cũ giữ tên, được mô tả lại.

Phát hiện phụ: bản phân tích PNJ 12/09 ghi lỗ quý 2 là −283 tỷ; BCTC gốc ghi −739 tỷ (dòng thuế và
lợi nhuận khớp nhau).

### 3.6 Định giá đóng băng ở ngày chốt quý

P/E, P/B, vùng định giá và `value_score` trong scorecard dùng giá ngày chốt quý (30/06) trong khi
giá đã đến 02/10. Chia `last_close` cho EPS quý cũ còn sai khi có thưởng cổ phiếu sau ngày chốt —
PHR trông rẻ một nửa trong bảng 12/09 vì thế.

**Sửa:** `int_valuation_current` quy đổi bằng tỷ lệ giá điều chỉnh; thưởng cổ phiếu tự triệt tiêu.

| Mã | P/E ngày chốt (main) | P/E hiện tại, chưa sửa giá | P/E hiện tại, đã sửa giá | Cổng |
|---|---|---|---|---|
| PHR | 8,75 | 4,78 | 8,50 | qua |
| TRC | 10,29 | 3,33 | 12,89 | qua |
| PNJ | 5,56 | 2,18 | 2,04 | chờ BCTC |
| FPT | 11,83 | 10,54 | 11,51 | qua |

`value_score` sau sửa: 1.223 mã có điểm ở cả hai bản; 167 mã đổi hơn 10 điểm, 13 mã hơn 25 điểm.

### 3.7 Không có cổng biến cố

PNJ ngày 12/09: kho **đã có** quý 2 lỗ 739 tỷ và hai đăng ký bán của người nhà lãnh đạo (18 triệu
và 7 triệu cổ phiếu, công bố 04/09). Không bước nào đọc chúng.

**Sửa:** `mart_risk_flags` + tool `get_risk_flags`. Trong 189 mã đủ lớn và thanh khoản:

| risk_gate | Số mã |
|---|---|
| `cho_bctc_ke_tiep` | 37 |
| `doc_tin_truoc` | 88 |
| `qua` | 64 |

Cờ phổ biến nhất: pha loãng (64), giá giảm sâu (55), nội bộ đăng ký bán (35), LNST quý giảm mạnh
(24), quý lỗ (22). PNJ bị chặn với 4 cờ.

### 3.8 Sàng lọc không tất định

`config/graham_screen.yml` (version `2026-10-03.1`) + `src/graham_screen.py` + tool `screen_graham`.
Gọi hai lần trên cùng dữ liệu cho kết quả giống hệt (kiểm cả hai lăng kính).

| Lăng kính `gia_tri` | Còn lại |
|---|---|
| Vũ trụ | 164 |
| Có lãi, không quý lỗ thật | 129 |
| P/E hiện tại ≤ 15 | 99 |
| P/E × P/B ≤ 22,5 | 82 |
| Cổ tức ≥ 5 năm | 19 |
| Thanh toán hiện hành ≥ 1,5 (phi tài chính) | 17 |
| Biên an toàn ⅓ | 6 |

Trong 6 mã: 3 phân tích tiếp (PTB cần đọc tin, VHC, MSH), 3 bị chặn (ANV, DGC, LAS). Lăng kính
`tang_truong`: 135 → 110 → 41 → 23 → 20 → 20; 18 phân tích tiếp, 2 bị chặn (BFC, CTS).

Rổ 12/09 dưới cổng mới: PNJ và DGC bị chặn; PTB và DPG cần đọc tin; PHR và TRC không còn rẻ giả.

### 3.9 Hai tool mới không được đăng ký khi chạy thật (phát hiện ở bước rà code)

Hai tool khai báo **sau** `if __name__ == "__main__": mcp.run()`. `mcp.run()` chặn luồng nên khi
chạy `python -m mcp_server.server` chúng không tồn tại, trong khi mọi test (import module) xanh.
Đã đưa khối main xuống cuối và thêm test cấu trúc AST.

### 3.10 Lỗi DuckDB 1.5.3 gặp khi viết `int_quarterly_profit`

`select *` + lọc `where rn = 1` theo `row_number()` ở CTE sau, rồi cắt bớt cột, khiến DuckDB áp phép
ép kiểu INT của `period_label` lên `item_id` (Conversion Error 'attributable_to_parent_company' →
INT32). QUALIFY với cột tường minh vẫn dính. Viết lại bằng GROUP BY + `arg_min`. Các model cũ dùng
`row_number` đều liệt kê cột tường minh và đã đối chiếu ra kết quả đúng — chưa sửa, ghi vào nợ.

## 4. Thay đổi test cũ (và vì sao không phải "chỉnh test cho xanh")

Sau khi nạp lại lịch sử, ba test cũ đỏ. Mỗi test được thu hẹp về đúng lớp lỗi nó nhắm tới, có số đo:

- `assert_value_matches_volume`: dòng đã sửa có close **đã điều chỉnh** nhưng `value` là doanh số
  **thật** — close × volume không còn là phép thử hợp lệ (400 dòng, toàn mã có sự kiện sau ngày đó).
  Giờ chỉ xét dòng bảng giá mới (có `ref_price`) — vẫn bắt lỗi đơn vị ×1e6.
- `assert_price_in_vnd_range`: NAC khớp lệnh thật ở 60–90 đ (2019–2021) và 1.300 đ (2025). Giờ xét
  theo (mã, năm) và chỉ phiên có khớp lệnh — lỗi đơn vị thật nằm xen trong cùng giai đoạn.
- `assert_volatility_in_range`: PPI năm 2020 giao dịch 300↔400 đ (một bước giá = 33%). Giờ chỉ xét
  giá ≥ 1.000 đ; max đo được 0,168 (trước 0,169).

## 5. Script sửa lịch sử — số đo trên bản sao

| Hạng mục | Kết quả |
|---|---|
| Mã | 1.582 (1.554 xong, 28 lỗi — nguồn không còn dữ liệu, chủ yếu mã huỷ niêm yết) |
| Dòng ghi | 1.551.111 (trước 1.306.324 — nguồn trả lịch sử dài hơn mốc bắt đầu, vd NAC/PTG từ 2019) |
| Phiên ma xoá | 3 ngày, 4.637 dòng |
| Thời gian | 4.956 giây (~83 phút, ~3,1 giây/mã) |

## 6. Triển khai sau merge — người dùng quyết định

1. Merge PR. Lần chạy `warehouse.yml` kế tiếp tự thêm cột vào `raw_price_daily` (ALTER idempotent)
   và ghi giá đúng từ phiên đó.
2. Chạy **một lần**, ngoài giờ giao dịch:
   ```bash
   python scripts/repair_price_history.py --db md:vn_market            # xem kế hoạch
   python scripts/repair_price_history.py --db md:vn_market --apply    # ~83 phút
   ```
   Bị ngắt giữa chừng thì chạy tiếp bằng `--since "<mốc sửa in ra ở lần trước>"`.
3. Chạy workflow `dbt build` (hoặc đợi lần chạy hằng ngày). **Trước bước này `search_stocks` báo lỗi
   thiếu cột** `loss_quarters_4q_actual` vì các profile đã bật `exclude_recent_loss_quarters`.

Trước bước 2, giá production từ 07/06 vẫn lệch một phiên; dbt mới không làm tệ hơn (không có
`ref_price` → không có sự kiện → `adj_close = close`).

## 7. Nợ kỹ thuật

1. **Chưa chạy sửa lịch sử trên production** — quyết định của người dùng (ghi ~1,55 triệu dòng).
2. **UPCoM:** sự kiện nhỏ hơn 15% không được điều chỉnh.
3. **Sót sự kiện khi kho thiếu phiên** ngay trước ngày GDKHQ; test warn sẽ báo.
4. **28 mã nạp lại lỗi** giữ dòng cũ.
5. **`turnover_vnd` của dòng trước 06/2026** (không có `value`) dùng close đã điều chỉnh × volume
   chưa điều chỉnh — thấp hơn thật với mã có chia/thưởng về sau. Không ảnh hưởng thanh khoản 20/60
   phiên (đều có `value`).
6. **`loss_quarters_12q_actual`** thực tế thấy ~8 quý (cửa sổ BCTC của B2).
7. **`pe_current`** gồm cả cổ tức tiền sau ngày chốt trong hệ số (HOSE/HNX) — hơi cao, lệch cỡ tỷ suất cổ tức.
8. **Lỗi DuckDB 1.5.3** (mục 3.10) — theo dõi khi nâng DuckDB; tránh `select *` + lọc theo `row_number`.
9. **Khối ngoại** mới lưu ở raw, chưa mô hình hoá.
10. **CI** vẫn chỉ `dbt compile`. Cách build thật đã dùng ở đây: chép các bảng nguồn từ MotherDuck
    vào một file DuckDB rồi `WAREHOUSE_DB=<file> dbt build` — có thể đóng gói thành script nếu cần.
11. **`mart_scorecard_daily`** bắt đầu tích luỹ từ ngày merge; không có lịch sử trước đó.

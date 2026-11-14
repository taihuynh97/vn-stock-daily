# Bỏ vnstock, gọi thẳng API Vietcap/VCB — Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Các workflow GitHub chạy lại được và dữ liệu nạp vào warehouse giữ nguyên như trước, không còn phụ thuộc vnstock.

**Architecture:** Thêm gói `src/sources/` gồm một HTTP client dùng chung và các hàm lấy dữ liệu theo từng endpoint Vietcap (`trading.vietcap.com.vn`, `iq.vietcap.com.vn`) và VCB. `src/ingest_market.py` thay lời gọi lớp vnstock bằng các hàm này. Phần chuẩn hoá phía sau có thể giữ nguyên hoặc đơn giản hoá, miễn là **đầu ra các hàm `fetch_*` của ingest_market không đổi**. Đây là hợp đồng duy nhất, được kiểm bằng đáp án mẫu chụp từ vnstock 4.0.9 ngày 12/11/2026.

**Tech Stack:** Python 3.12, requests, pandas, pytest; thêm `openpyxl` (đọc file Excel tỷ giá VCB, trước đây đi kèm vnstock).

**Spec:** chưa có file riêng. Mô tả đã được duyệt trong hội thoại ngày 12/11/2026 và tóm tắt dưới đây.
- Bối cảnh: từ 10/11/2026 chỉ mục `vnstocks.com/api/simple` trả HTTP 410 cho vnstock 4.x. Mọi workflow fail ở `pip install` từ 09/11.
- Bước 1 là chụp đáp án mẫu (đã xong: `data/vnstock_golden_2026-11-12/` ở repo chính, gitignored, 101 lời gọi, gồm `frames/*.pkl` và `http/*.json`).
- Lớp mới trả về cùng tên cột, cùng đơn vị, nên ingest, dbt, MCP và lịch sử warehouse không đổi.
- Test so từng cột với đáp án mẫu.
- Ba đợt, mỗi đợt một PR: (1) danh sách mã, giá ngày, chỉ số, bảng giá, ICB, tỷ giá; (2) sự kiện, tin, hồ sơ công ty; (3) BCTC, ratio_summary, cổ đông, ban lãnh đạo, rồi dọn dẹp.

## Global Constraints

- **Không chép mã nguồn vnstock** (giấy phép "Custom (Personal Use)", repo đang public). Chỉ được đọc để biết endpoint, tham số và ý nghĩa trường dữ liệu, rồi tự viết lại.
- Không thêm phụ thuộc mới ngoài `openpyxl>=3.1`.
- Endpoint không cần API key. Header bắt buộc: `User-Agent` kiểu trình duyệt, `Referer: https://trading.vietcap.com.vn/`, `Origin: https://trading.vietcap.com.vn/`, `Accept: application/json, text/plain, */*`, `Content-Type: application/json`.
- Timeout `(10, 30)` giây. Thử lại tối đa 2 lần, nghỉ 5 giây rồi 15 giây, chỉ khi gặp lỗi kết nối, timeout, HTTP 429 hoặc 5xx. Không lặp lại kiểu vnstock thử 9 lần × 30 giây (xem docstring `ingest.apply_vnstock_timeout`).
- Mọi lời gọi mạng vẫn đi qua `ingest._throttle()` như hiện nay.
- Phản hồi `iq.vietcap.com.vn` có vỏ `{"status":200,"code":0,"msg":"Successful","data":...}`. `status`/`code` khác thì coi là lỗi (ném `SourceError`).
- Test offline: không test nào trong bộ mặc định được gọi mạng. Test gọi nguồn thật đánh dấu `@pytest.mark.network` và bị bỏ qua mặc định.
- Fixture commit vào repo phải nhỏ: phản hồi thô nén `.json.gz`, đầu ra mong đợi lưu `.json` (không dùng pickle, vì CI cài pandas mới nhất).
- Sau đợt 1, `requirements.txt` không còn `vnstock` cũng như `--extra-index-url`, và không module nào bị import khi chạy workflow được import vnstock ở cấp module.

## Review Focus

- **Giá đơn vị nghìn đồng và đồng:** VCI chart trả giá cổ phiếu theo ĐỒNG (51600), vnstock chia cho 1000, pipeline nhân lại 1000. Chỉ số thì không nhân. Sai chỗ này làm hỏng toàn bộ giá. Test so `fetch_history_one` và `fetch_index_history` với đáp án mẫu (Task 3).
- **`countBack` và khoảng ngày:** chart API nhận `to` + `countBack` chứ không nhận `start`. vnstock trả dư dòng trước `start` (history_FPT bắt đầu 29/09 dù start=01/10). Đầu ra phải giống hệt pipeline cũ, kể cả các dòng dư nếu pipeline cũ giữ chúng. Có test cho chuỗi dài 2012–2026 (1995 dòng) (Task 3).
- **Thứ tự dòng BCTC (`row_seq`):** warehouse khoá theo `row_seq` = vị trí dòng. Đổi thứ tự là hỏng lịch sử. So nguyên `_fetch_statement_one` cho cả NONFIN, BANK, OTHERFIN (FPT, VCB, SSI, BVH), cả quý lẫn năm (Task 8).
- **Ô thiếu và số 0:** `'-'` trong tỷ giá VCB phải ra NULL chứ không phải 0. Mã không khớp lệnh trong bảng giá phải ra close = giá tham chiếu (đã có logic, chỉ cần cột đầu vào đúng tên) (Task 2, Task 4).
- **Nguồn đổi schema hoặc trả vỏ lỗi:** `data: null`, `status != 200`, JSON hỏng phải ném lỗi mà các vòng `try/except` hiện có bắt được. Không được trả DataFrame rỗng âm thầm (Task 1).

---

### Task 1: HTTP client dùng chung + bộ fixture từ đáp án mẫu

**Files:**
- Create: `src/sources/__init__.py`, `src/sources/http.py`
- Create: `scripts/build_vci_fixtures.py` (chạy MỘT LẦN trên máy có vnstock + đáp án mẫu)
- Create: `tests/fixtures/vci/http/*.json.gz`, `tests/fixtures/vci/expected/*.json`
- Create: `tests/vci_fixtures.py` (helper nạp fixture + giả lập HTTP)
- Test: `tests/test_sources_http.py`

**Interfaces:**
- Produces:
  - `class SourceError(Exception)`
  - `get_json(url: str, params: dict | None = None) -> Any` và `post_json(url: str, body: dict) -> Any`: trả JSON đã parse.
  - `iq_data(path: str, params: dict | None = None) -> Any`: GET `https://iq.vietcap.com.vn/api/iq-insight-service` + path, bóc vỏ, trả `data`.
  - `tests/vci_fixtures.py`: `fake_http(monkeypatch, label: str)` vá `src.sources.http._send` để phục vụ phản hồi đã ghi trong `tests/fixtures/vci/http/<label>.json.gz`, khớp theo (method, path, query params, body). Yêu cầu không có trong fixture thì ném `AssertionError` ghi rõ URL. `load_expected(name) -> pd.DataFrame` đọc `expected/<name>.json`.
  - Mọi I/O mạng đi qua MỘT hàm nội bộ `_send(method, url, *, params, json) -> requests.Response`, để test chỉ cần vá một chỗ.

- [ ] **Step 1: Viết `scripts/build_vci_fixtures.py`**: đọc `data/vnstock_golden_2026-11-12/http/<label>.json` và `frames/<label>.pkl`. Với mỗi hàm `fetch_*` của ingest_market trong bảng dưới, vá phương thức vnstock tương ứng (vd `vnstock.api.quote.Quote.history`) để trả frame mẫu, chạy hàm `fetch_*` HIỆN TẠI (trước khi sửa), rồi ghi đầu ra thành `expected/<tên>.json` (`to_json(orient="table")`, giữ dtype). Đồng thời ghi phản hồi HTTP thô thành `http/<label>.json.gz`, bỏ yêu cầu `trading.vietcap.com.vn/priceboard` (HTML). Riêng `search-bar` chỉ giữ dòng của mã trong mẫu.

  | expected | hàm hiện tại | mẫu |
  |---|---|---|
  | `universe` | `refresh_universe(["HOSE","HNX"])` | listing_all_symbols |
  | `industries_icb` | `fetch_industries_icb()` | listing_industries_icb |
  | `eod_prices` | `fetch_eod_prices(SYMS, run_date="2026-11-12")` | price_board |
  | `history_<S>` (FPT, VCB, MCH, FPT_long) | `fetch_history_one(S, start, end)` với start/end như lúc chụp | history_* |
  | `index_<I>` (VNINDEX, VN30, HNXINDEX) | `fetch_index_history(I, "2026-10-01", "2026-11-11")` | history_<I> |
  | `fx_2026-11-11` | `fetch_exchange_rate("2026-11-11")` | fx_vcb_2026-11-11 |
  | `events_<S>`, `news_<S>`, `company_<S>` | `fetch_corporate_events/fetch_news/fetch_company_info([S])` | company_* |
  | `shareholders_<S>`, `officers_<S>`, `ratio_summary_<S>` | `fetch_shareholders/fetch_officers/fetch_financials([S])` | company_* |
  | `stmt_<type>_<period>_<S>` (S ∈ FPT, VCB, SSI, BVH) | `_fetch_statement_one(S, type, "VCI", period)[0]` | finance_* |

  Các trường phụ thuộc thời gian chạy (vd `snapshot_date`, `fetched_at`) phải cố định qua tham số/vá `date.today()` để mong đợi tất định.
- [ ] **Step 2: Chạy script, kiểm tổng dung lượng `tests/fixtures/vci` < 5 MB, commit fixture + script** (`chore(test): fixture VCI từ đáp án mẫu vnstock 4.0.9`).
- [ ] **Step 3: Viết test cho `src/sources/http.py`**
  - `test_iq_data_boc_vo`: `_send` giả trả `{"status":200,"code":0,"data":[1]}` → `iq_data("/x") == [1]`.
  - `test_iq_data_vo_loi_nem_source_error`: `{"status":400,"code":1,"msg":"x","data":None}` → `SourceError`.
  - `test_thu_lai_khi_5xx_roi_thanh_cong`: 503, 503, rồi 200 → trả kết quả, `_send` gọi đúng 3 lần, `time.sleep` (đã vá) nhận `[5, 15]`.
  - `test_khong_thu_lai_khi_4xx`: 404 → `SourceError` sau 1 lần gọi.
  - `test_header_bat_buoc`: request gửi đi có đủ Referer, Origin, User-Agent.
- [ ] **Step 4: Chạy `pytest tests/test_sources_http.py -v` → FAIL (module chưa có)**
- [ ] **Step 5: Viết `src/sources/http.py`** theo Global Constraints (`requests.Session` dùng lại, timeout, thử lại).
- [ ] **Step 6: Chạy lại → PASS, rồi commit** (`feat(sources): HTTP client Vietcap dùng chung`).

### Task 2: Danh sách mã, ICB, bảng giá

**Files:**
- Create: `src/sources/vci.py`
- Modify: `src/ingest_market.py` (`refresh_universe`, `fetch_industries_icb`, `_price_board_batch`)
- Test: `tests/test_sources_vci_market.py`

**Interfaces:**
- Consumes: `post_json`, `get_json`, `iq_data` (Task 1).
- Produces trong `src/sources/vci.py`:
  - `all_symbols() -> pd.DataFrame` có cột `symbol`, `organ_name` (GET `trading.vietcap.com.vn/api/price/symbols/getAll`, chỉ `type == "STOCK"` nếu đáp án mẫu khớp; xem cột `board` nhưng KHÔNG thêm cột sàn, vì như vậy sẽ bật bộ lọc sàn đang tắt trong `refresh_universe`, xem comment `config/warehouse.yml`).
  - `industries_icb() -> pd.DataFrame` có cột `icb_code`, `icb_name`, `en_icb_name`, `level` (`iq_data("/v1/sectors/icb-codes")`).
  - `price_board(symbols: list[str]) -> pd.DataFrame`: cột đã làm phẳng dạng `listing.symbol`, `listing.trading_date`, `listing.ref_price`, `match.match_price`, `match.open_price`, `match.highest`, `match.lowest`, `match.accumulated_volume`, `match.accumulated_value`, `match.foreign_buy_volume`, `match.foreign_sell_volume`, `match.foreign_buy_value`, `match.foreign_sell_value` (POST `.../price/symbols/getList`, body `{"symbols": [...]}`). Đơn vị như frame mẫu (kiểm `accumulated_value` theo triệu đồng).

- [ ] **Step 1: Viết test**, mỗi test dùng `fake_http` + `load_expected`:
  - `test_refresh_universe_khop_mau`: `ingest_market.refresh_universe(["HOSE","HNX"])` == expected `universe`.
  - `test_industries_icb_khop_mau`.
  - `test_eod_prices_khop_mau`: `fetch_eod_prices(SYMS, run_date="2026-11-12")` == expected `eod_prices`, kể cả `attrs["market_trading_date"]`.
  - So bằng `pd.testing.assert_frame_equal(actual, expected, check_dtype=True)`. Nếu khác dtype mà cùng giá trị (int64 và Int64), sửa đầu ra cho khớp mong đợi, không nới test.
- [ ] **Step 2: Chạy → FAIL**
- [ ] **Step 3: Viết ba hàm trong `src/sources/vci.py`, rồi đổi ba lời gọi trong ingest_market sang chúng**
- [ ] **Step 4: Chạy test mới + toàn bộ `pytest -q` → PASS**
- [ ] **Step 5: Commit** (`feat(sources): danh sách mã, ICB, bảng giá gọi thẳng VCI`)

### Task 3: Lịch sử giá cổ phiếu và chỉ số

**Files:**
- Modify: `src/sources/vci.py`, `src/ingest_market.py` (`fetch_history_one`, `fetch_index_history`)
- Test: `tests/test_sources_vci_history.py`; sửa `tests/test_ingest_history.py` nếu nó dựng frame theo định dạng vnstock

**Interfaces:**
- Produces: `vci.ohlc_history(symbol: str, start: str, end: str) -> pd.DataFrame` có cột `time, open, high, low, close, volume`. POST `trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart`, body `{"timeFrame":"ONE_DAY","symbols":[symbol],"to":<epoch end>,"countBack":<n>}`; `t` là epoch giây dạng chuỗi. Chọn đơn vị trả về (đồng hay nghìn đồng) sao cho tầng ingest đúng: nếu trả đồng thì bỏ phép ×1000 ở `fetch_history_one` và giữ nguyên `fetch_index_history`. Cách tính `countBack` và `to` phải tái tạo đúng các yêu cầu đã ghi trong fixture (fake_http sẽ báo lỗi nếu body khác).

- [ ] **Step 1: Viết test**: `test_history_khop_mau[FPT|VCB|MCH|FPT_long]`, `test_index_khop_mau[VNINDEX|VN30|HNXINDEX]`, và `test_index_khong_nhan_1000` (VNINDEX close đầu tiên == 1780.42 ± 0,01 theo frame mẫu, không phải 1.780.420).
- [ ] **Step 2: Chạy → FAIL**
- [ ] **Step 3: Viết `ohlc_history`, đổi hai lời gọi Quote trong ingest_market**
- [ ] **Step 4: `pytest -q` → PASS**
- [ ] **Step 5: Commit** (`feat(sources): lịch sử giá và chỉ số gọi thẳng VCI`)

### Task 4: Tỷ giá VCB, gỡ vnstock khỏi requirements (khép PR 1)

**Files:**
- Create: `src/sources/vcb.py`
- Modify: `src/ingest_market.py` (`fetch_exchange_rate` + chuyển mọi `from vnstock...` còn lại vào TRONG các hàm chưa chuyển), `src/ingest.py` (xoá `apply_vnstock_timeout`, các hàm `fetch_history/fetch_index/fetch_ratios/fetch_industry/fetch_news/fetch_universe` không còn ai gọi, và import vnstock; giữ `_throttle`, `SourceBreaker`), `build_warehouse.py:314-317` và `backfill.py:34-37` (bọc `vnai.setup_api_key` trong `try/except ImportError`), `requirements.txt`, `tests/conftest.py`, `pytest.ini`
- Delete: `tests/test_vnstock_timeout.py`
- Test: `tests/test_sources_vcb.py`, `tests/test_no_vnstock_import.py`

**Interfaces:**
- Produces: `vcb.exchange_rate(rate_date: str) -> pd.DataFrame` có cột `currency_code, currency_name, buy_cash, buy_transfer, sell, date`, giữ chuỗi gốc (`'17,180.25'`, `'-'`) để `fetch_exchange_rate` chuẩn hoá như cũ. GET `https://www.vietcombank.com.vn/api/exchangerates/exportexcel?date=YYYY-MM-DD`, trường `Data` là xlsx mã hoá base64, đọc bằng `pd.read_excel(..., engine="openpyxl")`.

- [ ] **Step 1: Viết test**
  - `test_fx_khop_mau`: `fetch_exchange_rate("2026-11-11")` == expected `fx_2026-11-11`.
  - `test_fx_gach_ngang_la_null`: dòng có `'-'` trong frame mẫu → NULL trong đầu ra.
  - `test_no_vnstock_import`: chạy subprocess `python -c "import sys; sys.modules['vnstock']=None; import build_warehouse, alert_events, backfill"` → exit 0 (chặn vnstock, các entrypoint vẫn import được).
- [ ] **Step 2: Chạy → FAIL**
- [ ] **Step 3: Viết `vcb.py`, đổi `fetch_exchange_rate`, chuyển import vnstock còn lại vào trong hàm, dọn `ingest.py`, conftest (bỏ phần mồi import vnstock) và pytest.ini (bỏ filter cảnh báo vnstock)**
- [ ] **Step 4: Sửa `requirements.txt`**: xoá 3 dòng comment, `--extra-index-url` và `vnstock==4.0.9`; thêm `openpyxl>=3.1`.
- [ ] **Step 5: Kiểm môi trường sạch**: `python -m venv /tmp/venv-sach && /tmp/venv-sach/bin/pip install -r requirements.txt && /tmp/venv-sach/bin/python -m pytest -q` → cài được, test PASS (các test vẫn cần vnstock phải được đánh `skipif` không có vnstock, hoặc chuyển sang fixture).
- [ ] **Step 6: Chạy thật một lần không qua vnstock**: `/tmp/venv-sach/bin/python build_warehouse.py --mode daily --only prices,index` trên bản sao warehouse: `cp data/warehouse.duckdb <scratchpad>/wh.duckdb` rồi đặt `WAREHOUSE_DB=<scratchpad>/wh.duckdb` (`src/warehouse.py:108`). Tuyệt đối không chạy vào DB thật hay MotherDuck (`md:`). So số dòng giá phiên gần nhất với phiên trước (chênh < 2%).
- [ ] **Step 7: Commit, push, mở PR 1** (`fix: bỏ vnstock cho giá/chỉ số/bảng giá/ICB/tỷ giá — workflow cài được lại`). Mô tả PR nêu rõ trickle/ratios/company/statements tạm lỗi tới PR 2–3.

### Task 5: Sự kiện doanh nghiệp

**Files:** Create `src/sources/vci_company.py`; Modify `src/ingest_market.py` (`fetch_corporate_events`); Test `tests/test_sources_vci_company.py`

**Interfaces:**
- Produces: `vci_company.events(symbol: str) -> pd.DataFrame`: cột như frame mẫu `company_events_*` (snake_case của JSON), `iq_data("/v1/events", params)` với `ticker`, `fromDate`/`toDate` (YYYYMMDD, 10 năm về trước tới hôm nay), `eventCode=DIV,ISS,DDIND,DDINS,DDRP,AGME,AGMR,EGME,AIS,MA,MOVE,NLIS,OTHE,RETU,SUSP`, `page=0`, `size=50`. Nhận `today: date | None` để test cố định `toDate=20261112`.

- [ ] **Step 1: Test** `test_events_khop_mau[FPT|VCB|BVH|MCH]` (BVH có 21 cột thay vì 22, nên phải chịu được cột vắng).
- [ ] **Step 2: FAIL → Step 3: viết + đổi lời gọi → Step 4: `pytest -q` PASS → Step 5: commit**

### Task 6: Tin tức + hồ sơ công ty (khép PR 2)

**Files:** Modify `src/sources/vci_company.py`, `src/ingest_market.py` (`fetch_news`, `fetch_company_info`); Test thêm vào `tests/test_sources_vci_company.py`

**Interfaces:**
- Produces: `vci_company.news(symbol, today=None) -> pd.DataFrame` (`/v1/news`, `languageId=1`, `page=0`, `size=50`, cùng khoảng ngày như events) và `vci_company.overview(symbol) -> pd.DataFrame` một dòng (`/v1/company/details?ticker=`), đủ các cột `_normalize_company` đọc.

- [ ] **Step 1: Test** `test_news_khop_mau[...]`, `test_company_info_khop_mau[FPT|VCB|SSI|MCH]`
- [ ] **Step 2–4: FAIL → viết → PASS**
- [ ] **Step 5: Chạy thật** `build_warehouse.py --mode weekly --only company_missing,events` trên bản sao DB, so số sự kiện mới với lần chạy trước.
- [ ] **Step 6: Commit, PR 2**

### Task 7: Cổ đông, ban lãnh đạo, ratio_summary

**Files:** Modify `src/sources/vci_company.py`, `src/ingest_market.py` (`fetch_shareholders`, `fetch_officers`, `fetch_financials`); Test thêm vào `tests/test_sources_vci_company.py`

**Interfaces:**
- Produces: `vci_company.shareholders(symbol)` và `vci_company.officers(symbol)` (cùng endpoint `/v1/company/{symbol}/shareholder`; đọc mã vnstock để biết cách tách hai loại), `vci_company.ratio_summary(symbol)` (`/v1/company/{symbol}/statistics-financial`).

- [ ] **Step 1: Test** `test_shareholders_khop_mau`, `test_officers_khop_mau`, `test_ratio_summary_khop_mau`, mỗi test với FPT, VCB, SSI, BVH.
- [ ] **Step 2–4: FAIL → viết → PASS → Step 5: commit**

### Task 8: Báo cáo tài chính chi tiết

**Files:** Create `src/sources/vci_finance.py`; Modify `src/ingest_market.py` (`_fetch_statement_one`); Test `tests/test_sources_vci_finance.py`

**Interfaces:**
- Produces: `vci_finance.statement(symbol: str, statement_type: Literal["income_statement","balance_sheet","cash_flow"], period: Literal["quarter","year"]) -> pd.DataFrame` có cột `item, item_en, item_id, <kỳ…>` (nhãn kỳ dạng `2026-Q3` hoặc năm như frame mẫu), **cùng thứ tự dòng** như frame mẫu. Nguồn: `/v1/company/{symbol}/financial-statement?section=INCOME_STATEMENT|BALANCE_SHEET|CASH_FLOW` và `/v1/company/{symbol}/financial-statement/metrics` (tên chỉ tiêu). Phản hồi quý và năm giống nhau, lọc kỳ phía client. Đọc mã vnstock để biết `search-bar` dùng vào việc gì (nhiều khả năng là xác định loại doanh nghiệp để chọn bộ chỉ tiêu). Nếu cần, lấy loại doanh nghiệp bằng cách rẻ nhất, và cache `metrics` theo loại doanh nghiệp trong một lần chạy để không gọi lại cho mỗi mã.

- [ ] **Step 1: Test** `test_statement_khop_mau[<type>-<period>-<S>]`: 3 loại × 2 kỳ × 4 mã = 24 trường hợp, so đầu ra `_fetch_statement_one(...)[0]` với `stmt_*`.
- [ ] **Step 2–4: FAIL → viết → PASS**
- [ ] **Step 5: Đếm lời gọi**: một mã đủ 3 báo cáo không được nhiều hơn 4 yêu cầu HTTP (3 section + metrics đã cache), thay vì 12 như vnstock.
- [ ] **Step 6: Commit**

### Task 9: Dọn dẹp + kiểm chạy thật (khép PR 3)

**Files:** Modify `src/ingest_market.py` (xoá mọi import vnstock), `build_warehouse.py`, `backfill.py` (xoá khối `VNSTOCK_API_KEY`), `scripts/diagnose_api.py` (đổi sang `src.sources` hoặc xoá nếu không còn giá trị), các script một lần dùng vnstock (`scripts/probe_news_id_stability.py`, `scripts/migrate_financial_ratio_v2.py`: chuyển sang `src.sources` nếu còn dùng, không thì xoá), `.github/workflows/*.yml` (bỏ secret `VNSTOCK_API_KEY` nếu có), `docs/han-che-nen-tang.md` và README (nguồn dữ liệu = gọi thẳng Vietcap/VCB). Test: `tests/test_no_vnstock_import.py` mở rộng; `tests/test_sources_live.py` (`@pytest.mark.network`)

- [ ] **Step 1: Mở rộng test**: `grep -rn "vnstock" src build_warehouse.py backfill.py alert_events.py scripts mcp_server` không còn import nào (chỉ được phép xuất hiện trong comment lịch sử).
- [ ] **Step 2: Test sống** `tests/test_sources_live.py`: với FPT, gọi mỗi hàm `src.sources` một lần và chạy qua hàm `fetch_*` tương ứng; kiểm không rỗng và đủ cột bắt buộc. Đăng ký marker `network` trong `pytest.ini` với `addopts = -m "not network"`.
- [ ] **Step 3: `pytest -q` (offline) PASS; `pytest -m network -q` PASS trên máy**
- [ ] **Step 4: Chạy thật trên bản sao DB**: `build_warehouse.py --mode weekly --only company_missing,events,statements`, rồi `dbt build`. Không có test dbt mới nào đỏ so với lần chạy xanh gần nhất.
- [ ] **Step 5: Commit, PR 3; sau khi merge, chạy tay `gh workflow run` cho warehouse-trickle và warehouse-weekly, xác nhận xanh.**

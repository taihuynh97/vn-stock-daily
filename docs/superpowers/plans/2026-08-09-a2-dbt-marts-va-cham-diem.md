# A2 — Tầng dbt & Bộ chấm điểm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biến raw layer (đã hoàn thiện ở plan A1) thành tầng phân tích dùng được: khử sentinel `0.0` của ngân hàng, tính percentile định giá so với chính mã và so với ngành, chấm 5 điểm thành phần tách theo loại hình doanh nghiệp, và cho phép đổi "gu" đầu tư bằng cách sửa một file YAML.

**Architecture:** dbt-duckdb với 3 tầng `staging → intermediate → marts`. Điểm mấu chốt: các chỉ tiêu được **unpivot sang dạng long** `(symbol, period, metric, value)`, sau đó percentile và trọng số được áp bằng cách **join với seed** — nhờ vậy công thức chấm điểm là *dữ liệu*, không phải SQL cứng, và quy tắc chuẩn hoá lại trọng số khi thiếu chỉ tiêu chỉ cần viết một lần. Điểm tổng hợp **không** nằm trong dbt mà do `src/scoring.py` tính lúc đọc, để đổi profile không phải chạy lại dbt.

**Tech Stack:** dbt-core + dbt-duckdb · DuckDB 1.5.3 · MotherDuck · Python 3.12 · pandas · PyYAML · pytest

## Global Constraints

- Spec nguồn: `docs/superpowers/specs/2026-08-09-fundamental-analysis-platform-design.md`.
- **Điều kiện tiên quyết:** plan A1 đã hoàn tất và đạt hết 9 tiêu chí. Kiểm tra bằng `python -m scripts.reconcile_warehouse`.
- Ba giá trị `com_class`: `NONFIN`, `BANK`, `OTHERFIN`. **Không bao giờ so chỉ tiêu giữa hai `com_class` khác nhau.**
- **NULL ≠ 0.** Không dùng `coalesce(x, 0)` cho bất kỳ chỉ tiêu tài chính nào. Điểm 0 nghĩa là "kém nhất nhóm"; NULL nghĩa là "không đo được".
- Đơn vị: giá **VNĐ**; `raw_price_daily.value` **triệu VNĐ** → nhân `1e6` ở staging; chỉ số **không** đổi đơn vị.
- Mọi model phải chạy được trên cả DuckDB local lẫn MotherDuck qua `WAREHOUSE_DB`.
- `dbt build` = chạy model **và** test. Test fail → dừng.
- Chạy dbt từ thư mục `transforms/`.
- Branch làm việc: `feat/fundamental-analysis-platform`.

---

### Task 1: Dựng dbt project + staging giá và chỉ số

**Files:**
- Modify: `requirements.txt`
- Create: `transforms/dbt_project.yml`, `transforms/profiles.yml`, `transforms/.gitignore`
- Create: `transforms/models/staging/_sources.yml`, `transforms/models/staging/_staging.yml`
- Create: `transforms/models/staging/stg_price_daily.sql`, `stg_index_daily.sql`
- Create: `transforms/tests/assert_price_in_vnd_range.sql`, `assert_value_matches_volume.sql`, `assert_no_weekend_or_future_dates.sql`, `assert_index_not_scaled.sql`

**Interfaces:**
- Consumes: bảng raw từ plan A1.
- Produces:
  - `ref('stg_price_daily')` — cột `symbol, trade_date, open, high, low, close, volume, value_vnd, turnover_proxy_vnd, turnover_vnd, has_ohlc, has_value, is_suspect_price`
  - `ref('stg_index_daily')` — cột `index_code, trade_date, open, high, low, close, volume`
  - dbt var `metrics_common` / `metrics_nonfin` / `metrics_bank` (dùng ở Task 2)

- [ ] **Step 1: Cài dbt-duckdb**

Thêm vào `requirements.txt`:

```
dbt-core>=1.9,<2.0
dbt-duckdb>=1.9,<2.0
```

Run: `.venv/bin/pip install -r requirements.txt`
Expected: cài thành công; `.venv/bin/dbt --version` in ra `dbt-duckdb`.

- [ ] **Step 2: Tạo `transforms/dbt_project.yml`**

```yaml
name: vn_market
version: "1.0.0"
config-version: 2
profile: vn_market

model-paths: ["models"]
seed-paths: ["seeds"]
test-paths: ["tests"]
macro-paths: ["macros"]
target-path: "target"
clean-targets: ["target", "dbt_packages"]

models:
  vn_market:
    staging:
      +materialized: view
    intermediate:
      +materialized: table
    marts:
      +materialized: table

seeds:
  vn_market:
    +quote_columns: false

vars:
  # Nhóm chỉ tiêu theo khả dụng — xác minh bằng VCB (ngân hàng) vs HPG (phi tài chính).
  # COMMON: cả hai đều có giá trị thật.
  # NONFIN: ngân hàng trả sentinel 0.0 → phải NULL hoá.
  # BANK:   phi tài chính trả sentinel 0.0/None → phải NULL hoá.
  metrics_common:
    - market_cap
    - number_of_shares_mkt_cap
    - dividend_yield
    - pe
    - pb
    - ps
    - roe
    - roa
    - debt_to_equity
    - gross_margin
    - pre_tax_profit_margin
    - after_tax_profit_margin
    - price_to_cash_flow
  metrics_nonfin:
    - roic
    - ev_to_ebitda
    - current_ratio
    - quick_ratio
    - cash_ratio
    - ebit_margin
    - asset_turnover
    - fixed_asset_turnover
    - cash_cycle
    - day_sale_outstanding
    - days_inventory_outstanding
    - days_payable_outstanding
    - ebit
    - ebitda
    - debt_per_equity
  metrics_bank:
    - net_interest_margin
    - average_yield_on_earning_assets
    - average_cost_of_financing
    - non_and_interest_income
    - cir
    - loans_growth
    - deposit_growth
    - equity_to_liabilities
    - equity_to_loans
    - total_equity_total_asset
    - ldr_loan_deposit_ratio
    - npl
    - loans_loss_reserve_to_loans
    - provision_to_outstanding_loans
    - car
    - casa_ratio
  # Số mã tối thiểu để một peer group được coi là đủ tin cậy.
  peer_min_size: 15
  # Số mã tuyệt đối tối thiểu để tính percentile.
  peer_hard_min: 8
  # Số quý tối thiểu để tính percentile định giá so với chính mã.
  own_history_min_quarters: 12
```

- [ ] **Step 3: Tạo `transforms/profiles.yml` và `.gitignore`**

`transforms/profiles.yml`:

```yaml
vn_market:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "{{ env_var('WAREHOUSE_DB', '../data/warehouse.duckdb') }}"
      threads: 4
      extensions:
        - httpfs
```

`transforms/.gitignore`:

```
target/
dbt_packages/
logs/
```

> `WAREHOUSE_DB=md:vn_market` cùng biến `motherduck_token` sẽ trỏ dbt vào MotherDuck — dbt-duckdb nhận diện tiền tố `md:` như DuckDB.

- [ ] **Step 4: Khai báo nguồn — `transforms/models/staging/_sources.yml`**

```yaml
version: 2

sources:
  - name: warehouse
    schema: main
    tables:
      - name: raw_price_daily
        loaded_at_field: loaded_at
        freshness:
          warn_after: {count: 2, period: day}
          error_after: {count: 4, period: day}
          filter: "trade_date >= current_date - interval '30 days'"
      - name: raw_index_daily
        loaded_at_field: loaded_at
        freshness:
          warn_after: {count: 2, period: day}
          error_after: {count: 4, period: day}
      - name: raw_financial_ratio
        loaded_at_field: loaded_at
        freshness:
          warn_after: {count: 10, period: day}
          error_after: {count: 20, period: day}
      - name: raw_company_info
        loaded_at_field: loaded_at
        freshness:
          warn_after: {count: 40, period: day}
          error_after: {count: 70, period: day}
      - name: dim_industry
      - name: dim_symbols
```

- [ ] **Step 5: Viết test dbt (chạy trước khi có model → phải fail)**

`transforms/tests/assert_price_in_vnd_range.sql`:

```sql
-- Bắt LỆCH ĐƠN VỊ, không bắt "cổ phiếu giá thấp".
--
-- Bản đầu dùng sàn tuyệt đối 100 VNĐ, nhưng chạy thật trên production cho
-- thấy nó đo sai thứ: 1.682 dòng (0,13%) bị bắt đều là cổ phiếu penny THẬT —
-- DKC/VLP/VNX là vỏ công ty gần chết, khối lượng 1-5 cổ phiếu/phiên, giá
-- 30-900 VNĐ suốt 828 phiên. Đó là dữ liệu đúng.
--
-- Dấu hiệu thật của lệch đơn vị là ĐỨT GÃY: cùng một mã có cả dòng dưới
-- 100 VNĐ lẫn dòng trên 1.000 VNĐ. Ví dụ HPG nếu quên nhân 1000 ở phần
-- backfill sẽ có dòng 21,85 nằm cạnh dòng 21.850 — lỗi này đã xảy ra thật,
-- xem scripts/fix_backfill_units.py. Mã penny thật thì mọi phiên đều thấp.
--
-- Chặn trên vẫn giữ tuyệt đối: không cổ phiếu VN nào vượt 5 triệu VNĐ.
with per_symbol as (
    select
        symbol,
        count(*) filter (where close < 100)   as n_duoi_100,
        count(*) filter (where close > 1000)  as n_tren_1000,
        count(*) filter (where close > 5000000) as n_qua_lon
    from {{ ref('stg_price_daily') }}
    group by symbol
)
select symbol, n_duoi_100, n_tren_1000, n_qua_lon
from per_symbol
where (n_duoi_100 > 0 and n_tren_1000 > 0)   -- đứt gãy đơn vị trong cùng một mã
   or n_qua_lon > 0                           -- vượt chặn trên tuyệt đối
```

`transforms/tests/assert_value_matches_volume.sql`:

```sql
-- value_vnd phải xấp xỉ close * volume. Mục đích DUY NHẤT của test này là bắt
-- lệch đơn vị 10⁶ — không phải bắt nhiễu giá.
--
-- Dung sai ban đầu 30% cho 5/27.981 dòng (0,018%) fail trên production, với
-- mức lệch 32-40%. Đó KHÔNG phải lệch đơn vị (lệch 10⁶ tương đương 99.999.900%)
-- mà là nhiễu bình thường: giao dịch thoả thuận, hoặc close là giá khớp cuối
-- còn value tính theo giá bình quân cả phiên.
--
-- Nới lên 50%: vẫn bắt lệch đơn vị dư sức, mà không báo động sai. Một cổng
-- báo động sai liên tục thì tệ hơn không có cổng, vì người ta học cách bỏ qua
-- nó — bài học từ finding C4 của mảng A1.
select symbol, trade_date, value_vnd, turnover_proxy_vnd
from {{ ref('stg_price_daily') }}
where has_value
  and volume > 1000
  and turnover_proxy_vnd > 0
  and abs(value_vnd - turnover_proxy_vnd) / turnover_proxy_vnd > 0.50
```

`transforms/tests/assert_no_weekend_or_future_dates.sql`:

```sql
-- Không có phiên rơi vào T7/CN hoặc ở tương lai.
-- DuckDB: isodow() trả 1=T2 ... 6=T7, 7=CN.
select symbol, trade_date
from {{ ref('stg_price_daily') }}
where isodow(trade_date) >= 6
   or trade_date > current_date
```

`transforms/tests/assert_index_not_scaled.sql`:

```sql
-- VNINDEX quanh 1.700 điểm. Nếu bị nhân nhầm x1000 sẽ ra ~1.700.000.
select index_code, trade_date, close
from {{ ref('stg_index_daily') }}
where index_code = 'VNINDEX'
  and (close < 500 or close > 5000)
```

- [ ] **Step 6: Chạy dbt để xác nhận fail**

```bash
cd transforms
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
../.venv/bin/dbt build --profiles-dir .
```

Expected: FAIL — `Model 'model.vn_market.stg_price_daily' (ref) depends on a node named 'stg_price_daily' which was not found`

- [ ] **Step 7: Viết `stg_price_daily.sql`**

```sql
{{ config(materialized='view', tags=['daily']) }}

with deduped as (
    select
        upper(trim(symbol))      as symbol,
        cast(trade_date as date) as trade_date,
        cast(open   as double)   as open,
        cast(high   as double)   as high,
        cast(low    as double)   as low,
        cast(close  as double)   as close,
        cast(volume as bigint)   as volume,
        cast(value  as double)   as value_raw,
        row_number() over (
            partition by upper(trim(symbol)), cast(trade_date as date)
            order by loaded_at desc
        ) as rn
    from {{ source('warehouse', 'raw_price_daily') }}
    where close is not null
      and close > 0
)

select
    symbol,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    -- raw_price_daily.value tính bằng TRIỆU VNĐ trong khi giá tính bằng VNĐ.
    -- Xác minh HPG 2026-08-07: volume 13.018.100 x close 21.850 = 284 tỷ,
    -- còn value = 287.111,73 → hệ số 1e6.
    value_raw * 1e6                            as value_vnd,
    close * volume                             as turnover_proxy_vnd,
    -- value_vnd chỉ có từ 2026-06-07 (dòng backfill qua Quote.history đều NULL),
    -- nên dùng close*volume làm phương án thay thế cho lịch sử dài.
    coalesce(value_raw * 1e6, close * volume)  as turnover_vnd,
    (open is not null and high is not null and low is not null) as has_ohlc,
    (value_raw is not null)                    as has_value,
    (close < 100 or close > 5000000)           as is_suspect_price
from deduped
where rn = 1
```

- [ ] **Step 8: Viết `stg_index_daily.sql`**

```sql
{{ config(materialized='view', tags=['daily']) }}

with deduped as (
    select
        upper(trim(index_code))  as index_code,
        cast(trade_date as date) as trade_date,
        cast(open   as double)   as open,
        cast(high   as double)   as high,
        cast(low    as double)   as low,
        cast(close  as double)   as close,
        cast(volume as bigint)   as volume,
        row_number() over (
            partition by upper(trim(index_code)), cast(trade_date as date)
            order by loaded_at desc
        ) as rn
    from {{ source('warehouse', 'raw_index_daily') }}
    where close is not null
)

-- LƯU Ý: giá trị chỉ số KHÔNG đổi đơn vị (VNINDEX ~1.768 điểm là đúng).
select index_code, trade_date, open, high, low, close, volume
from deduped
where rn = 1
```

- [ ] **Step 9: Khai báo test generic — `transforms/models/staging/_staging.yml`**

```yaml
version: 2

models:
  - name: stg_price_daily
    description: "Giá EOD đã chuẩn hoá đơn vị VNĐ, khử trùng theo (symbol, trade_date)."
    columns:
      - name: symbol
        tests: [not_null]
      - name: trade_date
        tests: [not_null]
      - name: close
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, trade_date]

  - name: stg_index_daily
    description: "Chỉ số thị trường. KHÔNG đổi đơn vị."
    columns:
      - name: index_code
        tests:
          - not_null
          - accepted_values:
              values: ['VNINDEX', 'VN30', 'HNXINDEX']
      - name: trade_date
        tests: [not_null]
```

Thêm `transforms/packages.yml` (cho `dbt_utils`):

```yaml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.3.0", "<2.0.0"]
```

Run: `cd transforms && ../.venv/bin/dbt deps --profiles-dir .`

- [ ] **Step 10: Chạy dbt để xác nhận pass**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select stg_price_daily stg_index_daily
```

Expected: PASS — 2 model + toàn bộ test xanh.

> **Nếu `assert_value_matches_volume` fail:** kiểm tra lại giả định đơn vị `1e6` bằng
> `select close, volume, value_vnd, turnover_proxy_vnd from stg_price_daily where has_value limit 5`.
> Đây là test bảo vệ đúng lỗi V4 trong spec — đừng nới ngưỡng để cho qua.

- [ ] **Step 11: Commit**

```bash
git add requirements.txt transforms/
git commit -m "feat(dbt): dựng project + staging giá và chỉ số

Chuẩn hoá value về VNĐ (nhân 1e6). Chỉ số không đổi đơn vị.
4 singular test bảo vệ đơn vị và lịch giao dịch.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Staging hồ sơ DN, ngành và tỷ số — khử sentinel

**Files:**
- Create: `transforms/macros/applicable_metrics.sql`
- Create: `transforms/models/staging/stg_company_info.sql`, `stg_industry.sql`, `stg_financial_ratio.sql`
- Modify: `transforms/models/staging/_staging.yml`
- Create: `transforms/tests/assert_no_bank_sentinel_leak.sql`, `assert_no_nonfin_sentinel_leak.sql`

**Interfaces:**
- Consumes: `ref('stg_price_daily')` (Task 1), var `metrics_*`.
- Produces:
  - `ref('stg_company_info')` — thêm cột `com_class` ∈ {`NONFIN`,`BANK`,`OTHERFIN`}
  - `ref('stg_industry')` — `icb_code, icb_name, en_icb_name, level`
  - `ref('stg_financial_ratio')` — 44 cột chỉ tiêu **đã khử sentinel**, cộng `com_class`, `period_end_date`, `is_loss_making`, `pe_meaningful`, `pb_meaningful`

- [ ] **Step 1: Viết test dbt thất bại**

`transforms/tests/assert_no_bank_sentinel_leak.sql`:

```sql
-- LỖI NGHIÊM TRỌNG NHẤT của spec: VCI dùng 0.0 để biểu thị "không áp dụng".
-- 187/187 dòng ngân hàng có roic=0 và current_ratio=0 — nếu để nguyên,
-- mọi ngân hàng bị chấm 0 điểm chất lượng và bị đọc là mất thanh khoản.
-- Sau staging, các chỉ tiêu phi tài chính của ngân hàng PHẢI là NULL.
select symbol, year, quarter, roic, current_ratio, ebit_margin
from {{ ref('stg_financial_ratio') }}
where com_class = 'BANK'
  and (roic is not null or current_ratio is not null or ebit_margin is not null)
```

`transforms/tests/assert_no_nonfin_sentinel_leak.sql`:

```sql
-- Chiều ngược lại: doanh nghiệp phi tài chính không được có chỉ tiêu ngân hàng.
select symbol, year, quarter, npl, net_interest_margin, cir
from {{ ref('stg_financial_ratio') }}
where com_class = 'NONFIN'
  and (npl is not null or net_interest_margin is not null or cir is not null)
```

`transforms/tests/assert_com_class_coverage.sql`:

```sql
-- Nợ N2 từ A1: hai test sentinel ở trên đều lọc theo com_class, nên một mã bị
-- phân loại SAI sẽ trượt khỏi phạm vi của cả hai và không test nào bắt được.
-- Test này canh đúng lỗ hổng đó: đếm mã có tỷ số nhưng thiếu hồ sơ DN.
-- Cho phép tối đa 30 mã (≈2% của 1.585) để chịu được vài mã lỗi mạng khi nạp.
select count(*) as n_unknown
from (
    select distinct symbol
    from {{ ref('stg_financial_ratio') }}
    where com_class = 'UNKNOWN'
)
having count(*) > 30
```

- [ ] **Step 2: Chạy để xác nhận fail**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select stg_financial_ratio
```

Expected: FAIL — model `stg_financial_ratio` chưa tồn tại.

> **Ghi chú lệch so với spec §6.1:** spec mô tả một seed `metric_applicability.csv`
> mang hai cờ `is_applicable` và `use_in_scoring`. Plan này tách đôi: **cờ khả dụng**
> nằm trong dbt `vars` (`metrics_common/nonfin/bank`) vì nó cần được đọc lúc *biên dịch*
> để sinh câu SQL, còn seed đọc được lúc *chạy* thì không dùng được cho việc đó;
> **cờ chấm điểm** nằm trong seed `scoring_weights.csv` (Task 10) vì nó chỉ cần lúc chạy.
> Hành vi giống hệt thiết kế đã duyệt, chỉ khác chỗ đặt.

- [ ] **Step 3: Viết macro `transforms/macros/applicable_metrics.sql`**

```sql
{#
  Sinh danh sách cột chỉ tiêu đã khử sentinel.

  Nguyên tắc: VCI trả 0.0 cho chỉ tiêu "không áp dụng" với loại hình đó.
  Chỉ tiêu nhóm NONFIN chỉ giữ lại khi com_class='NONFIN'; nhóm BANK chỉ giữ
  khi com_class='BANK'; nhóm COMMON giữ cho mọi loại hình.

  OTHERFIN (bảo hiểm/chứng khoán) chỉ dùng nhóm COMMON — đúng thiết kế.
#}
{% macro applicable_metrics() %}
    {%- for m in var('metrics_common') %}
    , {{ m }}
    {%- endfor %}
    {%- for m in var('metrics_nonfin') %}
    , case when com_class = 'NONFIN' then {{ m }} end as {{ m }}
    {%- endfor %}
    {%- for m in var('metrics_bank') %}
    , case when com_class = 'BANK' then {{ m }} end as {{ m }}
    {%- endfor %}
{% endmacro %}


{# Danh sách phẳng tất cả 44 chỉ tiêu — dùng cho UNPIVOT ở Task 5. #}
{% macro all_metrics() %}
    {{- return(var('metrics_common') + var('metrics_nonfin') + var('metrics_bank')) -}}
{% endmacro %}
```

- [ ] **Step 4: Viết `stg_company_info.sql`**

```sql
{{ config(materialized='view') }}

select
    symbol,
    company_name,
    short_name,
    exchange,
    com_type_code,
    is_bank,
    -- Phân loại quyết định bộ chỉ tiêu nào áp dụng và so sánh trong nhóm nào.
    -- Nguồn chính là com_type_code — trường phân loại trực tiếp của VCI:
    -- CT = công ty thường, NH = ngân hàng, BH = bảo hiểm, CK = chứng khoán.
    -- Xác minh khi triển khai A1: VCB=NH, VNR=BH, SHS=CK, HPG/VNM/IDV/PHP=CT.
    -- Cách này sạch hơn suy từ `sector`; is_bank/sector chỉ còn là phương án
    -- dự phòng khi com_type_code thiếu.
    case
        when com_type_code = 'NH'                          then 'BANK'
        when com_type_code in ('BH', 'CK')                 then 'OTHERFIN'
        when com_type_code = 'CT'                          then 'NONFIN'
        when is_bank or sector = 'Banks'                   then 'BANK'
        when sector in ('Insurance', 'Financial Services') then 'OTHERFIN'
        else 'NONFIN'
    end                                       as com_class,
    icb_code_lv2,
    icb_code_lv4,
    sector,
    market_cap,
    issue_share,
    free_float_percentage,
    foreigner_percentage,
    maximum_foreign_percentage,
    state_percentage,
    avg_match_value_1m,
    avg_match_volume_1m,
    highest_price_1y,
    lowest_price_1y,
    listed_date,
    date_diff('year', listed_date, current_date) as listing_age_years
from {{ source('warehouse', 'raw_company_info') }}
```

- [ ] **Step 5: Viết `stg_industry.sql`**

```sql
{{ config(materialized='view') }}

-- Bảng ICB phẳng, một dòng mỗi mã ngành. Việc ghép phân cấp nằm ở mart
-- dim_industry — nguồn VCI dùng mã cấp 1 dạng '0001' không theo tiền tố,
-- nên chỉ ghép được cấp 2→4 bằng tiền tố mã.
select
    trim(icb_code)    as icb_code,
    trim(icb_name)    as icb_name,
    trim(en_icb_name) as en_icb_name,
    cast(level as integer) as level
from {{ source('warehouse', 'dim_industry') }}
where icb_code is not null
```

- [ ] **Step 6: Viết `stg_financial_ratio.sql`**

```sql
{{ config(materialized='view') }}

with joined as (
    select
        f.*,
        -- KHÔNG mặc định 'NONFIN' (khoản nợ N2 từ A1). Một ngân hàng thiếu dòng
        -- trong raw_company_info mà bị gán NONFIN sẽ giữ nguyên cụm sentinel 0.0
        -- của nhóm NONFIN (roic=0, current_ratio=0) như GIÁ TRỊ THẬT, đồng thời
        -- NULL hoá NIM/NPL/CAR thật của nó → bị chấm điểm chất lượng bét bảng.
        -- Và assert_no_bank_sentinel_leak KHÔNG bắt được, vì nó lọc
        -- `where com_class='BANK'` — mã bị phân loại nhầm đã trượt khỏi phạm vi test.
        coalesce(c.com_class, 'UNKNOWN') as com_class,
        c.icb_code_lv2,
        c.icb_code_lv4
    from {{ source('warehouse', 'raw_financial_ratio') }} f
    left join {{ ref('stg_company_info') }} c using (symbol)
),

cleaned as (
    select
        symbol,
        year,
        quarter,
        period_type,
        ratio_type,
        com_class,
        icb_code_lv2,
        icb_code_lv4,
        -- quarter 1-4 = TTM kết thúc tại quý đó; quarter 5 = cả năm.
        case
            when quarter between 1 and 4
                then last_day(make_date(year, quarter * 3, 1))
            else make_date(year, 12, 31)
        end as period_end_date
        {{ applicable_metrics() }}
    from joined
    where year is not null and quarter is not null
)

select
    * exclude (cir, average_cost_of_financing),
    -- Nguồn trả CIR và chi phí vốn theo quy ước dấu ÂM (VCB: cir = -0,4098).
    abs(cir)                       as cir,
    abs(average_cost_of_financing) as average_cost_of_financing,
    -- Cờ ngữ nghĩa tài chính: P/E âm khi lỗ, P/E rất lớn khi lãi sát 0.
    (pe < 0)                       as is_loss_making,
    (pe > 0 and pe < 200)          as pe_meaningful,
    (pb > 0 and pb < 30)           as pb_meaningful
from cleaned
```

- [ ] **Step 7: Bổ sung khai báo test vào `_staging.yml`**

```yaml
  - name: stg_company_info
    columns:
      - name: symbol
        tests: [not_null, unique]
      - name: com_class
        tests:
          - not_null
          - accepted_values:
              values: ['NONFIN', 'BANK', 'OTHERFIN', 'UNKNOWN']

  - name: stg_industry
    columns:
      - name: icb_code
        tests: [not_null, unique]
      - name: level
        tests:
          - accepted_values:
              values: [1, 2, 3, 4]
              quote: false

  - name: stg_financial_ratio
    columns:
      - name: symbol
        tests: [not_null]
      - name: period_end_date
        tests: [not_null]
      - name: period_type
        tests:
          - accepted_values:
              values: ['quarter', 'year']
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, year, quarter]
```

- [ ] **Step 8: Chạy dbt để xác nhận pass**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select staging
```

Expected: PASS — 5 model, mọi test xanh, đặc biệt `assert_no_bank_sentinel_leak`.

- [ ] **Step 9: Kiểm chứng bằng mắt rằng ngân hàng đã sạch**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select symbol, year, quarter, com_class, roic, current_ratio,
       net_interest_margin, npl, cir
from {{ ref('stg_financial_ratio') }}
where symbol in ('VCB','HPG') and year = 2026 and quarter = 2
" --limit 5
```

Expected: VCB có `roic`/`current_ratio` = NULL và `net_interest_margin`/`npl`/`cir` có giá trị; HPG ngược lại. `cir` của VCB phải **dương** sau `abs()`.

- [ ] **Step 10: Commit**

```bash
git add transforms/
git commit -m "feat(dbt): staging hồ sơ DN, ngành, tỷ số — khử sentinel 0.0

Macro applicable_metrics NULL hoá chỉ tiêu không áp dụng theo com_class.
2 test chặn rò rỉ sentinel theo cả hai chiều.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `int_price_features` — chỉ báo giá và thanh khoản

**Files:**
- Create: `transforms/models/intermediate/int_price_features.sql`
- Create: `transforms/models/intermediate/_intermediate.yml`

**Interfaces:**
- Consumes: `ref('stg_price_daily')`, `ref('stg_index_daily')`.
- Produces: `ref('int_price_features')` — hạt `(symbol, trade_date)`, cột `close, ma20, ma50, ma200, return_1m, return_3m, return_6m, return_12m, return_ytd, avg_turnover_20d, avg_turnover_60d, volatility_60d, high_52w, low_52w, pct_from_high_52w`

- [ ] **Step 1: Viết model**

```sql
{{ config(materialized='table', tags=['daily']) }}

with p as (
    select
        symbol, trade_date, close, volume, turnover_vnd,
        -- Tính suất sinh lời ngày ở đây, KHÔNG lồng vào stddev_samp bên dưới.
        -- Lồng window function trong window function là cú pháp bất hợp lệ
        -- của SQL chuẩn (DuckDB báo "window function calls cannot be nested").
        close / nullif(lag(close) over (partition by symbol order by trade_date), 0) - 1
            as daily_return
    from {{ ref('stg_price_daily') }}
    where not is_suspect_price
),

windowed as (
    select
        symbol,
        trade_date,
        close,
        volume,
        avg(close)  over w20  as ma20,
        avg(close)  over w50  as ma50,
        avg(close)  over w200 as ma200,
        avg(turnover_vnd) over w20 as avg_turnover_20d,
        avg(turnover_vnd) over w60 as avg_turnover_60d,
        stddev_samp(daily_return) over w60 as volatility_60d,
        max(close) over w250       as high_52w,
        min(close) over w250       as low_52w,
        lag(close, 21)  over (partition by symbol order by trade_date) as close_1m_ago,
        lag(close, 63)  over (partition by symbol order by trade_date) as close_3m_ago,
        lag(close, 126) over (partition by symbol order by trade_date) as close_6m_ago,
        lag(close, 250) over (partition by symbol order by trade_date) as close_12m_ago,
        count(*) over (partition by symbol order by trade_date
                       rows between 249 preceding and current row) as sessions_1y
    from p
    window
        w20  as (partition by symbol order by trade_date rows between 19  preceding and current row),
        w50  as (partition by symbol order by trade_date rows between 49  preceding and current row),
        w60  as (partition by symbol order by trade_date rows between 59  preceding and current row),
        w200 as (partition by symbol order by trade_date rows between 199 preceding and current row),
        w250 as (partition by symbol order by trade_date rows between 249 preceding and current row)
),

ytd as (
    select
        symbol,
        year(trade_date) as yr,
        min_by(close, trade_date) as close_year_open
    from p
    group by 1, 2
)

select
    w.symbol,
    w.trade_date,
    w.close,
    w.volume,
    w.ma20,
    w.ma50,
    w.ma200,
    w.avg_turnover_20d,
    w.avg_turnover_60d,
    w.volatility_60d,
    w.high_52w,
    w.low_52w,
    w.sessions_1y,
    w.close / nullif(w.close_1m_ago,  0) - 1 as return_1m,
    w.close / nullif(w.close_3m_ago,  0) - 1 as return_3m,
    w.close / nullif(w.close_6m_ago,  0) - 1 as return_6m,
    w.close / nullif(w.close_12m_ago, 0) - 1 as return_12m,
    w.close / nullif(y.close_year_open, 0) - 1 as return_ytd,
    w.close / nullif(w.high_52w, 0) - 1        as pct_from_high_52w
from windowed w
left join ytd y
       on y.symbol = w.symbol and y.yr = year(w.trade_date)
```

- [ ] **Step 2: Khai báo test — `transforms/models/intermediate/_intermediate.yml`**

```yaml
version: 2

models:
  - name: int_price_features
    description: "Chỉ báo giá, thanh khoản và biến động theo phiên."
    columns:
      - name: symbol
        tests: [not_null]
      - name: trade_date
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, trade_date]
```

- [ ] **Step 3: Chạy dbt**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select int_price_features
```

Expected: PASS.

- [ ] **Step 4: Kiểm chứng số học trên một mã đã biết**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select trade_date, close, ma20, ma50, avg_turnover_20d, volatility_60d,
       high_52w, low_52w, return_12m
from {{ ref('int_price_features') }}
where symbol = 'HPG' order by trade_date desc limit 3
" --limit 3
```

Expected: `avg_turnover_20d` của HPG cỡ **hàng trăm tỷ VNĐ** (2–5e11). Nếu ra cỡ 1e5 nghĩa là chưa nhân `1e6` ở staging.

- [ ] **Step 5: Commit**

```bash
git add transforms/models/intermediate/
git commit -m "feat(dbt): int_price_features — MA, return, thanh khoản, biến động

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `int_fundamentals_ttm` — suy ra doanh thu, lợi nhuận và tăng trưởng

**Files:**
- Create: `transforms/models/intermediate/int_fundamentals_ttm.sql`
- Modify: `transforms/models/intermediate/_intermediate.yml`
- Create: `transforms/tests/assert_derived_revenue_sanity.sql`, `assert_growth_uses_calendar_alignment.sql`

**Interfaces:**
- Consumes: `ref('stg_financial_ratio')`.
- Produces: `ref('int_fundamentals_ttm')` — hạt `(symbol, period_end_date)`, cột `revenue_ttm, earnings_ttm, book_value, eps, bvps, revenue_yoy, earnings_yoy, revenue_cagr_3y, earnings_cagr_3y, growth_consistency, loss_quarters_12q`

- [ ] **Step 1: Viết test thất bại**

`transforms/tests/assert_derived_revenue_sanity.sql`:

```sql
-- Bắt LỖI CÔNG THỨC, không bắt "mã có định giá cực đoan".
--
-- Bản đầu kiểm từng dòng với dải market_cap/100..market_cap*100 (tương đương
-- ps in [0,01; 100]) và fail 344/36.676 dòng trên production. Điều tra cho thấy
-- đó là dữ liệu THẬT: p99 của ps là 58,9 nhưng p99.9 là 2.146 và max 245.347 —
-- các mã ôm quỹ đất có doanh thu gần bằng 0.
--
-- Một lỗi công thức (quên chia, chia nhầm cột, sai đơn vị) sai HỆ THỐNG trên
-- MỌI dòng, không phải 0,94%. Nên kiểm TRUNG VỊ toàn thị trường: quên chia sẽ
-- làm trung vị nhảy nhiều bậc độ lớn, còn vài trăm mã cực đoan không kéo nổi
-- trung vị. Ngưỡng đặt trong dbt_project.yml (fundamentals_median_ps_min/max).
with med as (
    select median(market_cap / nullif(revenue_ttm, 0)) as median_ps
    from {{ ref('int_fundamentals_ttm') }}
    where revenue_ttm is not null
)
select median_ps from med
where median_ps < {{ var('fundamentals_median_ps_min') }}
   or median_ps > {{ var('fundamentals_median_ps_max') }}

union all

-- Rào chắn hồi quy rẻ tiền: sau khi chặn ps <= 0 ở model thì không dòng nào
-- được có doanh thu suy ra âm hoặc bằng 0.
select revenue_ttm from {{ ref('int_fundamentals_ttm') }} where revenue_ttm <= 0
```

`transforms/tests/assert_growth_uses_calendar_alignment.sql`:

```sql
-- Canh đúng lớp lỗi đã xảy ra: lag() theo VỊ TRÍ DÒNG thay vì theo LỊCH.
-- 87% mã có khoảng trống trong chuỗi quý (2021 Q2 chỉ 177/1.585 mã báo cáo),
-- nên lag(x, 4) lấy nhầm dòng ở đa số trường hợp — đo được 53% dòng
-- revenue_yoy LẬT DẤU tăng trưởng so với tính đúng theo lịch.
--
-- Khẳng định: mọi dòng có revenue_yoy phải TỒN TẠI kỳ đối chiếu đúng lịch
-- (cùng symbol, cùng quarter, year - 1) trong chính model.
select t.symbol, t.year, t.quarter
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y1
       on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
where t.revenue_yoy is not null
  and y1.symbol is null
```

- [ ] **Step 2: Chạy để xác nhận fail**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select int_fundamentals_ttm
```

Expected: FAIL — model chưa tồn tại.

- [ ] **Step 3: Viết model**

```sql
{{ config(materialized='table') }}

-- Vì pe, ps, pb và market_cap cùng thuộc một dòng (cùng thời điểm giá),
-- phép chia triệt tiêu giá và cho ra chỉ tiêu tuyệt đối.
-- Đối chiếu HPG 2024Q4: 138.855 tỷ doanh thu / 12.021 tỷ LNST — khớp BCTC.
-- Chỉ dùng dòng TTM (quarter 1-4); dòng cả năm (quarter=5) bị loại để chuỗi
-- thời gian không lẫn hai loại kỳ.
with ttm as (
    select
        symbol,
        year,
        quarter,
        period_end_date,
        com_class,
        market_cap,
        number_of_shares_mkt_cap                as shares,
        market_cap / nullif(ps, 0)              as revenue_ttm,
        market_cap / nullif(pe, 0)              as earnings_ttm,
        market_cap / nullif(pb, 0)              as book_value,
        is_loss_making
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

-- GHÉP THEO LỊCH, KHÔNG DÙNG lag() THEO DÒNG.
--
-- lag(x, 4) lấy dòng cách 4 VỊ TRÍ, chỉ đúng nếu chuỗi quý liền mạch. Thực tế
-- 1.378/1.585 mã (87%) có khoảng trống — riêng 2021 Q2 chỉ 177/1.585 mã báo cáo.
--
-- Ví dụ minh hoạ bằng chính HPG (thiếu 2021 Q2): từ dòng 2021Q4 lùi 4 VỊ TRÍ
-- được 2021Q3 -> 2021Q1 -> 2020Q4 -> 2020Q3, tức chỉ tới 2020Q3 chứ không tới
-- 2020Q4. Khoảng trống nằm TRONG cửa sổ nhìn lại thì kết quả sai; nằm ngoài
-- thì tình cờ đúng. Ghép theo lịch loại bỏ hẳn sự tình cờ đó.
--
-- Không tồn tại kỳ đối chiếu thì kết quả là NULL — đó là câu trả lời ĐÚNG.
-- Task 10 chuẩn hoá lại trọng số khi gặp NULL nên không gây hại.
with_lags as (
    select
        t.*,
        y1.revenue_ttm  as revenue_4q_ago,
        y1.earnings_ttm as earnings_4q_ago,
        y3.revenue_ttm  as revenue_12q_ago,
        y3.earnings_ttm as earnings_12q_ago,
        -- Số quý tuyệt đối, dùng cho cửa sổ theo LỊCH ở dưới.
        t.year * 4 + t.quarter as abs_quarter
    from ttm t
    left join ttm y1
           on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
    left join ttm y3
           on y3.symbol = t.symbol and y3.year = t.year - 3 and y3.quarter = t.quarter
),

-- Cửa sổ 12 quý phải tính theo LỊCH, không theo 12 dòng liền kề — cùng lý do
-- như trên. `range` trên abs_quarter cho đúng ngữ nghĩa "12 quý gần nhất".
with_windows as (
    select
        *,
        sum(case when is_loss_making then 1 else 0 end) over w12 as loss_quarters_12q
    from with_lags
    window w12 as (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    )
),

with_growth as (
    select
        *,
        revenue_ttm  / nullif(revenue_4q_ago, 0)  - 1 as revenue_yoy,
        earnings_ttm / nullif(earnings_4q_ago, 0) - 1 as earnings_yoy,
        -- CAGR 3 năm chỉ có nghĩa khi mốc gốc dương.
        case when revenue_12q_ago > 0 and revenue_ttm > 0
             then power(revenue_ttm / revenue_12q_ago, 1.0 / 3) - 1 end as revenue_cagr_3y,
        case when earnings_12q_ago > 0 and earnings_ttm > 0
             then power(earnings_ttm / earnings_12q_ago, 1.0 / 3) - 1 end as earnings_cagr_3y
    from with_windows
)

select
    symbol,
    year,
    quarter,
    period_end_date,
    com_class,
    market_cap,
    shares,
    revenue_ttm,
    earnings_ttm,
    book_value,
    earnings_ttm / nullif(shares, 0) as eps,
    book_value   / nullif(shares, 0) as bvps,
    revenue_yoy,
    earnings_yoy,
    revenue_cagr_3y,
    earnings_cagr_3y,
    loss_quarters_12q,
    -- Tính nhất quán tăng trưởng: tỉ lệ quý có YoY doanh thu dương trong 12 quý.
    -- Cửa sổ theo LỊCH (`range` trên abs_quarter), không phải 12 dòng liền kề —
    -- cùng lý do với loss_quarters_12q ở trên.
    avg(case when revenue_yoy > 0 then 1.0
             when revenue_yoy is null then null
             else 0.0 end) over (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    ) as growth_consistency
from with_growth
```

- [ ] **Step 4: Khai báo test trong `_intermediate.yml`**

```yaml
  - name: int_fundamentals_ttm
    description: "Doanh thu/LNST/vốn chủ suy ra từ market_cap và ps/pe/pb, kèm tăng trưởng."
    columns:
      - name: symbol
        tests: [not_null]
      - name: period_end_date
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, period_end_date]
```

- [ ] **Step 5: Chạy dbt để xác nhận pass**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select int_fundamentals_ttm
```

Expected: PASS.

- [ ] **Step 6: Đối chiếu với BCTC thật của HPG**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select year, quarter,
       round(revenue_ttm/1e9)  as doanhthu_ty,
       round(earnings_ttm/1e9) as lnst_ty,
       round(revenue_yoy, 3)   as dt_yoy
from {{ ref('int_fundamentals_ttm') }}
where symbol='HPG' and year in (2024, 2025) order by year, quarter
" --limit 10
```

Expected: 2024 Q4 ≈ **138.855 tỷ doanh thu / 12.021 tỷ LNST** (khớp BCTC HPG 2024). Lệch quá 2% nghĩa là công thức sai.

- [ ] **Step 7: Commit**

```bash
git add transforms/
git commit -m "feat(dbt): int_fundamentals_ttm — suy ra doanh thu/LNST và tăng trưởng

market_cap/ps và market_cap/pe cho TTM tuyệt đối; đối chiếu HPG 2024 khớp BCTC.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `int_quality_metrics`, `int_dividend_history` và bảng chỉ tiêu dạng long

**Files:**
- Create: `transforms/models/intermediate/int_quality_metrics.sql`, `int_dividend_history.sql`, `int_metric_long.sql`
- Modify: `transforms/models/intermediate/_intermediate.yml`

**Interfaces:**
- Consumes: `ref('stg_financial_ratio')`, `ref('int_fundamentals_ttm')`, `ref('int_price_features')`, `ref('stg_company_info')`.
- Produces:
  - `ref('int_quality_metrics')` — `symbol, period_end_date, roe_avg_8q, roe_stability, gross_margin_slope_8q`
  - `ref('int_dividend_history')` — `symbol, dividend_yield_avg_5y, dividend_years_consecutive, dividend_stability`
  - `ref('int_metric_long')` — hạt `(symbol, metric)` cho **kỳ mới nhất**, cột `symbol, com_class, icb_code_lv2, metric, value`

- [ ] **Step 1: Viết `int_quality_metrics.sql`**

```sql
{{ config(materialized='table') }}

-- CỬA SỔ THEO LỊCH, KHÔNG THEO DÒNG.
--
-- 1.378/1.585 mã (87%) có khoảng trống trong chuỗi quý báo cáo — riêng 2021 Q2
-- chỉ 177/1.585 mã báo cáo. Nên `rows between 7 preceding` KHÔNG phải "8 quý
-- gần nhất" mà là "8 dòng gần nhất", có thể trải dài nhiều năm. Đây đúng lớp
-- lỗi đã xảy ra ở int_fundamentals_ttm với lag() theo dòng.
--
-- `abs_quarter = year * 4 + quarter` cho phép dùng `range`, tức cửa sổ theo
-- khoảng cách LỊCH thật. Nó cũng là biến chạy đúng cho regr_slope: hệ số góc
-- phải là "thay đổi biên gộp trên mỗi QUÝ", không phải "trên mỗi dòng có dữ liệu".
with q as (
    select symbol, period_end_date, com_class, roe, gross_margin,
           year * 4 + quarter as abs_quarter
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

rolled as (
    select
        symbol,
        period_end_date,
        com_class,
        avg(roe)         over w8 as roe_avg_8q,
        stddev_samp(roe) over w8 as roe_sd_8q,
        count(roe)       over w8 as roe_n_8q,
        -- Hệ số góc xu hướng biên gộp: dương = biên đang cải thiện.
        regr_slope(gross_margin, abs_quarter) over w8 as gross_margin_slope_8q
    from q
    window w8 as (partition by symbol order by abs_quarter
                  range between 7 preceding and current row)
)

select
    symbol,
    period_end_date,
    com_class,
    roe_avg_8q,
    gross_margin_slope_8q,
    -- Độ bền ROE = 1 - hệ số biến thiên, chặn về [0, 1].
    -- Doanh nghiệp lỗ (ROE trung bình <= 0) KHÔNG có "độ bền" → 0.
    case
        when roe_n_8q < 4 or roe_avg_8q is null then null
        when roe_avg_8q <= 0                    then 0.0
        else greatest(0.0, least(1.0, 1 - roe_sd_8q / nullif(abs(roe_avg_8q), 0)))
    end as roe_stability
from rolled
```

- [ ] **Step 2: Viết `int_dividend_history.sql`**

```sql
{{ config(materialized='table') }}

-- Đếm trên các dòng NĂM (quarter = 5), không phải dòng TTM.
with yearly as (
    select symbol, year, dividend_yield
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5 and dividend_yield is not null
),

latest_year as (
    select symbol, max(year) as max_year from yearly group by 1
),

-- Đánh dấu năm KHÔNG trả cổ tức để cắt chuỗi liên tiếp.
gapped as (
    select
        y.symbol,
        y.year,
        y.dividend_yield,
        l.max_year,
        max(case when y.dividend_yield <= 0 then y.year end)
            over (partition by y.symbol) as last_zero_year
    from yearly y
    join latest_year l using (symbol)
)

select
    symbol,
    avg(case when year >= max_year - 4 then dividend_yield end) as dividend_yield_avg_5y,
    -- Số năm liên tiếp có cổ tức, tính lùi từ năm gần nhất.
    count(*) filter (
        where dividend_yield > 0
          and (last_zero_year is null or year > last_zero_year)
    ) as dividend_years_consecutive,
    case
        when avg(dividend_yield) is null or avg(dividend_yield) <= 0 then 0.0
        else greatest(0.0, least(1.0,
             1 - stddev_samp(dividend_yield) / nullif(avg(dividend_yield), 0)))
    end as dividend_stability
from gapped
group by symbol
```

- [ ] **Step 3: Viết `int_metric_long.sql`**

```sql
{{ config(materialized='table') }}

{% set metric_list = all_metrics() %}

-- Kỳ tỷ số mới nhất của mỗi mã (chỉ dòng TTM).
with latest_period as (
    select symbol, max(period_end_date) as period_end_date
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
    group by 1
),

ratio_latest as (
    select f.*
    from {{ ref('stg_financial_ratio') }} f
    join latest_period p using (symbol, period_end_date)
    where f.quarter between 1 and 4
),

-- (1) 44 chỉ tiêu gốc → dạng long. UNPIVOT của DuckDB tự bỏ giá trị NULL.
-- Dùng cú pháp UNPIVOT chuẩn SQL (đặt sau FROM) vì nó lồng được trong CTE.
ratio_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from (
        select symbol, com_class, icb_code_lv2,
               {{ metric_list | join(', ') }}
        from ratio_latest
    )
    unpivot (value for metric in ({{ metric_list | join(', ') }}))
),

-- (2) Chỉ tiêu suy ra ở kỳ mới nhất.
fund_latest as (
    select f.symbol, f.com_class, c.icb_code_lv2,
           f.revenue_yoy, f.earnings_yoy, f.revenue_cagr_3y,
           f.earnings_cagr_3y, f.growth_consistency,
           cast(f.loss_quarters_12q as double) as loss_quarters_12q
    from {{ ref('int_fundamentals_ttm') }} f
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

fund_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from fund_latest
    unpivot (value for metric in (
        revenue_yoy, earnings_yoy, revenue_cagr_3y, earnings_cagr_3y,
        growth_consistency, loss_quarters_12q))
),

qual_latest as (
    select q.symbol, q.com_class, c.icb_code_lv2,
           q.roe_avg_8q, q.roe_stability, q.gross_margin_slope_8q
    from {{ ref('int_quality_metrics') }} q
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

qual_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from qual_latest
    unpivot (value for metric in (
        roe_avg_8q, roe_stability, gross_margin_slope_8q))
),

div_latest as (
    select d.symbol, c.com_class, c.icb_code_lv2,
           d.dividend_yield_avg_5y,
           cast(d.dividend_years_consecutive as double) as dividend_years_consecutive,
           d.dividend_stability
    from {{ ref('int_dividend_history') }} d
    left join {{ ref('stg_company_info') }} c using (symbol)
),

div_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from div_latest
    unpivot (value for metric in (
        dividend_yield_avg_5y, dividend_years_consecutive, dividend_stability))
),

-- (3) Chỉ tiêu giá ở phiên mới nhất.
price_latest as (
    select p.symbol, c.com_class, c.icb_code_lv2,
           p.avg_turnover_20d, p.volatility_60d,
           cast(c.listing_age_years as double) as listing_age_years,
           c.free_float_percentage
    from {{ ref('int_price_features') }} p
    join (
        select symbol, max(trade_date) as trade_date
        from {{ ref('int_price_features') }} group by 1
    ) m using (symbol, trade_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

price_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from price_latest
    unpivot (value for metric in (
        avg_turnover_20d, volatility_60d, listing_age_years,
        free_float_percentage))
)

select symbol, com_class, icb_code_lv2, lower(metric) as metric, value
from (
    select * from ratio_long
    union all select * from fund_long
    union all select * from qual_long
    union all select * from div_long
    union all select * from price_long
)
where value is not null
  and isfinite(value)
```

- [ ] **Step 4: Khai báo test trong `_intermediate.yml`**

```yaml
  - name: int_quality_metrics
    columns:
      - name: symbol
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, period_end_date]

  - name: int_dividend_history
    columns:
      - name: symbol
        tests: [not_null, unique]

  - name: int_metric_long
    columns:
      - name: symbol
        tests: [not_null]
      - name: metric
        tests: [not_null]
      - name: value
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, metric]
```

- [ ] **Step 5: Chạy dbt**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select int_quality_metrics int_dividend_history int_metric_long
```

Expected: PASS.

- [ ] **Step 6: Kiểm chứng ngân hàng có chỉ tiêu riêng, phi tài chính không có**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select com_class, metric, count(*) n
from {{ ref('int_metric_long') }}
where metric in ('roic','npl','net_interest_margin','current_ratio','roe_avg_8q')
group by 1,2 order by 1,2
" --limit 20
```

Expected: `BANK` có `npl`, `net_interest_margin`, `roe_avg_8q` nhưng **không** có `roic`/`current_ratio`; `NONFIN` ngược lại.

- [ ] **Step 7: Commit**

```bash
git add transforms/
git commit -m "feat(dbt): chỉ tiêu chất lượng, cổ tức và bảng long int_metric_long

Dạng long (symbol, metric, value) cho phép áp percentile và trọng số
bằng join với seed thay vì SQL cứng 44 cột.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `int_valuation_percentile` — percentile định giá so với chính mã và so với ngành

**Files:**
- Create: `transforms/models/intermediate/int_valuation_percentile.sql`, `int_metric_percentile.sql`
- Modify: `transforms/models/intermediate/_intermediate.yml`
- Create: `transforms/tests/assert_percentile_in_bounds.sql`, `assert_peer_group_min_size.sql`

**Interfaces:**
- Consumes: `ref('stg_financial_ratio')`, `ref('int_metric_long')`.
- Produces:
  - `ref('int_valuation_percentile')` — `symbol, period_end_date, pe, pb, ps, pe_pct_own_5y, pb_pct_own_5y, pe_quarters_used, pb_quarters_used`
  - `ref('int_metric_percentile')` — `symbol, com_class, metric, value, pct_peer, peer_basis, peer_count`

- [ ] **Step 1: Viết test thất bại**

`transforms/tests/assert_percentile_in_bounds.sql`:

```sql
select symbol, metric, pct_peer
from {{ ref('int_metric_percentile') }}
where pct_peer is not null and (pct_peer < 0 or pct_peer > 1)

union all

select symbol, 'pe_pct_own_5y' as metric, pe_pct_own_5y
from {{ ref('int_valuation_percentile') }}
where pe_pct_own_5y is not null and (pe_pct_own_5y < 0 or pe_pct_own_5y > 1)
```

`transforms/tests/assert_peer_group_min_size.sql`:

```sql
-- Mọi percentile peer phải dựa trên đủ số mã, nếu không xếp hạng vô nghĩa.
select symbol, metric, peer_basis, peer_count
from {{ ref('int_metric_percentile') }}
where pct_peer is not null
  and peer_count < {{ var('peer_hard_min') }}
```

- [ ] **Step 2: Chạy để xác nhận fail**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select int_metric_percentile
```

Expected: FAIL — model chưa tồn tại.

- [ ] **Step 3: Viết `int_valuation_percentile.sql`**

```sql
{{ config(materialized='table') }}

-- Percentile P/E và P/B của kỳ hiện tại SO VỚI CHÍNH MÃ trong 20 quý gần nhất.
-- Chỉ tính trên các quý mà tỷ số có nghĩa (loại quý lỗ và quý P/E dị thường).
with hist as (
    select
        symbol,
        period_end_date,
        year * 4 + quarter as abs_quarter,
        pe,
        pb,
        ps,
        case when pe_meaningful then pe end as pe_valid,
        case when pb_meaningful then pb end as pb_valid
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

ranked as (
    select
        *,
        percent_rank() over (
            partition by symbol order by pe_valid
        ) as pe_pct_all_history,
        percent_rank() over (
            partition by symbol order by pb_valid
        ) as pb_pct_all_history,
        -- Cửa sổ theo LỊCH (`range` trên abs_quarter), không theo dòng: 87% mã
        -- có khoảng trống chuỗi quý nên 20 dòng liền kề có thể trải dài hơn 5 năm.
        count(pe_valid) over (
            partition by symbol
            order by abs_quarter
            range between 19 preceding and current row
        ) as pe_quarters_20,
        count(pb_valid) over (
            partition by symbol
            order by abs_quarter
            range between 19 preceding and current row
        ) as pb_quarters_20
    from hist
)

select
    symbol,
    period_end_date,
    pe,
    pb,
    ps,
    -- Yêu cầu tối thiểu số quý hợp lệ, nếu không percentile không đáng tin.
    case when pe_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pe_pct_all_history end as pe_pct_own_5y,
    case when pb_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pb_pct_all_history end as pb_pct_own_5y,
    pe_quarters_20 as pe_quarters_used,
    pb_quarters_20 as pb_quarters_used
from ranked
```

- [ ] **Step 4: Viết `int_metric_percentile.sql`**

```sql
{{ config(materialized='table') }}

-- Percentile của từng chỉ tiêu trong NHÓM TƯƠNG ĐƯƠNG.
-- Ưu tiên nhóm hẹp (cùng com_class + cùng ngành ICB lv2); nếu nhóm quá nhỏ
-- thì lùi về cùng com_class toàn thị trường. peer_basis ghi lại lựa chọn đó
-- để agent nói rõ "rẻ hơn ngành" là so với bao nhiêu mã.
with base as (
    select
        symbol,
        com_class,
        coalesce(icb_code_lv2, 'UNKNOWN') as icb_code_lv2,
        metric,
        value
    from {{ ref('int_metric_long') }}
    -- Loại mã chưa xác định được loại hình khỏi MỌI rổ percentile (nợ N2 từ A1).
    -- Chúng thiếu dòng trong raw_company_info nên không biết áp bộ chỉ tiêu nào;
    -- để lẫn vào rổ sẽ làm lệch percentile của cả nhóm.
    where com_class <> 'UNKNOWN'
),

sized as (
    select
        *,
        count(*) over (partition by metric, com_class, icb_code_lv2) as n_sector,
        count(*) over (partition by metric, com_class)               as n_class
    from base
),

chosen as (
    select
        *,
        case when n_sector >= {{ var('peer_min_size') }}
             then 'com_class+icb_lv2' else 'com_class' end as peer_basis,
        case when n_sector >= {{ var('peer_min_size') }}
             then n_sector else n_class end                as peer_count
    from sized
),

ranked as (
    select
        *,
        percent_rank() over (
            partition by metric, com_class, icb_code_lv2 order by value
        ) as pct_sector,
        percent_rank() over (
            partition by metric, com_class order by value
        ) as pct_class
    from chosen
)

select
    symbol,
    com_class,
    icb_code_lv2,
    metric,
    value,
    peer_basis,
    peer_count,
    case
        when peer_count < {{ var('peer_hard_min') }} then null
        when peer_basis = 'com_class+icb_lv2'        then pct_sector
        else pct_class
    end as pct_peer
from ranked
```

- [ ] **Step 5: Khai báo test trong `_intermediate.yml`**

```yaml
  - name: int_valuation_percentile
    columns:
      - name: symbol
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, period_end_date]

  - name: int_metric_percentile
    columns:
      - name: symbol
        tests: [not_null]
      - name: metric
        tests: [not_null]
      - name: peer_basis
        tests:
          - accepted_values:
              values: ['com_class+icb_lv2', 'com_class']
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, metric]
```

- [ ] **Step 6: Chạy dbt để xác nhận pass**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select intermediate
```

Expected: PASS — mọi model và test xanh.

- [ ] **Step 7: Kiểm chứng phân bố percentile**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select peer_basis, count(distinct metric) so_chi_tieu, count(*) n,
       round(min(peer_count)) nho_nhat, round(max(peer_count)) lon_nhat
from {{ ref('int_metric_percentile') }}
where pct_peer is not null group by 1
" --limit 5
```

Expected: cả hai `peer_basis` đều xuất hiện; `nho_nhat` ≥ 8.

- [ ] **Step 8: Commit**

```bash
git add transforms/
git commit -m "feat(dbt): percentile định giá so với chính mã và so với nhóm tương đương

Cơ chế lùi nhóm: ngành ICB lv2 nếu >= 15 mã, ngược lại com_class toàn TT.
peer_basis/peer_count ghi lại để agent nêu rõ mức tin cậy.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Marts nền — `dim_stock`, `dim_industry`, `fct_price_daily`, `fct_financial_quarterly`

**Files:**
- Create: `transforms/models/marts/dim_stock.sql`, `dim_industry.sql`, `fct_price_daily.sql`, `fct_financial_quarterly.sql`
- Create: `transforms/models/marts/_marts.yml`

**Interfaces:**
- Consumes: mọi model staging và intermediate.
- Produces:
  - `ref('dim_stock')` — 1 dòng/mã
  - `ref('dim_industry')` — 1 dòng/mã ngành cấp 4, kèm cấp 2 và 3
  - `ref('fct_price_daily')` — mã × phiên
  - `ref('fct_financial_quarterly')` — mã × quý

- [ ] **Step 1: Viết `dim_industry.sql`**

```sql
{{ config(materialized='table') }}

-- Nguồn VCI đánh mã cấp 1 dạng '0001' không theo tiền tố, nên chỉ ghép được
-- cấp 2 → 4 bằng tiền tố mã ICB (0500 → 0530 → 0533).
with lv as (select * from {{ ref('stg_industry') }})

select
    l4.icb_code               as icb_code_lv4,
    l4.icb_name               as icb_name_lv4,
    l4.en_icb_name            as en_icb_name_lv4,
    l3.icb_code               as icb_code_lv3,
    l3.icb_name               as icb_name_lv3,
    l2.icb_code               as icb_code_lv2,
    l2.icb_name               as icb_name_lv2,
    l2.en_icb_name            as en_icb_name_lv2
from lv l4
left join lv l3
       on l3.level = 3 and substr(l4.icb_code, 1, 3) = substr(l3.icb_code, 1, 3)
left join lv l2
       on l2.level = 2 and substr(l4.icb_code, 1, 2) = substr(l2.icb_code, 1, 2)
where l4.level = 4
```

- [ ] **Step 2: Viết `dim_stock.sql`**

```sql
{{ config(materialized='table') }}

with px as (
    select p.*
    from {{ ref('int_price_features') }} p
    join (select symbol, max(trade_date) as trade_date
          from {{ ref('int_price_features') }} group by 1) m
      using (symbol, trade_date)
),

ind2 as (
    select icb_code, icb_name, en_icb_name from {{ ref('stg_industry') }} where level = 2
),
ind4 as (
    select icb_code, icb_name, en_icb_name from {{ ref('stg_industry') }} where level = 4
)

select
    c.symbol,
    c.company_name,
    c.short_name,
    c.exchange,
    c.com_class,
    c.com_type_code,
    c.is_bank,
    c.icb_code_lv2,
    i2.icb_name    as industry_lv2,
    i2.en_icb_name as industry_lv2_en,
    c.icb_code_lv4,
    i4.icb_name    as industry_lv4,
    c.sector,
    c.market_cap,
    c.issue_share,
    c.free_float_percentage,
    c.foreigner_percentage,
    c.state_percentage,
    c.listed_date,
    c.listing_age_years,
    px.trade_date       as price_as_of,
    px.close            as last_close,
    px.avg_turnover_20d,
    px.avg_turnover_60d,
    px.volatility_60d,
    px.high_52w,
    px.low_52w,
    px.return_1m,
    px.return_3m,
    px.return_12m,
    px.sessions_1y,
    (s.symbol is not null and s.is_active) as is_active
from {{ ref('stg_company_info') }} c
left join px using (symbol)
left join ind2 i2 on i2.icb_code = c.icb_code_lv2
left join ind4 i4 on i4.icb_code = c.icb_code_lv4
left join {{ source('warehouse', 'dim_symbols') }} s on s.symbol = c.symbol
```

- [ ] **Step 3: Viết `fct_price_daily.sql`**

```sql
{{ config(materialized='table', tags=['daily']) }}

select
    p.symbol,
    p.trade_date,
    s.open, s.high, s.low, p.close, p.volume,
    s.value_vnd, s.turnover_vnd,
    p.ma20, p.ma50, p.ma200,
    p.return_1m, p.return_3m, p.return_6m, p.return_12m, p.return_ytd,
    p.avg_turnover_20d, p.avg_turnover_60d,
    p.volatility_60d, p.high_52w, p.low_52w, p.pct_from_high_52w
from {{ ref('int_price_features') }} p
join {{ ref('stg_price_daily') }} s using (symbol, trade_date)
```

- [ ] **Step 4: Viết `fct_financial_quarterly.sql`**

```sql
{{ config(materialized='table') }}

select
    f.symbol,
    f.year,
    f.quarter,
    f.period_end_date,
    f.period_type,
    f.com_class,
    f.* exclude (symbol, year, quarter, period_end_date, period_type,
                 com_class, ratio_type, icb_code_lv2, icb_code_lv4),
    t.revenue_ttm,
    t.earnings_ttm,
    t.book_value,
    t.eps,
    t.bvps,
    t.revenue_yoy,
    t.earnings_yoy,
    t.revenue_cagr_3y,
    t.earnings_cagr_3y,
    t.growth_consistency,
    t.loss_quarters_12q,
    q.roe_avg_8q,
    q.roe_stability,
    q.gross_margin_slope_8q
from {{ ref('stg_financial_ratio') }} f
left join {{ ref('int_fundamentals_ttm') }} t using (symbol, period_end_date)
left join {{ ref('int_quality_metrics') }}  q using (symbol, period_end_date)
```

- [ ] **Step 5: Khai báo test — `transforms/models/marts/_marts.yml`**

```yaml
version: 2

models:
  - name: dim_stock
    description: "Một dòng mỗi mã: hồ sơ, ngành, loại hình, thanh khoản."
    columns:
      - name: symbol
        tests: [not_null, unique]
      - name: com_class
        tests:
          - not_null
          - accepted_values:
              values: ['NONFIN', 'BANK', 'OTHERFIN', 'UNKNOWN']

  - name: dim_industry
    columns:
      - name: icb_code_lv4
        tests: [not_null, unique]

  - name: fct_price_daily
    columns:
      - name: symbol
        tests:
          - not_null
          - relationships:
              to: ref('dim_stock')
              field: symbol
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, trade_date]

  - name: fct_financial_quarterly
    columns:
      - name: symbol
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, year, quarter]
```

- [ ] **Step 6: Chạy dbt**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select dim_stock dim_industry fct_price_daily fct_financial_quarterly
```

Expected: PASS.

> **Nếu test `relationships` fail:** có mã trong `raw_price_daily` nhưng thiếu trong `raw_company_info`. Chạy `python build_warehouse.py --mode monthly` để bổ sung, rồi build lại.

- [ ] **Step 7: Commit**

```bash
git add transforms/models/marts/
git commit -m "feat(dbt): marts nền dim_stock, dim_industry, fct_price_daily, fct_financial_quarterly

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: `mart_valuation_band` và `mart_sector_snapshot`

**Files:**
- Create: `transforms/models/marts/mart_valuation_band.sql`, `mart_sector_snapshot.sql`
- Modify: `transforms/models/marts/_marts.yml`

**Interfaces:**
- Consumes: `ref('int_valuation_percentile')`, `ref('stg_financial_ratio')`, `ref('dim_stock')`, `ref('fct_price_daily')`.
- Produces:
  - `ref('mart_valuation_band')` — `symbol, period_end_date, pe, pb, pe_pct_own_5y, pb_pct_own_5y, valuation_band`
  - `ref('mart_sector_snapshot')` — `icb_code_lv2, industry_lv2, com_class, period_end_date, n_symbols, median_pe, median_pb, median_roe, sector_return_3m`

- [ ] **Step 1: Viết `mart_valuation_band.sql`**

```sql
{{ config(materialized='table') }}

select
    v.symbol,
    v.period_end_date,
    d.com_class,
    d.icb_code_lv2,
    d.industry_lv2,
    v.pe,
    v.pb,
    v.ps,
    v.pe_pct_own_5y,
    v.pb_pct_own_5y,
    v.pe_quarters_used,
    v.pb_quarters_used,
    -- Nhãn vùng định giá dựa trên percentile lịch sử CỦA CHÍNH MÃ.
    -- NULL khi chưa đủ 12 quý hợp lệ — không đoán bừa.
    case
        when v.pe_pct_own_5y is null  then null
        when v.pe_pct_own_5y < 0.20   then 'rất rẻ'
        when v.pe_pct_own_5y < 0.40   then 'rẻ'
        when v.pe_pct_own_5y < 0.60   then 'hợp lý'
        when v.pe_pct_own_5y < 0.80   then 'đắt'
        else                               'rất đắt'
    end as valuation_band
from {{ ref('int_valuation_percentile') }} v
left join {{ ref('dim_stock') }} d using (symbol)
```

- [ ] **Step 2: Viết `mart_sector_snapshot.sql`**

```sql
{{ config(materialized='table') }}

with ratios as (
    select
        f.symbol,
        f.period_end_date,
        f.com_class,
        d.icb_code_lv2,
        d.industry_lv2,
        case when f.pe_meaningful then f.pe end as pe,
        case when f.pb_meaningful then f.pb end as pb,
        f.roe
    from {{ ref('stg_financial_ratio') }} f
    join {{ ref('dim_stock') }} d using (symbol)
    where f.quarter between 1 and 4
),

sector_return as (
    select d.icb_code_lv2, d.com_class,
           sum(p.return_3m * d.market_cap) / nullif(sum(d.market_cap), 0) as sector_return_3m
    from {{ ref('dim_stock') }} d
    join (select symbol, max(trade_date) as trade_date
          from {{ ref('fct_price_daily') }} group by 1) m using (symbol)
    join {{ ref('fct_price_daily') }} p using (symbol, trade_date)
    where d.market_cap is not null and p.return_3m is not null
    group by 1, 2
)

select
    r.icb_code_lv2,
    r.industry_lv2,
    r.com_class,
    r.period_end_date,
    count(distinct r.symbol) as n_symbols,
    median(r.pe)             as median_pe,
    median(r.pb)             as median_pb,
    median(r.roe)            as median_roe,
    max(s.sector_return_3m)  as sector_return_3m
from ratios r
left join sector_return s
       on s.icb_code_lv2 = r.icb_code_lv2 and s.com_class = r.com_class
group by 1, 2, 3, 4
```

- [ ] **Step 3: Khai báo test**

```yaml
  - name: mart_valuation_band
    columns:
      - name: symbol
        tests: [not_null]
      - name: valuation_band
        tests:
          - accepted_values:
              values: ['rất rẻ', 'rẻ', 'hợp lý', 'đắt', 'rất đắt']
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [symbol, period_end_date]

  - name: mart_sector_snapshot
    columns:
      - name: icb_code_lv2
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [icb_code_lv2, com_class, period_end_date]
```

- [ ] **Step 4: Chạy dbt và kiểm chứng**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select mart_valuation_band mart_sector_snapshot
```

Expected: PASS.

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select valuation_band, count(*) n from {{ ref('mart_valuation_band') }}
where period_end_date = (select max(period_end_date) from {{ ref('mart_valuation_band') }})
group by 1 order by 1
" --limit 10
```

Expected: cả 5 nhãn đều xuất hiện, phân bố tương đối đều (mỗi nhãn ~20%).

- [ ] **Step 5: Commit**

```bash
git add transforms/models/marts/
git commit -m "feat(dbt): mart_valuation_band + mart_sector_snapshot

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `mart_data_quality` — độ tin cậy dữ liệu từng mã

**Files:**
- Create: `transforms/models/marts/mart_data_quality.sql`
- Modify: `transforms/models/marts/_marts.yml`

**Interfaces:**
- Consumes: `ref('stg_financial_ratio')`, `ref('stg_price_daily')`, `ref('dim_stock')`.
- Produces: `ref('mart_data_quality')` — `symbol, quarters_available, price_sessions_1y, ratio_age_days, max_price_gap_days, data_quality_score` (0–100), `data_quality_ratio` (0–1), `quality_flags` (VARCHAR)

- [ ] **Step 1: Viết model**

```sql
{{ config(materialized='table') }}

with ratio_stats as (
    select
        symbol,
        count(*) filter (where quarter between 1 and 4) as quarters_available,
        date_diff('day', max(period_end_date), current_date) as ratio_age_days
    from {{ ref('stg_financial_ratio') }}
    group by 1
),

price_stats as (
    select
        symbol,
        count(*) filter (where trade_date >= current_date - interval '365 days')
            as price_sessions_1y,
        max(gap_days) as max_price_gap_days
    from (
        select
            symbol,
            trade_date,
            date_diff('day',
                lag(trade_date) over (partition by symbol order by trade_date),
                trade_date) as gap_days
        from {{ ref('stg_price_daily') }}
        where trade_date >= current_date - interval '365 days'
    )
    group by 1
),

-- Ngân hàng phải có NIM và NPL; phi tài chính phải có ROIC. Thiếu = sentinel
-- chưa được xử lý đúng hoặc nguồn không trả dữ liệu.
required_ok as (
    select
        f.symbol,
        max(case
            when f.com_class = 'BANK'
                then (f.net_interest_margin is not null and f.npl is not null)::int
            when f.com_class = 'NONFIN'
                then (f.roic is not null)::int
            else 1
        end) as has_required_metrics
    from {{ ref('stg_financial_ratio') }} f
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('stg_financial_ratio') }} where quarter between 1 and 4
          group by 1) m using (symbol, period_end_date)
    group by 1
),

scored as (
    select
        d.symbol,
        coalesce(r.quarters_available, 0)  as quarters_available,
        coalesce(p.price_sessions_1y, 0)   as price_sessions_1y,
        r.ratio_age_days,
        coalesce(p.max_price_gap_days, 999) as max_price_gap_days,
        coalesce(q.has_required_metrics, 0) as has_required_metrics,
        -- 5 thành phần, tổng trọng số = 1.
        0.30 * least(1.0, coalesce(r.quarters_available, 0) / 20.0)
      + 0.25 * least(1.0, coalesce(p.price_sessions_1y, 0) / 240.0)
      + 0.20 * case when r.ratio_age_days is null then 0.0
                    when r.ratio_age_days <= 120  then 1.0
                    when r.ratio_age_days <= 240  then 0.5
                    else 0.0 end
      + 0.15 * coalesce(q.has_required_metrics, 0)
      + 0.10 * case when coalesce(p.max_price_gap_days, 999) <= 10 then 1.0 else 0.0 end
            as ratio
    from {{ ref('dim_stock') }} d
    left join ratio_stats r using (symbol)
    left join price_stats p using (symbol)
    left join required_ok q using (symbol)
)

select
    symbol,
    quarters_available,
    price_sessions_1y,
    ratio_age_days,
    max_price_gap_days,
    (has_required_metrics = 1) as has_required_metrics,
    ratio                      as data_quality_ratio,
    round(ratio * 100, 1)      as data_quality_score,
    concat_ws('; ',
        case when quarters_available < 12 then 'thiếu lịch sử tỷ số (<12 quý)' end,
        case when price_sessions_1y < 200 then 'thiếu phiên giá trong 1 năm' end,
        case when ratio_age_days > 240    then 'tỷ số quá cũ (>8 tháng)' end,
        case when has_required_metrics = 0 then 'thiếu chỉ tiêu bắt buộc của loại hình' end,
        case when max_price_gap_days > 10 then 'có khoảng trống giá >10 ngày' end
    ) as quality_flags
from scored
```

- [ ] **Step 2: Khai báo test**

```yaml
  - name: mart_data_quality
    columns:
      - name: symbol
        tests: [not_null, unique]
      - name: data_quality_score
        tests:
          - dbt_utils.accepted_range:
              min_value: 0
              max_value: 100
```

- [ ] **Step 3: Chạy dbt và xem phân bố**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select mart_data_quality
```

Expected: PASS.

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select
  count(*) tong,
  count(*) filter (where data_quality_score >= 60) dat_60,
  round(median(data_quality_score),1) trung_vi
from {{ ref('mart_data_quality') }}
" --limit 5
```

Expected: `dat_60` ≥ 800 mã.

- [ ] **Step 4: Commit**

```bash
git add transforms/models/marts/
git commit -m "feat(dbt): mart_data_quality — điểm tin cậy dữ liệu từng mã

Agent phải đọc bảng này trước khi phát biểu về một mã.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: `mart_stock_scorecard` — 5 điểm thành phần

**Files:**
- Create: `transforms/seeds/scoring_weights.csv`
- Create: `transforms/models/marts/mart_stock_scorecard.sql`
- Modify: `transforms/models/marts/_marts.yml`
- Create: `transforms/tests/assert_scorecard_coverage.sql`, `assert_bank_scored_on_quality.sql`

**Interfaces:**
- Consumes: `ref('int_metric_percentile')`, `ref('int_valuation_percentile')`, `ref('mart_data_quality')`, `ref('dim_stock')`.
- Produces: `ref('mart_stock_scorecard')` — 1 dòng/mã, cột `symbol, com_class, peer_basis, peer_count, value_score, quality_score, growth_score, dividend_score, safety_score, *_metrics_used, is_loss_making, data_quality_score, facts` (JSON)

- [ ] **Step 1: Tạo seed `transforms/seeds/scoring_weights.csv`**

`scale`: `peer` = dùng percentile trong nhóm tương đương; `direct` = giá trị đã ở thang [0,1], dùng thẳng.
`direction`: `higher` = cao thì tốt; `lower` = thấp thì tốt.

```csv
com_class,component,metric,direction,scale,weight
NONFIN,value,pe_pct_own_5y,lower,direct,0.30
NONFIN,value,pb_pct_own_5y,lower,direct,0.20
NONFIN,value,pe,lower,peer,0.25
NONFIN,value,pb,lower,peer,0.15
NONFIN,value,ev_to_ebitda,lower,peer,0.10
BANK,value,pe_pct_own_5y,lower,direct,0.35
BANK,value,pb_pct_own_5y,lower,direct,0.25
BANK,value,pe,lower,peer,0.25
BANK,value,pb,lower,peer,0.15
OTHERFIN,value,pe_pct_own_5y,lower,direct,0.35
OTHERFIN,value,pb_pct_own_5y,lower,direct,0.25
OTHERFIN,value,pe,lower,peer,0.25
OTHERFIN,value,pb,lower,peer,0.15
NONFIN,quality,roe_avg_8q,higher,peer,0.25
NONFIN,quality,roe_stability,higher,direct,0.20
NONFIN,quality,roic,higher,peer,0.20
NONFIN,quality,gross_margin_slope_8q,higher,peer,0.10
NONFIN,quality,current_ratio,higher,peer,0.10
NONFIN,quality,debt_to_equity,lower,peer,0.15
BANK,quality,roe_avg_8q,higher,peer,0.25
BANK,quality,roe_stability,higher,direct,0.15
BANK,quality,net_interest_margin,higher,peer,0.15
BANK,quality,cir,lower,peer,0.15
BANK,quality,npl,lower,peer,0.20
BANK,quality,casa_ratio,higher,peer,0.05
BANK,quality,ldr_loan_deposit_ratio,lower,peer,0.05
OTHERFIN,quality,roe_avg_8q,higher,peer,0.35
OTHERFIN,quality,roe_stability,higher,direct,0.25
OTHERFIN,quality,after_tax_profit_margin,higher,peer,0.20
OTHERFIN,quality,debt_to_equity,lower,peer,0.20
NONFIN,growth,revenue_cagr_3y,higher,peer,0.30
NONFIN,growth,earnings_cagr_3y,higher,peer,0.30
NONFIN,growth,revenue_yoy,higher,peer,0.15
NONFIN,growth,earnings_yoy,higher,peer,0.15
NONFIN,growth,growth_consistency,higher,direct,0.10
OTHERFIN,growth,revenue_cagr_3y,higher,peer,0.30
OTHERFIN,growth,earnings_cagr_3y,higher,peer,0.30
OTHERFIN,growth,revenue_yoy,higher,peer,0.15
OTHERFIN,growth,earnings_yoy,higher,peer,0.15
OTHERFIN,growth,growth_consistency,higher,direct,0.10
BANK,growth,loans_growth,higher,peer,0.30
BANK,growth,earnings_cagr_3y,higher,peer,0.30
BANK,growth,deposit_growth,higher,peer,0.15
BANK,growth,earnings_yoy,higher,peer,0.15
BANK,growth,growth_consistency,higher,direct,0.10
NONFIN,dividend,dividend_yield,higher,peer,0.30
NONFIN,dividend,dividend_yield_avg_5y,higher,peer,0.25
NONFIN,dividend,dividend_years_consecutive,higher,peer,0.30
NONFIN,dividend,dividend_stability,higher,direct,0.15
BANK,dividend,dividend_yield,higher,peer,0.30
BANK,dividend,dividend_yield_avg_5y,higher,peer,0.25
BANK,dividend,dividend_years_consecutive,higher,peer,0.30
BANK,dividend,dividend_stability,higher,direct,0.15
OTHERFIN,dividend,dividend_yield,higher,peer,0.30
OTHERFIN,dividend,dividend_yield_avg_5y,higher,peer,0.25
OTHERFIN,dividend,dividend_years_consecutive,higher,peer,0.30
OTHERFIN,dividend,dividend_stability,higher,direct,0.15
NONFIN,safety,avg_turnover_20d,higher,peer,0.20
NONFIN,safety,market_cap,higher,peer,0.15
NONFIN,safety,free_float_percentage,higher,peer,0.10
NONFIN,safety,volatility_60d,lower,peer,0.15
NONFIN,safety,loss_quarters_12q,lower,peer,0.20
NONFIN,safety,listing_age_years,higher,peer,0.10
NONFIN,safety,data_quality_ratio,higher,direct,0.10
BANK,safety,avg_turnover_20d,higher,peer,0.20
BANK,safety,market_cap,higher,peer,0.15
BANK,safety,free_float_percentage,higher,peer,0.10
BANK,safety,volatility_60d,lower,peer,0.15
BANK,safety,loss_quarters_12q,lower,peer,0.20
BANK,safety,listing_age_years,higher,peer,0.10
BANK,safety,data_quality_ratio,higher,direct,0.10
OTHERFIN,safety,avg_turnover_20d,higher,peer,0.20
OTHERFIN,safety,market_cap,higher,peer,0.15
OTHERFIN,safety,free_float_percentage,higher,peer,0.10
OTHERFIN,safety,volatility_60d,lower,peer,0.15
OTHERFIN,safety,loss_quarters_12q,lower,peer,0.20
OTHERFIN,safety,listing_age_years,higher,peer,0.10
OTHERFIN,safety,data_quality_ratio,higher,direct,0.10
```

Run: `cd transforms && ../.venv/bin/dbt seed --profiles-dir .`
Expected: nạp 79 dòng.

- [ ] **Step 2: Viết test thất bại**

`transforms/tests/assert_scorecard_coverage.sql`:

```sql
-- Phải chấm được ít nhất 800 mã với >= 3 trong 5 điểm thành phần.
select count(*) as n_qualified
from {{ ref('mart_stock_scorecard') }}
where (case when value_score    is not null then 1 else 0 end
     + case when quality_score  is not null then 1 else 0 end
     + case when growth_score   is not null then 1 else 0 end
     + case when dividend_score is not null then 1 else 0 end
     + case when safety_score   is not null then 1 else 0 end) >= 3
having count(*) < 800
```

`transforms/tests/assert_bank_scored_on_quality.sql`:

```sql
-- Phép thử trực tiếp cho lỗi sentinel: ngân hàng PHẢI có quality_score.
-- Nếu sentinel chưa được khử, mọi ngân hàng sẽ có quality_score NULL hoặc 0.
select count(*) as n_banks_scored
from {{ ref('mart_stock_scorecard') }}
where com_class = 'BANK' and quality_score is not null and quality_score > 0
having count(*) < 20
```

- [ ] **Step 3: Chạy để xác nhận fail**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir . --select mart_stock_scorecard
```

Expected: FAIL — model chưa tồn tại.

- [ ] **Step 4: Viết `mart_stock_scorecard.sql`**

```sql
{{ config(materialized='table') }}

-- Bảng chỉ tiêu dạng long, gộp cả percentile peer lẫn các chỉ tiêu đã ở
-- thang [0,1] (pe_pct_own_5y, roe_stability, data_quality_ratio...).
with metric_values as (
    select symbol, com_class, metric, value, pct_peer, peer_basis, peer_count
    from {{ ref('int_metric_percentile') }}

    union all

    -- Percentile định giá so với chính mã: đã ở [0,1], dùng trực tiếp.
    select
        v.symbol, d.com_class, 'pe_pct_own_5y' as metric,
        v.pe_pct_own_5y as value, null as pct_peer,
        'own_history' as peer_basis, v.pe_quarters_used as peer_count
    from {{ ref('int_valuation_percentile') }} v
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_valuation_percentile') }} group by 1) m
      using (symbol, period_end_date)
    join {{ ref('dim_stock') }} d using (symbol)
    where v.pe_pct_own_5y is not null

    union all

    select
        v.symbol, d.com_class, 'pb_pct_own_5y' as metric,
        v.pb_pct_own_5y as value, null as pct_peer,
        'own_history' as peer_basis, v.pb_quarters_used as peer_count
    from {{ ref('int_valuation_percentile') }} v
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_valuation_percentile') }} group by 1) m
      using (symbol, period_end_date)
    join {{ ref('dim_stock') }} d using (symbol)
    where v.pb_pct_own_5y is not null

    union all

    select
        q.symbol, d.com_class, 'data_quality_ratio' as metric,
        q.data_quality_ratio as value, null as pct_peer,
        'own_history' as peer_basis, 1 as peer_count
    from {{ ref('mart_data_quality') }} q
    join {{ ref('dim_stock') }} d using (symbol)
),

-- Ghép trọng số theo (com_class, metric) và quy mọi chỉ tiêu về thang
-- "cao là tốt" trong [0,1].
weighted as (
    select
        m.symbol,
        m.com_class,
        w.component,
        w.metric,
        w.weight,
        m.value,
        m.peer_basis,
        m.peer_count,
        case
            when w.scale = 'direct' then
                case when w.direction = 'lower' then 1 - m.value else m.value end
            when m.pct_peer is null then null
            when w.direction = 'lower' then 1 - m.pct_peer
            else m.pct_peer
        end as adj
    from metric_values m
    join {{ ref('scoring_weights') }} w
      on w.com_class = m.com_class and w.metric = m.metric
),

-- Chuẩn hoá lại trọng số trên các chỉ tiêu CÓ dữ liệu (§7.1-6 của spec):
-- chỉ tiêu NULL không kéo điểm xuống, mà bị loại khỏi mẫu số.
component_scores as (
    select
        symbol,
        com_class,
        component,
        round(100 * sum(weight * adj) filter (where adj is not null)
              / nullif(sum(weight) filter (where adj is not null), 0), 1) as raw_score,
        count(*) filter (where adj is not null) as metrics_used,
        count(*)                                as metrics_total
    from weighted
    group by 1, 2, 3
),

-- Dùng được dưới 50% số chỉ tiêu → điểm không đáng tin → NULL.
gated as (
    select
        symbol, com_class, component, metrics_used, metrics_total,
        case when metrics_used * 2 >= metrics_total then raw_score end as score
    from component_scores
),

pivoted as (
    select
        symbol,
        any_value(com_class) as com_class,
        max(score)        filter (where component = 'value')    as value_score,
        max(score)        filter (where component = 'quality')  as quality_score,
        max(score)        filter (where component = 'growth')   as growth_score,
        max(score)        filter (where component = 'dividend') as dividend_score,
        max(score)        filter (where component = 'safety')   as safety_score,
        max(metrics_used) filter (where component = 'value')    as value_metrics_used,
        max(metrics_used) filter (where component = 'quality')  as quality_metrics_used,
        max(metrics_used) filter (where component = 'growth')   as growth_metrics_used,
        max(metrics_used) filter (where component = 'dividend') as dividend_metrics_used,
        max(metrics_used) filter (where component = 'safety')   as safety_metrics_used
    from gated
    group by symbol
),

-- Nhóm tương đương chiếm đa số trong các chỉ tiêu của mã, để agent nêu rõ
-- điểm đang so với bao nhiêu mã.
peer_info as (
    select symbol,
           mode(peer_basis) as peer_basis,
           max(peer_count)  as peer_count
    from {{ ref('int_metric_percentile') }}
    where pct_peer is not null
    group by symbol
),

-- Fact có cấu trúc: mọi con số agent nói ra phải truy ngược về đây.
facts as (
    select
        v.symbol,
        to_json(list_filter([
            {'metric': 'pe_pct_own_5y',
             'value': v.pe_pct_own_5y,
             'text': 'P/E ' || replace(printf('%.1f', v.pe), '.', ',')
                     || ' — thấp hơn '
                     || printf('%.0f', (1 - v.pe_pct_own_5y) * 100)
                     || '% số quý trong 5 năm qua của chính mã'},
            {'metric': 'pb_pct_own_5y',
             'value': v.pb_pct_own_5y,
             'text': 'P/B ' || replace(printf('%.2f', v.pb), '.', ',')
                     || ' — thấp hơn '
                     || printf('%.0f', (1 - v.pb_pct_own_5y) * 100)
                     || '% số quý trong 5 năm qua'},
            {'metric': 'roe_avg_8q',
             'value': q.roe_avg_8q,
             'text': 'ROE trung bình 8 quý '
                     || replace(printf('%.1f', q.roe_avg_8q * 100), '.', ',')
                     || '%, độ bền '
                     || replace(printf('%.2f', q.roe_stability), '.', ',')},
            {'metric': 'dividend_years_consecutive',
             -- ép DOUBLE để mọi phần tử trong list có cùng kiểu struct
             'value': cast(dv.dividend_years_consecutive as double),
             'text': 'Trả cổ tức '
                     || printf('%.0f', dv.dividend_years_consecutive)
                     || ' năm liên tiếp, tỷ suất TB 5 năm '
                     || replace(printf('%.1f', dv.dividend_yield_avg_5y * 100), '.', ',')
                     || '%'},
            {'metric': 'revenue_cagr_3y',
             'value': t.revenue_cagr_3y,
             'text': 'Tăng trưởng doanh thu 3 năm (CAGR) '
                     || replace(printf('%.1f', t.revenue_cagr_3y * 100), '.', ',')
                     || '%'}
        ], x -> x.value is not null)) as facts
    from {{ ref('int_valuation_percentile') }} v
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_valuation_percentile') }} group by 1) m
      using (symbol, period_end_date)
    left join {{ ref('int_quality_metrics') }} q
           on q.symbol = v.symbol and q.period_end_date = v.period_end_date
    left join {{ ref('int_fundamentals_ttm') }} t
           on t.symbol = v.symbol and t.period_end_date = v.period_end_date
    left join {{ ref('int_dividend_history') }} dv on dv.symbol = v.symbol
)

select
    d.symbol,
    d.company_name,
    d.exchange,
    p.com_class,
    d.icb_code_lv2,
    d.industry_lv2,
    pi.peer_basis,
    pi.peer_count,
    p.value_score,
    p.quality_score,
    p.growth_score,
    p.dividend_score,
    p.safety_score,
    p.value_metrics_used,
    p.quality_metrics_used,
    p.growth_metrics_used,
    p.dividend_metrics_used,
    p.safety_metrics_used,
    d.market_cap,
    d.avg_turnover_20d,
    d.last_close,
    d.price_as_of,
    vb.pe,
    vb.pb,
    vb.pe_pct_own_5y,
    vb.pb_pct_own_5y,
    vb.valuation_band,
    vb.period_end_date          as ratio_as_of,
    t.is_loss_making,
    dq.data_quality_score,
    dq.quality_flags,
    dv.dividend_years_consecutive,
    q.roe_avg_8q,
    q.roe_stability,
    f.facts
from pivoted p
join {{ ref('dim_stock') }} d using (symbol)
left join peer_info pi using (symbol)
left join {{ ref('mart_data_quality') }} dq using (symbol)
left join {{ ref('int_dividend_history') }} dv using (symbol)
left join facts f using (symbol)
left join (
    select v.* from {{ ref('mart_valuation_band') }} v
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('mart_valuation_band') }} group by 1) m
      using (symbol, period_end_date)
) vb using (symbol)
left join (
    select q.* from {{ ref('int_quality_metrics') }} q
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_quality_metrics') }} group by 1) m
      using (symbol, period_end_date)
) q using (symbol)
left join (
    select t.symbol, t.is_loss_making from {{ ref('int_fundamentals_ttm') }} t
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_fundamentals_ttm') }} group by 1) m
      using (symbol, period_end_date)
) t using (symbol)
```

- [ ] **Step 5: Khai báo test**

```yaml
  - name: mart_stock_scorecard
    description: "Điểm thành phần từng mã. KHÔNG chứa điểm tổng hợp — điểm đó do src/scoring.py tính theo profile."
    columns:
      - name: symbol
        tests: [not_null, unique]
      - name: value_score
        tests:
          - dbt_utils.accepted_range:
              min_value: 0
              max_value: 100
              where: "value_score is not null"
      - name: quality_score
        tests:
          - dbt_utils.accepted_range:
              min_value: 0
              max_value: 100
              where: "quality_score is not null"
```

- [ ] **Step 6: Chạy dbt để xác nhận pass**

```bash
cd transforms && ../.venv/bin/dbt build --profiles-dir .
```

Expected: PASS toàn bộ — mọi model, mọi test, đặc biệt `assert_bank_scored_on_quality` và `assert_no_bank_sentinel_leak`.

- [ ] **Step 7: Kiểm chứng ngân hàng đã được chấm điểm**

```bash
cd transforms && ../.venv/bin/dbt show --profiles-dir . --inline "
select symbol, com_class, value_score, quality_score, dividend_score,
       quality_metrics_used, peer_basis, peer_count
from {{ ref('mart_stock_scorecard') }}
where com_class = 'BANK' order by quality_score desc nulls last limit 8
" --limit 8
```

Expected: ≥ 20 ngân hàng có `quality_score` khác NULL và > 0. **Nếu toàn NULL: lỗi sentinel chưa được sửa — quay lại Task 2.**

- [ ] **Step 8: Commit**

```bash
git add transforms/
git commit -m "feat(dbt): mart_stock_scorecard — 5 điểm thành phần theo loại hình DN

Trọng số nằm trong seed scoring_weights (79 dòng) thay vì SQL cứng.
Chuẩn hoá lại trọng số khi thiếu chỉ tiêu; <50% chỉ tiêu -> NULL.
Test assert_bank_scored_on_quality là phép thử trực tiếp cho lỗi sentinel.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: `config/scoring_profiles.yml` + `src/scoring.py`

**Files:**
- Create: `config/scoring_profiles.yml`
- Create: `src/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `ref('mart_stock_scorecard')` (Task 10).
- Produces:
  - `src.scoring.load_profiles(path=None) -> dict`
  - `src.scoring.compute_composite(df: pd.DataFrame, profile: dict) -> pd.DataFrame` — thêm cột `composite_score`, `components_missing`
  - `src.scoring.apply_universe(df: pd.DataFrame, profile: dict) -> tuple[pd.DataFrame, pd.DataFrame]` — trả `(đủ_điều_kiện, bị_loại_kèm_lý_do)`
  - `src.scoring.screen(con, profile_name: str, limit: int = 30) -> pd.DataFrame`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_scoring.py`:

```python
import pandas as pd
import pytest

from src import scoring


def _profile():
    return {
        "label": "Test",
        "universe": {
            "exchanges": ["HOSE", "HNX"],
            "min_market_cap_vnd": 1_000_000_000_000,
            "min_avg_turnover_20d_vnd": 1_000_000_000,
            "min_data_quality_score": 60,
        },
        "weights": {"value": 0.25, "quality": 0.30, "dividend": 0.30,
                    "growth": 0.05, "safety": 0.10},
        "require": {"dividend_years_min": 3, "roe_avg_8q_min": 0.12},
    }


def _rows():
    return pd.DataFrame([
        # đủ điều kiện, điểm cao
        {"symbol": "AAA", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # thiếu quality_score (NULL) → phải bị loại vì weight quality > 0
        {"symbol": "BBB", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": None, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # sàn UPCOM → ngoài universe
        {"symbol": "CCC", "exchange": "UPCOM", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # cổ tức chỉ 1 năm → không đạt require
        {"symbol": "DDD", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 1, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # thanh khoản quá thấp
        {"symbol": "EEE", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 1e8, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
    ])


def test_compute_composite_weighted_sum():
    out = scoring.compute_composite(_rows(), _profile())
    aaa = out[out.symbol == "AAA"].iloc[0]
    expected = (80 * 0.25 + 70 * 0.30 + 90 * 0.30 + 60 * 0.05 + 50 * 0.10)
    assert aaa["composite_score"] == pytest.approx(expected, abs=0.01)


def test_compute_composite_null_component_is_not_zero():
    """Thành phần NULL mà profile có trọng số > 0 → không chấm, KHÔNG tính là 0."""
    out = scoring.compute_composite(_rows(), _profile())
    bbb = out[out.symbol == "BBB"].iloc[0]
    assert pd.isna(bbb["composite_score"])
    assert "quality" in bbb["components_missing"]


def test_apply_universe_filters_exchange_liquidity_and_require():
    ok, rejected = scoring.apply_universe(_rows(), _profile())
    assert set(ok["symbol"]) == {"AAA", "BBB"}
    reasons = dict(zip(rejected["symbol"], rejected["reject_reason"]))
    assert "sàn" in reasons["CCC"]
    assert "cổ tức" in reasons["DDD"]
    assert "thanh khoản" in reasons["EEE"]


def test_zero_weight_component_may_be_null():
    """Nếu profile gán trọng số 0 cho một thành phần, thành phần đó NULL vẫn OK."""
    prof = _profile()
    prof["weights"] = {"value": 0.5, "quality": 0.0, "dividend": 0.5,
                       "growth": 0.0, "safety": 0.0}
    out = scoring.compute_composite(_rows(), prof)
    bbb = out[out.symbol == "BBB"].iloc[0]
    assert bbb["composite_score"] == pytest.approx(80 * 0.5 + 90 * 0.5, abs=0.01)


def test_load_profiles_reads_three_profiles():
    profiles = scoring.load_profiles()
    assert {"bluechip_dividend", "deep_value", "quality_growth"} <= set(profiles["profiles"])
    for name, p in profiles["profiles"].items():
        total = sum(p["weights"].values())
        assert total == pytest.approx(1.0, abs=1e-6), f"{name} tổng trọng số != 1"


def test_load_profiles_merges_universe_defaults():
    profiles = scoring.load_profiles()
    p = profiles["profiles"]["bluechip_dividend"]
    assert p["universe"]["exchanges"] == ["HOSE", "HNX"]      # từ universe_defaults
    assert p["universe"]["min_market_cap_vnd"] == 5_000_000_000_000
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.scoring'`

- [ ] **Step 3: Tạo `config/scoring_profiles.yml`**

```yaml
# Hồ sơ chấm điểm — ĐÂY LÀ CHỖ BẠN DÒ RA "GU" ĐẦU TƯ CỦA MÌNH.
#
# Điểm thành phần (0-100) do dbt tính sẵn trong mart_stock_scorecard.
# File này chỉ quyết định TRỌNG SỐ và ĐIỀU KIỆN LỌC, được áp lúc đọc —
# nên sửa xong chạy lại screener trong vài giây, không cần chạy lại dbt.
#
# Cách dùng: chạy cả 3 profile, so sánh danh sách kết quả, xem cái nào
# khớp trực giác của bạn nhất, rồi tinh chỉnh trọng số của cái đó.

default_profile: bluechip_dividend

# Áp cho mọi profile, có thể ghi đè trong từng profile.
universe_defaults:
  exchanges: [HOSE, HNX]
  min_quarters_history: 12
  min_data_quality_score: 60

profiles:

  bluechip_dividend:
    label: "Bluechip cổ tức — tích sản dài hạn"
    universe:
      min_market_cap_vnd: 5_000_000_000_000        # 5.000 tỷ
      min_avg_turnover_20d_vnd: 5_000_000_000      # 5 tỷ/phiên
    weights:
      value: 0.25
      quality: 0.30
      dividend: 0.30
      growth: 0.05
      safety: 0.10
    require:
      dividend_years_min: 3
      roe_avg_8q_min: 0.12

  deep_value:
    label: "Định giá sâu — mở rộng xuống mid-cap"
    universe:
      min_market_cap_vnd: 500_000_000_000          # 500 tỷ
      min_avg_turnover_20d_vnd: 1_000_000_000      # 1 tỷ/phiên
    weights:
      value: 0.45
      quality: 0.25
      dividend: 0.10
      growth: 0.05
      safety: 0.15
    require:
      exclude_loss_making: true

  quality_growth:
    label: "Chất lượng & tăng trưởng"
    universe:
      min_market_cap_vnd: 2_000_000_000_000        # 2.000 tỷ
      min_avg_turnover_20d_vnd: 3_000_000_000      # 3 tỷ/phiên
    weights:
      value: 0.15
      quality: 0.35
      dividend: 0.05
      growth: 0.35
      safety: 0.10
    require:
      roe_avg_8q_min: 0.15
```

- [ ] **Step 4: Viết `src/scoring.py`**

```python
"""Áp hồ sơ chấm điểm (profile) lên mart_stock_scorecard.

Đây là bản cài đặt DUY NHẤT của logic điểm tổng hợp — cả MCP server lẫn job
báo cáo định kỳ đều import module này, nên hai luồng không bao giờ lệch nhau.

Vì sao điểm tổng hợp không nằm trong dbt: đổi trọng số là việc sẽ làm rất
nhiều lần khi dò gu đầu tư. Tính lúc đọc thì mất vài giây, còn tính trong
dbt thì phải chạy lại toàn bộ mart.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = ROOT / "config" / "scoring_profiles.yml"

COMPONENTS = ["value", "quality", "growth", "dividend", "safety"]


def load_profiles(path=None) -> dict:
    """Đọc scoring_profiles.yml, hợp nhất universe_defaults vào từng profile."""
    path = Path(path) if path else DEFAULT_PROFILE_PATH
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = cfg.get("universe_defaults", {}) or {}
    for prof in cfg.get("profiles", {}).values():
        merged = dict(defaults)
        merged.update(prof.get("universe", {}) or {})
        prof["universe"] = merged
        prof.setdefault("require", {})
    return cfg


def get_profile(profile_name: str = None, path=None) -> dict:
    cfg = load_profiles(path)
    name = profile_name or cfg.get("default_profile")
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Không có profile '{name}'. Có: {sorted(profiles)}")
    prof = dict(profiles[name])
    prof["name"] = name
    return prof


def compute_composite(df: pd.DataFrame, profile: dict) -> pd.DataFrame:
    """Thêm cột composite_score và components_missing.

    Thành phần NULL mà profile gán trọng số > 0 → composite_score = NaN và
    mã bị liệt kê là "không chấm được". KHÔNG coi NULL là 0 điểm: 0 nghĩa là
    "kém nhất nhóm", NULL nghĩa là "không đo được" — trộn hai thứ này là sai.
    """
    out = df.copy()
    weights = profile["weights"]
    required = [c for c in COMPONENTS if weights.get(c, 0) > 0]

    missing = out[[f"{c}_score" for c in required]].isna()
    out["components_missing"] = [
        ",".join(c for c, m in zip(required, row) if m)
        for row in missing.itertuples(index=False)
    ]

    total = pd.Series(0.0, index=out.index)
    for comp in COMPONENTS:
        w = weights.get(comp, 0)
        if w:
            total = total + out[f"{comp}_score"].astype(float) * w
    out["composite_score"] = total.where(out["components_missing"] == "")
    return out


def apply_universe(df: pd.DataFrame, profile: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tách thành (đủ điều kiện, bị loại kèm lý do)."""
    uni = profile["universe"]
    req = profile.get("require", {}) or {}
    out = df.copy()
    reasons = pd.Series("", index=out.index)

    def add(mask, text):
        nonlocal reasons
        reasons = reasons.where(~(mask & (reasons == "")), text)

    if uni.get("exchanges"):
        add(~out["exchange"].isin(uni["exchanges"]), "ngoài sàn cho phép")
    if uni.get("min_market_cap_vnd") is not None:
        add(out["market_cap"].fillna(0) < uni["min_market_cap_vnd"],
            "vốn hoá dưới ngưỡng")
    if uni.get("min_avg_turnover_20d_vnd") is not None:
        add(out["avg_turnover_20d"].fillna(0) < uni["min_avg_turnover_20d_vnd"],
            "thanh khoản dưới ngưỡng")
    if uni.get("min_data_quality_score") is not None:
        add(out["data_quality_score"].fillna(0) < uni["min_data_quality_score"],
            "chất lượng dữ liệu thấp")
    if req.get("dividend_years_min") is not None:
        add(out["dividend_years_consecutive"].fillna(0) < req["dividend_years_min"],
            "cổ tức chưa đủ số năm liên tiếp")
    if req.get("roe_avg_8q_min") is not None:
        add(out["roe_avg_8q"].fillna(-1) < req["roe_avg_8q_min"],
            "ROE trung bình 8 quý dưới ngưỡng")
    if req.get("exclude_loss_making"):
        add(out["is_loss_making"].fillna(False).astype(bool), "đang lỗ")

    ok = out[reasons == ""].reset_index(drop=True)
    rejected = out[reasons != ""].copy()
    rejected["reject_reason"] = reasons[reasons != ""].values
    return ok, rejected.reset_index(drop=True)


SCORECARD_SQL = "SELECT * FROM mart_stock_scorecard"


def screen(con, profile_name: str = None, limit: int = 30,
           profile_path=None) -> pd.DataFrame:
    """Chạy screener: đọc mart → lọc universe → tính điểm tổng hợp → xếp hạng."""
    profile = get_profile(profile_name, profile_path)
    df = con.execute(SCORECARD_SQL).df()
    ok, _ = apply_universe(df, profile)
    scored = compute_composite(ok, profile)
    ranked = scored.dropna(subset=["composite_score"]).sort_values(
        "composite_score", ascending=False
    )
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    ranked["profile"] = profile["name"]
    return ranked.head(limit).reset_index(drop=True)


def screen_report(con, profile_name: str = None, limit: int = 30,
                  profile_path=None) -> dict:
    """Như screen() nhưng trả thêm phần bị loại — để giải thích, không giấu."""
    profile = get_profile(profile_name, profile_path)
    df = con.execute(SCORECARD_SQL).df()
    ok, rejected = apply_universe(df, profile)
    scored = compute_composite(ok, profile)
    unscored = scored[scored["composite_score"].isna()]
    ranked = scored.dropna(subset=["composite_score"]).sort_values(
        "composite_score", ascending=False
    ).head(limit).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return {
        "profile": profile["name"],
        "label": profile.get("label", ""),
        "ranked": ranked,
        "unscored": unscored[["symbol", "components_missing"]].reset_index(drop=True),
        "rejected_counts": rejected["reject_reason"].value_counts().to_dict(),
        "universe_size": len(ok),
    }
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -q`
Expected: PASS — 7 passed

- [ ] **Step 6: Chạy screener thật với cả 3 profile**

```bash
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -c "
from src import warehouse, scoring
con = warehouse.get_conn()
for name in ['bluechip_dividend','deep_value','quality_growth']:
    r = scoring.screen_report(con, name, limit=15)
    print('='*70)
    print(r['profile'], '—', r['label'], '| universe:', r['universe_size'])
    print(r['ranked'][['rank','symbol','com_class','industry_lv2','composite_score',
                       'value_score','quality_score','dividend_score',
                       'valuation_band','peer_basis']].to_string(index=False))
    print('bị loại:', r['rejected_counts'])
con.close()
"
```

Expected:
- Ba profile cho ra **ba danh sách khác nhau** (nếu giống hệt nhau → trọng số chưa có tác dụng, kiểm tra `compute_composite`).
- **`bluechip_dividend` phải có ít nhất 3 ngân hàng trong top 30** — đây là tiêu chí nghiệm thu #8 của spec, phép thử trực tiếp cho lỗi sentinel.

Kiểm tra riêng tiêu chí đó:

```bash
.venv/bin/python -c "
from src import warehouse, scoring
con = warehouse.get_conn()
r = scoring.screen(con, 'bluechip_dividend', limit=30)
banks = r[r.com_class=='BANK']
print(f'Ngân hàng trong top 30: {len(banks)}')
print(banks[['rank','symbol','composite_score','quality_score','dividend_score']].to_string(index=False))
assert len(banks) >= 3, 'KHÔNG ĐẠT tiêu chí nghiệm thu #8'
print('ĐẠT')
con.close()
"
```

> **§7.4 ĐÃ ĐƯỢC ĐO VÀ QUYẾT ở Task 5 — bước dưới chỉ để xác nhận lại.**
> Kết quả trên production 2026-08-13, ở kỳ gần nhất của cả 29 ngân hàng:
> `car` **0/29** · `casa_ratio` 29/29 · NIM/NPL/CIR/LDR đều 29/29.
> Toàn lịch sử: `car` chỉ có ở **quý 2 (50,7%)** và **dòng năm (87,4%)**;
> quý 1/3/4 đều bằng 0 — VCI chỉ công bố hệ số an toàn vốn ở báo cáo bán niên
> và thường niên, nên nó không bao giờ có mặt ở kỳ TTM gần nhất.
>
> **Quyết định (đúng quy tắc §7.4 ">50% NULL thì loại"):** bỏ `car` khỏi công
> thức `quality` của BANK, chuyển 0,05 sang `npl` (0,15 → 0,20). Chọn `npl` vì
> nợ xấu là chỉ báo chất lượng quan trọng nhất của ngân hàng, và `car` vốn đo
> cùng một thứ ở góc khác — đệm vốn để hấp thụ tổn thất.
> `scoring_weights.csv` ở Step 1 đã phản ánh quyết định này.

- [ ] **Step 7: Xác nhận lại tỉ lệ NULL của `car` và `casa_ratio` (§7.4 của spec)**

```bash
.venv/bin/python -c "
from src import warehouse
con = warehouse.get_conn()
print(con.execute('''
select count(*) tong,
  count(*) filter (where car is null) car_null,
  count(*) filter (where casa_ratio is null) casa_null
from stg_financial_ratio f
join (select symbol, max(period_end_date) pe from stg_financial_ratio
      where quarter between 1 and 4 group by 1) m
  on m.symbol=f.symbol and m.pe=f.period_end_date
where f.com_class='BANK'
''').df().to_string())
con.close()
"
```

**Nếu `car_null` hoặc `casa_null` > 50% tổng số ngân hàng:** xoá dòng tương ứng khỏi `transforms/seeds/scoring_weights.csv`, chạy lại `dbt seed` và `dbt build --select mart_stock_scorecard`. Quy tắc chuẩn hoá lại trọng số sẽ tự phân bổ lại phần trọng số đó cho các chỉ tiêu còn lại.

- [ ] **Step 8: Chạy toàn bộ test và commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 79 passed

```bash
git add config/scoring_profiles.yml src/scoring.py tests/test_scoring.py
git commit -m "feat(scoring): profile cấu hình được + screener đọc mart

Điểm tổng hợp tính lúc đọc, không trong dbt -> đổi trọng số chạy lại
trong vài giây. NULL thành phần không bị coi là 0 điểm.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Tích hợp dbt vào GitHub Actions

**Files:**
- Modify: `.github/workflows/warehouse.yml`, `warehouse-weekly.yml`, `warehouse-monthly.yml`

**Interfaces:**
- Consumes: dbt project `transforms/` (Task 1–10).
- Produces: không có interface code.

- [ ] **Step 1: Thêm bước dbt vào workflow daily**

Trong `.github/workflows/warehouse.yml`, sau bước `Build warehouse`, thêm:

```yaml
      - name: dbt deps
        working-directory: transforms
        run: dbt deps --profiles-dir .

      - name: dbt build (lineage giá)
        working-directory: transforms
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
        run: dbt build --profiles-dir . --select tag:daily
```

- [ ] **Step 2: Thêm bước dbt vào workflow weekly và monthly**

Trong cả `.github/workflows/warehouse-weekly.yml` và `warehouse-monthly.yml`, sau bước ingest, thêm:

```yaml
      - name: dbt deps
        working-directory: transforms
        run: dbt deps --profiles-dir .

      - name: dbt seed
        working-directory: transforms
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
        run: dbt seed --profiles-dir .

      - name: dbt build (toàn bộ)
        working-directory: transforms
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
        run: dbt build --profiles-dir .

      - name: dbt source freshness
        working-directory: transforms
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
        run: dbt source freshness --profiles-dir .
```

- [ ] **Step 3: Chạy thử workflow bằng tay**

Vào tab Actions, chạy `warehouse-weekly` qua **Run workflow**.
Expected: job xanh; log `dbt build` báo mọi model và test PASS.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/
git commit -m "ci: chạy dbt build + test sau mỗi lần ingest

Test fail -> workflow đỏ, chặn dữ liệu hỏng trước khi agent dùng.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành plan A2

| # | Tiêu chí | Cách kiểm tra |
|---|---|---|
| 1 | 79 test pytest pass | `.venv/bin/python -m pytest tests/ -q` |
| 2 | `dbt build` sạch: mọi model và test pass | `cd transforms && dbt build --profiles-dir .` |
| 3 | `assert_no_bank_sentinel_leak` pass | nằm trong #2 |
| 4 | `mart_stock_scorecard` có ≥ 800 mã với ≥ 3/5 điểm thành phần | `assert_scorecard_coverage` |
| 5 | ≥ 20 ngân hàng có `quality_score` > 0 | `assert_bank_scored_on_quality` |
| 6 | 3 profile cho ra 3 danh sách khác nhau | Task 11 Step 6 |
| 7 | **`bluechip_dividend` có ≥ 3 ngân hàng trong top 30** | Task 11 Step 6 |
| 8 | Doanh thu/LNST suy ra của HPG 2024 khớp BCTC (±2%) | Task 4 Step 6 |
| 9 | Đã đo tỉ lệ NULL của `car`/`casa_ratio` và xử lý theo §7.4 | Task 11 Step 7 |
| 10 | Workflow weekly xanh trên GitHub | Task 12 Step 3 |

Tiêu chí #7 là phép thử quyết định — nếu không đạt, lỗi sentinel chưa được sửa triệt để.

Sau khi đạt hết: chuyển sang plan **A3 — MCP server**.

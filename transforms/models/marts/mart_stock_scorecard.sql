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

-- Tổng trọng số ĐỊNH NGHĨA cho mỗi (com_class, component), lấy từ seed.
-- Đây là mẫu số đúng của cổng chặn bên dưới. Không được suy nó từ số dòng
-- thực có, vì một chỉ tiêu vắng mặt hoàn toàn thì KHÔNG sinh dòng nào và tự
-- biến mất khỏi cả tử số lẫn mẫu số.
component_weight_total as (
    select com_class, component, sum(weight) as weight_defined
    from {{ ref('scoring_weights') }}
    group by 1, 2
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
        sum(weight) filter (where adj is not null) as weight_used
    from weighted
    group by 1, 2, 3
),

-- CỔNG CHẶN: phải đo bằng TRỌNG SỐ, không bằng số chỉ tiêu có mặt.
--
-- Công thức cũ `metrics_used * 2 >= metrics_total` với `metrics_total = count(*)`
-- là van luôn mở, vì `count(*)` chỉ đếm những dòng có mặt trong `weighted`.
-- Đã đo trên production: **617 cặp (mã, thành phần) lọt lưới** — tăng trưởng
-- 442 · định giá 96 · cổ tức 33 · chất lượng 30 · an toàn 16.
--
-- Ca tệ nhất (QLD, SDY, HFX, VHH, VMT, PLA, VGL, LMC...): chỉ có duy nhất
-- `growth_consistency` (trọng số 0,10) trong khi 90% trọng số của thành phần
-- tăng trưởng không đo được. Cổng cũ thấy "1 trong 1 chỉ tiêu có mặt = 100%"
-- và cho qua. Vì điểm được chuẩn hoá lại trên phần trọng số dùng được, một mã
-- KHÔNG có dữ liệu doanh thu lẫn lợi nhuận sẽ nhận `growth_score = 100/100`.
-- Tự tin tối đa từ bằng chứng tối thiểu.
--
-- Siết cổng gần như không mất độ phủ: 1.552 mã vẫn đạt ≥3 trong 5 thành phần
-- (so với 1.573 ở cổng cũ), mà loại được 617 điểm bịa.
gated as (
    select
        g.symbol, g.com_class, g.component, g.metrics_used,
        round(g.weight_used / wt.weight_defined, 3) as weight_coverage,
        -- Ngưỡng 0,5 = phải đo được ít nhất một nửa TRỌNG SỐ của thành phần.
        -- Đây là con số duy nhất cần đổi nếu muốn siết/nới chính sách này.
        case when g.weight_used >= 0.5 * wt.weight_defined
             then g.raw_score end as score
    from component_scores g
    join component_weight_total wt
      on wt.com_class = g.com_class and wt.component = g.component
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
        max(metrics_used) filter (where component = 'safety')   as safety_metrics_used,
        -- `metrics_used` một mình vẫn gây ngộ nhận, đúng như `n_symbols` ở
        -- Task 8: "dùng 1 chỉ tiêu" không cho biết chỉ tiêu đó nặng 10% hay
        -- 50%. Phơi luôn phần trọng số đã đo được để mỗi điểm tự mang theo cơ
        -- sở bằng chứng của nó.
        max(weight_coverage) filter (where component = 'value')    as value_weight_coverage,
        max(weight_coverage) filter (where component = 'quality')  as quality_weight_coverage,
        max(weight_coverage) filter (where component = 'growth')   as growth_weight_coverage,
        max(weight_coverage) filter (where component = 'dividend') as dividend_weight_coverage,
        max(weight_coverage) filter (where component = 'safety')   as safety_weight_coverage
    from gated
    group by symbol
),

-- Nhóm tương đương chiếm đa số trong các chỉ tiêu của mã, để agent nêu rõ
-- điểm đang so với bao nhiêu mã.
peer_info as (
    select symbol,
           mode(peer_basis) as peer_basis,
           -- mode() chứ KHÔNG max(): các chỉ tiêu khác nhau có thể rơi vào rổ
           -- so sánh khác nhau (một số phải lùi về rổ chỉ theo com_class).
           -- max() sẽ báo con số lớn nhất trong mọi rổ, tức phóng đại số mã
           -- mà điểm thật sự được so với.
           mode(peer_count)  as peer_count
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
                     -- dividend_years_consecutive là BIGINT; printf('%.0f', ...)
                     -- đòi kiểu thực nên lỗi "Invalid type specifier f for
                     -- formatting a value of type int". cast sang varchar vừa
                     -- đúng kiểu vừa gọn hơn cho một số đếm.
                     || cast(dv.dividend_years_consecutive as varchar)
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
    p.value_weight_coverage,
    p.quality_weight_coverage,
    p.growth_weight_coverage,
    p.dividend_weight_coverage,
    p.safety_weight_coverage,
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

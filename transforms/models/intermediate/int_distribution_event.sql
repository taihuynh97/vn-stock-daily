{{ config(materialized='table') }}

-- CHỈ sự kiện phân phối cho cổ đông (is_distribution = true).
--
-- ESOP và PRIVATE_PLACEMENT bị loại ở đây nhưng VẪN nằm trong
-- stg_corporate_event — mảng C sẽ cần chúng để cảnh báo ("sắp phát hành
-- riêng lẻ" là tin đáng quan tâm, chỉ là không phải cổ tức).
--
-- Trục thời gian của model này là NGÀY GDKHQ (exright_date), KHÁC trục năm
-- tài chính của dividend_yield trong stg_financial_ratio: cổ tức "cả năm
-- 2021" của HPG chi trả ngày 17/06/2022. Không được cộng gộp hai trục.
select
    symbol,
    id as event_id,
    exright_date,
    record_date,
    payout_date,
    distribution_type,
    -- cash_per_share chỉ có nghĩa với cổ tức TIỀN MẶT. Cổ tức bằng cổ phiếu
    -- và cổ phiếu thưởng luôn NULL value_per_share ở nguồn (xác minh HPG:
    -- cả 4 sự kiện ISS đều value_per_share = NaN), nên gán NULL tường minh
    -- thay vì để lọt giá trị vô nghĩa.
    case when distribution_type = 'CASH_DIVIDEND'
         then value_per_share end as cash_per_share,
    -- stock_ratio chỉ có nghĩa với hai loại trả bằng cổ phiếu.
    case when distribution_type in ('STOCK_DIVIDEND', 'BONUS_SHARE')
         then exercise_ratio end as stock_ratio,
    event_title_vi
from {{ ref('stg_corporate_event') }}
where is_distribution
  and exright_date is not null

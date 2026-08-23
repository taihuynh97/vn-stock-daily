{{ config(materialized='view') }}

select
    currency_code,
    currency_name,
    buy_cash,
    buy_transfer,
    sell,
    rate_date
from {{ source('warehouse', 'raw_exchange_rate') }}

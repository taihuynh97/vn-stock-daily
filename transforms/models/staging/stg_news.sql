{{ config(materialized='view') }}

select
    id,
    symbol,
    news_title,
    news_short_content,
    news_source_link,
    public_date
from {{ source('warehouse', 'raw_news') }}

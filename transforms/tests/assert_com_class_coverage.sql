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

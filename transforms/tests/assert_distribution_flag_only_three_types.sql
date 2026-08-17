-- Global Constraint B1: is_distribution chỉ true cho đúng 3 loại. ESOP và
-- phát hành riêng lẻ (9 + 5 dòng trong mẫu khảo sát 12 mã) PHA LOÃNG cổ
-- đông hiện hữu — đếm chúng là phân phối thì sai ngược dấu. Test này canh
-- đúng chiều đó: bất kỳ dòng nào có cờ true mà loại nằm ngoài 3 giá trị
-- cho phép đều là lỗi.
select id, symbol, distribution_type, is_distribution
from {{ ref('stg_corporate_event') }}
where is_distribution
  and distribution_type not in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE')

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
        -- period_type phân biệt quarter 4 (TTM) với quarter 5 (cả năm) — hai
        -- dòng này CÙNG ra period_end_date = 31/12 (xem comment dưới), khác
        -- nhau đáng kể về giá trị (VCB 2024: pe=14,8188 ở q4, pe=10,3303 ở
        -- q5). Mọi truy vấn dùng period_end_date ở tầng sau PHẢI lọc
        -- period_type trước, không được coi period_end_date là khoá một mình.
        period_type,
        -- Nguồn stringify None của Python thành chuỗi ký tự 'None' (KHÁC NULL
        -- SQL) ở một số dòng — nullif để guard `is not null` phía sau không
        -- bị lừa.
        nullif(ratio_type, 'None') as ratio_type,
        com_class,
        icb_code_lv2,
        icb_code_lv4,
        -- quarter 1-4 = TTM kết thúc tại quý đó; quarter 5 = cả năm. LƯU Ý:
        -- quarter 4 và quarter 5 của cùng một năm cho CÙNG giá trị ở đây
        -- (31/12) — dùng kèm period_type ở trên để phân biệt, xem test
        -- unique_combination_of_columns [symbol, period_end_date, period_type].
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
    * exclude (cir, average_cost_of_financing, car, debt_to_equity),
    -- Nguồn trả CIR và chi phí vốn theo quy ước dấu ÂM (VCB: cir = -0,4098).
    abs(cir) as cir,
    -- Fix round 1 (review C1): sentinel 0.0 còn sót theo trục KỲ BÁO CÁO,
    -- không chỉ com_class — cùng lỗi gốc của cả task, chỉ khác trục. Đo trên
    -- production: average_cost_of_financing=0 tập trung ở ngân hàng nhỏ/mới
    -- thiếu dữ liệu nguồn (EVF 39/40=97,5%; KLB 38/42=90,5%...) trong khi
    -- 16/29 ngân hàng lớn (VCB, BID, CTG, MBB...) không có dòng nào = 0 —
    -- chi phí huy động vốn bằng 0 chính xác là bất khả thi. Cột này chỉ tồn
    -- tại (khác NULL) ở BANK — applicable_metrics() đã lọc theo com_class —
    -- nên nullif ở đây an toàn toàn cục, không đụng nhóm khác (đã NULL sẵn).
    nullif(abs(average_cost_of_financing), 0) as average_cost_of_financing,
    -- car=0.0 (mất sạch vốn tự có) bất khả thi với ngân hàng đang hoạt động.
    -- Đo trên production: car=0 ở 100% dòng BANK quý 1/3/4 (223/224, 199/199,
    -- 204/204), quý 2 chỉ 49,3%, dòng năm 12,6% — rõ ràng sentinel theo kỳ,
    -- không phải giá trị thật lặp lại. Cột chỉ tồn tại ở BANK nên nullif an
    -- toàn toàn cục.
    nullif(car, 0) as car,
    -- debt_to_equity là chỉ tiêu COMMON — giữ cho MỌI nhóm — nên PHẢI khoanh
    -- theo com_class: 0 bất khả thi CHỈ với ngân hàng (không huy động đồng
    -- nào là không thể; đo production: 207/207 dòng NĂM của BANK = 0 chính
    -- xác, trong khi quý 1-4 là 0%). Với NONFIN, 0 là giá trị THẬT (DN không
    -- vay nợ) — TUYỆT ĐỐI không nullif toàn cục, chỉ khoanh vùng BANK.
    case
        when com_class = 'BANK' then nullif(debt_to_equity, 0)
        else debt_to_equity
    end as debt_to_equity,
    -- Fix round 1 (review I2): is_loss_making suy từ biên lợi nhuận thật,
    -- KHÔNG phải dấu P/E — đo được 216 dòng is_loss_making=false (theo pe cũ)
    -- nhưng after_tax_profit_margin<0, và 295 dòng ngược lại; sai cả hai
    -- chiều vì P/E âm cũng xảy ra do các nguyên nhân kế toán khác ngoài lỗ.
    (after_tax_profit_margin < 0) as is_loss_making,
    -- nullif(pe, 0): loại 771 dòng pe=0 (khả năng cũng là sentinel, không
    -- phải P/E thật) khỏi diện "có nghĩa" — NULL đúng ngữ nghĩa hơn (không rõ)
    -- so với false (chắc chắn không có nghĩa) mà công thức cũ vô tình tạo ra
    -- vì 0 không > 0.
    (nullif(pe, 0) > 0 and nullif(pe, 0) < 200) as pe_meaningful,
    (pb > 0 and pb < 30) as pb_meaningful
from cleaned

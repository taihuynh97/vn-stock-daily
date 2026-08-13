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
        ,
        -- Fix V7 (Task 8.5): "dòng trắng" — nguồn trả CẢ BẢN GHI toàn số 0.0
        -- vì không có dữ liệu gì cho kỳ đó, khác với sentinel COMMON (roe...)
        -- xử lý ở SELECT ngoài cùng, nơi chỉ MỘT/HAI cột bị ảnh hưởng. Đo trên
        -- production: 686 dòng NONFIN có roa=0 and roic=0 and current_ratio=0
        -- đồng thời — mọi chỉ tiêu khác trong dòng đó cũng là 0.
        -- Guard tường minh `com_class in ('NONFIN', 'OTHERFIN')` (không chỉ
        -- dựa vào roic/current_ratio đã bị applicable_metrics() NULL hoá ở
        -- BANK/UNKNOWN): roic và current_ratio ở biểu thức này có thể phân
        -- giải theo cột THÔ của `joined` (trùng tên với alias CASE cùng dòng
        -- phía trên, tuỳ cách DuckDB giải quyết va chạm tên) — kiểm thử trên
        -- production cho thấy hiện tại luôn ra false/null cho BANK vì raw
        -- roa=0 chưa từng xảy ra ở BANK (0/1.036), nhưng đó là trùng hợp của
        -- dữ liệu, không phải đảm bảo cấu trúc. Guard com_class chặn đứng rủi
        -- ro này bất kể cách phân giải cột, không phụ thuộc vào trùng hợp đó.
        (
            com_class in ('NONFIN', 'OTHERFIN')
            and roa = 0
            and roic = 0
            and current_ratio = 0
        ) as is_blank_row
    from joined
    where year is not null and quarter is not null
)

select
    * exclude (
        cir, average_cost_of_financing, car, debt_to_equity,
        -- Nhóm A (Task 8.5, V7): 7 chỉ tiêu COMMON mà 0 bất khả thi kinh tế —
        -- khai báo lại bằng nullif ngay dưới.
        roe, pe, pb, ps, ev_to_ebitda, price_to_cash_flow, market_cap,
        -- Nhóm C + 1 ngoại lệ Nhóm B (Task 8.5, V7): NULL hoá chỉ khi
        -- is_blank_row — khai báo lại bằng case ngay dưới. is_blank_row bản
        -- thân không thuộc output, loại nó khỏi kết quả cuối.
        is_blank_row,
        dividend_yield, number_of_shares_mkt_cap, roa, gross_margin,
        pre_tax_profit_margin, after_tax_profit_margin,
        roic, current_ratio, quick_ratio, cash_ratio, ebit_margin,
        asset_turnover, fixed_asset_turnover, ebit, ebitda
    ),
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
    -- Fix V7 (Task 8.5) — trục sentinel THỨ BA: các chỉ tiêu COMMON (áp dụng
    -- cho MỌI com_class) mà 0 bất khả thi về kinh tế, không cần khoanh vùng
    -- vì bất khả thi ở mọi loại hình. Bằng chứng nặng nhất là roe: 1.661
    -- dòng roe=0, toàn bộ ở NONFIN (0/1.035 ở BANK — đã đo, khớp kỳ vọng vì
    -- roic/current_ratio NULL ở BANK khiến is_blank_row không bao giờ khớp
    -- BANK). Phân rã 1.661: 686 dòng "trắng" (mọi chỉ tiêu = 0, xem
    -- is_blank_row) + 975 dòng còn lại, trong đó 929 (95,3%) có debt_per_equity
    -- < 0 (vốn chủ âm) hoặc pb = 0 — ví dụ APT/JOS/HLA: roa âm (đang lỗ) mà
    -- roe = 0 là vô nghĩa, xảy ra vì nguồn blank ROE khi vốn chủ âm (lỗ chia
    -- vốn âm ra số dương giả, nguồn chọn trả 0 thay vì số dương sai lệch đó).
    nullif(roe, 0)                as roe,
    -- pe = 0: giá đóng cửa bằng 0 (không thể với mã đang niêm yết) hoặc lợi
    -- nhuận vô hạn — cả hai đều vô nghĩa. Đo trên production: 771 dòng pe=0
    -- (767 NONFIN, 4 BANK) — số 771 này đã được pe_meaningful loại ra từ Fix
    -- round 1 (review I2) phía dưới, nay nullif ngay tại nguồn cho nhất quán.
    nullif(pe, 0)                 as pe,
    -- pb = 0: giá bằng 0 hoặc giá trị sổ sách vô hạn. Đo trên production:
    -- 1.797 dòng pb=0 (1.793 NONFIN, 4 BANK).
    nullif(pb, 0)                 as pb,
    -- ps = 0: giá bằng 0 hoặc doanh thu vô hạn. Đo trên production: 1.190
    -- dòng ps=0 (1.032 NONFIN, 154 OTHERFIN, 4 BANK).
    nullif(ps, 0)                 as ps,
    -- ev_to_ebitda = 0: giá trị doanh nghiệp (EV) bằng 0 — bất khả thi cho
    -- một công ty đang hoạt động. Đo trên production: 861 dòng = 0 (860
    -- NONFIN, 1 OTHERFIN).
    nullif(ev_to_ebitda, 0)       as ev_to_ebitda,
    -- price_to_cash_flow = 0: giá bằng 0. Đo trên production: 818 dòng = 0
    -- (809 NONFIN, 5 OTHERFIN, 4 BANK).
    nullif(price_to_cash_flow, 0) as price_to_cash_flow,
    -- market_cap = 0: công ty đã niêm yết không thể có vốn hoá thị trường
    -- bằng 0 (giá hoặc số lượng cổ phiếu lưu hành bằng 0 đều vô lý). Đo trên
    -- production: 62 dòng = 0 (59 NONFIN, 3 BANK) — nhỏ nhất trong Nhóm A vì
    -- hầu hết mã mất giao dịch vẫn giữ giá đóng cửa cuối cùng khác 0.
    nullif(market_cap, 0)         as market_cap,
    -- Nhóm C (Task 8.5, V7) — TUYỆT ĐỐI KHÔNG nullif toàn cục: những chỉ tiêu
    -- này có thể = 0 THẬT (DN hoà vốn, ROA=0 thật, tỉ suất chưa dùng nợ...).
    -- Chỉ NULL hoá bên trong 686 "dòng trắng" (is_blank_row) — dòng mà nguồn
    -- không trả gì cả, nên ngay cả số 0 trong dòng đó cũng không đáng tin.
    -- dividend_yield là NGOẠI LỆ DUY NHẤT của Nhóm B (xem comment Nhóm B ở
    -- macro applicable_metrics()/dbt_project.yml): 38.112 dòng dividend_yield
    -- = 0 là giá trị THẬT (đa số DN Việt không trả cổ tức trong quý) và PHẢI
    -- giữ nguyên ngoài phạm vi 686 dòng trắng này — nullif toàn cục ở đây là
    -- xoá dữ liệu thật, không phải khử sentinel.
    case when is_blank_row then null else dividend_yield end          as dividend_yield,
    case when is_blank_row then null else number_of_shares_mkt_cap end as number_of_shares_mkt_cap,
    case when is_blank_row then null else roa end                     as roa,
    case when is_blank_row then null else gross_margin end            as gross_margin,
    case when is_blank_row then null else pre_tax_profit_margin end   as pre_tax_profit_margin,
    case when is_blank_row then null else after_tax_profit_margin end as after_tax_profit_margin,
    case when is_blank_row then null else roic end                   as roic,
    case when is_blank_row then null else current_ratio end          as current_ratio,
    case when is_blank_row then null else quick_ratio end            as quick_ratio,
    case when is_blank_row then null else cash_ratio end             as cash_ratio,
    case when is_blank_row then null else ebit_margin end            as ebit_margin,
    case when is_blank_row then null else asset_turnover end         as asset_turnover,
    case when is_blank_row then null else fixed_asset_turnover end   as fixed_asset_turnover,
    case when is_blank_row then null else ebit end                   as ebit,
    case when is_blank_row then null else ebitda end                 as ebitda,
    -- Các chỉ tiêu chỉ áp dụng riêng BANK (net_interest_margin,
    -- average_yield_on_earning_assets, non_and_interest_income, loans_growth,
    -- deposit_growth, equity_to_liabilities, equity_to_loans,
    -- total_equity_total_asset, ldr_loan_deposit_ratio,
    -- loans_loss_reserve_to_loans, provision_to_outstanding_loans) KHÔNG được
    -- bọc case is_blank_row ở trên: is_blank_row chỉ có thể đúng khi
    -- com_class in ('NONFIN', 'OTHERFIN') (xem guard trong CTE `cleaned`), và
    -- applicable_metrics() đã NULL hoá toàn bộ nhóm này cho NONFIN/OTHERFIN —
    -- bọc thêm case is_blank_row cho chúng là NULL else NULL, vô nghĩa. npl
    -- và casa_ratio (Nhóm B, BANK) cũng không bọc — cùng lý do cấu trúc.
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

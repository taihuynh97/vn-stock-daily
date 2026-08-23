"""Dựng một warehouse tí hon có cấu trúc giống mart thật, để test tool
không phụ thuộc MotherDuck."""
import duckdb


def build_fake_mart(path: str):
    con = duckdb.connect(path)
    con.execute("""
        CREATE TABLE mart_stock_scorecard (
            symbol VARCHAR, company_name VARCHAR, exchange VARCHAR,
            com_class VARCHAR, icb_code_lv2 VARCHAR, industry_lv2 VARCHAR,
            peer_basis VARCHAR, peer_count BIGINT,
            value_score DOUBLE, quality_score DOUBLE, growth_score DOUBLE,
            dividend_score DOUBLE, safety_score DOUBLE,
            value_metrics_used BIGINT, quality_metrics_used BIGINT,
            growth_metrics_used BIGINT, dividend_metrics_used BIGINT,
            safety_metrics_used BIGINT,
            market_cap DOUBLE, avg_turnover_20d DOUBLE, last_close DOUBLE,
            price_as_of DATE, pe DOUBLE, pb DOUBLE,
            pe_pct_own_5y DOUBLE, pb_pct_own_5y DOUBLE,
            valuation_band VARCHAR, ratio_as_of DATE,
            is_loss_making BOOLEAN, data_quality_score DOUBLE,
            -- quarters_available (KHÔNG có trong bản brief gốc — thêm ở đây):
            -- config/scoring_profiles.yml có universe_defaults.min_quarters_history
            -- = 12, áp cho MỌI profile qua load_profiles(); apply_universe() đọc
            -- thẳng cột này từ mart_stock_scorecard khi ngưỡng đó có mặt. Thiếu
            -- cột này làm search_stocks() KeyError ngay ở profile mặc định
            -- bluechip_dividend — đã tự xác minh thực nghiệm trước khi viết fixture
            -- này. Đúng thứ tự cột thật trong transforms/models/marts/
            -- mart_stock_scorecard.sql (dq.quarters_available nằm ngay sau
            -- data_quality_score, trước quality_flags).
            quarters_available BIGINT,
            quality_flags VARCHAR, dividend_years_consecutive DOUBLE,
            roe_avg_8q DOUBLE, roe_stability DOUBLE, facts VARCHAR
        );
        INSERT INTO mart_stock_scorecard VALUES
        ('AAA','Cty A','HOSE','NONFIN','1700','Tài nguyên cơ bản',
         'com_class+icb_lv2', 40, 80,70,60,90,50, 5,6,5,4,7,
         5e12, 5e9, 20000, DATE '2026-08-07', 9.5, 1.2, 0.18, 0.22,
         'rất rẻ', DATE '2026-06-30', FALSE, 90, 20, '', 5, 0.18, 0.85,
         '[{"metric":"pe_pct_own_5y","value":0.18,"text":"P/E 9,5 - thấp hơn 82% số quý"}]'),
        ('VCB','Cty B','HOSE','BANK','8300','Ngân hàng',
         'com_class', 27, 60,85,55,70,80, 4,8,5,4,7,
         5e14, 2e11, 59000, DATE '2026-08-07', 15.2, 2.6, 0.45, 0.40,
         'hợp lý', DATE '2026-06-30', FALSE, 95, 20, '', 4, 0.19, 0.90,
         '[{"metric":"roe_avg_8q","value":0.19,"text":"ROE trung bình 8 quý 19,0%"}]'),
        ('CCC','Cty C','UPCOM','NONFIN','1700','Tài nguyên cơ bản',
         'com_class', 300, 95,40,30,20,25, 5,6,5,4,7,
         6e11, 2e8, 8000, DATE '2026-08-07', 4.0, 0.5, 0.05, 0.08,
         'rất rẻ', DATE '2026-06-30', TRUE, 45, 6, 'thiếu lịch sử tỷ số (<12 quý)',
         0, -0.05, 0.0, '[]'),
        -- DDD (fix round 1, code review): mã mới niêm yết, ratio_as_of NULL
        -- THẬT — kịch bản có thật trên production, mart_stock_scorecard lấy
        -- ratio_as_of qua LEFT JOIN mart_valuation_band nên mã chưa có kỳ
        -- định giá nào sẽ ra NULL, không phải một ngày cụ thể. Khoá lại hành
        -- vi _date_str(): NULL phải ra None, không phải chuỗi "NaT". Đặt
        -- UPCOM (giống CCC) để bị loại khỏi universe bluechip_dividend, không
        -- lọt vào 'results'/ảnh hưởng thứ hạng của các test search_stocks đã
        -- có. Cố tình KHÔNG thêm dòng khớp trong dim_stock — LEFT JOIN ở
        -- get_stock_profile() sẽ tự cho listed_date NULL, khoá thêm luôn ca
        -- đó mà không cần bảng riêng.
        ('DDD','Cty D','UPCOM','NONFIN','1700','Tài nguyên cơ bản',
         'com_class', 10, 50,50,50,50,50, 5,6,5,4,7,
         1e11, 1e8, 10000, DATE '2026-08-07', NULL, NULL, NULL, NULL,
         NULL, NULL, FALSE, 50, 5, 'chưa đủ lịch sử định giá',
         0, NULL, NULL, '[]');
    """)
    con.execute("""
        CREATE TABLE fct_price_daily (symbol VARCHAR, trade_date DATE, close DOUBLE);
        INSERT INTO fct_price_daily VALUES ('AAA', DATE '2026-08-07', 20000);
        CREATE TABLE fct_financial_quarterly (
            symbol VARCHAR, year INTEGER, quarter INTEGER, period_end_date DATE,
            period_type VARCHAR, com_class VARCHAR, pe DOUBLE, pb DOUBLE, roe DOUBLE,
            revenue_ttm DOUBLE, earnings_ttm DOUBLE, revenue_yoy DOUBLE,
            earnings_yoy DOUBLE
        );
        INSERT INTO fct_financial_quarterly VALUES
          ('AAA',2026,2,DATE '2026-06-30','quarter','NONFIN',9.5,1.2,0.18,1e13,1e12,0.12,0.20),
          ('AAA',2026,1,DATE '2026-03-31','quarter','NONFIN',10.1,1.3,0.17,9.5e12,9e11,0.10,0.15),
          -- C1: dòng NĂM (quarter=5, period_type='year') — CÙNG period_end_date
          -- 31/12 như quarter=4 của năm trước đó nếu có, nhưng ở đây dùng
          -- năm riêng (2025) để không trùng period_end_date với 2 dòng quý
          -- trên. Mục đích: test _financial_trend PHẢI lọc period_type='quarter',
          -- nếu lọt dòng này vào kết quả thì test thất bại rõ ràng.
          ('AAA',2025,5,DATE '2025-12-31','year','NONFIN',8.8,1.1,0.16,8e12,7e11,0.08,0.10);
        -- pe_quarters_used / pb_quarters_used (KHÔNG phải own_quarters_used —
        -- đã tách ra hai cột riêng ở A2 Task 6 fix round 2, vì cửa sổ hợp lệ
        -- của P/E và P/B không luôn bằng nhau cho cùng một mã/kỳ; dùng đúng
        -- tên cột thật để fixture không che giấu lỗi khi chạy trên production).
        CREATE TABLE mart_valuation_band (
            symbol VARCHAR, period_end_date DATE, com_class VARCHAR,
            icb_code_lv2 VARCHAR, industry_lv2 VARCHAR,
            pe DOUBLE, pb DOUBLE, ps DOUBLE,
            pe_pct_own_5y DOUBLE, pb_pct_own_5y DOUBLE,
            pe_quarters_used BIGINT, pb_quarters_used BIGINT, valuation_band VARCHAR
        );
        INSERT INTO mart_valuation_band VALUES
          ('AAA',DATE '2026-06-30','NONFIN','1700','Tài nguyên cơ bản',
           9.5,1.2,0.9,0.18,0.22,20,18,'rất rẻ'),
          ('AAA',DATE '2026-03-31','NONFIN','1700','Tài nguyên cơ bản',
           10.1,1.3,1.0,0.30,0.35,19,17,'rẻ');
        -- n_pe/n_pb/n_roe (I2, fix round cuối — fixture cũ THIẾU cả ba cột
        -- này, đúng lý do I2 lọt qua 4 task trước: get_sector_snapshot() bỏ
        -- sót SELECT ba cột có sẵn trong mart thật mà test không thể phát
        -- hiện vì fixture lệch schema production). Đúng thứ tự cột thật
        -- trong transforms/models/marts/mart_sector_snapshot.sql (n_pe/n_pb/
        -- n_roe nằm ngay sau n_symbols, trước median_pe). Cố tình đặt
        -- n_pe/n_pb/n_roe < n_symbols cho nhóm '1700' để mô phỏng đúng ca
        -- thật A2 đã đo (median không dựa trên toàn bộ n_symbols mã).
        CREATE TABLE mart_sector_snapshot (
            icb_code_lv2 VARCHAR, industry_lv2 VARCHAR, com_class VARCHAR,
            period_end_date DATE, n_symbols BIGINT, n_pe BIGINT, n_pb BIGINT,
            n_roe BIGINT, median_pe DOUBLE, median_pb DOUBLE,
            median_roe DOUBLE, sector_return_3m DOUBLE
        );
        INSERT INTO mart_sector_snapshot VALUES
          ('1700','Tài nguyên cơ bản','NONFIN',DATE '2026-06-30',40,32,35,38,12.5,1.4,0.13,0.08),
          ('8300','Ngân hàng','BANK',DATE '2026-06-30',27,27,25,27,8.6,1.3,0.18,0.11);
        -- max_missed_sessions (KHÔNG phải max_price_gap_days — đổi tên ở A2
        -- Task 9: đếm ngày lịch khiến nghỉ Tết 10 ngày suýt báo động giả cho
        -- 891 mã; đếm phiên thị trường bị bỏ thì miễn nhiễm với lịch nghỉ).
        CREATE TABLE mart_data_quality (
            symbol VARCHAR, quarters_available BIGINT, price_sessions_1y BIGINT,
            ratio_age_days BIGINT, max_missed_sessions BIGINT,
            has_required_metrics BOOLEAN, data_quality_ratio DOUBLE,
            data_quality_score DOUBLE, quality_flags VARCHAR
        );
        INSERT INTO mart_data_quality VALUES
          ('AAA',20,245,40,3,TRUE,0.90,90,''),
          ('VCB',20,248,40,2,TRUE,0.95,95,''),
          ('CCC',6,120,400,45,FALSE,0.45,45,'thiếu lịch sử tỷ số (<12 quý)');
        CREATE TABLE dim_stock (
            symbol VARCHAR, company_name VARCHAR, exchange VARCHAR,
            com_class VARCHAR, industry_lv2 VARCHAR, market_cap DOUBLE,
            avg_turnover_20d DOUBLE, last_close DOUBLE, price_as_of DATE,
            free_float_percentage DOUBLE, foreigner_percentage DOUBLE,
            listed_date DATE, listing_age_years BIGINT,
            return_1m DOUBLE, return_3m DOUBLE, return_12m DOUBLE,
            high_52w DOUBLE, low_52w DOUBLE
        );
        INSERT INTO dim_stock VALUES
          ('AAA','Cty A','HOSE','NONFIN','Tài nguyên cơ bản',5e12,5e9,20000,
           DATE '2026-08-07',0.55,0.22,DATE '2007-11-15',18,0.03,0.08,0.15,29000,19500),
          ('VCB','Cty B','HOSE','BANK','Ngân hàng',5e14,2e11,59000,
           DATE '2026-08-07',0.25,0.23,DATE '2009-06-30',17,0.01,0.05,0.10,63100,50000),
          ('CCC','Cty C','UPCOM','NONFIN','Tài nguyên cơ bản',6e11,2e8,8000,
           DATE '2026-08-07',0.30,0.02,DATE '2022-01-10',4,-0.05,-0.12,-0.30,15000,7500);
    """)
    # --- B1: sự kiện phân phối + sở hữu ---
    # Fixture phải khớp schema thật (bài học A3 I2: fixture thiếu 3 cột
    # n_pe/n_pb/n_roe khiến lỗi lọt qua 4 task). Giá trị cố tình đặt
    # total_disclosed_pct < 1.0 để mô phỏng đúng ca thật (HPG 51,9%).
    con.execute("""
        CREATE TABLE int_distribution_event (
            symbol VARCHAR, event_id VARCHAR, exright_date DATE,
            record_date DATE, payout_date DATE, distribution_type VARCHAR,
            cash_per_share DOUBLE, stock_ratio DOUBLE, event_title_vi VARCHAR
        );
        INSERT INTO int_distribution_event VALUES
          ('AAA','e1',DATE '2026-05-11',DATE '2026-05-12',DATE '2026-06-30',
           'CASH_DIVIDEND',500.0,NULL,'Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND'),
          ('AAA','e2',DATE '2026-05-25',DATE '2026-05-26',NULL,
           'STOCK_DIVIDEND',NULL,0.10,'Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%'),
          ('AAA','e3',DATE '2022-06-17',DATE '2022-06-18',NULL,
           'BONUS_SHARE',NULL,0.30,'Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 30.0%');
        -- officer_snapshot_date (I1, fix round cuối): ngày snapshot RIÊNG
        -- của bảng officer — khác snapshot_date (ngày của cổ đông). AAA có
        -- cùng ngày cho cả hai (ca bình thường). BBB cố tình LỆCH ngày
        -- (snapshot cổ đông 2026-08-01, snapshot officer 2026-07-01) — đúng
        -- ca reviewer tái hiện: một mã lỗi fetch ở lần chạy monthly này cho
        -- MỘT TRONG HAI nguồn. VCB không có dòng nào trong stg_officer nên
        -- officer_snapshot_date NULL qua left join (ca đã có từ trước, giữ
        -- nguyên — không thuộc phạm vi sửa I1).
        CREATE TABLE int_ownership_snapshot (
            symbol VARCHAR, snapshot_date DATE, n_disclosed BIGINT,
            total_disclosed_pct DOUBLE, top1_pct DOUBLE, top5_pct DOUBLE,
            insider_pct DOUBLE, officer_snapshot_date DATE
        );
        INSERT INTO int_ownership_snapshot VALUES
          ('AAA',DATE '2026-08-01',66,0.5189,0.2580,0.3872,0.3105,DATE '2026-08-01'),
          ('VCB',DATE '2026-08-01',29,0.9101,0.7480,0.9096,0.0002,NULL),
          ('BBB',DATE '2026-08-01',10,0.4000,0.2000,0.3500,0.1500,DATE '2026-07-01');
        CREATE TABLE stg_shareholder (
            symbol VARCHAR, share_holder VARCHAR, quantity DOUBLE,
            share_own_percent DOUBLE, update_date DATE, snapshot_date DATE
        );
        INSERT INTO stg_shareholder VALUES
          ('AAA','Ông Nguyễn Văn A',1.6e9,0.2580,DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Bà Trần Thị B',4.2e8,0.0688,DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Quỹ ngoại C',1.7e8,0.0273,DATE '2026-07-15',DATE '2026-08-01'),
          ('BBB','Ông C',5.0e8,0.2000,DATE '2026-06-15',DATE '2026-08-01');
        CREATE TABLE stg_officer (
            symbol VARCHAR, officer_name VARCHAR, officer_position VARCHAR,
            officer_own_percent DOUBLE, officer_own_quantity DOUBLE,
            update_date DATE, snapshot_date DATE
        );
        INSERT INTO stg_officer VALUES
          ('AAA','Ông Nguyễn Văn A','Chủ tịch HĐQT',0.2580,1.6e9,
           DATE '2026-07-15',DATE '2026-08-01'),
          ('AAA','Bà Trần Thị B','Thành viên HĐQT',0.0525,3.2e8,
           DATE '2026-07-15',DATE '2026-08-01'),
          ('BBB','Ông D','Chủ tịch HĐQT',0.1500,3.75e8,
           DATE '2026-06-15',DATE '2026-07-01');
        -- C1: snapshot sở hữu THỨ HAI, sớm hơn (2026-05-01), cho AAA — để
        -- _ownership_change có 2 mốc THẬT để tính delta. Chỉ đổi tỉ lệ của
        -- Ông Nguyễn Văn A (0.2580 -> 0.2400) để tạo delta rõ ràng, dễ kiểm.
        INSERT INTO stg_shareholder VALUES
          ('AAA','Ông Nguyễn Văn A',1.5e9,0.2400,DATE '2026-04-15',DATE '2026-05-01'),
          ('AAA','Bà Trần Thị B',4.2e8,0.0688,DATE '2026-04-15',DATE '2026-05-01');
        INSERT INTO stg_officer VALUES
          ('AAA','Ông Nguyễn Văn A','Chủ tịch HĐQT',0.2400,1.5e9,
           DATE '2026-04-15',DATE '2026-05-01');
        -- GGG: CHỈ 1 snapshot duy nhất (baseline == latest) — ca "chưa đủ
        -- lịch sử để so sánh", delta phải ra 0 một cách hợp lệ, không lỗi.
        -- Đồng thời dùng GGG làm ca đối chiếu tiêu chí hoàn thành #2 (spec
        -- §7): int_ownership_snapshot.GGG bên dưới PHẢI là kết quả gộp
        -- ĐÚNG của các dòng stg_shareholder/stg_officer này (1 cổ đông +
        -- 1 officer, cùng người, 30%) — để test so sánh trực tiếp
        -- _ownership_change() với int_ownership_snapshot mà không đụng tới
        -- dòng AAA hiện có (dòng AAA trong int_ownership_snapshot được tạo
        -- cho mục đích khác từ B1, KHÔNG khớp số học với 3 dòng
        -- stg_shareholder của AAA — không dùng AAA để đối chiếu).
        INSERT INTO stg_shareholder VALUES
          ('GGG','Ông E',1.0e9,0.3000,DATE '2026-08-01',DATE '2026-08-01');
        INSERT INTO stg_officer VALUES
          ('GGG','Ông E','Chủ tịch HĐQT',0.3000,1.0e9,
           DATE '2026-08-01',DATE '2026-08-01');
        INSERT INTO int_ownership_snapshot VALUES
          ('GGG',DATE '2026-08-01',1,0.3000,0.3000,0.3000,0.3000,DATE '2026-08-01');
        -- C1 (Critical #1, final review): HHH — snapshot_date của CỔ ĐÔNG
        -- LỆCH với snapshot_date của OFFICER. Cổ đông có 2 mốc (2026-05-01,
        -- 2026-08-01) nhưng officer CHỈ có mốc 2026-05-01 — mô phỏng đúng ca
        -- fetch_officers lỗi ở lần chạy monthly SAU: fetch_shareholders và
        -- fetch_officers bọc `except Exception: continue` RIÊNG theo từng mã
        -- (src/ingest_market.py) nên một mã có thể lấy được cổ đông mà hỏng
        -- officer trong CÙNG một lần chạy. Đây đúng bài học I1 mà B1 đã sửa
        -- cho get_ownership; bản C1 đầu tiên lặp lại lỗi đó: dùng CHUNG ngày
        -- cổ đông để lọc stg_officer nên mốc 2026-08-01 không khớp dòng
        -- officer nào -> sum([]) = 0.0 -> báo insider_pct delta = -0.1200,
        -- tức "nội bộ đã bán sạch 12% cổ phần", HOÀN TOÀN GIẢ.
        INSERT INTO stg_shareholder VALUES
          ('HHH','Ông F',8.0e8,0.2000,DATE '2026-04-20',DATE '2026-05-01'),
          ('HHH','Ông F',8.4e8,0.2100,DATE '2026-07-20',DATE '2026-08-01');
        INSERT INTO stg_officer VALUES
          ('HHH','Ông F','Chủ tịch HĐQT',0.1200,4.8e8,
           DATE '2026-04-20',DATE '2026-05-01');
        -- C1 (Critical #1): KKK — có cổ đông nhưng KHÔNG có DÒNG OFFICER NÀO
        -- (chưa bao giờ fetch được). insider_pct phải là None ("không có dữ
        -- liệu"), KHÔNG PHẢI 0.0 ("nội bộ sở hữu 0%") — đúng cách model
        -- int_ownership_snapshot trả NULL qua left join (xem ca VCB ở trên).
        INSERT INTO stg_shareholder VALUES
          ('KKK','Ông G',5.0e8,0.1000,DATE '2026-04-20',DATE '2026-05-01'),
          ('KKK','Ông G',5.5e8,0.1100,DATE '2026-07-20',DATE '2026-08-01');
        CREATE TABLE stg_financial_ratio (
            symbol VARCHAR, year INTEGER, quarter INTEGER,
            dividend_yield DOUBLE
        );
        INSERT INTO stg_financial_ratio VALUES
          ('AAA',2025,5,0.0235),
          ('AAA',2024,5,0.0),
          ('AAA',2023,5,0.0),
          ('AAA',2022,5,0.0),
          ('AAA',2021,5,0.0278),
          -- EEE có dividend_yield thật (nên get_distribution_history KHÔNG
          -- rơi vào nhánh lỗi "không có dữ liệu") nhưng KHÔNG có dòng nào
          -- trong int_distribution_event — sự kiện duy nhất của nó bị lọc
          -- mất vì exright_date NULL (xem stg_corporate_event bên dưới).
          ('EEE',2024,5,0.05);
        -- stg_corporate_event (I4, fix round cuối): tầng TRƯỚC lọc
        -- exright_date is not null của int_distribution_event.sql. EEE có 1
        -- sự kiện phân phối THẬT (is_distribution=true, CASH_DIVIDEND) với
        -- exright_date NULL — đúng ca 323/9932 sự kiện production bị lọc
        -- mất âm thầm khỏi int_distribution_event mà get_distribution_history
        -- phải phơi ra qua data_quality.n_events_missing_exright_date.
        CREATE TABLE stg_corporate_event (
            symbol VARCHAR, id VARCHAR, event_code VARCHAR,
            event_title_vi VARCHAR, distribution_type VARCHAR,
            is_distribution BOOLEAN, exright_date DATE
        );
        INSERT INTO stg_corporate_event VALUES
          ('AAA','e1','DIV','Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND',
           'CASH_DIVIDEND',TRUE,DATE '2026-05-11'),
          ('AAA','e2','ISS','Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%',
           'STOCK_DIVIDEND',TRUE,DATE '2026-05-25'),
          ('AAA','e3','ISS','Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 30.0%',
           'BONUS_SHARE',TRUE,DATE '2022-06-17'),
          ('EEE','e4','DIV','Trả cổ tức bằng tiền mặt - Cả năm 2024 - 800 VND',
           'CASH_DIVIDEND',TRUE,NULL);
    """)
    # --- B2: BCTC chi tiết ---
    # Mô phỏng đúng ca thật: item_id 'cost' trùng 2 lần (2 nhóm tài sản
    # khác nhau, cùng item_id, khác item_vi/row_seq) — đúng bài học A3
    # I2/B1 Task 4/5: fixture phải khớp schema/hành vi thật, không chỉ khớp
    # tên cột, nếu không lỗi phân biệt row_seq sẽ lọt qua mọi test.
    con.execute("""
        CREATE TABLE stg_financial_statement (
            symbol VARCHAR, statement_type VARCHAR, period_type VARCHAR,
            period_label VARCHAR, row_seq INTEGER, item_id VARCHAR,
            item_vi VARCHAR, item_en VARCHAR, value DOUBLE
        );
        INSERT INTO stg_financial_statement VALUES
          ('AAA','income_statement','quarter','2026-Q2',0,'net_sales','Doanh thu thuần','Net sales',100.0),
          ('AAA','income_statement','quarter','2026-Q1',0,'net_sales','Doanh thu thuần','Net sales',90.0),
          ('AAA','balance_sheet','quarter','2026-Q2',30,'cost','Nguyên giá TSCĐ hữu hình','Cost of tangible FA',10.0),
          ('AAA','balance_sheet','quarter','2026-Q1',30,'cost','Nguyên giá TSCĐ hữu hình','Cost of tangible FA',9.0),
          ('AAA','balance_sheet','quarter','2026-Q2',40,'cost','Nguyên giá tài sản đầu tư','Cost of investment property',5.0),
          ('AAA','balance_sheet','quarter','2026-Q1',40,'cost','Nguyên giá tài sản đầu tư','Cost of investment property',4.0);
    """)
    # --- C1: raw_financial_statement (cần ingested_at, KHÔNG có trong
    # stg_financial_statement — _new_statement_periods phải đọc bảng raw).
    con.execute("""
        CREATE TABLE raw_financial_statement (
            symbol VARCHAR, statement_type VARCHAR, period_type VARCHAR,
            period_label VARCHAR, row_seq INTEGER, item_id VARCHAR,
            item_vi VARCHAR, item_en VARCHAR, value DOUBLE,
            ingested_at TIMESTAMP
        );
        INSERT INTO raw_financial_statement VALUES
          ('AAA','income_statement','quarter','2026-q1',0,'net_sales',
           'Doanh thu thuần','Net sales',90.0, TIMESTAMP '2026-05-01 00:00:00'),
          ('AAA','income_statement','quarter','2026-q2',0,'net_sales',
           'Doanh thu thuần','Net sales',100.0, TIMESTAMP '2026-08-18 00:00:00');
    """)
    # --- B2 final review: dữ liệu cho I2 (cắt âm thầm) và I3 (trôi dạt
    # template). Dùng mã RIÊNG (BIG/DRIFT) để không đụng các test cũ đang
    # đếm item của AAA.
    #
    # Nhãn kỳ ở đây viết thường ('2026-q2') đúng như production sinh ra
    # (_unpivot_statement lowercase toàn bộ tên cột) — khác các dòng AAA
    # phía trên viết hoa. Giữ cả hai dạng là CỐ Ý: sắp xếp DESC theo chuỗi
    # phải đúng thứ tự thời gian với cả hai, vì phần quyết định thứ tự là
    # tiền tố năm zero-pad, không phải chữ q hoa hay thường.
    #
    # BIG: 208 dòng x 10 kỳ = 2.080 dòng — ĐÚNG ca đã tái hiện được ở final
    # review, vượt hằng số cứng limit=2000 cũ nên tool trả về 200/208 item
    # mà has_data vẫn True, không tín hiệu nào báo bị cắt.
    con.execute("""
        INSERT INTO stg_financial_statement
        SELECT 'BIG', 'balance_sheet', 'quarter', p.period_label, s.seq,
               'item_' || s.seq, 'Dòng ' || s.seq, 'Row ' || s.seq,
               s.seq * 1.0 + p.k
        FROM generate_series(0, 207) AS s(seq)
        CROSS JOIN (VALUES
            ('2024-q1', 1), ('2024-q2', 2), ('2024-q3', 3), ('2024-q4', 4),
            ('2025-q1', 5), ('2025-q2', 6), ('2025-q3', 7), ('2025-q4', 8),
            ('2026-q1', 9), ('2026-q2', 10)
        ) AS p(period_label, k);
    """)
    # DRIFT: CÙNG row_seq=30 nhưng là HAI dòng BCTC khác hẳn nhau ở hai kỳ
    # khác nhau — mô phỏng template BCTC của VCI đổi theo thời gian. Phải
    # trả về 2 item RIÊNG BIỆT; gộp chỉ theo row_seq sẽ trộn giá trị của
    # "Hàng tồn kho" (kỳ cũ) vào chuỗi của "Nguyên giá TSCĐ hữu hình" (kỳ
    # mới) mà không có tín hiệu lỗi nào.
    con.execute("""
        INSERT INTO stg_financial_statement VALUES
          ('DRIFT','balance_sheet','quarter','2026-q2',30,'cost',
           'Nguyên giá TSCĐ hữu hình','Cost of tangible FA',10.0),
          ('DRIFT','balance_sheet','quarter','2025-q1',30,'inventory',
           'Hàng tồn kho','Inventories',7.0),
          ('DRIFT','balance_sheet','quarter','2026-q2',31,'other',
           'Tài sản khác','Other assets',1.0);
    """)
    # --- D: tỷ giá + tin tức ---
    con.execute("""
        CREATE TABLE stg_exchange_rate (
            currency_code VARCHAR, currency_name VARCHAR, buy_cash DOUBLE,
            buy_transfer DOUBLE, sell DOUBLE, rate_date DATE
        );
        INSERT INTO stg_exchange_rate VALUES
          ('USD','US DOLLAR',25000.0,25100.0,25400.0,DATE '2026-08-19'),
          ('USD','US DOLLAR',25050.0,25150.0,25450.0,DATE '2026-08-20'),
          ('DKK','DANISH KRONE',NULL,4012.10,4165.55,DATE '2026-08-20');

        CREATE TABLE stg_news (
            id VARCHAR, symbol VARCHAR, news_title VARCHAR,
            news_short_content VARCHAR, news_source_link VARCHAR,
            public_date TIMESTAMP
        );
        INSERT INTO stg_news VALUES
          ('n1','HPG','Tiêu đề mới nhất','Nội dung ngắn 1','https://x.com/1',
           TIMESTAMP '2026-08-20 10:00:00'),
          ('n2','HPG','Tiêu đề cũ hơn','Nội dung ngắn 2','https://x.com/2',
           TIMESTAMP '2026-08-19 09:00:00');
    """)
    # n3 (mã MLS riêng, không phải HPG): fixture `con` của
    # tests/test_mcp_tools.py mở read_only=True nên không thể INSERT ở thời
    # điểm chạy test (brief gốc giả định INSERT được trong test — sai với
    # fixture thật, xem task-4-report.md). Nướng sẵn dòng nội dung dài 500
    # ký tự vào đây, dùng mã MLS (trong portfolio, không phải HPG) để không
    # đụng test thứ tự "mới nhất trước" của HPG (chỉ trông cậy đúng 2 dòng).
    con.execute("""
        INSERT INTO stg_news VALUES
          ('n3','MLS','Tin dài','""" + "x" * 500 + """','https://x.com/3',
           TIMESTAMP '2026-08-21 08:00:00');
    """)
    con.close()

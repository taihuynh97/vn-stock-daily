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
            com_class VARCHAR, pe DOUBLE, pb DOUBLE, roe DOUBLE,
            revenue_ttm DOUBLE, earnings_ttm DOUBLE, revenue_yoy DOUBLE,
            earnings_yoy DOUBLE
        );
        INSERT INTO fct_financial_quarterly VALUES
          ('AAA',2026,2,DATE '2026-06-30','NONFIN',9.5,1.2,0.18,1e13,1e12,0.12,0.20),
          ('AAA',2026,1,DATE '2026-03-31','NONFIN',10.1,1.3,0.17,9.5e12,9e11,0.10,0.15);
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
        CREATE TABLE mart_sector_snapshot (
            icb_code_lv2 VARCHAR, industry_lv2 VARCHAR, com_class VARCHAR,
            period_end_date DATE, n_symbols BIGINT, median_pe DOUBLE,
            median_pb DOUBLE, median_roe DOUBLE, sector_return_3m DOUBLE
        );
        INSERT INTO mart_sector_snapshot VALUES
          ('1700','Tài nguyên cơ bản','NONFIN',DATE '2026-06-30',40,12.5,1.4,0.13,0.08),
          ('8300','Ngân hàng','BANK',DATE '2026-06-30',27,8.6,1.3,0.18,0.11);
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
    con.close()

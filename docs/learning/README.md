# Tài liệu học tập — VN Stock Daily

Đây là bộ tài liệu giúp bạn hiểu **toàn bộ hệ thống từ góc độ Data Analyst**, không chỉ biết "code làm gì" mà còn hiểu **tại sao làm vậy**, **thay thế bằng gì được**, và **nền tảng kiến thức nào đứng phía sau**.

## Thứ tự học gợi ý

| File | Chủ đề | Đọc khi nào |
|---|---|---|
| [01-kien-truc-tong-quan.md](01-kien-truc-tong-quan.md) | Toàn cảnh hệ thống, data flow, các lớp kiến trúc | **Đọc đầu tiên** |
| [02-thu-thap-du-lieu.md](02-thu-thap-du-lieu.md) | API, rate limiting, column normalization, backfill | Sau khi hiểu tổng quan |
| [03-warehouse-duckdb.md](03-warehouse-duckdb.md) | DuckDB, MotherDuck, ETL patterns, upsert | Để hiểu tầng lưu trữ |
| [04-tin-hieu-ky-thuat.md](04-tin-hieu-ky-thuat.md) | RSI, MA, screener value+momentum | Phần DA gần nhất |
| [05-ai-ban-tin.md](05-ai-ban-tin.md) | Claude API, prompt engineering trong data pipeline | Phần AI/LLM |
| [06-tu-dong-hoa.md](06-tu-dong-hoa.md) | GitHub Actions, cron, multi-cadence scheduling | Để hiểu vận hành |
| [07-nen-tang-data-engineer.md](07-nen-tang-data-engineer.md) | **Lộ trình DE**: ETL/ELT, data modeling, dbt, orchestration | **Đọc để chuyển sang DE** |
| [08-testing-pipeline.md](08-testing-pipeline.md) | pytest fixture, mock/patch, unit vs integration test | Sau khi đọc code tests/ |

## Các bổ sung trong docs hiện tại (v2)

- **01**: Thêm WAL mode (SQLite), argparse
- **02**: Thêm module-level singleton và thread safety
- **03**: Thêm LEFT JOIN + IS NULL pattern

## Bản đồ repo nhanh

```
vn-stock-daily/
├── main.py                  ← job bản tin hằng ngày (orchestrator)
├── build_warehouse.py       ← job nạp warehouse (daily/weekly/monthly)
├── backfill.py              ← nạp lịch sử 3 năm (one-time)
│
├── src/
│   ├── ingest.py            ← gọi API vnstock cho job bản tin
│   ├── ingest_market.py     ← gọi API vnstock cho job warehouse
│   ├── warehouse.py         ← DuckDB layer (read/write)
│   ├── signals.py           ← tính RSI, MA, vol_ratio
│   ├── screener.py          ← lọc cổ phiếu tiềm năng
│   ├── digest.py            ← gọi Claude API tạo bản tin
│   ├── notify.py            ← gửi Telegram
│   └── storage.py           ← SQLite log hằng ngày
│
├── config/
│   ├── warehouse.yml        ← danh sách sàn, nguồn dữ liệu
│   ├── screener.yml         ← tiêu chí lọc cổ phiếu
│   └── portfolio.yml        ← danh mục cá nhân của bạn
│
├── .github/workflows/
│   ├── daily.yml            ← chạy main.py mỗi ngày T2-T6
│   ├── warehouse.yml        ← chạy build_warehouse.py daily
│   ├── warehouse-weekly.yml ← chạy --mode weekly mỗi T7
│   └── warehouse-monthly.yml← chạy --mode monthly ngày 1 tháng
│
└── tests/                   ← unit tests cho từng module
```

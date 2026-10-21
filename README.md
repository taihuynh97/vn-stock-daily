# vn-stock-daily

Pipeline dữ liệu chứng khoán Việt Nam: mỗi ngày sau giờ đóng cửa kéo dữ liệu **toàn thị trường** (giá, chỉ số, tỷ số, sự kiện DN, BCTC, hồ sơ DN) vào warehouse trên **MotherDuck**, biến đổi bằng **dbt**, phục vụ phân tích qua SQL và MCP server.

> Luồng bản tin AI (`main.py` gọi Claude API tóm tắt, gửi Telegram) đã gỡ ngày 21/10/2026 — xem lịch sử git nếu cần khôi phục.

> ⚠️ **Miễn trừ trách nhiệm:** đây là công cụ tổng hợp thông tin và phát tín hiệu để tham khảo, **không phải lời khuyên đầu tư**. Mọi quyết định mua/bán là của bạn. Dữ liệu vnstock là cuối phiên/có độ trễ, không dùng cho giao dịch trong ngày.

## Kiến trúc

Ingestion ghi vào một warehouse trên MotherDuck, các consumer đọc từ đó:

```
INGESTION (Python)                WAREHOUSE            CONSUMERS
build_warehouse.py --mode         raw_* (immutable)    ├─ MCP server (hội thoại)
  daily   → giá EOD + chỉ số        ↓ dbt              ├─ alert_events.py (cảnh báo sự kiện DN, Telegram)
  weekly  → tỷ số                 stg_* → int_*        └─ SQL ad-hoc
  trickle → sự kiện DN + BCTC quý    ↓
            + hồ sơ mã mới
  monthly → hồ sơ DN + sở hữu
                                  mart_* ← nơi mọi phân tích query vào
```

- `transforms/` — dbt project (staging → intermediate → marts)
- `src/scoring.py` + `config/scoring_profiles.yml` — bộ chấm điểm, đổi "gu" đầu tư ở đây
- `mcp_server/` — 13 tool read-only cho luồng hội thoại

### Bật/tắt luồng hội thoại

Xoá khai báo trong `.mcp.json` là tắt hoàn toàn MCP server. Warehouse, dbt và
cảnh báo sự kiện không bị ảnh hưởng.

### Chạy screener bằng dòng lệnh

```bash
export WAREHOUSE_DB=md:vn_market
python -c "
from src import warehouse, scoring
con = warehouse.get_conn()
print(scoring.screen(con, 'bluechip_dividend', limit=20).to_string())
"
```

## Cấu hình

- `config/portfolio.yml` — các mã theo dõi (dùng cho tin tức và cảnh báo sự kiện DN).
- `config/warehouse.yml` — sàn, chỉ số, kích thước lô bảng giá.
- `config/scoring_profiles.yml`, `config/graham_screen.yml` — bộ chấm điểm và ngưỡng sàng lọc.

## Chạy thử ở máy (WSL)

```bash
pip install -r requirements.txt
export WAREHOUSE_DB=data/warehouse.duckdb   # hoặc md:vn_market + motherduck_token
python build_warehouse.py --mode daily
cd transforms && dbt build --profiles-dir .
```

## Lập lịch bằng GitHub Actions

| Workflow | Lịch (giờ VN) | Việc |
|---|---|---|
| `warehouse.yml` | 15:30 T2–T6 | giá EOD + chỉ số, dbt build |
| `warehouse-trickle.yml` | 06:07, 11:07, 19:07 | sự kiện DN, BCTC quý, hồ sơ mã mới (nạp rải) |
| `warehouse-weekly.yml` | 15:30 T7 | tỷ số tài chính, dbt build |
| `warehouse-monthly.yml` | 16:00 ngày 1 | hồ sơ DN, sở hữu, BCTC năm |
| `event-alerts.yml` | 16:00 T2–T6 | cảnh báo sự kiện DN cho danh mục |

Cần khai báo secrets trong repo (Settings → Secrets and variables → Actions):

| Secret | Lấy ở đâu |
|---|---|
| `MOTHERDUCK_TOKEN` | app.motherduck.com → Settings → Access tokens |
| `TELEGRAM_BOT_TOKEN` | nhắn **@BotFather** → `/newbot` |
| `TELEGRAM_CHAT_ID` | nhắn cho bot 1 tin, rồi mở `https://api.telegram.org/bot<token>/getUpdates` lấy `chat.id` |
| `VNSTOCK_API_KEY` | (tuỳ chọn) đăng ký miễn phí ở vnstocks.com nếu nguồn dữ liệu yêu cầu |

Bấm **Run workflow** ở tab Actions để chạy tay kiểm tra trước khi để chạy tự động.

## Những điểm cần biết

- **Nguồn hợp lệ:** giá, báo cáo TC, chỉ số, tin doanh nghiệp đều qua API vnstock. Job **không** scrape báo cáo phân tích có bản quyền của các CTCK.
- **vnstock đổi API:** mọi lời gọi vnstock gói trong `src/ingest.py`; thư viện cập nhật thì chỉ sửa 1 file. Một số nguồn dữ liệu/mã có thể cần API key vnstock miễn phí.
- **Chi phí:** không gọi API trả phí nào. GitHub Actions: repo private có 2.000 phút/tháng (gói Free) — các job trên cần ~2.000–2.200 phút/tháng; repo public thì không giới hạn.
- **Cron GHA** chạy theo UTC và đôi khi trễ vài phút lúc cao điểm — không sao với job cuối phiên.
- **Hạn chế nền tảng của phân tích** (tin tức chỉ 5 mã, BCTC gốc 8 quý/8 năm, tỷ số trễ, không có vĩ mô ngoài tỷ giá, một nguồn VCI...): xem `docs/han-che-nen-tang.md`.
- **Giá:** `fct_price_daily.close` là giá khớp thật, `adj_close` là giá đã điều chỉnh chia/thưởng/cổ tức. Từ 07/06 đến khi merge mảng Q, giá đóng cửa hằng ngày bị lấy nhầm giá tham chiếu — sau merge chạy một lần `python scripts/repair_price_history.py --db md:vn_market --apply` (~80 phút). Chi tiết: `docs/Q-ket-qua-va-no-ky-thuat.md`.
- **Sàng lọc:** tool MCP `screen_graham` với ngưỡng trong `config/graham_screen.yml` (có `version`); `get_risk_flags` là cổng biến cố bắt buộc trước khi định giá.

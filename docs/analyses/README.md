# Nhật ký phân tích

Mỗi lần agent trả lời một câu hỏi sàng lọc hoặc định giá, nó ghi một file
`YYYY-MM-DD-<chủ-đề>.md` vào thư mục này. Mục đích: lần sau hỏi lại cùng mã
hoặc cùng ngành, agent đối chiếu **bằng số** với lần trước thay vì đưa ra một
kết luận mới mà không giải thích vì sao khác.

Lý do có thư mục này: ngày 03/09, 10/09 và 12/09/2026, ba câu hỏi gần giống
nhau cho ba kết quả khác nhau (khu công nghiệp, ngân hàng, rổ 11 mã) vì thước
đo và ngưỡng đổi giữa các phiên mà không được ghi lại.

## Khuôn mẫu

```markdown
# <Chủ đề> — <ngày>

**Câu hỏi:** <nguyên văn câu hỏi của người dùng>

**Phiếu intake:** dạng câu hỏi · lăng kính · kỳ hạn nắm giữ · phân tích cũ đã đọc

**Mốc dữ liệu:** giá đến <price_as_of> · tỷ số đến <ratio_as_of> · phễu `config_version` <...>

**Phễu:** bảng bước → số mã còn lại (chép từ `screen_graham.steps`)

**Kết quả:**
| Mã | P/E hiện tại | P/B hiện tại | risk_gate | Ghi chú |
|---|---|---|---|---|

**Mã bị chặn (`cho`):** <mã — cờ>

**Ngưỡng đã nêu:** <mã — vùng giá trị / ngưỡng biên an toàn>

**Khác lần trước:** <tên file cũ — khác ở đâu, bằng số>

**Nguồn ngoài:** <link — ngày>
```

Không ghi khuyến nghị mua/bán. Không ghi số liệu không có nguồn.

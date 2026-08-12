{#
  Sinh danh sách cột chỉ tiêu đã khử sentinel.

  Nguyên tắc: VCI trả 0.0 cho chỉ tiêu "không áp dụng" với loại hình đó.
  Chỉ tiêu nhóm NONFIN chỉ giữ lại khi com_class='NONFIN'; nhóm BANK chỉ giữ
  khi com_class='BANK'; nhóm COMMON giữ cho mọi loại hình.

  Fix round 1 (review C2): OTHERFIN (bảo hiểm/chứng khoán) KHÔNG chỉ dùng
  nhóm COMMON — đo trên production: BH 478/478, CK ~1.396/1.402 (~99,6%) có
  giá trị THẬT ở 14/15 chỉ tiêu metrics_nonfin. Chỉ tiêu nào có mặt trong
  var('metrics_otherfin') (14/15, trừ days_inventory_outstanding — công ty
  chứng khoán/bảo hiểm không có hàng tồn kho) thì giữ cho cả NONFIN lẫn
  OTHERFIN; phần còn lại của metrics_nonfin vẫn chỉ giữ riêng cho NONFIN.
  com_class OTHERFIN vẫn tách riêng khỏi NONFIN (không gộp) — so percentile
  ROIC của công ty chứng khoán với nhà máy thép là không tương đương.
#}
{% macro applicable_metrics() %}
    {%- for m in var('metrics_common') %}
    , {{ m }}
    {%- endfor %}
    {%- for m in var('metrics_nonfin') %}
        {%- if m in var('metrics_otherfin') %}
    , case when com_class in ('NONFIN', 'OTHERFIN') then {{ m }} end as {{ m }}
        {%- else %}
    , case when com_class = 'NONFIN' then {{ m }} end as {{ m }}
        {%- endif %}
    {%- endfor %}
    {%- for m in var('metrics_bank') %}
    , case when com_class = 'BANK' then {{ m }} end as {{ m }}
    {%- endfor %}
{% endmacro %}


{# Danh sách phẳng tất cả 44 chỉ tiêu — dùng cho UNPIVOT ở Task 5. #}
{% macro all_metrics() %}
    {{- return(var('metrics_common') + var('metrics_nonfin') + var('metrics_bank')) -}}
{% endmacro %}

{#
  Sinh danh sách cột chỉ tiêu đã khử sentinel.

  Nguyên tắc: VCI trả 0.0 cho chỉ tiêu "không áp dụng" với loại hình đó.
  Chỉ tiêu nhóm NONFIN chỉ giữ lại khi com_class='NONFIN'; nhóm BANK chỉ giữ
  khi com_class='BANK'; nhóm COMMON giữ cho mọi loại hình.

  OTHERFIN (bảo hiểm/chứng khoán) chỉ dùng nhóm COMMON — đúng thiết kế.
#}
{% macro applicable_metrics() %}
    {%- for m in var('metrics_common') %}
    , {{ m }}
    {%- endfor %}
    {%- for m in var('metrics_nonfin') %}
    , case when com_class = 'NONFIN' then {{ m }} end as {{ m }}
    {%- endfor %}
    {%- for m in var('metrics_bank') %}
    , case when com_class = 'BANK' then {{ m }} end as {{ m }}
    {%- endfor %}
{% endmacro %}


{# Danh sách phẳng tất cả 44 chỉ tiêu — dùng cho UNPIVOT ở Task 5. #}
{% macro all_metrics() %}
    {{- return(var('metrics_common') + var('metrics_nonfin') + var('metrics_bank')) -}}
{% endmacro %}

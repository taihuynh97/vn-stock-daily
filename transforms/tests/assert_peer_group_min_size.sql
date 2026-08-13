-- Mọi percentile peer phải dựa trên đủ số mã, nếu không xếp hạng vô nghĩa.
select symbol, metric, peer_basis, peer_count
from {{ ref('int_metric_percentile') }}
where pct_peer is not null
  and peer_count < {{ var('peer_hard_min') }}

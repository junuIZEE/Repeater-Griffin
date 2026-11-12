"""Desktop dashboard and visualization modules."""

from dashboard.charts import (
    MATPLOTLIB_AVAILABLE,
    build_ranking_figure,
    build_rtt_figure,
    build_throughput_figure,
    save_all_charts,
)

__all__ = [
    "MATPLOTLIB_AVAILABLE",
    "build_ranking_figure",
    "build_rtt_figure",
    "build_throughput_figure",
    "save_all_charts",
]


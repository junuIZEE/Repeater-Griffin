"""Matplotlib visualization generators for Repeater Griffin."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from placement.ranker import PlacementReport, PositionEvaluation
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    from matplotlib.figure import Figure
    from matplotlib.patches import Patch

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency fallback
    Figure = object  # type: ignore[misc,assignment]
    Patch = object  # type: ignore[misc,assignment]
    MATPLOTLIB_AVAILABLE = False


def _ordered_for_charts(report: PlacementReport) -> list[PositionEvaluation]:
    """Order positions consistently by position label for comparison charts."""
    return sorted(report.ranked_positions, key=lambda p: p.candidate_position)


def build_throughput_figure(
    report: PlacementReport,
    direction: str = "upload",
    figsize: tuple[float, float] = (7.0, 4.2),
) -> Figure:
    """Create a Matplotlib Figure comparing median upload or download throughput."""
    if not MATPLOTLIB_AVAILABLE:
        raise RuntimeError("matplotlib is not installed. Install it via 'pip install matplotlib'.")

    normalized = direction.strip().lower()
    if normalized not in ("upload", "download"):
        raise ValueError(f"Unsupported chart direction: {direction}")

    positions = _ordered_for_charts(report)
    labels = [p.candidate_position for p in positions]
    values = [
        (p.median_upload_mbps if normalized == "upload" else p.median_download_mbps) or 0.0
        for p in positions
    ]
    available_flags = [
        p.is_available
        and (
            (p.median_upload_mbps if normalized == "upload" else p.median_download_mbps)
            is not None
        )
        for p in positions
    ]

    fig = Figure(figsize=figsize, dpi=100)
    ax = fig.add_subplot(111)

    primary_color = "#1f77b4" if normalized == "upload" else "#2ca02c"
    colors = [primary_color if ok else "#bdbdbd" for ok in available_flags]
    bars = ax.bar(labels, values, color=colors, edgecolor="#333333", linewidth=0.8)

    for bar, ok, val in zip(bars, available_flags, values):
        if not ok:
            bar.set_hatch("//")
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                0.5,
                "Unavailable",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#444444",
                rotation=0,
            )
        else:
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                val,
                f"{val:.1f}",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
            )

    title_dir = "Upload" if normalized == "upload" else "Download"
    ax.set_title(f"Median {title_dir} Throughput by Candidate Position", fontsize=12, pad=12)
    ax.set_xlabel("Candidate Position", fontsize=10)
    ax.set_ylabel("Throughput (Mbps)", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    max_val = max(values) if values else 10.0
    ax.set_ylim(0, max(max_val * 1.18, 5.0))

    legend_handles = [
        Patch(facecolor=primary_color, edgecolor="#333333", label=f"Median {title_dir} (Mbps)"),
        Patch(facecolor="#bdbdbd", edgecolor="#333333", hatch="//", label="Unavailable"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)
    fig.tight_layout()
    return fig


def build_rtt_figure(
    report: PlacementReport,
    figsize: tuple[float, float] = (7.0, 4.2),
) -> Figure:
    """Create a Matplotlib Figure comparing median RTT (ms) and packet loss."""
    if not MATPLOTLIB_AVAILABLE:
        raise RuntimeError("matplotlib is not installed. Install it via 'pip install matplotlib'.")

    positions = _ordered_for_charts(report)
    labels = [p.candidate_position for p in positions]
    rtts = [p.median_rtt_ms if p.median_rtt_ms is not None else 0.0 for p in positions]
    has_rtt = [p.median_rtt_ms is not None for p in positions]

    fig = Figure(figsize=figsize, dpi=100)
    ax = fig.add_subplot(111)

    colors = ["#ff7f0e" if ok else "#bdbdbd" for ok in has_rtt]
    bars = ax.bar(labels, rtts, color=colors, edgecolor="#333333", linewidth=0.8)

    for bar, ok, pos in zip(bars, has_rtt, positions):
        loss_note = (
            f"\n({pos.median_packet_loss_pct:.0f}% loss)"
            if pos.median_packet_loss_pct is not None and pos.median_packet_loss_pct > 0
            else ""
        )
        if not ok:
            bar.set_hatch("//")
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                0.5,
                f"N/A{loss_note}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#444444",
            )
        else:
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height(),
                f"{bar.get_height():.1f} ms{loss_note}",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )

    ax.set_title("Median Round-Trip Time (RTT) by Candidate Position", fontsize=12, pad=12)
    ax.set_xlabel("Candidate Position", fontsize=10)
    ax.set_ylabel("Median RTT (ms) — Lower is Better", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    max_rtt = max(rtts) if rtts else 20.0
    ax.set_ylim(0, max(max_rtt * 1.25, 10.0))

    legend_handles = [
        Patch(facecolor="#ff7f0e", edgecolor="#333333", label="Median RTT (ms)"),
        Patch(facecolor="#bdbdbd", edgecolor="#333333", hatch="//", label="RTT Unavailable"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)
    fig.tight_layout()
    return fig


def build_ranking_figure(
    report: PlacementReport,
    figsize: tuple[float, float] = (7.0, 4.2),
) -> Figure:
    """Create a Matplotlib Figure showing ranked bottleneck scores across tested positions."""
    if not MATPLOTLIB_AVAILABLE:
        raise RuntimeError("matplotlib is not installed. Install it via 'pip install matplotlib'.")

    ordered = list(report.ranked_positions)
    labels = [
        f"#{p.rank} {p.candidate_position}" if p.rank is not None else f"N/A {p.candidate_position}"
        for p in ordered
    ]
    scores = [p.score_mbps if (p.is_available and p.score_mbps is not None) else 0.0 for p in ordered]

    fig = Figure(figsize=figsize, dpi=100)
    ax = fig.add_subplot(111)

    best_name = report.best_position.candidate_position if report.best_position else None
    colors: list[str] = []
    for p in ordered:
        if not p.is_available:
            colors.append("#bdbdbd")
        elif p.candidate_position == best_name:
            colors.append("#2e7d32")
        else:
            colors.append("#4c78a8")

    bars = ax.bar(labels, scores, color=colors, edgecolor="#333333", linewidth=0.8)

    for bar, pos in zip(bars, ordered):
        if not pos.is_available or pos.score_mbps is None:
            bar.set_hatch("//")
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                0.5,
                "Unavailable",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#444444",
            )
        else:
            rtt_label = f"\nRTT: {pos.median_rtt_ms:.1f}ms" if pos.median_rtt_ms is not None else ""
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                pos.score_mbps,
                f"{pos.score_mbps:.1f} Mbps{rtt_label}",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )

    ax.set_title(
        "Placement Ranking Score: min(Median Upload, Median Download)",
        fontsize=11.5,
        pad=12,
    )
    ax.set_xlabel("Tested Candidate Position (Ranked Best to Worst)", fontsize=10)
    ax.set_ylabel("Ranking Score (Mbps)", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    max_score = max(scores) if scores else 10.0
    ax.set_ylim(0, max(max_score * 1.25, 5.0))

    legend_handles = [
        Patch(facecolor="#2e7d32", edgecolor="#333333", label="Best Tested Position"),
        Patch(facecolor="#4c78a8", edgecolor="#333333", label="Other Available Positions"),
        Patch(facecolor="#bdbdbd", edgecolor="#333333", hatch="//", label="Unavailable"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)
    fig.tight_layout()
    return fig


def save_all_charts(
    report: PlacementReport,
    output_dir: Path,
    prefix: Optional[str] = None,
) -> dict[str, Path]:
    """Generate and save all four placement comparison charts into `output_dir`."""
    if not MATPLOTLIB_AVAILABLE:
        raise RuntimeError("matplotlib is not installed. Cannot save charts.")

    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name_prefix = f"{prefix}_" if prefix else ""

    chart_specs = {
        "upload": (
            f"{name_prefix}upload_throughput_comparison.png",
            build_throughput_figure(report, direction="upload"),
        ),
        "download": (
            f"{name_prefix}download_throughput_comparison.png",
            build_throughput_figure(report, direction="download"),
        ),
        "rtt": (
            f"{name_prefix}rtt_comparison.png",
            build_rtt_figure(report),
        ),
        "ranking": (
            f"{name_prefix}placement_ranking.png",
            build_ranking_figure(report),
        ),
    }

    saved: dict[str, Path] = {}
    for key, (filename, fig) in chart_specs.items():
        out_path = dest_dir / filename
        fig.savefig(out_path, dpi=150)
        saved[key] = out_path
        logger.info("Saved %s chart to %s", key, out_path)

    return saved


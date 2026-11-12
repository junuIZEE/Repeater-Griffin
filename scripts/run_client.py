"""CLI measurement and placement-ranking runner for Repeater Griffin."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.charts import MATPLOTLIB_AVAILABLE, save_all_charts  # noqa: E402
from hotspot.manager import check_hotspot_status  # noqa: E402
from measurement.runner import run_position_experiment  # noqa: E402
from placement.ranker import PlacementReport, rank_from_raw_records  # noqa: E402
from storage.csv_handler import append_processed_summary, load_raw_measurements  # noqa: E402
from utils.config import DEFAULT_SETTINGS_PATH, load_settings  # noqa: E402
from utils.logger import setup_logging  # noqa: E402


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Repeater Griffin measurements or compute rankings from CSV."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="Path to settings JSON file (default: config/settings.json).",
    )
    parser.add_argument(
        "--position",
        type=str,
        default="",
        help="Candidate position label to test (e.g., P1).",
    )
    parser.add_argument(
        "--server",
        type=str,
        default="",
        help="Override iperf3 server IP.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Override iperf3 port.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Override iperf3 test duration in seconds.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=0,
        help="Override number of repetitions per direction.",
    )
    parser.add_argument(
        "--ping-target",
        type=str,
        default="",
        help="Override ping target IP/host.",
    )
    parser.add_argument(
        "--rank-only",
        action="store_true",
        help="Skip live tests; compute rankings and graphs from existing raw CSV data.",
    )
    return parser.parse_args(argv)


def _print_report(report: PlacementReport) -> None:
    print("\n=== Placement Ranking Report ===")
    print(f"{'Rank':<6} {'Pos':<6} {'Med Up':>10} {'Med Down':>10} {'Score':>10} {'Med RTT':>10} {'Loss %':>8}  Status")
    print("-" * 78)
    for ev in report.ranked_positions:
        rank_s = f"#{ev.rank}" if ev.rank is not None else "-"
        up_s = f"{ev.median_upload_mbps:.2f}" if ev.median_upload_mbps is not None else "-"
        down_s = f"{ev.median_download_mbps:.2f}" if ev.median_download_mbps is not None else "-"
        score_s = f"{ev.score_mbps:.2f}" if ev.score_mbps is not None else "-"
        rtt_s = f"{ev.median_rtt_ms:.2f}" if ev.median_rtt_ms is not None else "-"
        loss_s = f"{ev.median_packet_loss_pct:.2f}" if ev.median_packet_loss_pct is not None else "-"
        print(
            f"{rank_s:<6} {ev.candidate_position:<6} {up_s:>10} {down_s:>10} "
            f"{score_s:>10} {rtt_s:>10} {loss_s:>8}  {ev.status}"
        )
    print("\n" + report.recommendation_text)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    settings = load_settings(args.config)
    settings.ensure_directories()
    setup_logging(log_file=settings.reports_path / "repeater_griffin_cli.log")

    if args.server:
        settings.iperf3.server_ip = args.server
    if args.port > 0:
        settings.iperf3.port = args.port
    if args.duration > 0:
        settings.iperf3.duration_sec = args.duration
    if args.repetitions > 0:
        settings.iperf3.repetitions = args.repetitions
    if args.ping_target:
        settings.ping.target = args.ping_target

    hs = check_hotspot_status()
    print(f"Hotspot status: {hs.state} — {hs.summary}")

    if not args.rank_only:
        if not args.position:
            print(
                "Error: Provide --position <LABEL> (e.g., --position P1) or use --rank-only.",
                file=sys.stderr,
            )
            return 1

        def on_progress(step: int, total: int, message: str) -> None:
            print(f"[{step}/{total}] {message}")

        run_position_experiment(
            candidate_position=args.position,
            settings=settings,
            progress_callback=on_progress,
        )

    records = load_raw_measurements(settings.raw_csv_path)
    if not records:
        print(f"No measurements found at {settings.raw_csv_path}.")
        return 0

    report = rank_from_raw_records(
        records,
        tie_threshold_pct=settings.placement.tie_threshold_pct,
        required_repetitions=settings.iperf3.repetitions,
    )
    _print_report(report)
    append_processed_summary(settings.summary_csv_path, report.ranked_positions)

    if MATPLOTLIB_AVAILABLE:
        saved = save_all_charts(report, settings.graphs_path)
        print("\nSaved graphs:")
        for name, path in saved.items():
            print(f"  {name}: {path}")
    else:
        print("\nNote: matplotlib not installed; skipped graph generation.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


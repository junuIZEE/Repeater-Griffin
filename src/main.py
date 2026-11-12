"""Entry point for the Repeater Griffin desktop application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils.config import DEFAULT_SETTINGS_PATH, load_settings  # noqa: E402
from utils.logger import setup_logging  # noqa: E402


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repeater-griffin",
        description="Repeater Griffin: Performance-Guided Wi-Fi Repeater Placement",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="Path to JSON settings file (default: config/settings.json).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and module imports without opening the GUI.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    settings = load_settings(args.config)
    settings.ensure_directories()

    logger = setup_logging(log_file=settings.reports_path / "repeater_griffin.log")
    logger.info("Loaded settings from %s", args.config)

    if args.check:
        from hotspot.manager import check_hotspot_status
        from dashboard.charts import MATPLOTLIB_AVAILABLE

        hs = check_hotspot_status()
        print(f"App: {settings.app_name}")
        print(f"iperf3 target: {settings.iperf3.server_ip}:{settings.iperf3.port}")
        print(f"Hotspot status: {hs.state} ({hs.summary})")
        print(f"Matplotlib available: {MATPLOTLIB_AVAILABLE}")
        return 0

    try:
        from dashboard.app import launch_dashboard
    except ImportError as exc:
        logger.error("Tkinter GUI could not be imported: %s", exc)
        print(
            "Error: Tkinter is unavailable in this Python installation. "
            "On Windows, reinstall Python with 'tcl/tk and IDLE' enabled, "
            "or use 'python scripts/run_client.py' for CLI measurements.",
            file=sys.stderr,
        )
        return 1

    launch_dashboard(settings=settings, config_path=args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


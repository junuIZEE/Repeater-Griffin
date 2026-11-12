"""Helper script to launch the iperf3 server on the Ethernet-connected machine."""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils.config import DEFAULT_SETTINGS_PATH, load_settings  # noqa: E402


def _get_local_ipv4_hints() -> list[str]:
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    settings = load_settings(DEFAULT_SETTINGS_PATH)
    parser = argparse.ArgumentParser(
        description="Start the iperf3 server for Repeater Griffin throughput experiments."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.iperf3.port,
        help=f"TCP port to listen on (default: {settings.iperf3.port}).",
    )
    parser.add_argument(
        "--bind",
        default="",
        help="Optional local IP address to bind the iperf3 server to.",
    )
    parser.add_argument(
        "--executable",
        default=settings.iperf3.executable_path,
        help="Path or command name for iperf3 executable.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    exe = shutil.which(args.executable) or args.executable

    cmd = [exe, "-s", "-p", str(args.port)]
    if args.bind:
        cmd.extend(["-B", args.bind])

    ip_hints = _get_local_ipv4_hints()
    print("Repeater Griffin — Ethernet iperf3 Server")
    print(f"Command: {' '.join(cmd)}")
    if ip_hints:
        print(f"Detected local IPv4 address(es): {', '.join(ip_hints)}")
    print("Press Ctrl+C to stop the server.\n")

    try:
        completed = subprocess.run(cmd, check=False)
        return completed.returncode
    except FileNotFoundError:
        print(
            f"Error: iperf3 executable '{args.executable}' not found. "
            "Install iperf3 and ensure it is in PATH.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\niperf3 server stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())


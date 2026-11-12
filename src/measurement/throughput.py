"""TCP throughput measurement using iperf3."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

TestDirection = Literal["upload", "download"]

_BLOCKED_PUBLIC_SPEEDTEST_DOMAINS = (
    "speedtest.net",
    "fast.com",
    "speed.cloudflare.com",
    "iperf.he.net",
    "iperf.scottlinux.com",
    "ping.online.net",
    "bouygues.iperf.fr",
)


@dataclass
class ThroughputResult:
    """Structured TCP throughput measurement returned from an iperf3 run."""

    direction: str
    server_ip: str
    port: int
    duration_sec: float
    throughput_mbps: Optional[float] = None
    retransmits: Optional[int] = None
    bytes_transferred: Optional[int] = None
    status: str = "error"
    error_message: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    raw_json: Optional[dict[str, Any]] = None


def build_iperf3_command(
    server_ip: str,
    port: int = 5201,
    duration_sec: int = 20,
    direction: str = "upload",
    parallel_streams: int = 1,
    executable_path: str = "iperf3",
) -> list[str]:
    """Build the iperf3 client command list."""
    normalized_direction = direction.strip().lower()
    if normalized_direction not in ("upload", "download"):
        raise ValueError(
            f"Unsupported direction '{direction}'. Expected 'upload' or 'download'."
        )

    cmd = [
        executable_path,
        "-c",
        server_ip,
        "-p",
        str(port),
        "-t",
        str(duration_sec),
        "-P",
        str(parallel_streams),
        "-J",
    ]
    if normalized_direction == "download":
        cmd.append("-R")
    return cmd


def parse_iperf3_json(
    raw_stdout: str,
    direction: str,
    server_ip: str,
    port: int,
    duration_sec: int,
    return_code: int = 0,
    raw_stderr: str = "",
) -> ThroughputResult:
    """Parse iperf3 JSON output into a structured ThroughputResult."""
    normalized_direction = direction.strip().lower()
    text = (raw_stdout or "").strip()

    if not text:
        err_text = (raw_stderr or "").strip() or (
            f"iperf3 produced no output (exit code {return_code})."
        )
        status = _classify_connection_error(err_text)
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status=status,
            error_message=err_text,
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        err_detail = f"Invalid JSON output from iperf3: {exc}"
        if raw_stderr.strip():
            err_detail = f"{err_detail} | stderr: {raw_stderr.strip()}"
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="invalid_output",
            error_message=err_detail,
        )

    if not isinstance(payload, dict):
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="invalid_output",
            error_message="iperf3 JSON root is not an object.",
        )

    if "error" in payload and payload["error"]:
        err_msg = str(payload["error"])
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status=_classify_connection_error(err_msg),
            error_message=err_msg,
            raw_json=payload,
        )

    end_section = payload.get("end")
    if not isinstance(end_section, dict):
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="invalid_output",
            error_message="Missing 'end' summary section in iperf3 JSON output.",
            raw_json=payload,
        )

    sum_received = end_section.get("sum_received")
    sum_sent = end_section.get("sum_sent")

    # Prefer sum_received (goodput delivered to receiver); fall back to sum_sent.
    primary_summary: Optional[dict[str, Any]] = None
    if isinstance(sum_received, dict) and "bits_per_second" in sum_received:
        primary_summary = sum_received
    elif isinstance(sum_sent, dict) and "bits_per_second" in sum_sent:
        primary_summary = sum_sent

    if primary_summary is None:
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="invalid_output",
            error_message="Missing 'bits_per_second' in iperf3 JSON summary.",
            raw_json=payload,
        )

    try:
        bps = float(primary_summary["bits_per_second"])
    except (TypeError, ValueError) as exc:
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="invalid_output",
            error_message=f"Invalid bits_per_second value: {exc}",
            raw_json=payload,
        )

    throughput_mbps = round(bps / 1_000_000.0, 3)

    actual_seconds = primary_summary.get("seconds")
    measured_duration = (
        round(float(actual_seconds), 3)
        if isinstance(actual_seconds, (int, float)) and actual_seconds > 0
        else float(duration_sec)
    )

    bytes_transferred = primary_summary.get("bytes")
    if not isinstance(bytes_transferred, int):
        bytes_transferred = int(bytes_transferred) if isinstance(bytes_transferred, float) else None

    retransmits = None
    if isinstance(sum_sent, dict) and isinstance(sum_sent.get("retransmits"), int):
        retransmits = sum_sent["retransmits"]

    if return_code != 0:
        err_msg = (raw_stderr or "").strip() or f"iperf3 exited with code {return_code}."
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=server_ip,
            port=port,
            duration_sec=measured_duration,
            throughput_mbps=throughput_mbps,
            retransmits=retransmits,
            bytes_transferred=bytes_transferred,
            status="error",
            error_message=err_msg,
            raw_json=payload,
        )

    return ThroughputResult(
        direction=normalized_direction,
        server_ip=server_ip,
        port=port,
        duration_sec=measured_duration,
        throughput_mbps=throughput_mbps,
        retransmits=retransmits,
        bytes_transferred=bytes_transferred,
        status="success",
        raw_json=payload,
    )


def _classify_connection_error(message: str) -> str:
    lower = message.lower()
    connection_hints = (
        "unable to connect",
        "connection refused",
        "no route to host",
        "network is unreachable",
        "server is busy",
        "timed out",
        "interrupt",
        "unable to send control message",
    )
    if any(hint in lower for hint in connection_hints):
        return "connection_failed"
    return "error"


def _is_blocked_public_server(server_ip: str) -> bool:
    lower = server_ip.strip().lower()
    return any(domain in lower for domain in _BLOCKED_PUBLIC_SPEEDTEST_DOMAINS)


def measure_throughput(
    server_ip: str,
    port: int = 5201,
    duration_sec: int = 20,
    direction: str = "upload",
    parallel_streams: int = 1,
    executable_path: str = "iperf3",
    timeout_buffer_sec: int = 15,
) -> ThroughputResult:
    """Run an iperf3 TCP throughput test against a local Ethernet-connected server.

    Args:
        server_ip: Local IP/hostname of the Ethernet-connected iperf3 server.
        port: TCP port where iperf3 server is listening (default 5201).
        duration_sec: Test duration in seconds (default 20).
        direction: 'upload' (client -> server) or 'download' (server -> client, -R).
        parallel_streams: Number of parallel TCP streams (default 1).
        executable_path: Path or command name for the iperf3 binary.
        timeout_buffer_sec: Extra seconds added to duration for subprocess timeout.

    Returns:
        ThroughputResult with throughput in Mbps and diagnostic status.
    """
    clean_ip = (server_ip or "").strip()
    normalized_direction = (direction or "").strip().lower()

    if normalized_direction not in ("upload", "download"):
        return ThroughputResult(
            direction=normalized_direction or "unknown",
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message=f"Invalid direction '{direction}'. Use 'upload' or 'download'.",
        )

    if not clean_ip:
        return ThroughputResult(
            direction=normalized_direction,
            server_ip="",
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message="iperf3 server IP cannot be empty.",
        )

    if _is_blocked_public_server(clean_ip):
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message=(
                f"Public speed-test servers ('{clean_ip}') are not allowed. "
                "Use the local Ethernet-connected iperf3 server IP."
            ),
        )

    if port <= 0 or port > 65535:
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message=f"Invalid TCP port: {port}. Must be between 1 and 65535.",
        )

    if duration_sec <= 0:
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message=f"Test duration must be positive, got {duration_sec}.",
        )

    cmd = build_iperf3_command(
        server_ip=clean_ip,
        port=port,
        duration_sec=duration_sec,
        direction=normalized_direction,
        parallel_streams=parallel_streams,
        executable_path=executable_path,
    )
    timeout_sec = duration_sec + max(5, timeout_buffer_sec)

    logger.info("Executing iperf3 (%s): %s", normalized_direction, " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError:
        msg = (
            f"iperf3 executable '{executable_path}' was not found. "
            "Install iperf3 and add it to PATH or set iperf3.executable_path in config/settings.json."
        )
        logger.error(msg)
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="missing_executable",
            error_message=msg,
        )
    except subprocess.TimeoutExpired:
        msg = (
            f"iperf3 {normalized_direction} test to {clean_ip}:{port} "
            f"timed out after {timeout_sec}s."
        )
        logger.warning(msg)
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="timeout",
            error_message=msg,
        )
    except OSError as exc:
        msg = f"Failed to execute iperf3: {exc}"
        logger.error(msg)
        return ThroughputResult(
            direction=normalized_direction,
            server_ip=clean_ip,
            port=port,
            duration_sec=float(duration_sec),
            status="error",
            error_message=msg,
        )

    return parse_iperf3_json(
        raw_stdout=completed.stdout,
        direction=normalized_direction,
        server_ip=clean_ip,
        port=port,
        duration_sec=duration_sec,
        return_code=completed.returncode,
        raw_stderr=completed.stderr,
    )


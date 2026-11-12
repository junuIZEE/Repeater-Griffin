"""Latency (RTT) measurement using Windows ping."""

from __future__ import annotations

import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from measurement.packet_loss import parse_ping_packet_loss
from utils.logger import get_logger

logger = get_logger(__name__)

# Matches Windows/POSIX per-packet RTT values:
#   time=4ms, time=12.3ms, time<1ms, time=4.12 ms
_RTT_TOKEN_RE = re.compile(r"time\s*([=<])\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)

# Windows RTT summary line fallback:
#   Minimum = 2ms, Maximum = 8ms, Average = 4ms
_WIN_RTT_STATS_RE = re.compile(
    r"Minimum\s*=\s*(\d+(?:\.\d+)?)\s*ms,\s*Maximum\s*=\s*(\d+(?:\.\d+)?)\s*ms,\s*"
    r"Average\s*=\s*(\d+(?:\.\d+)?)\s*ms",
    re.IGNORECASE,
)

_UNREACHABLE_HINTS = (
    "destination host unreachable",
    "destination net unreachable",
    "could not find host",
    "unknown host",
    "transmit failed",
    "general failure",
)


@dataclass
class LatencyResult:
    """Structured ping latency and packet-loss measurement result."""

    target: str
    packet_count: int
    rtts_ms: list[float] = field(default_factory=list)
    median_rtt_ms: Optional[float] = None
    min_rtt_ms: Optional[float] = None
    max_rtt_ms: Optional[float] = None
    packets_sent: int = 0
    packets_received: int = 0
    packets_lost: int = 0
    packet_loss_pct: float = 100.0
    status: str = "error"
    error_message: Optional[str] = None
    raw_output: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


def build_ping_command(
    target: str,
    packet_count: int = 10,
    timeout_ms: int = 2000,
    platform_name: Optional[str] = None,
) -> list[str]:
    """Build the OS-appropriate ping command, targeting Windows ping by default."""
    plat = (platform_name or sys.platform).lower()
    if plat.startswith("win"):
        return ["ping", "-n", str(packet_count), "-w", str(timeout_ms), target]
    timeout_sec = max(1, round(timeout_ms / 1000))
    return ["ping", "-c", str(packet_count), "-W", str(timeout_sec), target]


def extract_individual_rtts(raw_output: str) -> list[float]:
    """Extract per-packet RTT measurements (in milliseconds) from ping output.

    Windows `time<1ms` responses are recorded as 0.5 ms (midpoint of <1 ms).
    """
    rtts: list[float] = []
    for operator, numeric_str in _RTT_TOKEN_RE.findall(raw_output or ""):
        value = float(numeric_str)
        if operator == "<" and value <= 1.0:
            rtts.append(0.5)
        else:
            rtts.append(value)
    return rtts


def parse_ping_output(
    raw_output: str,
    target: str,
    packet_count: int,
    return_code: int = 0,
) -> LatencyResult:
    """Parse raw ping output into a structured LatencyResult."""
    text = raw_output or ""
    lower_text = text.lower()
    rtts = extract_individual_rtts(text)
    loss = parse_ping_packet_loss(text, expected_count=packet_count, target=target)

    median_rtt: Optional[float] = None
    min_rtt: Optional[float] = None
    max_rtt: Optional[float] = None

    if rtts:
        median_rtt = round(float(statistics.median(rtts)), 3)
        min_rtt = round(min(rtts), 3)
        max_rtt = round(max(rtts), 3)
    else:
        stats_match = _WIN_RTT_STATS_RE.search(text)
        if stats_match and loss.packets_received > 0:
            min_rtt = float(stats_match.group(1))
            max_rtt = float(stats_match.group(2))
            median_rtt = float(stats_match.group(3))

    error_message = loss.error_message
    if any(hint in lower_text for hint in _UNREACHABLE_HINTS) and not rtts:
        status = "unreachable"
        if not error_message:
            error_message = f"Ping target {target} is unreachable."
    elif not rtts and ("request timed out" in lower_text or loss.packet_loss_pct == 100.0):
        status = "timeout"
        if not error_message:
            error_message = f"All ping requests to {target} timed out."
    elif loss.packet_loss_pct > 0.0 and rtts:
        status = "partial_loss"
        if not error_message:
            error_message = f"Partial packet loss ({loss.packet_loss_pct}%) to {target}."
    elif rtts and return_code == 0:
        status = "success"
    elif rtts:
        status = "partial_loss" if loss.packet_loss_pct > 0.0 else "success"
    else:
        status = "error"
        if not error_message:
            error_message = text.strip() or f"Ping failed with exit code {return_code}."

    return LatencyResult(
        target=target,
        packet_count=packet_count,
        rtts_ms=rtts,
        median_rtt_ms=median_rtt,
        min_rtt_ms=min_rtt,
        max_rtt_ms=max_rtt,
        packets_sent=loss.packets_sent,
        packets_received=loss.packets_received,
        packets_lost=loss.packets_lost,
        packet_loss_pct=loss.packet_loss_pct,
        status=status,
        error_message=error_message,
        raw_output=text,
    )


def measure_latency(
    target: str,
    packet_count: int = 10,
    timeout_ms: int = 2000,
    platform_name: Optional[str] = None,
) -> LatencyResult:
    """Execute ping against `target` and return structured RTT and packet-loss metrics."""
    clean_target = (target or "").strip()
    if not clean_target:
        return LatencyResult(
            target="",
            packet_count=packet_count,
            status="error",
            error_message="Ping target cannot be empty.",
        )
    if packet_count <= 0:
        return LatencyResult(
            target=clean_target,
            packet_count=packet_count,
            status="error",
            error_message="Ping packet_count must be greater than zero.",
        )

    cmd = build_ping_command(
        target=clean_target,
        packet_count=packet_count,
        timeout_ms=timeout_ms,
        platform_name=platform_name,
    )
    overall_timeout = (packet_count * max(timeout_ms / 1000.0, 1.0)) + 10.0

    logger.info("Executing ping: %s", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=overall_timeout,
            check=False,
        )
    except FileNotFoundError:
        msg = "System 'ping' executable was not found in PATH."
        logger.error(msg)
        return LatencyResult(
            target=clean_target,
            packet_count=packet_count,
            status="missing_executable",
            error_message=msg,
        )
    except subprocess.TimeoutExpired as exc:
        partial_out = (exc.stdout or "") + "\n" + (exc.stderr or "")
        if isinstance(partial_out, bytes):
            partial_out = partial_out.decode("utf-8", errors="replace")
        parsed = parse_ping_output(
            partial_out,
            target=clean_target,
            packet_count=packet_count,
            return_code=1,
        )
        parsed.status = "timeout"
        parsed.error_message = (
            f"Ping subprocess timed out after {overall_timeout:.1f}s for {clean_target}."
        )
        logger.warning(parsed.error_message)
        return parsed
    except OSError as exc:
        msg = f"Failed to execute ping: {exc}"
        logger.error(msg)
        return LatencyResult(
            target=clean_target,
            packet_count=packet_count,
            status="error",
            error_message=msg,
        )

    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )
    return parse_ping_output(
        combined_output,
        target=clean_target,
        packet_count=packet_count,
        return_code=completed.returncode,
    )


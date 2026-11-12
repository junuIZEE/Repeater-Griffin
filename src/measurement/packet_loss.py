"""Packet-loss parsing and calculation utilities built on Windows ping output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from utils.logger import get_logger

if TYPE_CHECKING:
    from measurement.latency import LatencyResult

logger = get_logger(__name__)

# Windows ping summary, e.g.:
#   Packets: Sent = 10, Received = 8, Lost = 2 (20% loss),
_WIN_SUMMARY_RE = re.compile(
    r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)"
    r"(?:\s*\((\d+(?:\.\d+)?)%\s*loss\))?",
    re.IGNORECASE,
)

# Secondary Linux/macOS summary fallback, e.g.:
#   10 packets transmitted, 8 received, 20% packet loss
_POSIX_SUMMARY_RE = re.compile(
    r"(\d+)\s+packets\s+transmitted,\s+(\d+)\s+(?:packets\s+)?received,"
    r".*?(\d+(?:\.\d+)?)%\s+packet\s+loss",
    re.IGNORECASE,
)

# Individual successful echo reply line (contains time=...ms or time<1ms)
_SUCCESS_REPLY_RE = re.compile(r"time\s*[=<]\s*\d+(?:\.\d+)?\s*ms", re.IGNORECASE)

_FATAL_PING_ERROR_PATTERNS = (
    "could not find host",
    "unknown host",
    "name or service not known",
    "transmit failed",
    "general failure",
    "invalid",
)


@dataclass
class PacketLossResult:
    """Structured result for packet-loss extraction from ping output."""

    target: str
    packets_sent: int
    packets_received: int
    packets_lost: int
    packet_loss_pct: float
    status: str
    error_message: Optional[str] = None


def calculate_packet_loss_pct(packets_sent: int, packets_received: int) -> float:
    """Compute packet loss percentage in [0.0, 100.0].

    Args:
        packets_sent: Total probe packets transmitted.
        packets_received: Total valid echo replies received.

    Returns:
        Numeric packet-loss percentage rounded to two decimal places.
        Returns 100.0 if packets_sent <= 0 (request failed before sending).
    """
    if packets_sent <= 0:
        return 100.0
    clamped_received = max(0, min(packets_received, packets_sent))
    loss_pct = ((packets_sent - clamped_received) / packets_sent) * 100.0
    return round(loss_pct, 2)


def parse_ping_packet_loss(
    raw_output: str,
    expected_count: Optional[int] = None,
    target: str = "",
) -> PacketLossResult:
    """Parse Windows (or POSIX fallback) ping output into packet-loss metrics.

    Args:
        raw_output: Combined stdout/stderr text from ping execution.
        expected_count: Expected probe count when summary lines are absent
            (for example, after a subprocess timeout).
        target: Ping target host/IP for reporting.

    Returns:
        PacketLossResult with numeric packet_loss_pct.
    """
    text = raw_output or ""
    lower_text = text.lower()

    win_match = _WIN_SUMMARY_RE.search(text)
    if win_match:
        sent = int(win_match.group(1))
        received = int(win_match.group(2))
        lost = int(win_match.group(3))
        loss_pct = calculate_packet_loss_pct(sent, received)
        status = "success" if loss_pct == 0.0 else ("failed" if received == 0 else "partial_loss")
        return PacketLossResult(
            target=target,
            packets_sent=sent,
            packets_received=received,
            packets_lost=lost,
            packet_loss_pct=loss_pct,
            status=status,
        )

    posix_match = _POSIX_SUMMARY_RE.search(text)
    if posix_match:
        sent = int(posix_match.group(1))
        received = int(posix_match.group(2))
        lost = max(0, sent - received)
        loss_pct = calculate_packet_loss_pct(sent, received)
        status = "success" if loss_pct == 0.0 else ("failed" if received == 0 else "partial_loss")
        return PacketLossResult(
            target=target,
            packets_sent=sent,
            packets_received=received,
            packets_lost=lost,
            packet_loss_pct=loss_pct,
            status=status,
        )

    # Fallback when ping output is truncated or terminated on error before summary.
    replies = len(_SUCCESS_REPLY_RE.findall(text))
    for pattern in _FATAL_PING_ERROR_PATTERNS:
        if pattern in lower_text:
            sent = expected_count if expected_count and expected_count > 0 else 0
            return PacketLossResult(
                target=target,
                packets_sent=sent,
                packets_received=0,
                packets_lost=sent,
                packet_loss_pct=100.0,
                status="failed",
                error_message=text.strip() or f"Ping failed ({pattern}).",
            )

    if expected_count and expected_count > 0:
        sent = expected_count
        received = min(replies, sent)
        lost = sent - received
        loss_pct = calculate_packet_loss_pct(sent, received)
        status = "success" if loss_pct == 0.0 else ("failed" if received == 0 else "partial_loss")
        return PacketLossResult(
            target=target,
            packets_sent=sent,
            packets_received=received,
            packets_lost=lost,
            packet_loss_pct=loss_pct,
            status=status,
            error_message=None if received > 0 else "No ping summary or replies received.",
        )

    return PacketLossResult(
        target=target,
        packets_sent=0,
        packets_received=0,
        packets_lost=0,
        packet_loss_pct=100.0,
        status="failed",
        error_message=text.strip() or "Unable to parse ping output.",
    )


def extract_packet_loss_from_latency(latency_result: "LatencyResult") -> PacketLossResult:
    """Reuse an existing LatencyResult without re-executing ping."""
    if latency_result.raw_output:
        parsed = parse_ping_packet_loss(
            latency_result.raw_output,
            expected_count=latency_result.packet_count,
            target=latency_result.target,
        )
        if latency_result.error_message and not parsed.error_message:
            parsed.error_message = latency_result.error_message
        return parsed

    loss_pct = calculate_packet_loss_pct(
        latency_result.packets_sent,
        latency_result.packets_received,
    )
    return PacketLossResult(
        target=latency_result.target,
        packets_sent=latency_result.packets_sent,
        packets_received=latency_result.packets_received,
        packets_lost=latency_result.packets_lost,
        packet_loss_pct=loss_pct,
        status=latency_result.status,
        error_message=latency_result.error_message,
    )


def measure_packet_loss(
    target: str,
    packet_count: int = 10,
    timeout_ms: int = 2000,
    latency_result: Optional["LatencyResult"] = None,
) -> PacketLossResult:
    """Obtain packet-loss percentage, reusing a prior LatencyResult when provided.

    If `latency_result` is None, executes `measure_latency` once and extracts
    packet-loss metrics from that single ping invocation.
    """
    if latency_result is not None:
        return extract_packet_loss_from_latency(latency_result)

    from measurement.latency import measure_latency

    result = measure_latency(
        target=target,
        packet_count=packet_count,
        timeout_ms=timeout_ms,
    )
    return extract_packet_loss_from_latency(result)


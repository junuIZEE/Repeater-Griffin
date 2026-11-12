"""Unit tests for Windows ping latency and packet-loss measurement (synthetic fixtures)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from measurement.latency import (
    build_ping_command,
    extract_individual_rtts,
    measure_latency,
    parse_ping_output,
)
from measurement.packet_loss import (
    calculate_packet_loss_pct,
    measure_packet_loss,
    parse_ping_packet_loss,
)

WINDOWS_PING_SUCCESS_FIXTURE = """
Pinging 192.168.1.100 with 32 bytes of data:
Reply from 192.168.1.100: bytes=32 time=12ms TTL=64
Reply from 192.168.1.100: bytes=32 time=8ms TTL=64
Reply from 192.168.1.100: bytes=32 time=20ms TTL=64
Reply from 192.168.1.100: bytes=32 time<1ms TTL=64
Reply from 192.168.1.100: bytes=32 time=10ms TTL=64

Ping statistics for 192.168.1.100:
    Packets: Sent = 5, Received = 5, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 20ms, Average = 10ms
"""

WINDOWS_PING_PARTIAL_LOSS_FIXTURE = """
Pinging 192.168.1.100 with 32 bytes of data:
Reply from 192.168.1.100: bytes=32 time=14ms TTL=64
Request timed out.
Reply from 192.168.1.100: bytes=32 time=18ms TTL=64
Request timed out.

Ping statistics for 192.168.1.100:
    Packets: Sent = 4, Received = 2, Lost = 2 (50% loss),
Approximate round trip times in milli-seconds:
    Minimum = 14ms, Maximum = 18ms, Average = 16ms
"""

WINDOWS_PING_UNREACHABLE_FIXTURE = """
Pinging 192.168.1.250 with 32 bytes of data:
Reply from 192.168.137.1: Destination host unreachable.
Reply from 192.168.137.1: Destination host unreachable.
Reply from 192.168.137.1: Destination host unreachable.
Reply from 192.168.137.1: Destination host unreachable.

Ping statistics for 192.168.1.250:
    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),
"""


def test_build_ping_command_windows_and_linux() -> None:
    win_cmd = build_ping_command("192.168.1.100", packet_count=10, timeout_ms=2000, platform_name="win32")
    assert win_cmd == ["ping", "-n", "10", "-w", "2000", "192.168.1.100"]

    linux_cmd = build_ping_command("192.168.1.100", packet_count=10, timeout_ms=2000, platform_name="linux")
    assert linux_cmd == ["ping", "-c", "10", "-W", "2", "192.168.1.100"]


def test_parse_windows_ping_success_and_median_rtt() -> None:
    rtts = extract_individual_rtts(WINDOWS_PING_SUCCESS_FIXTURE)
    assert rtts == [12.0, 8.0, 20.0, 0.5, 10.0]

    result = parse_ping_output(
        WINDOWS_PING_SUCCESS_FIXTURE,
        target="192.168.1.100",
        packet_count=5,
        return_code=0,
    )
    assert result.status == "success"
    assert result.median_rtt_ms == pytest.approx(10.0)
    assert result.min_rtt_ms == pytest.approx(0.5)
    assert result.max_rtt_ms == pytest.approx(20.0)
    assert result.packet_loss_pct == pytest.approx(0.0)
    assert result.packets_sent == 5
    assert result.packets_received == 5


def test_parse_windows_ping_partial_loss() -> None:
    result = parse_ping_output(
        WINDOWS_PING_PARTIAL_LOSS_FIXTURE,
        target="192.168.1.100",
        packet_count=4,
        return_code=0,
    )
    assert result.status == "partial_loss"
    assert result.rtts_ms == [14.0, 18.0]
    assert result.median_rtt_ms == pytest.approx(16.0)
    assert result.packet_loss_pct == pytest.approx(50.0)
    assert result.packets_lost == 2


def test_parse_windows_ping_unreachable() -> None:
    result = parse_ping_output(
        WINDOWS_PING_UNREACHABLE_FIXTURE,
        target="192.168.1.250",
        packet_count=4,
        return_code=1,
    )
    assert result.status == "unreachable"
    assert result.rtts_ms == []
    assert result.median_rtt_ms is None
    assert result.packet_loss_pct == pytest.approx(100.0)


def test_packet_loss_reuse_without_duplicate_ping() -> None:
    latency_res = parse_ping_output(
        WINDOWS_PING_PARTIAL_LOSS_FIXTURE,
        target="192.168.1.100",
        packet_count=4,
    )
    with patch("measurement.latency.measure_latency") as mock_measure:
        loss_res = measure_packet_loss("192.168.1.100", latency_result=latency_res)
        mock_measure.assert_not_called()

    assert loss_res.packet_loss_pct == pytest.approx(50.0)
    assert loss_res.packets_sent == 4
    assert loss_res.packets_received == 2


def test_calculate_packet_loss_edge_cases() -> None:
    assert calculate_packet_loss_pct(0, 0) == pytest.approx(100.0)
    assert calculate_packet_loss_pct(10, 10) == pytest.approx(0.0)
    assert calculate_packet_loss_pct(10, 7) == pytest.approx(30.0)

    dns_fail = parse_ping_packet_loss(
        "Ping request could not find host nonexistent.local. Please check the name and try again.",
        expected_count=4,
        target="nonexistent.local",
    )
    assert dns_fail.packet_loss_pct == pytest.approx(100.0)
    assert dns_fail.status == "failed"


@patch("measurement.latency.subprocess.run")
def test_measure_latency_subprocess_timeout(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ping"], timeout=15)
    result = measure_latency("192.168.1.100", packet_count=4, timeout_ms=2000)
    assert result.status == "timeout"
    assert result.packet_loss_pct == pytest.approx(100.0)


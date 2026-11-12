"""Unit tests for iperf3 TCP throughput measurement (using synthetic fixtures)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from measurement.throughput import (
    build_iperf3_command,
    measure_throughput,
    parse_iperf3_json,
)


def _synthetic_iperf3_json(
    bits_per_second: float = 52_500_000.0,
    retransmits: int = 3,
    seconds: float = 20.0,
) -> str:
    """Return a synthetic iperf3 JSON output payload for unit testing."""
    payload = {
        "start": {"connected": [{"socket": 5, "local_host": "192.168.137.42"}]},
        "end": {
            "sum_sent": {
                "seconds": seconds,
                "bytes": int((bits_per_second / 8.0) * seconds),
                "bits_per_second": bits_per_second * 1.01,
                "retransmits": retransmits,
            },
            "sum_received": {
                "seconds": seconds,
                "bytes": int((bits_per_second / 8.0) * seconds),
                "bits_per_second": bits_per_second,
            },
        },
    }
    return json.dumps(payload)


def test_build_iperf3_command_upload_and_download() -> None:
    up_cmd = build_iperf3_command("192.168.1.100", port=5201, duration_sec=20, direction="upload")
    assert up_cmd == ["iperf3", "-c", "192.168.1.100", "-p", "5201", "-t", "20", "-P", "1", "-J"]
    assert "-R" not in up_cmd

    down_cmd = build_iperf3_command("192.168.1.100", port=5202, duration_sec=15, direction="download")
    assert down_cmd[-1] == "-R"
    assert "-J" in down_cmd


def test_parse_valid_iperf3_json() -> None:
    raw = _synthetic_iperf3_json(bits_per_second=48_250_000.0, retransmits=2, seconds=20.0)
    result = parse_iperf3_json(
        raw_stdout=raw,
        direction="download",
        server_ip="192.168.1.100",
        port=5201,
        duration_sec=20,
    )
    assert result.status == "success"
    assert result.direction == "download"
    assert result.throughput_mbps == pytest.approx(48.25)
    assert result.retransmits == 2
    assert result.duration_sec == pytest.approx(20.0)
    assert result.error_message is None


def test_parse_iperf3_error_json() -> None:
    raw = json.dumps({"error": "unable to connect to server: Connection refused"})
    result = parse_iperf3_json(
        raw_stdout=raw,
        direction="upload",
        server_ip="192.168.1.100",
        port=5201,
        duration_sec=20,
        return_code=1,
    )
    assert result.status == "connection_failed"
    assert result.throughput_mbps is None
    assert "Connection refused" in (result.error_message or "")


def test_parse_invalid_json_and_missing_keys() -> None:
    bad_json = parse_iperf3_json(
        raw_stdout="{not-valid-json",
        direction="upload",
        server_ip="192.168.1.100",
        port=5201,
        duration_sec=20,
    )
    assert bad_json.status == "invalid_output"
    assert bad_json.throughput_mbps is None

    missing_end = parse_iperf3_json(
        raw_stdout=json.dumps({"start": {}}),
        direction="upload",
        server_ip="192.168.1.100",
        port=5201,
        duration_sec=20,
    )
    assert missing_end.status == "invalid_output"


@patch("measurement.throughput.subprocess.run")
def test_measure_throughput_missing_executable(mock_run: MagicMock) -> None:
    mock_run.side_effect = FileNotFoundError("No such file")
    result = measure_throughput(server_ip="192.168.1.100", duration_sec=20, direction="upload")
    assert result.status == "missing_executable"
    assert result.throughput_mbps is None
    assert "iperf3" in (result.error_message or "")


@patch("measurement.throughput.subprocess.run")
def test_measure_throughput_timeout(mock_run: MagicMock) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["iperf3"], timeout=35)
    result = measure_throughput(server_ip="192.168.1.100", duration_sec=20, direction="download")
    assert result.status == "timeout"
    assert result.throughput_mbps is None


@patch("measurement.throughput.subprocess.run")
def test_measure_throughput_success_subprocess(mock_run: MagicMock) -> None:
    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = _synthetic_iperf3_json(bits_per_second=64_000_000.0)
    completed.stderr = ""
    mock_run.return_value = completed

    result = measure_throughput(server_ip="192.168.1.100", port=5201, duration_sec=20, direction="upload")
    assert result.status == "success"
    assert result.throughput_mbps == pytest.approx(64.0)
    mock_run.assert_called_once()


def test_rejects_public_speedtest_domains_and_invalid_inputs() -> None:
    blocked = measure_throughput(server_ip="speedtest.net", direction="upload")
    assert blocked.status == "error"
    assert "not allowed" in (blocked.error_message or "").lower()

    bad_dir = measure_throughput(server_ip="192.168.1.100", direction="sideways")
    assert bad_dir.status == "error"

    bad_port = measure_throughput(server_ip="192.168.1.100", port=70000, direction="upload")
    assert bad_port.status == "error"


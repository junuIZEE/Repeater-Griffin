"""Experiment runner orchestrating upload, download, ping, and CSV logging."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from measurement.latency import LatencyResult, measure_latency
from measurement.packet_loss import PacketLossResult, extract_packet_loss_from_latency
from measurement.throughput import ThroughputResult, measure_throughput
from storage.csv_handler import RawMeasurementRecord, append_raw_measurement
from utils.config import AppSettings
from utils.logger import get_logger

logger = get_logger(__name__)

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class PositionExperimentResult:
    """Results collected during a single candidate position measurement session."""

    experiment_id: str
    candidate_position: str
    upload_results: list[ThroughputResult] = field(default_factory=list)
    download_results: list[ThroughputResult] = field(default_factory=list)
    latency_result: Optional[LatencyResult] = None
    packet_loss_result: Optional[PacketLossResult] = None
    records: list[RawMeasurementRecord] = field(default_factory=list)
    cancelled: bool = False


def run_position_experiment(
    candidate_position: str,
    settings: AppSettings,
    experiment_id: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> PositionExperimentResult:
    """Execute upload/download iperf3 repetitions and ping test for one position.

    Appends each measurement record immediately to the configured raw CSV file
    without overwriting existing records.
    """
    pos = candidate_position.strip()
    if not pos:
        raise ValueError("Candidate position label cannot be empty.")

    settings.ensure_directories()
    exp_id = experiment_id or datetime.now(timezone.utc).strftime(f"exp_%Y%m%d_%H%M%S_{pos}")
    reps = max(1, int(settings.iperf3.repetitions))
    total_steps = (reps * 2) + 1
    current_step = 0

    def notify(message: str) -> None:
        if progress_callback is not None:
            progress_callback(current_step, total_steps, message)

    result = PositionExperimentResult(experiment_id=exp_id, candidate_position=pos)

    # 1. Upload throughput repetitions
    for rep in range(1, reps + 1):
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            notify(f"Measurement cancelled before {pos} upload {rep}/{reps}.")
            return result

        current_step += 1
        notify(f"[{pos}] Running upload test {rep}/{reps} ({settings.iperf3.duration_sec}s)...")
        tp_res = measure_throughput(
            server_ip=settings.iperf3.server_ip,
            port=settings.iperf3.port,
            duration_sec=settings.iperf3.duration_sec,
            direction="upload",
            parallel_streams=settings.iperf3.parallel_streams,
            executable_path=settings.iperf3.executable_path,
            timeout_buffer_sec=settings.iperf3.timeout_buffer_sec,
        )
        result.upload_results.append(tp_res)

        record = RawMeasurementRecord(
            candidate_position=pos,
            test_direction="upload",
            test_status=tp_res.status,
            repetition=rep,
            upload_throughput_mbps=tp_res.throughput_mbps,
            experiment_id=exp_id,
            server_ip=settings.iperf3.server_ip,
            ping_target=settings.ping.target,
            error_message=tp_res.error_message or "",
            timestamp=tp_res.timestamp,
        )
        append_raw_measurement(settings.raw_csv_path, record)
        result.records.append(record)

    # 2. Download throughput repetitions
    for rep in range(1, reps + 1):
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            notify(f"Measurement cancelled before {pos} download {rep}/{reps}.")
            return result

        current_step += 1
        notify(f"[{pos}] Running download test {rep}/{reps} ({settings.iperf3.duration_sec}s)...")
        tp_res = measure_throughput(
            server_ip=settings.iperf3.server_ip,
            port=settings.iperf3.port,
            duration_sec=settings.iperf3.duration_sec,
            direction="download",
            parallel_streams=settings.iperf3.parallel_streams,
            executable_path=settings.iperf3.executable_path,
            timeout_buffer_sec=settings.iperf3.timeout_buffer_sec,
        )
        result.download_results.append(tp_res)

        record = RawMeasurementRecord(
            candidate_position=pos,
            test_direction="download",
            test_status=tp_res.status,
            repetition=rep,
            download_throughput_mbps=tp_res.throughput_mbps,
            experiment_id=exp_id,
            server_ip=settings.iperf3.server_ip,
            ping_target=settings.ping.target,
            error_message=tp_res.error_message or "",
            timestamp=tp_res.timestamp,
        )
        append_raw_measurement(settings.raw_csv_path, record)
        result.records.append(record)

    # 3. Ping RTT and packet loss (single ping execution reused for packet loss)
    if cancel_event is not None and cancel_event.is_set():
        result.cancelled = True
        notify(f"Measurement cancelled before {pos} ping test.")
        return result

    current_step += 1
    notify(
        f"[{pos}] Measuring RTT & packet loss ({settings.ping.packet_count} pings to {settings.ping.target})..."
    )
    lat_res = measure_latency(
        target=settings.ping.target,
        packet_count=settings.ping.packet_count,
        timeout_ms=settings.ping.timeout_ms,
    )
    loss_res = extract_packet_loss_from_latency(lat_res)
    result.latency_result = lat_res
    result.packet_loss_result = loss_res

    ping_record = RawMeasurementRecord(
        candidate_position=pos,
        test_direction="ping",
        test_status=lat_res.status,
        repetition=1,
        rtt_ms=lat_res.median_rtt_ms,
        packet_loss_pct=loss_res.packet_loss_pct,
        experiment_id=exp_id,
        server_ip=settings.iperf3.server_ip,
        ping_target=settings.ping.target,
        error_message=lat_res.error_message or "",
        timestamp=lat_res.timestamp,
    )
    append_raw_measurement(settings.raw_csv_path, ping_record)
    result.records.append(ping_record)

    notify(f"[{pos}] Measurement complete and saved to {settings.raw_csv_path.name}.")
    return result


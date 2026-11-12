"""CSV persistence for raw measurements and processed placement summaries."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from utils.logger import get_logger

logger = get_logger(__name__)

RAW_CSV_COLUMNS = [
    "timestamp",
    "experiment_id",
    "candidate_position",
    "repetition",
    "test_direction",
    "upload_throughput_mbps",
    "download_throughput_mbps",
    "rtt_ms",
    "packet_loss_pct",
    "test_status",
    "server_ip",
    "ping_target",
    "error_message",
]

SUMMARY_CSV_COLUMNS = [
    "summary_timestamp",
    "run_id",
    "rank",
    "candidate_position",
    "is_available",
    "median_upload_mbps",
    "median_download_mbps",
    "score_mbps",
    "median_rtt_ms",
    "median_packet_loss_pct",
    "max_packet_loss_pct",
    "upload_runs",
    "download_runs",
    "ping_runs",
    "tie_broken_by_rtt",
    "status",
    "notes",
]


@dataclass
class RawMeasurementRecord:
    """Single raw measurement row persisted to data/raw/."""

    candidate_position: str
    test_direction: str
    test_status: str
    repetition: int = 1
    upload_throughput_mbps: Optional[float] = None
    download_throughput_mbps: Optional[float] = None
    rtt_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    experiment_id: str = ""
    server_ip: str = ""
    ping_target: str = ""
    error_message: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_csv_row(self) -> dict[str, Any]:
        """Serialize record into a dictionary matching RAW_CSV_COLUMNS."""
        return {
            "timestamp": self.timestamp,
            "experiment_id": self.experiment_id,
            "candidate_position": self.candidate_position,
            "repetition": self.repetition,
            "test_direction": self.test_direction,
            "upload_throughput_mbps": _fmt_opt(self.upload_throughput_mbps),
            "download_throughput_mbps": _fmt_opt(self.download_throughput_mbps),
            "rtt_ms": _fmt_opt(self.rtt_ms),
            "packet_loss_pct": _fmt_opt(self.packet_loss_pct),
            "test_status": self.test_status,
            "server_ip": self.server_ip,
            "ping_target": self.ping_target,
            "error_message": self.error_message,
        }

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "RawMeasurementRecord":
        """Reconstruct a RawMeasurementRecord from a csv.DictReader row."""
        return cls(
            timestamp=row.get("timestamp", ""),
            experiment_id=row.get("experiment_id", ""),
            candidate_position=row.get("candidate_position", ""),
            repetition=_parse_int(row.get("repetition"), default=1),
            test_direction=row.get("test_direction", ""),
            upload_throughput_mbps=_parse_opt_float(row.get("upload_throughput_mbps")),
            download_throughput_mbps=_parse_opt_float(row.get("download_throughput_mbps")),
            rtt_ms=_parse_opt_float(row.get("rtt_ms")),
            packet_loss_pct=_parse_opt_float(row.get("packet_loss_pct")),
            test_status=row.get("test_status", ""),
            server_ip=row.get("server_ip", ""),
            ping_target=row.get("ping_target", ""),
            error_message=row.get("error_message", ""),
        )


def _fmt_opt(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _parse_opt_float(value: Optional[str]) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: Optional[str], default: int = 1) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def append_raw_measurement(csv_path: Path, record: RawMeasurementRecord) -> Path:
    """Append a single raw measurement record without overwriting existing rows."""
    return append_raw_measurements(csv_path, [record])


def append_raw_measurements(
    csv_path: Path,
    records: Iterable[RawMeasurementRecord],
) -> Path:
    """Append multiple raw measurement records to `csv_path`.

    Creates parent directories if needed and writes the CSV header only when
    the target file does not exist or is empty.
    """
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record_list = list(records)
    if not record_list:
        return path

    needs_header = (not path.exists()) or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_CSV_COLUMNS)
        if needs_header:
            writer.writeheader()
        for record in record_list:
            writer.writerow(record.to_csv_row())

    logger.info("Appended %d raw record(s) to %s", len(record_list), path)
    return path


def load_raw_measurements(csv_path: Path) -> list[RawMeasurementRecord]:
    """Load all raw measurement records from `csv_path`."""
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    records: list[RawMeasurementRecord] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row or not any(v.strip() for v in row.values() if isinstance(v, str)):
                continue
            records.append(RawMeasurementRecord.from_csv_row(row))
    return records


def append_processed_summary(
    csv_path: Path,
    ranked_positions: Sequence[Any],
    run_id: Optional[str] = None,
) -> Path:
    """Append processed placement summary rows to `data/processed/` without overwriting."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resolved_run_id = run_id or datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")

    needs_header = (not path.exists()) or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_CSV_COLUMNS)
        if needs_header:
            writer.writeheader()
        for pos in ranked_positions:
            writer.writerow(
                {
                    "summary_timestamp": summary_ts,
                    "run_id": resolved_run_id,
                    "rank": pos.rank if pos.rank is not None else "",
                    "candidate_position": pos.candidate_position,
                    "is_available": pos.is_available,
                    "median_upload_mbps": _fmt_opt(pos.median_upload_mbps),
                    "median_download_mbps": _fmt_opt(pos.median_download_mbps),
                    "score_mbps": _fmt_opt(pos.score_mbps),
                    "median_rtt_ms": _fmt_opt(pos.median_rtt_ms),
                    "median_packet_loss_pct": _fmt_opt(pos.median_packet_loss_pct),
                    "max_packet_loss_pct": _fmt_opt(pos.max_packet_loss_pct),
                    "upload_runs": pos.upload_run_count,
                    "download_runs": pos.download_run_count,
                    "ping_runs": pos.ping_run_count,
                    "tie_broken_by_rtt": pos.tie_broken_by_rtt,
                    "status": pos.status,
                    "notes": pos.notes,
                }
            )

    logger.info("Appended processed placement summary (%s) to %s", resolved_run_id, path)
    return path


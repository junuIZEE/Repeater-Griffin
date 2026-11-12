"""Measurement-based candidate placement ranking algorithm for Repeater Griffin."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from storage.csv_handler import RawMeasurementRecord

DEFAULT_REQUIRED_REPETITIONS = 3
DEFAULT_TIE_THRESHOLD_PCT = 5.0


@dataclass
class PositionMeasurements:
    """Aggregated raw measurements for a single candidate laptop position."""

    candidate_position: str
    upload_throughputs_mbps: list[float] = field(default_factory=list)
    download_throughputs_mbps: list[float] = field(default_factory=list)
    rtts_ms: list[float] = field(default_factory=list)
    packet_losses_pct: list[float] = field(default_factory=list)
    disconnected: bool = False
    total_upload_attempts: int = 0
    total_download_attempts: int = 0


@dataclass
class PositionEvaluation:
    """Evaluated metrics and final placement rank for a candidate position."""

    candidate_position: str
    is_available: bool
    rank: Optional[int]
    median_upload_mbps: Optional[float]
    median_download_mbps: Optional[float]
    score_mbps: Optional[float]
    median_rtt_ms: Optional[float]
    median_packet_loss_pct: Optional[float]
    max_packet_loss_pct: Optional[float]
    upload_run_count: int
    download_run_count: int
    ping_run_count: int
    tie_broken_by_rtt: bool = False
    tie_group: Optional[int] = None
    status: str = "available"
    notes: str = ""


@dataclass
class PlacementReport:
    """Complete placement ranking report limited to the tested candidate positions."""

    ranked_positions: list[PositionEvaluation]
    best_position: Optional[PositionEvaluation]
    tested_positions: list[str]
    tie_threshold_pct: float
    recommendation_text: str


def _valid_positive_floats(values: Iterable[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None and float(v) > 0.0]


def _valid_non_negative_floats(values: Iterable[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None and float(v) >= 0.0]


def evaluate_position(
    measurements: PositionMeasurements,
    required_repetitions: int = DEFAULT_REQUIRED_REPETITIONS,
) -> PositionEvaluation:
    """Compute medians and bottleneck score = min(median_upload, median_download)."""
    valid_uploads = _valid_positive_floats(measurements.upload_throughputs_mbps)
    valid_downloads = _valid_positive_floats(measurements.download_throughputs_mbps)
    valid_rtts = _valid_non_negative_floats(measurements.rtts_ms)
    valid_losses = [
        float(v)
        for v in measurements.packet_losses_pct
        if v is not None and 0.0 <= float(v) <= 100.0
    ]

    median_upload = (
        round(float(statistics.median(valid_uploads)), 3) if valid_uploads else None
    )
    median_download = (
        round(float(statistics.median(valid_downloads)), 3) if valid_downloads else None
    )
    median_rtt = round(float(statistics.median(valid_rtts)), 3) if valid_rtts else None
    median_loss = (
        round(float(statistics.median(valid_losses)), 2) if valid_losses else None
    )
    max_loss = round(max(valid_losses), 2) if valid_losses else None

    notes: list[str] = []
    if measurements.disconnected or median_upload is None or median_download is None:
        reason = (
            "Position marked disconnected."
            if measurements.disconnected
            else "Missing successful upload and/or download throughput measurements."
        )
        notes.append(reason)
        return PositionEvaluation(
            candidate_position=measurements.candidate_position,
            is_available=False,
            rank=None,
            median_upload_mbps=median_upload,
            median_download_mbps=median_download,
            score_mbps=None,
            median_rtt_ms=median_rtt,
            median_packet_loss_pct=median_loss,
            max_packet_loss_pct=max_loss,
            upload_run_count=len(valid_uploads),
            download_run_count=len(valid_downloads),
            ping_run_count=len(valid_rtts),
            status="unavailable",
            notes=" ".join(notes),
        )

    score = round(min(median_upload, median_download), 3)
    if score <= 0.0:
        notes.append("Calculated score is non-positive; position unavailable.")
        return PositionEvaluation(
            candidate_position=measurements.candidate_position,
            is_available=False,
            rank=None,
            median_upload_mbps=median_upload,
            median_download_mbps=median_download,
            score_mbps=None,
            median_rtt_ms=median_rtt,
            median_packet_loss_pct=median_loss,
            max_packet_loss_pct=max_loss,
            upload_run_count=len(valid_uploads),
            download_run_count=len(valid_downloads),
            ping_run_count=len(valid_rtts),
            status="unavailable",
            notes=" ".join(notes),
        )

    if len(valid_uploads) < required_repetitions:
        notes.append(
            f"Only {len(valid_uploads)}/{required_repetitions} valid upload runs."
        )
    if len(valid_downloads) < required_repetitions:
        notes.append(
            f"Only {len(valid_downloads)}/{required_repetitions} valid download runs."
        )
    if median_rtt is None:
        notes.append("No valid RTT measurements recorded.")

    return PositionEvaluation(
        candidate_position=measurements.candidate_position,
        is_available=True,
        rank=None,
        median_upload_mbps=median_upload,
        median_download_mbps=median_download,
        score_mbps=score,
        median_rtt_ms=median_rtt,
        median_packet_loss_pct=median_loss,
        max_packet_loss_pct=max_loss,
        upload_run_count=len(valid_uploads),
        download_run_count=len(valid_downloads),
        ping_run_count=len(valid_rtts),
        status="available",
        notes=" ".join(notes),
    )


def rank_positions(
    positions: Sequence[PositionMeasurements],
    tie_threshold_pct: float = DEFAULT_TIE_THRESHOLD_PCT,
    required_repetitions: int = DEFAULT_REQUIRED_REPETITIONS,
) -> PlacementReport:
    """Rank candidate positions using median bottleneck throughput and RTT tie-breaking.

    Algorithm:
    1. Calculate median upload and median download throughput per position.
    2. Score each available position as: score = min(median_upload, median_download).
    3. Rank available positions in descending order of score.
    4. Group positions whose scores fall within `tie_threshold_pct` (default 5%)
       of the tie-group leader's score, and break ties using lower median RTT.
    5. Mark disconnected or incomplete positions as unavailable.
    6. Preserve packet-loss statistics in every evaluation.
    """
    evaluations = [
        evaluate_position(pos, required_repetitions=required_repetitions)
        for pos in positions
    ]
    tested_names = [ev.candidate_position for ev in evaluations]

    available = [ev for ev in evaluations if ev.is_available and ev.score_mbps is not None]
    unavailable = [ev for ev in evaluations if not ev.is_available]

    # Deterministic primary sort by descending score (with RTT as sub-key for exact ties)
    available.sort(
        key=lambda ev: (
            -(ev.score_mbps if ev.score_mbps is not None else 0.0),
            ev.median_rtt_ms if ev.median_rtt_ms is not None else float("inf"),
            ev.median_packet_loss_pct
            if ev.median_packet_loss_pct is not None
            else float("inf"),
            ev.candidate_position,
        )
    )

    # Cluster into tie groups anchored at each group's highest-score leader.
    final_available: list[PositionEvaluation] = []
    idx = 0
    group_id = 1
    while idx < len(available):
        leader = available[idx]
        leader_score = leader.score_mbps or 0.0
        group = [leader]
        next_idx = idx + 1

        while next_idx < len(available):
            candidate = available[next_idx]
            candidate_score = candidate.score_mbps or 0.0
            diff_pct = (
                ((leader_score - candidate_score) / leader_score) * 100.0
                if leader_score > 0.0
                else 0.0
            )
            if diff_pct <= tie_threshold_pct + 1e-9:
                group.append(candidate)
                next_idx += 1
            else:
                break

        if len(group) > 1:
            group.sort(
                key=lambda ev: (
                    ev.median_rtt_ms if ev.median_rtt_ms is not None else float("inf"),
                    ev.median_packet_loss_pct
                    if ev.median_packet_loss_pct is not None
                    else float("inf"),
                    -(ev.score_mbps if ev.score_mbps is not None else 0.0),
                    ev.candidate_position,
                )
            )
            peer_names = ", ".join(ev.candidate_position for ev in group)
            for member in group:
                member.tie_broken_by_rtt = True
                member.tie_group = group_id
                tie_note = (
                    f"Score within {tie_threshold_pct:.1f}% tie band ({peer_names}); "
                    "ordered by lower median RTT."
                )
                member.notes = f"{member.notes} {tie_note}".strip()
            group_id += 1

        final_available.extend(group)
        idx = next_idx

    for rank_num, ev in enumerate(final_available, start=1):
        ev.rank = rank_num

    # Keep unavailable positions sorted alphabetically after ranked positions
    unavailable.sort(key=lambda ev: ev.candidate_position)
    ranked_all = final_available + unavailable
    best = final_available[0] if final_available else None

    recommendation = _build_recommendation_text(
        best=best,
        tested_names=tested_names,
        unavailable_count=len(unavailable),
    )

    return PlacementReport(
        ranked_positions=ranked_all,
        best_position=best,
        tested_positions=tested_names,
        tie_threshold_pct=tie_threshold_pct,
        recommendation_text=recommendation,
    )


def _build_recommendation_text(
    best: Optional[PositionEvaluation],
    tested_names: list[str],
    unavailable_count: int,
) -> str:
    tested_str = ", ".join(tested_names) if tested_names else "none"
    if best is None:
        return (
            f"No usable candidate position found among tested positions ({tested_str}). "
            "Verify router connection, Mobile Hotspot, and iperf3 server reachability."
        )

    rtt_str = f"{best.median_rtt_ms:.2f} ms" if best.median_rtt_ms is not None else "N/A"
    loss_str = (
        f"{best.median_packet_loss_pct:.2f}%"
        if best.median_packet_loss_pct is not None
        else "N/A"
    )
    tie_clause = " (tie resolved by lower median RTT)" if best.tie_broken_by_rtt else ""
    unavail_clause = (
        f" {unavailable_count} tested position(s) marked unavailable."
        if unavailable_count > 0
        else ""
    )

    return (
        f"Best tested candidate position: {best.candidate_position}{tie_clause} — "
        f"Score: {best.score_mbps:.2f} Mbps "
        f"(Median Up: {best.median_upload_mbps:.2f} Mbps, "
        f"Median Down: {best.median_download_mbps:.2f} Mbps, "
        f"Median RTT: {rtt_str}, Median Loss: {loss_str})."
        f"{unavail_clause} "
        f"Scope note: recommendation is restricted to the tested positions ({tested_str}) "
        "and does not claim global optimality."
    )


def aggregate_raw_records(
    records: Sequence[RawMeasurementRecord],
) -> list[PositionMeasurements]:
    """Group raw CSV measurement records by candidate position."""
    grouped: dict[str, PositionMeasurements] = {}

    for rec in records:
        pos = (rec.candidate_position or "").strip()
        if not pos:
            continue
        if pos not in grouped:
            grouped[pos] = PositionMeasurements(candidate_position=pos)
        bucket = grouped[pos]

        status_lower = (rec.test_status or "").strip().lower()
        direction_lower = (rec.test_direction or "").strip().lower()

        if status_lower == "disconnected":
            bucket.disconnected = True

        if direction_lower in ("upload", "combined", "both"):
            bucket.total_upload_attempts += 1
            if rec.upload_throughput_mbps is not None and rec.upload_throughput_mbps > 0:
                bucket.upload_throughputs_mbps.append(rec.upload_throughput_mbps)

        if direction_lower in ("download", "combined", "both"):
            bucket.total_download_attempts += 1
            if rec.download_throughput_mbps is not None and rec.download_throughput_mbps > 0:
                bucket.download_throughputs_mbps.append(rec.download_throughput_mbps)

        if rec.rtt_ms is not None and rec.rtt_ms >= 0:
            bucket.rtts_ms.append(rec.rtt_ms)

        if rec.packet_loss_pct is not None and 0.0 <= rec.packet_loss_pct <= 100.0:
            bucket.packet_losses_pct.append(rec.packet_loss_pct)

    # Sort deterministically by position label
    ordered_keys = sorted(grouped.keys())
    return [grouped[k] for k in ordered_keys]


def rank_from_raw_records(
    records: Sequence[RawMeasurementRecord],
    tie_threshold_pct: float = DEFAULT_TIE_THRESHOLD_PCT,
    required_repetitions: int = DEFAULT_REQUIRED_REPETITIONS,
) -> PlacementReport:
    """Aggregate raw CSV records by candidate position and produce a PlacementReport."""
    aggregated = aggregate_raw_records(records)
    return rank_positions(
        aggregated,
        tie_threshold_pct=tie_threshold_pct,
        required_repetitions=required_repetitions,
    )


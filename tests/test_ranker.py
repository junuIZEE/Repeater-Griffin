"""Unit tests for placement ranking, tie-breaking, unavailable handling, and CSV persistence.

All numerical fixtures below are synthetic test inputs used strictly to verify
algorithmic correctness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from placement.ranker import (
    PositionMeasurements,
    evaluate_position,
    rank_from_raw_records,
    rank_positions,
)
from storage.csv_handler import (
    RawMeasurementRecord,
    append_raw_measurement,
    append_raw_measurements,
    load_raw_measurements,
)


def test_median_used_instead_of_mean_and_bottleneck_score() -> None:
    # Mean upload would be (10 + 12 + 90)/3 = 37.33, while median is 12.0.
    pos = PositionMeasurements(
        candidate_position="P1",
        upload_throughputs_mbps=[10.0, 12.0, 90.0],
        download_throughputs_mbps=[30.0, 32.0, 35.0],
        rtts_ms=[15.0, 14.0, 16.0],
        packet_losses_pct=[0.0, 0.0, 0.0],
    )
    ev = evaluate_position(pos)
    assert ev.is_available is True
    assert ev.median_upload_mbps == pytest.approx(12.0)
    assert ev.median_download_mbps == pytest.approx(32.0)
    assert ev.score_mbps == pytest.approx(12.0)  # min(12.0, 32.0)
    assert ev.median_rtt_ms == pytest.approx(15.0)
    assert ev.median_packet_loss_pct == pytest.approx(0.0)


def test_ranking_descending_order_without_tie() -> None:
    # Synthetic positions separated by more than 5%.
    p1 = PositionMeasurements("P1", [40.0, 42.0, 41.0], [50.0, 52.0, 51.0], [8.0, 9.0, 10.0], [0.0])
    p2 = PositionMeasurements("P2", [55.0, 54.0, 56.0], [60.0, 62.0, 61.0], [20.0, 21.0, 22.0], [0.0])
    p3 = PositionMeasurements("P3", [25.0, 26.0, 27.0], [18.0, 19.0, 20.0], [5.0, 6.0, 5.5], [10.0])

    report = rank_positions([p1, p2, p3])
    assert [p.candidate_position for p in report.ranked_positions] == ["P2", "P1", "P3"]
    assert [p.rank for p in report.ranked_positions] == [1, 2, 3]
    assert report.best_position is not None
    assert report.best_position.candidate_position == "P2"
    assert report.best_position.score_mbps == pytest.approx(55.0)
    assert report.ranked_positions[2].median_packet_loss_pct == pytest.approx(10.0)


def test_five_percent_tie_broken_by_lower_median_rtt() -> None:
    # P1 score = 100.0 Mbps (median RTT 32.0 ms)
    # P2 score = 96.0 Mbps (within 5% of 100.0 -> 4% diff), median RTT 11.0 ms -> P2 must win!
    # P3 score = 88.0 Mbps (12% below 100.0 -> not tied), median RTT 5.0 ms -> Rank 3.
    p1 = PositionMeasurements("P1", [100.0, 100.0, 100.0], [120.0, 120.0, 120.0], [32.0, 31.0, 33.0], [0.0])
    p2 = PositionMeasurements("P2", [96.0, 96.0, 96.0], [110.0, 110.0, 110.0], [11.0, 10.0, 12.0], [0.0])
    p3 = PositionMeasurements("P3", [88.0, 88.0, 88.0], [95.0, 95.0, 95.0], [5.0, 5.0, 5.0], [0.0])

    report = rank_positions([p1, p2, p3], tie_threshold_pct=5.0)
    ordered = [p.candidate_position for p in report.ranked_positions]
    assert ordered == ["P2", "P1", "P3"]
    assert report.best_position is not None
    assert report.best_position.candidate_position == "P2"
    assert report.best_position.tie_broken_by_rtt is True
    assert report.ranked_positions[1].tie_broken_by_rtt is True
    assert report.ranked_positions[2].tie_broken_by_rtt is False


def test_outside_five_percent_does_not_tie_break() -> None:
    # 94.0 vs 100.0 is a 6.0% difference -> P1 stays Rank 1 despite higher RTT.
    p1 = PositionMeasurements("P1", [100.0, 100.0, 100.0], [100.0, 100.0, 100.0], [40.0], [0.0])
    p2 = PositionMeasurements("P2", [94.0, 94.0, 94.0], [94.0, 94.0, 94.0], [5.0], [0.0])

    report = rank_positions([p1, p2], tie_threshold_pct=5.0)
    assert [p.candidate_position for p in report.ranked_positions] == ["P1", "P2"]
    assert report.best_position is not None
    assert report.best_position.tie_broken_by_rtt is False


def test_unavailable_and_disconnected_positions() -> None:
    p_ok = PositionMeasurements("P1", [30.0, 31.0, 29.0], [40.0, 41.0, 39.0], [12.0], [0.0])
    p_disc = PositionMeasurements("P2", [50.0], [50.0], [5.0], [100.0], disconnected=True)
    p_no_down = PositionMeasurements("P3", [35.0, 36.0, 34.0], [], [14.0], [20.0])

    report = rank_positions([p_disc, p_no_down, p_ok])
    assert report.best_position is not None
    assert report.best_position.candidate_position == "P1"
    assert report.best_position.rank == 1

    by_name = {p.candidate_position: p for p in report.ranked_positions}
    assert by_name["P2"].is_available is False
    assert by_name["P2"].rank is None
    assert by_name["P2"].status == "unavailable"
    assert by_name["P2"].median_packet_loss_pct == pytest.approx(100.0)

    assert by_name["P3"].is_available is False
    assert by_name["P3"].rank is None
    assert by_name["P3"].median_packet_loss_pct == pytest.approx(20.0)


def test_all_unavailable_positions_returns_no_best() -> None:
    p1 = PositionMeasurements("P1", [], [], [], [100.0], disconnected=True)
    p2 = PositionMeasurements("P2", [0.0, 0.0], [0.0, 0.0], [], [100.0])

    report = rank_positions([p1, p2])
    assert report.best_position is None
    assert "No usable candidate position" in report.recommendation_text


def test_recommendation_scope_never_claims_global_optimality() -> None:
    p1 = PositionMeasurements("P1", [25.0, 26.0, 27.0], [30.0, 31.0, 29.0], [10.0], [0.0])
    p2 = PositionMeasurements("P2", [15.0, 16.0, 17.0], [20.0, 21.0, 19.0], [12.0], [0.0])

    report = rank_positions([p1, p2])
    text = report.recommendation_text.lower()
    assert "does not claim global optimality" in text
    assert "p1" in text and "p2" in text


def test_csv_append_does_not_overwrite_and_ranks_loaded_records(tmp_path: Path) -> None:
    csv_file = tmp_path / "raw_measurements.csv"

    batch_1 = [
        RawMeasurementRecord("P1", "upload", "success", 1, upload_throughput_mbps=20.0),
        RawMeasurementRecord("P1", "upload", "success", 2, upload_throughput_mbps=22.0),
        RawMeasurementRecord("P1", "upload", "success", 3, upload_throughput_mbps=24.0),
        RawMeasurementRecord("P1", "download", "success", 1, download_throughput_mbps=30.0),
        RawMeasurementRecord("P1", "download", "success", 2, download_throughput_mbps=31.0),
        RawMeasurementRecord("P1", "download", "success", 3, download_throughput_mbps=32.0),
        RawMeasurementRecord("P1", "ping", "success", 1, rtt_ms=14.0, packet_loss_pct=0.0),
    ]
    append_raw_measurements(csv_file, batch_1)

    batch_2 = [
        RawMeasurementRecord("P2", "upload", "success", 1, upload_throughput_mbps=35.0),
        RawMeasurementRecord("P2", "upload", "success", 2, upload_throughput_mbps=36.0),
        RawMeasurementRecord("P2", "upload", "success", 3, upload_throughput_mbps=37.0),
        RawMeasurementRecord("P2", "download", "success", 1, download_throughput_mbps=40.0),
        RawMeasurementRecord("P2", "download", "success", 2, download_throughput_mbps=41.0),
        RawMeasurementRecord("P2", "download", "success", 3, download_throughput_mbps=42.0),
        RawMeasurementRecord("P2", "ping", "success", 1, rtt_ms=9.0, packet_loss_pct=5.0),
    ]
    append_raw_measurements(csv_file, batch_2)
    append_raw_measurement(
        csv_file,
        RawMeasurementRecord("P3", "ping", "disconnected", 1, rtt_ms=None, packet_loss_pct=100.0),
    )

    loaded = load_raw_measurements(csv_file)
    assert len(loaded) == len(batch_1) + len(batch_2) + 1

    report = rank_from_raw_records(loaded)
    assert report.best_position is not None
    assert report.best_position.candidate_position == "P2"
    assert report.best_position.score_mbps == pytest.approx(36.0)
    assert report.best_position.median_packet_loss_pct == pytest.approx(5.0)

    by_name = {p.candidate_position: p for p in report.ranked_positions}
    assert by_name["P3"].is_available is False


def test_charts_save_all_outputs_with_synthetic_data(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from dashboard.charts import save_all_charts

    p1 = PositionMeasurements("P1", [32.0, 33.0, 34.0], [45.0, 46.0, 47.0], [11.0], [0.0])
    p2 = PositionMeasurements("P2", [31.0, 32.0, 32.5], [40.0, 41.0, 42.0], [25.0], [5.0])
    p3 = PositionMeasurements("P3", [], [], [], [100.0], disconnected=True)

    report = rank_positions([p1, p2, p3])
    saved = save_all_charts(report, tmp_path)
    assert set(saved.keys()) == {"upload", "download", "rtt", "ranking"}
    for out_path in saved.values():
        assert out_path.exists()
        assert out_path.stat().st_size > 0

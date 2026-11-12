"""Main Tkinter desktop dashboard for Repeater Griffin."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Optional

from dashboard.charts import (
    MATPLOTLIB_AVAILABLE,
    build_ranking_figure,
    build_rtt_figure,
    build_throughput_figure,
    save_all_charts,
)
from dashboard.components import (
    ConfigFrame,
    HotspotStatusFrame,
    LatestResultsFrame,
    LogPanel,
    MeasurementControlFrame,
    RankingTableFrame,
)
from hotspot.manager import HotspotManager
from measurement.runner import PositionExperimentResult, run_position_experiment
from placement.ranker import PlacementReport, rank_from_raw_records
from storage.csv_handler import (
    RawMeasurementRecord,
    append_processed_summary,
    append_raw_measurement,
    load_raw_measurements,
)
from utils.config import AppSettings, load_settings, save_settings
from utils.logger import get_logger

if MATPLOTLIB_AVAILABLE:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
else:  # pragma: no cover
    FigureCanvasTkAgg = None  # type: ignore[misc,assignment]

logger = get_logger(__name__)


class RepeaterGriffinApp:
    """Tkinter GUI application coordinating hotspot checks, measurements, and ranking."""

    def __init__(
        self,
        root: tk.Tk,
        settings: Optional[AppSettings] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self.root = root
        self.config_path = config_path
        self.settings = settings or load_settings(config_path)
        self.settings.ensure_directories()

        self.hotspot_manager = HotspotManager()
        self._event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._latest_report: Optional[PlacementReport] = None
        self._chart_canvases: dict[str, Any] = {}

        self.root.title("Repeater Griffin")
        self.root.geometry("1100x860")
        self.root.minsize(920, 720)

        self._build_layout()
        self._populate_config_inputs()
        self.refresh_hotspot_status()
        self.reload_csv_and_rank(save_charts=False)
        self._poll_events()

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill="both", expand=True)

        header = ttk.Label(
            container,
            text="Repeater Griffin — Performance-Guided Wi-Fi Repeater Placement",
            font=("Segoe UI", 13, "bold"),
        )
        header.pack(anchor="w", pady=(0, 8))

        self.config_frame = ConfigFrame(container, on_save=self._on_save_config)
        self.config_frame.pack(fill="x", pady=(0, 6))

        self.hotspot_frame = HotspotStatusFrame(
            container,
            on_refresh=self.refresh_hotspot_status,
            on_open_settings=self._on_open_hotspot_settings,
        )
        self.hotspot_frame.pack(fill="x", pady=(0, 6))

        self.control_frame = MeasurementControlFrame(
            container,
            positions=self.settings.placement.candidate_positions,
            on_start=self._on_start_measurement,
            on_cancel=self._on_cancel_measurement,
            on_mark_disconnected=self._on_mark_disconnected,
            on_reload_csv=lambda: self.reload_csv_and_rank(save_charts=True),
            on_save_graphs=self._on_save_graphs,
        )
        self.control_frame.pack(fill="x", pady=(0, 6))

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True, pady=(0, 6))

        results_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(results_tab, text="Measurements & Placement Ranking")

        self.latest_results_frame = LatestResultsFrame(results_tab)
        self.latest_results_frame.pack(fill="x", pady=(0, 6))

        self.ranking_frame = RankingTableFrame(results_tab)
        self.ranking_frame.pack(fill="both", expand=True)

        charts_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(charts_tab, text="Comparison Graphs")
        self._chart_notebook = ttk.Notebook(charts_tab)
        self._chart_notebook.pack(fill="both", expand=True)

        self._chart_frames: dict[str, ttk.Frame] = {}
        for key, title in (
            ("ranking", "Placement Ranking"),
            ("upload", "Upload Throughput"),
            ("download", "Download Throughput"),
            ("rtt", "RTT Comparison"),
        ):
            frame = ttk.Frame(self._chart_notebook)
            self._chart_notebook.add(frame, text=title)
            self._chart_frames[key] = frame

        self.log_panel = LogPanel(container)
        self.log_panel.pack(fill="x")

    def _populate_config_inputs(self) -> None:
        self.config_frame.set_values(
            server_ip=self.settings.iperf3.server_ip,
            port=self.settings.iperf3.port,
            duration_sec=self.settings.iperf3.duration_sec,
            repetitions=self.settings.iperf3.repetitions,
            ping_target=self.settings.ping.target,
        )

    def _apply_config_from_ui(self) -> bool:
        try:
            server_ip = self.config_frame.server_ip_var.get().strip()
            ping_target = self.config_frame.ping_target_var.get().strip() or server_ip
            port = int(self.config_frame.port_var.get().strip())
            duration = int(self.config_frame.duration_var.get().strip())
            reps = int(self.config_frame.repetitions_var.get().strip())
            if not server_ip:
                raise ValueError("iperf3 Server IP cannot be empty.")
            if not (1 <= port <= 65535):
                raise ValueError("Port must be between 1 and 65535.")
            if duration <= 0 or reps <= 0:
                raise ValueError("Duration and repetitions must be positive integers.")
        except ValueError as exc:
            messagebox.showerror("Invalid Configuration", str(exc))
            return False

        self.settings.iperf3.server_ip = server_ip
        self.settings.iperf3.port = port
        self.settings.iperf3.duration_sec = duration
        self.settings.iperf3.repetitions = reps
        self.settings.ping.target = ping_target
        return True

    def _on_save_config(self) -> None:
        if not self._apply_config_from_ui():
            return
        saved_path = save_settings(self.settings, self.config_path)
        self.log_panel.append_line(f"Saved configuration to {saved_path}")

    def refresh_hotspot_status(self) -> None:
        status = self.hotspot_manager.get_status()
        self.hotspot_frame.update_status(status)
        self.log_panel.append_line(f"Hotspot check: {status.state} — {status.summary}")

    def _on_open_hotspot_settings(self) -> None:
        opened, msg = self.hotspot_manager.open_settings()
        self.log_panel.append_line(msg)
        if not opened:
            messagebox.showinfo("Windows Hotspot Settings", msg)

    def _on_start_measurement(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        if not self._apply_config_from_ui():
            return

        position = self.control_frame.position_var.get().strip()
        if not position:
            messagebox.showwarning("Missing Position", "Select or enter a candidate position.")
            return

        self._cancel_event.clear()
        self.latest_results_frame.clear_rows()
        self.latest_results_frame.summary_var.set(
            f"Running measurement at {position} (target {self.settings.iperf3.server_ip}:{self.settings.iperf3.port})..."
        )
        self.control_frame.set_running(True)
        self.control_frame.update_progress(0, 1, f"Starting {position}...")
        self.log_panel.append_line(f"Started experiment for candidate position {position}.")

        self._worker_thread = threading.Thread(
            target=self._measurement_worker,
            args=(position,),
            daemon=True,
        )
        self._worker_thread.start()

    def _on_cancel_measurement(self) -> None:
        self._cancel_event.set()
        self.control_frame.status_var.set("Cancelling after current step...")
        self.log_panel.append_line("Cancellation requested by user.")

    def _on_mark_disconnected(self) -> None:
        position = self.control_frame.position_var.get().strip()
        if not position:
            return
        confirm = messagebox.askyesno(
            "Mark Position Unavailable",
            f"Record candidate position '{position}' as disconnected / unavailable in CSV?",
        )
        if not confirm:
            return
        record = RawMeasurementRecord(
            candidate_position=position,
            test_direction="ping",
            test_status="disconnected",
            repetition=1,
            rtt_ms=None,
            packet_loss_pct=100.0,
            server_ip=self.settings.iperf3.server_ip,
            ping_target=self.settings.ping.target,
            error_message="Marked disconnected/unavailable by user.",
        )
        append_raw_measurement(self.settings.raw_csv_path, record)
        self.log_panel.append_line(f"Recorded {position} as disconnected in CSV.")
        self.reload_csv_and_rank(save_charts=True)

    def _measurement_worker(self, position: str) -> None:
        def on_progress(step: int, total: int, message: str) -> None:
            self._event_queue.put(("progress", (step, total, message)))

        try:
            exp_result = run_position_experiment(
                candidate_position=position,
                settings=self.settings,
                progress_callback=on_progress,
                cancel_event=self._cancel_event,
            )
            self._event_queue.put(("completed", exp_result))
        except Exception as exc:  # pragma: no cover - defensive UI worker guard
            logger.exception("Measurement worker failed")
            self._event_queue.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                event_type, payload = self._event_queue.get_nowait()
                if event_type == "progress":
                    step, total, message = payload
                    self.control_frame.update_progress(step, total, message)
                    self.log_panel.append_line(message)
                elif event_type == "completed":
                    self._handle_experiment_completed(payload)
                elif event_type == "error":
                    self.control_frame.set_running(False)
                    self.control_frame.update_progress(0, 1, "Measurement failed.")
                    self.log_panel.append_line(f"ERROR: {payload}")
                    messagebox.showerror("Measurement Error", str(payload))
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _handle_experiment_completed(self, result: PositionExperimentResult) -> None:
        self.control_frame.set_running(False)
        self.latest_results_frame.clear_rows()

        for idx, up in enumerate(result.upload_results, start=1):
            self.latest_results_frame.add_row(
                idx, "Upload", up.throughput_mbps, None, None, up.status
            )
        for idx, down in enumerate(result.download_results, start=1):
            self.latest_results_frame.add_row(
                idx, "Download", down.throughput_mbps, None, None, down.status
            )
        if result.latency_result is not None and result.packet_loss_result is not None:
            lat = result.latency_result
            loss = result.packet_loss_result
            self.latest_results_frame.add_row(
                1,
                "Ping",
                None,
                lat.median_rtt_ms,
                loss.packet_loss_pct,
                lat.status,
            )
            rtt_text = f"{lat.median_rtt_ms:.2f} ms" if lat.median_rtt_ms is not None else "N/A"
            self.latest_results_frame.summary_var.set(
                f"{result.candidate_position}: Median RTT = {rtt_text}, "
                f"Packet Loss = {loss.packet_loss_pct:.2f}% "
                f"({len(result.upload_results)} upload, {len(result.download_results)} download runs)."
            )

        if result.cancelled:
            self.control_frame.update_progress(0, 1, "Measurement cancelled.")
        else:
            self.control_frame.update_progress(1, 1, f"{result.candidate_position} complete.")

        self.reload_csv_and_rank(save_charts=True)

    def reload_csv_and_rank(self, save_charts: bool = False) -> None:
        records = load_raw_measurements(self.settings.raw_csv_path)
        if not records:
            self.log_panel.append_line(
                f"No raw measurements found yet at {self.settings.raw_csv_path}."
            )
            return

        report = rank_from_raw_records(
            records,
            tie_threshold_pct=self.settings.placement.tie_threshold_pct,
            required_repetitions=self.settings.iperf3.repetitions,
        )
        self._latest_report = report
        self.ranking_frame.update_report(report)
        append_processed_summary(self.settings.summary_csv_path, report.ranked_positions)
        self._render_embedded_charts(report)

        if save_charts and MATPLOTLIB_AVAILABLE:
            saved = save_all_charts(report, self.settings.graphs_path)
            self.log_panel.append_line(
                f"Updated ranking and saved {len(saved)} graph(s) to {self.settings.graphs_path}."
            )

    def _on_save_graphs(self) -> None:
        if self._latest_report is None:
            messagebox.showinfo("No Data", "Run measurements or load a CSV before saving graphs.")
            return
        if not MATPLOTLIB_AVAILABLE:
            messagebox.showerror(
                "Matplotlib Unavailable",
                "matplotlib is not installed. Run: pip install matplotlib",
            )
            return
        saved = save_all_charts(self._latest_report, self.settings.graphs_path)
        msg = "Saved graphs:\n" + "\n".join(str(p) for p in saved.values())
        self.log_panel.append_line(f"Saved graphs to {self.settings.graphs_path}")
        messagebox.showinfo("Graphs Saved", msg)

    def _render_embedded_charts(self, report: PlacementReport) -> None:
        if not MATPLOTLIB_AVAILABLE or FigureCanvasTkAgg is None:
            return

        figures = {
            "ranking": build_ranking_figure(report, figsize=(7.5, 3.8)),
            "upload": build_throughput_figure(report, direction="upload", figsize=(7.5, 3.8)),
            "download": build_throughput_figure(report, direction="download", figsize=(7.5, 3.8)),
            "rtt": build_rtt_figure(report, figsize=(7.5, 3.8)),
        }

        for key, fig in figures.items():
            frame = self._chart_frames[key]
            for child in frame.winfo_children():
                child.destroy()
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self._chart_canvases[key] = canvas


def launch_dashboard(
    settings: Optional[AppSettings] = None,
    config_path: Optional[Path] = None,
) -> None:
    """Create the Tk root window and start the Repeater Griffin event loop."""
    root = tk.Tk()
    RepeaterGriffinApp(root, settings=settings, config_path=config_path)
    root.mainloop()


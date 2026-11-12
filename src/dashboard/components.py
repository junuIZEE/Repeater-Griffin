"""Reusable Tkinter UI components for the Repeater Griffin dashboard."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional, Sequence

from hotspot.manager import HotspotStatus
from placement.ranker import PlacementReport


class ConfigFrame(ttk.LabelFrame):
    """Configuration panel for iperf3 server, ping target, and test parameters."""

    def __init__(
        self,
        parent: tk.Widget,
        on_save: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, text="Test Configuration", padding=8)
        self._on_save = on_save

        self.server_ip_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.duration_var = tk.StringVar()
        self.repetitions_var = tk.StringVar()
        self.ping_target_var = tk.StringVar()

        fields = [
            ("iperf3 Server IP:", self.server_ip_var, 16),
            ("Port:", self.port_var, 7),
            ("Duration (s):", self.duration_var, 6),
            ("Repetitions:", self.repetitions_var, 5),
            ("Ping Target IP:", self.ping_target_var, 16),
        ]

        for col_idx, (label_text, var, width) in enumerate(fields):
            base_col = col_idx * 2
            ttk.Label(self, text=label_text).grid(
                row=0, column=base_col, sticky="w", padx=(0, 4), pady=2
            )
            ttk.Entry(self, textvariable=var, width=width).grid(
                row=0, column=base_col + 1, sticky="w", padx=(0, 10), pady=2
            )

        ttk.Button(self, text="Save Config", command=self._handle_save).grid(
            row=0, column=len(fields) * 2, sticky="e", padx=(4, 0), pady=2
        )

    def _handle_save(self) -> None:
        if self._on_save is not None:
            self._on_save()

    def set_values(
        self,
        server_ip: str,
        port: int,
        duration_sec: int,
        repetitions: int,
        ping_target: str,
    ) -> None:
        self.server_ip_var.set(server_ip)
        self.port_var.set(str(port))
        self.duration_var.set(str(duration_sec))
        self.repetitions_var.set(str(repetitions))
        self.ping_target_var.set(ping_target)


class HotspotStatusFrame(ttk.LabelFrame):
    """Panel showing Windows Mobile Hotspot state, adapter details, and controls."""

    def __init__(
        self,
        parent: tk.Widget,
        on_refresh: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, text="Windows Mobile Hotspot Status", padding=8)
        self._on_refresh = on_refresh
        self._on_open_settings = on_open_settings
        self._instructions = ""

        self.state_var = tk.StringVar(value="State: Checking...")
        self.detail_var = tk.StringVar(value="")

        self.state_label = ttk.Label(
            self,
            textvariable=self.state_var,
            font=("Segoe UI", 10, "bold"),
        )
        self.state_label.grid(row=0, column=0, sticky="w", padx=(0, 12))

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=0, column=1, sticky="e")
        ttk.Button(btn_frame, text="Refresh Status", command=self._handle_refresh).pack(
            side="left", padx=3
        )
        ttk.Button(
            btn_frame, text="Open Hotspot Settings", command=self._handle_open_settings
        ).pack(side="left", padx=3)
        ttk.Button(
            btn_frame, text="Setup Instructions", command=self._show_instructions
        ).pack(side="left", padx=3)

        ttk.Label(self, textvariable=self.detail_var, wraplength=820).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self.columnconfigure(0, weight=1)

    def _handle_refresh(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    def _handle_open_settings(self) -> None:
        if self._on_open_settings is not None:
            self._on_open_settings()

    def _show_instructions(self) -> None:
        messagebox.showinfo(
            "Windows Mobile Hotspot Instructions",
            self._instructions
            or "Open Windows Settings > Network & internet > Mobile hotspot and turn it On.",
        )

    def update_status(self, status: HotspotStatus) -> None:
        self._instructions = status.instructions
        state_display = status.state.replace("_", " ").title()
        self.state_var.set(f"Hotspot State: {state_display}")

        adapter_text = ""
        if status.hotspot_adapter is not None:
            ips = ", ".join(status.hotspot_adapter.ipv4_addresses) or "no IPv4"
            adapter_text = (
                f" | Hotspot Adapter: {status.hotspot_adapter.name} "
                f"({status.hotspot_adapter.status}, {ips})"
            )
        self.detail_var.set(f"{status.summary}{adapter_text}")


class MeasurementControlFrame(ttk.LabelFrame):
    """Candidate position selection, start/cancel buttons, and progress bar."""

    def __init__(
        self,
        parent: tk.Widget,
        positions: Sequence[str],
        on_start: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_mark_disconnected: Optional[Callable[[], None]] = None,
        on_reload_csv: Optional[Callable[[], None]] = None,
        on_save_graphs: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent, text="Experiment Control", padding=8)
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._on_mark_disconnected = on_mark_disconnected
        self._on_reload_csv = on_reload_csv
        self._on_save_graphs = on_save_graphs

        self.position_var = tk.StringVar(value=positions[0] if positions else "P1")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Idle — ready to measure.")

        top_row = ttk.Frame(self)
        top_row.pack(fill="x", expand=True)

        ttk.Label(top_row, text="Candidate Position:").pack(side="left", padx=(0, 6))
        self.position_combo = ttk.Combobox(
            top_row,
            textvariable=self.position_var,
            values=list(positions),
            width=10,
        )
        self.position_combo.pack(side="left", padx=(0, 12))

        self.start_btn = ttk.Button(
            top_row, text="Start Measurement", command=self._handle_start
        )
        self.start_btn.pack(side="left", padx=3)

        self.cancel_btn = ttk.Button(
            top_row, text="Cancel", command=self._handle_cancel, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=3)

        self.disconnected_btn = ttk.Button(
            top_row,
            text="Mark Unavailable / Disconnected",
            command=self._handle_disconnected,
        )
        self.disconnected_btn.pack(side="left", padx=3)

        ttk.Button(
            top_row, text="Load CSV & Re-Rank", command=self._handle_reload
        ).pack(side="right", padx=3)

        ttk.Button(
            top_row, text="Save Graphs", command=self._handle_save_graphs
        ).pack(side="right", padx=3)

        prog_row = ttk.Frame(self)
        prog_row.pack(fill="x", expand=True, pady=(6, 0))
        self.progress_bar = ttk.Progressbar(
            prog_row,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(prog_row, textvariable=self.status_var, width=52).pack(side="right")

    def _handle_start(self) -> None:
        if self._on_start is not None:
            self._on_start()

    def _handle_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()

    def _handle_disconnected(self) -> None:
        if self._on_mark_disconnected is not None:
            self._on_mark_disconnected()

    def _handle_reload(self) -> None:
        if self._on_reload_csv is not None:
            self._on_reload_csv()

    def _handle_save_graphs(self) -> None:
        if self._on_save_graphs is not None:
            self._on_save_graphs()

    def set_running(self, running: bool) -> None:
        self.start_btn.config(state="disabled" if running else "normal")
        self.disconnected_btn.config(state="disabled" if running else "normal")
        self.position_combo.config(state="disabled" if running else "normal")
        self.cancel_btn.config(state="normal" if running else "disabled")

    def update_progress(self, step: int, total: int, message: str) -> None:
        pct = (step / total) * 100.0 if total > 0 else 0.0
        self.progress_var.set(min(100.0, max(0.0, pct)))
        self.status_var.set(message)


class LatestResultsFrame(ttk.LabelFrame):
    """Displays latest throughput runs, median RTT, and packet loss."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Latest Position Measurement Results", padding=8)
        self.summary_var = tk.StringVar(
            value="No active trial measured yet. Select a position and click Start Measurement."
        )
        ttk.Label(self, textvariable=self.summary_var, wraplength=860).pack(
            anchor="w", pady=(0, 4)
        )

        columns = ("repetition", "direction", "throughput_mbps", "rtt_ms", "packet_loss_pct", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=5)
        headings = {
            "repetition": ("Rep", 55),
            "direction": ("Test Type", 100),
            "throughput_mbps": ("Throughput (Mbps)", 140),
            "rtt_ms": ("Median RTT (ms)", 130),
            "packet_loss_pct": ("Packet Loss (%)", 120),
            "status": ("Status", 180),
        }
        for col_id, (label, width) in headings.items():
            self.tree.heading(col_id, text=label)
            self.tree.column(col_id, width=width, anchor="center")

        self.tree.pack(fill="x", expand=True)

    def clear_rows(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def add_row(
        self,
        repetition: int,
        direction: str,
        throughput_mbps: Optional[float],
        rtt_ms: Optional[float],
        packet_loss_pct: Optional[float],
        status: str,
    ) -> None:
        self.tree.insert(
            "",
            "end",
            values=(
                repetition,
                direction,
                f"{throughput_mbps:.2f}" if throughput_mbps is not None else "-",
                f"{rtt_ms:.2f}" if rtt_ms is not None else "-",
                f"{packet_loss_pct:.2f}" if packet_loss_pct is not None else "-",
                status,
            ),
        )


class RankingTableFrame(ttk.LabelFrame):
    """Placement ranking table and best-tested-position recommendation banner."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Placement Ranking & Recommendation", padding=8)

        self.best_var = tk.StringVar(
            value="Best Tested Position: Pending measurements."
        )
        self.best_label = ttk.Label(
            self,
            textvariable=self.best_var,
            font=("Segoe UI", 10, "bold"),
            wraplength=900,
        )
        self.best_label.pack(anchor="w", pady=(0, 6))

        columns = (
            "rank",
            "position",
            "median_up",
            "median_down",
            "score",
            "median_rtt",
            "packet_loss",
            "runs",
            "status",
            "notes",
        )
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=6)
        headings = {
            "rank": ("Rank", 50),
            "position": ("Pos", 55),
            "median_up": ("Med Up (Mbps)", 105),
            "median_down": ("Med Down (Mbps)", 115),
            "score": ("Score (Mbps)", 100),
            "median_rtt": ("Med RTT (ms)", 95),
            "packet_loss": ("Loss (%)", 75),
            "runs": ("Up/Down/Ping", 95),
            "status": ("Status", 90),
            "notes": ("Notes", 240),
        }
        for col_id, (label, width) in headings.items():
            self.tree.heading(col_id, text=label)
            anchor = "w" if col_id == "notes" else "center"
            self.tree.column(col_id, width=width, anchor=anchor)

        self.tree.pack(fill="both", expand=True)

    def update_report(self, report: PlacementReport) -> None:
        self.best_var.set(report.recommendation_text)
        for item in self.tree.get_children():
            self.tree.delete(item)

        for ev in report.ranked_positions:
            self.tree.insert(
                "",
                "end",
                values=(
                    f"#{ev.rank}" if ev.rank is not None else "-",
                    ev.candidate_position,
                    f"{ev.median_upload_mbps:.2f}" if ev.median_upload_mbps is not None else "-",
                    f"{ev.median_download_mbps:.2f}" if ev.median_download_mbps is not None else "-",
                    f"{ev.score_mbps:.2f}" if ev.score_mbps is not None else "-",
                    f"{ev.median_rtt_ms:.2f}" if ev.median_rtt_ms is not None else "-",
                    f"{ev.median_packet_loss_pct:.2f}"
                    if ev.median_packet_loss_pct is not None
                    else "-",
                    f"{ev.upload_run_count}/{ev.download_run_count}/{ev.ping_run_count}",
                    ev.status,
                    ev.notes,
                ),
            )


class LogPanel(ttk.LabelFrame):
    """Scrollable status/event log panel."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Activity Log", padding=6)
        self.text = scrolledtext.ScrolledText(self, height=5, state="disabled", wrap="word")
        self.text.pack(fill="both", expand=True)

    def append_line(self, message: str) -> None:
        self.text.config(state="normal")
        self.text.insert("end", f"{message}\n")
        self.text.see("end")
        self.text.config(state="disabled")


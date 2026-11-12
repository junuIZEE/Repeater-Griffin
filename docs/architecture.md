# Repeater Griffin — System Architecture

## 1. End-to-End Network Path

Repeater Griffin evaluates candidate placements for a Windows 11 laptop acting as a wireless repeater via Windows Mobile Hotspot:

```
[Ethernet Server (iperf3 -s)]
        │  (Wired Ethernet)
        ▼
[Wi-Fi Router / Access Point]
        │  (Upstream Wi-Fi link)
        ▼
[Windows 11 Repeater Laptop]  <-- Candidate Position P1..P6
        │  (Windows Mobile Hotspot / Wi-Fi Direct Virtual Adapter)
        ▼
[Test Client Laptop]          <-- Runs Repeater Griffin (iperf3 -c, ping)
```

Because end-to-end client performance depends on **both** the upstream link (Router ↔ Repeater Laptop) and the downstream hotspot link (Repeater Laptop ↔ Client), measuring RSSI at the repeater laptop alone is insufficient. Repeater Griffin measures the complete path using active TCP throughput, RTT, and packet-loss probes.

## 2. Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `src/utils/config.py` | Loads/saves `config/settings.json` into typed dataclasses (`AppSettings`) and resolves output paths via `pathlib.Path`. |
| `src/utils/logger.py` | Configures console and file logging under `results/reports/`. |
| `src/hotspot/manager.py` | Read-only inspection of Windows 11 Mobile Hotspot via WinRT `NetworkOperatorTetheringManager` and `Get-NetAdapter`, plus `ms-settings:network-mobilehotspot` launcher and manual instructions. |
| `src/measurement/throughput.py` | Runs `iperf3 -c <server> -p <port> -t <duration> -J` (and `-R` for download) via `subprocess.run`, parses JSON, returns `ThroughputResult` in Mbps. |
| `src/measurement/latency.py` | Executes Windows `ping -n <count> -w <timeout_ms> <target>`, extracts per-packet RTTs (`time=XXms`, `time<1ms`), computes median RTT, and classifies timeouts/unreachable hosts. |
| `src/measurement/packet_loss.py` | Parses ping summary/reply lines to calculate numeric packet-loss percentages and reuses `LatencyResult` so `ping` is never executed twice per trial. |
| `src/measurement/runner.py` | Coordinates `N` upload runs, `N` download runs, and 1 ping test per candidate position, appending each record immediately to CSV with cancellation and progress callbacks. |
| `src/storage/csv_handler.py` | Appends raw measurements (`data/raw/raw_measurements.csv`) and processed summaries (`data/processed/placement_summaries.csv`) without overwriting existing records. |
| `src/placement/ranker.py` | Aggregates per-position measurements, computes median upload/download throughput and `score = min(median_upload, median_download)`, applies the 5% RTT tie-breaker, marks disconnected/incomplete positions unavailable, and preserves packet loss. |
| `src/dashboard/charts.py` | Generates four Matplotlib comparison charts (Upload, Download, RTT, Placement Ranking) for Tkinter embedding and PNG export under `results/graphs/`. |
| `src/dashboard/components.py` & `app.py` | Tkinter desktop UI running long measurements on background `threading.Thread` workers and dispatching updates via `queue.Queue` + `root.after()`. |

## 3. Ranking & Tie-Breaking Rules

For each candidate position $P_i$:

1. Collect $k=3$ upload and $k=3$ download throughput measurements.
2. Compute $\text{median\_upload}_i$ and $\text{median\_download}_i$ (resistant to single-run spikes).
3. Compute bottleneck score:
   $$\text{score}_i = \min(\text{median\_upload}_i, \text{median\_download}_i)$$
4. Positions with missing upload/download measurements, zero/non-positive scores, or marked `disconnected` are classified as `unavailable` and excluded from numeric ranks.
5. Available positions are sorted descending by $\text{score}_i$. Positions within `tie_threshold_pct` (default `5.0%`) of a tie-group leader's score are grouped and ordered by lower median RTT ($\text{median\_rtt}_i$), with lower median packet loss as secondary tie-breaker.
6. Recommendations explicitly apply **only** to the candidate positions evaluated and never claim global optimality.


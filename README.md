# Repeater-Griffin

**Repeater Griffin: Network Range Extender with Performance-Guided Placement**

Repeater Griffin is a Computer Networks semester project targeting Windows 11. It evaluates 4–6 candidate placements for a Windows laptop acting as a Wi-Fi range extender (via built-in Windows Mobile Hotspot) by measuring end-to-end network performance along the full path:

`Router → Repeater Laptop (Wi-Fi) → Windows Mobile Hotspot → Client`

Rather than relying on upstream RSSI alone, Repeater Griffin measures TCP upload/download throughput (`iperf3`), round-trip time (`ping`), and packet loss across repeated trials, persists raw experiment data to CSV, ranks tested candidate locations using bottleneck median throughput with RTT tie-breaking, and visualizes comparisons in a Tkinter + Matplotlib desktop dashboard.

---

## Repository Structure

```text
repeater-griffin/
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   └── settings.json
├── src/
│   ├── main.py
│   ├── hotspot/
│   │   ├── __init__.py
│   │   └── manager.py
│   ├── measurement/
│   │   ├── __init__.py
│   │   ├── throughput.py
│   │   ├── latency.py
│   │   ├── packet_loss.py
│   │   └── runner.py
│   ├── placement/
│   │   ├── __init__.py
│   │   └── ranker.py
│   ├── storage/
│   │   ├── __init__.py
│   │   └── csv_handler.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── charts.py
│   │   └── components.py
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       └── logger.py
├── tests/
│   ├── conftest.py
│   ├── test_throughput.py
│   ├── test_latency.py
│   └── test_ranker.py
├── data/
│   ├── raw/
│   └── processed/
├── results/
│   ├── graphs/
│   └── reports/
├── scripts/
│   ├── run_server.py
│   └── run_client.py
└── docs/
    ├── architecture.md
    └── experiment_setup.md
```

---

## Prerequisites (Windows 11)

1. **Python 3.10+** (with Tkinter enabled — included by default in the official Windows installer).
2. **iperf3** installed and available on `PATH` (or configure `iperf3.executable_path` in `config/settings.json`).
   - Windows builds are available from the official iperf3 distribution or `winget install iperf3`.
3. **Windows 11 Mobile Hotspot** on the repeater laptop (managed through Windows OS settings; no custom wireless driver is used).

---

## Installation

```powershell
git clone https://github.com/junuIZEE/Repeater-Griffin.git
cd Repeater-Griffin
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuration (`config/settings.json`)

Edit `config/settings.json` before starting experiments:

```json
{
  "app_name": "Repeater Griffin",
  "iperf3": {
    "server_ip": "192.168.1.100",
    "port": 5201,
    "duration_sec": 20,
    "repetitions": 3,
    "parallel_streams": 1,
    "executable_path": "iperf3",
    "timeout_buffer_sec": 15
  },
  "ping": {
    "target": "192.168.1.100",
    "packet_count": 10,
    "timeout_ms": 2000
  },
  "placement": {
    "candidate_positions": ["P1", "P2", "P3", "P4", "P5", "P6"],
    "tie_threshold_pct": 5.0
  },
  "paths": {
    "raw_data_dir": "data/raw",
    "processed_data_dir": "data/processed",
    "graphs_dir": "results/graphs",
    "reports_dir": "results/reports",
    "raw_csv_filename": "raw_measurements.csv",
    "summary_csv_filename": "placement_summaries.csv"
  }
}
```

---

## Exact Commands to Run

### 1. Start the `iperf3` Server (Ethernet-Connected Machine)

Using the helper script:
```powershell
python scripts/run_server.py --port 5201
```
Or directly with `iperf3`:
```powershell
iperf3 -s -p 5201
```

### 2. Launch the Desktop Dashboard (Client Machine)

```powershell
python src/main.py
```

### 3. Optional CLI Runner (Headless Experiments / Offline Re-Ranking)

Run measurements for a single candidate position:
```powershell
python scripts/run_client.py --position P1 --server 192.168.1.100
```

Recompute placement rankings and regenerate graphs from existing CSV measurements:
```powershell
python scripts/run_client.py --rank-only
```

### 4. Run Unit Tests

```powershell
pytest -v tests/
```

---

## Placement Ranking Logic

For each tested candidate position:
1. Collect 3 upload and 3 download `iperf3` measurements (20s each by default).
2. Compute `median_upload` and `median_download` (in Mbps).
3. Compute `score = min(median_upload, median_download)`.
4. Rank available positions in descending order of `score`.
5. If positions are within `5%` of a tie-group leader's score, break ties using lower median RTT (`ms`).
6. Mark disconnected or incomplete positions as `unavailable` and preserve packet-loss percentages for reporting.
7. Limit recommendations strictly to the tested candidate positions (no claim of global optimality).

---

## Documentation

- [System Architecture](docs/architecture.md)
- [Experiment Setup & Protocol](docs/experiment_setup.md)

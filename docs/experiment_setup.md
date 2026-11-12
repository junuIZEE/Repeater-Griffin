# Repeater Griffin — Experimental Setup & Protocol

## 1. Hardware & Network Topology

You need three devices on the same local testbed:

1. **Ethernet-Connected Server**: Desktop or laptop wired to the Wi-Fi router via Ethernet. Runs `iperf3 -s`.
2. **Repeater Laptop (Windows 11)**: Connects to the existing Wi-Fi router and enables **Windows Mobile Hotspot** to share that connection.
3. **Client Laptop (Windows 11)**: Connects wirelessly to the Repeater Laptop's Mobile Hotspot and runs the Repeater Griffin measurement dashboard (or CLI runner).

> **Important:** All throughput and ping measurements target the local Ethernet-connected `iperf3` server IP. Never point experiments at public internet speed-test servers.

## 2. Pre-Experiment Checklist

1. Verify `iperf3` is installed and accessible on both the Ethernet server and Client laptop (`iperf3 --version`).
2. Connect the Ethernet server to the router and note its LAN IPv4 address (e.g., `192.168.1.100`).
3. Ensure Windows Firewall on the Ethernet server allows incoming TCP traffic on port `5201` (or your configured port).
4. Start the `iperf3` server on the Ethernet machine:
   ```powershell
   python scripts/run_server.py --port 5201
   ```
5. Update `config/settings.json` (or use the Dashboard UI) with:
   - `iperf3.server_ip`: Ethernet server LAN IP
   - `ping.target`: Ethernet server LAN IP (or router IP if isolating upstream RTT)
   - `iperf3.duration_sec`: `20`
   - `iperf3.repetitions`: `3`
6. Mark 4–6 reproducible candidate laptop positions (`P1` through `P6`) with tape or floor markers (e.g., hallway, doorway, corner desk, stairwell landing, living room shelf).

## 3. Repeater Laptop Setup (Windows 11)

On the Repeater Laptop:

1. Connect to the upstream Wi-Fi router.
2. Open **Settings → Network & internet → Mobile hotspot** (or click **Open Hotspot Settings** in the app if running on the repeater).
3. Set **Share my Internet connection from** to **Wi-Fi**.
4. Toggle **Mobile hotspot** to **On**.
5. Connect the **Client Laptop** to the Mobile Hotspot SSID.

## 4. Running Measurements at Each Candidate Position

For each candidate position `P1`..`P6`:

1. Physically place the Repeater Laptop at the marked position and wait ~10 seconds for Wi-Fi links to stabilize.
2. On the Client Laptop, select the position label (e.g., `P1`) in the Repeater Griffin dashboard and click **Start Measurement** (or run `python scripts/run_client.py --position P1`).
3. Wait for the automated sequence:
   - 3 × 20s TCP upload tests (`iperf3 -c <server_ip> -p 5201 -t 20 -J`)
   - 3 × 20s TCP download tests (`iperf3 -c <server_ip> -p 5201 -t 20 -J -R`)
   - 1 × 10-packet Windows `ping` test for RTT and packet loss
4. If the client loses connectivity completely or cannot associate at a candidate position, click **Mark Unavailable / Disconnected** so that position is preserved in CSV as `unavailable`.
5. Move the Repeater Laptop to the next candidate position and repeat.

## 5. Output Artifacts

- **Raw measurements:** `data/raw/raw_measurements.csv` (append-only; preserves every individual trial).
- **Processed placement summaries:** `data/processed/placement_summaries.csv` (append-only summary snapshots).
- **Comparison graphs:** `results/graphs/` (`upload_throughput_comparison.png`, `download_throughput_comparison.png`, `rtt_comparison.png`, `placement_ranking.png`).
- **Logs:** `results/reports/repeater_griffin.log`.


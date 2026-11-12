"""Configuration management for Repeater Griffin."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"


@dataclass
class IperfConfig:
    """Configuration for iperf3 TCP throughput tests."""

    server_ip: str = "192.168.1.100"
    port: int = 5201
    duration_sec: int = 20
    repetitions: int = 3
    parallel_streams: int = 1
    executable_path: str = "iperf3"
    timeout_buffer_sec: int = 15


@dataclass
class PingConfig:
    """Configuration for Windows ping latency and packet-loss tests."""

    target: str = "192.168.1.100"
    packet_count: int = 10
    timeout_ms: int = 2000


@dataclass
class PlacementConfig:
    """Configuration for candidate placement evaluation."""

    candidate_positions: list[str] = field(
        default_factory=lambda: ["P1", "P2", "P3", "P4", "P5", "P6"]
    )
    tie_threshold_pct: float = 5.0


@dataclass
class PathsConfig:
    """Output directory and filename configuration."""

    raw_data_dir: str = "data/raw"
    processed_data_dir: str = "data/processed"
    graphs_dir: str = "results/graphs"
    reports_dir: str = "results/reports"
    raw_csv_filename: str = "raw_measurements.csv"
    summary_csv_filename: str = "placement_summaries.csv"


@dataclass
class AppSettings:
    """Top-level application settings loaded from config/settings.json."""

    app_name: str = "Repeater Griffin"
    iperf3: IperfConfig = field(default_factory=IperfConfig)
    ping: PingConfig = field(default_factory=PingConfig)
    placement: PlacementConfig = field(default_factory=PlacementConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    project_root: Path = field(default=PROJECT_ROOT, repr=False, compare=False)

    def resolve_path(self, relative_or_absolute: str) -> Path:
        """Resolve a configured path relative to the project root."""
        candidate = Path(relative_or_absolute)
        if candidate.is_absolute():
            return candidate
        return self.project_root / candidate

    @property
    def raw_data_path(self) -> Path:
        return self.resolve_path(self.paths.raw_data_dir)

    @property
    def processed_data_path(self) -> Path:
        return self.resolve_path(self.paths.processed_data_dir)

    @property
    def graphs_path(self) -> Path:
        return self.resolve_path(self.paths.graphs_dir)

    @property
    def reports_path(self) -> Path:
        return self.resolve_path(self.paths.reports_dir)

    @property
    def raw_csv_path(self) -> Path:
        return self.raw_data_path / self.paths.raw_csv_filename

    @property
    def summary_csv_path(self) -> Path:
        return self.processed_data_path / self.paths.summary_csv_filename

    def ensure_directories(self) -> None:
        """Create configured output directories if they do not exist."""
        for directory in (
            self.raw_data_path,
            self.processed_data_path,
            self.graphs_path,
            self.reports_path,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def to_serializable_dict(self) -> dict[str, Any]:
        """Convert settings to a JSON-serializable dictionary."""
        data = asdict(self)
        data.pop("project_root", None)
        return data


def _merge_dataclass(cls: type, raw: Optional[dict[str, Any]]) -> Any:
    defaults = asdict(cls())
    if raw:
        for key, value in raw.items():
            if key in defaults and value is not None:
                defaults[key] = value
    return cls(**defaults)


def load_settings(
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> AppSettings:
    """Load application settings from JSON, falling back to defaults if absent.

    Args:
        config_path: Path to settings.json. Defaults to config/settings.json.
        project_root: Base directory for resolving relative output paths.

    Returns:
        Populated AppSettings instance.
    """
    path = Path(config_path) if config_path else DEFAULT_SETTINGS_PATH
    root = Path(project_root) if project_root else PROJECT_ROOT

    if not path.exists():
        return AppSettings(project_root=root)

    with path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    if not isinstance(raw_data, dict):
        raise ValueError(f"Expected JSON object in settings file: {path}")

    return AppSettings(
        app_name=str(raw_data.get("app_name", "Repeater Griffin")),
        iperf3=_merge_dataclass(IperfConfig, raw_data.get("iperf3")),
        ping=_merge_dataclass(PingConfig, raw_data.get("ping")),
        placement=_merge_dataclass(PlacementConfig, raw_data.get("placement")),
        paths=_merge_dataclass(PathsConfig, raw_data.get("paths")),
        project_root=root,
    )


def save_settings(
    settings: AppSettings,
    config_path: Optional[Path] = None,
) -> Path:
    """Persist application settings to JSON.

    Args:
        settings: AppSettings object to serialize.
        config_path: Destination JSON path. Defaults to config/settings.json.

    Returns:
        Path to the saved JSON configuration file.
    """
    path = Path(config_path) if config_path else DEFAULT_SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings.to_serializable_dict(), handle, indent=2)
        handle.write("\n")
    return path


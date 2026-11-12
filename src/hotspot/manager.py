"""Windows 11 Mobile Hotspot status inspection and settings launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

WINDOWS_HOTSPOT_SETTINGS_URI = "ms-settings:network-mobilehotspot"


@dataclass
class AdapterInfo:
    """Summary of a Windows network adapter."""

    name: str
    description: str
    status: str
    link_speed: str = ""
    mac_address: str = ""
    ipv4_addresses: list[str] = field(default_factory=list)
    is_hotspot_adapter: bool = False


@dataclass
class HotspotStatus:
    """Read-only inspection result for Windows Mobile Hotspot."""

    state: str  # "enabled", "disabled", "in_transition", "unknown", "unsupported_os"
    is_enabled: Optional[bool]
    is_windows: bool
    detection_method: str
    summary: str
    adapters: list[AdapterInfo] = field(default_factory=list)
    hotspot_adapter: Optional[AdapterInfo] = None
    instructions: str = ""


def get_manual_instructions() -> str:
    """Return step-by-step instructions for manually enabling Windows Mobile Hotspot."""
    return (
        "Manual Windows 11 Mobile Hotspot Setup:\n"
        "1. Connect this laptop to the upstream Wi-Fi router first.\n"
        "2. Click 'Open Hotspot Settings' (or open Settings > Network & internet > Mobile hotspot).\n"
        "3. Set 'Share my Internet connection from' to your Wi-Fi adapter.\n"
        "4. Toggle 'Mobile hotspot' to On.\n"
        "5. Note the Hotspot SSID and Password, then connect the test client device to it.\n"
        "6. Click 'Refresh Hotspot Status' to verify the Microsoft Wi-Fi Direct Virtual Adapter is Up."
    )


def _run_powershell(script: str, timeout_sec: float = 8.0) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _query_winrt_tethering_state() -> tuple[Optional[str], str]:
    """Query Windows Runtime NetworkOperatorTetheringManager (read-only)."""
    ps_script = (
        "$ErrorActionPreference = 'Stop'; "
        "[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null; "
        "[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null; "
        "$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile(); "
        "if ($null -eq $profile) { Write-Output 'NO_PROFILE'; exit 0 }; "
        "$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile); "
        "Write-Output $mgr.TetheringOperationalState.ToString()"
    )
    try:
        rc, out, err = _run_powershell(ps_script)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, f"WinRT query unavailable: {exc}"

    if rc != 0:
        return None, err or f"PowerShell exited with code {rc}"

    token = out.splitlines()[-1].strip().lower() if out else ""
    if token == "on":
        return "enabled", "WinRT NetworkOperatorTetheringManager reports state 'On'."
    if token == "off":
        return "disabled", "WinRT NetworkOperatorTetheringManager reports state 'Off'."
    if token == "intransition":
        return "in_transition", "WinRT NetworkOperatorTetheringManager reports 'InTransition'."
    if token == "no_profile":
        return None, "No active upstream internet connection profile detected by Windows."
    return None, f"Unrecognized WinRT tethering state: '{out}'."


def get_network_adapters(platform_name: Optional[str] = None) -> list[AdapterInfo]:
    """Inspect network adapters and IPv4 addresses (read-only, Windows 11)."""
    plat = (platform_name or sys.platform).lower()
    if not plat.startswith("win"):
        return []

    ps_script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$ips = @{}; "
        "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
        "  $idx = $_.InterfaceIndex; "
        "  if (-not $ips.ContainsKey($idx)) { $ips[$idx] = @() }; "
        "  $ips[$idx] += $_.IPAddress "
        "}; "
        "Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, LinkSpeed, MacAddress, "
        "@{Name='IPv4'; Expression={ $ips[$_.ifIndex] }} | ConvertTo-Json -Depth 3"
    )
    try:
        rc, out, _ = _run_powershell(ps_script)
        if rc != 0 or not out:
            return []
        parsed = json.loads(out)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("Get-NetAdapter inspection failed: %s", exc)
        return []

    items = parsed if isinstance(parsed, list) else [parsed]
    adapters: list[AdapterInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "")
        desc = str(item.get("InterfaceDescription") or "")
        status = str(item.get("Status") or "")
        link_speed = str(item.get("LinkSpeed") or "")
        mac = str(item.get("MacAddress") or "")
        raw_ips = item.get("IPv4")
        if isinstance(raw_ips, list):
            ipv4s = [str(ip) for ip in raw_ips if ip]
        elif isinstance(raw_ips, str) and raw_ips:
            ipv4s = [raw_ips]
        else:
            ipv4s = []

        desc_lower = desc.lower()
        is_hotspot = (
            "wi-fi direct virtual adapter" in desc_lower
            or "hosted network virtual adapter" in desc_lower
            or "192.168.137.1" in ipv4s
        )
        adapters.append(
            AdapterInfo(
                name=name,
                description=desc,
                status=status,
                link_speed=link_speed,
                mac_address=mac,
                ipv4_addresses=ipv4s,
                is_hotspot_adapter=is_hotspot,
            )
        )
    return adapters


def check_hotspot_status(platform_name: Optional[str] = None) -> HotspotStatus:
    """Check Windows Mobile Hotspot status and adapter details without altering config."""
    plat = (platform_name or sys.platform).lower()
    instructions = get_manual_instructions()

    if not plat.startswith("win"):
        return HotspotStatus(
            state="unsupported_os",
            is_enabled=None,
            is_windows=False,
            detection_method="platform_check",
            summary=(
                f"Running on '{plat}'. Windows Mobile Hotspot inspection requires Windows 10/11."
            ),
            instructions=instructions,
        )

    adapters = get_network_adapters(platform_name=plat)
    hotspot_adapter = next((a for a in adapters if a.is_hotspot_adapter), None)

    winrt_state, winrt_msg = _query_winrt_tethering_state()
    if winrt_state == "enabled":
        return HotspotStatus(
            state="enabled",
            is_enabled=True,
            is_windows=True,
            detection_method="winrt_tethering_manager",
            summary=winrt_msg,
            adapters=adapters,
            hotspot_adapter=hotspot_adapter,
            instructions=instructions,
        )
    if winrt_state == "disabled":
        return HotspotStatus(
            state="disabled",
            is_enabled=False,
            is_windows=True,
            detection_method="winrt_tethering_manager",
            summary=winrt_msg,
            adapters=adapters,
            hotspot_adapter=hotspot_adapter,
            instructions=instructions,
        )
    if winrt_state == "in_transition":
        return HotspotStatus(
            state="in_transition",
            is_enabled=None,
            is_windows=True,
            detection_method="winrt_tethering_manager",
            summary=winrt_msg,
            adapters=adapters,
            hotspot_adapter=hotspot_adapter,
            instructions=instructions,
        )

    # Adapter-based fallback when WinRT query is inconclusive
    if hotspot_adapter is not None:
        is_up = hotspot_adapter.status.strip().lower() == "up"
        return HotspotStatus(
            state="enabled" if is_up else "disabled",
            is_enabled=is_up,
            is_windows=True,
            detection_method="adapter_inspection",
            summary=(
                f"Hotspot virtual adapter '{hotspot_adapter.name}' "
                f"({hotspot_adapter.description}) is {hotspot_adapter.status}."
            ),
            adapters=adapters,
            hotspot_adapter=hotspot_adapter,
            instructions=instructions,
        )

    return HotspotStatus(
        state="unknown",
        is_enabled=None,
        is_windows=True,
        detection_method="fallback",
        summary=f"Could not confirm Mobile Hotspot state automatically. {winrt_msg}",
        adapters=adapters,
        hotspot_adapter=None,
        instructions=instructions,
    )


def open_hotspot_settings(platform_name: Optional[str] = None) -> tuple[bool, str]:
    """Open the official Windows 11 Mobile Hotspot settings page."""
    plat = (platform_name or sys.platform).lower()
    if not plat.startswith("win"):
        return (
            False,
            "Opening Windows Mobile Hotspot Settings is only supported on Windows 10/11.",
        )

    try:
        startfile = getattr(os, "startfile", None)
        if callable(startfile):
            startfile(WINDOWS_HOTSPOT_SETTINGS_URI)
        else:
            subprocess.Popen(
                ["cmd", "/c", "start", "", WINDOWS_HOTSPOT_SETTINGS_URI],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True, "Opened Windows Mobile Hotspot settings."
    except OSError as exc:
        msg = f"Unable to open Windows Mobile Hotspot settings: {exc}"
        logger.warning(msg)
        return False, msg


class HotspotManager:
    """Object-oriented facade for inspecting Windows Mobile Hotspot status."""

    def get_status(self) -> HotspotStatus:
        return check_hotspot_status()

    def get_adapters(self) -> list[AdapterInfo]:
        return get_network_adapters()

    def open_settings(self) -> tuple[bool, str]:
        return open_hotspot_settings()

    def get_instructions(self) -> str:
        return get_manual_instructions()


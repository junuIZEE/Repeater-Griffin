"""Windows Mobile Hotspot status and settings management."""

from hotspot.manager import (
    AdapterInfo,
    HotspotManager,
    HotspotStatus,
    check_hotspot_status,
    get_manual_instructions,
    get_network_adapters,
    open_hotspot_settings,
)

__all__ = [
    "AdapterInfo",
    "HotspotManager",
    "HotspotStatus",
    "check_hotspot_status",
    "get_manual_instructions",
    "get_network_adapters",
    "open_hotspot_settings",
]


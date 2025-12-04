"""
IC-7300 Memory Manager - Flask Web UI
Modern web interface for managing IC-7300 memories
"""

import tempfile
import threading
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request, send_file

from .memory_manager import MemoryManager
from .models import (
    FREQUENCY_BANDS,
    DuplexMode,
    FilterWidth,
    OperatingMode,
    RadioConfig,
    ToneMode,
    get_band_for_frequency,
)

app = Flask(__name__)

# Default data file for auto-save/load (same as CLI)
DEFAULT_DATA_FILE = Path.home() / ".ic7300_channels.json"

# Global state
manager: Optional[MemoryManager] = None
is_connected: bool = False
radio_lock = threading.Lock()
operation_in_progress: Optional[str] = None


def auto_save() -> bool:
    """Save channels and groups to default data file."""
    global manager
    if manager is None:
        return False
    try:
        return manager.export_to_json(DEFAULT_DATA_FILE)
    except Exception:
        return False


def auto_load(mgr: MemoryManager) -> bool:
    """Load channels and groups from default data file if it exists."""
    if DEFAULT_DATA_FILE.exists():
        try:
            success, _ = mgr.import_from_json(DEFAULT_DATA_FILE)
            return success > 0
        except Exception:
            return False
    return False


def get_manager() -> MemoryManager:
    """Get or create the memory manager instance."""
    global manager
    if manager is None:
        manager = MemoryManager(RadioConfig(port="COM3", baud_rate=115200))
        # Auto-load saved data on first access
        auto_load(manager)
    return manager


def channels_to_list(
    mgr: MemoryManager,
    band_filter: str = "All",
    group_filter: str = "All",
    show_empty: bool = True,
) -> list[dict]:
    """Convert memory channels to a list of dicts for JSON response."""
    rows = []
    for ch_num in range(100):
        channel = mgr.channels.get(ch_num)
        if channel is None:
            from .models import MemoryChannel
            channel = MemoryChannel(number=ch_num)

        # Apply band filter
        if band_filter != "All" and not channel.is_empty:
            ch_band = get_band_for_frequency(channel.rx_frequency)
            if ch_band != band_filter:
                continue

        # Apply group filter
        if group_filter != "All" and not channel.is_empty:
            if group_filter == "_ungrouped":
                if channel.group and channel.group in mgr.groups:
                    continue
            elif channel.group != group_filter:
                continue

        # Apply empty filter
        if not show_empty and channel.is_empty:
            continue

        rows.append({
            "ch": ch_num,
            "name": channel.name if not channel.is_empty else "",
            "rx_freq": channel.rx_frequency / 1_000_000 if not channel.is_empty else 0.0,
            "tx_freq": channel.tx_frequency / 1_000_000 if not channel.is_empty else 0.0,
            "mode": channel.mode.name if not channel.is_empty else "",
            "filter": channel.filter_width.name if not channel.is_empty else "",
            "duplex": channel.duplex.name if not channel.is_empty else "",
            "tone": channel.tone_mode.name if not channel.is_empty else "",
            "group": channel.group if not channel.is_empty else "",
            "is_empty": channel.is_empty,
        })

    return rows


def list_to_channels(channels_data: list[dict], mgr: MemoryManager) -> int:
    """Parse channel list back to MemoryChannel objects. Returns count updated."""
    from .models import MemoryChannel

    updated = 0
    for row in channels_data:
        ch_num = int(row["ch"])
        rx_freq = float(row.get("rx_freq", 0))
        name = str(row.get("name", "")).strip()
        mode_str = str(row.get("mode", "")).strip()

        # Skip empty rows (no frequency or mode)
        if rx_freq == 0.0 or not mode_str:
            mgr.channels[ch_num] = MemoryChannel(number=ch_num)
            continue

        try:
            tx_freq = float(row.get("tx_freq", rx_freq)) if row.get("tx_freq", 0) > 0 else rx_freq
            mode = OperatingMode[mode_str] if mode_str else OperatingMode.USB
            filter_str = str(row.get("filter", "FIL1")).strip()
            filter_width = FilterWidth[filter_str] if filter_str else FilterWidth.FIL1
            duplex_str = str(row.get("duplex", "SIMPLEX")).strip()
            duplex = DuplexMode[duplex_str] if duplex_str else DuplexMode.SIMPLEX
            tone_str = str(row.get("tone", "OFF")).strip()
            tone_mode = ToneMode[tone_str] if tone_str else ToneMode.OFF
            group_str = str(row.get("group", "")).strip()

            channel = MemoryChannel(
                number=ch_num,
                name=name[:10],
                rx_frequency=int(rx_freq * 1_000_000),
                tx_frequency=int(tx_freq * 1_000_000),
                mode=mode,
                filter_width=filter_width,
                duplex=duplex,
                tone_mode=tone_mode,
                is_empty=False,
                group=group_str,
            )
            mgr.channels[ch_num] = channel
            updated += 1
        except (KeyError, ValueError) as e:
            print(f"Error parsing channel {ch_num}: {e}")

    return updated


# Routes

@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template(
        "index.html",
        bands=["All"] + list(FREQUENCY_BANDS.keys()),
        modes=[m.name for m in OperatingMode],
        filters=[f.name for f in FilterWidth],
        duplex_modes=[d.name for d in DuplexMode],
        tone_modes=[t.name for t in ToneMode],
    )


@app.route("/api/status")
def get_status():
    """Get current connection status."""
    global is_connected, manager, operation_in_progress
    return jsonify({
        "connected": is_connected,
        "port": manager.config.port if manager else "COM3",
        "baud": manager.config.baud_rate if manager else 115200,
        "busy": operation_in_progress is not None,
        "operation": operation_in_progress,
    })


@app.route("/api/connect", methods=["POST"])
def connect():
    """Connect to the radio."""
    global manager, is_connected

    data = request.get_json() or {}
    port = data.get("port", "COM3")
    baud = int(data.get("baud", 115200))
    address = data.get("address", "0x94")

    try:
        civ_addr = int(address, 0) if address.startswith("0x") else int(address)
    except ValueError:
        civ_addr = 0x94

    config = RadioConfig(port=port, baud_rate=baud, civ_address=civ_addr)

    # Preserve existing channels and groups when reconnecting
    old_channels = None
    old_groups = None
    if manager is not None:
        old_channels = manager.channels.copy()
        old_groups = manager.groups.copy()

    manager = MemoryManager(config)

    # Restore channels and groups
    if old_channels:
        manager.channels = old_channels
    if old_groups:
        manager.groups = old_groups

    # If no channels were preserved, try auto-loading from file
    if not old_channels:
        auto_load(manager)

    if manager.connect():
        is_connected = True
        return jsonify({"success": True, "message": f"Connected to {port}"})
    else:
        is_connected = False
        return jsonify({"success": False, "message": f"Failed to connect to {port}"})


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    """Disconnect from the radio."""
    global manager, is_connected

    if manager:
        manager.disconnect()
    is_connected = False
    return jsonify({"success": True, "message": "Disconnected"})


@app.route("/api/channels")
def get_channels():
    """Get all memory channels."""
    mgr = get_manager()
    band = request.args.get("band", "All")
    group = request.args.get("group", "All")
    show_empty = request.args.get("show_empty", "true").lower() == "true"

    channels = channels_to_list(mgr, band, group, show_empty)
    return jsonify({"channels": channels, "groups": list(mgr.groups.keys())})


@app.route("/api/channels-grouped")
def get_channels_grouped():
    """Get all channels organized by group with computed target slots."""
    mgr = get_manager()
    return jsonify(mgr.get_channels_grouped())


@app.route("/api/channels", methods=["POST"])
def save_channels():
    """Save edited channels."""
    global manager
    mgr = get_manager()

    data = request.get_json() or {}
    channels_data = data.get("channels", [])

    count = list_to_channels(channels_data, mgr)
    manager = mgr
    # Auto-save to persist changes
    auto_save()
    return jsonify({"success": True, "count": count, "message": f"Saved {count} channels"})


@app.route("/api/download", methods=["POST"])
def download_from_radio():
    """Download all channels from the radio."""
    global manager, is_connected, operation_in_progress

    if not is_connected or manager is None:
        return jsonify({"success": False, "message": "Not connected to radio"})

    # Try to acquire the lock (non-blocking)
    if not radio_lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": f"Radio busy: {operation_in_progress or 'operation'} in progress",
        })

    try:
        operation_in_progress = "download"
        count = manager.download_all_channels(1, 99)
        # Auto-save downloaded channels
        if count > 0:
            auto_save()
        return jsonify({
            "success": True,
            "count": count,
            "message": f"Downloaded {count} channels from radio",
        })
    finally:
        operation_in_progress = None
        radio_lock.release()


@app.route("/api/upload", methods=["POST"])
def upload_to_radio():
    """Upload all channels to the radio."""
    global manager, is_connected, operation_in_progress

    if not is_connected or manager is None:
        return jsonify({"success": False, "message": "Not connected to radio"})

    # Try to acquire the lock (non-blocking)
    if not radio_lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": f"Radio busy: {operation_in_progress or 'operation'} in progress",
        })

    try:
        operation_in_progress = "upload"
        success, failed = manager.upload_all_channels()
        return jsonify({
            "success": True,
            "uploaded": success,
            "failed": failed,
            "message": f"Uploaded {success} channels, {failed} failed",
        })
    finally:
        operation_in_progress = None
        radio_lock.release()


@app.route("/api/groups")
def get_groups():
    """Get all memory groups with their computed ranges."""
    mgr = get_manager()
    ranges = mgr.get_group_ranges()

    groups_list = []
    for group_id, group in mgr.groups.items():
        if group_id in ranges:
            base, count, end = ranges[group_id]
        else:
            base, count, end = group.base_channel, 0, group.base_channel - 1

        groups_list.append({
            "id": group_id,
            "base_channel": group.base_channel,
            "count": count,
            "range_start": base,
            "range_end": end,
        })

    # Include ungrouped info
    ungrouped_info = None
    if "_ungrouped" in ranges:
        base, count, end = ranges["_ungrouped"]
        ungrouped_info = {
            "count": count,
            "range_start": base,
            "range_end": end,
        }

    # Check for overlaps
    valid, error = mgr.validate_no_overlaps()

    return jsonify({
        "groups": groups_list,
        "ungrouped": ungrouped_info,
        "valid": valid,
        "overlap_error": error if not valid else None,
    })


@app.route("/api/groups", methods=["POST"])
def create_group():
    """Create a new memory group."""
    mgr = get_manager()
    data = request.get_json() or {}

    group_id = str(data.get("id", "")).strip()
    base_channel = int(data.get("base_channel", 1))

    if not group_id:
        return jsonify({"success": False, "message": "Group ID is required"})

    if mgr.create_group(group_id, base_channel):
        # Auto-save to persist group changes
        auto_save()
        return jsonify({"success": True, "message": f"Created group '{group_id}'"})
    else:
        return jsonify({"success": False, "message": f"Failed to create group (may already exist)"})


@app.route("/api/groups/<group_id>", methods=["PUT"])
def update_group(group_id: str):
    """Update a memory group's base channel."""
    mgr = get_manager()
    data = request.get_json() or {}

    new_base = int(data.get("base_channel", 1))

    if mgr.update_group(group_id, new_base):
        # Auto-save to persist group changes
        auto_save()
        return jsonify({"success": True, "message": f"Updated group '{group_id}'"})
    else:
        return jsonify({"success": False, "message": f"Failed to update group"})


@app.route("/api/groups/<group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    """Delete a memory group."""
    mgr = get_manager()

    if mgr.delete_group(group_id):
        # Auto-save to persist group changes
        auto_save()
        return jsonify({"success": True, "message": f"Deleted group '{group_id}'"})
    else:
        return jsonify({"success": False, "message": f"Group not found"})


@app.route("/api/upload-group/<group_id>", methods=["POST"])
def upload_group_to_radio(group_id: str):
    """Upload a specific group's channels to the radio."""
    global manager, is_connected, operation_in_progress

    if not is_connected or manager is None:
        return jsonify({"success": False, "message": "Not connected to radio"})

    if group_id not in manager.groups:
        return jsonify({"success": False, "message": f"Group '{group_id}' not found"})

    # Try to acquire the lock (non-blocking)
    if not radio_lock.acquire(blocking=False):
        return jsonify({
            "success": False,
            "message": f"Radio busy: {operation_in_progress or 'operation'} in progress",
        })

    try:
        operation_in_progress = f"upload group '{group_id}'"
        success, failed = manager.upload_group(group_id)
        return jsonify({
            "success": True,
            "uploaded": success,
            "failed": failed,
            "message": f"Uploaded {success} channels from group '{group_id}', {failed} failed",
        })
    finally:
        operation_in_progress = None
        radio_lock.release()


@app.route("/api/export/csv")
def export_csv():
    """Export channels as CSV file."""
    mgr = get_manager()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        filepath = Path(f.name)

    mgr.export_to_csv(filepath)

    return send_file(
        filepath,
        mimetype="text/csv",
        as_attachment=True,
        download_name="ic7300_channels.csv",
    )


@app.route("/api/export/json")
def export_json():
    """Export channels as JSON file."""
    mgr = get_manager()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        filepath = Path(f.name)

    mgr.export_to_json(filepath)

    return send_file(
        filepath,
        mimetype="application/json",
        as_attachment=True,
        download_name="ic7300_channels.json",
    )


@app.route("/api/import", methods=["POST"])
def import_file():
    """Import channels from uploaded file."""
    global manager

    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file provided"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"})

    mgr = get_manager()

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as f:
        file.save(f.name)
        filepath = Path(f.name)

    if filepath.suffix.lower() == ".csv":
        success, failed = mgr.import_from_csv(filepath)
    elif filepath.suffix.lower() == ".json":
        success, failed = mgr.import_from_json(filepath)
    else:
        return jsonify({"success": False, "message": "Unsupported file format"})

    manager = mgr

    # Clean up temp file
    filepath.unlink(missing_ok=True)

    # Auto-save imported data
    if success > 0:
        auto_save()

    return jsonify({
        "success": True,
        "imported": success,
        "failed": failed,
        "message": f"Imported {success} channels, {failed} failed",
    })


@app.route("/api/summary")
def get_summary():
    """Get memory summary statistics."""
    mgr = get_manager()
    summary = mgr.summary()
    return jsonify(summary)


def launch():
    """Launch the Flask web interface."""
    print("Starting IC-7300 Memory Manager...")
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    launch()

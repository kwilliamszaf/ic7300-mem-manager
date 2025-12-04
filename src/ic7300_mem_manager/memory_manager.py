"""
IC-7300 Memory Manager Service
High-level memory management operations
"""

import csv
import json
import time
from pathlib import Path
from typing import Callable, Optional

from .civ_protocol import CIVProtocol
from .models import (
    DuplexMode,
    FilterWidth,
    MemoryBank,
    MemoryChannel,
    MemoryGroup,
    OperatingMode,
    RadioConfig,
    ToneMode,
    get_band_for_frequency,
)


class MemoryManager:
    """High-level memory management for IC-7300"""

    MAX_CHANNELS = 99  # IC-7300 has 99 regular memory channels

    def __init__(self, config: Optional[RadioConfig] = None):
        self.config = config or RadioConfig()
        self.protocol = CIVProtocol(self.config)
        self.channels: dict[int, MemoryChannel] = {}
        self.banks: dict[str, MemoryBank] = {}
        self.groups: dict[str, MemoryGroup] = {}

        # Initialize empty channels
        for i in range(self.MAX_CHANNELS + 1):
            self.channels[i] = MemoryChannel(number=i)

        # Initialize memory banks A-Z
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            self.banks[letter] = MemoryBank(id=letter, name=f"Bank {letter}")

    def connect(self) -> bool:
        """Connect to the radio"""
        return self.protocol.connect()

    def disconnect(self) -> None:
        """Disconnect from the radio"""
        self.protocol.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.protocol.is_connected

    def get_channel(self, number: int) -> Optional[MemoryChannel]:
        """Get a memory channel by number"""
        if 0 <= number <= self.MAX_CHANNELS:
            return self.channels.get(number)
        return None

    def set_channel(self, channel: MemoryChannel) -> bool:
        """Set/update a memory channel locally"""
        if 0 <= channel.number <= self.MAX_CHANNELS:
            channel.is_empty = False
            self.channels[channel.number] = channel
            return True
        return False

    def clear_channel(self, number: int) -> bool:
        """Clear a memory channel locally"""
        if 0 <= number <= self.MAX_CHANNELS:
            self.channels[number] = MemoryChannel(number=number)
            return True
        return False

    def upload_channel(self, number: int) -> bool:
        """Upload a channel to the radio"""
        channel = self.channels.get(number)
        if channel and not channel.is_empty:
            return self.protocol.write_memory_channel(channel)
        return False

    def upload_all_channels(self) -> tuple[int, int]:
        """Upload all non-empty channels to the radio with group-aware slot assignment.

        - First clears ALL memory channels (1-99) on the radio
        - Grouped channels are written sequentially from their group's base_channel
        - Ungrouped channels are written at next multiple of 10 after last group

        Returns (success_count, fail_count)
        """
        # Validate no overlaps first
        valid, error = self.validate_no_overlaps()
        if not valid:
            print(f"Upload aborted: {error}")
            return 0, 0

        # Clear ALL memory channels (1-99) first using direct 1A 00 FF command
        # This does NOT change the radio display
        print("Clearing all memory channels (background)...")
        for slot in range(1, 100):
            self.protocol.clear_memory_channel(slot)
            if slot % 10 == 0:
                print(f"  Cleared slots 1-{slot}...")
            time.sleep(0.02)  # Small delay between clear operations

        success = 0
        failed = 0

        # Write each group's channels first
        print(f"Writing grouped channels... (groups: {list(self.groups.keys())})")
        for group_id, group in self.groups.items():
            group_channels = sorted(
                self.get_channels_by_group(group_id), key=lambda ch: ch.number
            )
            print(f"  Group '{group_id}': {len(group_channels)} channels starting at slot {group.base_channel}")
            for idx, channel in enumerate(group_channels):
                target_slot = group.base_channel + idx
                # Create a copy with the target slot number
                ch_copy = MemoryChannel(
                    number=target_slot,
                    name=channel.name,
                    rx_frequency=channel.rx_frequency,
                    tx_frequency=channel.tx_frequency,
                    mode=channel.mode,
                    filter_width=channel.filter_width,
                    duplex=channel.duplex,
                    tone_mode=channel.tone_mode,
                    tone_frequency=channel.tone_frequency,
                    dtcs_code=channel.dtcs_code,
                    tuning_step=channel.tuning_step,
                    is_empty=False,
                    group=channel.group,
                )
                result = self.protocol.write_memory_channel(ch_copy)
                print(f"    Slot {target_slot}: '{channel.name}' -> {'OK' if result else 'FAIL'}")
                if result:
                    success += 1
                else:
                    failed += 1
                time.sleep(0.02)  # Small delay between write operations

        # Write ungrouped channels at next multiple of 10 after last group
        ungrouped = sorted(self.get_ungrouped_channels(), key=lambda ch: ch.number)
        ungrouped_base = self._get_ungrouped_base()

        if ungrouped:
            print(f"Writing ungrouped channels: {len(ungrouped)} channels starting at slot {ungrouped_base}")

        for idx, channel in enumerate(ungrouped):
            target_slot = ungrouped_base + idx
            # Create a copy with the target slot number
            ch_copy = MemoryChannel(
                number=target_slot,
                name=channel.name,
                rx_frequency=channel.rx_frequency,
                tx_frequency=channel.tx_frequency,
                mode=channel.mode,
                filter_width=channel.filter_width,
                duplex=channel.duplex,
                tone_mode=channel.tone_mode,
                tone_frequency=channel.tone_frequency,
                dtcs_code=channel.dtcs_code,
                tuning_step=channel.tuning_step,
                is_empty=False,
                group=channel.group,
            )
            result = self.protocol.write_memory_channel(ch_copy)
            print(f"    Slot {target_slot}: '{channel.name}' -> {'OK' if result else 'FAIL'}")
            if result:
                success += 1
            else:
                failed += 1
            time.sleep(0.02)  # Small delay between write operations

        # Switch back to VFO mode after upload (the 09 command sequence changes radio display)
        self.protocol.switch_to_vfo()

        # Update in-memory channels to reflect the new slot assignments
        if success > 0:
            self._reorganize_channels_after_upload()

        print(f"Upload complete: {success} succeeded, {failed} failed")
        return success, failed

    def _reorganize_channels_after_upload(self) -> None:
        """Reorganize in-memory channels to match the uploaded slot assignments.

        After upload, channels are moved to their target slots so the UI shows
        current and new slot numbers as the same.
        """
        # Build new channel mapping based on target slots
        new_channels: dict[int, MemoryChannel] = {}

        # Initialize all slots as empty
        for i in range(self.MAX_CHANNELS + 1):
            new_channels[i] = MemoryChannel(number=i)

        # Place grouped channels at their target slots
        for group_id, group in self.groups.items():
            group_channels = sorted(
                self.get_channels_by_group(group_id), key=lambda ch: ch.number
            )
            for idx, channel in enumerate(group_channels):
                target_slot = group.base_channel + idx
                if target_slot <= self.MAX_CHANNELS:
                    new_channels[target_slot] = MemoryChannel(
                        number=target_slot,
                        name=channel.name,
                        rx_frequency=channel.rx_frequency,
                        tx_frequency=channel.tx_frequency,
                        mode=channel.mode,
                        filter_width=channel.filter_width,
                        duplex=channel.duplex,
                        tone_mode=channel.tone_mode,
                        tone_frequency=channel.tone_frequency,
                        dtcs_code=channel.dtcs_code,
                        tuning_step=channel.tuning_step,
                        is_empty=False,
                        group=channel.group,
                    )

        # Place ungrouped channels at their target slots
        ungrouped = sorted(self.get_ungrouped_channels(), key=lambda ch: ch.number)
        ungrouped_base = self._get_ungrouped_base()

        for idx, channel in enumerate(ungrouped):
            target_slot = ungrouped_base + idx
            if target_slot <= self.MAX_CHANNELS:
                new_channels[target_slot] = MemoryChannel(
                    number=target_slot,
                    name=channel.name,
                    rx_frequency=channel.rx_frequency,
                    tx_frequency=channel.tx_frequency,
                    mode=channel.mode,
                    filter_width=channel.filter_width,
                    duplex=channel.duplex,
                    tone_mode=channel.tone_mode,
                    tone_frequency=channel.tone_frequency,
                    dtcs_code=channel.dtcs_code,
                    tuning_step=channel.tuning_step,
                    is_empty=False,
                    group=channel.group,
                )

        # Replace channels with reorganized version
        self.channels = new_channels

    def upload_group(self, group_id: str) -> tuple[int, int]:
        """Upload a specific group's channels to the radio.

        Returns (success_count, fail_count)
        """
        if group_id not in self.groups:
            return 0, 0

        group = self.groups[group_id]
        success = 0
        failed = 0

        group_channels = sorted(
            self.get_channels_by_group(group_id), key=lambda ch: ch.number
        )

        for idx, channel in enumerate(group_channels):
            target_slot = group.base_channel + idx
            # Clear target slot first
            self.protocol.clear_memory_channel(target_slot)
            # Create a copy with the target slot number
            ch_copy = MemoryChannel(
                number=target_slot,
                name=channel.name,
                rx_frequency=channel.rx_frequency,
                tx_frequency=channel.tx_frequency,
                mode=channel.mode,
                filter_width=channel.filter_width,
                duplex=channel.duplex,
                tone_mode=channel.tone_mode,
                tone_frequency=channel.tone_frequency,
                dtcs_code=channel.dtcs_code,
                tuning_step=channel.tuning_step,
                is_empty=False,
                group=channel.group,
            )
            if self.protocol.write_memory_channel(ch_copy):
                success += 1
            else:
                failed += 1

        return success, failed

    def download_channel(self, number: int) -> Optional[MemoryChannel]:
        """Download a single channel from the radio"""
        channel = self.protocol.read_memory_channel(number)
        if channel:
            self.channels[number] = channel
        return channel

    def download_all_channels(
        self,
        start: int = 1,
        end: int = 99,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Download all memory channels from the radio. Returns count of channels read."""
        channels = self.protocol.read_all_memory_channels(start, end, progress_callback)
        for channel in channels:
            self.channels[channel.number] = channel
        return len(channels)

    def add_channel_to_bank(self, channel_number: int, bank_id: str) -> bool:
        """Add a channel to a memory bank"""
        bank_id = bank_id.upper()
        if bank_id in self.banks and 0 <= channel_number <= self.MAX_CHANNELS:
            if channel_number not in self.banks[bank_id].channels:
                self.banks[bank_id].channels.append(channel_number)
            return True
        return False

    def remove_channel_from_bank(self, channel_number: int, bank_id: str) -> bool:
        """Remove a channel from a memory bank"""
        bank_id = bank_id.upper()
        if bank_id in self.banks and channel_number in self.banks[bank_id].channels:
            self.banks[bank_id].channels.remove(channel_number)
            return True
        return False

    # --- Group Management ---

    def create_group(self, group_id: str, base_channel: int) -> bool:
        """Create a new memory group"""
        if not group_id or group_id in self.groups:
            return False
        if not 0 <= base_channel <= self.MAX_CHANNELS:
            return False
        self.groups[group_id] = MemoryGroup(id=group_id, base_channel=base_channel)
        return True

    def delete_group(self, group_id: str) -> bool:
        """Delete a memory group and unassign all its channels"""
        if group_id not in self.groups:
            return False
        # Unassign channels from this group
        for channel in self.channels.values():
            if channel.group == group_id:
                channel.group = ""
        del self.groups[group_id]
        return True

    def update_group(self, group_id: str, new_base: int) -> bool:
        """Update the base channel for a group"""
        if group_id not in self.groups:
            return False
        if not 0 <= new_base <= self.MAX_CHANNELS:
            return False
        self.groups[group_id].base_channel = new_base
        return True

    def get_group_ranges(self) -> dict[str, tuple[int, int, int]]:
        """Calculate the target slot range for each group and ungrouped channels.

        Returns dict mapping group_id (or '_ungrouped') to (base, count, end).
        """
        ranges: dict[str, tuple[int, int, int]] = {}

        # Count channels per group
        group_counts: dict[str, int] = {gid: 0 for gid in self.groups}
        ungrouped_count = 0

        for ch in self.channels.values():
            if not ch.is_empty:
                if ch.group and ch.group in self.groups:
                    group_counts[ch.group] += 1
                else:
                    ungrouped_count += 1

        # Build ranges for groups
        for gid, group in self.groups.items():
            count = group_counts[gid]
            if count > 0:
                ranges[gid] = (group.base_channel, count, group.base_channel + count - 1)

        # Ungrouped channels start at next multiple of 10 after last group
        if ungrouped_count > 0:
            ungrouped_base = self._get_ungrouped_base()
            ranges["_ungrouped"] = (ungrouped_base, ungrouped_count, ungrouped_base + ungrouped_count - 1)

        return ranges

    def validate_no_overlaps(self) -> tuple[bool, str]:
        """Check if any group ranges overlap. Returns (valid, error_message)."""
        ranges = self.get_group_ranges()
        range_list = list(ranges.items())

        for i, (name1, (base1, count1, end1)) in enumerate(range_list):
            r1 = set(range(base1, end1 + 1))
            for name2, (base2, count2, end2) in range_list[i + 1:]:
                r2 = set(range(base2, end2 + 1))
                overlap = r1 & r2
                if overlap:
                    display1 = "(ungrouped)" if name1 == "_ungrouped" else name1
                    display2 = "(ungrouped)" if name2 == "_ungrouped" else name2
                    return False, f"'{display1}' and '{display2}' overlap at slots {sorted(overlap)}"

        return True, ""

    def get_channels_by_group(self, group_id: str) -> list[MemoryChannel]:
        """Get all non-empty channels assigned to a specific group"""
        return [
            ch for ch in self.channels.values()
            if not ch.is_empty and ch.group == group_id
        ]

    def get_ungrouped_channels(self) -> list[MemoryChannel]:
        """Get all non-empty channels not assigned to any group"""
        return [
            ch for ch in self.channels.values()
            if not ch.is_empty and (not ch.group or ch.group not in self.groups)
        ]

    def _get_ungrouped_base(self) -> int:
        """Calculate base slot for ungrouped channels.

        Returns the next multiple of 10 after the last group's end position.
        If no groups exist, returns 1.
        """
        if not self.groups:
            return 1

        # Find the highest end position among all groups
        max_end = 0
        for group_id, group in self.groups.items():
            group_channels = self.get_channels_by_group(group_id)
            if group_channels:
                end = group.base_channel + len(group_channels) - 1
                max_end = max(max_end, end)

        if max_end == 0:
            return 1

        # Round up to next multiple of 10
        return ((max_end // 10) + 1) * 10

    def get_channels_grouped(self) -> dict:
        """Get all channels organized by group with computed target slots.

        Returns dict with:
        - groups: list of group dicts sorted by base_channel
        - valid: bool indicating no overlaps
        - overlap_error: error message if overlaps exist
        """
        result_groups = []

        # Get group ranges for computing target slots
        ranges = self.get_group_ranges()

        # Process each defined group, sorted by base_channel
        sorted_groups = sorted(self.groups.items(), key=lambda x: x[1].base_channel)

        for group_id, group in sorted_groups:
            group_channels = sorted(
                self.get_channels_by_group(group_id), key=lambda ch: ch.number
            )
            channels_data = []
            for idx, ch in enumerate(group_channels):
                target_slot = group.base_channel + idx
                channels_data.append({
                    "current_slot": ch.number,
                    "target_slot": target_slot,
                    "name": ch.name,
                    "rx_freq": ch.rx_frequency / 1_000_000,
                    "tx_freq": ch.tx_frequency / 1_000_000,
                    "mode": ch.mode.name,
                    "filter": ch.filter_width.name,
                    "duplex": ch.duplex.name,
                    "tone": ch.tone_mode.name,
                })

            range_info = ranges.get(group_id)
            result_groups.append({
                "id": group_id,
                "base_channel": group.base_channel,
                "range_start": range_info[0] if range_info else group.base_channel,
                "range_end": range_info[2] if range_info else group.base_channel - 1,
                "channels": channels_data,
            })

        # Process ungrouped channels
        ungrouped = sorted(self.get_ungrouped_channels(), key=lambda ch: ch.number)
        if ungrouped:
            # Ungrouped channels start at next multiple of 10 after last group
            ungrouped_base = self._get_ungrouped_base()
            channels_data = []
            for idx, ch in enumerate(ungrouped):
                target_slot = ungrouped_base + idx
                channels_data.append({
                    "current_slot": ch.number,
                    "target_slot": target_slot,
                    "name": ch.name,
                    "rx_freq": ch.rx_frequency / 1_000_000,
                    "tx_freq": ch.tx_frequency / 1_000_000,
                    "mode": ch.mode.name,
                    "filter": ch.filter_width.name,
                    "duplex": ch.duplex.name,
                    "tone": ch.tone_mode.name,
                })

            range_info = ranges.get("_ungrouped")
            result_groups.append({
                "id": "_unassigned",
                "base_channel": ungrouped_base,
                "range_start": range_info[0] if range_info else ungrouped_base,
                "range_end": range_info[2] if range_info else ungrouped_base - 1,
                "channels": channels_data,
            })

        # Check for overlaps
        valid, error = self.validate_no_overlaps()

        return {
            "groups": result_groups,
            "valid": valid,
            "overlap_error": error if not valid else None,
        }

    def get_channels_by_band(self, band: str) -> list[MemoryChannel]:
        """Get all channels for a specific amateur band"""
        result = []
        for channel in self.channels.values():
            if not channel.is_empty:
                channel_band = get_band_for_frequency(channel.rx_frequency)
                if channel_band == band:
                    result.append(channel)
        return result

    def get_channels_by_mode(self, mode: OperatingMode) -> list[MemoryChannel]:
        """Get all channels using a specific mode"""
        return [ch for ch in self.channels.values() if not ch.is_empty and ch.mode == mode]

    def export_to_csv(self, filepath: Path) -> bool:
        """Export all channels to CSV file, sorted by channel number"""
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Channel",
                    "Name",
                    "RX Frequency (Hz)",
                    "TX Frequency (Hz)",
                    "Mode",
                    "Filter",
                    "Duplex",
                    "Tone Mode",
                    "Tone Freq",
                    "DTCS Code",
                    "Tuning Step",
                    "Group",
                ])
                # Sort channels by number for consistent export order
                sorted_channels = sorted(
                    [ch for ch in self.channels.values() if not ch.is_empty],
                    key=lambda ch: ch.number
                )
                for channel in sorted_channels:
                    writer.writerow([
                        channel.number,
                        channel.name,
                        channel.rx_frequency,
                        channel.tx_frequency,
                        channel.mode.name,
                        channel.filter_width.name,
                        channel.duplex.name,
                        channel.tone_mode.name,
                        channel.tone_frequency,
                        channel.dtcs_code,
                        channel.tuning_step,
                        channel.group,
                    ])
            return True
        except IOError as e:
            print(f"Failed to export CSV: {e}")
            return False

    def import_from_csv(self, filepath: Path) -> tuple[int, int]:
        """Import channels from CSV file. Returns (success_count, fail_count)

        Note: CSV import clears existing channels first and creates groups
        from unique group names found in the data.
        """
        success = 0
        failed = 0
        try:
            # Clear existing channels
            for i in range(self.MAX_CHANNELS + 1):
                self.channels[i] = MemoryChannel(number=i)

            # Track unique groups found in CSV
            found_groups: set[str] = set()

            with open(filepath, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        group_name = row.get("Group", "").strip()
                        if group_name:
                            found_groups.add(group_name)

                        channel = MemoryChannel(
                            number=int(row["Channel"]),
                            name=row.get("Name", ""),
                            rx_frequency=int(row["RX Frequency (Hz)"]),
                            tx_frequency=int(row.get("TX Frequency (Hz)", row["RX Frequency (Hz)"])),
                            mode=OperatingMode[row.get("Mode", "USB")],
                            filter_width=FilterWidth[row.get("Filter", "FIL1")],
                            duplex=DuplexMode[row.get("Duplex", "SIMPLEX")],
                            tone_mode=ToneMode[row.get("Tone Mode", "OFF")],
                            tone_frequency=float(row.get("Tone Freq", 88.5)),
                            dtcs_code=int(row.get("DTCS Code", 23)),
                            tuning_step=int(row.get("Tuning Step", 100)),
                            is_empty=False,
                            group=group_name,
                        )
                        if self.set_channel(channel):
                            success += 1
                        else:
                            failed += 1
                    except (KeyError, ValueError) as e:
                        print(f"Failed to parse row: {e}")
                        failed += 1

            # Create groups that don't already exist
            for group_name in found_groups:
                if group_name and group_name not in self.groups:
                    # Find base channel from first channel in this group
                    for ch in self.channels.values():
                        if not ch.is_empty and ch.group == group_name:
                            self.groups[group_name] = MemoryGroup(
                                id=group_name, base_channel=ch.number
                            )
                            break

        except IOError as e:
            print(f"Failed to import CSV: {e}")
        return success, failed

    def export_to_json(self, filepath: Path) -> bool:
        """Export all channels, banks, and groups to JSON file, sorted by channel number"""
        try:
            data: dict = {
                "channels": [],
                "banks": {},
                "groups": {},
            }
            # Sort channels by number for consistent export order
            sorted_channels = sorted(
                [ch for ch in self.channels.values() if not ch.is_empty],
                key=lambda ch: ch.number
            )
            for channel in sorted_channels:
                ch_data: dict = {
                    "number": channel.number,
                    "name": channel.name,
                    "rx_frequency": channel.rx_frequency,
                    "tx_frequency": channel.tx_frequency,
                    "mode": channel.mode.name,
                    "filter": channel.filter_width.name,
                    "duplex": channel.duplex.name,
                    "tone_mode": channel.tone_mode.name,
                    "tone_frequency": channel.tone_frequency,
                    "dtcs_code": channel.dtcs_code,
                    "tuning_step": channel.tuning_step,
                }
                if channel.group:
                    ch_data["group"] = channel.group
                data["channels"].append(ch_data)

            for bank_id, bank in self.banks.items():
                if bank.channels:
                    data["banks"][bank_id] = {
                        "name": bank.name,
                        "channels": bank.channels,
                    }

            for group_id, group in self.groups.items():
                data["groups"][group_id] = {
                    "base_channel": group.base_channel,
                }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except IOError as e:
            print(f"Failed to export JSON: {e}")
            return False

    def import_from_json(self, filepath: Path) -> tuple[int, int]:
        """Import channels, banks, and groups from JSON file. Returns (success_count, fail_count)

        Note: JSON import clears existing channels and groups first.
        """
        success = 0
        failed = 0
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            # Clear existing channels
            for i in range(self.MAX_CHANNELS + 1):
                self.channels[i] = MemoryChannel(number=i)

            # Clear existing groups and import new ones
            self.groups.clear()
            for group_id, group_data in data.get("groups", {}).items():
                base_channel = group_data.get("base_channel", 1)
                self.groups[group_id] = MemoryGroup(id=group_id, base_channel=base_channel)

            for ch_data in data.get("channels", []):
                try:
                    channel = MemoryChannel(
                        number=ch_data["number"],
                        name=ch_data.get("name", ""),
                        rx_frequency=ch_data["rx_frequency"],
                        tx_frequency=ch_data.get("tx_frequency", ch_data["rx_frequency"]),
                        mode=OperatingMode[ch_data.get("mode", "USB")],
                        filter_width=FilterWidth[ch_data.get("filter", "FIL1")],
                        duplex=DuplexMode[ch_data.get("duplex", "SIMPLEX")],
                        tone_mode=ToneMode[ch_data.get("tone_mode", "OFF")],
                        tone_frequency=ch_data.get("tone_frequency", 88.5),
                        dtcs_code=ch_data.get("dtcs_code", 23),
                        tuning_step=ch_data.get("tuning_step", 100),
                        is_empty=False,
                        group=ch_data.get("group", ""),
                    )
                    if self.set_channel(channel):
                        success += 1
                    else:
                        failed += 1
                except (KeyError, ValueError) as e:
                    print(f"Failed to parse channel: {e}")
                    failed += 1

            for bank_id, bank_data in data.get("banks", {}).items():
                if bank_id.upper() in self.banks:
                    self.banks[bank_id.upper()].name = bank_data.get("name", f"Bank {bank_id}")
                    self.banks[bank_id.upper()].channels = bank_data.get("channels", [])

        except (IOError, json.JSONDecodeError) as e:
            print(f"Failed to import JSON: {e}")
        return success, failed

    def summary(self) -> dict:
        """Get a summary of memory contents"""
        used_channels = [ch for ch in self.channels.values() if not ch.is_empty]
        modes = {}
        bands = {}

        for ch in used_channels:
            mode_name = ch.mode.name
            modes[mode_name] = modes.get(mode_name, 0) + 1

            band = get_band_for_frequency(ch.rx_frequency)
            if band:
                bands[band] = bands.get(band, 0) + 1

        return {
            "total_channels": self.MAX_CHANNELS + 1,
            "used_channels": len(used_channels),
            "free_channels": (self.MAX_CHANNELS + 1) - len(used_channels),
            "channels_by_mode": modes,
            "channels_by_band": bands,
        }

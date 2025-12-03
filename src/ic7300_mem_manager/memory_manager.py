"""
IC-7300 Memory Manager Service
High-level memory management operations
"""

import csv
import json
from pathlib import Path
from typing import Callable, Optional

from .civ_protocol import CIVProtocol
from .models import (
    DuplexMode,
    FilterWidth,
    MemoryBank,
    MemoryChannel,
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
        """Upload all non-empty channels to the radio. Returns (success_count, fail_count)"""
        success = 0
        failed = 0
        for channel in self.channels.values():
            if not channel.is_empty:
                if self.protocol.write_memory_channel(channel):
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
        """Export all channels to CSV file"""
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
                ])
                for channel in self.channels.values():
                    if not channel.is_empty:
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
                        ])
            return True
        except IOError as e:
            print(f"Failed to export CSV: {e}")
            return False

    def import_from_csv(self, filepath: Path) -> tuple[int, int]:
        """Import channels from CSV file. Returns (success_count, fail_count)"""
        success = 0
        failed = 0
        try:
            with open(filepath, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
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
                        )
                        if self.set_channel(channel):
                            success += 1
                        else:
                            failed += 1
                    except (KeyError, ValueError) as e:
                        print(f"Failed to parse row: {e}")
                        failed += 1
        except IOError as e:
            print(f"Failed to import CSV: {e}")
        return success, failed

    def export_to_json(self, filepath: Path) -> bool:
        """Export all channels and banks to JSON file"""
        try:
            data = {
                "channels": [],
                "banks": {},
            }
            for channel in self.channels.values():
                if not channel.is_empty:
                    data["channels"].append({
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
                    })
            for bank_id, bank in self.banks.items():
                if bank.channels:
                    data["banks"][bank_id] = {
                        "name": bank.name,
                        "channels": bank.channels,
                    }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except IOError as e:
            print(f"Failed to export JSON: {e}")
            return False

    def import_from_json(self, filepath: Path) -> tuple[int, int]:
        """Import channels and banks from JSON file. Returns (success_count, fail_count)"""
        success = 0
        failed = 0
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

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

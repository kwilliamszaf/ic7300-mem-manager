"""
IC-7300 Memory Manager Data Models
Based on ICOM CI-V protocol and IC-7300 specifications
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class OperatingMode(IntEnum):
    """Operating modes supported by IC-7300"""
    LSB = 0x00
    USB = 0x01
    AM = 0x02
    CW = 0x03
    RTTY = 0x04
    FM = 0x05
    CW_R = 0x07       # CW Reverse
    RTTY_R = 0x08     # RTTY Reverse
    LSB_D = 0x80      # LSB Data
    USB_D = 0x81      # USB Data
    AM_D = 0x82       # AM Data
    FM_D = 0x85       # FM Data


class FilterWidth(IntEnum):
    """Filter width settings"""
    FIL1 = 0x01  # Widest
    FIL2 = 0x02  # Medium
    FIL3 = 0x03  # Narrowest


class DuplexMode(IntEnum):
    """Duplex/split settings"""
    SIMPLEX = 0x00
    SPLIT = 0x01


class ToneMode(IntEnum):
    """Tone mode settings"""
    OFF = 0x00
    TONE = 0x01      # CTCSS encode
    TSQL = 0x02      # CTCSS encode/decode
    DTCS = 0x03      # DCS


# Standard CTCSS tone frequencies in Hz
CTCSS_TONES = (
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
    94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9,
    171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1
)

# Frequency band definitions for IC-7300
FREQUENCY_BANDS = {
    "160m": {"min": 1_800_000, "max": 2_000_000},
    "80m": {"min": 3_500_000, "max": 4_000_000},
    "60m": {"min": 5_330_500, "max": 5_405_000},
    "40m": {"min": 7_000_000, "max": 7_300_000},
    "30m": {"min": 10_100_000, "max": 10_150_000},
    "20m": {"min": 14_000_000, "max": 14_350_000},
    "17m": {"min": 18_068_000, "max": 18_168_000},
    "15m": {"min": 21_000_000, "max": 21_450_000},
    "12m": {"min": 24_890_000, "max": 24_990_000},
    "10m": {"min": 28_000_000, "max": 29_700_000},
    "6m": {"min": 50_000_000, "max": 54_000_000},
    "4m": {"min": 70_000_000, "max": 70_500_000},
}


@dataclass
class MemoryChannel:
    """Memory channel structure for IC-7300"""

    number: int
    """Channel number (0-99 for regular memories)"""

    name: str = ""
    """Channel name (up to 10 characters)"""

    rx_frequency: int = 14_200_000
    """Receive frequency in Hz"""

    tx_frequency: int = 14_200_000
    """Transmit frequency in Hz (for split operation)"""

    mode: OperatingMode = OperatingMode.USB
    """Operating mode"""

    filter_width: FilterWidth = FilterWidth.FIL1
    """Filter width selection"""

    duplex: DuplexMode = DuplexMode.SIMPLEX
    """Duplex mode"""

    tone_mode: ToneMode = ToneMode.OFF
    """Tone mode"""

    tone_frequency: float = 88.5
    """CTCSS tone frequency in Hz"""

    dtcs_code: int = 23
    """DTCS code (if using DCS)"""

    is_empty: bool = True
    """Whether channel is empty/unused"""

    is_locked: bool = False
    """Whether channel is locked from editing"""

    tuning_step: int = 100
    """Tuning step in Hz"""

    group: str = ""
    """Memory group assignment (user-defined group ID)"""

    synced_with_radio: bool = False
    """Whether this channel's slot number is confirmed from the radio"""


@dataclass
class MemoryGroup:
    """Memory group for organizing channels with sequential slot assignment"""

    id: str
    """Group identifier (user-defined, e.g., 'Contest', 'Repeaters')"""

    base_channel: int = 1
    """Starting memory slot for this group (0-99)"""


@dataclass
class MemoryBank:
    """Memory bank for organizing channels"""

    id: str
    """Bank identifier (A-Z)"""

    name: str = ""
    """Bank name"""

    channels: list[int] = field(default_factory=list)
    """Channel numbers assigned to this bank"""


@dataclass
class RadioConfig:
    """Radio connection configuration"""

    port: str = "COM1"
    """Serial port path (e.g., COM3 or /dev/ttyUSB0)"""

    baud_rate: int = 19200
    """Baud rate (default 19200 for IC-7300)"""

    civ_address: int = 0x94
    """CI-V address of the radio (default 0x94 for IC-7300)"""

    controller_address: int = 0xE0
    """CI-V address of the controller (default 0xE0)"""


def get_band_for_frequency(frequency: int) -> Optional[str]:
    """Get band name for a given frequency in Hz"""
    for band, band_range in FREQUENCY_BANDS.items():
        if band_range["min"] <= frequency <= band_range["max"]:
            return band
    return None


def format_frequency(frequency_hz: int) -> str:
    """Format frequency for display (e.g., 14.200.000)"""
    mhz = frequency_hz / 1_000_000
    return f"{mhz:,.6f}".replace(",", ".")


def parse_frequency(frequency_str: str) -> int:
    """Parse frequency string to Hz"""
    cleaned = "".join(c for c in frequency_str if c.isdigit() or c == ".")
    mhz = float(cleaned)
    return round(mhz * 1_000_000)

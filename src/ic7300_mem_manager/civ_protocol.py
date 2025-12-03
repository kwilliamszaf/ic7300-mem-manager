"""
ICOM CI-V Protocol Handler
Implements the CI-V (Computer Interface V) protocol for IC-7300 communication
"""

import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import serial

from .models import (
    DuplexMode,
    FilterWidth,
    MemoryChannel,
    OperatingMode,
    RadioConfig,
    ToneMode,
)


class CIVCommand(IntEnum):
    """CI-V command codes"""
    # Transceive commands
    SET_FREQUENCY = 0x00
    SET_MODE = 0x01
    READ_BAND_EDGE = 0x02
    READ_FREQUENCY = 0x03
    READ_MODE = 0x04
    SET_VFO = 0x07
    SELECT_MEMORY = 0x08
    MEMORY_WRITE = 0x09
    MEMORY_TO_VFO = 0x0A
    MEMORY_CLEAR = 0x0B
    READ_OFFSET = 0x0C
    SET_OFFSET = 0x0D
    SCAN = 0x0E
    SPLIT = 0x0F
    SET_TUNING_STEP = 0x10
    SET_ATTENUATOR = 0x11
    SET_ANT = 0x12
    SET_SPEECH = 0x13
    SET_AF_GAIN = 0x14
    READ_METER = 0x15
    SET_TONE = 0x16
    SET_RIT = 0x21
    READ_NAME = 0x1A
    SET_NAME = 0x1A


class CIVResponse(IntEnum):
    """CI-V response codes"""
    OK = 0xFB
    NG = 0xFA


# CI-V protocol constants
CIV_PREAMBLE = 0xFE
CIV_EOM = 0xFD  # End of message


@dataclass
class CIVMessage:
    """Represents a CI-V protocol message"""
    destination: int
    source: int
    command: int
    sub_command: Optional[int] = None
    data: bytes = b""

    def to_bytes(self) -> bytes:
        """Convert message to bytes for transmission"""
        msg = bytes([CIV_PREAMBLE, CIV_PREAMBLE, self.destination, self.source, self.command])
        if self.sub_command is not None:
            msg += bytes([self.sub_command])
        msg += self.data
        msg += bytes([CIV_EOM])
        return msg

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["CIVMessage"]:
        """Parse a CI-V message from bytes"""
        if len(data) < 6:
            return None
        if data[0] != CIV_PREAMBLE or data[1] != CIV_PREAMBLE:
            return None
        if data[-1] != CIV_EOM:
            return None

        destination = data[2]
        source = data[3]
        command = data[4]
        payload = data[5:-1]

        sub_command = None
        msg_data = payload
        if len(payload) > 0 and command in (CIVCommand.READ_NAME, CIVCommand.SET_NAME):
            sub_command = payload[0]
            msg_data = payload[1:]

        return cls(
            destination=destination,
            source=source,
            command=command,
            sub_command=sub_command,
            data=msg_data,
        )


def freq_to_bcd(frequency: int) -> bytes:
    """Convert frequency in Hz to BCD format (5 bytes, LSB first).

    IC-7300 uses 1Hz resolution for frequency data.
    Example: 7.200.000 Hz = 0x00 0x00 0x20 0x07 0x00
    """
    freq = frequency
    bcd = []
    for _ in range(5):
        bcd.append((freq % 10) | ((freq // 10 % 10) << 4))
        freq //= 100
    return bytes(bcd)


def bcd_to_freq(bcd_data: bytes) -> int:
    """Convert BCD format to frequency in Hz.

    IC-7300 sends frequency as 5 bytes BCD, LSB first, in 1Hz resolution.
    Example: 7.200.000 Hz = 0x00 0x00 0x20 0x07 0x00
    """
    frequency = 0
    multiplier = 1  # Start at 1Hz
    for byte in bcd_data:
        low_nibble = byte & 0x0F
        high_nibble = (byte >> 4) & 0x0F
        frequency += low_nibble * multiplier
        multiplier *= 10
        frequency += high_nibble * multiplier
        multiplier *= 10
    return frequency


class CIVProtocol:
    """CI-V protocol handler for IC-7300 communication"""

    def __init__(self, config: RadioConfig):
        self.config = config
        self.serial: Optional[serial.Serial] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.serial is not None and self.serial.is_open

    def connect(self) -> bool:
        """Establish connection to the radio"""
        try:
            self.serial = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,
            )
            self._connected = True
            return True
        except serial.SerialException as e:
            print(f"Failed to connect: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close connection to the radio"""
        if self.serial and self.serial.is_open:
            self.serial.close()
        self._connected = False

    def send_command(self, message: CIVMessage) -> Optional[CIVMessage]:
        """Send a CI-V command and wait for response"""
        if not self.is_connected or self.serial is None:
            return None

        # Clear any pending data
        self.serial.reset_input_buffer()

        # Send command
        cmd_bytes = message.to_bytes()
        self.serial.write(cmd_bytes)
        self.serial.flush()

        # Wait for response
        time.sleep(0.05)
        response = self._read_response()
        return response

    def _read_response(self) -> Optional[CIVMessage]:
        """Read and parse CI-V response"""
        if self.serial is None:
            return None

        buffer = bytearray()
        start_time = time.time()
        timeout = 1.0

        while time.time() - start_time < timeout:
            if self.serial.in_waiting > 0:
                byte = self.serial.read(1)
                if byte:
                    buffer.extend(byte)
                    if byte[0] == CIV_EOM and len(buffer) >= 6:
                        # Find start of message (skip echo)
                        for i in range(len(buffer) - 5):
                            if buffer[i] == CIV_PREAMBLE and buffer[i + 1] == CIV_PREAMBLE:
                                if buffer[i + 3] == self.config.civ_address:
                                    # This is a response from radio
                                    msg_end = buffer.index(CIV_EOM, i) + 1
                                    return CIVMessage.from_bytes(bytes(buffer[i:msg_end]))
            else:
                time.sleep(0.01)

        return None

    def read_frequency(self) -> Optional[int]:
        """Read current VFO frequency"""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.READ_FREQUENCY,
        )
        response = self.send_command(msg)
        if response and len(response.data) >= 5:
            return bcd_to_freq(response.data[:5])
        return None

    def set_frequency(self, frequency: int) -> bool:
        """Set VFO frequency"""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SET_FREQUENCY,
            data=freq_to_bcd(frequency),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def read_mode(self) -> Optional[tuple[OperatingMode, FilterWidth]]:
        """Read current operating mode and filter"""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.READ_MODE,
        )
        response = self.send_command(msg)
        if response and len(response.data) >= 2:
            mode = OperatingMode(response.data[0])
            filter_width = FilterWidth(response.data[1])
            return mode, filter_width
        return None

    def set_mode(self, mode: OperatingMode, filter_width: FilterWidth = FilterWidth.FIL1) -> bool:
        """Set operating mode and filter"""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SET_MODE,
            data=bytes([mode, filter_width]),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def select_memory_channel(self, channel: int) -> bool:
        """Select a memory channel"""
        # Channel number as 2-digit BCD
        ch_bcd = ((channel // 10) << 4) | (channel % 10)
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SELECT_MEMORY,
            data=bytes([ch_bcd]),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def write_memory_channel(self, channel: MemoryChannel) -> bool:
        """Write a memory channel to the radio"""
        # Build memory data
        data = bytearray()

        # Channel number (2-digit BCD)
        ch_bcd = ((channel.number // 10) << 4) | (channel.number % 10)
        data.append(ch_bcd)

        # Frequency (5 bytes BCD)
        data.extend(freq_to_bcd(channel.rx_frequency))

        # Mode and filter
        data.append(channel.mode)
        data.append(channel.filter_width)

        # Additional data flags
        data.append(channel.duplex)
        data.append(channel.tone_mode)

        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.MEMORY_WRITE,
            data=bytes(data),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def clear_memory_channel(self, channel: int) -> bool:
        """Clear/erase a memory channel"""
        ch_bcd = ((channel // 10) << 4) | (channel % 10)
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.MEMORY_CLEAR,
            data=bytes([ch_bcd]),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def set_split(self, enabled: bool) -> bool:
        """Enable or disable split operation"""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SPLIT,
            data=bytes([0x01 if enabled else 0x00]),
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def read_memory_channel(self, channel: int) -> Optional[MemoryChannel]:
        """Read a memory channel from the radio"""
        # First select the memory channel
        if not self.select_memory_channel(channel):
            return None

        # Switch to memory mode to read the channel
        # Command 0x08 with no data switches to memory mode
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SELECT_MEMORY,
        )
        self.send_command(msg)

        # Small delay for radio to switch
        time.sleep(0.05)

        # Read the frequency
        frequency = self.read_frequency()
        if frequency is None:
            return None

        # Read the mode
        mode_result = self.read_mode()
        if mode_result is None:
            return None

        mode, filter_width = mode_result

        # Read memory name using command 0x1A, sub-command 0x00
        name = ""
        name_msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=0x1A,
            sub_command=0x00,
        )
        name_response = self.send_command(name_msg)
        if name_response and len(name_response.data) > 0:
            # Name is ASCII encoded
            try:
                name = name_response.data.decode("ascii").strip("\x00").strip()
            except UnicodeDecodeError:
                name = ""

        return MemoryChannel(
            number=channel,
            name=name,
            rx_frequency=frequency,
            tx_frequency=frequency,
            mode=mode,
            filter_width=filter_width,
            is_empty=False,
        )

    def read_all_memory_channels(
        self, start: int = 1, end: int = 99, progress_callback: Optional[callable] = None
    ) -> list[MemoryChannel]:
        """Read all memory channels from the radio"""
        channels = []
        for i in range(start, end + 1):
            if progress_callback:
                progress_callback(i, end)
            channel = self.read_memory_channel(i)
            if channel:
                channels.append(channel)
            time.sleep(0.05)  # Small delay between reads
        return channels

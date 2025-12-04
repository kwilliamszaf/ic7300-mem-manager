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
    SEND_FREQUENCY = 0x00     # Send frequency data (transceive)
    SEND_MODE = 0x01          # Send mode data (transceive)
    READ_BAND_EDGE = 0x02
    READ_FREQUENCY = 0x03
    READ_MODE = 0x04
    SET_FREQUENCY = 0x05      # Set operating frequency
    SET_MODE = 0x06           # Set operating mode
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

        # Wait for response - give more time for the radio to respond
        time.sleep(0.1)
        return self._read_response()

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

    def switch_to_vfo(self) -> bool:
        """Switch the radio to VFO mode (command 0x07 0x00)."""
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.SET_VFO,
            data=bytes([0x00]),  # 0x00 = select VFO A
        )
        response = self.send_command(msg)
        return response is not None and response.command == CIVResponse.OK

    def write_memory_channel(self, channel: MemoryChannel) -> bool:
        """Write a memory channel to the radio.

        Uses the IC-7300's memory write approach (verified working sequence):
        1. Switch to VFO mode
        2. Set frequency in VFO (command 0x05)
        3. Set mode in VFO (command 0x06)
        4. Select memory channel (command 0x08)
        5. Write VFO to selected memory (command 0x09 with NO data)
        6. Write the name via command 0x1A 0x00
        """
        if not self.serial:
            return False

        # Step 1: Switch to VFO mode
        if not self.switch_to_vfo():
            return False
        time.sleep(0.2)

        # Step 2: Set the RX frequency (in VFO) using command 0x05
        if not self.set_frequency(channel.rx_frequency):
            return False
        time.sleep(0.2)

        # Step 3: Set the mode (in VFO) using command 0x06
        if not self.set_mode(channel.mode, channel.filter_width):
            return False
        time.sleep(0.2)

        # Step 4: Select the memory channel (command 0x08)
        if not self.select_memory_channel(channel.number):
            return False
        time.sleep(0.2)

        # Step 5: Write VFO to memory using command 0x09 (NO data - writes to selected channel)
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.MEMORY_WRITE,
            # No data - writes current VFO to the previously selected memory channel
        )
        response = self.send_command(msg)
        if response is None or response.command != CIVResponse.OK:
            return False
        time.sleep(0.1)

        # Step 6: Write the channel name using command 0x1A 0x00
        if channel.name:
            self._write_memory_name(channel.number, channel.name)

        return True

    def _write_memory_name(self, channel_num: int, name: str) -> bool:
        """Write memory channel name by reading current data and updating name field"""
        if not self.serial:
            return False

        # First, read the current memory content to get the full data structure
        ch_high = 0x00
        ch_low = ((channel_num // 10) << 4) | (channel_num % 10)

        # Read current memory content
        read_cmd = bytes([
            CIV_PREAMBLE, CIV_PREAMBLE,
            self.config.civ_address,
            self.config.controller_address,
            0x1A, 0x00, ch_high, ch_low,
            CIV_EOM
        ])

        self.serial.reset_input_buffer()
        self.serial.write(read_cmd)
        self.serial.flush()
        time.sleep(0.15)

        # Read response
        buffer = bytearray()
        start_time = time.time()
        while time.time() - start_time < 1.0:
            if self.serial.in_waiting > 0:
                buffer.extend(self.serial.read(self.serial.in_waiting))
                if buffer.count(CIV_EOM) >= 2:
                    break
            time.sleep(0.01)

        # Parse response to get current payload
        first_fd = buffer.find(CIV_EOM)
        if first_fd < 0 or first_fd + 1 >= len(buffer):
            return False

        response_part = buffer[first_fd + 1:]
        current_payload = None

        for i in range(len(response_part) - 6):
            if (response_part[i] == CIV_PREAMBLE and
                response_part[i+1] == CIV_PREAMBLE and
                response_part[i+4] == 0x1A):
                end_idx = response_part.find(CIV_EOM, i)
                if end_idx > i:
                    current_payload = bytearray(response_part[i+5:end_idx])
                    break

        if current_payload is None or len(current_payload) < 10:
            return False

        # Update the name (last 10 bytes of payload)
        name_padded = name[:10].ljust(10)
        name_bytes = name_padded.encode("ascii")
        current_payload[-10:] = name_bytes

        # Write back the modified payload
        write_cmd = bytes([
            CIV_PREAMBLE, CIV_PREAMBLE,
            self.config.civ_address,
            self.config.controller_address,
            0x1A,
        ]) + bytes(current_payload) + bytes([CIV_EOM])

        self.serial.reset_input_buffer()
        self.serial.write(write_cmd)
        self.serial.flush()
        time.sleep(0.1)

        # Read response
        buffer = bytearray()
        start_time = time.time()
        while time.time() - start_time < 1.0:
            if self.serial.in_waiting > 0:
                buffer.extend(self.serial.read(self.serial.in_waiting))
                if buffer.count(CIV_EOM) >= 2:
                    break
            time.sleep(0.01)

        # Check for OK response (FB)
        return b'\xfb' in buffer

    def clear_memory_channel(self, channel: int) -> bool:
        """Clear/erase a memory channel.

        The IC-7300 requires selecting the memory channel first,
        then issuing the memory clear command.
        """
        if not self.serial:
            return False

        # First, select the memory channel
        if not self.select_memory_channel(channel):
            return False

        # Small delay after selection
        time.sleep(0.05)

        # Now send the clear command (0x0B) - no data needed after selection
        msg = CIVMessage(
            destination=self.config.civ_address,
            source=self.config.controller_address,
            command=CIVCommand.MEMORY_CLEAR,
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
        """Read a memory channel from the radio using command 1A 00.

        This method reads memory channel content directly without selecting
        the channel on the radio, so it doesn't change the radio's display.

        CI-V command 1A 00 returns the full channel data structure:
        - Bytes 0: sub-command (0x00)
        - Bytes 1-2: Memory channel number (BCD)
        - Byte 3: Split and Select memory setting
        - Bytes 4-8: Operating frequency (5 bytes BCD)
        - Bytes 9-10: Operating mode and filter
        - Byte 11: Data mode and tone type
        - Bytes 12-14: Repeater tone frequency
        - Bytes 15-17: Tone squelch frequency
        - Bytes 18+: Memory name (up to 10 characters)
        """
        if not self.serial:
            return None

        # Channel number as 2-byte BCD (00 01 to 00 99)
        ch_high = 0x00  # Always 0 for channels 0-99
        ch_low = ((channel // 10) << 4) | (channel % 10)

        # Build command: FE FE <to> <from> 1A 00 <ch_high> <ch_low> FD
        raw_cmd = bytes([
            CIV_PREAMBLE, CIV_PREAMBLE,
            self.config.civ_address,
            self.config.controller_address,
            0x1A, 0x00, ch_high, ch_low,
            CIV_EOM
        ])

        print(f"DEBUG read_memory_channel({channel}): Using 1A 00 command (no channel select)")
        self.serial.reset_input_buffer()
        self.serial.write(raw_cmd)
        self.serial.flush()
        time.sleep(0.15)

        # Read response
        buffer = bytearray()
        start_time = time.time()
        while time.time() - start_time < 1.0:
            if self.serial.in_waiting > 0:
                buffer.extend(self.serial.read(self.serial.in_waiting))
                if buffer.count(CIV_EOM) >= 2:
                    break
            time.sleep(0.01)

        # Find the response (skip echo)
        first_fd = buffer.find(CIV_EOM)
        if first_fd < 0 or first_fd + 1 >= len(buffer):
            return None

        response_part = buffer[first_fd + 1:]

        for i in range(len(response_part) - 6):
            if (response_part[i] == CIV_PREAMBLE and
                response_part[i+1] == CIV_PREAMBLE):
                cmd_byte = response_part[i+4]
                end_idx = response_part.find(CIV_EOM, i)

                # Check for error response (FA = NG) - channel is empty
                if cmd_byte == 0xFA:
                    return None

                # Check for valid 1A response
                if cmd_byte == 0x1A and end_idx > i:
                    payload = response_part[i+5:end_idx]

                    # Payload structure after 1A command:
                    # 00: sub-command (0x00)
                    # 01-02: channel number (2 bytes BCD)
                    # 03: Split/select setting
                    # 04-08: Operating frequency (5 bytes BCD)
                    # 09-10: Operating mode and filter
                    # 11: Data mode and tone type
                    # 12-14: Repeater tone freq
                    # 15-17: Tone squelch freq
                    # 18+: Memory name (up to 10 characters)

                    if len(payload) < 18:
                        return None

                    # Parse frequency (bytes 4-8 in payload, after sub_cmd + ch_num + split)
                    freq_bytes = payload[4:9]
                    frequency = bcd_to_freq(freq_bytes)

                    # Parse mode (byte 9) and filter (byte 10)
                    mode_byte = payload[9]
                    filter_byte = payload[10] if len(payload) > 10 else 0x01

                    try:
                        mode = OperatingMode(mode_byte)
                    except ValueError:
                        mode = OperatingMode.USB

                    try:
                        filter_width = FilterWidth(filter_byte)
                    except ValueError:
                        filter_width = FilterWidth.FIL1

                    # Parse name (last 10 bytes)
                    name = ""
                    if len(payload) >= 28:
                        name_bytes = payload[-10:]
                        try:
                            name = bytes(name_bytes).decode("ascii").strip("\x00").strip()
                        except (UnicodeDecodeError, ValueError):
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

        return None

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

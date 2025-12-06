# Installation Guide

This guide covers building, packaging, and installing the IC-7300 Memory Manager using `uv`.

## Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager

### Installing uv

**Windows (PowerShell):**
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

**Linux/macOS:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Quick Install (End Users)

If you just want to install and use the tool:

```bash
# Install directly from the repository
uv tool install git+https://github.com/YOUR_USERNAME/ic7300_mem_manager.git

# Or install from a local directory
uv tool install /path/to/ic7300_mem_manager
```

After installation, the `ic7300-mem` command will be available globally.

---

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/ic7300_mem_manager.git
cd ic7300_mem_manager
```

### 2. Create Virtual Environment and Install Dependencies

```bash
# Create venv and install in editable mode
uv venv
uv pip install -e .

# Or install with development dependencies
uv pip install -e ".[dev]"
```

### 3. Activate the Virtual Environment

**Windows:**
```powershell
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
source .venv/bin/activate
```

### 4. Run the Application

```bash
# Command-line interface
ic7300-mem --help

# Web interface
python -m ic7300_mem_manager.ui
```

---

## Building a Distributable Package

### 1. Build the Package

```bash
# Install build tools
uv pip install build

# Build wheel and sdist
uv run python -m build
```

This creates:
- `dist/ic7300_memory_manager-1.0.0-py3-none-any.whl` (wheel)
- `dist/ic7300_memory_manager-1.0.0.tar.gz` (source distribution)

### 2. Install from Built Package

```bash
# Install the wheel
uv pip install dist/ic7300_memory_manager-1.0.0-py3-none-any.whl

# Or install as a global tool
uv tool install dist/ic7300_memory_manager-1.0.0-py3-none-any.whl
```

---

## Installing as a Global Tool

`uv tool install` installs the package in an isolated environment and makes the CLI available globally:

```bash
# Install from local source
uv tool install .

# Install from wheel
uv tool install dist/ic7300_memory_manager-1.0.0-py3-none-any.whl

# Install from git
uv tool install git+https://github.com/YOUR_USERNAME/ic7300_mem_manager.git
```

After installation:
```bash
# Verify installation
ic7300-mem --help

# List installed tools
uv tool list

# Uninstall
uv tool uninstall ic7300-memory-manager
```

---

## Usage

### Command-Line Interface

```bash
# List all memory channels
ic7300-mem list

# Download channels from radio
ic7300-mem download --port COM3 --baud 115200

# Upload channels to radio
ic7300-mem upload --port COM3 --baud 115200

# Import from CSV
ic7300-mem import channels.csv

# Export to JSON
ic7300-mem export channels.json
```

### Web Interface

```bash
# Start the web UI
python -m ic7300_mem_manager.ui
```

Then open http://127.0.0.1:5000 in your browser.

---

## Troubleshooting

### Finding Your Serial Port

#### Windows

1. Connect the IC-7300 via USB
2. Open **Device Manager** (Win+X, then select Device Manager)
3. Expand **Ports (COM & LPT)**
4. Look for "Silicon Labs CP210x USB to UART Bridge" or similar
5. Note the COM port number (e.g., `COM3`, `COM4`)

**List ports from command line:**
```powershell
# PowerShell - list all COM ports
Get-WmiObject Win32_SerialPort | Select-Object DeviceID, Description

# Or using mode command
mode
```

**Using the port:**
```bash
ic7300-mem download --port COM3 --baud 115200
```

#### Linux

1. Connect the IC-7300 via USB
2. The device typically appears as `/dev/ttyUSB0` or `/dev/ttyACM0`

**List ports from command line:**
```bash
# List all serial devices
ls -la /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# More detailed information
dmesg | grep -i tty

# Using pyserial's miniterm to list ports
python -m serial.tools.list_ports
```

**Using the port:**
```bash
ic7300-mem download --port /dev/ttyUSB0 --baud 115200
```

#### macOS

1. Connect the IC-7300 via USB
2. The device typically appears as `/dev/tty.usbserial-*` or `/dev/tty.SLAB_USBtoUART`

**List ports from command line:**
```bash
ls /dev/tty.usb* /dev/tty.SLAB*
```

**Using the port:**
```bash
ic7300-mem download --port /dev/tty.usbserial-0001 --baud 115200
```

---

### Serial Port Permissions

#### Linux - Permission Denied

If you get "Permission denied" when accessing the serial port:

```bash
# Add your user to the dialout group
sudo usermod -a -G dialout $USER

# Log out and back in for changes to take effect
# Or use newgrp to apply immediately (current session only)
newgrp dialout
```

Alternatively, set permissions directly (temporary, resets on reboot):
```bash
sudo chmod 666 /dev/ttyUSB0
```

#### Linux - Create udev Rule (Permanent)

Create a udev rule for persistent permissions:

```bash
# Create the rule file
sudo tee /etc/udev/rules.d/99-ic7300.rules << 'EOF'
# ICOM IC-7300 USB Serial
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"
EOF

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

#### Windows - Port in Use

If the port is busy or in use:

1. Close any other programs using the port (logging software, other CAT programs)
2. Check Task Manager for running processes that might hold the port
3. Try disconnecting and reconnecting the USB cable
4. Restart the IC-7300

---

### IC-7300 USB Settings

Ensure the IC-7300's USB settings match your connection parameters:

1. Press **MENU** on the IC-7300
2. Navigate to **SET** > **Connectors** > **CI-V**
3. Verify these settings:
   - **CI-V Baud Rate**: 115200 (or match your `--baud` setting)
   - **CI-V Address**: 94h (default)
   - **CI-V Transceive**: ON (recommended)
   - **CI-V USB Port**: Unlink from [REMOTE]
   - **CI-V USB Baud Rate**: 115200
   - **CI-V USB Echo Back**: OFF

---

### uv Not Found

Ensure uv is in your PATH:

**Check installation:**
```bash
uv --version
```

**Reinstall if needed:**

Windows (PowerShell):
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Linux/macOS:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

### Common Errors

#### "Could not open port"
- Check that the correct port name is specified
- Ensure no other program is using the port
- Verify USB cable is connected

#### "Permission denied" (Linux)
- Add user to `dialout` group (see above)
- Check udev rules

#### "Timeout" or "No response"
- Verify baud rate matches radio settings
- Check CI-V address (default 0x94)
- Ensure CI-V USB Echo Back is OFF on the radio
- Try a shorter USB cable or different USB port

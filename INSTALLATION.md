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

### Serial Port Access (Linux)

Add your user to the `dialout` group:
```bash
sudo usermod -a -G dialout $USER
```
Log out and back in for changes to take effect.

### Serial Port Access (Windows)

Ensure the correct COM port is selected. Check Device Manager for the IC-7300's virtual serial port.

### uv Not Found

Ensure uv is in your PATH:
```bash
# Check installation
uv --version

# Reinstall if needed
curl -LsSf https://astral.sh/uv/install.sh | sh
```

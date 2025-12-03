# IC-7300 Memory Manager

A memory manager for the ICOM IC-7300 amateur radio.

## Prerequisites

### Install uv (Python package manager)

**Windows (PowerShell):**
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Installation

```bash
uv pip install -e .
```

## Usage

### Command Line

```bash
# Show help
ic7300-mem --help

# Download channels from radio
ic7300-mem download

# List channels
ic7300-mem list

# Export to CSV
ic7300-mem export channels.csv

# Import from CSV
ic7300-mem import channels.csv

# Upload to radio
ic7300-mem upload
```

### Web UI

```bash
uv run python -m ic7300_mem_manager.ui
```

Then open http://127.0.0.1:5000 in your browser.

## Requirements

- Python 3.10+
- pyserial
- flask

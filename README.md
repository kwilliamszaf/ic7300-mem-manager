# IC-7300 Memory Manager

A memory manager for the ICOM IC-7300 amateur radio.

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

## Requirements

- Python 3.10+
- pyserial
- gradio
- pandas

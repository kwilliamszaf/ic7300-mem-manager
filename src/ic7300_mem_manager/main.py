"""
IC-7300 Memory Manager - Main Entry Point
Command-line interface for managing IC-7300 memories
"""

import argparse
import sys
from pathlib import Path

from .memory_manager import MemoryManager
from .models import (
    FilterWidth,
    MemoryChannel,
    OperatingMode,
    RadioConfig,
    format_frequency,
)

# Default data file for auto-save/load
DEFAULT_DATA_FILE = Path.home() / ".ic7300_channels.json"


def auto_load(manager: MemoryManager) -> bool:
    """Load channels from default data file if it exists."""
    if DEFAULT_DATA_FILE.exists():
        try:
            success, _ = manager.import_from_json(DEFAULT_DATA_FILE)
            return success > 0
        except Exception:
            return False
    return False


def auto_save(manager: MemoryManager) -> bool:
    """Save channels to default data file."""
    try:
        return manager.export_to_json(DEFAULT_DATA_FILE)
    except Exception:
        return False


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser"""
    parser = argparse.ArgumentParser(
        prog="ic7300-mem",
        description="Memory manager for ICOM IC-7300 amateur radio",
    )

    parser.add_argument(
        "--port",
        "-p",
        default="COM3",
        help="Serial port (default: COM3)",
    )
    parser.add_argument(
        "--baud",
        "-b",
        type=int,
        default=115200,
        help="Baud rate (default: 115200)",
    )
    parser.add_argument(
        "--address",
        "-a",
        type=lambda x: int(x, 0),
        default=0x94,
        help="CI-V address of radio (default: 0x94)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List memory channels")
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Show all channels including empty",
    )
    list_parser.add_argument(
        "--band",
        help="Filter by band (e.g., 20m, 40m)",
    )

    # Import command
    import_parser = subparsers.add_parser("import", help="Import channels from file")
    import_parser.add_argument("file", type=Path, help="Input file (CSV or JSON)")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export channels to file")
    export_parser.add_argument("file", type=Path, help="Output file (CSV or JSON)")

    # Upload command
    upload_parser = subparsers.add_parser("upload", help="Upload channels to radio")
    upload_parser.add_argument(
        "--channel",
        "-c",
        type=int,
        help="Specific channel number to upload (uploads all if not specified)",
    )

    # Download command
    download_parser = subparsers.add_parser("download", help="Download channels from radio")
    download_parser.add_argument(
        "--channel",
        "-c",
        type=int,
        help="Specific channel number to download (downloads all if not specified)",
    )
    download_parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start channel for range download (default: 1)",
    )
    download_parser.add_argument(
        "--end",
        type=int,
        default=99,
        help="End channel for range download (default: 99)",
    )

    # Set command
    set_parser = subparsers.add_parser("set", help="Set a memory channel")
    set_parser.add_argument("channel", type=int, help="Channel number (0-99)")
    set_parser.add_argument("frequency", help="Frequency in MHz (e.g., 14.200)")
    set_parser.add_argument("--name", "-n", default="", help="Channel name")
    set_parser.add_argument(
        "--mode",
        "-m",
        default="USB",
        choices=[m.name for m in OperatingMode],
        help="Operating mode",
    )

    # Clear command
    clear_parser = subparsers.add_parser("clear", help="Clear a memory channel")
    clear_parser.add_argument("channel", type=int, help="Channel number to clear")

    # Summary command
    subparsers.add_parser("summary", help="Show memory summary")

    return parser


def cmd_list(manager: MemoryManager, args: argparse.Namespace) -> int:
    """List memory channels"""
    channels = list(manager.channels.values())

    if args.band:
        channels = manager.get_channels_by_band(args.band)
    elif not args.all:
        channels = [ch for ch in channels if not ch.is_empty]

    if not channels:
        print("No channels found.")
        return 0

    print(f"{'Ch':>3} {'Name':<10} {'Frequency':>14} {'Mode':<6} {'Filter':<5}")
    print("-" * 45)

    for ch in sorted(channels, key=lambda x: x.number):
        if not ch.is_empty or args.all:
            freq_str = format_frequency(ch.rx_frequency) if not ch.is_empty else "-"
            mode_str = ch.mode.name if not ch.is_empty else "-"
            filter_str = ch.filter_width.name if not ch.is_empty else "-"
            name = ch.name if ch.name else "-"
            print(f"{ch.number:>3} {name:<10} {freq_str:>14} {mode_str:<6} {filter_str:<5}")

    return 0


def cmd_import(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Import channels from file"""
    filepath = args.file

    if not filepath.exists():
        print(f"Error: File not found: {filepath}")
        return 1

    if filepath.suffix.lower() == ".csv":
        success, failed = manager.import_from_csv(filepath)
    elif filepath.suffix.lower() == ".json":
        success, failed = manager.import_from_json(filepath)
    else:
        print(f"Error: Unsupported file format: {filepath.suffix}")
        return 1

    print(f"Imported {success} channels successfully, {failed} failed.")

    # Auto-save after import
    if success > 0:
        auto_save(manager)

    return 0 if failed == 0 else 1


def cmd_export(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Export channels to file"""
    filepath = args.file

    if filepath.suffix.lower() == ".csv":
        success = manager.export_to_csv(filepath)
    elif filepath.suffix.lower() == ".json":
        success = manager.export_to_json(filepath)
    else:
        print(f"Error: Unsupported file format: {filepath.suffix}")
        return 1

    if success:
        print(f"Exported channels to {filepath}")
        return 0
    else:
        print("Export failed.")
        return 1


def cmd_upload(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Upload channels to radio"""
    if not manager.connect():
        print(f"Error: Failed to connect to radio on {manager.config.port}")
        return 1

    try:
        if args.channel is not None:
            if manager.upload_channel(args.channel):
                print(f"Uploaded channel {args.channel}")
                return 0
            else:
                print(f"Failed to upload channel {args.channel}")
                return 1
        else:
            success, failed = manager.upload_all_channels()
            print(f"Uploaded {success} channels, {failed} failed.")
            return 0 if failed == 0 else 1
    finally:
        manager.disconnect()


def cmd_download(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Download channels from radio"""
    if not manager.connect():
        print(f"Error: Failed to connect to radio on {manager.config.port}")
        return 1

    def progress(current: int, total: int) -> None:
        print(f"\rDownloading channel {current}/{total}...", end="", flush=True)

    try:
        if args.channel is not None:
            channel = manager.download_channel(args.channel)
            if channel:
                print(
                    f"Downloaded channel {args.channel}: "
                    f"{format_frequency(channel.rx_frequency)} {channel.mode.name}"
                )
                # Auto-save after single channel download
                auto_save(manager)
                return 0
            else:
                print(f"Failed to download channel {args.channel} (may be empty)")
                return 1
        else:
            count = manager.download_all_channels(args.start, args.end, progress)
            print(f"\nDownloaded {count} channels from radio.")
            # Auto-save after batch download
            if count > 0:
                auto_save(manager)
            return 0
    finally:
        manager.disconnect()


def cmd_set(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Set a memory channel"""
    from .models import parse_frequency

    if not 0 <= args.channel <= manager.MAX_CHANNELS:
        print(f"Error: Channel must be 0-{manager.MAX_CHANNELS}")
        return 1

    try:
        frequency = parse_frequency(args.frequency)
    except ValueError:
        print(f"Error: Invalid frequency: {args.frequency}")
        return 1

    channel = MemoryChannel(
        number=args.channel,
        name=args.name[:10],  # Max 10 characters
        rx_frequency=frequency,
        tx_frequency=frequency,
        mode=OperatingMode[args.mode],
        filter_width=FilterWidth.FIL1,
        is_empty=False,
    )

    manager.set_channel(channel)
    print(f"Set channel {args.channel}: {format_frequency(frequency)} {args.mode}")

    # Auto-save after setting channel
    auto_save(manager)

    return 0


def cmd_clear(manager: MemoryManager, args: argparse.Namespace) -> int:
    """Clear a memory channel"""
    if manager.clear_channel(args.channel):
        print(f"Cleared channel {args.channel}")
        # Auto-save after clearing channel
        auto_save(manager)
        return 0
    else:
        print(f"Error: Invalid channel number: {args.channel}")
        return 1


def cmd_summary(manager: MemoryManager, _args: argparse.Namespace) -> int:
    """Show memory summary"""
    summary = manager.summary()

    print("IC-7300 Memory Summary")
    print("=" * 40)
    print(f"Total channels:  {summary['total_channels']}")
    print(f"Used channels:   {summary['used_channels']}")
    print(f"Free channels:   {summary['free_channels']}")

    if summary["channels_by_band"]:
        print("\nChannels by band:")
        for band, count in sorted(summary["channels_by_band"].items()):
            print(f"  {band}: {count}")

    if summary["channels_by_mode"]:
        print("\nChannels by mode:")
        for mode, count in sorted(summary["channels_by_mode"].items()):
            print(f"  {mode}: {count}")

    return 0


def main() -> int:
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Create radio config and manager
    config = RadioConfig(
        port=args.port,
        baud_rate=args.baud,
        civ_address=args.address,
    )
    manager = MemoryManager(config)

    # Auto-load saved channels from previous session
    auto_load(manager)

    # Dispatch command
    commands = {
        "list": cmd_list,
        "import": cmd_import,
        "export": cmd_export,
        "upload": cmd_upload,
        "download": cmd_download,
        "set": cmd_set,
        "clear": cmd_clear,
        "summary": cmd_summary,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(manager, args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

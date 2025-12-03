"""
IC-7300 Memory Manager - Gradio UI
Web interface for managing IC-7300 memories
"""

import tempfile
from pathlib import Path
from typing import Optional

import gradio as gr
import pandas as pd

from .memory_manager import MemoryManager
from .models import (
    FREQUENCY_BANDS,
    DuplexMode,
    FilterWidth,
    MemoryChannel,
    OperatingMode,
    RadioConfig,
    ToneMode,
    get_band_for_frequency,
)


def channels_to_dataframe(
    manager: MemoryManager,
    band_filter: str = "All",
    show_empty: bool = True,
) -> pd.DataFrame:
    """Convert memory channels to a pandas DataFrame for display."""
    rows = []
    for ch_num in range(100):
        channel = manager.channels.get(ch_num)
        if channel is None:
            channel = MemoryChannel(number=ch_num)

        # Apply band filter
        if band_filter != "All" and not channel.is_empty:
            ch_band = get_band_for_frequency(channel.rx_frequency)
            if ch_band != band_filter:
                continue

        # Apply empty filter
        if not show_empty and channel.is_empty:
            continue

        rows.append({
            "Ch": ch_num,
            "Name": channel.name if not channel.is_empty else "",
            "RX Freq (MHz)": channel.rx_frequency / 1_000_000 if not channel.is_empty else 0.0,
            "TX Freq (MHz)": channel.tx_frequency / 1_000_000 if not channel.is_empty else 0.0,
            "Mode": channel.mode.name if not channel.is_empty else "",
            "Filter": channel.filter_width.name if not channel.is_empty else "",
            "Duplex": channel.duplex.name if not channel.is_empty else "",
            "Tone": channel.tone_mode.name if not channel.is_empty else "",
        })

    return pd.DataFrame(rows)


def dataframe_to_channels(df: pd.DataFrame, manager: MemoryManager) -> int:
    """Parse edited DataFrame back to MemoryChannel objects. Returns count updated."""
    updated = 0
    for _, row in df.iterrows():
        ch_num = int(row["Ch"])
        rx_freq = row["RX Freq (MHz)"]
        name = str(row["Name"]).strip() if pd.notna(row["Name"]) else ""
        mode_str = str(row["Mode"]).strip() if pd.notna(row["Mode"]) else ""

        # Skip empty rows (no frequency or mode)
        if rx_freq == 0.0 or not mode_str:
            manager.channels[ch_num] = MemoryChannel(number=ch_num)
            continue

        try:
            tx_freq = row["TX Freq (MHz)"] if row["TX Freq (MHz)"] > 0 else rx_freq
            mode = OperatingMode[mode_str] if mode_str else OperatingMode.USB
            filter_str = str(row["Filter"]).strip() if pd.notna(row["Filter"]) else "FIL1"
            filter_width = FilterWidth[filter_str] if filter_str else FilterWidth.FIL1
            duplex_str = str(row["Duplex"]).strip() if pd.notna(row["Duplex"]) else "SIMPLEX"
            duplex = DuplexMode[duplex_str] if duplex_str else DuplexMode.SIMPLEX
            tone_str = str(row["Tone"]).strip() if pd.notna(row["Tone"]) else "OFF"
            tone_mode = ToneMode[tone_str] if tone_str else ToneMode.OFF

            channel = MemoryChannel(
                number=ch_num,
                name=name[:10],
                rx_frequency=int(rx_freq * 1_000_000),
                tx_frequency=int(tx_freq * 1_000_000),
                mode=mode,
                filter_width=filter_width,
                duplex=duplex,
                tone_mode=tone_mode,
                is_empty=False,
            )
            manager.channels[ch_num] = channel
            updated += 1
        except (KeyError, ValueError) as e:
            print(f"Error parsing channel {ch_num}: {e}")

    return updated


def get_summary_text(manager: MemoryManager) -> str:
    """Generate summary statistics text."""
    summary = manager.summary()
    lines = [
        f"**Used:** {summary['used_channels']} / {summary['total_channels']} channels",
        "",
    ]

    if summary["channels_by_band"]:
        lines.append("**By Band:**")
        for band, count in sorted(summary["channels_by_band"].items()):
            lines.append(f"  {band}: {count}")

    return "\n".join(lines)


def create_ui() -> gr.Blocks:
    """Create the Gradio interface."""

    # Band options for filter
    band_options = ["All"] + list(FREQUENCY_BANDS.keys())

    # Mode options for reference
    mode_options = [m.name for m in OperatingMode]
    filter_options = [f.name for f in FilterWidth]
    duplex_options = [d.name for d in DuplexMode]
    tone_options = [t.name for t in ToneMode]

    with gr.Blocks(title="IC-7300 Memory Manager") as app:
        # State
        manager_state = gr.State(None)
        connected_state = gr.State(False)

        gr.Markdown("# IC-7300 Memory Manager")

        # Section 1: Connection
        with gr.Row():
            port_input = gr.Textbox(label="Serial Port", value="COM3", scale=1)
            baud_dropdown = gr.Dropdown(
                label="Baud Rate",
                choices=["9600", "19200", "38400", "57600", "115200"],
                value="115200",
                scale=1,
            )
            address_input = gr.Textbox(label="CI-V Address", value="0x94", scale=1)
            connect_btn = gr.Button("Connect", variant="primary", scale=1)
            connection_status = gr.Textbox(label="Status", value="Disconnected", interactive=False, scale=2)

        # Section 2: Radio Operations
        with gr.Row():
            download_btn = gr.Button("Download All from Radio", variant="secondary")
            upload_btn = gr.Button("Upload All to Radio", variant="secondary")

        operation_status = gr.Textbox(label="Operation Status", value="", interactive=False)

        gr.Markdown("---")

        # Section 3: Memory Table
        gr.Markdown("## Memory Channels")

        with gr.Row():
            band_filter = gr.Dropdown(
                label="Filter by Band",
                choices=band_options,
                value="All",
                scale=1,
            )
            show_empty = gr.Checkbox(label="Show Empty Channels", value=True, scale=1)
            refresh_btn = gr.Button("Refresh Table", scale=1)

        channel_table = gr.Dataframe(
            headers=["Ch", "Name", "RX Freq (MHz)", "TX Freq (MHz)", "Mode", "Filter", "Duplex", "Tone"],
            datatype=["number", "str", "number", "number", "str", "str", "str", "str"],
            col_count=(8, "fixed"),
            interactive=True,
            wrap=True,
        )

        with gr.Row():
            save_btn = gr.Button("Save Changes", variant="primary")
            save_status = gr.Textbox(label="", value="", interactive=False, show_label=False)

        gr.Markdown(f"**Valid Modes:** {', '.join(mode_options)}")
        gr.Markdown(f"**Valid Filters:** {', '.join(filter_options)} | **Duplex:** {', '.join(duplex_options)} | **Tone:** {', '.join(tone_options)}")

        gr.Markdown("---")

        # Section 4: Import/Export
        gr.Markdown("## Import / Export")

        with gr.Row():
            export_csv_btn = gr.Button("Export CSV")
            export_json_btn = gr.Button("Export JSON")
            csv_download = gr.File(label="Download CSV", interactive=False)
            json_download = gr.File(label="Download JSON", interactive=False)

        with gr.Row():
            import_file = gr.File(label="Import File (CSV or JSON)", file_types=[".csv", ".json"])
            import_status = gr.Textbox(label="Import Status", value="", interactive=False)

        gr.Markdown("---")
        summary_display = gr.Markdown("**Summary:** No data loaded")

        # ============ Event Handlers ============

        def init_manager(port: str, baud: str, address: str):
            """Initialize the MemoryManager."""
            try:
                civ_addr = int(address, 0) if address.startswith("0x") else int(address)
            except ValueError:
                civ_addr = 0x94

            config = RadioConfig(
                port=port,
                baud_rate=int(baud),
                civ_address=civ_addr,
            )
            return MemoryManager(config)

        def on_connect(manager, connected, port, baud, address):
            """Handle connect/disconnect."""
            if manager is None:
                manager = init_manager(port, baud, address)

            if not connected:
                # Connect
                if manager.connect():
                    return manager, True, "Connected to " + port, gr.update(value="Disconnect")
                else:
                    return manager, False, "Failed to connect to " + port, gr.update(value="Connect")
            else:
                # Disconnect
                manager.disconnect()
                return manager, False, "Disconnected", gr.update(value="Connect")

        def on_download(manager, connected):
            """Download all channels from radio."""
            if manager is None:
                return None, "No manager initialized", gr.update(), gr.update()
            if not connected:
                return manager, "Not connected to radio", gr.update(), gr.update()

            count = manager.download_all_channels(1, 99)
            df = channels_to_dataframe(manager)
            summary = get_summary_text(manager)
            return manager, f"Downloaded {count} channels from radio", df, summary

        def on_upload(manager, connected):
            """Upload all channels to radio."""
            if manager is None:
                return "No manager initialized"
            if not connected:
                return "Not connected to radio"

            success, failed = manager.upload_all_channels()
            return f"Uploaded {success} channels, {failed} failed"

        def on_refresh(manager, band, show):
            """Refresh the table display."""
            if manager is None:
                manager = MemoryManager(RadioConfig(port="COM3", baud_rate=115200))
            df = channels_to_dataframe(manager, band, show)
            summary = get_summary_text(manager)
            return manager, df, summary

        def on_save(manager, df):
            """Save changes from table to manager."""
            if manager is None:
                manager = MemoryManager(RadioConfig(port="COM3", baud_rate=115200))
            count = dataframe_to_channels(df, manager)
            summary = get_summary_text(manager)
            return manager, f"Saved {count} channels", summary

        def on_export_csv(manager):
            """Export to CSV file."""
            if manager is None:
                return None
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                filepath = Path(f.name)
            manager.export_to_csv(filepath)
            return str(filepath)

        def on_export_json(manager):
            """Export to JSON file."""
            if manager is None:
                return None
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                filepath = Path(f.name)
            manager.export_to_json(filepath)
            return str(filepath)

        def on_import(manager, file):
            """Import from CSV or JSON file."""
            if file is None:
                return manager, "No file selected", gr.update(), ""

            if manager is None:
                manager = MemoryManager(RadioConfig(port="COM3", baud_rate=115200))

            filepath = Path(file.name)
            if filepath.suffix.lower() == ".csv":
                success, failed = manager.import_from_csv(filepath)
            elif filepath.suffix.lower() == ".json":
                success, failed = manager.import_from_json(filepath)
            else:
                return manager, "Unsupported file format", gr.update(), ""

            df = channels_to_dataframe(manager)
            summary = get_summary_text(manager)
            return manager, f"Imported {success} channels, {failed} failed", df, summary

        # Wire up events
        connect_btn.click(
            on_connect,
            inputs=[manager_state, connected_state, port_input, baud_dropdown, address_input],
            outputs=[manager_state, connected_state, connection_status, connect_btn],
        )

        download_btn.click(
            on_download,
            inputs=[manager_state, connected_state],
            outputs=[manager_state, operation_status, channel_table, summary_display],
        )

        upload_btn.click(
            on_upload,
            inputs=[manager_state, connected_state],
            outputs=[operation_status],
        )

        refresh_btn.click(
            on_refresh,
            inputs=[manager_state, band_filter, show_empty],
            outputs=[manager_state, channel_table, summary_display],
        )

        band_filter.change(
            on_refresh,
            inputs=[manager_state, band_filter, show_empty],
            outputs=[manager_state, channel_table, summary_display],
        )

        show_empty.change(
            on_refresh,
            inputs=[manager_state, band_filter, show_empty],
            outputs=[manager_state, channel_table, summary_display],
        )

        save_btn.click(
            on_save,
            inputs=[manager_state, channel_table],
            outputs=[manager_state, save_status, summary_display],
        )

        export_csv_btn.click(
            on_export_csv,
            inputs=[manager_state],
            outputs=[csv_download],
        )

        export_json_btn.click(
            on_export_json,
            inputs=[manager_state],
            outputs=[json_download],
        )

        import_file.change(
            on_import,
            inputs=[manager_state, import_file],
            outputs=[manager_state, import_status, channel_table, summary_display],
        )

        # Initialize on load
        app.load(
            on_refresh,
            inputs=[manager_state, band_filter, show_empty],
            outputs=[manager_state, channel_table, summary_display],
        )

    return app


def launch():
    """Launch the Gradio interface."""
    app = create_ui()
    app.launch(share=True)


if __name__ == "__main__":
    launch()

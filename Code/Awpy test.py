"""
Test script for awpy library - CS2 demo parsing and analysis
awpy is used to parse and analyze Counter-Strike 2 demo files (.dem)
"""

import os
import sys
from pathlib import Path
import threading

try:
    from awpy import Demo
    import pandas as pd
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("\nPlease install awpy using: pip install awpy")
    print("If pandas is not installed: pip install pandas")
    sys.exit(1)


def test_demo_parsing(demo_path):
    """
    Test parsing a CS2 demo file with awpy
    
    Args:
        demo_path (str): Path to the .dem file
    """
    print(f"\n{'='*60}")
    print(f"Testing awpy with demo: {demo_path}")
    print(f"{'='*60}\n")
    
    # Check if file exists
    if not os.path.exists(demo_path):
        print(f"ERROR: Demo file not found at: {demo_path}")
        print("\nTo download a demo:")
        print("1. Go to FACEIT match page and click 'Watch Demo'")
        print("2. Or download from HLTV.org for professional matches")
        print("3. Save the .dem file to your computer")
        return False
    
    try:
        # Create Demo object
        print("1. Creating Demo object...")
        dem = Demo(demo_path)
        
        # Parse the demo
        print("2. Parsing demo file (this may take a moment)...")
        dem.parse()
        
        print("3. Demo parsed successfully!\n")
        
        # Display basic information
        print("="*60)
        print("DEMO INFORMATION")
        print("="*60)
        
        # Get dataframes
        print("\n4. Extracting data...")
        
        # Kills dataframe
        if hasattr(dem, 'kills') and dem.kills is not None:
            kills_df = dem.kills.to_pandas()
            print(f"\n   Kills: {len(kills_df)} entries")
            if len(kills_df) > 0:
                print("   Sample kills data:")
                print(kills_df.head())
        else:
            print("\n   No kills data available")
        
        # Damages dataframe
        if hasattr(dem, 'damages') and dem.damages is not None:
            damages_df = dem.damages.to_pandas()
            print(f"\n   Damages: {len(damages_df)} entries")
            if len(damages_df) > 0:
                print("   Sample damages data:")
                print(damages_df.head())
        else:
            print("\n   No damages data available")
        
        # Rounds dataframe
        if hasattr(dem, 'rounds') and dem.rounds is not None:
            rounds_df = dem.rounds.to_pandas()
            print(f"\n   Rounds: {len(rounds_df)} entries")
            if len(rounds_df) > 0:
                print("   Sample rounds data:")
                print(rounds_df.head())
        else:
            print("\n   No rounds data available")
        
        # Additional information
        print("\n" + "="*60)
        print("AVAILABLE DATA ATTRIBUTES")
        print("="*60)
        available_attrs = [attr for attr in dir(dem) if not attr.startswith('_')]
        for attr in available_attrs:
            if not callable(getattr(dem, attr, None)):
                print(f"   - {attr}")
        
        return True
        
    except Exception as e:
        print(f"\nERROR: Failed to parse demo")
        print(f"Error details: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def build_summary_text(dem: "Demo") -> str:
    """
    Build a concise text summary from a parsed Demo object for UI display.
    """
    lines = []
    lines.append("awpy CS2 Demo Summary")
    lines.append("".join(["=", "=" * 20]))

    # Rounds
    if hasattr(dem, "rounds") and dem.rounds is not None:
        try:
            rounds_df = dem.rounds.to_pandas()
            lines.append(f"Rounds: {len(rounds_df)}")
        except Exception:
            lines.append("Rounds: unavailable")
    else:
        lines.append("Rounds: unavailable")

    # Kills
    if hasattr(dem, "kills") and dem.kills is not None:
        try:
            kills_df = dem.kills.to_pandas()
            lines.append(f"Kills: {len(kills_df)}")
            if len(kills_df) > 0:
                sample_cols = [c for c in [
                    "tick", "round", "attackerName", "victimName", "weapon"
                ] if c in kills_df.columns]
                lines.append("\nSample Kills (top 5):")
                lines.append(kills_df[sample_cols].head(5).to_string(index=False))
        except Exception:
            lines.append("Kills: unavailable")
    else:
        lines.append("Kills: unavailable")

    # Damages
    if hasattr(dem, "damages") and dem.damages is not None:
        try:
            damages_df = dem.damages.to_pandas()
            lines.append(f"Damages: {len(damages_df)}")
            if len(damages_df) > 0:
                sample_cols = [c for c in [
                    "tick", "round", "attackerName", "victimName", "hpDamage", "weapon"
                ] if c in damages_df.columns]
                lines.append("\nSample Damages (top 5):")
                lines.append(damages_df[sample_cols].head(5).to_string(index=False))
        except Exception:
            lines.append("Damages: unavailable")
    else:
        lines.append("Damages: unavailable")

    return "\n".join(lines)


def parse_demo_minimal(demo_path: str) -> str:
    """
    Parse a demo and return a concise summary string or raise on error.
    """
    if not os.path.exists(demo_path):
        raise FileNotFoundError(f"Demo file not found: {demo_path}")

    dem = Demo(demo_path)
    dem.parse()
    return build_summary_text(dem)


def run_gui():
    """Launch a minimal UI to choose a .dem file and show parsed results."""
    root = tk.Tk()
    root.title("awpy Demo Tester")
    root.geometry("820x560")

    selected_path = tk.StringVar(value="")

    def choose_file():
        path = filedialog.askopenfilename(
            title="Select CS2 demo (.dem)",
            filetypes=[("CS2 Demo", "*.dem"), ("All Files", "*.*")],
        )
        if path:
            selected_path.set(path)
            parse_btn.config(state=tk.NORMAL)

    def set_busy(busy: bool):
        if busy:
            parse_btn.config(state=tk.DISABLED)
            browse_btn.config(state=tk.DISABLED)
        else:
            parse_btn.config(state=tk.NORMAL if selected_path.get() else tk.DISABLED)
            browse_btn.config(state=tk.NORMAL)

    def do_parse():
        path = selected_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a .dem file first.")
            return

        def worker():
            try:
                summary = parse_demo_minimal(path)
                output_text.configure(state=tk.NORMAL)
                output_text.delete("1.0", tk.END)
                output_text.insert(tk.END, summary)
                output_text.configure(state=tk.DISABLED)
            except Exception as e:
                messagebox.showerror("Parse error", f"Failed to parse demo:\n{type(e).__name__}: {e}")
            finally:
                set_busy(False)

        set_busy(True)
        threading.Thread(target=worker, daemon=True).start()

    # Top controls
    top_frame = tk.Frame(root)
    top_frame.pack(fill=tk.X, padx=12, pady=12)

    browse_btn = tk.Button(top_frame, text="Browse .dem", command=choose_file)
    browse_btn.pack(side=tk.LEFT)

    path_entry = tk.Entry(top_frame, textvariable=selected_path)
    path_entry.configure(state="readonly")
    path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

    parse_btn = tk.Button(top_frame, text="Parse Demo", command=do_parse, state=tk.DISABLED)
    parse_btn.pack(side=tk.LEFT)

    # Output area
    output_frame = tk.Frame(root)
    output_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

    output_text = tk.Text(output_frame, wrap=tk.NONE)
    output_text_scroll_y = tk.Scrollbar(output_frame, orient=tk.VERTICAL, command=output_text.yview)
    output_text_scroll_x = tk.Scrollbar(output_frame, orient=tk.HORIZONTAL, command=output_text.xview)
    output_text.configure(yscrollcommand=output_text_scroll_y.set, xscrollcommand=output_text_scroll_x.set)

    output_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    output_text_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
    output_text_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

    # Initial hint
    output_text.insert(tk.END, "Select a .dem file to parse. A short summary will appear here.")
    output_text.configure(state=tk.DISABLED)

    root.mainloop()


def download_demo_example():
    """
    Example function showing how you might download a demo
    Note: awpy doesn't download demos directly - you need to download .dem files first
    """
    print("\n" + "="*60)
    print("DOWNLOADING DEMOS")
    print("="*60)
    print("\nawpy does not download demos directly.")
    print("You need to download .dem files manually or use other tools.")
    print("\nWays to get demo files:")
    print("1. FACEIT: Go to match page → Click 'Watch Demo'")
    print("2. HLTV.org: Download professional match demos")
    print("3. Steam: Download your own match demos from game")
    print("\nOnce you have the .dem file, use test_demo_parsing() to analyze it.")


def main():
    """Launch GUI by default; pass --cli for console mode test."""
    if "--cli" in sys.argv:
        print("="*60)
        print("AWPY TEST SCRIPT - CS2 Demo Parser (CLI)")
        print("="*60)
        demo_path = input("\nEnter path to .dem file: ").strip()
        if not demo_path:
            print("No path provided.")
            return
        ok = test_demo_parsing(demo_path)
        print("\nDONE" if ok else "\nFAILED")
    else:
        run_gui()


if __name__ == "__main__":
    main()


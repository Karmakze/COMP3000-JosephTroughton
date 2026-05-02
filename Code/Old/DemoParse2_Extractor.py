"""
DemoParse2 Extractor - Extract kill window features using demoparser2 library.

This script parses CS2 demo files and extracts player view angles (pitch/yaw)
around each kill for aimbot/aim assist detection.
"""

import math
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from demoparser2 import DemoParser

BASE_DIR = Path(__file__).resolve().parent.parent


def _normalize_angle_diff(a: float, b: float) -> float:
    """Shortest signed diff (degrees) a - b normalized to [-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


def parse_demo(demo_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Parse a .dem file using demoparser2 and return tick data and kill events.
    """
    if not demo_path.exists():
        raise FileNotFoundError(f"Demo file not found: {demo_path}")
    
    print(f"Parsing demo: {demo_path}")
    parser = DemoParser(str(demo_path))
    
    # Parse tick data with positions and view angles
    # demoparser2 uses these prop names for view angles
    tick_props = [
        "X", "Y", "Z",           # Position
        "pitch", "yaw",          # View angles (eye_angles)
        "health",
        "team_num",
    ]
    
    print("Extracting tick data...")
    ticks_df = parser.parse_ticks(tick_props)
    print(f"  Got {len(ticks_df)} tick rows")
    print(f"  Columns: {list(ticks_df.columns)}")
    
    # Parse kill events
    print("Extracting kill events...")
    kills_df = parser.parse_event("player_death")
    print(f"  Got {len(kills_df)} kills")
    print(f"  Columns: {list(kills_df.columns)}")
    
    return ticks_df, kills_df


def extract_features(
    demo_path: str | Path,
    window: int = 32,
) -> List[Dict[str, Any]]:
 
    path = Path(demo_path)
    ticks_df, kills_df = parse_demo(path)
    
    print(f"\nTick columns: {sorted(ticks_df.columns)}")
    
    steamid_col = None
    for col in ['steamid', 'steamID', 'steam_id', 'user_id']:
        if col in ticks_df.columns:
            steamid_col = col
            break
    
    if steamid_col is None:
        print(f"ERROR: Could not find steamid column. Available: {list(ticks_df.columns)}")
        return []
    
    pos_cols = None
    for px, py, pz in [("X", "Y", "Z"), ("x", "y", "z")]:
        if all(c in ticks_df.columns for c in [px, py, pz]):
            pos_cols = (px, py, pz)
            break
    
    if pos_cols is None:
        print(f"ERROR: Could not find position columns. Available: {list(ticks_df.columns)}")
        return []
    
    px, py, pz = pos_cols
    
    have_view_angles = all(c in ticks_df.columns for c in ['pitch', 'yaw'])
    if not have_view_angles:
        print("WARNING: No view angle data (pitch/yaw) available.")
    
    attacker_col = None
    victim_col = None
    for col in ['attacker_steamid', 'attackerSteamId', 'attacker_steam_id', 'attacker']:
        if col in kills_df.columns:
            attacker_col = col
            break
    for col in ['user_steamid', 'victimSteamId', 'victim_steam_id', 'victim', 'user']:
        if col in kills_df.columns:
            victim_col = col
            break
    
    print(f"\nKills columns: {list(kills_df.columns)}")
    print(f"Using attacker column: {attacker_col}")
    print(f"Using victim column: {victim_col}")
    
    if attacker_col is None or victim_col is None:
        print("ERROR: Could not find attacker/victim columns in kills data")
        return []
    
    victim_positions = ticks_df.set_index(["tick", steamid_col])[[px, py, pz]]
    
    slices: List[Dict[str, Any]] = []
    print(f"\nProcessing {len(kills_df)} kills...")
    
    print(f"\nDEBUG - Tick steamid type: {ticks_df[steamid_col].dtype}")
    print(f"DEBUG - Tick steamid samples: {ticks_df[steamid_col].unique()[:5]}")
    print(f"DEBUG - Kill attacker type: {kills_df[attacker_col].dtype}")
    print(f"DEBUG - Kill attacker samples: {kills_df[attacker_col].unique()[:5]}")
    
    ticks_df[steamid_col] = ticks_df[steamid_col].astype(str)
    kills_df[attacker_col] = kills_df[attacker_col].astype(str)
    kills_df[victim_col] = kills_df[victim_col].astype(str)
    
    victim_positions = ticks_df.set_index(["tick", steamid_col])[[px, py, pz]]
    
    for kill_id, kill in kills_df.reset_index(drop=True).iterrows():
        tick = int(kill["tick"])
        attacker = str(kill[attacker_col])
        victim = str(kill[victim_col])
        
        if pd.isna(attacker) or attacker == 'nan' or pd.isna(victim) or victim == 'nan':
            continue
        
        attacker_slice = ticks_df[
            (ticks_df[steamid_col] == attacker)
            & (ticks_df["tick"].between(tick - window, tick + window))
        ].copy()
        
        if attacker_slice.empty:
            if kill_id < 3:  
                print(f"DEBUG - Kill {kill_id}: No ticks found for attacker {attacker} at tick {tick}")
            continue
        
        slice_data = {
            "kill_id": int(kill_id),
            "tick_center": tick,
            "attacker_steamid": attacker,
            "victim_steamid": victim,
            "ticks": attacker_slice["tick"].tolist(),
            "X": attacker_slice[px].tolist(),
            "Y": attacker_slice[py].tolist(),
            "Z": attacker_slice[pz].tolist(),
        }
        
        if have_view_angles:
            slice_data["yaw"] = attacker_slice["yaw"].tolist()
            slice_data["pitch"] = attacker_slice["pitch"].tolist()
            
            delta_yaw_list = []
            delta_pitch_list = []
            
            for _, row in attacker_slice.iterrows():
                key = (row["tick"], victim)
                if key not in victim_positions.index:
                    delta_yaw_list.append(None)
                    delta_pitch_list.append(None)
                    continue
                
                vx, vy, vz = victim_positions.loc[key, [px, py, pz]]
                
                dx = vx - row[px]
                dy = vy - row[py]
                dz = vz - row[pz]
                
                desired_yaw = math.degrees(math.atan2(dy, dx))
                horiz_dist = math.hypot(dx, dy)
                desired_pitch = -math.degrees(math.atan2(dz, horiz_dist))
                
                cur_yaw = float(row["yaw"])
                cur_pitch = float(row["pitch"])
                
                delta_yaw_list.append(_normalize_angle_diff(desired_yaw, cur_yaw))
                delta_pitch_list.append(desired_pitch - cur_pitch)
            
            slice_data["deltaYaw"] = delta_yaw_list
            slice_data["deltaPitch"] = delta_pitch_list
        
        slices.append(slice_data)
    
    return slices


def main():
    demo_path = BASE_DIR / "data" / "Single Demos" / "Test Sample (LABEL!)" / "faze-vs-nrg-dust2(T1 PRO LEGIT).dem"
    
    slices = extract_features(demo_path, window=32)
    print(f"\nExtracted {len(slices)} kill windows")
    
    if slices:
        print("\nFirst kill window sample:")
        first = slices[0]
        print(f"  Kill ID: {first['kill_id']}")
        print(f"  Tick: {first['tick_center']}")
        print(f"  Attacker: {first['attacker_steamid']}")
        print(f"  Victim: {first['victim_steamid']}")
        print(f"  Ticks captured: {len(first['ticks'])}")
        if 'yaw' in first:
            print(f"  Yaw range: {min(first['yaw']):.1f}° to {max(first['yaw']):.1f}°")
            print(f"  Pitch range: {min(first['pitch']):.1f}° to {max(first['pitch']):.1f}°")


if __name__ == "__main__":
    main()


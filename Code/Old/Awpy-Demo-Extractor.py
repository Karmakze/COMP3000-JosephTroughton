import math
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from awpy import Demo

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_demo(demo_path: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], "Demo"]:
    if not demo_path.exists():
        raise FileNotFoundError(f"Demo file not found: {demo_path}")
    
    print(f"Parsing demo: {demo_path}")
    dem = Demo(str(demo_path))
    dem.parse(player_props=["health", "armor_value", "pitch", "yaw"])
    print("Demo parsed successfully!")
    
    print("\nAvailable Demo attributes:")
    available_attrs = [attr for attr in dir(dem) if not attr.startswith('_')]
    for attr in available_attrs:
        obj = getattr(dem, attr, None)
        if obj is not None and not callable(obj):
            try:
                if hasattr(obj, 'to_pandas'):
                    df = obj.to_pandas()
                    print(f"  - {attr}: DataFrame with {len(df)} rows, columns: {list(df.columns)}")
                else:
                    print(f"  - {attr}: {type(obj).__name__}")
            except Exception as e:
                print(f"  - {attr}: (error: {e})")
    
    ticks_df = None
    if hasattr(dem, 'ticks') and dem.ticks is not None:
        ticks_df = dem.ticks.to_pandas()
    
    events: dict[str, pd.DataFrame] = {}
    
    if hasattr(dem, 'kills') and dem.kills is not None:
        kills_df = dem.kills.to_pandas()
        col_renames = {}
        if 'attackerSteamID' in kills_df.columns:
            col_renames['attackerSteamID'] = 'attacker_steamid'
        if 'attacker_steamid' not in kills_df.columns and 'attackerSteamId' in kills_df.columns:
            col_renames['attackerSteamId'] = 'attacker_steamid'
        if 'victimSteamID' in kills_df.columns:
            col_renames['victimSteamID'] = 'victim_steamid'
        if 'victim_steamid' not in kills_df.columns and 'victimSteamId' in kills_df.columns:
            col_renames['victimSteamId'] = 'victim_steamid'
        kills_df = kills_df.rename(columns=col_renames)
        events['player_death'] = kills_df
        print(f"\nKills DataFrame columns: {list(kills_df.columns)}")
    
    if hasattr(dem, 'damages') and dem.damages is not None:
        events['damages'] = dem.damages.to_pandas()
    
    if hasattr(dem, 'rounds') and dem.rounds is not None:
        events['rounds'] = dem.rounds.to_pandas()
    
    return ticks_df, events, dem


def _normalize_angle_diff(a: float, b: float) -> float:
    # Shortest signed diff (degrees) a - b normalized to [-180, 180].
    return (a - b + 180.0) % 360.0 - 180.0


def extract_features(
    demo_path: str | Path,
    window: int = 32,
) -> List[Dict[str, Any]]:

    path = Path(demo_path)
    ticks_df, events, dem = _load_demo(path)
    
    if ticks_df is None:
        print("No tick data available - listing kills only")
        if "player_death" in events:
            kills_df = events["player_death"]
            print(f"\nTotal kills in demo: {len(kills_df)}")
            print(kills_df.head(10))
        return []
    
    print(f"\nAvailable tick columns: {sorted(ticks_df.columns)}")
    
    col_mapping = {
        'steamID': 'steamid',
        'steamId': 'steamid',
        'viewX': 'yaw',
        'viewY': 'pitch',
    }
    ticks_df = ticks_df.rename(columns={k: v for k, v in col_mapping.items() if k in ticks_df.columns})
    
    pos_candidates = [("X", "Y", "Z"), ("x", "y", "z"), ("pos_x", "pos_y", "pos_z")]
    have_pos = None
    for px, py, pz in pos_candidates:
        if {px, py, pz}.issubset(ticks_df.columns):
            have_pos = (px, py, pz)
            break

    if have_pos is None:
        raise KeyError(
            f"Could not find position columns among {pos_candidates}. "
            f"Available: {sorted(ticks_df.columns)}"
        )
    
    px, py, pz = have_pos
    
    have_view_angles = {"pitch", "yaw"}.issubset(ticks_df.columns)
    if not have_view_angles:
        print("\nWARNING: No view angle data (pitch/yaw) available in tick data.")
        print("Will extract position-based kill windows only.")

    victim_positions = ticks_df.set_index(["tick", "steamid"])[[px, py, pz]]

    if "player_death" not in events:
        raise KeyError("No 'player_death' events found")

    kills_df = events["player_death"].copy()
    print(f"\nKills columns available: {list(kills_df.columns)}")
    
    attacker_col = None
    victim_col = None
    for col in ['attacker_steamid', 'attackerSteamId', 'attacker_steam_id']:
        if col in kills_df.columns:
            attacker_col = col
            break
    for col in ['victim_steamid', 'victimSteamId', 'victim_steam_id']:
        if col in kills_df.columns:
            victim_col = col
            break
    
    if attacker_col is None or victim_col is None:
        print(f"Could not find attacker/victim steamid columns. Available: {list(kills_df.columns)}")
        return []

    slices: List[Dict[str, Any]] = []
    
    print(f"\nProcessing {len(kills_df)} kills...")

    for kill_id, kill in kills_df.reset_index(drop=True).iterrows():
        tick = int(kill["tick"])
        attacker = kill[attacker_col]
        victim = kill[victim_col]

        if pd.isna(attacker) or pd.isna(victim):
            continue

        attacker_slice = ticks_df[
            (ticks_df["steamid"] == attacker)
            & (ticks_df["tick"].between(tick - window, tick + window))
        ].copy()

        if attacker_slice.empty:
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
            def crosshair_delta(row: pd.Series) -> pd.Series:
                key = (row["tick"], victim)
                if key not in victim_positions.index:
                    return pd.Series({"deltaYaw": None, "deltaPitch": None})

                vx, vy, vz = victim_positions.loc[key, [px, py, pz]]

                dx = vx - row[px]
                dy = vy - row[py]
                dz = vz - row[pz]

                desired_yaw = math.degrees(math.atan2(dy, dx))
                horiz_dist = math.hypot(dx, dy)
                desired_pitch = -math.degrees(math.atan2(dz, horiz_dist))

                cur_yaw = float(row["yaw"])
                cur_pitch = float(row["pitch"])

                return pd.Series(
                    {
                        "deltaYaw": _normalize_angle_diff(desired_yaw, cur_yaw),
                        "deltaPitch": desired_pitch - cur_pitch,
                    }
                )

            deltas = attacker_slice.apply(crosshair_delta, axis=1)
            slice_data["deltaYaw"] = deltas["deltaYaw"].tolist()
            slice_data["deltaPitch"] = deltas["deltaPitch"].tolist()
            slice_data["yaw"] = attacker_slice["yaw"].tolist()
            slice_data["pitch"] = attacker_slice["pitch"].tolist()
        
        slices.append(slice_data)

    return slices


def main():
    demo_path = BASE_DIR / "data" / "Single Demos" / "Test Sample (LABEL!)" / "faze-vs-nrg-dust2(T1 PRO LEGIT).dem"
    slices = extract_features(demo_path, window=32)
    print(f"Extracted {len(slices)} kill windows")
    if slices:
        print(slices[0])


if __name__ == "__main__":
    main()

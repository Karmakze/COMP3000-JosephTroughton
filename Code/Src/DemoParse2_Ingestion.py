"""
Cheat Detection Inference Script

Parses a CS2 demo file and runs the trained XGBoost model to detect
potential cheaters based on player behavior patterns.

Usage:
    python Src/DemoParse2-Ingestion.py path/to/demo.dem
    python Src/DemoParse2-Ingestion.py path/to/demo.dem --threshold 0.7
"""

import json
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import load
from demoparser2 import DemoParser

BASE_DIR = Path(__file__).resolve().parent.parent

# Features required by the model (must match training)
FEATURE_COLS = [
    "pitch",
    "yaw",
    "usercmd_viewangle_x",
    "usercmd_viewangle_y",
    "usercmd_mouse_dx",
    "usercmd_mouse_dy",
    "velocity",
    "velocity_X",
    "velocity_Y",
    "velocity_Z",
    "is_scoped",
    "is_walking",
    "spotted",
    "is_airborne",
    "is_alive",
    "shots_fired",
    "accuracy_penalty",
    "usercmd_forward_move",
    "usercmd_left_move",
    "FIRE",
    "RELOAD",
    "ZOOM",
]


def load_model():
    model_path = BASE_DIR / "data" / "outputs" / "xgb_cs2cd_cheat_detector.joblib"
    features_path = BASE_DIR / "data" / "outputs" / "feature_names.json"
    
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found at {model_path}\n"
            "Run XGBoost-Training-Model.py first to train the model."
        )
    
    model = load(model_path)
    
    with open(features_path, "r") as f:
        feature_names = json.load(f)
    
    print(f"Loaded model from {model_path}")
    print(f"Model expects {len(feature_names)} features")
    
    return model, feature_names


def parse_demo(demo_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, int | None]:
    """Parse demo: tick data, kill events, optional player_hurt, and round count."""
    if not demo_path.exists():
        raise FileNotFoundError(f"Demo file not found: {demo_path}")
    
    parser = DemoParser(str(demo_path))
    props_to_parse = FEATURE_COLS + ["steamid", "name"]
    df = parser.parse_ticks(props_to_parse)
    kills_df = parser.parse_event("player_death")
    
    hurts_df = None
    num_rounds = None
    try:
        h = parser.parse_event("player_hurt")
        if h is not None and len(h) > 0:
            hurts_df = h
    except Exception:
        pass
    try:
        re = parser.parse_event("round_end")
        if re is not None and len(re) > 0:
            num_rounds = int(len(re))
    except Exception:
        pass
    
    return df, kills_df, hurts_df, num_rounds


def prepare_features(df: pd.DataFrame, feature_names: list) -> np.ndarray:
    """
    Prepare features for prediction, including engineered features.
    Must match the feature engineering from training.
    """
    X = df[FEATURE_COLS].copy()
    
    # Add engineered features (same as training)
    if "usercmd_mouse_dx" in X.columns and "usercmd_mouse_dy" in X.columns:
        X["mouse_velocity"] = np.sqrt(
            X["usercmd_mouse_dx"].fillna(0) ** 2 + 
            X["usercmd_mouse_dy"].fillna(0) ** 2
        )
    
    if "pitch" in X.columns:
        X["abs_pitch"] = X["pitch"].abs()
    
    if "yaw" in X.columns:
        X["abs_yaw"] = X["yaw"].abs()
    
    if "usercmd_viewangle_x" in X.columns and "pitch" in X.columns:
        X["viewangle_pitch_diff"] = (X["usercmd_viewangle_x"] - X["pitch"]).abs()
    
    if "usercmd_viewangle_y" in X.columns and "yaw" in X.columns:
        X["viewangle_yaw_diff"] = (X["usercmd_viewangle_y"] - X["yaw"]).abs()
    
    if "FIRE" in X.columns and "velocity" in X.columns:
        X["fire_while_moving"] = (X["FIRE"].fillna(0).astype(int) * X["velocity"].fillna(0))
    
    # Handle missing values
    X = X.fillna(0)
    
    # Convert booleans to int
    for col in X.columns:
        if X[col].dtype == bool or X[col].dtype == "boolean":
            X[col] = X[col].astype(int)
        if X[col].dtype == object:
            try:
                X[col] = X[col].astype(float)
            except:
                X[col] = 0
    
    # Ensure column order matches training
    X = X[feature_names]
    
    return X.values.astype(np.float32)


def analyze_player(
    player_name: str,
    player_probs: np.ndarray,
    threshold: float = 0.5,
) -> dict:
    return {
        "name": player_name,
        "total_ticks": len(player_probs),
        "mean_probability": float(player_probs.mean()),
        "max_probability": float(player_probs.max()),
        "min_probability": float(player_probs.min()),
        "std_probability": float(player_probs.std()),
        "ticks_above_threshold": int((player_probs > threshold).sum()),
        "percent_above_threshold": float((player_probs > threshold).mean() * 100),
    }


def run_ingestion(demo_path: str, threshold: float = 0.5):
    demo_path = Path(demo_path)
    
    # Load model
    model, feature_names = load_model()
    
    # Parse demo (ticks + kill events + optional hurt events + round count)
    df, kills_df, hurts_df, num_rounds = parse_demo(demo_path)
    
    # Check for missing columns
    missing_cols = set(FEATURE_COLS) - set(df.columns)
    if missing_cols:
        print(f"\nWARNING: Missing columns in demo: {missing_cols}")
        print("These will be filled with zeros, which may affect accuracy.")
        for col in missing_cols:
            df[col] = 0
    
    # Prepare features
    X = prepare_features(df, feature_names)
    
    # Run predictions
    predictions = model.predict(X)
    probabilities = model.predict_proba(X)[:, 1]
    
    df["prediction"] = predictions
    df["cheat_probability"] = probabilities
    
    # Analyze per-player results
    print(f"\n{'='*60}")
    print("RESULTS BY PLAYER")
    print(f"{'='*60}")
    print(f"(Threshold: {threshold})")
    print()
    
    results = []
    for player_name in df["name"].unique():
        player_mask = df["name"] == player_name
        player_probs = df.loc[player_mask, "cheat_probability"].values
        
        result = analyze_player(player_name, player_probs, threshold)
        results.append(result)
    
    # Sort by mean probability (most suspicious first)
    results.sort(key=lambda x: x["mean_probability"], reverse=True)
    
    return df, results, kills_df, hurts_df, num_rounds


def main():
    parser = argparse.ArgumentParser(
        description="Run cheat detection on a CS2 demo file"
    )
    parser.add_argument(
        "demo_path",
        type=str,
        help="Path to the .dem file to analyze"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Probability threshold for flagging suspicious behavior (default: 0.5)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to save detailed results as CSV"
    )
    
    args = parser.parse_args()
    
    df, results, kills_df, hurts_df, num_rounds = run_ingestion(args.demo_path, args.threshold)
    
    if args.output:
        output_path = Path(args.output)
        df.to_csv(output_path, index=False)
        print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()

"""
XGBoost Cheat Detection Model trained on CS2CD dataset.
Dataset: https://huggingface.co/datasets/CS2CD/CS2CD.Counter-Strike_2_Cheat_Detection

Training approach:
1. Load "no_cheater_present" data as legit samples (97.2% verified clean) Y
2. Load "with_cheater_present" data and use JSON metadata to identify VAC-banned cheaters only 55% of no_cheater_present samples are accurate due to trust factor system Y
3. Train model to distinguish cheater behavior from legit behavior Y 
5. bias towards legit samples 

"""
import gc
import json
import pandas as pd
import numpy as np
from pathlib import Path
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.utils import shuffle
from huggingface_hub import hf_hub_download, list_repo_files
from tqdm import tqdm

# Dataset info
DATASET_REPO = "CS2CD/CS2CD.Counter-Strike_2_Cheat_Detection"

# Feature columns relevant for cheat detection
FEATURE_COLS = [
    # View angles (key for aimbot detection)
    "pitch",
    "yaw",
    "usercmd_viewangle_x",
    "usercmd_viewangle_y",
    # Mouse movement (key for aim assist detection) 
    "usercmd_mouse_dx",
    "usercmd_mouse_dy",
    # Velocity info
    "velocity",
    "velocity_X",
    "velocity_Y",
    "velocity_Z",
    # Player state
    "is_scoped",
    "is_walking",
    "spotted",
    "is_airborne",
    "is_alive",
    # Shooting info
    "shots_fired",
    "accuracy_penalty",
    # Movement commands
    "usercmd_forward_move",
    "usercmd_left_move",
    # Actions
    "FIRE",
    "RELOAD",
    "ZOOM",
]


def list_dataset_files() -> dict:
    print("Fetching file list from Hugging Face...")
    files = list_repo_files(DATASET_REPO, repo_type="dataset") # ~1592 files
    
    
    no_cheater_files = {"parquet": [], "json": []}
    with_cheater_files = {"parquet": [], "json": []}

    
    # Use Parquet and JSON files
    for f in files:
        if "no_cheater_present" in f:
            if f.endswith(".parquet"):
                no_cheater_files["parquet"].append(f)
            elif f.endswith(".json"):
                no_cheater_files["json"].append(f)
        elif "with_cheater_present" in f:
            if f.endswith(".parquet"):
                with_cheater_files["parquet"].append(f)
            elif f.endswith(".json"):
                with_cheater_files["json"].append(f)
    
    # for consistency
    for d in [no_cheater_files, with_cheater_files]:
        d["parquet"].sort()
        d["json"].sort()
    
    print(f"Found {len(no_cheater_files['parquet'])} no-cheater matches")
    print(f"Found {len(with_cheater_files['parquet'])} with-cheater matches")
    
    return {
        "no_cheater": no_cheater_files,
        "with_cheater": with_cheater_files,
    }


def download_file(filename: str, cache_dir: str = "data/cs2cd_cache") -> str:
    local_path = hf_hub_download(
        repo_id=DATASET_REPO,
        filename=filename,
        repo_type="dataset",
        cache_dir=cache_dir,
    )
    return local_path

# Anomised but required for cheater Reference
def extract_cheater_steamids(json_path: str) -> set:
    with open(json_path, "r") as f:
        metadata = json.load(f)
    
    cheater_steamids = set()
    
    if "cheaters" in metadata:
        for entry in metadata["cheaters"]:
            if isinstance(entry, dict) and "steamid" in entry:
                cheater_steamids.add(entry["steamid"])
            elif isinstance(entry, str):
                cheater_steamids.add(entry)
    
    return cheater_steamids


def load_legit_samples(
    file_list: dict,
    n_matches: int = 50,
    samples_per_match: int = 1000,
    cache_dir: str = "data/cs2cd_cache",
) -> pd.DataFrame:
    print(f"\nLoading {n_matches} legit matches...")
    
    parquet_files = file_list["no_cheater"]["parquet"][:n_matches]
    
    # LOAD ONLY NEEDED COLUMNS
    cols_to_load = FEATURE_COLS + ["steamid"]
    
    all_samples = []
    
    for parquet_file in tqdm(parquet_files, desc="Loading legit matches"):
        try:
            parquet_path = download_file(parquet_file, cache_dir)
            
            df = pd.read_parquet(parquet_path, columns=cols_to_load)
            
            if len(df) > samples_per_match:
                df = df.sample(n=samples_per_match, random_state=42)
            
            df["label"] = 0
            
            all_samples.append(df)
            
            # Free memory !IMPORTANT!
            del df
            
        except Exception as e:
            print(f"  Error loading {parquet_file}: {e}")
            continue
    
    if not all_samples:
        raise ValueError("No legit samples loaded!")
    
    combined = pd.concat(all_samples, ignore_index=True)
    print(f"Loaded {len(combined):,} legit samples from {len(all_samples)} matches")
    
    return combined


def load_cheater_samples(
    file_list: dict,
    n_matches: int = 50,
    samples_per_cheater: int = 500,
    cache_dir: str = "data/cs2cd_cache",
) -> pd.DataFrame:
    print(f"\nLoading {n_matches} cheater matches...")
    
    parquet_files = file_list["with_cheater"]["parquet"][:n_matches]
    json_files = file_list["with_cheater"]["json"][:n_matches]
    
    # LOAD ONLY NEEDED COLUMNS
    cols_to_load = FEATURE_COLS + ["steamid"]
    
    # Pair tick data and cheater metadata
    parquet_bases = {}
    for f in parquet_files:
        base = Path(f).stem  # "0"
        parquet_bases[base] = f
    
    json_bases = {}
    for f in json_files:
        base = Path(f).stem  # "0"
        json_bases[base] = f
    
    all_cheater_samples = []
    matches_with_cheaters = 0
    
    for base in tqdm(list(parquet_bases.keys())[:n_matches], desc="Loading cheater matches"):
        if base not in json_bases:
            continue
        
        parquet_file = parquet_bases[base]
        json_file = json_bases[base]
        
        try:
            json_path = download_file(json_file, cache_dir)
            cheater_steamids = extract_cheater_steamids(json_path)
            
            if not cheater_steamids:
                continue
            
            # Load Only Needed Columns
            parquet_path = download_file(parquet_file, cache_dir)
            df = pd.read_parquet(parquet_path, columns=cols_to_load)
            
            if "steamid" in df.columns:
                df["steamid"] = df["steamid"].astype(str)
                cheater_df = df[df["steamid"].isin(cheater_steamids)].copy()
                
                # Free Memory !IMPORTANT!
                del df
                
                if len(cheater_df) > 0:
                    # Sample
                    if len(cheater_df) > samples_per_cheater:
                        cheater_df = cheater_df.sample(n=samples_per_cheater, random_state=42)
                    
                    cheater_df["label"] = 1
                    all_cheater_samples.append(cheater_df)
                    matches_with_cheaters += 1
            
        except Exception as e:
            print(f"  Error loading {parquet_file}: {e}")
            continue
    
    if not all_cheater_samples:
        raise ValueError("No cheater samples loaded!")
    
    combined = pd.concat(all_cheater_samples, ignore_index=True)
    print(f"Loaded {len(combined):,} cheater samples from {matches_with_cheaters} matches")
    
    return combined


def prepare_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list]:
    # Select available feature columns
    available_cols = [col for col in FEATURE_COLS if col in df.columns]
    print(f"\nUsing {len(available_cols)} base features")
    
    if len(available_cols) == 0:
        print("Available columns in dataset:")
        print(sorted(df.columns.tolist())[:30])
        raise ValueError("No matching feature columns found!")
    
    X = df[available_cols].copy()
    feature_names = list(available_cols)
    
    # ------- Add additional features -------
    
    # Mouse velocity magnitude (aimbot snaps show extreme values)
    if "usercmd_mouse_dx" in X.columns and "usercmd_mouse_dy" in X.columns:
        X["mouse_velocity"] = np.sqrt(
            X["usercmd_mouse_dx"].fillna(0) ** 2 + 
            X["usercmd_mouse_dy"].fillna(0) ** 2
        )
        feature_names.append("mouse_velocity")
    
    # Absolute view angles
    if "pitch" in X.columns:
        X["abs_pitch"] = X["pitch"].abs()
        feature_names.append("abs_pitch")
    
    if "yaw" in X.columns:
        X["abs_yaw"] = X["yaw"].abs()
        feature_names.append("abs_yaw")
    
    # View angle deltas 
    if "usercmd_viewangle_x" in X.columns and "pitch" in X.columns:
        X["viewangle_pitch_diff"] = (X["usercmd_viewangle_x"] - X["pitch"]).abs()
        feature_names.append("viewangle_pitch_diff")
    
    if "usercmd_viewangle_y" in X.columns and "yaw" in X.columns:
        X["viewangle_yaw_diff"] = (X["usercmd_viewangle_y"] - X["yaw"]).abs()
        feature_names.append("viewangle_yaw_diff")
    
    # Movement while shooting (aimbots often fire while moving unnaturally)
    if "FIRE" in X.columns and "velocity" in X.columns:
        X["fire_while_moving"] = (X["FIRE"].fillna(0).astype(int) * X["velocity"].fillna(0))
        feature_names.append("fire_while_moving")
    
    # ------ Clean up -------
    
    # Handle missing values
    X = X.fillna(0)
    
    
    for col in X.columns:
        if X[col].dtype == bool or X[col].dtype == "boolean":
            X[col] = X[col].astype(int)

        if X[col].dtype == object:
            try:
                X[col] = X[col].astype(float)
            except:
                X[col] = 0
    
    # Get labels
    y = df["label"].astype(int).values
    
    print(f"Final feature count: {len(feature_names)}")
    
    return X.values.astype(np.float32), y, feature_names


def train_model(
    X: np.ndarray, 
    y: np.ndarray, 
    feature_names: list,
) -> XGBClassifier:
    """Train XGBoost classifier for cheat detection."""
    
    # Shuffle and split
    X, y = shuffle(X, y, random_state=42)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=7, stratify=y
    )
    
    print(f"\n{'='*50}")
    print("Training Configuration")
    print(f"{'='*50}")
    print(f"Training set: {len(X_train):,} samples")
    print(f"Test set: {len(X_test):,} samples")
    print(f"Cheater ratio in train: {y_train.mean():.2%}")
    print(f"Cheater ratio in test: {y_test.mean():.2%}")
    
    # Handle class imbalance
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0
    print(f"Class weight ratio: {scale_pos_weight:.2f}")
    
    model = XGBClassifier(
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        reg_alpha=0.1,
        scale_pos_weight=scale_pos_weight,
        n_jobs=-1,
        tree_method="hist",  # AMD GPU friendly confirm with Nvidia GPU
        random_state=42,
        eval_metric=["auc", "logloss"],
        early_stopping_rounds=50,
    )
    
    print(f"\n{'='*50}")
    print("Training XGBoost Model")
    print(f"{'='*50}")
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, y_test)],
        verbose=True,
    )
    
    # ------- Evaluation -------
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    
    print(f"\n{'='*50}")
    print("Model Evaluation")
    print(f"{'='*50}")
    
    print("\nClassification Report:")
    print(classification_report(
        y_test, y_pred, 
        digits=3, 
        target_names=["Legit", "Cheater"]
    ))
    
    print("Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  TN={cm[0,0]:,}  FP={cm[0,1]:,}")
    print(f"  FN={cm[1,0]:,}  TP={cm[1,1]:,}")
    
    auc = roc_auc_score(y_test, y_pred_proba)
    print(f"\nROC-AUC Score: {auc:.4f}")
    
    # ------- Feature importance -------
    print(f"\n{'='*50}")
    print("Top 15 Feature Importances")
    print(f"{'='*50}")
    importance_df = pd.DataFrame({
        "feature": feature_names,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)
    print(importance_df.head(15).to_string(index=False))
    
    return model


def main():
    # Setup
    output_dir = Path("data/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = "data/cs2cd_cache"
    
    print("="*60)
    print("CS2CD Cheat Detection Model Training")
    print("="*60)
    
    file_list = list_dataset_files()
    
    
    legit_df = load_legit_samples(
        file_list,
        n_matches=200,            # Number of matches to sample from
        samples_per_match=1000,  # Ticks per match ~15k total
        cache_dir=cache_dir,
    )
    
    
    cheater_df = load_cheater_samples(
        file_list,
        n_matches=200,
        samples_per_cheater=1000,  # ~15k total
        cache_dir=cache_dir,
    )
    
    print("\nCombining datasets...")
    df = pd.concat([legit_df, cheater_df], ignore_index=True)
    
    # Free memory from individual dataframes !IMPORTANT!
    del legit_df, cheater_df
    gc.collect()
    
    print(f"Total samples: {len(df):,}")
    print(f"  Legit: {(df['label'] == 0).sum():,}")
    print(f"  Cheater: {(df['label'] == 1).sum():,}")
    
    # Prepare features
    X, y, feature_names = prepare_features(df)
    
    # Free the raw dataframe !IMPORTANT!
    del df
    gc.collect()
    
    print(f"\nFeature matrix shape: {X.shape}")
    
    model = train_model(X, y, feature_names)
    
    from joblib import dump
    
    model_path = output_dir / "xgb_cs2cd_cheat_detector.joblib"
    dump(model, model_path)
    print(f"\n✓ Saved model → {model_path}")
    
    features_path = output_dir / "feature_names.json"
    with open(features_path, "w") as f:
        json.dump(feature_names, f, indent=2)
    print(f"✓ Saved features → {features_path}")
    
    print("\n" + "="*60)
    print("Training Complete!")
    print("="*60)
    print(f"\nTo use this model for prediction:")
    print(f"  from joblib import load")
    print(f"  model = load('{model_path}')")
    print(f"  prediction = model.predict(features)")


if __name__ == "__main__":
    main()

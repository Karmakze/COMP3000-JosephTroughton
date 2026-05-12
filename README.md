
# Cheat Detection in Competitive Games Through Machine Learning Analysis of Player Input Vectors

This project is a proof-of-concept behavioural cheat detection framework for Counter-Strike 2 (CS2). It analyses demo-derived gameplay data using a trained XGBoost model and presents suspicious player behaviour through a PyQt6 review interface.

The project is designed as a **reviewer-support tool**, not an automated banning system.

## Overview

Traditional anti-cheat systems often rely on signature detection, process monitoring, or kernel-level access. This project explores a less intrusive alternative by analysing player behaviour from recorded gameplay data.

The system parses CS2 demo files, extracts tick-level gameplay features, applies a trained machine learning model, and displays interpretable outputs such as player suspicion scores, kill-level probabilities, match statistics, and telemetry-style aim graphs.

## Features

- CS2 `.dem` / `.dem.gz` demo analysis
- Demo parsing using DemoParse2
- XGBoost-based cheat probability model
- Per-player suspicion scoring
- Per-kill cheat probability analysis
- Killfeed with killer and weapon filters
- Match statistics including kills, deaths, ADR, HS%, running%, and TTD
- Mouse movement telemetry graph
- Yaw/pitch crosshair path visualisation
- Drag-and-drop demo loading
- Persistent demo list stored in JSON
- Configurable thresholds via `.env`

## Project Structure

```text
.
├── Code/
│   ├── UI.py
│   ├── DemoParse2_Ingestion.py
│   ├── Match_Stats.py
│   ├── Player_View.py
│   ├── XGBoost-Training-Model.py
│   └── app_config.py
├── data/
│   ├── outputs/
│   │   ├── xgb_cs2cd_cheat_detector.joblib
│   │   └── feature_names.json
│   └── saved_demos.json
└── README.md

```

## Installation Guide

### Requirements

Before running the project, ensure the following are installed or available:

- Python 3.10 or newer
- Git
- A terminal or command prompt
- Counter-Strike 2 demo files (`.dem` or `.dem.gz`)
- Trained model files in `data/outputs/`:
  - `xgb_cs2cd_cheat_detector.joblib`
  - `feature_names.json`

---

### Linux Installation

Clone the repository:

```bash
git clone https://github.com/Karmakze/COMP3000-JosephTroughton.git
cd COMP3000-JosephTroughton/Code
```

Create and activate a virtual environment.

For Bash/Zsh:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

For Fish shell:

```fish
python -m venv .venv
source .venv/bin/activate.fish
```

Install dependencies:

```bash
pip install -r Requirements.txt
```

Run the application:

```bash
python3 Src/UI.py
```

---

### Windows Installation

Open PowerShell and clone the repository:

```powershell
git clone https://github.com/Karmakze/COMP3000-JosephTroughton.git
cd COMP3000-JosephTroughton/Code
```

Create a virtual environment:

```powershell
py -m venv .venv
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again:

```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt alternative:

```cmd
.venv\Scripts\activate.bat
```

Install dependencies:

```powershell
pip install -r Requirements.txt
```

Run the application:

```powershell
python Src/UI.py
```

---

### Optional Configuration

Runtime settings can be configured using a `.env` file in the project root. If no `.env` file is provided, the application will use the default values defined in `app_config.py`.

Example `.env` file:

```env
CS2CD_INGEST_THRESHOLD=0.55
CS2CD_KILL_SCORE_WINDOW_TICKS=2
CS2CD_FORGET_WINDOW_SECONDS=4.0
CS2CD_KILL_WINDOW_BASELINE_TICKS=20
CS2CD_KILL_WINDOW_POST_DEATH_TICKS=20
CS2CD_KILL_WINDOW_SEARCH_BACK_TICKS=256
CS2CD_DEFAULT_DEMO_DIR=/path/to/demo/folder
```

Windows path example:

```env
CS2CD_DEFAULT_DEMO_DIR=C:\Users\YourName\Documents\CS2Demos
```

Common options:

| Setting | Purpose |
|---|---|
| `CS2CD_INGEST_THRESHOLD` | Default suspicion threshold used during inference |
| `CS2CD_KILL_SCORE_WINDOW_TICKS` | Tick window used when smoothing per-kill score output |
| `CS2CD_FORGET_WINDOW_SECONDS` | Engagement timing window used for TTD-style calculations |
| `CS2CD_KILL_WINDOW_BASELINE_TICKS` | Number of ticks before movement start shown in the kill graph |
| `CS2CD_KILL_WINDOW_POST_DEATH_TICKS` | Number of ticks after the kill shown in the kill graph |
| `CS2CD_KILL_WINDOW_SEARCH_BACK_TICKS` | Maximum number of ticks searched before a kill |
| `CS2CD_DEFAULT_DEMO_DIR` | Default folder opened by the demo file picker |

---

### Notes

The application is intended as a reviewer-support tool. Suspicion scores should be treated as indicators for manual review, not proof of cheating.

## Licence

This project is licensed under the GNU General Public License v3.0.

This licence applies to this project’s source code only. Third-party datasets, demo files, libraries, and game assets remain subject to their own licences and terms.

import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QInputDialog, QListWidget, QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from DemoParse2_Ingestion import run_ingestion
app = QApplication([])
win = QMainWindow()

# Ribbon / menu bar with File dropdown
menubar = win.menuBar()
file_menu = menubar.addMenu("&File")

# Store demo paths mapped to their display names need to be cached in file in future 
demo_paths = {
    "Demo 1": "/home/karmakaze/Git/Single Demos/Pro/iem-krakw-2026-faze-vs-bcgame/faze-vs-bc-game-m3-ancient.dem",
    "Demo 2": "/home/karmakaze/Git/Single Demos/Pro/iem-krakw-2026-faze-vs-bcgame/faze-vs-bc-game-m2-nuke.dem",
    "Demo 3": "/home/karmakaze/Git/Single Demos/Pro/iem-krakw-2026-faze-vs-bcgame/faze-vs-bc-game-m1-dust2.dem",

} # TEMP PATHs

def on_open_demo():
    path, _ = QFileDialog.getOpenFileName(win, "Open Demo", "", "Demo files (*.dem *.dem.gz)")
    if not path:
        return
    # df, results = run_ingestion(path)
    # print(df)
    # print(results)
    # Prompt Name of Demo
    name, ok = QInputDialog.getText(win, "Enter Name of Demo", "Name:")
    if not name or not ok:
        return
    # Add to selector
    selector.addItem(name)
    demo_paths[name] = path

def on_demo_selected(item):
    demo_name = item.text()
    if demo_name not in demo_paths:
        return
    path = demo_paths[demo_name]
    # TODO: Load and display the selected demo
    print(f"Selected demo: {demo_name} at {path}")
    # df, results = run_ingestion(path)
    # Update UI with demo data


def run_ingestion_analysis():
    item = selector.currentItem()
    if item is None:
        return

    demo_name = item.text()
    path = demo_paths.get(demo_name)
    if not path:
        return

    df, results, kills_df = run_ingestion(path)

    # Kill feed: [Killer] -> [Weapon] -> [Victim]
    kill_feed_list.clear()
    if kills_df is None or len(kills_df) == 0:
        kill_feed_list.addItem("(No kills in this demo)")
        return

    steamid_to_name = {} if "steamid" not in df.columns or "name" not in df.columns else {
        str(r["steamid"]): r["name"] or "?"
        for _, r in df[["steamid", "name"]].drop_duplicates("steamid").iterrows()
        if str(r["steamid"]) and str(r["steamid"]) != "nan"
    }

    def name_for(steamid):
        if pd.isna(steamid) or str(steamid) == "nan":
            return "?"
        return steamid_to_name.get(str(steamid), str(steamid))

    name_to_legitness = {r["name"]: (1 - r["mean_probability"]) * 100 for r in results}
    att_col = next((c for c in ["attacker_steamid", "attackerSteamId", "attacker"] if c in kills_df.columns), None)
    vic_col = next((c for c in ["user_steamid", "victimSteamId", "victim", "user"] if c in kills_df.columns), None)
    weapon_col = "weapon" if "weapon" in kills_df.columns else None

    for _, kill in kills_df.iterrows():
        killer = name_for(kill.get(att_col)) if att_col else "?"
        victim = name_for(kill.get(vic_col)) if vic_col else "?"
        weapon = (str(kill.get(weapon_col, "")).strip() if weapon_col else "") or "?"
        legitness = name_to_legitness.get(killer)
        legitness_str = f" — {legitness:.0f}% legit" if legitness is not None else ""
        kill_feed_list.addItem(f"[{killer}] -> [{weapon}] -> [{victim}]{legitness_str}")

def on_open_folder():
    path = QFileDialog.getExistingDirectory(win, "Open Demo Folder")
    if not path:
        return
    # TODO: scan folder for demos and add to selector
    pass

open_action = QAction("&Open Demo...", win)
open_action.setShortcut("Ctrl+O")
open_action.triggered.connect(on_open_demo)
file_menu.addAction(open_action)

open_folder_action = QAction("Open &Folder...", win)
open_folder_action.setShortcut("Ctrl+Shift+O")
open_folder_action.triggered.connect(on_open_folder)
file_menu.addAction(open_folder_action)

file_menu.addSeparator()

exit_action = QAction("E&xit", win)
exit_action.setShortcut("Ctrl+Q")
exit_action.triggered.connect(win.close)
file_menu.addAction(exit_action)

# Central widget with nested splitters
central = QWidget()
main_layout = QVBoxLayout(central)

button_row = QHBoxLayout()
test_ingest_button = QPushButton("Analyse Selected Demo")
test_ingest_button.clicked.connect(run_ingestion_analysis)
button_row.addWidget(test_ingest_button)
button_row.addStretch()
main_layout.addLayout(button_row)

# Horizontal splitter (left | right)
h_split = QSplitter(Qt.Orientation.Horizontal)

left_split = QSplitter(Qt.Orientation.Vertical)
selector = QListWidget()
selector.setAlternatingRowColors(True)
selector.itemClicked.connect(on_demo_selected)
left_split.addWidget(selector)
selector.addItems(list(demo_paths.keys()))
kill_feed_list = QListWidget()
kill_feed_list.setAlternatingRowColors(True)
left_split.addWidget(kill_feed_list)

right_split = QSplitter(Qt.Orientation.Vertical)
right_split.addWidget(QLabel("Player Stats & Model"))
right_split.addWidget(QLabel("Scoreboard"))

h_split.addWidget(left_split)
h_split.addWidget(right_split)
main_layout.addWidget(h_split)

win.setCentralWidget(central)
win.show()
app.exec()
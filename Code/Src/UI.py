from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QInputDialog, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from DemoParse2_Ingestion import run_ingestion
from Match_Stats import get_name_from_steamid, calc_killfeed, calc_scoreboard
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

def _fill_scoreboard(rows):
    scoreboard.setRowCount(0)
    if not rows:
        return
    headers = ["Player", "K", "D", "ADR", "HS%", "Util%", "Running%", "TTD", "Cheat%"]
    keys = ["name", "k", "d", "adr_str", "hs_str", "util_str", "running_str", "ttk_str", "cheat_str"]
    scoreboard.setRowCount(len(rows))
    for c, col in enumerate(headers):
        scoreboard.setHorizontalHeaderItem(c, QTableWidgetItem(col))
    for row_idx, row in enumerate(rows):
        for col_idx, key in enumerate(keys):
            val = row.get(key, "")
            scoreboard.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))
    scoreboard.resizeColumnsToContents()


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

    df, results, kills_df, hurts_df, num_rounds = run_ingestion(path)
    steamid_to_name = get_name_from_steamid(df)

    kill_feed_list.clear()
    for line in calc_killfeed(kills_df, df, results, steamid_to_name):
        kill_feed_list.addItem(line)

    rows = calc_scoreboard(df, results, kills_df, hurts_df, num_rounds, steamid_to_name)
    _fill_scoreboard(rows)

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
scoreboard = QTableWidget()
scoreboard.setColumnCount(9)
scoreboard.setAlternatingRowColors(True)
# All columns share horizontal space evenly and scale with the window
scoreboard.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
scoreboard.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
scoreboard.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
scoreboard.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
scoreboard.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
scoreboard.setMinimumSize(0, 0)
scoreboard.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
scoreboard.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
right_split.addWidget(scoreboard)

h_split.addWidget(left_split)
h_split.addWidget(right_split)
main_layout.addWidget(h_split)

win.setCentralWidget(central)
win.show()
app.exec()
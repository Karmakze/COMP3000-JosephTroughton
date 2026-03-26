import numpy as np
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QInputDialog, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from DemoParse2_Ingestion import run_ingestion
from Match_Stats import get_name_from_steamid, calc_killfeed, calc_scoreboard
from Player_View import build_player_view_lines, build_kill_view_lines, compute_kill_mouse_window

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except Exception:  # matplotlib optional at runtime
    Figure = None
    FigureCanvas = None
app = QApplication([])
win = QMainWindow()

# cached current demo data for click handlers
current_df = None
current_kills_df = None
current_steamid_to_name = None

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

    demo_file = Path(path).expanduser()
    if not demo_file.is_file():
        QMessageBox.warning(
            win,
            "Demo not found",
            f"No file at path for “{demo_name}”:\n\n{demo_file}\n\n"
            "It may have been moved or renamed. Use File → Open Demo and add it again, "
            "or fix the path in your demo list.",
        )
        return

    global current_df, current_kills_df, current_steamid_to_name
    try:
        df, results, kills_df, hurts_df, num_rounds = run_ingestion(str(demo_file))
    except FileNotFoundError as e:
        QMessageBox.warning(
            win,
            "Demo not found",
            str(e),
        )
        return
    except OSError as e:
        QMessageBox.critical(
            win,
            "Could not read demo",
            str(e),
        )
        return
    steamid_to_name = get_name_from_steamid(df)
    current_df = df
    current_kills_df = kills_df
    current_steamid_to_name = steamid_to_name

    kill_feed_list.clear()
    lines = calc_killfeed(kills_df, df, results, steamid_to_name)

    # attach tick/killer/victim metadata to each killfeed row (UI-only)
    att_cols = ["attacker_steamid", "attackerSteamId", "attacker"]
    vic_cols = ["user_steamid", "victimSteamId", "victim", "user"]
    att_col = next((c for c in att_cols if kills_df is not None and c in kills_df.columns), None)
    vic_col = next((c for c in vic_cols if kills_df is not None and c in kills_df.columns), None)
    tick_col = "tick" if kills_df is not None and "tick" in kills_df.columns else None

    kill_rows = list(kills_df.iterrows()) if kills_df is not None else []
    for i, line in enumerate(lines):
        kill_feed_list.addItem(line)
        lw_item = kill_feed_list.item(kill_feed_list.count() - 1)

        meta = {}
        if i < len(kill_rows):
            _, row = kill_rows[i]
            try:
                meta["kill_tick"] = int(float(row.get(tick_col))) if tick_col else None
            except (ValueError, TypeError):
                meta["kill_tick"] = None
            if att_col:
                meta["killer_name"] = steamid_to_name.get(str(row.get(att_col)), str(row.get(att_col)))
            if vic_col:
                meta["victim_name"] = steamid_to_name.get(str(row.get(vic_col)), str(row.get(vic_col)))

        lw_item.setData(Qt.ItemDataRole.UserRole, meta)

    rows = calc_scoreboard(df, results, kills_df, hurts_df, num_rounds, steamid_to_name)
    _fill_scoreboard(rows)


def _set_player_view(player_name: str):
    player_view_list.clear()
    for line in build_player_view_lines(player_name):
        player_view_list.addItem(line)


def _parse_killer_from_killfeed_line(line: str) -> str | None:
    # Expected: "[killer] -> [weapon] -> [victim] — ..."
    if not line:
        return None
    try:
        start = line.index("[") + 1
        end = line.index("]", start)
    except ValueError:
        return None
    name = line[start:end].strip()
    return name or None


def _parse_cheat_pct_from_killfeed_line(line: str) -> float | None:
    # Expected suffix: "— {xx.x}% cheat"
    if not line:
        return None
    marker = "—"
    i = line.rfind(marker)
    if i == -1:
        return None
    tail = line[i + 1 :].strip()
    if "% cheat" not in tail:
        return None
    num = tail.split("%", 1)[0].strip()
    try:
        return float(num)
    except ValueError:
        return None


def on_killfeed_clicked(item):
    txt = item.text()
    name = _parse_killer_from_killfeed_line(txt)
    if not name:
        return
    cheat_pct = _parse_cheat_pct_from_killfeed_line(txt)
    player_view_list.clear()
    for line in build_kill_view_lines(name, cheat_pct):
        player_view_list.addItem(line)

    meta = item.data(Qt.ItemDataRole.UserRole) or {}
    kill_tick = meta.get("kill_tick")
    killer_name = meta.get("killer_name") or name
    if FigureCanvas is None or Figure is None:
        return
    if current_df is None or kill_tick is None:
        return

    data = compute_kill_mouse_window(current_df, killer_name, kill_tick, baseline_ticks=20, post_death_ticks=20)
    if not data:
        return
    _plot_kill_mouse(data)


def on_scoreboard_clicked(row, _col):
    it = scoreboard.item(row, 0)
    if it is None:
        return
    name = (it.text() or "").strip()
    if name:
        _set_player_view(name)

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
kill_feed_list.itemClicked.connect(on_killfeed_clicked)
left_split.addWidget(kill_feed_list)

right_split = QSplitter(Qt.Orientation.Vertical)
player_view_list = QListWidget()
player_view_list.setAlternatingRowColors(True)
right_split.addWidget(player_view_list)

# kill analysis: mouse magnitude vs time + 2D aim (yaw/pitch)
if FigureCanvas is not None and Figure is not None:
    fig = Figure(figsize=(8.5, 3.2), dpi=100)
    canvas = FigureCanvas(fig)
    ax_mouse_time = fig.add_subplot(1, 2, 1)
    ax_aim = fig.add_subplot(1, 2, 2)
    ax_mouse_time.set_title("Mouse Δ magnitude vs tick")
    ax_mouse_time.set_xlabel("Tick (rel. death)")
    ax_mouse_time.set_ylabel("|Δ mouse|")
    ax_aim.set_title("Aim trace (yaw vs pitch)")
    ax_aim.set_xlabel("yaw (°)")
    ax_aim.set_ylabel("pitch (°)")
    fig.tight_layout()
    right_split.addWidget(canvas)
else:
    canvas = None
    ax_mouse_time = None
    ax_aim = None


def _index_at_kill_tick(ticks_abs, kill_tick: int) -> int | None:
    if ticks_abs is None or len(ticks_abs) == 0:
        return None
    ta = np.asarray(ticks_abs, dtype=np.int64)
    kt = int(kill_tick)
    idx = int(np.argmin(np.abs(ta - kt)))
    if idx < 0 or idx >= len(ta):
        return None
    return idx


def _plot_kill_mouse(data: dict):
    if canvas is None or ax_mouse_time is None or ax_aim is None:
        return
    ax_mouse_time.clear()
    ax_aim.clear()

    ticks_rel = data["ticks_rel"]
    mag = data["mag"]
    kt = int(data.get("kill_tick", 0))
    ticks_abs = data.get("ticks_abs")
    kill_idx = _index_at_kill_tick(ticks_abs, kt)

    ax_mouse_time.plot(ticks_rel, mag, linewidth=1.5, color="C0")
    ax_mouse_time.axvline(0, linestyle="--", linewidth=1.0, color="gray")
    ax_mouse_time.axvline(data.get("start_move_rel", 0), linestyle=":", linewidth=1.0, color="C2")
    ax_mouse_time.set_title("Mouse Δ magnitude vs tick")
    ax_mouse_time.set_xlabel("Tick (rel. death)")
    ax_mouse_time.set_ylabel("|Δ mouse|")
    ax_mouse_time.grid(True, alpha=0.25)

    yaw = data.get("yaw")
    pitch = data.get("pitch")
    if yaw is not None and pitch is not None and len(yaw) == len(pitch) and len(yaw) > 0:
        ax_aim.plot(yaw, pitch, "-", color="C3", linewidth=1.2, alpha=0.85, zorder=1)
        c_aim = ticks_rel if len(ticks_rel) == len(yaw) else np.arange(len(yaw))
        ax_aim.scatter(yaw, pitch, s=8, c=c_aim, cmap="plasma", zorder=2, alpha=0.7)
        if kill_idx is not None and kill_idx < len(yaw):
            ax_aim.scatter(
                [yaw[kill_idx]],
                [pitch[kill_idx]],
                s=55,
                c="red",
                zorder=3,
                marker="*",
                label="kill tick",
            )
            ax_aim.legend(loc="best", fontsize=7)
        ax_aim.set_title("Aim trace (yaw vs pitch)")
        ax_aim.set_xlabel("yaw (°)")
        ax_aim.set_ylabel("pitch (°)")
    else:
        ax_aim.text(
            0.5,
            0.5,
            "No pitch/yaw in tick data",
            ha="center",
            va="center",
            transform=ax_aim.transAxes,
            fontsize=10,
            color="gray",
        )
        ax_aim.set_title("Aim trace (yaw vs pitch)")
    ax_aim.grid(True, alpha=0.25)

    fig = canvas.figure
    fig.tight_layout()
    canvas.draw()

scoreboard = QTableWidget()
scoreboard.setColumnCount(9)
scoreboard.setAlternatingRowColors(True)
# All columns share horizontal space evenly and scale with the window
scoreboard.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
scoreboard.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
scoreboard.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
scoreboard.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
scoreboard.cellClicked.connect(on_scoreboard_clicked)
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
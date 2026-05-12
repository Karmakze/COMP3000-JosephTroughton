import json
import numpy as np
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog, QInputDialog, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy, QMessageBox, QComboBox, QProgressDialog,
)
from PyQt6.QtCore import QObject, QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices
from DemoParse2_Ingestion import run_ingestion
from Match_Stats import get_name_from_steamid, calc_killfeed, calc_scoreboard
from Player_View import build_player_view_lines, build_kill_view_lines, compute_kill_mouse_window
from app_config import (
    BASE_DIR,
    DEFAULT_DEMO_DIR,
    KILL_WINDOW_BASELINE_TICKS_DEFAULT,
    KILL_WINDOW_POST_DEATH_TICKS_DEFAULT,
)

# Persists list name -> .dem path between sessions (updated when a demo is added).
SAVED_DEMOS_JSON = BASE_DIR / "data" / "saved_demos.json"


def _load_saved_demo_paths() -> dict[str, str]:
    if not SAVED_DEMOS_JSON.is_file():
        return {}
    try:
        raw = json.loads(SAVED_DEMOS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip():
            out[k.strip()] = v.strip()
    return out


def _persist_demo_paths() -> None:
    try:
        SAVED_DEMOS_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = SAVED_DEMOS_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(demo_paths, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(SAVED_DEMOS_JSON)
    except OSError:
        pass


def _qt_demo_start_dir() -> str:
    """Directory for file dialogs; from CS2CD_DEFAULT_DEMO_DIR when set and valid."""
    if not (DEFAULT_DEMO_DIR or "").strip():
        return ""
    p = Path(DEFAULT_DEMO_DIR.strip()).expanduser()
    return str(p.resolve()) if p.is_dir() else ""

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.collections import LineCollection
except Exception:  # matplotlib optional at runtime
    Figure = None
    FigureCanvas = None
    LinearSegmentedColormap = None
    Normalize = None
    LineCollection = None


# Same pattern as QFileDialog filter below — single definition of “demo extension”.
def _is_demo_file(path: Path) -> bool:
    if not path.is_file():
        return False
    pl = path.name.lower()
    return pl.endswith(".dem") or pl.endswith(".dem.gz")


DEMO_OPEN_FILE_FILTER = "Demo files (*.dem *.dem.gz)"


def _paths_from_mime_urls(mime) -> list[str]:
    if mime is None or not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.toLocalFile()]


def _mime_has_demo_urls(mime) -> bool:
    return any(_is_demo_file(Path(p)) for p in _paths_from_mime_urls(mime))


class _IngestionWorker(QObject):
    """Runs run_ingestion in a background thread so the UI stays responsive."""

    # Do not pass huge pandas objects through signals — Qt may freeze copying them for the queue.
    finished = pyqtSignal()
    failed = pyqtSignal(str, str)  # title, message

    def __init__(self, demo_path: str):
        super().__init__()
        self._demo_path = demo_path
        self._payload: tuple | None = None

    def run_ingest(self) -> None:
        try:
            self._payload = run_ingestion(self._demo_path)
            self.finished.emit()
        except FileNotFoundError as e:
            self._payload = None
            self.failed.emit("Demo not found", str(e))
        except OSError as e:
            self._payload = None
            self.failed.emit("Could not read demo", str(e))
        except Exception as e:
            self._payload = None
            self.failed.emit("Could not load demo", f"{type(e).__name__}: {e}")


app = QApplication([])

# Display name -> absolute path (loaded from data/saved_demos.json on startup).
demo_paths = _load_saved_demo_paths()

# Filled when the demo QListWidget is constructed (drag-drop may run after UI build).
_ui_main: dict = {"demo_selector": None}


def _unique_demo_list_key(base: str) -> str:
    base = (base or "").strip() or "demo"
    if base not in demo_paths:
        return base
    n = 2
    while f"{base} ({n})" in demo_paths:
        n += 1
    return f"{base} ({n})"


def _default_demo_label(p: Path) -> str:
    pl = p.name.lower()
    if pl.endswith(".dem.gz"):
        return p.name[:-7]
    return p.stem


def _register_demo_file(path_str: str, *, label: str | None = None) -> bool:
    """Append one demo file to the selector list and demo_paths."""
    sel = _ui_main.get("demo_selector")
    if sel is None:
        return False
    p = Path(path_str).expanduser().resolve()
    if not _is_demo_file(p):
        return False
    key_base = label.strip() if label else _default_demo_label(p)
    name = _unique_demo_list_key(key_base)
    demo_paths[name] = str(p)
    sel.addItem(name)
    _persist_demo_paths()
    return True


def _prompt_demo_display_name(path_str: str) -> str | None:
    """Ask list name; default text is the file name (with extension). Returns None if cancelled or empty."""
    p = Path(path_str).expanduser().resolve()
    default = p.name
    name, ok = QInputDialog.getText(win, "Enter Name of Demo", "Name:", text=default)
    if not ok:
        return None
    name = (name or "").strip()
    if not name:
        return None
    return name


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if _mime_has_demo_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if _mime_has_demo_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        paths = _paths_from_mime_urls(mime)
        if not paths:
            event.ignore()
            return
        demo_paths_only = [raw for raw in paths if _is_demo_file(Path(raw).expanduser().resolve())]
        if not demo_paths_only:
            event.ignore()
            QMessageBox.information(
                self,
                "Drag and drop",
                "No supported demo files here. Drop a .dem or .dem.gz file.",
            )
            return
        added = 0
        for raw in demo_paths_only:
            label = _prompt_demo_display_name(raw)
            if label is None:
                continue
            if _register_demo_file(raw, label=label):
                added += 1
        if added:
            event.acceptProposedAction()
        else:
            event.ignore()


win = MainWindow()


def _browse_single_demo_path() -> str | None:
    """Open demo file picker (shared filter/dir with File → Open Demo)."""
    path, _ = QFileDialog.getOpenFileName(
        win,
        "Open Demo",
        _qt_demo_start_dir(),
        DEMO_OPEN_FILE_FILTER,
    )
    return path or None


# cached current demo data for click handlers
current_df = None
current_kills_df = None
current_steamid_to_name = None
current_loaded_demo_name: str | None = None

# cached killfeed for filters
killfeed_all_items: list[dict] = []

# Ribbon / menu bar with File dropdown
menubar = win.menuBar()
file_menu = menubar.addMenu("&File")

def on_open_demo():
    path = _browse_single_demo_path()
    if not path:
        return
    label = _prompt_demo_display_name(path)
    if label is None:
        return
    _register_demo_file(path, label=label)

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


def _apply_ingestion_result(demo_name: str, df, results, kills_df, hurts_df, num_rounds) -> None:
    """Apply parsed demo + model output to the UI (main thread only)."""
    global current_df, current_kills_df, current_steamid_to_name, killfeed_all_items
    global current_loaded_demo_name

    steamid_to_name = get_name_from_steamid(df)
    current_df = df
    current_kills_df = kills_df
    current_steamid_to_name = steamid_to_name

    # Reset killfeed + filters
    kill_feed_list.clear()
    kill_filter_killer.blockSignals(True)
    kill_filter_weapon.blockSignals(True)
    kill_filter_killer.clear()
    kill_filter_weapon.clear()
    kill_filter_killer.addItem("All")
    kill_filter_weapon.addItem("All")
    kill_filter_killer.blockSignals(False)
    kill_filter_weapon.blockSignals(False)

    # Killfeed should only show kills where the attacker is a real player.
    # Otherwise you get environment/world/c4-style "kills" polluting the list.
    kills_df_for_killfeed = kills_df
    att_cols = ["attacker_steamid", "attackerSteamId", "attacker"]
    vic_cols = ["user_steamid", "victimSteamId", "victim", "user"]
    att_col = next(
        (c for c in att_cols if kills_df_for_killfeed is not None and c in kills_df_for_killfeed.columns),
        None,
    )
    vic_col = next(
        (c for c in vic_cols if kills_df_for_killfeed is not None and c in kills_df_for_killfeed.columns),
        None,
    )
    if kills_df_for_killfeed is not None and att_col and steamid_to_name:
        def _is_player_steamid(v) -> bool:
            # World kills / c4 often arrive as NaN/None or some non-steamid token.
            if v is None:
                return False
            s = str(v)
            if s.lower() == "nan":
                return False
            if s not in steamid_to_name:
                return False
            # If the mapping exists but resolves to "?", it's not a real player name.
            mapped = (steamid_to_name.get(s) or "").strip()
            return bool(mapped) and mapped != "?"

        try:
            mask = kills_df_for_killfeed[att_col].apply(_is_player_steamid)
            kills_df_for_killfeed = kills_df_for_killfeed.loc[mask].copy()
        except Exception:
            # If anything about the column types is unexpected, fall back to unfiltered killfeed.
            kills_df_for_killfeed = kills_df

    killfeed_all_items = calc_killfeed(
        kills_df_for_killfeed, df, results, steamid_to_name, hurts_df
    ) or []

    # Populate filter options from killfeed metadata
    killers = sorted(
        {str(it.get("meta", {}).get("killer_name")).strip() for it in killfeed_all_items if it.get("meta", {}).get("killer_name")}
    )
    weapons = sorted(
        {str(it.get("meta", {}).get("weapon")).strip() for it in killfeed_all_items if it.get("meta", {}).get("weapon")}
    )
    kill_filter_killer.blockSignals(True)
    kill_filter_weapon.blockSignals(True)
    for k in killers:
        if k and k != "?":
            kill_filter_killer.addItem(k)
    for w in weapons:
        if w and w != "?":
            kill_filter_weapon.addItem(w)
    kill_filter_killer.blockSignals(False)
    kill_filter_weapon.blockSignals(False)

    _apply_killfeed_filter()

    rows = calc_scoreboard(df, results, kills_df, hurts_df, num_rounds, steamid_to_name)
    _fill_scoreboard(rows)
    current_loaded_demo_name = demo_name


def run_ingestion_analysis():
    _clear_analysis_results()
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

    progress = QProgressDialog(win)
    progress.setWindowTitle("Loading demo")
    progress.setLabelText(f'Loading "{demo_name}"\nParsing demo and running model.')
    progress.setRange(0, 0)
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)

    worker = _IngestionWorker(str(demo_file))
    thread = QThread(win)
    worker.moveToThread(thread)

    timer = QTimer(win)
    timer.setInterval(380)
    phase = [0]

    def tick_loading_label() -> None:
        phase[0] = (phase[0] + 1) % 4
        dots = "." * phase[0]
        progress.setLabelText(
            f'Loading "{demo_name}"{dots}\nParsing demo and running model.'
        )

    def cleanup_progress() -> None:
        timer.stop()
        progress.close()
        progress.deleteLater()
        test_ingest_button.setEnabled(True)
        remove_demo_button.setEnabled(True)
        QApplication.processEvents()

    def on_finished() -> None:
        payload = worker._payload
        cleanup_progress()
        if payload is None:
            return
        df, results, kills_df, hurts_df, num_rounds = payload
        _apply_ingestion_result(demo_name, df, results, kills_df, hurts_df, num_rounds)

    def on_failed(title: str, msg: str) -> None:
        cleanup_progress()
        if title == "Demo not found":
            QMessageBox.warning(win, title, msg)
        elif title == "Could not read demo":
            QMessageBox.critical(win, title, msg)
        else:
            QMessageBox.critical(win, title, msg)

    thread.started.connect(worker.run_ingest)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    timer.timeout.connect(tick_loading_label)

    test_ingest_button.setEnabled(False)
    remove_demo_button.setEnabled(False)
    progress.show()
    QApplication.processEvents()
    timer.start()
    thread.start()


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
    meta = item.data(Qt.ItemDataRole.UserRole) or {}
    name = meta.get("killer_name") or None
    if not name:
        # Fallback for older/newer killfeed text formats.
        name = _parse_killer_from_killfeed_line(item.text())
    if not name:
        return

    cheat_prob = meta.get("cheat_prob")
    cheat_pct = None if cheat_prob is None else float(cheat_prob) * 100.0
    # Same ref tick as cheat % + mouse plot (last FIRE at/before kill when available).
    kill_tick = meta.get("score_tick") or meta.get("kill_tick")
    killer_name = meta.get("killer_name") or name

    data = None
    if current_df is not None and kill_tick is not None:
        data = compute_kill_mouse_window(
            current_df,
            killer_name,
            kill_tick,
            baseline_ticks=KILL_WINDOW_BASELINE_TICKS_DEFAULT,
            post_death_ticks=KILL_WINDOW_POST_DEATH_TICKS_DEFAULT,
        )

    player_view_list.clear()
    ticks_abs = data.get("ticks_abs") if data else None
    for line in build_kill_view_lines(name, cheat_pct, meta, ticks_abs=ticks_abs):
        player_view_list.addItem(line)

    if FigureCanvas is None or Figure is None:
        return
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
    """Open CS2CD_DEFAULT_DEMO_DIR in the OS default file manager (no picker)."""
    path = _qt_demo_start_dir()
    if not path:
        QMessageBox.information(
            win,
            "Demo folder",
            "Set CS2CD_DEFAULT_DEMO_DIR in Code/.env to an existing folder, then try again.",
        )
        return
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
        QMessageBox.warning(
            win,
            "Demo folder",
            f"Could not open this path in the file manager:\n\n{path}",
        )


def _apply_killfeed_filter():
    """Re-render killfeed list based on current filter dropdowns."""
    kill_feed_list.clear()
    killer_sel = (kill_filter_killer.currentText() or "").strip()
    weapon_sel = (kill_filter_weapon.currentText() or "").strip()

    for it in killfeed_all_items:
        meta = it.get("meta", {}) or {}
        k = (meta.get("killer_name") or "").strip()
        w = (meta.get("weapon") or "").strip()
        if killer_sel and killer_sel != "All" and k != killer_sel:
            continue
        if weapon_sel and weapon_sel != "All" and w != weapon_sel:
            continue
        kill_feed_list.addItem(it.get("text", ""))
        lw_item = kill_feed_list.item(kill_feed_list.count() - 1)
        lw_item.setData(Qt.ItemDataRole.UserRole, meta)

open_action = QAction("&Open Demo...", win)
open_action.setShortcut("Ctrl+O")
open_action.triggered.connect(on_open_demo)
file_menu.addAction(open_action)

open_folder_action = QAction("Open Demo &Folder", win)
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
remove_demo_button = QPushButton("Remove Demo")
button_row.addWidget(remove_demo_button)
button_row.addStretch()
main_layout.addLayout(button_row)

# Horizontal splitter (left | right)
h_split = QSplitter(Qt.Orientation.Horizontal)

left_split = QSplitter(Qt.Orientation.Vertical)
selector = QListWidget()
_ui_main["demo_selector"] = selector
selector.setAlternatingRowColors(True)
selector.itemClicked.connect(on_demo_selected)
left_split.addWidget(selector)
selector.addItems(list(demo_paths.keys()))

# Killfeed filters (killer + weapon)
kill_filter_bar = QWidget()
kill_filter_layout = QHBoxLayout(kill_filter_bar)
kill_filter_layout.setContentsMargins(6, 4, 6, 4)
kill_filter_layout.setSpacing(8)

kill_filter_layout.addWidget(QLabel("Killer"))
kill_filter_killer = QComboBox()
kill_filter_killer.addItem("All")
kill_filter_killer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
kill_filter_layout.addWidget(kill_filter_killer, 2)

kill_filter_layout.addWidget(QLabel("Weapon"))
kill_filter_weapon = QComboBox()
kill_filter_weapon.addItem("All")
kill_filter_weapon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
kill_filter_layout.addWidget(kill_filter_weapon, 2)

left_split.addWidget(kill_filter_bar)

kill_feed_list = QListWidget()
kill_feed_list.setAlternatingRowColors(True)
kill_feed_list.itemClicked.connect(on_killfeed_clicked)
left_split.addWidget(kill_feed_list)

# Re-filter killfeed when dropdowns change
kill_filter_killer.currentIndexChanged.connect(lambda _i: _apply_killfeed_filter())
kill_filter_weapon.currentIndexChanged.connect(lambda _i: _apply_killfeed_filter())

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
    ax_aim.set_title("Crosshair path (yaw vs pitch)")
    ax_aim.set_xlabel("yaw (°)")
    ax_aim.set_ylabel("pitch (°)")
    # Keep a stable subplot layout to avoid jitter/shrinking on redraw.
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.16, top=0.90, wspace=0.30)
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


def _plot_crosshair_start_finish(ax_aim, yaw, pitch) -> None:
    """Mark first and last samples of the plotted window (green Start ▲, blue Finish ▼)."""
    ya = np.asarray(yaw, dtype=float)
    pi = np.asarray(pitch, dtype=float)
    if ya.size < 1 or ya.shape != pi.shape:
        return
    ax_aim.scatter(
        [ya[0]],
        [pi[0]],
        s=95,
        c="tab:green",
        marker="^",
        zorder=4,
        edgecolors="black",
        linewidths=0.5,
        label="Start",
    )
    if ya.size >= 2:
        ax_aim.scatter(
            [ya[-1]],
            [pi[-1]],
            s=95,
            c="tab:blue",
            marker="v",
            zorder=4,
            edgecolors="black",
            linewidths=0.5,
            label="Finish",
        )


def _plot_kill_mouse(data: dict):
    if canvas is None or ax_mouse_time is None or ax_aim is None:
        return
    # Remove any previously-added colorbar axes from prior draws.
    fig = canvas.figure
    for extra_ax in list(fig.axes):
        if extra_ax not in (ax_mouse_time, ax_aim):
            fig.delaxes(extra_ax)
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
    tr = np.asarray(ticks_rel, dtype=np.float64)
    if tr.size >= 1:
        ax_mouse_time.axvline(float(tr[0]), linestyle="--", linewidth=1.2, color="tab:green", alpha=0.85, label="Start")
    if tr.size >= 2:
        ax_mouse_time.axvline(float(tr[-1]), linestyle="--", linewidth=1.2, color="tab:blue", alpha=0.85, label="Finish")
    ax_mouse_time.set_title("Mouse Δ magnitude vs tick")
    ax_mouse_time.set_xlabel("Tick (rel. death)")
    ax_mouse_time.set_ylabel("|Δ mouse|")
    ax_mouse_time.grid(True, alpha=0.25)
    if tr.size >= 1:
        ax_mouse_time.legend(loc="upper right", fontsize=7)

    yaw = data.get("yaw")
    pitch = data.get("pitch")
    fire_mask = data.get("fire_mask")

    def _scatter_shots_only(y_arr, p_arr, colors, *, fallback_c=None):
        """Dots only on discrete shots (shots_fired↑ or FIRE rising edge). No dots if neither column usable."""
        if fire_mask is None or len(fire_mask) != len(y_arr):
            return
        idx = np.flatnonzero(fire_mask)
        if idx.size == 0:
            return
        ys, ps = np.asarray(y_arr)[idx], np.asarray(p_arr)[idx]
        if fallback_c is not None:
            ax_aim.scatter(ys, ps, s=10, c=fallback_c, zorder=2, alpha=0.9)
        else:
            ax_aim.scatter(ys, ps, s=10, c=colors[idx], zorder=2, alpha=0.9)

    if yaw is not None and pitch is not None and len(yaw) == len(pitch) and len(yaw) > 0:
        if (
            len(mag) == len(yaw)
            and LinearSegmentedColormap is not None
            and Normalize is not None
            and LineCollection is not None
            and len(yaw) >= 2
        ):
            # Green -> orange -> red speed map (slow -> fast), applied to line segments.
            speed_cmap = LinearSegmentedColormap.from_list(
                "aim_speed",
                ["#2ca02c", "#ff7f0e", "#d62728"],
            )
            m_min = float(np.nanmin(mag)) if len(mag) else 0.0
            m_max = float(np.nanmax(mag)) if len(mag) else 1.0
            if not np.isfinite(m_min):
                m_min = 0.0
            if not np.isfinite(m_max) or m_max <= m_min:
                m_max = m_min + 1.0
            norm = Normalize(vmin=m_min, vmax=m_max)

            # Build line segments between consecutive points.
            pts = np.column_stack((np.asarray(yaw, dtype=float), np.asarray(pitch, dtype=float)))
            segs = np.stack([pts[:-1], pts[1:]], axis=1)
            seg_speed = 0.5 * (np.asarray(mag[:-1], dtype=float) + np.asarray(mag[1:], dtype=float))

            lc = LineCollection(segs, cmap=speed_cmap, norm=norm, linewidths=1.8, alpha=0.9, zorder=1)
            lc.set_array(seg_speed)
            ax_aim.add_collection(lc)

            # Point colours = average RGBA of adjacent segment colours (speed gradient on either side).
            seg_rgba = speed_cmap(norm(seg_speed))
            n = len(yaw)
            pt_rgba = np.empty((n, 4), dtype=float)
            pt_rgba[0] = seg_rgba[0]
            pt_rgba[-1] = seg_rgba[-1]
            if n > 2:
                pt_rgba[1:-1] = 0.5 * (seg_rgba[:-1] + seg_rgba[1:])
            np.clip(pt_rgba, 0.0, 1.0, out=pt_rgba)
            _scatter_shots_only(yaw, pitch, pt_rgba)

            # Window start / finish flags (first and last tick in this plot).
            _plot_crosshair_start_finish(ax_aim, yaw, pitch)

            # Draw colorbar in an inset axis so the main aim axis size stays fixed.
            cax = ax_aim.inset_axes([1.02, 0.10, 0.03, 0.80])
            cbar = fig.colorbar(lc, cax=cax)
            cbar.set_label("Mouse speed |Δ mouse|", fontsize=8)
            cbar.ax.tick_params(labelsize=7)
        else:
            # Fallback: fixed-color line; dots only on FIRE ticks when mask available.
            ax_aim.plot(yaw, pitch, "-", color="C3", linewidth=1.4, alpha=0.85, zorder=1)
            _scatter_shots_only(yaw, pitch, None, fallback_c="C3")
            _plot_crosshair_start_finish(ax_aim, yaw, pitch)
        if kill_idx is not None and kill_idx < len(yaw):
            ax_aim.scatter(
                [yaw[kill_idx]],
                [pitch[kill_idx]],
                s=55,
                c="red",
                zorder=5,
                marker="*",
                label="kill tick",
            )
        ax_aim.legend(loc="best", fontsize=7)
        ax_aim.set_title("Crosshair path (yaw vs pitch)")
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
        ax_aim.set_title("Crosshair path (yaw vs pitch)")
    ax_aim.grid(True, alpha=0.25)

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


def _clear_analysis_results() -> None:
    """Reset panels after the loaded demo is removed or cleared."""
    global current_df, current_kills_df, current_steamid_to_name, killfeed_all_items
    global current_loaded_demo_name

    current_df = None
    current_kills_df = None
    current_steamid_to_name = None
    current_loaded_demo_name = None
    killfeed_all_items = []

    kill_feed_list.clear()
    kill_filter_killer.blockSignals(True)
    kill_filter_weapon.blockSignals(True)
    kill_filter_killer.clear()
    kill_filter_weapon.clear()
    kill_filter_killer.addItem("All")
    kill_filter_weapon.addItem("All")
    kill_filter_killer.blockSignals(False)
    kill_filter_weapon.blockSignals(False)

    player_view_list.clear()
    scoreboard.setRowCount(0)

    if canvas is not None and ax_mouse_time is not None and ax_aim is not None:
        fig = canvas.figure
        for extra_ax in list(fig.axes):
            if extra_ax not in (ax_mouse_time, ax_aim):
                fig.delaxes(extra_ax)
        ax_mouse_time.clear()
        ax_aim.clear()
        ax_mouse_time.set_title("Mouse Δ magnitude vs tick")
        ax_mouse_time.set_xlabel("Tick (rel. death)")
        ax_mouse_time.set_ylabel("|Δ mouse|")
        ax_mouse_time.grid(True, alpha=0.25)
        ax_aim.set_title("Crosshair path (yaw vs pitch)")
        ax_aim.set_xlabel("yaw (°)")
        ax_aim.set_ylabel("pitch (°)")
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
        ax_aim.grid(True, alpha=0.25)
        canvas.draw()


def on_remove_selected_demo():
    row = selector.currentRow()
    if row < 0:
        QMessageBox.information(win, "Remove demo", "Select a demo in the list first.")
        return
    item = selector.currentItem()
    name = (item.text() or "").strip()
    if not name or name not in demo_paths:
        return
    reply = QMessageBox.question(
        win,
        "Remove demo",
        f'Remove "{name}" from the list?\n\nThis does not delete the .dem file.',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return
    demo_paths.pop(name, None)
    selector.takeItem(row)
    _persist_demo_paths()
    if name == current_loaded_demo_name:
        _clear_analysis_results()


remove_demo_button.clicked.connect(on_remove_selected_demo)

h_split.addWidget(left_split)
h_split.addWidget(right_split)
main_layout.addWidget(h_split)

win.setCentralWidget(central)
win.show()
app.exec()
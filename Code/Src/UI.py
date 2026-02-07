#TODO - Everything
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QFileDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

app = QApplication([])
win = QMainWindow()

# Ribbon / menu bar with File dropdown
menubar = win.menuBar()
file_menu = menubar.addMenu("&File")

def on_open_demo():
    path, _ = QFileDialog.getOpenFileName(win, "Open Demo", "", "Demo files (*.dem *.dem.gz)")
    if path:
        # TODO: load demo and add to selector
        pass

def on_open_folder():
    path = QFileDialog.getExistingDirectory(win, "Open Demo Folder")
    if path:
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

# Horizontal splitter (left | right)
h_split = QSplitter(Qt.Orientation.Horizontal)

left_split = QSplitter(Qt.Orientation.Vertical)
left_split.addWidget(QLabel("Demo Selector"))
left_split.addWidget(QLabel("Kill Feed"))

right_split = QSplitter(Qt.Orientation.Vertical)
right_split.addWidget(QLabel("Player Stats & Model"))
right_split.addWidget(QLabel("Scoreboard"))

h_split.addWidget(left_split)
h_split.addWidget(right_split)
main_layout.addWidget(h_split)

win.setCentralWidget(central)
win.show()
app.exec()
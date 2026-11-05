#!/usr/bin/env python3
"""Screenplay Annotator - native desktop app (PySide6) for labeling movie dialogue.

    pip install PySide6
    python app.py                                   # then File > Open...
    python app.py --movie film.mp4 --subs film.fa.srt --subs2 film.en.srt \
                  --lang1 fa --lang2 en --annotator parsa
    python app.py --dump-schema my_schema.json      # default schema to edit
"""
import argparse
import bisect
import html as _html
import json
import os
import re
import sys
from datetime import datetime

from PySide6.QtCore import QEvent, QSize, QStringListModel, Qt, QTimer, QUrl, Signal, QPoint, QRect
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QFont, QKeySequence, QPalette, QShortcut, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QListWidget, QListWidgetItem, QPushButton, QProgressBar, QScrollArea, QSlider, QSplitter,
    QStackedWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QLayout, QSizePolicy)

import core

try:                                    # video is optional: without it the app still labels/edits subtitles
    from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_MM = os.environ.get("SA_NO_VIDEO") != "1"
except ImportError:
    HAS_MM = False

NOFOCUS = Qt.FocusPolicy.NoFocus
GREY = "#52627a"


def apply_theme():
    """Own both text and surface colors, independent of the OS light/dark theme."""
    app = QApplication.instance()
    if app.property("annotationTheme"):
        return
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in ((QPalette.Window, "#f3f5f9"), (QPalette.WindowText, "#172b46"),
                        (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f2f6fc"),
                        (QPalette.Text, "#172b46"), (QPalette.Button, "#ffffff"),
                        (QPalette.ButtonText, "#172b46"), (QPalette.Highlight, "#dce9ff"),
                        (QPalette.HighlightedText, "#143e78"), (QPalette.ToolTipBase, "#172b46"),
                        (QPalette.ToolTipText, "#ffffff"), (QPalette.PlaceholderText, "#52627a")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.Text, QColor("#66758a"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ButtonText, QColor("#66758a"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { font-family: 'Segoe UI', Tahoma; font-size: 13px; color: #172b46; }
        QMainWindow, QDialog { background: #f3f5f9; }
        QLabel { background: transparent; }
        QLabel#sectionTitle { font-size: 16px; font-weight: 700; }
        QLabel#muted { color: #52627a; }
        QFrame#currentLine { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; }
        QPushButton { background: #ffffff; color: #172b46; border: 1px solid #becbdb;
                      border-radius: 5px; padding: 7px 10px; }
        QPushButton:hover { background: #eaf1fc; border-color: #7494bf; }
        QPushButton:pressed, QPushButton:checked { background: #2458a6; color: #ffffff; }
        QPushButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 2px solid #2458a6; }
        QPushButton:disabled { background: #edf0f4; color: #66758a; border-color: #d3dce8; }
        QPushButton#primary { background: #2458a6; color: #ffffff; border-color: #2458a6; font-weight: 600; }
        QPushButton#primary:hover { background: #1c4788; }
        QLineEdit, QPlainTextEdit, QComboBox { background: #ffffff; color: #172b46;
            selection-background-color: #dce9ff; selection-color: #143e78;
            border: 1px solid #becbdb; border-radius: 5px; padding: 6px; }
        QComboBox QAbstractItemView { background: #ffffff; color: #172b46;
            selection-background-color: #dce9ff; selection-color: #143e78; }
        QTreeWidget, QListWidget { background: #ffffff; alternate-background-color: #f2f6fc;
            color: #172b46; border: 1px solid #cbd5e1; border-radius: 6px;
            selection-background-color: #dce9ff; selection-color: #143e78; }
        QTreeWidget::item { padding: 7px 4px; }
        QListWidget::item { padding: 7px; border-bottom: 1px solid #e5eaf2; }
        QTreeWidget::item:selected, QListWidget::item:selected { background: #dce9ff; color: #143e78; }
        QHeaderView::section { background: #eaf0f8; color: #334966; padding: 7px 4px;
            border: 0; border-bottom: 1px solid #cbd5e1; font-weight: 600; }
        QScrollArea { background: transparent; border: 0; }
        QScrollArea > QWidget > QWidget { background: transparent; }
        QMenuBar, QMenu, QToolBar { background: #ffffff; color: #172b46; }
        QMenu::item:selected, QMenuBar::item:selected { background: #dce9ff; color: #143e78; }
        QToolBar { border-bottom: 1px solid #d3dce8; spacing: 8px; padding: 5px; }
        QToolButton { padding: 7px 10px; color: #172b46; }
        QToolButton:hover { background: #eaf1fc; }
        QToolTip { background: #172b46; color: #ffffff; border: 0; padding: 6px; }
        QProgressBar { border: 0; border-radius: 3px; background: #e3eaf4; color: #172b46; }
        QProgressBar::chunk { background: #2458a6; border-radius: 3px; }
        QStatusBar { background: #ffffff; color: #52627a; }
        QSplitter::handle { background: #dce3ed; }
    """)
    app.setProperty("annotationTheme", True)

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if index >= 0 and index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if index >= 0 and index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        for item in self.itemList:
            spaceX = self.spacing()
            spaceY = self.spacing()
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())
        return y + lineHeight - rect.y()

class SentenceWidget(QLabel):
    clicked = Signal(int)

    def __init__(self, text, index, is_alt_color):
        super().__init__(text)
        self.index = index
        self.is_selected = False
        self.base_bg = "#f2f6fc" if is_alt_color else "#ffffff"
        self.hover_bg = "#dce9ff"
        self.blink_state = False
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._toggle_blink)
        self.timer.start(800)
        
        self._update_style()

    def _toggle_blink(self):
        if not self.is_selected:
            self.blink_state = not self.blink_state
            self._update_style()

    def _update_style(self, is_hover=False):
        bg_color = self.hover_bg if is_hover else self.base_bg
        border = "2px solid #2458a6" if self.is_selected else "1px solid transparent"
        text_color = "#52627a" if (self.blink_state and not self.is_selected and not is_hover) else "#172b46"
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                border: {border};
                border-radius: 4px;
                padding: 4px;
                margin: 2px;
                color: {text_color};
                font-size: 15px;
            }}
        """)

    def enterEvent(self, event):
        self._update_style(is_hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._update_style(is_hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def set_selected(self, selected):
        self.is_selected = selected
        if selected:
            self.blink_state = False
        self._update_style()


# --------------------------------------------------------------------------- helpers
def is_rtl(s):
    ar = sum(1 for c in s if "֐" <= c <= "ࣿ" or "יִ" <= c <= "ﻼ")
    la = sum(1 for c in s if c.isascii() and c.isalpha())
    return ar > la


def rich(text, color=None):
    if not text:
        return ""
    rtl = is_rtl(text)
    return '<p dir="%s" align="%s" style="margin:0 0 2px 0;%s">%s</p>' % (
        "rtl" if rtl else "ltr", "right" if rtl else "left", "color:%s;" % color if color else "",
        _html.escape(text).replace("\\n", "<br>"))


def cell(text):
    text = text.replace("\\n", " ")
    return "\u202b" + text + "\u202c" if is_rtl(text) else text


def fmt(t):
    t = max(0.0, t)
    h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def auto_dir(edit):
    doc = edit.document()
    opt = doc.defaultTextOption()
    opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
    doc.setDefaultTextOption(opt)


# --------------------------------------------------------------------------- widgets
BTN_H = 54


class EntryEditor(QWidget):
    changed = Signal()
    focused = Signal()

    def __init__(self, task, with_char, char_model):
        super().__init__()
        self.task = task
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.char = self.del_btn = self.speaker = None
        if with_char:
            top = QHBoxLayout()
            self.char = QLineEdit()
            self.char.setPlaceholderText("Character")
            comp = QCompleter(char_model, self.char)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.char.setCompleter(comp)
            self.char.textChanged.connect(self.changed)
            self.char.installEventFilter(self)
            top.addWidget(self.char)
            self.del_btn = QPushButton("×")
            self.del_btn.setFocusPolicy(NOFOCUS)
            self.del_btn.setFixedWidth(28)
            self.del_btn.setToolTip("Remove this character")
            top.addWidget(self.del_btn)
            lay.addLayout(top)
        grid = QGridLayout()
        grid.setSpacing(5)
        self.btns = []
        for k, lab in enumerate(task["labels"]):
            b = QPushButton("%d   %s" % (k + 1, lab["value"]) + "\\n" + (lab.get("hint") or " "))
            b.setCheckable(True)
            b.setFixedHeight(BTN_H)
            b.setFocusPolicy(NOFOCUS)
            b.setToolTip(lab.get("hint", "") or "Select this label. Click again to clear it.")
            b.setStyleSheet("QPushButton{text-align:left;padding:7px;min-height:20px;}"
                            "QPushButton:checked{background:#2458a6;color:#ffffff;border:2px solid #173e78;font-weight:600;}")
            b.clicked.connect(lambda checked=False, i=k: self._clicked(i))
            grid.addWidget(b, k // 2, k % 2)
            self.btns.append(b)
        if with_char and task.get("speaker_flag"):
            n = len(self.btns)
            self.speaker = QPushButton("Speaker\\nSpeaking this line")
            self.speaker.setCheckable(True)
            self.speaker.setFocusPolicy(NOFOCUS)
            self.speaker.setFixedHeight(BTN_H)
            self.speaker.setToolTip("This character is the one speaking this line. Click again to clear it.")
            self.speaker.setStyleSheet("QPushButton{text-align:left;padding:7px;min-height:20px;background:#d5deea;border:1px solid #9fb0c7;}"
                                       "QPushButton:hover{background:#c5d3e6;}"
                                       "QPushButton:checked{background:#2458a6;color:#ffffff;border:2px solid #173e78;font-weight:600;}")
            self.speaker.toggled.connect(lambda _=False: (self.focused.emit(), self.changed.emit()))
            grid.addWidget(self.speaker, n // 2, n % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.rat = QPlainTextEdit()
        self.rat.setPlaceholderText("Rationale%s - why this label?" % (" (required)" if task["rationale"] == "required" else ""))
        hint = QLabel("Reason for this label" + (" (required)" if task["rationale"] == "required" else " (optional)"))
        lay.addWidget(hint)
        self.rat.setMinimumHeight(64)
        self.rat.setMaximumHeight(96)
        auto_dir(self.rat)
        self.rat.textChanged.connect(self.changed)
        self.rat.installEventFilter(self)
        lay.addWidget(self.rat)

    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.FocusIn:
            self.focused.emit()
        return False

    def _clicked(self, i):
        if not self.task["multi"]:
            for j, b in enumerate(self.btns):
                if j != i:
                    b.setChecked(False)
        self.focused.emit()
        self.changed.emit()

    def get(self):
        vals = [self.task["labels"][k]["value"] for k, b in enumerate(self.btns) if b.isChecked()]
        d = {"label": vals if self.task["multi"] else (vals[0] if vals else ""), "rationale": self.rat.toPlainText()}
        if self.char is not None:
            d = {"character": self.char.text(), **d}
            if self.speaker is not None:
                d["is_speaker"] = self.speaker.isChecked()
        return d

    def set(self, d):
        for w in [self.rat, self.char, self.speaker] + self.btns:
            if w is not None:
                w.blockSignals(True)
        lab = d.get("label", [] if self.task["multi"] else "")
        lab = lab if isinstance(lab, list) else [lab]
        for k, b in enumerate(self.btns):
            b.setChecked(self.task["labels"][k]["value"] in lab)
        self.rat.setPlainText(d.get("rationale", ""))
        if self.char is not None:
            self.char.setText(d.get("character", ""))
        if self.speaker is not None:
            self.speaker.setChecked(bool(d.get("is_speaker", False)))
        for w in [self.rat, self.char, self.speaker] + self.btns:
            if w is not None:
                w.blockSignals(False)


class TaskCard(QFrame):
    changed = Signal(object)
    focused = Signal(object)

    def __init__(self, task, idx, char_model):
        super().__init__()
        self.task, self.idx, self.char_model = task, idx, char_model
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        mode = QLabel("Choose all labels that apply." if task["multi"] else "Choose one label. Click it again to clear the selection.")
        mode.setObjectName("muted")
        mode.setWordWrap(True)
        mode.setVisible(task["multi"])
        lay.addWidget(mode)
        self.rows = []
        if task["per_character"]:
            self.rows_box = QVBoxLayout()
            lay.addLayout(self.rows_box)
            self.empty_hint = QLabel("Add a character, then choose a label and give a reason for this task.")
            self.empty_hint.setWordWrap(True)
            self.empty_hint.setObjectName("muted")
            lay.addWidget(self.empty_hint)
            add = QPushButton("+ Add character")
            add.setFocusPolicy(NOFOCUS)
            add.clicked.connect(lambda: self.add_row(focus=True))
            lay.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            self.editor = EntryEditor(task, False, char_model)
            self.editor.changed.connect(lambda: self.changed.emit(self))
            self.editor.focused.connect(lambda: self.focused.emit(self))
            lay.addWidget(self.editor)
        self.refresh_style(False, "empty")

    def add_row(self, data=None, focus=False):
        ed = EntryEditor(self.task, True, self.char_model)
        ed.changed.connect(lambda: self.changed.emit(self))
        ed.focused.connect(lambda: self.focused.emit(self))
        ed.del_btn.clicked.connect(lambda: self.remove_row(ed))
        self.rows.append(ed)
        self.empty_hint.hide()
        self.rows_box.addWidget(ed)
        if data:
            ed.set(data)
        if focus:
            ed.char.setFocus()
        return ed

    def remove_row(self, ed):
        self.rows.remove(ed)
        self.rows_box.removeWidget(ed)
        ed.hide()
        ed.deleteLater()
        self.empty_hint.setVisible(not self.rows)
        self.changed.emit(self)

    def load(self, entry):
        if self.task["per_character"]:
            for ed in self.rows:
                self.rows_box.removeWidget(ed)
                ed.hide()
                ed.deleteLater()
            self.rows = []
            self.empty_hint.setVisible(not entry)
            for r in entry or []:
                self.add_row(r)
        else:
            self.editor.set(entry or {"label": [] if self.task["multi"] else "", "rationale": ""})

    def collect(self):
        return [r.get() for r in self.rows] if self.task["per_character"] else self.editor.get()

    def toggle_label(self, k):
        if self.task["per_character"]:
            ed = self.rows[-1] if self.rows else self.add_row()
            ed.btns[k].click()
            if not ed.char.text():
                ed.char.setFocus()
        else:
            self.editor.btns[k].click()

    def focus_rationale(self):
        ed = (self.rows[-1] if self.rows else None) if self.task["per_character"] else self.editor
        if ed:
            ed.rat.setFocus()

    def refresh_style(self, active, state):
        col = "#3556d8" if active else {"ok": "#2e9e5b", "incomplete": "#e08a1e"}.get(state, "#9aa1ae")
        self.setStyleSheet("QFrame#card{background:#ffffff;border:1px solid #cbd5e1;border-radius:8px;}")
        mark = {"ok": " <span style='color:#17613a'>Complete</span>", "incomplete": " <span style='color:#925000'>Needs a label, character, or reason</span>"}.get(state, "")
        self.title.setText("<b>%s</b>%s<br><span style='color:%s'>%s</span>" % (
            _html.escape(self.task["name"]), mark, GREY, _html.escape(self.task.get("description", ""))))


class TemplateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Create task template")
        self.resize(760, 650)
        source = parent.P.schema if parent.P else core.DEFAULT_SCHEMA
        self.tasks = json.loads(json.dumps(source["tasks"]))
        self.current = -1
        layout = QVBoxLayout(self)
        intro = QLabel("Define the tasks and choices for a new project. Save this template, then select it when opening subtitles.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.template_name = QLineEdit(source["name"])
        form = QFormLayout()
        form.addRow("Template name", self.template_name)
        layout.addLayout(form)
        self.tasks_list = QListWidget()
        self.tasks_list.setMaximumHeight(140)
        self.tasks_list.addItems([t["name"] for t in self.tasks])
        layout.addWidget(self.tasks_list)
        buttons = QHBoxLayout()
        add = QPushButton("+ Add task")
        remove = QPushButton("Remove task")
        add.clicked.connect(self.add_task)
        remove.clicked.connect(self.remove_task)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        form = QFormLayout()
        self.task_name = QLineEdit()
        self.description = QLineEdit()
        self.labels = QPlainTextEdit()
        self.labels.setPlaceholderText("One choice per line. Optional guidance after |\\nPositive | Genuine relief or affection\\nNegative | Fear or resentment\\nNeutral")
        self.labels.setMinimumHeight(120)
        self.multi = QCheckBox("Allow multiple labels for this task")
        self.per_character = QCheckBox("Annotate each character separately")
        self.speaker_flag = QCheckBox("Add a 'Speaker' button for each character")
        self.per_character.toggled.connect(self.speaker_flag.setEnabled)
        self.required = QCheckBox("Require a reason for each label")
        form.addRow("Task name", self.task_name)
        form.addRow("Instructions", self.description)
        form.addRow("Label choices\\n(one per line)", self.labels)
        form.addRow(self.multi)
        form.addRow(self.per_character)
        form.addRow(self.speaker_flag)
        form.addRow(self.required)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        self.tasks_list.currentRowChanged.connect(self.select_task)
        self.tasks_list.setCurrentRow(0)

    def store_task(self):
        if not 0 <= self.current < len(self.tasks):
            return
        task = self.tasks[self.current]
        task["name"] = self.task_name.text().strip()
        task["description"] = self.description.text().strip()
        task["multi"] = self.multi.isChecked()
        task["per_character"] = self.per_character.isChecked()
        task["speaker_flag"] = self.per_character.isChecked() and self.speaker_flag.isChecked()
        task["rationale"] = "required" if self.required.isChecked() else "optional"
        old = {l["value"]: l for l in task["labels"]}
        labels = []
        for line in self.labels.toPlainText().splitlines():
            if line.strip():
                value, _, hint = line.partition("|")
                value = value.strip()
                labels.append({"value": value, "hint": hint.strip(), "color": old.get(value, {}).get("color", "#52627a")})
        task["labels"] = labels
        self.tasks_list.item(self.current).setText(task["name"] or "Unnamed task")

    def select_task(self, row):
        self.store_task()
        self.current = row
        if row < 0:
            return
        task = self.tasks[row]
        self.task_name.setText(task["name"])
        self.description.setText(task["description"])
        self.labels.setPlainText("\\n".join(l["value"] + (" | " + l["hint"] if l.get("hint") else "") for l in task["labels"]))
        self.multi.setChecked(task["multi"])
        self.per_character.setChecked(task["per_character"])
        self.speaker_flag.setChecked(task.get("speaker_flag", False))
        self.speaker_flag.setEnabled(task["per_character"])
        self.required.setChecked(task["rationale"] == "required")

    def add_task(self):
        self.store_task()
        number = len(self.tasks) + 1
        while any(t["id"] == "task_%d" % number for t in self.tasks):
            number += 1
        task = {"id": "task_%d" % number, "short": "T%d" % number, "name": "New task",
                "description": "", "multi": False, "per_character": False, "rationale": "required",
                "labels": [{"value": "Choice 1", "hint": "", "color": "#52627a"}]}
        self.tasks.append(task)
        self.tasks_list.addItem(task["name"])
        self.tasks_list.setCurrentRow(len(self.tasks) - 1)

    def remove_task(self):
        row = self.tasks_list.currentRow()
        if row < 0 or len(self.tasks) <= 1:
            return
        self.current = -1
        self.tasks_list.blockSignals(True)
        self.tasks.pop(row)
        self.tasks_list.takeItem(row)
        self.tasks_list.blockSignals(False)
        new_row = min(row, len(self.tasks) - 1)
        self.tasks_list.setCurrentRow(new_row)
        self.select_task(new_row)

    def schema(self):
        self.store_task()
        return core.normalize_schema({"name": self.template_name.text().strip() or "Custom annotation", "tasks": self.tasks})

    def accept(self):
        try:
            schema = self.schema()
            if any(not t["name"] for t in schema["tasks"]):
                raise ValueError("Give every task a name.")
        except ValueError as error:
            QMessageBox.warning(self, "Check task template", str(error))
            return
        super().accept()


class OpenDialog(QDialog):
    def __init__(self, parent, defaults):
        super().__init__(parent)
        self.setWindowTitle("Open project")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        intro = QLabel("Open dialogue subtitles and choose an annotator name. Video and a second language are optional.\\nLeave Task template blank to use the four screenplay tasks.")
        intro.setWordWrap(True)
        form.addRow(intro)
        self.f = {}

        def path_row(key, label, mode):
            e = QLineEdit(defaults.get(key, ""))
            b = QPushButton("Browse…")
            b.setFocusPolicy(NOFOCUS)

            def browse():
                if mode == "dir":
                    p = QFileDialog.getExistingDirectory(self, label, e.text() or "")
                else:
                    p, _ = QFileDialog.getOpenFileName(self, label, os.path.dirname(e.text()) if e.text() else "")
                if p:
                    e.setText(p)
            b.clicked.connect(browse)
            row = QHBoxLayout()
            row.addWidget(e)
            row.addWidget(b)
            form.addRow(label, row)
            self.f[key] = e

        def text_row(key, label, default=""):
            e = QLineEdit(defaults.get(key) or default)
            form.addRow(label, e)
            self.f[key] = e

        path_row("movie", "Movie (optional)", "file")
        path_row("subs", "Subtitle – language 1", "file")
        path_row("subs2", "Subtitle – language 2 (optional)", "file")
        text_row("lang1", "Language 1 code", "fa")
        text_row("lang2", "Language 2 code", "en")
        text_row("annotator", "Annotator name", "Model")
        text_row("encoding", "Encoding (blank = auto)")
        path_row("schema", "Task template (optional)", "file")
        path_row("outdir", "Output folder (optional)", "dir")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        return {k: e.text().strip() for k, e in self.f.items()}


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        apply_theme()
        self.P = None
        self.cur = -1
        self.cur_sentence = 0
        self.active = 0
        self.dirty = False
        self.loading = False
        self.sync = False
        self.play_idx = -1
        self.play_until = None
        self.view = "both"
        self.starts = []
        self.rows = []
        self.cards = []
        self.sentence_widgets = []
        self.char_model = QStringListModel()
        self.save_timer = QTimer(self, singleShot=True, interval=450)
        self.save_timer.timeout.connect(self.save_now)
        self.setWindowTitle("Screenplay Annotator")
        self.resize(1280, 820)
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._build_toolbar()

    # ---- UI construction
    def _build_ui(self):
        self.video = self.player = self.audio = None
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Play / pause video (Space)")
        self.btn_play.setFixedWidth(64)
        self.btn_play.setFocusPolicy(NOFOCUS)
        self.btn_play.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setFocusPolicy(NOFOCUS)
        self.slider.sliderMoved.connect(lambda v: self.player and self.player.setPosition(v))
        self.tlabel = QLabel("0:00")
        vol = QSlider(Qt.Orientation.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(80)
        vol.setFixedWidth(80)
        vol.setFocusPolicy(NOFOCUS)
        vol.valueChanged.connect(lambda v: self.audio and self.audio.setVolume(v / 100))
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        for w in (self.btn_play, self.slider, self.tlabel, QLabel("Vol"), vol):
            ctrl.addWidget(w)
        self.ctrl_w = QWidget()
        self.ctrl_w.setLayout(ctrl)
        self.vmsg = QLabel()
        self.vmsg.setStyleSheet("color:%s" % GREY)
        self.vmsg.setWordWrap(True)
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.RichText)
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(48)
        self.caption.setStyleSheet("font-size:15px;")
        vbox = QWidget()
        vl = QVBoxLayout(vbox)
        vl.setContentsMargins(0, 0, 0, 0)
        self.vl = vl
        vl.addWidget(self.ctrl_w)
        vl.addWidget(self.vmsg)
        vl.addWidget(self.caption)
        vl.addStretch(1)

        self.curhead = QLabel()
        b_prev, b_play, b_next = QPushButton("Previous"), QPushButton("Play line"), QPushButton("Next")
        self.line_play = b_play
        for b, fn in ((b_prev, lambda: self.move(-1)), (b_play, self.play_line), (b_next, lambda: self.move(1))):
            b.setFocusPolicy(NOFOCUS)
            b.clicked.connect(fn)
        head = QHBoxLayout()
        head.addWidget(self.curhead, 1)
        for b in (b_prev, b_play, b_next):
            head.addWidget(b)
        
        self.sentence_container = QWidget()
        self.sentence_layout = FlowLayout(self.sentence_container, margin=0, spacing=4)

        cur = QFrame()
        cur.setObjectName("currentLine")
        cur.setFrameShape(QFrame.Shape.StyledPanel)
        cl = QVBoxLayout(cur)
        cl.addLayout(head)
        cl.addWidget(self.sentence_container)

        left = QWidget()
        ml = QVBoxLayout(left)
        ml.setContentsMargins(0, 0, 6, 0)
        ml.setSpacing(8)
        title = QLabel("Dialogue & context")
        title.setObjectName("sectionTitle")
        ml.addWidget(title)
        vbox.setMaximumHeight(240)
        ml.addWidget(vbox)
        ml.addWidget(cur)
        self.context = QLabel()
        self.context.setObjectName("muted")
        self.context.setWordWrap(True)
        self.context.setMaximumHeight(64)
        ml.addWidget(self.context)

        self.f_q = QLineEdit()
        self.f_q.setPlaceholderText("Search text / rationale / character…")
        self.f_q.setClearButtonEnabled(True)
        self.f_status = QComboBox()
        for lab, key in (("All lines", "all"), ("Annotated", "annotated"), ("Unannotated", "unannotated"), ("Incomplete", "incomplete"), ("Description", "description")):
            self.f_status.addItem(lab, key)
        self.f_task = QComboBox()
        self.f_label = QComboBox()
        self.f_q.textChanged.connect(self.apply_filters)
        self.f_status.currentIndexChanged.connect(self.apply_filters)
        self.f_task.currentIndexChanged.connect(self.on_task_filter)
        self.f_label.currentIndexChanged.connect(self.apply_filters)
        ml.addWidget(self.f_q)
        fl = QHBoxLayout()
        for w in (self.f_status, self.f_task, self.f_label):
            w.setMinimumWidth(80)
            w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            fl.addWidget(w, 1)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["#", "Time", "Language 1", "Language 2", "Labels"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hd.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hd.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hd.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hd.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(4, 145)
        self.tree.currentItemChanged.connect(self.on_tree_current)
        ml.addLayout(fl)
        ml.addWidget(self.tree, 1)
        self.queue_count = QLabel()
        self.queue_count.setObjectName("muted")
        ml.addWidget(self.queue_count)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self.annotation_title = QLabel("Annotate this line")
        self.annotation_title.setObjectName("sectionTitle")
        rl.addWidget(self.annotation_title)
        self.project_info = QLabel("Open subtitles to begin. Use a task template for your own labels.")
        self.project_info.setObjectName("muted")
        self.project_info.setWordWrap(True)
        rl.addWidget(self.project_info)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Line type"))
        self.line_type = QComboBox()
        self.line_type.addItem("Dialogue", "dialogue")
        self.line_type.addItem("Description (scene sound / narration - nothing to annotate)", "description")
        self.line_type.setFocusPolicy(NOFOCUS)
        self.line_type.currentIndexChanged.connect(self.on_line_type)
        type_row.addWidget(self.line_type, 1)
        rl.addLayout(type_row)
        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(136)
        self.task_list.setMinimumHeight(90)
        self.task_list.currentRowChanged.connect(self.set_active)
        rl.addWidget(self.task_list)
        self.cards_stack = QStackedWidget()
        rl.addWidget(self.cards_stack, 1)
        self.last_edited_label = QLabel()
        self.last_edited_label.setObjectName("muted")
        self.last_edited_label.setWordWrap(True)
        rl.addWidget(self.last_edited_label)
        self.task_progress = QLabel()
        self.task_progress.setObjectName("muted")
        rl.addWidget(self.task_progress)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        rl.addWidget(self.progress)
        self.task_hint = QLabel()
        self.task_hint.setWordWrap(True)
        self.task_hint.setObjectName("muted")
        rl.addWidget(self.task_hint)
        actions = QHBoxLayout()
        next_task = QPushButton("Next task (T)")
        next_task.clicked.connect(lambda: self.set_active((self.active + 1) % max(1, len(self.cards))))
        self.next_pending = QPushButton("Next pending line (N)")
        self.next_pending.setObjectName("primary")
        self.next_pending.clicked.connect(self.next_todo)
        actions.addWidget(next_task)
        actions.addWidget(self.next_pending)
        rl.addLayout(actions)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([690, 550])
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(14, 12, 14, 8)
        shell_layout.addWidget(split)
        self.setCentralWidget(shell)
        self.stats = QLabel()
        self.saved = QLabel()
        self.statusBar().addWidget(self.stats, 1)
        self.statusBar().addPermanentWidget(self.saved)

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        a = fm.addAction("Open…")
        a.setShortcut(QKeySequence.StandardKey.Open)
        a.triggered.connect(self.open_dialog)
        fm.addAction("Import pre-annotations (JSON)…").triggered.connect(self.import_pre)
        fm.addSeparator()
        self.act_all = QAction("Include unannotated lines in export", self, checkable=True)
        fm.addAction(self.act_all)
        for f, lab in (("jsonl", "Export JSONL…"), ("json", "Export JSON…"), ("csv", "Export CSV…")):
            fm.addAction(lab).triggered.connect(lambda _=False, f=f: self.export(f))
        fm.addSeparator()
        fm.addAction("Quit").triggered.connect(self.close)
        vm = mb.addMenu("&View")
        grp = QActionGroup(self)
        self.view_acts = {}
        for key, lab in (("both", "Both languages"), ("a", "Language 1 only"), ("b", "Language 2 only")):
            act = QAction(lab, self, checkable=True)
            act.setChecked(key == "both")
            act.triggered.connect(lambda _=False, k=key: self.set_view(k))
            grp.addAction(act)
            vm.addAction(act)
            self.view_acts[key] = act
        vm.addSeparator()
        self.act_follow = QAction("Follow video", self, checkable=True)
        self.act_follow.setChecked(True)
        vm.addAction(self.act_follow)
        mb.addMenu("&Help").addAction("Shortcuts").triggered.connect(self.show_help)

    def _build_shortcuts(self):
        self.single_shortcuts = []
        def sc(key, fn):
            shortcut = QShortcut(QKeySequence(key), self, activated=fn)
            if len(key) == 1 or key == "Space":
                self.single_shortcuts.append(shortcut)
        sc("J", lambda: self.move(1))
        sc("K", lambda: self.move(-1))
        sc("Ctrl+Down", lambda: self.move(1))
        sc("Ctrl+Up", lambda: self.move(-1))
        sc("N", self.next_todo)
        sc("Space", self.toggle_play)
        sc("Ctrl+Space", self.toggle_play)
        sc("P", self.play_line)
        sc("T", lambda: self.set_active((self.active + 1) % max(1, len(self.cards))))
        sc("R", lambda: self.cards and self.cards[self.active].focus_rationale())
        sc("Esc", lambda: self.focusWidget() and self.focusWidget().clearFocus())
        for k in range(1, 10):
            sc(str(k), lambda k=k: self.pick(k - 1))
        QApplication.instance().focusChanged.connect(self._typing_focus)

    def _typing_focus(self, _old, new):
        typing = isinstance(new, (QLineEdit, QPlainTextEdit, QComboBox))
        for shortcut in self.single_shortcuts:
            shortcut.setEnabled(not typing)

    def _build_toolbar(self):
        bar = QToolBar("Project", self)
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addAction("Open project…", self.open_dialog)
        bar.addAction("Create task template…", self.create_template)
        bar.addSeparator()
        bar.addAction("Export JSONL…", lambda: self.export("jsonl"))
        bar.addAction("Export CSV…", lambda: self.export("csv"))
        space = QWidget()
        space.setSizePolicy(space.sizePolicy().Policy.Expanding, space.sizePolicy().Policy.Preferred)
        bar.addWidget(space)
        bar.addAction(self.act_follow)
        bar.addAction("Shortcuts", self.show_help)

    def create_template(self):
        dlg = TemplateDialog(self)
        if dlg.exec():
            path, _ = QFileDialog.getSaveFileName(self, "Save task template", "annotation-tasks.json", "JSON (*.json)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(dlg.schema(), f, ensure_ascii=False, indent=2)
                self.statusBar().showMessage("Template saved. Select it under Task template when opening a project.", 10000)

    def show_help(self):
        QMessageBox.information(self, "Shortcuts",
            "J / Ctrl+Down  next line     K / Ctrl+Up  previous line\\nN  next pending line for the selected task\\n"
            "Space  play / pause     P  play the selected line only\\nT  switch active task\\n"
            "1-9  pick a label in the active task (again = clear)\\nR  write the rationale of the active task\\n"
            "Esc  leave a text box\\n\\nSingle-key shortcuts do not fire while you type in a text box.\\n"
            "Everything autosaves. Labels without a rationale are marked incomplete.")

    def open_dialog(self):
        self.save_now()
        if self.dirty:
            return False
        dlg = OpenDialog(self, core.load_prefs() if not self.P else self.P.cfg)
        while dlg.exec():
            try:
                P = core.Project(dlg.values())
            except (ValueError, OSError, KeyError) as e:
                QMessageBox.warning(self, "Cannot open", str(e))
                continue
            core.save_prefs(P.cfg)
            self.set_project(P)
            return True
        return False

    def _ensure_player(self):
        if self.player is not None or not HAS_MM:
            return self.player is not None
        try:
            self.video = QVideoWidget()
            self.video.setMinimumHeight(120)
            self.player = QMediaPlayer(self)
            if QMediaDevices.audioOutputs():
                self.audio = QAudioOutput(self)
                self.audio.setVolume(0.8)
                self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video)
        except Exception as e:
            self.player = self.video = None
            self.vmsg.setText("Video unavailable (%s) - labeling still works." % e)
            return False
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.errorOccurred.connect(lambda e, msg: self.vmsg.setText("Video error: %s (continuing without video)" % msg))
        self.player.playbackStateChanged.connect(lambda s: self.btn_play.setText("Pause" if s == QMediaPlayer.PlaybackState.PlayingState else "Play"))
        self.vl.insertWidget(0, self.video, 1)
        return True

    def has_video(self):
        return self.player is not None and bool(self.P and self.P.cfg["movie"])

    def set_project(self, P):
        self.save_now()
        if self.dirty:
            return
        self.P = P
        self.cur, self.cur_sentence, self.active, self.play_idx = -1, 0, 0, -1
        self.starts = [l["start"] for l in P.lines]
        c = P.cfg
        self.setWindowTitle("Screenplay Annotator – %s – %s" % (os.path.basename(c["movie"] or c["subs"]), c["annotator"]))
        
        self.task_list.blockSignals(True)
        self.task_list.clear()
        while self.cards_stack.count():
            page = self.cards_stack.widget(0)
            self.cards_stack.removeWidget(page)
            page.deleteLater()
        self.cards = []
        for i, t in enumerate(P.schema["tasks"]):
            card = TaskCard(t, i, self.char_model)
            card.changed.connect(self.on_card_changed)
            card.focused.connect(lambda cd: self.set_active(cd.idx))
            holder = QWidget()
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, 0, 4, 0)
            layout.addWidget(card)
            layout.addStretch(1)
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setWidget(holder)
            self.cards_stack.addWidget(page)
            item = QListWidgetItem(t["name"])
            item.setSizeHint(QSize(0, 32))
            self.task_list.addItem(item)
            self.cards.append(card)
        self.task_list.setCurrentRow(0)
        self.task_list.blockSignals(False)
        self.cards_stack.setCurrentIndex(0)
        self.project_info.setText("%s  ·  %s" % (P.schema["name"], c["annotator"]))
        self.project_info.setToolTip("Working file: " + P.path)
        
        self.f_task.blockSignals(True)
        self.f_task.clear()
        self.f_task.addItem("any task", "")
        for t in P.schema["tasks"]:
            self.f_task.addItem(t["name"], t["id"])
        self.f_task.blockSignals(False)
        self.on_task_filter(apply=False)
        
        self.tree.blockSignals(True)
        self.tree.clear()
        self.rows = []
        for i, L in enumerate(P.lines):
            it = QTreeWidgetItem([str(L["id"]), fmt(L["start"]), cell(L["t1"]), cell(L["t2"]), ""])
            for col, txt in ((2, L["t1"]), (3, L["t2"])):
                it.setTextAlignment(col, (Qt.AlignmentFlag.AlignRight if is_rtl(txt) else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(it)
            self.rows.append(it)
            self.refresh_row(i)
        self.tree.blockSignals(False)
        has2 = bool(c["subs2"])
        for k in ("a", "b"):
            self.view_acts[k].setEnabled(has2)
        self.view_acts["both"].setChecked(True)
        self.set_view("both")
        
        has_v = bool(c["movie"]) and self._ensure_player()
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(c["movie"]) if has_v else QUrl())
            self.video.setVisible(has_v)
        self.ctrl_w.setVisible(has_v)
        self.line_play.setEnabled(has_v)
        self.caption.setVisible(has_v)
        self.act_follow.setEnabled(has_v)
        if has_v:
            self.vmsg.setText("")
        elif not c["movie"]:
            self.vmsg.setText("No movie loaded – subtitles only (viewer / edit mode).")
        elif not HAS_MM:
            self.vmsg.setText("Qt Multimedia not available (pip install PySide6) – subtitles only.")
        self.rebuild_chars()
        self.update_stats()
        self.saved.setText("autosave → " + os.path.basename(P.path))
        if P.warnings:
            QMessageBox.warning(self, "Please review", "\\n".join(P.warnings))
        self.select_line(self.first_todo(), seek=True)
        self.apply_filters()

    def chips(self, i):
        L = self.P.lines[i]
        if core.is_description(self.P, L["id"]):
            return "Description", "Scene sound / narration - no annotation needed", None, False
        sentences = self.P.items.get(L["id"], {}).get("sentences", {})
        parts, tips, color, inc = [], [], None, False
        for sent_idx, tasks in sentences.items():
            for t in self.P.schema["tasks"]:
                e = tasks.get(t["id"])
                if core.entry_state(t, e) == "empty":
                    continue
                for r in (e if t["per_character"] else [e]):
                    labs = r["label"] if isinstance(r["label"], list) else ([r["label"]] if r["label"] else ["?"])
                    bad = not r["label"] or (t["rationale"] == "required" and not r["rationale"].strip()) or (t["per_character"] and not r["character"].strip())
                    inc |= bad
                    who = (r.get("character", "") + ("🗣" if r.get("is_speaker") else "") + ": ") if r.get("character") else ""
                    parts.append(("⚠" if bad else "") + f"S{sent_idx}-%s·%s%s" % (t["short"], who, "/".join(labs)))
                    tips.append("S%s: %s – %s: %s%s" % (sent_idx, t["name"], who + "/".join(labs), r["rationale"] or "(no rationale)", "" if not bad else "   [incomplete]"))
                    if color is None and r["label"]:
                        first = r["label"][0] if isinstance(r["label"], list) else r["label"]
                        color = next((l["color"] for l in t["labels"] if l["value"] == first), None)
        return "  ".join(parts), "\\n".join(tips), color, inc

    def refresh_row(self, i):
        txt, tip, color, inc = self.chips(i)
        it = self.rows[i]
        it.setText(4, txt)
        it.setToolTip(4, tip)
        desc = core.is_description(self.P, self.P.lines[i]["id"])
        it.setForeground(4, QBrush(QColor("#6b7686" if desc else "#875000" if inc else "#334966")))
        bg = QBrush(QColor("#fff3db")) if inc else QBrush()
        for col in range(5):
            it.setBackground(col, bg)

    def on_task_filter(self, *_, apply=True):
        tid = self.f_task.currentData()
        self.f_label.blockSignals(True)
        self.f_label.clear()
        self.f_label.addItem("any label", "")
        t = next((x for x in self.P.schema["tasks"] if x["id"] == tid), None) if self.P else None
        for l in (t["labels"] if t else []):
            self.f_label.addItem(l["value"], l["value"])
        self.f_label.blockSignals(False)
        if apply:
            self.apply_filters()

    def matches(self, i):
        P, L = self.P, self.P.lines[i]
        sentences = P.items.get(L["id"], {}).get("sentences", {})

        any_, inc = core.line_state(P, L["id"])
        st = self.f_status.currentData()
        desc = core.is_description(P, L["id"])

        if st == "description":
            return desc

        all_complete = desc or (sentences and all(
            core.entry_state(t, tasks.get(t["id"])) == "ok"
            for tasks in sentences.values()
            for t in P.schema["tasks"]
        ))

        if st == "annotated" and not all_complete:
            return False

        if st == "unannotated" and any_:
            return False

        if st == "incomplete" and (not any_ or all_complete):
            return False

        tid, lb = self.f_task.currentData(), self.f_label.currentData()

        if tid and desc:
            return False

        if tid:
            t = next(x for x in P.schema["tasks"] if x["id"] == tid)
            task_found = False
            for tasks in sentences.values():
                e = tasks.get(tid)
                if core.entry_state(t, e) == "empty":
                    continue
                
                if lb:
                    rows = e if t["per_character"] else [e]
                    if any((lb in r["label"]) if isinstance(r["label"], list) else r["label"] == lb for r in rows):
                        task_found = True
                        break
                else:
                    task_found = True
                    break
            
            if not task_found:
                return False

        q = self.f_q.text().strip().lower()

        if q:
            hay = (L["t1"] + " " + L["t2"]).lower()
            for tasks in sentences.values():
                for e in tasks.values():
                    for r in (e if isinstance(e, list) else [e]):
                        hay += " " + r["rationale"].lower() + " " + r.get("character", "").lower()

            if q not in hay:
                return False

        return True

    def apply_filters(self, *_):
        if not self.P:
            return
        for i, it in enumerate(self.rows):
            it.setHidden(not self.matches(i))
        visible = sum(not it.isHidden() for it in self.rows)
        self.queue_count.setText("%d of %d lines shown" % (visible, len(self.rows)))

    def rebuild_chars(self):
        names = set()
        for it in self.P.items.values():
            for tasks in it.get("sentences", {}).values():
                for e in tasks.values():
                    if isinstance(e, list):
                        names.update(r["character"] for r in e if r.get("character"))
        self.char_model.setStringList(sorted(names))

    def update_stats(self):
        a = inc = 0
        for L in self.P.lines:
            x, y = core.line_state(self.P, L["id"])
            a += x
            inc += y
        self.stats.setText("%d / %d lines annotated%s" % (a, len(self.P.lines), " · %d incomplete" % inc if inc else ""))

    def set_view(self, v):
        self.view = v
        self.tree.setColumnHidden(2, v == "b")
        self.tree.setColumnHidden(3, v == "a" or not self.P or not self.P.cfg["subs2"])
        self.tree.setHeaderLabels(["#", "Time", "Language 1 (%s)" % self.P.cfg["lang1"] if self.P else "Language 1",
                                   "Language 2 (%s)" % self.P.cfg["lang2"] if self.P else "Language 2", "Labels"])
        self.render_cur()
        self.render_caption(self.play_idx)

    def texts_html(self, L, big=False):
        a = rich(L["t1"]) if self.view != "b" else ""
        b = rich(L["t2"], GREY if self.view == "both" else None) if self.view != "a" else ""
        return a + b

    def render_caption(self, i):
        self.caption.setText(self.texts_html(self.P.lines[i]) if self.P and i >= 0 else "")

    def render_cur(self):
        if not self.P or self.cur < 0:
            self.curhead.setText("")
            while self.sentence_layout.count():
                item = self.sentence_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            return
            
        L = self.P.lines[self.cur]
        self.curhead.setText("<b>#%d</b> &nbsp; %s → %s" % (L["id"], fmt(L["start"]), fmt(L["end"])))
        self.annotation_title.setText("Annotate line %d of %d" % (L["id"], len(self.P.lines)))
        
        while self.sentence_layout.count():
            item = self.sentence_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        text_to_split = L["t2"] if self.view == "b" else L["t1"]
        parts = re.split(r'(?<=[.!?])\s+', text_to_split.strip())
        sentences = [p for p in parts if p]
        
        self.sentence_widgets = []
        for idx, text in enumerate(sentences):
            widget = SentenceWidget(text, idx, is_alt_color=(idx % 2 == 0))
            widget.clicked.connect(self.select_sentence)
            self.sentence_layout.addWidget(widget)
            self.sentence_widgets.append(widget)

        context = []
        for idx, label in ((self.cur - 1, "Before"), (self.cur + 1, "After")):
            if 0 <= idx < len(self.P.lines):
                neighbor = self.P.lines[idx]
                text = neighbor["t2"] if self.view == "b" else neighbor["t1"]
                context.append("<b>%s:</b> %s" % (label, _html.escape(text.replace("\\n", " ")[:170])))
        self.context.setText("<br>".join(context))
        
        if self.sentence_widgets:
            self.select_sentence(0)

    def select_sentence(self, index):
        self.cur_sentence = index
        for w in self.sentence_widgets:
            w.set_selected(w.index == index)
            
        if self.P and self.cur >= 0:
            L = self.P.lines[self.cur]
            item_data = self.P.items.get(L["id"], {})
            sentences_data = item_data.get("sentences", {})
            tasks = sentences_data.get(str(index), {})
            
            self.loading = True
            for card in self.cards:
                card.load(tasks.get(card.task["id"]))
            self.line_type.setCurrentIndex(1 if core.is_description(self.P, L["id"]) else 0)
            self.loading = False
            self.update_card_styles()

    def first_todo(self):
        for i, L in enumerate(self.P.lines):
            if not core.line_state(self.P, L["id"])[0]:
                return i
        return 0

    def next_todo(self):
        if not self.P or not self.cards:
            return
        self.save_now()
        if self.dirty:
            return
        task = self.cards[self.active].task
        n = len(self.P.lines)
        for offset in range(1, n + 1):
            i = (self.cur + offset) % n
            sentences = self.P.items.get(self.P.lines[i]["id"], {}).get("sentences", {})
            if not self.rows[i].isHidden() and not core.is_description(self.P, self.P.lines[i]["id"]):
                text_to_split = self.P.lines[i]["t2"] if self.view == "b" else self.P.lines[i]["t1"]
                parts = re.split(r'(?<=[.!?])\s+', text_to_split.strip())
                num_sentences = len([p for p in parts if p]) or 1
                
                pending = False
                for s_idx in range(num_sentences):
                    tasks = sentences.get(str(s_idx), {})
                    if core.entry_state(task, tasks.get(task["id"])) != "ok":
                        pending = True
                        break
                if pending:
                    return self.select_line(i, seek=True)
        self.statusBar().showMessage("This task is complete for all visible lines.", 6000)

    def move(self, d):
        if self.P:
            for i in range(self.cur + d, len(self.rows) if d > 0 else -1, d):
                if not self.rows[i].isHidden():
                    self.select_line(i, seek=True)
                    break

    def on_tree_current(self, item, _old):
        if item is not None and not self.sync:
            self.select_line(self.rows.index(item), seek=True, from_tree=True)

    def select_line(self, i, seek=False, from_tree=False):
        if not self.P or not self.P.lines:
            return
        i = max(0, min(i, len(self.P.lines) - 1))
        self.save_now()
        if self.dirty:
            if self.cur >= 0:
                self.sync = True
                self.tree.setCurrentItem(self.rows[self.cur])
                self.sync = False
            return
        self.cur = i
        if not from_tree:
            self.sync = True
            self.tree.setCurrentItem(self.rows[i])
            self.tree.scrollToItem(self.rows[i])
            self.sync = False
        if seek and self.has_video():
            self.player.setPosition(int(self.P.lines[i]["start"] * 1000))
        self.render_cur()
        self.update_last_edited_label()

    def update_last_edited_label(self):
        if not self.P or self.cur < 0:
            self.last_edited_label.setText("")
            return

        line_id = self.P.lines[self.cur]["id"]
        item = self.P.items.get(line_id, {})

        username = item.get("last_edited_by", "")
        timestamp = item.get("last_edited_at", "")

        if not username:
            self.last_edited_label.setText(
                "Last edited by: Not edited yet"
            )
            return

        text = f"Last edited by: {username}"

        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                dt = dt.astimezone()
                text += "\\nLast edited: " + dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass

        self.last_edited_label.setText(text)

    def set_active(self, k):
        if 0 <= k < len(self.cards):
            self.active = k
            self.cards_stack.setCurrentIndex(k)
            self.task_list.blockSignals(True)
            self.task_list.setCurrentRow(k)
            self.task_list.blockSignals(False)
            self.update_card_styles()

    def update_card_styles(self):
        complete = 0
        is_desc = self.line_type.currentData() == "description"
        for k, card in enumerate(self.cards):
            state = core.entry_state(card.task, card.collect())
            complete += state == "ok"
            card.refresh_style(k == self.active, state)
            state_text = "Not needed" if is_desc else {"empty": "Not started", "ok": "Complete", "incomplete": "Needs attention"}[state]
            item = self.task_list.item(k)
            item.setText("%d. %s  ·  %s" % (k + 1, card.task["name"], state_text))
            item.setToolTip(card.task["description"] + "\\n" + state_text)
        desc = self.line_type.currentData() == "description"
        self.task_list.setEnabled(not desc)
        self.cards_stack.setEnabled(not desc)
        self.next_pending.setEnabled(True)
        if desc:
            complete = len(self.cards)
            self.task_progress.setText("Description line - complete, no tasks to fill in")
        else:
            self.task_progress.setText("%d of %d tasks complete on this sentence" % (complete, len(self.cards)))
        self.progress.setRange(0, max(1, len(self.cards)))
        self.progress.setValue(complete)
        if self.P and self.cards:
            task = self.cards[self.active].task
            done = sum(core.is_description(self.P, line["id"]) or core.line_state(self.P, line["id"])[0] for line in self.P.lines)
            self.task_hint.setText("%s: %d / %d lines have some annotation. Next pending follows the current filters." %
                                   (task["name"], done, len(self.P.lines)))

    def pick(self, k):
        if self.cards and self.line_type.currentData() == "dialogue" and k < len(self.cards[self.active].task["labels"]):
            self.cards[self.active].toggle_label(k)

    def on_line_type(self, *_):
        if self.loading or not self.P or self.cur < 0:
            self.update_card_styles() if self.P and self.cards else None
            return
        self.dirty = True
        self.saved.setText("● editing…")
        self.update_card_styles()
        self.save_timer.start()

    def on_card_changed(self, card):
        if self.loading:
            return
        self.set_active(card.idx)
        self.dirty = True
        self.saved.setText("● editing…")
        self.save_timer.start()

    def save_now(self):
        self.save_timer.stop()
        if not self.dirty or not self.P or self.cur < 0:
            return
        self.dirty = False
        L = self.P.lines[self.cur]
        try:
            self.P.set_annotation(L["id"], self.cur_sentence, {c.task["id"]: c.collect() for c in self.cards},
                                  self.line_type.currentData())
            self.update_last_edited_label()
        except (ValueError, OSError) as e:
            self.dirty = True
            self.saved.setText("<span style='color:#d64545'>Save failed: %s</span>" % e)
            return
        self.refresh_row(self.cur)
        self.rebuild_chars()
        self.update_stats()
        self.update_card_styles()
        self.apply_filters()
        self.saved.setText("✓ saved %s" % datetime.now().strftime("%H:%M:%S"))

    def toggle_play(self):
        if not self.has_video():
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_line(self):
        if self.has_video() and self.cur >= 0:
            L = self.P.lines[self.cur]
            self.play_until = int(L["end"] * 1000)
            self.player.setPosition(int(L["start"] * 1000))
            self.player.play()

    def line_at(self, t):
        a = bisect.bisect_right(self.starts, t) - 1
        for k in range(a, max(-1, a - 4), -1):
            if self.P.lines[k]["end"] > t:
                return k
        return -1

    def on_position(self, ms):
        if not self.P:
            return
        if self.play_until is not None and ms >= self.play_until:
            self.player.pause()
            self.play_until = None
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.tlabel.setText("%s / %s" % (fmt(ms / 1000), fmt(self.player.duration() / 1000)))
        i = self.line_at(ms / 1000)
        if i == self.play_idx:
            return
        if self.play_idx >= 0:
            f = self.rows[self.play_idx].font(1)
            f.setBold(False)
            self.rows[self.play_idx].setFont(1, f)
        self.play_idx = i
        if i >= 0:
            f = self.rows[i].font(1)
            f.setBold(True)
            self.rows[i].setFont(1, f)
        self.render_caption(i)
        typing = isinstance(self.focusWidget(), (QLineEdit, QPlainTextEdit)) and self.focusWidget() not in (self.f_q,)
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if i >= 0 and playing and self.act_follow.isChecked() and not typing and i != self.cur:
            self.select_line(i, seek=False)

    def import_pre(self):
        if not self.P:
            QMessageBox.information(self, "Import", "Open a project first.")
            return
        self.save_now()
        if self.dirty:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Import pre-annotations", os.path.dirname(self.P.path),
                                                "JSON / JSONL (*.json *.jsonl *.txt);;All files (*)")
        if not paths:
            return
        total = {"imported": 0, "skipped_existing": 0, "empty": 0, "unmatched": [], "errors": []}
        for path in paths:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    records = core.parse_preannotation_text(f.read())
            except (OSError, ValueError) as e:
                total["errors"].append("%s: %s" % (os.path.basename(path), e))
                continue
            r = self.P.import_preannotations(records)
            for k in ("imported", "skipped_existing", "empty"):
                total[k] += r[k]
            total["unmatched"] += r["unmatched"]
            total["errors"] += r["errors"]
        for i in range(len(self.rows)):
            self.refresh_row(i)
        self.rebuild_chars()
        self.update_stats()
        self.apply_filters()
        self.select_line(max(self.cur, 0))
        msg = "Imported %d line(s). Their 'Last edited by' says AI pre-annotation until you change them." % total["imported"]
        if total["skipped_existing"]:
            msg += "\\nKept %d line(s) that were already annotated." % total["skipped_existing"]
        if total["empty"]:
            msg += "\\nIgnored %d dialogue record(s) with no annotations." % total["empty"]
        if total["unmatched"]:
            msg += "\\nNo matching subtitle line for %d record(s): %s" % (
                len(total["unmatched"]), ", ".join(str(x) for x in total["unmatched"][:10]))
        if total["errors"]:
            msg += "\\n\\nProblems (%d):\\n%s" % (len(total["errors"]), "\\n".join(total["errors"][:10]))
        (QMessageBox.warning if total["errors"] or total["unmatched"] else QMessageBox.information)(
            self, "Import pre-annotations", msg)

    def export(self, fmt_):
        if not self.P:
            return
        self.save_now()
        base = os.path.splitext(os.path.basename(self.P.cfg["movie"] or self.P.cfg["subs"]))[0]
        default = os.path.join(os.path.dirname(self.P.path), "%s.%s.%s" % (base, self.P.cfg["annotator"], fmt_))
        path, _ = QFileDialog.getSaveFileName(self, "Export", default, "*.%s" % fmt_)
        if not path:
            return
        body, _ = self.P.export(fmt_, self.act_all.isChecked())
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        self.statusBar().showMessage("Exported → %s" % path, 6000)

    def closeEvent(self, e):
        self.save_now()
        if self.dirty:
            e.ignore()
            return
        if self.player:
            self.player.stop()
        e.accept()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Screenplay Annotator (desktop)")
    for a in ("movie", "subs", "subs2", "lang1", "lang2", "annotator", "schema", "outdir", "encoding"):
        ap.add_argument("--" + a)
    ap.add_argument("--dump-schema", metavar="FILE")
    args = ap.parse_args(argv)
    if args.dump_schema:
        with open(args.dump_schema, "w", encoding="utf-8") as f:
            json.dump(core.DEFAULT_SCHEMA, f, ensure_ascii=False, indent=2)
        print("Wrote", args.dump_schema)
        return 0
    app = QApplication(sys.argv[:1])
    font = app.font()
    font.setFamilies(["Segoe UI", "Vazirmatn", "Tahoma", font.family()])
    app.setFont(font)
    win = MainWindow()
    win.show()
    if args.subs:
        try:
            win.set_project(core.Project(vars(args)))
        except (ValueError, OSError) as e:
            QMessageBox.critical(win, "Cannot open", str(e))
            if not win.open_dialog():
                return 1
    elif not win.open_dialog():
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

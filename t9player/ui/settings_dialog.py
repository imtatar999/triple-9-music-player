"""Settings window. Most changes apply immediately and are saved; theme and
language need a restart (one click, the music continues)."""

import os

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION, audio, i18n, meta, theme, updater
from ..i18n import tr
from .decor import DecorPage


class ColorButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, color, tooltip, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self._color = color
        self._apply()
        self.clicked.connect(self._pick)

    def _apply(self):
        self.setStyleSheet(f"QPushButton {{ background: {self._color}; border: 1px solid {theme.FAINT}; border-radius: 6px; }}"
                           f"QPushButton:hover {{ border: 1px solid {theme.RED_BRIGHT}; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, tr("Choose a colour"))
        if c.isValid():
            self._color = c.name()
            self._apply()
            self.color_changed.emit(self._color)

    def set_color(self, color):
        self._color = color
        self._apply()


class ThemeCard(QAbstractButton):
    """A small preview of a theme: sidebar, accent, lyrics colours, its title font."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.t = theme.THEMES[name]
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(176, 112)
        self.setToolTip(tr(self.t["hint"]))
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(176, 112)

    def paintEvent(self, event):
        t = self.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["BG"]))
        p.drawRoundedRect(r, 10, 10)
        side = QRectF(r.left(), r.top(), 34, r.height())
        p.setBrush(QColor(t["SIDEBAR"]))
        p.drawRoundedRect(side, 10, 10)
        p.drawRect(side.adjusted(20, 0, 0, 0))
        for i in range(4):
            c = QColor(t["RED"] if i == 1 else t["DIM"])
            c.setAlpha(255 if i == 1 else 120)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(side.left() + 7, side.top() + 14 + i * 12, 20, 5), 2, 2)
        # lyric lines: sung / current / upcoming
        x = side.right() + 10
        for i, (key, w) in enumerate((("LYR_PAST", 70), ("LYR_ACTIVE", 100), ("LYR_UPCOMING", 84), ("LYR_UPCOMING", 60))):
            p.setBrush(QColor(t[key]))
            p.drawRoundedRect(QRectF(x, r.top() + 12 + i * 11, w, 6), 3, 3)
        # accent play button + a picture from the album
        p.setBrush(QColor(t["RED"]))
        p.drawEllipse(QRectF(r.right() - 30, r.top() + 10, 20, 20))
        from .decor import card_art
        card_art(p, self.name, r)
        f = QFont(t["TITLE_FONT"])
        f.setPixelSize(int(15 * t["TITLE_SCALE"]))
        f.setWeight(QFont.Weight(t["TITLE_WEIGHT"]))
        p.setFont(f)
        p.setPen(QColor(t["TEXT"]))
        label = theme.title_text(t["label"], t["TITLE_CASE"], t["TITLE_FONT"])
        box = QRectF(x, r.bottom() - 48, r.right() - x - 6, 44)
        fm = QFontMetrics(f)
        words = label.split()
        if fm.horizontalAdvance(label) > box.width() and len(words) > 1:
            # two balanced lines ("Legends / Never Die") instead of one long line and a lonely word
            cut = min(range(1, len(words)), key=lambda i: max(fm.horizontalAdvance(" ".join(words[:i])),
                                                              fm.horizontalAdvance(" ".join(words[i:]))))
            first, second = " ".join(words[:cut]), " ".join(words[cut:])
            if max(fm.horizontalAdvance(first), fm.horizontalAdvance(second)) <= box.width():
                label = first + "\n" + second
                f.setPixelSize(int(13 * t["TITLE_SCALE"]))      # two lines must fit the card
                p.setFont(f)
        p.drawText(box, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, label)
        if self.isChecked() or self._hover:
            p.setBrush(Qt.NoBrush)
            from PySide6.QtGui import QPen
            p.setPen(QPen(QColor(theme.RED_BRIGHT if self.isChecked() else theme.FAINT), 2.5 if self.isChecked() else 1.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)


def _hint(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
    return lab


class SettingsDialog(QDialog):
    lyrics_style_changed = Signal()
    lyrics_order_changed = Signal()
    audio_changed = Signal()
    folders_changed = Signal(list, list)      # new list, removed folders
    rescan_requested = Signal()
    update_check_requested = Signal()
    tour_requested = Signal()
    restart_requested = Signal()
    online_covers_changed = Signal(bool)
    rain_changed = Signal(bool)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Settings") + f" - {APP_NAME}")
        self.setMinimumSize(700, 700)
        # tall enough to show every theme card and the language row without scrolling
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
        self.resize(min(780, screen.width() - 60), min(940, screen.height() - 50))
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._scroll(self._look_tab()), tr("Look"))
        self.tabs.addTab(self._scroll(self._audio_tab()), tr("Playback"))
        self.tabs.addTab(self._scroll(self._lyrics_tab()), tr("Lyrics"))
        self.tabs.addTab(self._scroll(self._library_tab()), tr("Library"))
        self.tabs.addTab(self._scroll(self._general_tab()), tr("General"))
        bottom = QHBoxLayout()
        self.restart_note = QLabel(tr("Restart the player to use the new look / language."))
        self.restart_note.setStyleSheet(f"color: {theme.RED_BRIGHT}; font-size: 12px;")
        self.restart_btn = QPushButton(tr("Restart now"))
        self.restart_btn.setObjectName("Primary")
        self.restart_btn.setToolTip(tr("Restart the player now - the music continues where it was"))
        self.restart_btn.clicked.connect(self.restart_requested)
        bottom.addWidget(self.restart_note)
        bottom.addWidget(self.restart_btn)
        bottom.addStretch(1)
        close = QPushButton(tr("Close"))
        close.setToolTip(tr("Close the settings (everything is already saved)"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)
        self._started_theme = theme.NAME
        self._started_language = settings["language"]
        self._update_restart()

    @staticmethod
    def _scroll(widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(widget)
        return area

    def _update_restart(self):
        need = (self.settings["theme"] != self._started_theme or self.settings["language"] != self._started_language)
        self.restart_note.setVisible(need)
        self.restart_btn.setVisible(need)

    # ------------------------------------------------------------------ look
    def _look_tab(self):
        w = DecorPage()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        title = QLabel(tr("Theme"))
        title.setObjectName("H2")
        lay.addWidget(title)
        lay.addWidget(_hint(tr("Colours and small details for the whole player, including the synced lyrics.")))
        self.cards_box = QWidget()
        self.cards = QGridLayout(self.cards_box)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(10)
        lay.addWidget(self.cards_box)
        self._fill_cards()

        lang_row = QHBoxLayout()
        lab = QLabel(tr("Language"))
        lab.setObjectName("H2")
        lang_row.addWidget(lab)
        self.language = QComboBox()
        self.language.setToolTip(tr("Language of the player's texts"))
        for code, label in i18n.LANGUAGES:
            self.language.addItem(tr(label), code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.settings["language"])))
        self.language.currentIndexChanged.connect(self._on_language)
        lang_row.addWidget(self.language)
        lang_row.addStretch(1)
        rain = QCheckBox(tr("Falling code animation in the Matrix theme"))
        rain.setToolTip(tr("Turn off if the moving code rain is distracting"))
        rain.setChecked(self.settings["matrix_rain"])
        rain.toggled.connect(lambda v: (self.settings.set("matrix_rain", v), self.rain_changed.emit(v)))
        lay.addWidget(rain)
        self.rain_box = rain
        rain.setVisible("matrix" in self.settings["theme_keys"])
        lay.addSpacing(8)
        lay.addLayout(lang_row)

        code_row = QHBoxLayout()
        code_lab = QLabel(tr("Code:"))
        code_lab.setToolTip(tr("Some themes are hidden until you type their code"))
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.Password)
        self.code.setPlaceholderText("••••••")
        self.code.setFixedWidth(200)
        self.code.setToolTip(tr("Type a secret code and press Enter"))
        unlock = QPushButton(tr("Unlock"))
        unlock.setToolTip(tr("Check the code"))
        self.code_result = QLabel("")
        self.code.returnPressed.connect(self._try_code)
        unlock.clicked.connect(self._try_code)
        code_row.addWidget(code_lab)
        code_row.addWidget(self.code)
        code_row.addWidget(unlock)
        code_row.addWidget(self.code_result, 1)
        lay.addSpacing(8)
        lay.addLayout(code_row)
        lay.addStretch(1)
        return w

    def _fill_cards(self):
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        current = self.settings["theme"]
        self._card_widgets = []
        for i, name in enumerate(theme.visible_themes(self.settings["theme_keys"])):
            card = ThemeCard(name)
            card.setChecked(name == current)
            card.clicked.connect(lambda _=False, n=name: self._choose_theme(n))
            self.cards.addWidget(card, i // 3, i % 3)
            self._card_widgets.append(card)

    def _choose_theme(self, name):
        for card in self._card_widgets:
            card.setChecked(card.name == name)
        t = theme.THEMES[name]
        # the synced lyrics follow the theme (can still be changed in the Lyrics tab)
        self.settings.update({"theme": name, "lyrics_active_color": t["LYR_ACTIVE"],
                              "lyrics_upcoming_color": t["LYR_UPCOMING"], "lyrics_past_color": t["LYR_PAST"]})
        self.c_active.set_color(t["LYR_ACTIVE"])
        self.c_up.set_color(t["LYR_UPCOMING"])
        self.c_past.set_color(t["LYR_PAST"])
        self.lyrics_style_changed.emit()
        self._update_restart()

    def _on_language(self, _):
        self.settings.set("language", self.language.currentData())
        self._update_restart()

    def _try_code(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            name, shown, keys = theme.try_code(self.code.text(), self.settings["theme_keys"])
        finally:
            QApplication.restoreOverrideCursor()
        self.code.clear()
        if name is None:
            self.code_result.setText(tr("Wrong code"))
            self.code_result.setStyleSheet(f"color: {theme.DIM};")
            return
        self.settings.set("theme_keys", keys)
        if not shown and self.settings["theme"] == name:
            self._choose_theme("999")
        self.rain_box.setVisible("matrix" in keys)
        self._fill_cards()
        if shown:
            self.code_result.setText(tr("Unlocked the {name} theme", name=theme.THEMES[name]["label"]) + " ♥")
            self.code_result.setStyleSheet(f"color: {theme.THEMES[name]['RED']}; font-weight: 600;")
        else:
            self.code_result.setText(tr("Code accepted"))
            self.code_result.setStyleSheet(f"color: {theme.DIM};")

    # ------------------------------------------------------------------ playback
    def _audio_tab(self):
        w = DecorPage()
        form = QFormLayout(w)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        s = self.settings
        self.device = QComboBox()
        self.device.setToolTip(tr("Which speakers or headphones to play through") + "\n" +
                               tr("System default follows Windows: switch the device there and the music moves with it."))
        self.device.addItem(tr("System default"), "")
        for name, _ in audio.list_output_devices():
            self.device.addItem(name, name)
        idx = self.device.findData(s["output_device"])
        self.device.setCurrentIndex(max(0, idx))
        self.device.currentIndexChanged.connect(self._audio_save)
        form.addRow(tr("Output device"), self.device)

        self.exclusive = QCheckBox(tr("WASAPI Exclusive mode (bit-perfect)"))
        self.exclusive.setToolTip(tr("Sends the original samples straight to the device, bypassing the Windows mixer"))
        self.exclusive.setChecked(s["exclusive_mode"])
        self.exclusive.toggled.connect(self._audio_save)
        form.addRow("", self.exclusive)
        form.addRow("", _hint(tr(
            "Exclusive mode plays every file at its own sample rate and bit depth with no resampling "
            "or mixing - true lossless output. Other apps cannot play sound while it is active. "
            "Keep the player volume at 100% for bit-perfect output and set the level on your amp/DAC or Windows.")))

        self.buffer = QComboBox()
        self.buffer.setToolTip(tr("Bigger buffer = safer against stutter, slightly slower reaction"))
        for label, ms in ((tr("Low latency (80 ms)"), 80), (tr("Balanced (150 ms)"), 150),
                          (tr("Safe (300 ms)"), 300), (tr("Very safe (500 ms)"), 500)):
            self.buffer.addItem(label, ms)
        self.buffer.setCurrentIndex(max(0, self.buffer.findData(s["buffer_ms"])))
        if self.buffer.findData(s["buffer_ms"]) < 0:
            self.buffer.setCurrentIndex(1)
        self.buffer.currentIndexChanged.connect(self._audio_save)
        form.addRow(tr("Output buffer"), self.buffer)

        self.gapless = QCheckBox(tr("Gapless playback"))
        self.gapless.setToolTip(tr("No silence between songs that flow into each other (live albums, mixes)"))
        self.gapless.setChecked(s["gapless"])
        self.gapless.toggled.connect(self._audio_save)
        form.addRow("", self.gapless)

        xf = QHBoxLayout()
        self.crossfade = QSlider(Qt.Horizontal)
        self.crossfade.setRange(0, 12)
        self.crossfade.setPageStep(1)
        self.crossfade.setValue(s["crossfade"])
        self.crossfade.setToolTip(tr("How long the end of a song overlaps the start of the next one"))
        self.crossfade_label = QLabel("")
        self.crossfade_label.setFixedWidth(70)
        self.crossfade.valueChanged.connect(self._on_crossfade_moved)
        self.crossfade.sliderReleased.connect(self._audio_save)
        self.crossfade.valueChanged.connect(lambda _: None if self.crossfade.isSliderDown() else self._audio_save())
        xf.addWidget(self.crossfade, 1)
        xf.addWidget(self.crossfade_label)
        form.addRow(tr("Crossfade"), xf)
        form.addRow("", _hint(tr(
            "Songs blend smoothly into each other (1-12 s). While crossfade is on the sound is mixed, "
            "so it is not bit-perfect - set it to Off for pure lossless playback.")))
        self._on_crossfade_moved(s["crossfade"])

        self.resume = QCheckBox(tr("Resume where I left off when the player starts"))
        self.resume.setToolTip(tr("Restores the queue, song and position from the last session"))
        self.resume.setChecked(s["resume_on_start"])
        self.resume.toggled.connect(lambda v: s.set("resume_on_start", v))
        form.addRow("", self.resume)
        return w

    def _on_crossfade_moved(self, value):
        self.crossfade_label.setText(tr("Off") if value == 0 else f"{value} s")

    def _audio_save(self, *_):
        self.settings.update({
            "output_device": self.device.currentData() or "",
            "exclusive_mode": self.exclusive.isChecked(),
            "buffer_ms": int(self.buffer.currentData() or 150),
            "gapless": self.gapless.isChecked(),
            "crossfade": int(self.crossfade.value()),
        })
        self.audio_changed.emit()

    # ------------------------------------------------------------------ lyrics
    def _lyrics_tab(self):
        w = DecorPage()
        form = QFormLayout(w)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        s = self.settings
        self.font_family = QComboBox()
        self.font_family.setToolTip(tr("Font used for the lyrics"))
        families = QFontDatabase.families()
        preferred = [f for f in ("Segoe UI", "Segoe UI Variable Display", "Segoe UI Black", "Arial",
                                 "Bahnschrift", "Montserrat", "Inter", "Poppins", "Roboto", "Verdana",
                                 "Old London", "I KNOW A GHOST", "Dream MMA", "Ink Free", "Consolas")
                     if f in families]
        others = [f for f in families if f not in preferred and not f.startswith("@")]
        for f in preferred + others:
            self.font_family.addItem(f)
        self.font_family.setCurrentText(s["lyrics_font_family"])
        self.font_family.currentTextChanged.connect(lambda v: self._lyr("lyrics_font_family", v))
        form.addRow(tr("Font"), self.font_family)

        self.font_size = QSpinBox()
        self.font_size.setRange(14, 96)
        self.font_size.setSuffix(" px")
        self.font_size.setToolTip(tr("Size of the lyrics text (also Ctrl+= / Ctrl+- in the lyrics view)"))
        self.font_size.setValue(s["lyrics_font_size"])
        self.font_size.valueChanged.connect(lambda v: self._lyr("lyrics_font_size", int(v)))
        form.addRow(tr("Text size"), self.font_size)

        self.bold = QCheckBox(tr("Bold text"))
        self.bold.setToolTip(tr("Thick letters like in Spotify"))
        self.bold.setChecked(s["lyrics_bold"])
        self.bold.toggled.connect(lambda v: self._lyr("lyrics_bold", v))
        form.addRow("", self.bold)

        self.align = QComboBox()
        self.align.setToolTip(tr("Where the lyric lines sit"))
        self.align.addItem(tr("Left (justified like Spotify)"), "left")
        self.align.addItem(tr("Centered"), "center")
        self.align.setCurrentIndex(max(0, self.align.findData(s["lyrics_align"])))
        self.align.currentIndexChanged.connect(lambda _: self._lyr("lyrics_align", self.align.currentData()))
        form.addRow(tr("Alignment"), self.align)

        colors = QHBoxLayout()
        self.c_active = ColorButton(s["lyrics_active_color"], tr("Colour of the line being sung"))
        self.c_up = ColorButton(s["lyrics_upcoming_color"], tr("Colour of the lines still to come"))
        self.c_past = ColorButton(s["lyrics_past_color"], tr("Colour of the lines already sung"))
        for label, btn, key in ((tr("Current"), self.c_active, "lyrics_active_color"),
                                (tr("Upcoming"), self.c_up, "lyrics_upcoming_color"),
                                (tr("Sung"), self.c_past, "lyrics_past_color")):
            box = QVBoxLayout()
            lab = QLabel(label)
            lab.setObjectName("Dim")
            box.addWidget(lab)
            box.addWidget(btn)
            colors.addLayout(box)
            btn.color_changed.connect(lambda v, k=key: self._lyr(k, v))
        colors.addStretch(1)
        form.addRow(tr("Colours"), colors)

        presets = QHBoxLayout()
        cur = theme.THEMES[self.settings["theme"]] if self.settings["theme"] in theme.THEMES else theme.THEMES["999"]
        for name, active, up, past in (
                (tr("Theme"), cur["LYR_ACTIVE"], cur["LYR_UPCOMING"], cur["LYR_PAST"]),
                ("Blood", "#ff3b47", "#e9e9ec", "#5a5a62"),
                ("Spotify", "#ffffff", "#8fd3ff", "#5b88a6"),
                ("Classic", "#22e04b", "#e6e6e6", "#6a6a6a")):
            b = QPushButton(name)
            b.setToolTip(tr("Use the {name} colour set", name=name))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=active, u=up, p=past: self._preset(a, u, p))
            presets.addWidget(b)
        presets.addStretch(1)
        form.addRow(tr("Presets"), presets)

        self.cover_side = QComboBox()
        self.cover_side.setToolTip(tr("Which half of the screen shows the album cover"))
        self.cover_side.addItem(tr("Cover on the left, lyrics on the right"), "left")
        self.cover_side.addItem(tr("Lyrics on the left, cover on the right"), "right")
        self.cover_side.setCurrentIndex(max(0, self.cover_side.findData(s["lyrics_cover_side"])))
        self.cover_side.currentIndexChanged.connect(lambda _: self._lyr("lyrics_cover_side", self.cover_side.currentData()))
        form.addRow(tr("Layout"), self.cover_side)

        self.karaoke = QCheckBox(tr("Word-by-word highlight (when the .lrc has word timing)"))
        self.karaoke.setToolTip(tr("Fills each word as it is sung - needs an enhanced LRC with <mm:ss.xx> word tags"))
        self.karaoke.setChecked(s["lyrics_karaoke"])
        self.karaoke.toggled.connect(lambda v: self._lyr("lyrics_karaoke", v))
        form.addRow("", self.karaoke)

        order_box = QVBoxLayout()
        order_box.setSpacing(6)
        row = QHBoxLayout()
        self.order = QListWidget()
        self.order.setToolTip(tr("The player checks these places from the top down"))
        self.order.setFixedHeight(3 * 30 + 8)
        self._fill_order(meta.normalize_lyrics_order(s["lyrics_order"]))
        row.addWidget(self.order, 1)
        arrows = QVBoxLayout()
        up = QPushButton(tr("Up"))
        up.setToolTip(tr("Check the selected place earlier"))
        down = QPushButton(tr("Down"))
        down.setToolTip(tr("Check the selected place later"))
        reset = QPushButton(tr("Default"))
        reset.setToolTip(tr("Embedded lyrics first, then .lrc, then .txt"))
        up.clicked.connect(lambda: self._move_order(-1))
        down.clicked.connect(lambda: self._move_order(1))
        reset.clicked.connect(lambda: self._set_order(list(meta.LYRICS_SOURCES)))
        for b in (up, down, reset):
            b.setCursor(Qt.PointingHandCursor)
            arrows.addWidget(b)
        arrows.addStretch(1)
        row.addLayout(arrows)
        order_box.addLayout(row)
        order_box.addWidget(_hint(tr(
            "Synced lyrics always win over plain text: the first place in this list that has synced "
            "lyrics is used, plain lyrics only when no place has synced ones.")))
        form.addRow(tr("Lyrics source\norder"), order_box)
        return w

    def _fill_order(self, order):
        self.order.clear()
        for i, key in enumerate(order, 1):
            item = QListWidgetItem(f"{i}.  {tr(meta.LYRICS_SOURCE_NAMES[key])}")
            item.setData(Qt.UserRole, key)
            self.order.addItem(item)

    def _current_order(self):
        return [self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]

    def _move_order(self, delta):
        row = self.order.currentRow()
        order = self._current_order()
        new = row + delta
        if row < 0 or not 0 <= new < len(order):
            return
        order[row], order[new] = order[new], order[row]
        self._set_order(order)
        self.order.setCurrentRow(new)

    def _set_order(self, order):
        self._fill_order(order)
        self.settings.set("lyrics_order", order)
        self.lyrics_order_changed.emit()

    def _lyr(self, key, value):
        self.settings.set(key, value)
        self.lyrics_style_changed.emit()

    def _preset(self, active, up, past):
        self.settings.update({"lyrics_active_color": active, "lyrics_upcoming_color": up,
                              "lyrics_past_color": past})
        self.c_active.set_color(active)
        self.c_up.set_color(up)
        self.c_past.set_color(past)
        self.lyrics_style_changed.emit()

    def sync_lyrics_controls(self):
        """Reflect changes made with keyboard shortcuts while the dialog is open."""
        self.font_size.blockSignals(True)
        self.font_size.setValue(self.settings["lyrics_font_size"])
        self.font_size.blockSignals(False)

    # ------------------------------------------------------------------ library
    def _library_tab(self):
        w = DecorPage()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)
        lab = QLabel(tr("Music folders"))
        lab.setObjectName("H2")
        lay.addWidget(lab)
        lay.addWidget(_hint(tr("Songs in these folders (and their subfolders) appear in your library. "
                               "Files are only read, never changed or deleted.")))
        self.folders = QListWidget()
        self.folders.addItems(self.settings["library_folders"])
        lay.addWidget(self.folders, 1)
        row = QHBoxLayout()
        add = QPushButton(tr("Add folder..."))
        add.setToolTip(tr("Choose a folder with music to add to the library"))
        remove = QPushButton(tr("Remove"))
        remove.setToolTip(tr("Stop showing songs from the selected folder (files stay on disk)"))
        rescan = QPushButton(tr("Rescan now"))
        rescan.setToolTip(tr("Look for new, changed and removed songs"))
        add.clicked.connect(self._add_folder)
        remove.clicked.connect(self._remove_folder)
        rescan.clicked.connect(self.rescan_requested)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(rescan)
        lay.addLayout(row)
        self.rescan_start = QCheckBox(tr("Check folders for changes every time the player starts"))
        self.rescan_start.setToolTip(tr("A quick background check - the player stays usable meanwhile"))
        self.rescan_start.setChecked(self.settings["rescan_on_start"])
        self.rescan_start.toggled.connect(lambda v: self.settings.set("rescan_on_start", v))
        lay.addWidget(self.rescan_start)
        online = QCheckBox(tr("Download album covers (MusicBrainz) and artist pictures (Deezer)"))
        online.setToolTip(tr("Looks up official album covers and artist photos on the internet. "
                             "Without a connection the cover of one of the songs is used."))
        online.setChecked(self.settings["online_covers"])
        online.toggled.connect(lambda v: (self.settings.set("online_covers", v), self.online_covers_changed.emit(v)))
        lay.addWidget(online)
        lay.addWidget(_hint(tr("Right-click an album or artist (or use ⋮ on its page) to pick a different picture: "
                               "one of its songs, or any image on this computer.")))
        return w

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Add a music folder"))
        if not folder:
            return
        folder = os.path.normpath(folder)
        current = list(self.settings["library_folders"])
        if folder in current:
            return
        current.append(folder)
        self.settings.set("library_folders", current)
        self.folders.addItem(folder)
        self.folders_changed.emit(current, [])

    def _remove_folder(self):
        item = self.folders.currentItem()
        if item is None:
            return
        folder = item.text()
        current = [f for f in self.settings["library_folders"] if f != folder]
        self.settings.set("library_folders", current)
        self.folders.takeItem(self.folders.row(item))
        self.folders_changed.emit(current, [folder])

    # ------------------------------------------------------------------ general
    def _general_tab(self):
        w = DecorPage()
        form = QFormLayout(w)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        tray = QCheckBox(tr("Closing the window keeps the music playing in the tray"))
        tray.setToolTip(tr("The player hides next to the clock instead of quitting"))
        tray.setChecked(self.settings["minimize_to_tray"])
        tray.toggled.connect(lambda v: self.settings.set("minimize_to_tray", v))
        form.addRow("", tray)
        mkeys = QCheckBox(tr("Keyboard media keys control this player even in the background"))
        mkeys.setToolTip(tr("Turn off if you want play/pause keys to control your browser instead (applies after restart)"))
        mkeys.setChecked(self.settings["global_media_keys"])
        mkeys.toggled.connect(lambda v: self.settings.set("global_media_keys", v))
        form.addRow("", mkeys)

        upd = QVBoxLayout()
        upd.setSpacing(6)
        online = QCheckBox(tr("Check GitHub for a new version at start-up"))
        online.setToolTip(tr("Shows a notification when a newer version is published and installs it on request"))
        online.setChecked(self.settings["online_updates"])
        online.toggled.connect(lambda v: self.settings.set("online_updates", v))
        online_row = QHBoxLayout()
        online_row.addWidget(online, 1)
        check = QPushButton(tr("Check now"))
        check.setToolTip(tr("Look for a newer version right now (GitHub and the update folder)"))
        check.setCursor(Qt.PointingHandCursor)
        check.clicked.connect(self.update_check_requested)
        online_row.addWidget(check)
        upd.addLayout(online_row)
        row = QHBoxLayout()
        self.update_folder = QLineEdit(self.settings["update_folder"])
        self.update_folder.setReadOnly(True)
        self.update_folder.setPlaceholderText(tr("No update folder chosen"))
        self.update_folder.setToolTip(tr("Folder where you put new T9MusicPlayer-Setup-X.Y.Z.exe files"))
        choose = QPushButton(tr("Choose..."))
        choose.setToolTip(tr("Pick the folder that receives new installers (e.g. on OneDrive or a USB stick)"))
        clear = QPushButton(tr("Clear"))
        clear.setToolTip(tr("Stop looking in this folder"))
        choose.clicked.connect(self._choose_update_folder)
        clear.clicked.connect(lambda: self._set_update_folder(""))
        row.addWidget(self.update_folder, 1)
        for b in (choose, clear):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        upd.addLayout(row)
        upd.addWidget(_hint(tr(
            "Optional: a folder (OneDrive, USB stick...) with newer T9MusicPlayer-Setup-X.Y.Z.exe files is "
            "checked too. Your library, playlists and settings are always kept.")))
        form.addRow(tr("Updates"), upd)
        version = QLabel(f"{APP_NAME} {APP_VERSION}")
        version.setObjectName("Dim")
        ver_row = QHBoxLayout()
        ver_row.addWidget(version)
        ver_row.addSpacing(12)
        for label, tip, url in ((tr("Project page"), tr("Open the player's page on GitHub"), updater.PROJECT_PAGE),
                                (tr("What's new"), tr("See what changed in every version"), updater.RELEASES_PAGE)):
            link = QPushButton(label)
            link.setToolTip(tip)
            link.setCursor(Qt.PointingHandCursor)
            link.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            ver_row.addWidget(link)
        ver_row.addStretch(1)
        form.addRow(tr("Version"), ver_row)
        tour = QPushButton(tr("Show the tour again"))
        tour.setToolTip(tr("The short walk-through of the main features from the first start"))
        tour.setCursor(Qt.PointingHandCursor)
        tour.clicked.connect(lambda: (self.close(), self.tour_requested.emit()))
        tour_row = QHBoxLayout()
        tour_row.addWidget(tour)
        tour_row.addStretch(1)
        form.addRow(tr("Tour"), tour_row)
        keys = QLabel(tr(
            "Space - play / pause\n"
            "Ctrl+Left / Ctrl+Right - previous / next song\n"
            "Left / Right - jump 5 s back / forward\n"
            "Up / Down - volume\n"
            "M - mute       S - shuffle       R - repeat       F - favourite\n"
            "L - lyrics view       Q - queue       Ctrl+M - compact player\n"
            "F11 - full screen       Esc / Backspace - back\n"
            "[ / ] - lyrics earlier / later       Ctrl+= / Ctrl+- - lyrics text size\n"
            "Ctrl+F - search       Ctrl+O - open files\n"
            "Media keys on the keyboard work even when the player is in the background."))
        keys.setStyleSheet(f"color: {theme.DIM}; font-size: 12px;")
        form.addRow(tr("Shortcuts"), keys)
        return w

    def _choose_update_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Choose the update folder"), self.settings["update_folder"])
        if folder:
            self._set_update_folder(os.path.normpath(folder))

    def _set_update_folder(self, folder):
        self.settings.set("update_folder", folder)
        self.update_folder.setText(folder)

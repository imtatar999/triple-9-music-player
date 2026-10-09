"""Bottom player bar and the transport wiring shared with the mini player."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import audio, theme
from ..i18n import tr
from .widgets import CoverWidget, ElidedLabel, IconButton, SeekBar, VolumeSlider, bold_font, fmt_time


class Transport(QObject):
    """Connects one set of controls to the Player and keeps them in sync."""

    def __init__(self, player, play, prev, nxt, shuffle, repeat, seek, t_pos, t_dur,
                 heart=None, volume=None, vol_btn=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.play, self.prev, self.nxt = play, prev, nxt
        self.shuffle_btn, self.repeat_btn = shuffle, repeat
        self.seek, self.t_pos, self.t_dur = seek, t_pos, t_dur
        self.heart, self.volume, self.vol_btn = heart, volume, vol_btn
        self._preview = None
        play.clicked.connect(player.play_pause)
        prev.clicked.connect(player.previous)
        nxt.clicked.connect(player.next)
        shuffle.clicked.connect(lambda: player.set_shuffle(not player.shuffle))
        repeat.clicked.connect(player.cycle_repeat)
        seek.seek_requested.connect(self._on_seek)
        seek.preview.connect(self._on_preview)
        if heart is not None:
            heart.clicked.connect(lambda: player.toggle_favorite())
        if volume is not None:
            volume.value_changed.connect(lambda v: player.set_volume(v, save=False))
            volume.released.connect(player.save_volume)
        if vol_btn is not None:
            vol_btn.clicked.connect(player.toggle_mute)
        player.state_changed.connect(self._on_state)
        player.modes_changed.connect(self._on_modes)
        player.duration_changed.connect(self._on_duration)
        player.track_changed.connect(self._on_track)
        player.favorite_changed.connect(lambda t: self._on_track(player.current))
        player.volume_changed.connect(self._on_volume)
        self._on_state(player.state)
        self._on_modes()
        self._on_duration(player.duration)
        self._on_track(player.current)
        self._on_volume(player.volume, player.muted)

    def _on_seek(self, value):
        self._preview = None
        self.player.seek(value)

    def _on_preview(self, value):
        self._preview = value
        self.t_pos.setText(fmt_time(value))

    def tick(self):
        if self._preview is not None:
            return
        pos = self.player.position()
        self.seek.set_value(pos)
        text = fmt_time(pos)
        if self.t_pos.text() != text:
            self.t_pos.setText(text)

    def _on_state(self, state):
        playing = state == audio.STATE_PLAYING
        self.play.set_icon("pause" if playing else "play")
        self.play.setToolTip(tr("Pause (Space)") if playing else tr("Play (Space)"))

    def _on_modes(self):
        p = self.player
        self.shuffle_btn.setChecked(p.shuffle)
        self.shuffle_btn.setToolTip(tr("Shuffle: on (S)") if p.shuffle else tr("Shuffle: off (S)"))
        self.repeat_btn.setChecked(p.repeat != "off")
        self.repeat_btn.set_icon("repeat_one" if p.repeat == "one" else "repeat")
        self.repeat_btn.setToolTip({"off": tr("Repeat: off (R)"), "all": tr("Repeat: whole queue (R)"),
                                    "one": tr("Repeat: this song (R)")}[p.repeat])

    def _on_duration(self, duration):
        self.seek.set_duration(duration)
        self.t_dur.setText(fmt_time(duration))

    def _on_track(self, track):
        if self.heart is not None:
            fav = bool(track and track.favorite)
            self.heart.set_icon("heart" if fav else "heart_outline")
            self.heart.setChecked(fav)
            self.heart.setEnabled(track is not None)
            self.heart.setToolTip(tr("Remove from Favorites (F)") if fav else tr("Add to Favorites (F)"))
        if track is None:
            self.seek.set_value(0)
            self.t_pos.setText("0:00")

    def _on_volume(self, volume, muted):
        if self.volume is not None:
            self.volume.set_value(volume, muted)
        if self.vol_btn is not None:
            if muted or volume <= 0.001:
                name = "volume_off"
            elif volume < 0.5:
                name = "volume_low"
            else:
                name = "volume"
            self.vol_btn.set_icon(name)
            self.vol_btn.setToolTip(tr("Unmute (M)") if muted else
                                    tr("Mute (M) - volume {n}%", n=int(round(volume * 100))))


def time_label(align):
    lab = QLabel("0:00")
    lab.setObjectName("Dim")
    lab.setFixedWidth(46)
    lab.setAlignment(align | Qt.AlignVCenter)
    lab.setStyleSheet("font-size: 11px;")
    return lab


class LinkLabel(ElidedLabel):
    """Elided text that underlines on hover and can be clicked."""
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event):
        f = self.font()
        f.setUnderline(True)
        self.setFont(f)

    def leaveEvent(self, event):
        f = self.font()
        f.setUnderline(False)
        self.setFont(f)


class PlayerBar(QFrame):
    lyrics_clicked = Signal()
    queue_clicked = Signal()
    mini_clicked = Signal()
    cover_clicked = Signal()
    title_clicked = Signal()
    artist_clicked = Signal()
    sleep_clicked = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.setObjectName("PlayerBar")
        self.setFixedHeight(92)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 8, 16, 8)
        root.setSpacing(8)

        # left: cover + titles + heart
        left = QWidget()
        left.setMinimumWidth(220)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        self.cover = CoverWidget(radius=6, shadow=False)
        self.cover.setFixedSize(60, 60)
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.setToolTip(tr("Open the lyrics view (L)"))
        self.cover.clicked.connect(self.cover_clicked)
        ll.addWidget(self.cover)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addStretch(1)
        self.title = LinkLabel(theme.say("Nothing playing"))
        self.title.setFont(bold_font(14))
        self.title.setToolTip(tr("Go to the album"))
        self.title.clicked.connect(self.title_clicked)
        self.artist = LinkLabel("")
        self.artist.setObjectName("Dim")
        self.artist.setStyleSheet("font-size: 12px;")
        self.artist.setToolTip(tr("Go to the artist"))
        self.artist.clicked.connect(self.artist_clicked)
        titles.addWidget(self.title)
        titles.addWidget(self.artist)
        titles.addStretch(1)
        ll.addLayout(titles, 1)
        self.heart = IconButton("heart_outline", tr("Add to Favorites (F)"), 32, 18, checkable=True)
        ll.addWidget(self.heart)

        # center: transport + seek
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.shuffle = IconButton("shuffle", tr("Shuffle (S)"), 34, 18, checkable=True)
        self.prev = IconButton("prev", tr("Previous / restart (Ctrl+Left)"), 36, 22)
        self.play = IconButton("play", tr("Play (Space)"), 42, 20, filled=True)
        self.next = IconButton("next", tr("Next (Ctrl+Right)"), 36, 22)
        self.repeat = IconButton("repeat", tr("Repeat (R)"), 34, 18, checkable=True)
        for b in (self.shuffle, self.prev, self.play, self.next, self.repeat):
            buttons.addWidget(b)
        buttons.addStretch(1)
        cl.addLayout(buttons)
        seek_row = QHBoxLayout()
        seek_row.setSpacing(6)
        self.t_pos = time_label(Qt.AlignRight)
        self.t_dur = time_label(Qt.AlignLeft)
        self.seek = SeekBar()
        self.seek.setToolTip(tr("Drag or click to jump to a moment in the song"))
        seek_row.addWidget(self.t_pos)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.t_dur)
        cl.addLayout(seek_row)

        # right: quality badge + view buttons + volume
        right = QWidget()
        right.setMinimumWidth(240)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addStretch(1)
        self.badge = QLabel("")
        self.badge.setObjectName("Badge")
        self.badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.badge.hide()
        rl.addWidget(self.badge, 0, Qt.AlignVCenter)
        rl.addSpacing(6)
        self.lyrics_btn = IconButton("lyrics", tr("Lyrics view (L)"), 34, 20, checkable=True)
        self.queue_btn = IconButton("queue", tr("Queue - what plays next (Q)"), 34, 20, checkable=True)
        self.sleep_btn = IconButton("timer", tr("Sleep timer - stop the music later"), 34, 20, checkable=True)
        self.mini_btn = IconButton("mini", tr("Compact player (Ctrl+M)"), 34, 20)
        self.vol_btn = IconButton("volume", tr("Mute (M)"), 34, 20)
        self.volume = VolumeSlider(width=100)
        self.volume.setToolTip(tr("Volume - drag, or scroll the mouse wheel"))
        for w in (self.lyrics_btn, self.queue_btn, self.sleep_btn, self.mini_btn, self.vol_btn, self.volume):
            rl.addWidget(w)
        self.lyrics_btn.clicked.connect(self.lyrics_clicked)
        self.queue_btn.clicked.connect(self.queue_clicked)
        self.mini_btn.clicked.connect(self.mini_clicked)
        # the menu decides the checked state
        self.sleep_btn.clicked.connect(lambda: (self.sleep_btn.setChecked(not self.sleep_btn.isChecked()),
                                                self.sleep_clicked.emit()))

        root.addWidget(left, 3)
        root.addWidget(center, 4)
        root.addWidget(right, 3)

        self.transport = Transport(player, self.play, self.prev, self.next, self.shuffle, self.repeat,
                                   self.seek, self.t_pos, self.t_dur, self.heart, self.volume,
                                   self.vol_btn, self)
        player.track_changed.connect(self._on_track)
        player.output_changed.connect(self._update_badge)
        player.volume_changed.connect(lambda *_: self._update_badge(player.output_info))
        self._on_track(player.current)

    def _on_track(self, track):
        if track is None:
            self.title.setText(theme.say("Nothing playing"))
            self.artist.setText(theme.say("Pick a song from the library"))
            self.badge.hide()
            return
        self.title.setText(track.title)
        self.artist.setText(track.display_artist)
        self._update_badge(self.player.output_info, track)

    def _update_badge(self, info, track=None):
        track = track or self.player.current
        if track is None:
            self.badge.hide()
            return
        label = track.format_label
        extra = ""
        if audio.is_bit_perfect(info, self.player.volume, self.player.muted):
            extra = "  •  BIT-PERFECT"
        elif info and info.get("crossfade"):
            extra = "  •  CROSSFADE"
        elif track.hires:
            extra = "  •  HI-RES"
        self.badge.setText(label + extra)
        desc = audio.describe_output(info, self.player.volume, self.player.muted)
        tip = tr("File: {label}", label=label)
        if desc:
            tip += "\n" + tr("Output: {desc}", desc=desc)
        if info and not info.get("exclusive") and not info.get("error"):
            tip += "\n\n" + tr("Tip: turn on WASAPI Exclusive in Settings for bit-perfect playback.")
        self.badge.setToolTip(tip)
        self.badge.show()

    def tick(self):
        self.transport.tick()

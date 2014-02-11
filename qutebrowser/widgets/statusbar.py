# Copyright 2014 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <http://www.gnu.org/licenses/>.

"""Widgets needed in the qutebrowser statusbar."""

import logging

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (QLineEdit, QShortcut, QHBoxLayout, QWidget,
                             QSizePolicy, QProgressBar, QLabel, QStyle,
                             QStyleOption)
from PyQt5.QtGui import QValidator, QKeySequence, QPainter

import qutebrowser.utils.config as config
import qutebrowser.commands.keys as keys
from qutebrowser.utils.url import urlstring


class StatusBar(QWidget):

    """The statusbar at the bottom of the mainwindow."""

    cmd = None
    txt = None
    keystring = None
    percentage = None
    url = None
    prog = None
    resized = pyqtSignal('QRect')
    moved = pyqtSignal('QPoint')
    fgcolor = None
    bgcolor = None
    _stylesheet = """
        * {{
            {color[statusbar.bg.__cur__]}
            {color[statusbar.fg.__cur__]}
            {font[statusbar]}
        }}
    """

    def __setattr__(self, name, value):
        """Update the stylesheet if relevant attributes have been changed."""
        super().__setattr__(name, value)
        if name == 'fgcolor' and value is not None:
            config.colordict['statusbar.fg.__cur__'] = value
            self.setStyleSheet(config.get_stylesheet(self._stylesheet))
        elif name == 'bgcolor' and value is not None:
            config.colordict['statusbar.bg.__cur__'] = value
            self.setStyleSheet(config.get_stylesheet(self._stylesheet))

    # TODO: the statusbar should be a bit smaller
    def __init__(self, mainwindow):
        super().__init__(mainwindow)
        self.fgcolor = config.colordict.getraw('statusbar.fg')
        self.bgcolor = config.colordict.getraw('statusbar.bg')
        self.setStyleSheet(config.get_stylesheet(self._stylesheet))

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(5)

        self.cmd = Command(self)
        hbox.addWidget(self.cmd)

        self.txt = Text(self)
        hbox.addWidget(self.txt)
        hbox.addStretch()

        self.keystring = KeyString(self)
        hbox.addWidget(self.keystring)

        self.url = Url(self)
        hbox.addWidget(self.url)

        self.percentage = Percentage(self)
        hbox.addWidget(self.percentage)

        self.prog = Progress(self)
        hbox.addWidget(self.prog)

    def paintEvent(self, e):
        """Override QWIidget.paintEvent to handle stylesheets."""
        # pylint: disable=unused-argument
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

    def disp_error(self, text):
        """Displaysan error in the statusbar."""
        self.bgcolor = config.colordict.getraw('statusbar.bg.error')
        self.fgcolor = config.colordict.getraw('statusbar.fg.error')
        self.txt.set_error(text)

    def clear_error(self):
        """Clear a displayed error from the status bar."""
        self.bgcolor = config.colordict.getraw('statusbar.bg')
        self.fgcolor = config.colordict.getraw('statusbar.fg')
        self.txt.clear_error()

    def resizeEvent(self, e):
        """Extend resizeEvent of QWidget to emit a resized signal afterwards.

        e -- The QResizeEvent.

        """
        super().resizeEvent(e)
        self.resized.emit(self.geometry())

    def moveEvent(self, e):
        """Extend moveEvent of QWidget to emit a moved signal afterwards.

        e -- The QMoveEvent.

        """
        super().moveEvent(e)
        self.moved.emit(e.pos())


class Command(QLineEdit):

    """The commandline part of the statusbar."""

    # Emitted when a command is triggered by the user
    got_cmd = pyqtSignal(str)
    # Emitted for searches triggered by the user
    got_search = pyqtSignal(str)
    got_search_rev = pyqtSignal(str)
    statusbar = None  # The status bar object
    esc_pressed = pyqtSignal()  # Emitted when escape is pressed
    tab_pressed = pyqtSignal(bool)  # Emitted when tab is pressed (arg: shift)
    hide_completion = pyqtSignal()  # Hide completion window
    history = []  # The command history, with newer commands at the bottom
    _tmphist = []
    _histpos = None

    # FIXME won't the tab key switch to the next widget?
    # See [0] for a possible fix.
    # [0] http://www.saltycrane.com/blog/2008/01/how-to-capture-tab-key-press-event-with/ # noqa # pylint: disable=line-too-long

    def __init__(self, statusbar):
        super().__init__(statusbar)
        # FIXME
        self.statusbar = statusbar
        self.setStyleSheet("border: 0px; padding-left: 1px;")
        self.setValidator(CommandValidator())
        self.returnPressed.connect(self.process_cmdline)
        self.textEdited.connect(self._histbrowse_stop)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

        for (key, handler) in [
                (Qt.Key_Escape, self.esc_pressed),
                (Qt.Key_Up, self.key_up_handler),
                (Qt.Key_Down, self.key_down_handler),
                (Qt.Key_Tab | Qt.SHIFT, lambda: self.tab_pressed.emit(True)),
                (Qt.Key_Tab, lambda: self.tab_pressed.emit(False))
        ]:
            sc = QShortcut(self)
            sc.setKey(QKeySequence(key))
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def process_cmdline(self):
        """Handle the command in the status bar."""
        signals = {
            ':': self.got_cmd,
            '/': self.got_search,
            '?': self.got_search_rev,
        }
        self._histbrowse_stop()
        text = self.text()
        if not self.history or text != self.history[-1]:
            self.history.append(text)
        self.setText('')
        if text[0] in signals:
            signals[text[0]].emit(text.lstrip(text[0]))

    def set_cmd(self, text):
        """Preset the statusbar to some text."""
        self.setText(text)
        self.setFocus()

    def append_cmd(self, text):
        """Append text to the commandline."""
        # FIXME do the right thing here
        self.setText(':' + text)
        self.setFocus()

    def focusOutEvent(self, e):
        """Clear the statusbar text if it's explicitely unfocused."""
        if e.reason() in [Qt.MouseFocusReason, Qt.TabFocusReason,
                          Qt.BacktabFocusReason, Qt.OtherFocusReason]:
            self.setText('')
            self._histbrowse_stop()
        self.hide_completion.emit()
        super().focusOutEvent(e)

    def focusInEvent(self, e):
        """Clear error message when the statusbar is focused."""
        self.statusbar.clear_error()
        super().focusInEvent(e)

    def _histbrowse_start(self):
        """Start browsing to the history.

        Called when the user presses the up/down key and wasn't browsing the
        history already.

        """
        pre = self.text().strip()
        logging.debug('Preset text: "{}"'.format(pre))
        if pre:
            self._tmphist = [e for e in self.history if e.startswith(pre)]
        else:
            self._tmphist = self.history
        self._histpos = len(self._tmphist) - 1

    def _histbrowse_stop(self):
        """Stop browsing the history."""
        self._histpos = None

    def key_up_handler(self):
        """Handle Up presses (go back in history)."""
        logging.debug("history up [pre]: pos {}".format(self._histpos))
        if self._histpos is None:
            self._histbrowse_start()
        elif self._histpos <= 0:
            return
        else:
            self._histpos -= 1
        if not self._tmphist:
            return
        logging.debug("history up: {} / len {} / pos {}".format(
            self._tmphist, len(self._tmphist), self._histpos))
        self.set_cmd(self._tmphist[self._histpos])

    def key_down_handler(self):
        """Handle Down presses (go forward in history)."""
        logging.debug("history up [pre]: pos {}".format(self._histpos,
                      self._tmphist, len(self._tmphist), self._histpos))
        if (self._histpos is None or
                self._histpos >= len(self._tmphist) - 1 or
                not self._tmphist):
            return
        self._histpos += 1
        logging.debug("history up: {} / len {} / pos {}".format(
            self._tmphist, len(self._tmphist), self._histpos))
        self.set_cmd(self._tmphist[self._histpos])


class CommandValidator(QValidator):

    """Validator to prevent the : from getting deleted."""

    def validate(self, string, pos):
        """Override QValidator::validate.

        string -- The string to validate.
        pos -- The current curser position.

        Returns a tuple (status, string, pos) as a QValidator should.

        """
        if any(string.startswith(c) for c in keys.startchars):
            return (QValidator.Acceptable, string, pos)
        else:
            return (QValidator.Invalid, string, pos)


class Progress(QProgressBar):

    """The progress bar part of the status bar."""

    statusbar = None
    color = None
    # FIXME for some reason, margin-left is not shown
    _stylesheet = """
        QProgressBar {{
            border-radius: 0px;
            border: 2px solid transparent;
            margin-left: 1px;
        }}

        QProgressBar::chunk {{
            {color[statusbar.progress.bg.__cur__]}
        }}
    """

    def __init__(self, statusbar):
        self.statusbar = statusbar
        super().__init__(statusbar)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Ignored)
        self.setTextVisible(False)
        self.color = config.colordict.getraw('statusbar.progress.bg')
        self.hide()

    def __setattr__(self, name, value):
        """Update the stylesheet if relevant attributes have been changed."""
        super().__setattr__(name, value)
        if name == 'color' and value is not None:
            config.colordict['statusbar.progress.bg.__cur__'] = value
            self.setStyleSheet(config.get_stylesheet(self._stylesheet))

    def set_progress(self, prog):
        """Set the progress of the bar and show/hide it if necessary."""
        # TODO display failed loading in some meaningful way?
        if prog == 100:
            self.setValue(prog)
        else:
            color = config.colordict.getraw('status.progress.bg')
            if self.color != color:
                self.color = color
            self.setValue(prog)
            self.show()

    def load_finished(self, ok):
        """Hide the progress bar or color it red, depending on ok.

        Slot for the loadFinished signal of a QWebView.

        """
        if ok:
            self.color = config.colordict.getraw('status.progress.bg')
            self.hide()
        else:
            self.color = config.colordict.getraw('statusbar.progress.bg.error')


class TextBase(QLabel):

    """A text in the statusbar."""

    def __init__(self, bar):
        super().__init__(bar)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)


class Text(TextBase):

    """Text displayed in the statusbar."""

    old_text = ''

    def set_error(self, text):
        """Display an error message and save current text in old_text."""
        self.old_text = self.text()
        self.setText(text)

    def clear_error(self):
        """Clear a displayed error message."""
        self.setText(self.old_text)


class KeyString(TextBase):

    """Keychain string displayed in the statusbar."""

    pass


class Percentage(TextBase):

    """Reading percentage displayed in the statusbar."""

    def set_perc(self, x, y):
        """Setter to be used as a Qt slot."""
        # pylint: disable=unused-argument
        if y == 0:
            self.setText('[top]')
        elif y == 100:
            self.setText('[bot]')
        else:
            self.setText('[{:2}%]'.format(y))


class Url(TextBase):

    """URL displayed in the statusbar."""

    old_url = ''

    def set_url(self, s):
        """Setter to be used as a Qt slot."""
        self.setText(urlstring(s))

    def set_hover_url(self, link, title, text):
        """Setter to be used as a Qt slot.

        Saves old shown URL in self.old_url and restores it later if a link is
        "un-hovered" when it gets called with empty parameters.

        """
        # pylint: disable=unused-argument
        if link:
            self.old_url = self.text()
            self.setText(link)
        else:
            self.setText(self.old_url)

"""
A Toolkit engine for Foundry Katana.

Runs inside Katana's Python. It is started by the startup script in
./katana_resources/Startup (found by Katana through KATANA_RESOURCES) and adds
a "Flow Production Tracking" menu to Katana's main menu bar with one entry per
command the configured apps register. In batch/script mode the engine runs
without a menu.

Tested headless in Katana 9.0v4 (Python 3.11, Qt 6). The menu code has not
been run in Katana's UI yet.
"""

import logging

import sgtk
from sgtk.platform import Engine

MENU_TITLE = "Flow Production Tracking"
KATANA_LOGGER = "FlowProductionTracking"


class KatanaEngine(Engine):
    def pre_app_init(self):
        # fails early, with a clear error, if we are not inside Katana
        import Katana  # noqa: F401

        self._menu = None

    @property
    def host_info(self):
        try:
            from Katana import Configuration

            version = Configuration.get("KATANA_RELEASE") or "unknown"
        except Exception:
            version = "unknown"
        return {"name": "Katana", "version": version}

    @property
    def has_ui(self):
        try:
            from Katana import Configuration

            return bool(Configuration.get("KATANA_UI_MODE"))
        except Exception:
            return False

    @property
    def context_change_allowed(self):
        return True

    def post_app_init(self):
        self._build_menu()

    def post_context_change(self, old_context, new_context):
        self._build_menu()

    def destroy_engine(self):
        self._remove_menu()

    # ---- Qt

    def _main_window(self):
        from sgtk.platform.qt import QtGui

        try:
            from Katana import UI4

            window = UI4.App.MainWindow.GetMainWindow()
            if window is not None:
                return window
        except Exception:
            pass
        for widget in QtGui.QApplication.topLevelWidgets():
            if isinstance(widget, QtGui.QMainWindow) and widget.isVisible():
                return widget
        return None

    def _get_dialog_parent(self):
        from sgtk.platform.qt import QtGui

        return self._main_window() or QtGui.QApplication.activeWindow()

    # ---- menu

    def _menu_bar(self):
        """Katana's main menu bar (File, Edit, Render, ...), or None."""
        from sgtk.platform.qt import QtGui

        window = self._main_window()
        if window is not None:
            getter = getattr(window, "getMenuBar", None)
            if getter:
                try:
                    bar = getter()
                    if bar is not None:
                        return bar
                except Exception:
                    pass
            bars = window.findChildren(QtGui.QMenuBar)
            if bars:
                return bars[0]
        # older layouts: the bar is the parent of the "Layouts" menu
        for widget in QtGui.QApplication.topLevelWidgets():
            if type(widget).__name__ == "LayoutsMenu" and widget.parent() is not None:
                return widget.parent()
        return None

    def _build_menu(self):
        if not self.has_ui:
            return
        self._remove_menu()
        bar = self._menu_bar()
        if bar is None:
            self.logger.warning("Katana's menu bar was not found; no menu was added.")
            return
        self._menu = bar.addMenu(MENU_TITLE)
        for name in sorted(self.commands):
            action = self._menu.addAction(name)
            action.triggered.connect(lambda checked=False, n=name: self.run_command(n))

    def _remove_menu(self):
        if self._menu is not None:
            try:
                self._menu.menuAction().setVisible(False)
                self._menu.deleteLater()
            except Exception:
                pass
        self._menu = None

    def run_command(self, name):
        """Run a registered command by name (called from the menu actions)."""
        try:
            self.commands[name]["callback"]()
        except Exception:
            self.logger.exception("Command '%s' failed" % name)

    # ---- logging

    def _emit_log_message(self, handler, record):
        if record.levelno < logging.INFO:
            return
        # Katana shows Python logging in its Messages window
        logging.getLogger(KATANA_LOGGER).log(record.levelno, handler.format(record))

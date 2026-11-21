"""
A Toolkit engine for Foundry Mari.

Runs inside Mari's Python. It is started by the startup script in
./mari_startup (found by Mari through MARI_SCRIPT_PATH) and adds a
"Flow Production Tracking" menu to Mari's main window with one entry per
command the configured apps register. In terminal mode (mari -t / -x) the
engine runs without a menu, which is what the headless tests use.
"""

import logging

import sgtk
from sgtk.platform import Engine

MENU_PATH = "MainWindow/Flow Production Tracking"
ACTION_PATH = "/Mari/Flow Production Tracking/"


class MariEngine(Engine):
    def pre_app_init(self):
        # fails early, with a clear error, if we are not inside Mari
        import mari  # noqa: F401

        self._menu_items = []

    @property
    def host_info(self):
        import mari

        try:
            version = mari.app.version().string()
        except Exception:
            version = "unknown"
        return {"name": "Mari", "version": version}

    @property
    def has_ui(self):
        import mari

        return not mari.app.inTerminalMode()

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

    def _get_dialog_parent(self):
        from sgtk.platform.qt import QtGui

        for widget in QtGui.QApplication.topLevelWidgets():
            if isinstance(widget, QtGui.QMainWindow) and widget.isVisible():
                return widget
        return QtGui.QApplication.activeWindow()

    # ---- menu

    def _build_menu(self):
        if not self.has_ui:
            return
        import mari

        self._remove_menu()
        for name in sorted(self.commands):
            action = mari.actions.create(
                ACTION_PATH + name,
                "import sgtk; sgtk.platform.current_engine().run_command(%r)" % name,
            )
            mari.menus.addAction(action, MENU_PATH)
            self._menu_items.append("%s/%s" % (MENU_PATH, name))

    def _remove_menu(self):
        import mari

        for item_path in self._menu_items:
            try:
                mari.menus.removeAction(item_path)
            except Exception:
                pass
        self._menu_items = []

    def run_command(self, name):
        """Run a registered command by name (called from the menu actions)."""
        try:
            self.commands[name]["callback"]()
        except Exception:
            self.logger.exception("Command '%s' failed" % name)

    # ---- logging

    def _emit_log_message(self, handler, record):
        import mari

        if record.levelno < logging.INFO:
            return
        mari.app.log("[sgtk] %s" % handler.format(record))

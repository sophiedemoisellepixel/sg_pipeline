"""
A Toolkit engine for Adobe Substance 3D Painter.

Runs inside Painter's own Python (PySide6). It is started by the Painter
startup plugin in ./painter/startup, and adds a "Flow Production Tracking"
menu to Painter's menu bar with one entry per command the configured apps
register (Loader, About, ...).
"""

import logging

import sgtk
from sgtk.platform import Engine

MENU_TITLE = "Flow Production Tracking"


class SubstancePainterEngine(Engine):
    def pre_app_init(self):
        # fails early, with a clear error, if we are not inside Painter
        import substance_painter  # noqa: F401

        self._menu = None

    @property
    def host_info(self):
        import substance_painter.application

        try:
            version = substance_painter.application.version()
        except Exception:
            version = "unknown"
        return {"name": "Substance 3D Painter", "version": version}

    @property
    def has_ui(self):
        return True

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
        import substance_painter.ui

        return substance_painter.ui.get_main_window()

    # ---- menu

    def _build_menu(self):
        import substance_painter.ui
        from PySide6 import QtWidgets

        self._remove_menu()

        menu = QtWidgets.QMenu(MENU_TITLE, substance_painter.ui.get_main_window())

        context_action = menu.addAction(str(self.context))
        context_action.setEnabled(False)
        menu.addSeparator()

        for name in sorted(self.commands):
            callback = self.commands[name]["callback"]
            action = menu.addAction(name)
            action.triggered.connect(
                lambda checked=False, cb=callback, n=name: self._run_command(n, cb)
            )

        substance_painter.ui.add_menu(menu)
        self._menu = menu

    def _remove_menu(self):
        if self._menu is None:
            return
        import substance_painter.ui

        try:
            substance_painter.ui.delete_ui_element(self._menu)
        except Exception:
            pass
        self._menu = None

    def _run_command(self, name, callback):
        try:
            callback()
        except Exception:
            self.logger.exception("Command '%s' failed" % name)

    # ---- logging

    def _emit_log_message(self, handler, record):
        import substance_painter.logging

        message = "[sgtk] %s" % handler.format(record)
        if record.levelno >= logging.ERROR:
            substance_painter.logging.error(message)
        elif record.levelno >= logging.WARNING:
            substance_painter.logging.warning(message)
        elif record.levelno >= logging.INFO:
            substance_painter.logging.info(message)
        else:
            substance_painter.logging.log(
                substance_painter.logging.DBG_INFO, "sgtk", message
            )

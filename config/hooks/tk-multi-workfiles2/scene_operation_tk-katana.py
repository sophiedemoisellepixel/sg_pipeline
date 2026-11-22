"""
Workfiles scene operations for Katana (our tk-katana engine).

Workfiles ships hooks for the engines Autodesk maintains; tk-katana is ours, so
this tells Workfiles how Katana opens, saves and resets a project. Configured
in env/includes/katana/apps.yml as

    hook_scene_operation: '{config}/tk-multi-workfiles2/scene_operation_tk-katana.py'

Work files are <step>/work/katana/<name>.v###.katana (core/templates.yml).
"""

import sgtk

HookClass = sgtk.get_hook_baseclass()


class SceneOperation(HookClass):
    def execute(self, operation, file_path, context, parent_action, file_version, read_only, **kwargs):
        """
        :param operation: current_path, open, save, save_as, reset or prepare_new
        :returns: the current project path for 'current_path', True/False for
            'reset' (False if the artist cancelled), otherwise None
        """
        from Katana import KatanaFile, NodegraphAPI

        if operation == "current_path":
            return NodegraphAPI.GetProjectFile() or ""

        if operation == "open":
            KatanaFile.Load(file_path)
            return None

        if operation == "save":
            current = NodegraphAPI.GetProjectFile()
            if not current:
                raise sgtk.TankError("This Katana project has never been saved; use File Save As.")
            KatanaFile.Save(current)
            return None

        if operation == "save_as":
            KatanaFile.Save(file_path)
            return None

        if operation == "reset":
            # before New or Open: give the artist a chance to keep their changes
            if KatanaFile.IsFileDirty() and not self._save_or_discard(KatanaFile, NodegraphAPI):
                return False
            KatanaFile.New()
            return True

        # prepare_new: nothing else to set up in an empty Katana project
        return None

    def _save_or_discard(self, KatanaFile, NodegraphAPI):
        """Ask Save / Don't Save / Cancel. False if cancelled."""
        from sgtk.platform.qt import QtGui

        answer = QtGui.QMessageBox.question(
            None, "Save your work?", "Your Katana project has unsaved changes. Save them first?",
            QtGui.QMessageBox.Save | QtGui.QMessageBox.Discard | QtGui.QMessageBox.Cancel,
        )
        if answer == QtGui.QMessageBox.Cancel:
            return False
        if answer == QtGui.QMessageBox.Save:
            current = NodegraphAPI.GetProjectFile()
            if not current:
                # an unsaved new project has nowhere to go; Workfiles' Save As handles that
                return False
            KatanaFile.Save(current)
        return True

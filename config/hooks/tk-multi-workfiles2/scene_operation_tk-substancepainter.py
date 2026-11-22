"""
Workfiles scene operations for Substance 3D Painter (our tk-substancepainter engine).

Tells Workfiles how Painter opens, saves and closes a project. Configured in
env/includes/substancepainter/apps.yml as

    hook_scene_operation: '{config}/tk-multi-workfiles2/scene_operation_tk-substancepainter.py'

Work files are <step>/work/substancepainter/<name>.v###.spp (core/templates.yml).

A Painter project needs a mesh to exist, so "New File" only closes the current
project: create the new one from a USD Geometry publish with the Loader's
"Create Painter Project", then File Save As puts it in the work area.
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
        import substance_painter.project as project

        if operation == "current_path":
            return (project.file_path() or "") if project.is_open() else ""

        if operation == "open":
            if project.is_open():
                project.close()
            project.open(file_path.replace("\\", "/"))
            return None

        if operation == "save":
            if not project.is_open():
                raise sgtk.TankError("No Painter project is open.")
            if not project.file_path():
                raise sgtk.TankError("This Painter project has never been saved; use File Save As.")
            project.save()
            return None

        if operation == "save_as":
            if not project.is_open():
                raise sgtk.TankError("No Painter project is open.")
            project.save_as(file_path.replace("\\", "/"))
            return None

        if operation == "reset":
            if project.is_open():
                if project.needs_saving() and not self._save_or_discard(project):
                    return False
                project.close()
            return True

        if operation == "prepare_new" and parent_action == "new_file":
            from sgtk.platform.qt import QtGui

            QtGui.QMessageBox.information(
                None, "New Painter project",
                "Painter projects start from a mesh: use Flow Production Tracking > Load..., "
                "right-click a USD Geometry publish > Create Painter Project, then File Save As.",
            )
        return None

    def _save_or_discard(self, project):
        """Ask Save / Don't Save / Cancel. False if cancelled."""
        from sgtk.platform.qt import QtGui

        answer = QtGui.QMessageBox.question(
            None, "Save your work?", "This Painter project has unsaved changes. Save them first?",
            QtGui.QMessageBox.Save | QtGui.QMessageBox.Discard | QtGui.QMessageBox.Cancel,
        )
        if answer == QtGui.QMessageBox.Cancel:
            return False
        if answer == QtGui.QMessageBox.Save:
            if not project.file_path():
                return False
            project.save()
        return True

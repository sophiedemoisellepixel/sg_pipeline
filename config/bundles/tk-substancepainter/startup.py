"""
Launch logic for Substance 3D Painter, used by tk-multi-launchapp (the desktop
app) when a Software entity with engine "tk-substancepainter" exists.

It points Painter at the startup plugin in ./painter, which starts the engine.
"""

import os
import sys

import sgtk
from sgtk.platform import LaunchInformation, SoftwareLauncher, SoftwareVersion

EXECUTABLES = {
    "win32": [
        r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe",
    ],
    "darwin": [
        "/Applications/Adobe Substance 3D Painter.app",
        "/Applications/Adobe Substance 3D Painter/Adobe Substance 3D Painter.app",
    ],
    "linux": [
        "/opt/Adobe/Adobe_Substance_3D_Painter/Adobe Substance 3D Painter",
    ],
}


class SubstancePainterLauncher(SoftwareLauncher):
    @property
    def minimum_supported_version(self):
        # first release with USD import in the Python API
        return "8.3"

    def scan_software(self):
        platform = "linux" if sys.platform.startswith("linux") else sys.platform
        icon = os.path.join(self.disk_location, "icon_256.png")

        found = []
        for path in EXECUTABLES.get(platform, []):
            if not os.path.exists(path):
                continue
            software = SoftwareVersion(
                _executable_version(path), "Substance 3D Painter", path, icon
            )
            supported, reason = self._is_supported(software)
            if supported:
                found.append(software)
            else:
                self.logger.debug("Skipping %s: %s" % (path, reason))
        return found

    def prepare_launch(self, exec_path, args, file_to_open=None):
        env = environment_for_painter(self.disk_location)
        env.update(self.get_standard_plugin_environment())
        env["SGTK_ENGINE"] = self.engine_name
        env["SGTK_CONTEXT"] = sgtk.context.serialize(self.context)
        if file_to_open:
            env["SGTK_FILE_TO_OPEN"] = file_to_open
        return LaunchInformation(exec_path, args, env)


def environment_for_painter(engine_location):
    """
    Environment variables Painter needs in order to load the startup plugin and
    for that plugin to find the Toolkit core.
    """
    plugins_paths = [os.path.join(engine_location, "painter")]
    existing = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_PATH")
    if existing:
        plugins_paths.append(existing)

    return {
        "SUBSTANCE_PAINTER_PLUGINS_PATH": os.pathsep.join(plugins_paths),
        # .../python/tank/__init__.py -> .../python
        "SGTK_CORE_PYTHON_PATH": os.path.dirname(os.path.dirname(sgtk.__file__)),
    }


def _executable_version(path):
    """The product version of the executable ("12.1.5"), or "0.0.0" if unknown."""
    if sys.platform != "win32":
        return "0.0.0"
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return "0.0.0"
        data = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(path, 0, size, data)
        value = ctypes.c_void_p()
        length = wintypes.UINT()
        ctypes.windll.version.VerQueryValueW(
            data, "\\", ctypes.byref(value), ctypes.byref(length)
        )
        # VS_FIXEDFILEINFO: signature, struct version, file version MS, file version LS
        info = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
        ms, ls = info[2], info[3]
        return "%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16)
    except Exception:
        return "0.0.0"

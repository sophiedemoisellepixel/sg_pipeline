"""
Launch logic for Mari, used by tk-multi-launchapp (the desktop app) when a
Software entity with engine "tk-mari" exists.

It adds ./mari_startup to MARI_SCRIPT_PATH; Mari runs the script in there at
startup and that starts the engine.
"""

import glob
import os
import re
import sys

import sgtk
from sgtk.platform import LaunchInformation, SoftwareLauncher, SoftwareVersion

# glob pattern and the regex that pulls the version ("7.1v2") out of a match
EXECUTABLES = {
    "win32": (
        r"C:\Program Files\Mari*\Bundle\bin\Mari*.exe",
        r"\\Mari(?P<version>\d[\w.]*)\\Bundle\\bin\\Mari(?P=version)\.exe$",
    ),
    "linux": (
        "/usr/local/Mari*/mari",
        r"/Mari(?P<version>\d[\w.]*)/mari$",
    ),
    "darwin": (
        "/Applications/Mari*/Mari*.app",
        r"/Mari(?P<version>\d[\w.]*)/Mari(?P=version)\.app$",
    ),
}


class MariLauncher(SoftwareLauncher):
    @property
    def minimum_supported_version(self):
        # first release with Python 3
        return "4.8"

    def scan_software(self):
        platform = "linux" if sys.platform.startswith("linux") else sys.platform
        if platform not in EXECUTABLES:
            return []
        pattern, version_regex = EXECUTABLES[platform]
        icon = os.path.join(self.disk_location, "icon_256.png")

        found = []
        for path in sorted(glob.glob(pattern)):
            match = re.search(version_regex, path)
            if not match:
                continue
            software = SoftwareVersion(match.group("version"), "Mari", path, icon)
            supported, reason = self._is_supported(software)
            if supported:
                found.append(software)
            else:
                self.logger.debug("Skipping %s: %s" % (path, reason))
        return found

    def prepare_launch(self, exec_path, args, file_to_open=None):
        env = environment_for_mari(self.disk_location)
        env.update(self.get_standard_plugin_environment())
        env["SGTK_ENGINE"] = self.engine_name
        env["SGTK_CONTEXT"] = sgtk.context.serialize(self.context)
        if file_to_open:
            env["SGTK_FILE_TO_OPEN"] = file_to_open
        return LaunchInformation(exec_path, args, env)


def environment_for_mari(engine_location):
    """
    Environment variables Mari needs in order to run the startup script and
    for that script to find the Toolkit core.
    """
    script_paths = [os.path.join(engine_location, "mari_startup")]
    existing = os.environ.get("MARI_SCRIPT_PATH")
    if existing:
        script_paths.append(existing)

    return {
        "MARI_SCRIPT_PATH": os.pathsep.join(script_paths),
        # .../python/tank/__init__.py -> .../python
        "SGTK_CORE_PYTHON_PATH": os.path.dirname(os.path.dirname(sgtk.__file__)),
    }

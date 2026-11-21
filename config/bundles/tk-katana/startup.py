"""
Launch logic for Katana, used by tk-multi-launchapp (the desktop app) when a
Software entity with engine "tk-katana" exists.

It puts ./katana_resources in front of KATANA_RESOURCES; Katana runs
Startup/init.py in there at startup and that starts the engine. Existing
entries (renderer plug-ins such as 3Delight) are kept.

Katana is always launched with the Arnold plug-in (KtoA): the launcher sets the
same environment as KtoA's own launchKtoA.bat. The KtoA folder is
SG_PIPELINE_KTOA_ROOT if set, else the newest ~/ktoa/ktoa-*-kat<major.minor>-*
build that matches the Katana being launched.
"""

import glob
import os
import re
import sys

import sgtk
from sgtk.platform import LaunchInformation, SoftwareLauncher, SoftwareVersion

# glob pattern and the regex that pulls the version ("9.0v4") out of a match
EXECUTABLES = {
    "win32": (
        r"C:\Program Files\Katana*\bin\katanaBin.exe",
        r"\\Katana(?P<version>\d[\w.]*)\\bin\\katanaBin\.exe$",
    ),
    "linux": (
        "/opt/Foundry/Katana*/katana",
        r"/Katana(?P<version>\d[\w.]*)/katana$",
    ),
}


class KatanaLauncher(SoftwareLauncher):
    @property
    def minimum_supported_version(self):
        # first release with Python 3
        return "5.0"

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
            software = SoftwareVersion(match.group("version"), "Katana", path, icon)
            supported, reason = self._is_supported(software)
            if supported:
                found.append(software)
            else:
                self.logger.debug("Skipping %s: %s" % (path, reason))
        return found

    def prepare_launch(self, exec_path, args, file_to_open=None):
        env = environment_for_katana(self.disk_location, exec_path)
        if "DEFAULT_RENDERER" not in env:
            self.logger.warning("No Arnold plug-in (KtoA) found for %s; launching without it." % exec_path)
        env.update(self.get_standard_plugin_environment())
        env["SGTK_ENGINE"] = self.engine_name
        env["SGTK_CONTEXT"] = sgtk.context.serialize(self.context)
        if file_to_open:
            env["SGTK_FILE_TO_OPEN"] = file_to_open
        return LaunchInformation(exec_path, args, env)


def ktoa_root_for(exec_path):
    """
    The KtoA install to load with this Katana executable, or None.

    KtoA builds are tied to a Katana release line: Katana 9.0v4 needs a
    "kat9.0" build.
    """
    override = os.environ.get("SG_PIPELINE_KTOA_ROOT")
    if override:
        return override if os.path.isdir(os.path.join(override, "bin")) else None

    match = re.search(r"Katana(\d+\.\d+)v\d+", exec_path)
    if not match:
        return None
    pattern = os.path.join(os.path.expanduser("~"), "ktoa", "ktoa-*-kat%s-*" % match.group(1))

    def version_key(path):
        return [int(n) for n in re.findall(r"\d+", os.path.basename(path).split("-kat")[0])]

    builds = [p for p in glob.glob(pattern) if os.path.isdir(os.path.join(p, "bin"))]
    return max(builds, key=version_key) if builds else None


def environment_for_katana(engine_location, exec_path=None):
    """
    Environment variables Katana needs in order to load Arnold, run the
    startup script and for that script to find the Toolkit core.
    """

    def prepend(name, paths):
        existing = os.environ.get(name)
        return os.pathsep.join(paths + ([existing] if existing else []))

    env = {
        # .../python/tank/__init__.py -> .../python
        "SGTK_CORE_PYTHON_PATH": os.path.dirname(os.path.dirname(sgtk.__file__)),
    }
    resources = [os.path.join(engine_location, "katana_resources")]

    ktoa = ktoa_root_for(exec_path) if exec_path else None
    if ktoa:
        # same settings as KtoA's own launchKtoA.bat
        katana_root = os.path.dirname(os.path.dirname(exec_path))
        usd = os.path.join(katana_root, "plugins", "Resources", "Usd")
        resources += [ktoa, os.path.join(usd, "plugin"), os.path.join(ktoa, "USD", "KatanaUsdArnold")]
        env["DEFAULT_RENDERER"] = "arnold"
        env["USD_KATANA_ALLOW_CUSTOM_MATERIAL_SCOPES"] = "true"
        env["PATH"] = prepend(
            "PATH",
            [os.path.join(ktoa, "bin"), os.path.join(usd, "lib"), os.path.join(usd, "plugin", "Libs")],
        )
        env["FNPXR_PLUGINPATH"] = prepend("FNPXR_PLUGINPATH", [os.path.join(ktoa, "USD", "Viewport")])
        env["PYTHONPATH"] = prepend("PYTHONPATH", [os.path.join(usd, "lib", "python")])

    env["KATANA_RESOURCES"] = prepend("KATANA_RESOURCES", resources)
    return env
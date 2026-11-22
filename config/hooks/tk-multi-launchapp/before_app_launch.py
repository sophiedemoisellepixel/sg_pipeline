"""
sg_pipeline: runs just before the desktop app starts any application.

Sets OCIO to the project's colour config, config/color/sg_pipeline.ocio, so
Maya, Substance Painter, Mari, Katana, Nuke and Arnold all show and convert
colour the same way. The config belongs to the pipeline configuration, so each
project can have its own; a studio-wide OCIO set before the desktop app starts
is replaced for applications launched from this project, and the log says so.

Configured on every tk-multi-launchapp instance as

    hook_before_app_launch: "{config}/tk-multi-launchapp/before_app_launch.py"
"""

import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

COLOR_CONFIG = os.path.join("color", "sg_pipeline.ocio")


def color_config_for(config_location):
    """The OCIO config path inside a pipeline configuration folder."""
    return os.path.normpath(os.path.join(config_location, COLOR_CONFIG))


class BeforeAppLaunch(HookBaseClass):
    def execute(self, app_path, app_args, version, engine_name, software_entity=None, **kwargs):
        config = color_config_for(self.sgtk.pipeline_configuration.get_config_location())
        if not os.path.isfile(config):
            self.logger.warning("No colour config at %s; %s keeps its own colour settings." % (config, engine_name))
            return
        previous = os.environ.get("OCIO")
        if previous and os.path.normcase(previous) != os.path.normcase(config):
            self.logger.info("OCIO was %s; using the project's config instead." % previous)
        os.environ["OCIO"] = config
        self.logger.debug("OCIO=%s for %s" % (config, engine_name))

        if engine_name in ("tk-nuke", "tk-nukestudio"):
            # Nuke needs a startup file to switch new scripts to OCIO; the
            # engine's own NUKE_PATH entries are already set and kept
            nuke_startup = os.path.join(os.path.dirname(config), "nuke")
            current = os.environ.get("NUKE_PATH")
            os.environ["NUKE_PATH"] = os.pathsep.join([nuke_startup] + ([current] if current else []))

"""
ShotGrid (Flow Production Tracking) nodes for Griptape Nodes.

    ShotGridLoadPublish    Nuke -> Griptape (and anything else that publishes
                           images): finds a publish and outputs its image.
    ShotGridPublishImage   Griptape -> everything: saves an image and registers
                           it as a publish, which the Maya, Nuke and Mari
                           loaders can then load.

Part of the "ShotGrid Pipeline" Griptape library (griptape/griptape-nodes-library.json),
which Griptape loads from this folder; griptape/install.ps1 registers it. The nodes
talk to ShotGrid through griptape/sg_bridge.py, run with the desktop app's
Python, so the sign-in saved by the desktop app is used and Griptape never
sees any credentials.
"""

import io
import json
import os
import re
import subprocess
from typing import Any

from griptape.artifacts import ImageUrlArtifact
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ControlNode, DataNode
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes
from griptape_nodes.traits.options import Options

# the repo this file belongs to (this file is <repo>/griptape/sg_pipeline_nodes.py);
# the SG_PIPELINE_REPO environment variable overrides it
SG_PIPELINE_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP_PYTHON = r"C:\Program Files\Shotgun\Python3\python.exe"

DEFAULT_PROJECT_ID = 91
# Nuke's stock publisher registers PNG/JPEG/TIFF frames as "Image" and EXR/DPX as "Rendered Image"
LOAD_TYPES = ["Image", "Rendered Image", "Texture"]
PUBLISH_TYPES = ["Texture", "Image", "Rendered Image"]
UDIM_TOKEN = "<UDIM>"


def call_bridge(command: str, request: dict) -> dict:
    """Run griptape/sg_bridge.py with the desktop app's Python and return its answer."""
    repo = os.environ.get("SG_PIPELINE_REPO") or SG_PIPELINE_REPO
    bridge = os.path.join(repo, "griptape", "sg_bridge.py")
    python = os.environ.get("SG_PIPELINE_DESKTOP_PYTHON") or DESKTOP_PYTHON
    for required in (bridge, python):
        if not os.path.exists(required):
            raise RuntimeError("Not found: %s" % required)

    completed = subprocess.run(
        [python, bridge, command],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1])
    except Exception:
        raise RuntimeError(
            "The ShotGrid bridge gave no answer.\n%s" % (completed.stderr or completed.stdout)[-600:]
        ) from None
    if not answer.get("ok"):
        raise RuntimeError("ShotGrid: %s" % answer.get("error"))
    return answer


def image_bytes_from(value: Any) -> bytes:
    """The bytes of whatever arrives on an image input: artifact, dict, url or path."""
    if value is None:
        raise ValueError("No image connected.")
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        if os.path.exists(value):
            with open(value, "rb") as handle:
                return handle.read()
        import requests

        response = requests.get(value, timeout=120)
        response.raise_for_status()
        return response.content
    if hasattr(value, "to_bytes"):
        return value.to_bytes()
    raise ValueError("Cannot read an image from %s" % type(value).__name__)


def as_png(data: bytes) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


class ShotGridLoadPublish(DataNode):
    """Finds a ShotGrid publish and outputs its image."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        self.category = "ShotGrid"
        self.description = "Loads the image of a ShotGrid publish (Nuke or Katana renders, textures)."

        self.add_parameter(
            Parameter(name="project_id", type="int", default_value=DEFAULT_PROJECT_ID,
                      tooltip="Id of the ShotGrid project.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="publish_type", type="str", default_value=LOAD_TYPES[0],
                      tooltip="Type of publish to look for.", traits={Options(choices=LOAD_TYPES)},
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="name_contains", type="str", default_value="",
                      tooltip="Only publishes whose name contains this text. Empty: any.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="publish_id", type="int", default_value=0,
                      tooltip="Load exactly this publish. 0: the newest one that matches.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="frame_index", type="int", default_value=0,
                      tooltip="Which file of a sequence or UDIM set to load, counted from 0.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="image", type="ImageUrlArtifact", output_type="ImageUrlArtifact",
                      tooltip="The image of the publish.", ui_options={"expander": True},
                      allowed_modes={ParameterMode.OUTPUT})
        )
        self.add_parameter(
            Parameter(name="file_path", type="str", output_type="str",
                      tooltip="The file on disk that was loaded.", allowed_modes={ParameterMode.OUTPUT})
        )
        self.add_parameter(
            Parameter(name="loaded_publish_id", type="int", output_type="int",
                      tooltip="Id of the publish that was loaded. Connect it to 'upstream_publish_id' "
                              "of Publish Image to ShotGrid to record what an image was made from.",
                      allowed_modes={ParameterMode.OUTPUT})
        )
        self.add_parameter(
            Parameter(name="info", type="str", output_type="str",
                      tooltip="What was loaded.", ui_options={"multiline": True},
                      allowed_modes={ParameterMode.OUTPUT})
        )

    def process(self) -> None:
        answer = call_bridge(
            "find",
            {
                "project_id": self.get_parameter_value("project_id") or DEFAULT_PROJECT_ID,
                "publish_type": self.get_parameter_value("publish_type"),
                "name_contains": self.get_parameter_value("name_contains"),
                "publish_id": self.get_parameter_value("publish_id") or 0,
            },
        )
        if not answer["publishes"]:
            raise RuntimeError("No matching publish found in ShotGrid.")
        publish = answer["publishes"][0]
        files = publish["files"]
        if not files:
            raise RuntimeError("Publish %s has no file on this computer: %s" % (publish["id"], publish["path"]))
        index = max(0, min(int(self.get_parameter_value("frame_index") or 0), len(files) - 1))
        file_path = files[index]

        try:
            with open(file_path, "rb") as handle:
                png = as_png(handle.read())
        except Exception as error:
            raise RuntimeError(
                "Griptape cannot read %s (%s). Publish PNG, JPEG or TIFF for Griptape; EXR is not supported."
                % (os.path.basename(file_path), error)
            ) from None

        static_name = "sg_publish_%s_%s.png" % (publish["id"], safe(os.path.splitext(os.path.basename(file_path))[0]))
        url = GriptapeNodes.StaticFilesManager().save_static_file(png, static_name)

        self.parameter_output_values["image"] = ImageUrlArtifact(value=url)
        self.parameter_output_values["file_path"] = file_path
        self.parameter_output_values["loaded_publish_id"] = publish["id"]
        self.parameter_output_values["info"] = "%s v%03d (%s, id %s)\n%s\nfile %d of %d" % (
            publish["name"], publish["version_number"] or 0, publish["type"], publish["id"],
            file_path, index + 1, len(files),
        )


class ShotGridPublishImage(ControlNode):
    """Saves an image to disk and registers it in ShotGrid as a publish."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        self.category = "ShotGrid"
        self.description = "Saves an image and publishes it to ShotGrid for Maya, Nuke and Mari to load."

        self.add_parameter(
            Parameter(name="image", input_types=["ImageUrlArtifact", "ImageArtifact", "str"],
                      type="ImageUrlArtifact", tooltip="The image to publish.",
                      allowed_modes={ParameterMode.INPUT})
        )
        self.add_parameter(
            Parameter(name="name", type="str", default_value="",
                      tooltip="Name of the publish. For textures use <asset>_<map>, e.g. testAsset_basecolor: "
                              "the Maya and Mari loaders read the map from the text after the last underscore.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="publish_type", type="str", default_value=PUBLISH_TYPES[0],
                      tooltip="Texture: loads as a layer in Mari and a material or file node in Maya. "
                              "Image or Rendered Image: loads as a Read node in Nuke.",
                      traits={Options(choices=PUBLISH_TYPES)},
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="project_id", type="int", default_value=DEFAULT_PROJECT_ID,
                      tooltip="Id of the ShotGrid project.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="entity_type", type="str", default_value="Asset",
                      tooltip="What the publish belongs to.", traits={Options(choices=["Asset", "Shot", "Project"])},
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="entity_id", type="int", default_value=0,
                      tooltip="Id of the Asset or Shot. 0: publish to the project itself.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="task_id", type="int", default_value=0, tooltip="Id of the Task, or 0 for none.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="upstream_publish_id", type="int", default_value=0,
                      tooltip="Id of the publish this image was made from, or 0 for none.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="description", type="str", default_value="Published from Griptape Nodes",
                      tooltip="Comment stored on the publish.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="publish_root", type="str", default_value="",
                      tooltip="Folder the image is saved under. Empty: the SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT "
                              "environment variable, else Documents/GriptapeNodes/sg_pipeline_publish.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="dry_run", type="bool", default_value=False,
                      tooltip="Save the file but do not register anything in ShotGrid.",
                      allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY})
        )
        self.add_parameter(
            Parameter(name="published_path", type="str", output_type="str",
                      tooltip="The path that was published.", allowed_modes={ParameterMode.OUTPUT})
        )
        self.add_parameter(
            Parameter(name="new_publish_id", type="int", output_type="int",
                      tooltip="Id of the new publish (0 for a dry run).", allowed_modes={ParameterMode.OUTPUT})
        )
        self.add_parameter(
            Parameter(name="info", type="str", output_type="str", tooltip="What was published.",
                      ui_options={"multiline": True}, allowed_modes={ParameterMode.OUTPUT})
        )

    def validate_before_node_run(self) -> list[Exception] | None:
        errors = []
        if not (self.get_parameter_value("name") or "").strip():
            errors.append(ValueError("%s: give the publish a name." % self.name))
        return errors or None

    def process(self) -> None:
        name = safe(self.get_parameter_value("name").strip())
        publish_type = self.get_parameter_value("publish_type") or PUBLISH_TYPES[0]
        project_id = int(self.get_parameter_value("project_id") or DEFAULT_PROJECT_ID)
        entity_id = int(self.get_parameter_value("entity_id") or 0)
        entity = (
            {"type": self.get_parameter_value("entity_type"), "id": entity_id}
            if entity_id and self.get_parameter_value("entity_type") != "Project"
            else {"type": "Project", "id": project_id}
        )
        dry_run = bool(self.get_parameter_value("dry_run"))
        png = as_png(image_bytes_from(self.get_parameter_value("image")))

        request = {
            "project_id": project_id,
            "name": name,
            "publish_type": publish_type,
            "entity": entity,
            "task_id": int(self.get_parameter_value("task_id") or 0),
            "description": self.get_parameter_value("description") or "",
            "upstream_ids": [int(self.get_parameter_value("upstream_publish_id") or 0)],
        }

        # the version decides the folder, so ask ShotGrid first; with a task, the
        # bridge also gives the studio path (<step>/publish/textures or /griptape)
        kind = "texture" if publish_type == "Texture" else "image"
        located = call_bridge("locate", dict(request, kind=kind))
        version = located["version_number"]
        publish_path = located.get("path")
        if not publish_path:
            root = (
                self.get_parameter_value("publish_root")
                or os.environ.get("SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT")
                or os.path.join(os.path.expanduser("~"), "Documents", "GriptapeNodes", "sg_pipeline_publish")
            )
            folder = os.path.join(root, "%s_%s" % (entity["type"], entity["id"]), name, "v%03d" % version)
            if kind == "texture":
                publish_path = os.path.join(folder, "%s.%s.png" % (name, UDIM_TOKEN))
            else:
                publish_path = os.path.join(folder, "%s_v%03d.png" % (name, version))
        # textures are published the way Painter and Mari publish them: one file per UDIM tile
        file_path = publish_path.replace(UDIM_TOKEN, "1001")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as handle:
            handle.write(png)

        answer = call_bridge("publish", dict(request, path=publish_path, version_number=version, dry_run=dry_run))
        publish = answer["publish"]
        self.parameter_output_values["published_path"] = publish_path
        self.parameter_output_values["new_publish_id"] = 0 if dry_run else publish["id"]
        self.parameter_output_values["info"] = "%s%s v%03d (%s)\n%s\n%s" % (
            "DRY RUN, nothing registered: " if dry_run else "Published id %s: " % publish.get("id"),
            name, version, publish_type, publish_path,
            "studio folder of the task" if located.get("path") else "Griptape folder (%s)" % located.get("reason"),
        )

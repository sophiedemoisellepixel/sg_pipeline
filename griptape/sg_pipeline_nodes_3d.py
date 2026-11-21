"""
ShotGrid node for AI-generated 3D models in Griptape Nodes.

    ShotGridPublish3D   AI 3D -> everything: converts a generated model
                        (Rodin, Tripo, Load 3D: GLB, glTF, USDZ, FBX, OBJ) to
                        USD with griptape/mesh_to_usd.py and publishes it as
                        "USD Geometry", which Maya, Painter, Mari, Katana and
                        Nuke already load.

Part of the "ShotGrid Pipeline" Griptape library (griptape/griptape-nodes-library.json),
next to sg_pipeline_nodes.py, whose ShotGrid bridge it uses.
"""

import os
import shutil
import sys
from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ControlNode
from griptape_nodes.traits.options import Options

# the repo this file belongs to (this file is <repo>/griptape/sg_pipeline_nodes_3d.py);
# the SG_PIPELINE_REPO environment variable overrides it
SG_PIPELINE_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT_ID = 91


def _repo() -> str:
    return os.environ.get("SG_PIPELINE_REPO") or SG_PIPELINE_REPO


def _helpers():
    """sg_pipeline_nodes (bridge, file helpers) and mesh_to_usd, from the repo."""
    import importlib.util

    folder = os.path.join(_repo(), "griptape")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import mesh_to_usd

    spec = importlib.util.spec_from_file_location("_sg_pipeline_nodes_shared", os.path.join(folder, "sg_pipeline_nodes.py"))
    nodes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nodes)
    nodes.SG_PIPELINE_REPO = _repo()
    return nodes, mesh_to_usd


def model_file_from(value: Any, folder: str, nodes) -> str:
    """Save whatever arrives on a 3D input (artifact, url or path) into `folder`; its path."""
    from urllib.parse import unquote, urlparse

    meta = {}
    if isinstance(value, dict):
        meta = value.get("meta") or {}
        value = value.get("value")
    elif hasattr(value, "value"):
        meta = getattr(value, "meta", None) or {}
        value = value.value
    if value is None:
        raise ValueError("No 3D model connected.")

    os.makedirs(folder, exist_ok=True)
    if isinstance(value, bytes):
        extension = "." + str(meta.get("format") or meta.get("extension") or "glb").lstrip(".")
        target = os.path.join(folder, "model" + extension)
        with open(target, "wb") as handle:
            handle.write(value)
        return target
    if isinstance(value, str) and os.path.exists(value):
        target = os.path.join(folder, nodes.safe(os.path.basename(value)))
        shutil.copyfile(value, target)
        return target
    if isinstance(value, str):
        file_name = os.path.basename(unquote(urlparse(value).path)) or "model.glb"
        target = os.path.join(folder, nodes.safe(file_name))
        with open(target, "wb") as handle:
            handle.write(nodes.image_bytes_from(value))
        return target
    raise ValueError("Cannot read a 3D model from %s" % type(value).__name__)


class ShotGridPublish3D(ControlNode):
    """Turns a generated 3D model into USD and publishes it as USD Geometry."""

    def __init__(self, name: str, metadata: dict[Any, Any] | None = None) -> None:
        super().__init__(name, metadata)
        self.category = "ShotGrid"
        self.description = (
            "Converts a 3D model (Rodin, Tripo, Load 3D: GLB, glTF, USDZ, FBX, OBJ) to USD and "
            "publishes it as USD Geometry, which Maya, Painter, Mari, Katana and Nuke load."
        )

        def add(name, kind, default, tooltip, **extra):
            self.add_parameter(
                Parameter(name=name, type=kind, default_value=default, tooltip=tooltip,
                          allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY}, **extra)
            )

        self.add_parameter(
            Parameter(name="model", input_types=["ThreeDUrlArtifact", "ThreeDArtifact", "str"],
                      type="ThreeDUrlArtifact",
                      tooltip="The 3D model to publish, e.g. the 3D Model output of Rodin or Tripo, or a file path.",
                      allowed_modes={ParameterMode.INPUT})
        )
        add("name", "str", "", "Name of the publish, e.g. lantern_model.")
        add("project_id", "int", DEFAULT_PROJECT_ID, "Id of the ShotGrid project.")
        add("entity_type", "str", "Asset", "What the publish belongs to.",
            traits={Options(choices=["Asset", "Shot", "Project"])})
        add("entity_id", "int", 0, "Id of the Asset or Shot. 0: publish to the project itself.")
        add("task_id", "int", 0, "Id of the Task, or 0 for none.")
        add("upstream_publish_id", "int", 0, "Id of the publish the model was made from (e.g. a concept image), or 0.")
        add("scale", "float", 1.0,
            "Extra scale. GLB and glTF are read as metres (1 unit = 100 cm); FBX and OBJ keep their own units.")
        add("description", "str", "Generated in Griptape Nodes",
            "Comment stored on the publish. Say which model and prompt made it.")
        add("publish_root", "str", "",
            "Folder the USD is written under. Empty: the SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT environment "
            "variable, else Documents/GriptapeNodes/sg_pipeline_publish.")
        add("dry_run", "bool", False, "Convert and save the USD but do not register anything in ShotGrid.")

        for name, kind, tooltip in (
            ("published_path", "str", "The USD file that was published."),
            ("new_publish_id", "int", "Id of the new publish (0 for a dry run)."),
            ("info", "str", "What was converted and published."),
        ):
            self.add_parameter(
                Parameter(name=name, type=kind, output_type=kind, tooltip=tooltip,
                          ui_options={"multiline": True} if name == "info" else {},
                          allowed_modes={ParameterMode.OUTPUT})
            )

    def validate_before_node_run(self) -> list[Exception] | None:
        errors = []
        if not (self.get_parameter_value("name") or "").strip():
            errors.append(ValueError("%s: give the publish a name." % self.name))
        if self.get_parameter_value("model") is None:
            errors.append(ValueError("%s: connect a 3D model." % self.name))
        return errors or None

    def process(self) -> None:
        nodes, mesh_to_usd = _helpers()

        name = nodes.safe(self.get_parameter_value("name").strip())
        project_id = int(self.get_parameter_value("project_id") or DEFAULT_PROJECT_ID)
        entity_id = int(self.get_parameter_value("entity_id") or 0)
        entity = (
            {"type": self.get_parameter_value("entity_type"), "id": entity_id}
            if entity_id and self.get_parameter_value("entity_type") != "Project"
            else {"type": "Project", "id": project_id}
        )
        dry_run = bool(self.get_parameter_value("dry_run"))
        request = {
            "project_id": project_id,
            "name": name,
            "publish_type": "USD Geometry",
            "entity": entity,
            "task_id": int(self.get_parameter_value("task_id") or 0),
            "description": self.get_parameter_value("description") or "",
            "upstream_ids": [int(self.get_parameter_value("upstream_publish_id") or 0)],
        }

        root = (
            self.get_parameter_value("publish_root")
            or os.environ.get("SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT")
            or os.path.join(os.path.expanduser("~"), "Documents", "GriptapeNodes", "sg_pipeline_publish")
        )
        version = nodes.call_bridge("next_version", request)["version_number"]
        folder = os.path.join(root, "%s_%s" % (entity["type"], entity["id"]), name, "v%03d" % version)
        # the generated file is kept next to the USD, so it can be converted again
        source = model_file_from(self.get_parameter_value("model"), os.path.join(folder, "source"), nodes)
        usd_path = os.path.join(folder, "%s_v%03d.usd" % (name, version))
        converted = mesh_to_usd.convert(source, usd_path, float(self.get_parameter_value("scale") or 1.0))

        publish = nodes.call_bridge(
            "publish", dict(request, path=usd_path, version_number=version, dry_run=dry_run)
        )["publish"]

        details = []
        if converted.get("meshes") is not None:
            size = " x ".join(str(v) for v in converted.get("size_cm") or []) or "?"
            details.append("%s mesh(es), %s faces, %s material(s), size %s cm" % (
                converted["meshes"], converted.get("faces"), converted.get("materials", "?"), size))
        if converted.get("has_uvs") is False:
            details.append("WARNING: no UVs. Painter can unwrap it; Mari and textures in Maya need UVs.")
        details += converted.get("warnings") or []

        self.parameter_output_values["published_path"] = usd_path
        self.parameter_output_values["new_publish_id"] = 0 if dry_run else publish["id"]
        self.parameter_output_values["info"] = "%s%s v%03d (USD Geometry, from %s)\n%s\n%s" % (
            "DRY RUN, nothing registered: " if dry_run else "Published id %s: " % publish.get("id"),
            name, version, converted["source_format"].upper(), usd_path, "\n".join(details),
        )

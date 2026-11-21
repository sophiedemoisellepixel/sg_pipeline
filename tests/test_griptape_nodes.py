"""
Checks the ShotGrid nodes for Griptape Nodes outside the Griptape app, with
the Python of Griptape's engine:

    "%LOCALAPPDATA%\\ai.griptape.nodes.desktop\\current\\resources\\engine-bundle\\python\\python.exe" tests\\test_griptape_nodes.py

It loads a real Texture publish through the load node, and runs the publish
node as a dry run: the image is saved but nothing is registered. With
--publish the publish node really registers one "Texture" publish (WRITES to
ShotGrid). Griptape's static file server is not running here, so saving the
preview image is replaced by a stand-in.
"""

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["SG_PIPELINE_REPO"] = REPO
os.environ["SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT"] = os.path.join(
    os.path.dirname(REPO), "sg_pipeline_work", "griptape_publish"
)
PUBLISH = "--publish" in sys.argv
ASSET_ID = 1412  # testAsset


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        raise SystemExit(1)


spec = importlib.util.spec_from_file_location(
    "sg_pipeline_nodes", os.path.join(REPO, "griptape", "sg_pipeline_nodes.py")
)
nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nodes)

# stand-in for Griptape's static file server
saved = {}


class _Static:
    def save_static_file(self, data, file_name, *args, **kwargs):
        path = os.path.join(tempfile.gettempdir(), file_name)
        with open(path, "wb") as handle:
            handle.write(data)
        saved[file_name] = path
        return "file:///" + path.replace("\\", "/")


nodes.GriptapeNodes.StaticFilesManager = staticmethod(lambda: _Static())


def run(node, values):
    for name, value in values.items():
        node.set_parameter_value(name, value)
    errors = node.validate_before_node_run()
    check("%s validates %s" % (type(node).__name__, errors or ""), not errors)
    node.process()
    return node.parameter_output_values


# ---- load: a texture Mari published
load = nodes.ShotGridLoadPublish("load")
check("load node has its parameters",
      {"project_id", "publish_type", "name_contains", "publish_id", "frame_index", "image", "file_path"}
      <= {p.name for p in load.parameters})
out = run(load, {"publish_type": "Texture", "name_contains": "basecolor"})
print("     ", out["info"].replace("\n", " | "))
check("a publish was loaded (id %s)" % out["loaded_publish_id"], out["loaded_publish_id"] > 0)
check("it points at a file on disk", os.path.exists(out["file_path"]))
check("an image artifact comes out", type(out["image"]).__name__ == "ImageUrlArtifact" and len(saved) == 1)

from PIL import Image

preview = Image.open(next(iter(saved.values())))
red, green, blue = preview.convert("RGB").getpixel((preview.width // 2, preview.height // 2))
check("the image is the red base colour (%d %d %d)" % (red, green, blue), red > 128 > green and red > 128 > blue)

# ---- Nuke -> Griptape: the PNG comp Nuke published, if there is one on the site
#      (Nuke's stock publisher registers PNG frames as type "Image")
comp = nodes.call_bridge(
    "find", {"project_id": 91, "publish_type": "Image", "name_contains": "katana_test_comp"}
)["publishes"]
if comp:
    saved.clear()
    load_comp = nodes.ShotGridLoadPublish("load_comp")
    out = run(load_comp, {"publish_type": "Image", "name_contains": "katana_test_comp", "frame_index": 1})
    print("     ", out["info"].replace("\n", " | "))
    check("the Nuke comp publish was loaded (id %s)" % out["loaded_publish_id"],
          out["loaded_publish_id"] == comp[0]["id"])
    check("frame 2 of 2 was picked", out["file_path"].endswith("katana_test_comp.0002.png"))
    comp_image = Image.open(next(iter(saved.values())))
    check("the image has the render resolution (%dx%d)" % comp_image.size, comp_image.size == (512, 512))
else:
    print("SKIP  no Nuke comp publish on the site: run tests\\test_nuke_usd.py with SG_PIPELINE_SELFTEST_PUBLISH=1")
# ---- publish: the loaded image back out as a new texture
publish = nodes.ShotGridPublishImage("publish")
out = run(
    publish,
    {
        "image": out["file_path"],
        "name": "griptapeTest_basecolor",
        "publish_type": "Texture",
        "entity_type": "Asset",
        "entity_id": ASSET_ID,
        "upstream_publish_id": out["loaded_publish_id"],
        "description": "sg_pipeline Griptape self-test",
        "dry_run": not PUBLISH,
    },
)
print("     ", out["info"].replace("\n", " | "))
check("the publish path uses the UDIM token", out["published_path"].endswith("griptapeTest_basecolor.<UDIM>.png"))
tile = out["published_path"].replace("<UDIM>", "1001")
check("the image was saved as tile 1001", os.path.exists(tile))
check("the saved tile is a readable PNG", Image.open(tile).format == "PNG")
if PUBLISH:
    check("a publish was registered (id %s)" % out["new_publish_id"], out["new_publish_id"] > 0)
    found = nodes.call_bridge("find", {"project_id": 91, "publish_id": out["new_publish_id"]})["publishes"][0]
    check("it reads back as a Texture named griptapeTest_basecolor",
          found["type"] == "Texture" and found["name"] == "griptapeTest_basecolor" and found["files"] == [tile])
else:
    check("dry run: nothing was registered", out["new_publish_id"] == 0 and out["info"].startswith("DRY RUN"))

empty = nodes.ShotGridPublishImage("empty")
check("a publish without a name is refused", bool(empty.validate_before_node_run()))
print("\nALL CHECKS PASSED")

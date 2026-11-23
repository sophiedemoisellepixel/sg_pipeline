"""
Tests the Workfiles scene-operation hooks we wrote for our own engines
(config/hooks/tk-multi-workfiles2/scene_operation_tk-*.py), outside Toolkit.

    Katana (real Katana, script mode, no window):
        "C:\\Program Files\\Katana9.0v4\\bin\\katanaBin.exe" --script tests\\test_workfiles_hooks.py
    Painter (a stand-in for substance_painter.project; Painter has no script mode):
        "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\test_workfiles_hooks.py

Neither touches ShotGrid. Files are written under %TEMP%\\sg_pipeline_workfiles_test.
"""

import os
import sys
import tempfile
import types

# Katana's --script runs the file without __file__; run the tests from the repo folder
REPO = os.environ.get("SG_PIPELINE_REPO") or (
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
)
HOOKS = os.path.join(REPO, "config", "hooks", "tk-multi-workfiles2")
OUT = os.path.join(tempfile.gettempdir(), "sg_pipeline_workfiles_test")
os.makedirs(OUT, exist_ok=True)
failures = []


def check(label, condition, detail=""):
    print("%s  %s%s" % ("PASS" if condition else "FAIL", label, ("  (%s)" % detail) if detail else ""))
    if not condition:
        failures.append(label)


def load_hook(file_name):
    """The hook's SceneOperation class, with a small stand-in for sgtk."""
    stub = types.ModuleType("sgtk")

    class TankError(Exception):
        pass

    class Hook(object):
        logger = None
        parent = None

    stub.TankError = TankError
    stub.get_hook_baseclass = lambda: Hook
    sys.modules["sgtk"] = stub
    namespace = {"__name__": "hook"}
    path = os.path.join(HOOKS, file_name)
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"), namespace)
    return namespace["SceneOperation"](), TankError


def run(hook, operation, file_path=None, parent_action=None):
    return hook.execute(operation, file_path, None, parent_action, None, False)


def test_katana():
    from Katana import KatanaFile, NodegraphAPI

    hook, _ = load_hook("scene_operation_tk-katana.py")
    path = os.path.join(OUT, "lookdev.v001.katana")
    if os.path.exists(path):
        os.remove(path)
    check("Katana: reset on a clean project starts a new one", run(hook, "reset") is True)
    NodegraphAPI.CreateNode("Group", NodegraphAPI.GetRootNode()).setName("sgPipelineTest")
    run(hook, "save_as", path)
    check("Katana: save_as writes the work file", os.path.isfile(path), path)
    check("Katana: current_path is the saved file", os.path.normcase(run(hook, "current_path")) == os.path.normcase(path))
    before = os.path.getmtime(path)
    NodegraphAPI.CreateNode("Group", NodegraphAPI.GetRootNode())
    run(hook, "save")
    check("Katana: save writes over the current file", os.path.getmtime(path) >= before and not KatanaFile.IsFileDirty())
    KatanaFile.New()
    run(hook, "open", path)
    check("Katana: open loads the work file", os.path.normcase(run(hook, "current_path")) == os.path.normcase(path))
    check("Katana: the saved node came back", NodegraphAPI.GetNode("sgPipelineTest") is not None)


def test_painter():
    calls = []

    class FakeProject(types.ModuleType):
        """substance_painter.project with the calls the hook uses."""
        path = None
        dirty = False

        def is_open(self):
            return self.path is not None or getattr(self, "_new", False)

        def file_path(self):
            return self.path

        def open(self, p):
            calls.append(("open", p)); self.path = p; self.dirty = False

        def close(self):
            calls.append(("close",)); self.path = None; self._new = False

        def save(self):
            calls.append(("save", self.path)); self.dirty = False

        def save_as(self, p):
            calls.append(("save_as", p)); self.path = p; self.dirty = False

        def needs_saving(self):
            return self.dirty

    project = FakeProject("substance_painter.project")
    package = types.ModuleType("substance_painter")
    package.project = project
    sys.modules["substance_painter"] = package
    sys.modules["substance_painter.project"] = project

    hook, TankError = load_hook("scene_operation_tk-substancepainter.py")
    path = os.path.join(OUT, "texturing.v001.spp")
    check("Painter: current_path with nothing open is empty", run(hook, "current_path") == "")
    try:
        run(hook, "save_as", path)
        check("Painter: save_as with nothing open is refused", False)
    except TankError:
        check("Painter: save_as with nothing open is refused", True)
    project._new = True  # a project made by the loader's "Create Painter Project", never saved
    try:
        run(hook, "save")
        check("Painter: save of a never-saved project points to Save As", False)
    except TankError as error:
        check("Painter: save of a never-saved project points to Save As", "Save As" in str(error))
    run(hook, "save_as", path)
    check("Painter: save_as saves with forward slashes", calls[-1] == ("save_as", path.replace("\\", "/")))
    check("Painter: current_path is the saved file", run(hook, "current_path") == path.replace("\\", "/"))
    run(hook, "save")
    check("Painter: save saves the current project", calls[-1][0] == "save")
    run(hook, "open", path)
    check("Painter: open closes the current project first", calls[-2:] == [("close",), ("open", path.replace("\\", "/"))])
    check("Painter: reset on a clean project closes it", run(hook, "reset") is True and calls[-1] == ("close",))


try:
    import Katana  # noqa: F401
    in_katana = True
except ImportError:
    in_katana = False

(test_katana if in_katana else test_painter)()
print("\nALL CHECKS PASSED" if not failures else "\n%d FAILED: %s" % (len(failures), failures))
if not in_katana:
    sys.exit(1 if failures else 0)

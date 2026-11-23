"""
Bridge between Griptape Nodes and ShotGrid (Flow Production Tracking).

Griptape's engine runs its own Python, in which the Toolkit core does not
import, so the Griptape nodes (sg_pipeline_nodes.py) run this script with the
desktop app's Python instead:

    "C:\\Program Files\\Shotgun\\Python3\\python.exe" sg_bridge.py find    < request.json
    "C:\\Program Files\\Shotgun\\Python3\\python.exe" sg_bridge.py publish < request.json

It uses the sign-in saved by the desktop app. The request is JSON on stdin and
the answer is one JSON object on the last line of stdout: {"ok": true, ...} or
{"ok": false, "error": "..."}.

find     {"project_id", "publish_type"?, "name_contains"?, "publish_id"?, "limit"?}
         -> {"publishes": [{id, code, name, version_number, type, entity, path, files}]}
         READS only. "path" is the local path (may hold %04d or <UDIM>), "files"
         the files of it that exist on disk.

next_version  {"project_id", "name", "publish_type", "entity"?: {type, id}}
         -> {"version_number"} READS only: one more than the newest publish of
         that name and type on the entity.

locate   {"project_id", "name", "publish_type", "kind": image|texture|usd,
          "entity"?: {type, id}, "task_id"?}
         -> {"version_number", "path" or null, "template"?, "reason"?} READS only:
         the next version (as next_version) and, for an Asset or Shot task,
         where the studio folder structure puts it (core/templates.yml under
         the "primary" storage). path is null without a task; the node then
         keeps its own folder.

publish  {"project_id", "path", "name", "version_number"?, "publish_type",
          "entity"?: {type, id}, "task_id"?, "description"?, "upstream_ids"?, "dry_run"?}
         -> {"publish": {...}} WRITES one PublishedFile (and the publish type if
         it does not exist yet), unless dry_run is true. Without version_number
         it is one more than the newest publish of that name on the entity.
"""

import glob
import json
import os
import re
import sys
import traceback
import urllib.parse

CORE_PYTHON = os.environ.get(
    "SGTK_CORE_PYTHON_PATH",
    r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache\app_store\tk-core\v0.24.6\python",
)
FIELDS = ["code", "name", "version_number", "published_file_type", "entity", "task", "path", "description"]
LOCAL_SETTINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sg_pipeline.local.json")


def _pipeline_site():
    """
    The ShotGrid site the pipeline works on (the desktop app may be showing
    another one): SG_PIPELINE_SITE, else "shotgrid_site" in
    sg_pipeline.local.json at the repo root. That file is git-ignored, so each
    studio keeps its own site out of the repository; copy
    sg_pipeline.local.example.json to start one.
    """
    site = os.environ.get("SG_PIPELINE_SITE")
    if not site and os.path.isfile(LOCAL_SETTINGS):
        with open(LOCAL_SETTINGS, encoding="utf-8") as handle:
            site = json.load(handle).get("shotgrid_site")
    return (site or "").rstrip("/")


SITE = _pipeline_site()


def connect():
    """A connection to SITE with the sign-in the desktop app saved for it."""
    if not SITE:
        raise RuntimeError(
            "No ShotGrid site set: put {\"shotgrid_site\": \"https://<your site>.shotgrid.autodesk.com\"} "
            "in %s (see sg_pipeline.local.example.json) or set SG_PIPELINE_SITE." % LOCAL_SETTINGS
        )
    sys.path.insert(0, CORE_PYTHON)
    import sgtk
    from tank.authentication import session_cache

    authenticator = sgtk.authentication.ShotgunAuthenticator()
    login = session_cache.get_current_user(SITE)
    session = session_cache.get_session_data(SITE, login) if login else None
    if not session:
        raise RuntimeError(
            "Not signed in to %s. Sign in to that site with the Flow Production Tracking desktop app first." % SITE
        )
    user = authenticator.create_session_user(
        login=session["login"], session_token=session["session_token"], host=SITE,
        session_metadata=session.get("session_metadata"),
    )
    sg = user.create_sg_connection()
    sg.find_one("Project", [], ["id"])  # fails here, not halfway through a publish, if the sign-in expired
    return sg


def local_path(sg_path):
    """The local path of a zero-config publish (a file:// url), or None."""
    if not sg_path:
        return None
    if sg_path.get("local_path"):
        return sg_path["local_path"]
    url = sg_path.get("url") or ""
    if not url.startswith("file://"):
        return None
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    # /C:/folder -> C:/folder
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return os.path.normpath(path)


def files_of(path):
    """The files on disk behind a path that may hold a frame or UDIM token."""
    if not path:
        return []
    pattern = glob.escape(path)
    pattern = re.sub(r"%0(\d)d", lambda m: "[0-9]" * int(m.group(1)), pattern)
    pattern = pattern.replace(glob.escape("<UDIM>"), "[0-9]" * 4).replace("<UDIM>", "[0-9]" * 4)
    return sorted(glob.glob(pattern))


def summary(publish):
    path = local_path(publish.get("path"))
    return {
        "id": publish["id"],
        "code": publish.get("code"),
        "name": publish.get("name"),
        "version_number": publish.get("version_number"),
        "type": (publish.get("published_file_type") or {}).get("name"),
        "entity": publish.get("entity"),
        "task": publish.get("task"),
        "description": publish.get("description"),
        "path": path,
        "files": files_of(path),
    }


def find(request):
    sg = connect()
    project = {"type": "Project", "id": int(request["project_id"])}
    if request.get("publish_id"):
        filters = [["id", "is", int(request["publish_id"])]]
    else:
        # same filter as the loaders: only the latest publish of each path
        filters = [["project", "is", project], ["sg_status_list", "is_not", None]]
        if request.get("publish_type"):
            filters.append(["published_file_type.PublishedFileType.code", "is", request["publish_type"]])
        if request.get("name_contains"):
            filters.append(["name", "contains", request["name_contains"]])
    found = sg.find(
        "PublishedFile", filters, FIELDS,
        order=[{"field_name": "id", "direction": "desc"}], limit=int(request.get("limit") or 1),
    )
    return {"publishes": [summary(p) for p in found]}


def _next_version(sg, project, entity, name, type_name):
    """One more than the newest publish of this name and type on the entity."""
    latest = sg.find_one(
        "PublishedFile",
        [["project", "is", project], ["entity", "is", entity], ["name", "is", name],
         ["published_file_type.PublishedFileType.code", "is", type_name]],
        ["version_number"], order=[{"field_name": "version_number", "direction": "desc"}],
    )
    return ((latest or {}).get("version_number") or 0) + 1


def next_version(request):
    sg = connect()
    project = {"type": "Project", "id": int(request["project_id"])}
    entity = request.get("entity") or project
    entity = {"type": entity["type"], "id": int(entity["id"])}
    return {"version_number": _next_version(sg, project, entity, request["name"], request["publish_type"])}


# kind of Griptape publish -> template per entity type (config/core/templates.yml)
GRIPTAPE_TEMPLATES = {
    ("image", "Asset"): "griptape_image_asset_publish",
    ("image", "Shot"): "griptape_image_shot_publish",
    ("texture", "Asset"): "texture_asset_publish",
    ("usd", "Asset"): "griptape_usd_asset_publish",
    ("usd", "Shot"): "griptape_usd_shot_publish",
}
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")


def studio_templates(sg, project_id):
    """
    The pipeline's path templates, rooted at <primary storage>/<project tank_name>.

    Built straight from config/core/templates.yml with tk-core's template
    classes: starting Toolkit itself takes about a minute, too slow for a node.
    """
    from tank import template, template_includes, templatekey
    from tank_vendor import yaml

    storage = sg.find_one("LocalStorage", [["code", "is", "primary"]], ["windows_path", "linux_path", "mac_path"])
    project = sg.find_one("Project", [["id", "is", project_id]], ["tank_name"])
    if not storage or not (project or {}).get("tank_name"):
        return None
    platform_paths = {"win32": storage["windows_path"], "linux2": storage["linux_path"], "darwin": storage["mac_path"]}
    root = {k: os.path.join(v, project["tank_name"]) if v else None for k, v in platform_paths.items()}
    templates_file = os.path.join(CONFIG, "core", "templates.yml")
    with open(templates_file, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    # expands includes and the @asset_root / @shot_root references, as Toolkit does
    data = template_includes.process_includes(templates_file, data)
    keys = templatekey.make_keys(data.get("keys") or {})
    return template.make_template_paths(data.get("paths") or {}, keys, {"primary": root}, default_root="primary")


def task_fields(sg, task_id):
    """The template fields of a task's folders: Asset/Shot, Step, sg_asset_type, Sequence."""
    task = sg.find_one("Task", [["id", "is", int(task_id)]], [
        "entity", "step.Step.short_name", "entity.Asset.code", "entity.Asset.sg_asset_type",
        "entity.Shot.code", "entity.Shot.sg_sequence",
    ])
    if not task or not task.get("entity") or not task.get("step.Step.short_name"):
        return None, None
    kind = task["entity"]["type"]
    fields = {"Step": task["step.Step.short_name"]}
    if kind == "Asset" and task.get("entity.Asset.sg_asset_type"):
        fields.update(Asset=task["entity.Asset.code"], sg_asset_type=task["entity.Asset.sg_asset_type"])
    elif kind == "Shot" and task.get("entity.Shot.sg_sequence"):
        fields.update(Shot=task["entity.Shot.code"], Sequence=task["entity.Shot.sg_sequence"]["name"])
    else:
        return None, None
    return kind, fields


def locate(request):
    sg = connect()
    project_id = int(request["project_id"])
    project = {"type": "Project", "id": project_id}
    entity = request.get("entity") or project
    entity = {"type": entity["type"], "id": int(entity["id"])}
    version = _next_version(sg, project, entity, request["name"], request["publish_type"])
    answer = {"version_number": version, "path": None}

    if not request.get("task_id"):
        answer["reason"] = "no task: the studio folders are per task"
        return answer
    kind, fields = task_fields(sg, request["task_id"])
    template_name = GRIPTAPE_TEMPLATES.get((request.get("kind"), kind))
    templates = studio_templates(sg, project_id) if template_name else None
    if not template_name or not templates or template_name not in templates:
        answer["reason"] = "no studio template for a %s publish on a %s task" % (request.get("kind"), kind)
        return answer

    name = request["name"]
    # template {name} fields allow letters and digits only; textures keep the full name in the file
    fields.update(name=re.sub(r"[^A-Za-z0-9]", "", name) or "main", version=version,
                  texture_name=name, texture_ext="png")
    answer.update(path=templates[template_name].apply_fields(fields), template=template_name)
    return answer


def publish(request):
    sg = connect()
    project = {"type": "Project", "id": int(request["project_id"])}
    entity = request.get("entity") or project
    entity = {"type": entity["type"], "id": int(entity["id"])}
    path = os.path.normpath(request["path"])
    code = os.path.basename(path)
    name = request["name"]
    type_name = request["publish_type"]

    if not files_of(path):
        raise RuntimeError("Nothing on disk at %s" % path)

    version = request.get("version_number") or _next_version(sg, project, entity, name, type_name)

    data = {
        "project": project,
        "entity": entity,
        "code": code,
        "name": name,
        "version_number": int(version),
        "description": request.get("description") or "",
        # the same shape Toolkit registers when no storage roots are configured
        "path": {
            "url": "file:///" + urllib.parse.quote(path.replace("\\", "/"), safe="/:"),
            "name": code,
        },
    }
    if request.get("task_id"):
        data["task"] = {"type": "Task", "id": int(request["task_id"])}
    upstream = [{"type": "PublishedFile", "id": int(i)} for i in request.get("upstream_ids") or [] if i]
    if upstream:
        data["upstream_published_files"] = upstream

    sg_type = sg.find_one("PublishedFileType", [["code", "is", type_name]], ["code"])
    if request.get("dry_run"):
        data["published_file_type"] = sg_type or {"type": "PublishedFileType", "code": type_name, "would_create": True}
        return {"dry_run": True, "publish": data}

    if sg_type is None:
        sg_type = sg.create("PublishedFileType", {"code": type_name})
    data["published_file_type"] = sg_type
    created = sg.create("PublishedFile", data)
    return {"publish": summary(sg.find_one("PublishedFile", [["id", "is", created["id"]]], FIELDS))}


def main():
    try:
        command = sys.argv[1]
        # PowerShell pipes text with a byte-order mark in front
        request = json.loads(sys.stdin.read().lstrip("﻿\xef\xbb\xbf") or "{}")
        answer = {"find": find, "next_version": next_version, "locate": locate, "publish": publish}[command](request)
        answer["ok"] = True
    except EOFError:
        # tk-core tried to ask for a password on the console: the saved session expired
        answer = {
            "ok": False,
            "error": "The sign-in to %s saved by the Flow Production Tracking desktop app has "
            "expired. Sign in to that site in the desktop app, then run this again." % SITE,
            "traceback": traceback.format_exc(),
        }
    except Exception as error:
        answer = {"ok": False, "error": str(error), "traceback": traceback.format_exc()}
    print("\n" + json.dumps(answer))


if __name__ == "__main__":
    main()

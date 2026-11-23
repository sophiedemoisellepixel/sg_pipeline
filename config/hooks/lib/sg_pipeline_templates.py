"""
sg_pipeline: where publishes go, from the templates in core/templates.yml.

Shared by the publish hooks (Maya USD, Painter textures, Mari channels). Each
function returns the template path for the current task, or None when the
pipeline cannot place the file (no Asset or Shot task, the work file is not in
the work area, a template is missing); the hooks then keep their old,
zero-config path, so nothing that worked before breaks.

Hooks load it with load_helper() (see the bottom of each hook), because
Toolkit loads hooks from file paths, not as a package.
"""

import os
import re

UDIM_TOKEN = "<UDIM>"

# work-file template per engine and entity type
WORK_TEMPLATES = {
    ("maya", "Asset"): "maya_asset_work",
    ("maya", "Shot"): "maya_shot_work",
    ("substancepainter", "Asset"): "substancepainter_asset_work",
}


def template_name_key(value):
    """Template {name} fields allow letters and digits only: testAsset_model -> testAssetmodel."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "") or "main"


def entity_kind(context):
    """'Asset' or 'Shot' when the context is a task (or entity) on one, else None."""
    entity = context.entity if context else None
    kind = entity["type"] if entity else None
    return kind if kind in ("Asset", "Shot") else None


def context_fields(tk, context, template):
    """
    The template fields the context provides (Asset, Step, sg_asset_type...).

    Toolkit reads these from the folders recorded for the task; if the task has
    no folders yet they are created first, which is what Workfiles does when an
    artist opens a task.
    """
    fields = context.as_template_fields(template)
    if template.missing_keys(fields, skip_defaults=True) and (context.task or context.entity):
        target = context.task or context.entity
        tk.create_filesystem_structure(target["type"], target["id"])
        fields = context.as_template_fields(template)
    return fields


def resolve(tk, context, template_name, fields):
    """Apply the template with the context's fields plus `fields`; None if anything is missing."""
    template = tk.templates.get(template_name)
    if template is None or not entity_kind(context):
        return None
    all_fields = dict(context_fields(tk, context, template))
    all_fields.update(fields)
    if template.missing_keys(all_fields, skip_defaults=True):
        return None
    return template.apply_fields(all_fields)


def work_file_fields(tk, context, engine, work_path):
    """{name, version} of a work file saved with Workfiles, else None."""
    kind = entity_kind(context)
    template = tk.templates.get(WORK_TEMPLATES.get((engine, kind), ""))
    if not work_path or template is None or not template.validate(work_path):
        return None
    fields = template.get_fields(work_path)
    return {"name": fields["name"], "version": fields["version"]}


def maya_usd_publish(tk, context, scene_path):
    """
    (usd path, version) for a Maya scene saved in the work area:
    <step>/publish/usd/<name>.v###.usd, same name and version as the scene.
    """
    work = work_file_fields(tk, context, "maya", scene_path)
    if not work:
        return None
    name = "usd_%s_publish" % entity_kind(context).lower()
    path = resolve(tk, context, name, work)
    return (path, work["version"]) if path else None


def painter_texture_folder(tk, context, project_path):
    """
    (folder, version) for the textures of a Painter project saved in the work
    area: <step>/publish/textures/<name>/v###/, holding <set>_<map>.<UDIM>.png.
    """
    work = work_file_fields(tk, context, "substancepainter", project_path)
    if not work:
        return None
    path = resolve(tk, context, "texture_asset_publish",
                   dict(work, texture_name="texture", texture_ext="png"))
    return (os.path.dirname(path), work["version"]) if path else None


def mari_texture_path(tk, context, project_name, publish_name, version, extension):
    """
    The UDIM path of one Mari channel: <step>/publish/textures/<mari project>/v###/
    <publish name>.<UDIM>.<ext>. Mari projects are not files, so the name comes
    from the Mari project and the version from ShotGrid.
    """
    return resolve(tk, context, "texture_asset_publish", {
        "name": template_name_key(project_name),
        "version": version,
        "texture_name": publish_name,
        "texture_ext": extension,
    })

"""
Loader actions for Substance 3D Painter (Maya -> Painter).

Actions, mapped to "USD Geometry" publishes in env/includes/substancepainter/apps.yml:

    painter_new_project   Create a Painter project from the published mesh.
    painter_update_mesh   Replace the current project's mesh with the published
                          one (e.g. a newer version), keeping the paint strokes.

The publish the mesh came from is stored in the project's metadata (context
"sg_pipeline", key "source_publish") so texture publishes can be linked back
to the geometry they were painted on.
"""

import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

METADATA_CONTEXT = "sg_pipeline"
METADATA_KEY = "source_publish"

# Subdivision applied to USD meshes that have a subdivision scheme. 0 keeps the
# mesh exactly as it was modelled.
USD_SUBDIVISION_LEVEL = 0


class SubstancePainterActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        action_instances = []

        if "painter_new_project" in actions:
            action_instances.append(
                {
                    "name": "painter_new_project",
                    "params": None,
                    "caption": "Create Painter Project",
                    "description": "Creates a new Substance 3D Painter project from this mesh.",
                }
            )

        if "painter_update_mesh" in actions:
            action_instances.append(
                {
                    "name": "painter_update_mesh",
                    "params": None,
                    "caption": "Update Mesh in Current Project",
                    "description": "Replaces the mesh of the open project with this one, keeping the paint strokes.",
                }
            )

        return action_instances

    def execute_multiple_actions(self, actions):
        for single_action in actions:
            self.execute_action(
                single_action["name"],
                single_action["params"],
                single_action["sg_publish_data"],
            )

    def execute_action(self, name, params, sg_publish_data):
        path = self.get_publish_path(sg_publish_data)
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        if name == "painter_new_project":
            self._new_project(path, sg_publish_data)
        elif name == "painter_update_mesh":
            self._update_mesh(path, sg_publish_data)

    # ---- actions

    def _new_project(self, path, sg_publish_data):
        import substance_painter.project as sp_project

        if sp_project.is_open():
            if sp_project.needs_saving():
                raise Exception(
                    "The current Painter project has unsaved changes. Save and "
                    "close it, then try again."
                )
            sp_project.close()

        settings = sp_project.Settings(
            import_cameras=False,
            # one texture set per material, with all of its UDIM tiles
            project_workflow=sp_project.ProjectWorkflow.UVTile,
            mesh_settings=_mesh_settings(path),
        )
        sp_project.create(mesh_file_path=path.replace("\\", "/"), settings=settings)
        self.parent.logger.info("Created Painter project from %s" % path)

        record = source_publish_record(sg_publish_data, path)
        sp_project.execute_when_not_busy(lambda: _store_source_publish(record))

    def _update_mesh(self, path, sg_publish_data):
        import substance_painter.project as sp_project

        if not sp_project.is_open():
            raise Exception("There is no Painter project open to update.")

        logger = self.parent.logger
        record = source_publish_record(sg_publish_data, path)

        def on_reloaded(status):
            if status == sp_project.ReloadMeshStatus.SUCCESS:
                _store_source_publish(record)
                logger.info("Mesh updated from %s" % path)
            else:
                logger.error("Painter could not reload the mesh from %s" % path)

        settings = sp_project.MeshReloadingSettings(
            import_cameras=False,
            preserve_strokes=True,
            mesh_settings=_mesh_settings(path),
        )
        sp_project.reload_mesh(path.replace("\\", "/"), settings, on_reloaded)


def source_publish_record(sg_publish_data, path):
    """The subset of the publish worth remembering inside the Painter project."""
    entity = sg_publish_data.get("entity") or {}
    task = sg_publish_data.get("task") or {}
    return {
        "id": sg_publish_data.get("id"),
        "name": sg_publish_data.get("name"),
        "code": sg_publish_data.get("code"),
        "version_number": sg_publish_data.get("version_number"),
        "entity_type": entity.get("type"),
        "entity_id": entity.get("id"),
        "entity_name": entity.get("name"),
        "task_id": task.get("id"),
        "path": path.replace("\\", "/"),
    }


def _mesh_settings(path):
    import substance_painter.project as sp_project

    if os.path.splitext(path)[1].lower() in (".usd", ".usda", ".usdc", ".usdz"):
        return sp_project.UsdSettings(subdivision_level=USD_SUBDIVISION_LEVEL)
    return None


def _store_source_publish(record):
    import substance_painter.project as sp_project

    sp_project.Metadata(METADATA_CONTEXT).set(METADATA_KEY, record)

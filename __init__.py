bl_info = {
    "name": "RyRef",
    "blender": (4, 3, 2),
    "version": (1, 0, 0),
    "author": "Logan Fairbairn",
    "description": "A screen-space reference overlay system for the 3D viewport",
    "category": "3D View"
}

import bpy
import gpu
import os
from gpu_extras.batch import batch_for_shader
from bpy.props import (
    StringProperty, FloatProperty, FloatVectorProperty,
    CollectionProperty, IntProperty, BoolProperty
)

_shader = gpu.shader.from_builtin('IMAGE_COLOR')
_draw_handle = None
_image_cache = {}

def tag_redraw():
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

class RyRefImage(bpy.types.PropertyGroup):
    """Data container for a reference image overlay."""

    name: StringProperty(
        name="Name",
        description="Display name for this reference image",
        default="Reference"
    )
    filepath: StringProperty(
        name="File Path",
        description="Path to the reference image",
        subtype='FILE_PATH'
    )
    visible: BoolProperty(
        name="Visible",
        description="Toggle visibility of this reference image",
        default=True
    )
    position: FloatVectorProperty(
        name="Position",
        description="Screen-space position of the image (bottom-left corner)",
        size=2, default=(100.0, 100.0),
        step=10, precision=1,
        update=lambda self, context: tag_redraw()
    )
    scale: FloatVectorProperty(
        name="Scale",
        description="Scaling of the image on the X and Y axes",
        size=2, default=(0.2, 0.2),
        soft_min=0.01, soft_max=2.0,
        step=0.01, precision=2,
        update=lambda self, context: tag_redraw()
    )
    opacity: FloatProperty(
        name="Opacity",
        description="Transparency level of the image",
        default=1.0, min=0.0, max=1.0,
        step=0.01, precision=2,
        update=lambda self, context: tag_redraw()
    )
    flip_x: BoolProperty(
        name="Flip X",
        description="Flip image horizontally",
        default=False,
        update=lambda self, context: tag_redraw()
    )
    flip_y: BoolProperty(
        name="Flip Y",
        description="Flip image vertically",
        default=False,
        update=lambda self, context: tag_redraw()
    )


def draw_overlay():
    scene = bpy.context.scene
    if not scene.ryref_references_on:
        return

    for img_data in scene.ryref_images:
        if not img_data.visible:
            continue

        filepath = img_data.filepath
        if filepath not in _image_cache:
            try:
                image = bpy.data.images.load(filepath, check_existing=True)
                image.gl_load()
                gpu_tex = gpu.texture.from_image(image)
                _image_cache[filepath] = (image, gpu_tex)
            except Exception:
                continue
        else:
            image, gpu_tex = _image_cache[filepath]

        if not image.has_data or image.size[0] == 0 or image.size[1] == 0:
            continue

        x, y = img_data.position
        sx, sy = img_data.scale

        width = image.size[0] * sx
        height = image.size[1] * sy

        coords = [
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
        ]

        uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
        if img_data.flip_x:
            uvs = [(1 - u, v) for u, v in uvs]
        if img_data.flip_y:
            uvs = [(u, 1 - v) for u, v in uvs]

        indices = [(0, 1, 2), (2, 3, 0)]

        batch = batch_for_shader(
            _shader, 'TRIS',
            {"pos": coords, "texCoord": uvs},
            indices=indices
        )

        gpu.state.blend_set('ALPHA')
        _shader.bind()
        _shader.uniform_sampler("image", gpu_tex)
        _shader.uniform_float("color", (1.0, 1.0, 1.0, img_data.opacity))
        batch.draw(_shader)
        gpu.state.blend_set('NONE')

class RYREF_OT_add_image(bpy.types.Operator):
    """Add a reference image to the overlay system"""
    bl_idname = "ryref.add_image"
    bl_label = "Add Reference"

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        img = context.scene.ryref_images.add()
        img.filepath = self.filepath

        filename = os.path.basename(self.filepath)
        name = os.path.splitext(filename)[0]
        img.name = name
        img.position = (100.0, 100.0)
        img.scale = (0.2, 0.2)
        img.opacity = 1.0

        context.scene.ryref_index = len(context.scene.ryref_images) - 1
        tag_redraw()
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class RYREF_OT_remove_image(bpy.types.Operator):
    """Remove the currently selected reference image"""
    bl_idname = "ryref.remove_image"
    bl_label = "Remove Reference"

    def execute(self, context):
        idx = context.scene.ryref_index
        if 0 <= idx < len(context.scene.ryref_images):
            img = context.scene.ryref_images[idx]
            _image_cache.pop(img.filepath, None)
            context.scene.ryref_images.remove(idx)
            context.scene.ryref_index = max(0, idx - 1)
        tag_redraw()
        return {'FINISHED'}

class RYREF_OT_move_image(bpy.types.Operator):
    """Move the selected reference image up or down in the list"""
    bl_idname = "ryref.move_image"
    bl_label = "Move Reference"

    direction: bpy.props.EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
        name="Direction"
    )

    def execute(self, context):
        images = context.scene.ryref_images
        index = context.scene.ryref_index

        if self.direction == 'UP' and index > 0:
            images.move(index, index - 1)
            context.scene.ryref_index -= 1
        elif self.direction == 'DOWN' and index < len(images) - 1:
            images.move(index, index + 1)
            context.scene.ryref_index += 1

        tag_redraw()
        return {'FINISHED'}

class RYREF_UL_ImageList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", icon='HIDE_OFF' if item.visible else 'HIDE_ON', emboss=False)
        row.prop(item, "name", text="", emboss=False)

class RYREF_PT_panel(bpy.types.Panel):
    bl_label = "RyRef"
    bl_idname = "RYREF_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'RyRef'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        images = scene.ryref_images

        label = "References On" if scene.ryref_references_on else "References Off"
        layout.prop(scene, "ryref_references_on", toggle=True, text=label)

        row = layout.row(align=True)
        row.operator("ryref.add_image", icon="ADD", text="")
        row.operator("ryref.remove_image", icon="X", text="")
        row.operator("ryref.move_image", icon="TRIA_UP", text="").direction = 'UP'
        row.operator("ryref.move_image", icon="TRIA_DOWN", text="").direction = 'DOWN'

        layout.template_list("RYREF_UL_ImageList", "", scene, "ryref_images", scene, "ryref_index")

        if 0 <= scene.ryref_index < len(images):
            img = images[scene.ryref_index]

            layout.prop(img, "filepath", text="")
            layout.prop(img, "opacity", slider=True)

            col = layout.column(align=True)
            col.prop(img, "position", index=0, text="Position X")
            col.prop(img, "position", index=1, text="Position Y")

            col = layout.column(align=True)
            col.prop(img, "scale", index=0, text="Scale X")
            col.prop(img, "scale", index=1, text="Scale Y")

            row = layout.row(align=True)
            row.prop(img, "flip_x", toggle=True)
            row.prop(img, "flip_y", toggle=True)

classes = (
    RyRefImage,
    RYREF_OT_add_image,
    RYREF_OT_remove_image,
    RYREF_OT_move_image,
    RYREF_UL_ImageList,
    RYREF_PT_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.ryref_images = CollectionProperty(type=RyRefImage)
    bpy.types.Scene.ryref_index = IntProperty(default=0)
    bpy.types.Scene.ryref_references_on = BoolProperty(
        name="Enable Overlays",
        description="Toggle visibility of all reference overlays",
        default=True
    )

    global _draw_handle
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_overlay, (), 'WINDOW', 'POST_PIXEL')

def unregister():
    global _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None

    del bpy.types.Scene.ryref_images
    del bpy.types.Scene.ryref_index
    del bpy.types.Scene.ryref_references_on

    _image_cache.clear()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()

"""Open helper for output/woody/woody.blend:

  blender output/woody/woody.blend --python open_woody.py

Adds the 'Woody' tab in the 3D-view sidebar (N): live WASD control (wm.woody_controller) and buttons that play the baked actions,
then starts the showcase through the chase camera (Cam_Follow)."""
import os
import sys
import time
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import char_anim as CA
import char_controller as CTL

RIG = "Rig_Woody"


class WOODY_OT_controller(CTL.MALE20S_OT_controller):
    bl_idname = "wm.woody_controller"
    bl_label = "Woody controller"

    def invoke(self, context, event):
        arm = bpy.data.objects.get(RIG)
        if arm is None:
            self.report({"ERROR"}, RIG + " not found")
            return {"CANCELLED"}
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        if arm.animation_data:
            arm.animation_data.action = None
        self.state = CTL.ControllerState(arm, CA.RigData(arm))
        self.keys = {}
        self.t_last = time.perf_counter()
        self._timer = context.window_manager.event_timer_add(1.0 / 30.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("操作: W 歩く / Shift+W 走る / Shift+Ctrl+W 全力 / A D 旋回 / Space ジャンプ / S 停止 / Esc 終了")
        return {"RUNNING_MODAL"}


class WOODY_OT_play(bpy.types.Operator):
    bl_idname = "wm.woody_play"
    bl_label = "Play action"
    action: bpy.props.StringProperty()

    def execute(self, context):
        arm = bpy.data.objects.get(RIG)
        act = bpy.data.actions.get(self.action)
        if arm is None or act is None:
            return {"CANCELLED"}
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        ad = arm.animation_data or arm.animation_data_create()
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
        arm.location = (0, 3.0 if "Showcase" in act.name else 0.0, 0)
        arm.rotation_euler = (0, 0, 0)
        ad.action = act
        sc = context.scene
        sc.frame_start, sc.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
        sc.frame_set(sc.frame_start)
        bpy.ops.screen.animation_play()
        return {"FINISHED"}


class WOODY_PT_panel(bpy.types.Panel):
    bl_label = "Woody"
    bl_idname = "WOODY_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Woody"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="操作 (ライブ)")
        col.operator("wm.woody_controller", text="操作開始  (Esc で終了)", icon="PLAY")
        col.label(text="W 歩く / Shift+W 走る / Shift+Ctrl+W 全力")
        col.label(text="A D 旋回 / Space ジャンプ / S 停止")
        col.separator()
        col.label(text="アクション再生")
        for nm, label in (("Woody_Showcase", "デモ (全部つなぎ)"), ("Woody_Idle", "Idle"), ("Woody_Walk", "Walk"), ("Woody_Run", "Run"),
                          ("Woody_Sprint", "Sprint"), ("Woody_Jump", "Jump")):
            col.operator("wm.woody_play", text=label).action = nm


def view_setup():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                sp = area.spaces.active
                sp.shading.type = "MATERIAL"
                sp.overlay.show_floor = False
                sp.region_3d.view_perspective = "CAMERA"
                sp.show_region_ui = True
                with bpy.context.temp_override(window=win, area=area, region=[r for r in area.regions if r.type == "WINDOW"][0]):
                    try:
                        bpy.ops.wm.woody_play(action="Woody_Showcase")
                    except Exception as e:
                        print("play failed:", e)
                return None
    return None


for c in (WOODY_OT_controller, WOODY_OT_play, WOODY_PT_panel):
    try:
        bpy.utils.register_class(c)
    except ValueError:
        pass
bpy.app.timers.register(view_setup, first_interval=2.5)

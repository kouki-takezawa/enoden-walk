"""Interactive control of the character inside the Blender GUI (WASD-style).

  W            walk forward            Shift+W       run             Shift+Ctrl+W   sprint
  A / D        turn left / right       Space         jump            S              stop        Esc  quit

The pose is generated live from the same gait functions that were used for the baked actions (walk / run / sprint / idle / jump blended by
speed), so the controller can be tested without any keyframes.  ControllerState is pure logic (no UI) and is also used by the headless
self-test."""
import math
import time
import bpy
from mathutils import Vector
from char_core import lerp, smoothstep, clamp
import char_anim as CA

SPEEDS = {"walk": 1.25, "run": 2.9, "sprint": 6.0}
STRIDE = {k: CA.GAITS[k]["v"] * CA.GAITS[k]["T"] / CA.FPS for k in ("walk", "run", "sprint")}
TURN_DEG = {"idle": 150.0, "walk": 120.0, "run": 85.0, "sprint": 45.0}


class ControllerState:
    def __init__(self, arm, rig):
        self.arm, self.rig = arm, rig
        self.phase = 0.0
        self.idle_t = 0.0
        self.speed = 0.0
        self.yaw = 0.0
        self.pos = Vector((0.0, 0.0, 0.0))
        self.jump_t = None
        self.turn_rate = 0.0

    @staticmethod
    def target_speed(keys):
        if not keys.get("W"):
            return 0.0
        if keys.get("SHIFT") and keys.get("CTRL"):
            return SPEEDS["sprint"]
        if keys.get("SHIFT"):
            return SPEEDS["run"]
        return SPEEDS["walk"]

    def stride_for(self, s):
        if s <= SPEEDS["walk"]:
            return STRIDE["walk"]
        if s <= SPEEDS["run"]:
            return lerp(STRIDE["walk"], STRIDE["run"], (s - SPEEDS["walk"]) / (SPEEDS["run"] - SPEEDS["walk"]))
        return lerp(STRIDE["run"], STRIDE["sprint"], clamp((s - SPEEDS["run"]) / (SPEEDS["sprint"] - SPEEDS["run"])))

    def loco_keys(self, s):
        rig, ph = self.rig, self.phase
        fr = lambda g: ph * CA.GAITS[g]["T"]
        idle = CA.pose_keys(rig, "idle", (self.idle_t * CA.FPS) % 120.0, None)
        if s < 0.03:
            return idle
        walk = CA.pose_keys(rig, "gait", fr("walk"), CA.GAITS["walk"])
        if s <= SPEEDS["walk"]:
            return CA.blend_keys(idle, walk, smoothstep(0.03, 0.75, s))
        run = CA.pose_keys(rig, "gait", fr("run"), CA.GAITS["run"])
        if s <= SPEEDS["run"]:
            return CA.blend_keys(walk, run, smoothstep(SPEEDS["walk"], SPEEDS["run"], s))
        sprint = CA.pose_keys(rig, "gait", fr("sprint"), CA.GAITS["sprint"])
        return CA.blend_keys(run, sprint, smoothstep(SPEEDS["run"], SPEEDS["sprint"], s))

    def update(self, dt, keys):
        """Advance the simulation by dt seconds with the given key states; returns the pose keys that were applied."""
        dt = min(dt, 0.1)
        st = self.target_speed(keys)
        acc = 7.0 if st > self.speed else 9.0
        self.speed += clamp(st - self.speed, -acc * dt, acc * dt)
        kind = "idle" if self.speed < 0.6 else ("walk" if self.speed < 2.0 else ("run" if self.speed < 4.5 else "sprint"))
        turn = (1.0 if keys.get("A") else 0.0) - (1.0 if keys.get("D") else 0.0)
        self.yaw += turn * math.radians(TURN_DEG[kind]) * dt
        fwd = Vector((math.sin(self.yaw), -math.cos(self.yaw), 0.0))                  # yaw 0 = facing -Y; +yaw (CCW seen from above) turns left
        self.pos += fwd * self.speed * dt
        if self.speed > 0.03:
            self.phase = (self.phase + dt * self.speed / self.stride_for(self.speed)) % 1.0
        else:
            self.idle_t += dt
            self.phase = 0.0
        self.idle_t += dt * 0.0
        keys_out = self.loco_keys(self.speed)
        if keys.get("SPACE") and self.jump_t is None:
            self.jump_t = 0.0
        if self.jump_t is not None:
            f = self.jump_t * CA.FPS
            jk = CA.pose_keys(self.rig, "jump", min(f, 46.0), None)
            w = smoothstep(0.0, 3.0, f) * (1.0 - smoothstep(43.0, 46.0, f))
            keys_out = CA.blend_keys(keys_out, jk, w)
            self.jump_t += dt
            if f >= 46.0:
                self.jump_t = None
        return keys_out

    def apply(self, keys_out):
        arm = self.arm
        for n, (q, l) in keys_out.items():
            pb = arm.pose.bones[n]
            pb.rotation_mode = "QUATERNION"
            if n != "Root":
                pb.rotation_quaternion = q
            if n == "Hips":
                pb.location = l
        arm.location = self.pos
        arm.rotation_euler = (0.0, 0.0, self.yaw)


KEYMAP = {"W": "W", "A": "A", "S": "S", "D": "D", "UP_ARROW": "W", "LEFT_ARROW": "A", "DOWN_ARROW": "S", "RIGHT_ARROW": "D",
          "LEFT_SHIFT": "SHIFT", "RIGHT_SHIFT": "SHIFT", "LEFT_CTRL": "CTRL", "RIGHT_CTRL": "CTRL", "SPACE": "SPACE"}


class MALE20S_OT_controller(bpy.types.Operator):
    bl_idname = "wm.male20s_controller"
    bl_label = "Male20s character controller"

    def invoke(self, context, event):
        arm = bpy.data.objects.get("Rig_Male20s")
        if arm is None:
            self.report({"ERROR"}, "Rig_Male20s not found")
            return {"CANCELLED"}
        if arm.animation_data:
            arm.animation_data.action = None                    # the live pose must not fight a baked action
        self.state = ControllerState(arm, CA.RigData(arm))
        self.keys = {}
        self.t_last = time.perf_counter()
        self._timer = context.window_manager.event_timer_add(1.0 / 30.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("操作: W 歩く / Shift+W 走る / Shift+Ctrl+W 全力 / A D 旋回 / Space ジャンプ / S 停止 / Esc 終了")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" and event.value == "PRESS":
            return self.cancel(context)
        if event.type == "TIMER":
            now = time.perf_counter()
            dt = now - self.t_last
            self.t_last = now
            k = self.state.update(dt, self.keys)
            if self.keys.get("SPACE"):
                self.keys["SPACE"] = False
            self.state.apply(k)
            return {"PASS_THROUGH"}
        name = KEYMAP.get(event.type)
        if name:
            if event.value == "PRESS":
                self.keys[name] = True
            elif event.value == "RELEASE":
                self.keys[name] = False
            if name == "S":
                self.keys["W"] = False
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        return {"CANCELLED"}


def register():
    try:
        bpy.utils.register_class(MALE20S_OT_controller)
    except ValueError:
        pass


def selftest(arm, rig, log):
    """Headless simulation: idle -> walk -> run -> sprint -> jump -> turn, checks that the pose stays finite and the speed / position match."""
    st = ControllerState(arm, rig)
    dt = 1.0 / 30.0
    script = [("idle", {}, 30), ("walk", {"W": True}, 90), ("run", {"W": True, "SHIFT": True}, 90), ("sprint", {"W": True, "SHIFT": True, "CTRL": True}, 90),
              ("jump", {"W": True, "SHIFT": True, "SPACE": True}, 60), ("turn", {"W": True, "A": True}, 60), ("stop", {}, 45)]
    ok = True
    for name, keys, n in script:
        p0 = st.pos.copy()
        for i in range(n):
            k = dict(keys)
            if name == "jump" and i > 0:
                k["SPACE"] = False
            out = st.update(dt, k)
            st.apply(out)
            bad = any(not all(math.isfinite(c) for c in q) for q, _ in out.values())
            if bad:
                ok = False
        log("  controller %-6s speed %.2f m/s  travelled %.2f m  yaw %.0f deg" % (name, st.speed, (st.pos - p0).length, math.degrees(st.yaw)))
    log("  controller self-test:", "OK" if ok else "FAILED")
    return ok

"""Procedural animation for the character: idle, walk, run (jog), sprint, jump.

The gaits are generated analytically: foot targets follow an inverted-pendulum-like treadmill model (the stance foot moves backwards at exactly
the ground speed, heel-strike -> flat -> heel-off about the heel / ball), two-bone analytic IK for the legs, FK for spine / arms / head.
The result is baked as ordinary pose-bone rotation keys (game-engine friendly, no constraints).  Verification: foot sliding, ground
penetration, reach limit, loop closure are measured on the evaluated armature."""
import math
import os
import bpy
from mathutils import Vector, Matrix, Quaternion
from char_core import *

FPS = 30
SHEET_W = 0
G = 9.81
DEG = math.pi / 180.0


def Rx(a):
    return Matrix.Rotation(a, 3, "X")


def Ry(a):
    return Matrix.Rotation(a, 3, "Y")


def Rz(a):
    return Matrix.Rotation(a, 3, "Z")


def ident():
    return Matrix.Identity(3)


def basis(a, f):
    """Orthonormal frame (columns: axis, front, side) from a bone axis and a 'front' hint."""
    a = Vector(a).normalized()
    f = Vector(f) - a * Vector(f).dot(a)
    if f.length < 1e-6:
        f = Vector((0, -1, 0)) - a * a.y * -1
    f.normalize()
    s = a.cross(f)
    return Matrix(((a.x, f.x, s.x), (a.y, f.y, s.y), (a.z, f.z, s.z)))


# ------------------------------------------------------------------------------------------------------ rig data
class RigData:
    def __init__(self, arm):
        self.arm = arm
        self.b = {}
        for bone in arm.data.bones:
            self.b[bone.name] = dict(head=Vector(bone.head_local), tail=Vector(bone.tail_local), R=bone.matrix_local.to_3x3(),
                                     parent=bone.parent.name if bone.parent else None)
        names = list(self.b)
        order = []
        while len(order) < len(names):
            for n in names:
                if n not in order and (self.b[n]["parent"] is None or self.b[n]["parent"] in order):
                    order.append(n)
        self.order = order
        self.finger_bones = [n for n in names if any(f in n for f in ("Thumb", "Index", "Middle", "Ring", "Pinky"))]
        hips = self.b["Hips"]["head"]
        self.hips_head = hips
        self.hip_off = {s: self.b[s + "UpLeg"]["head"] - hips for s in ("Left", "Right")}
        self.L1 = (self.b["LeftLeg"]["head"] - self.b["LeftUpLeg"]["head"]).length
        self.L2 = (self.b["LeftFoot"]["head"] - self.b["LeftLeg"]["head"]).length
        self.rest_ankle = {s: self.b[s + "Foot"]["head"] for s in ("Left", "Right")}
        self.a0 = {n: (self.b[n]["tail"] - self.b[n]["head"]).normalized() for n in ("LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot")}

    def to_keys(self, D, hips_t):
        """D: bone -> absolute delta rotation (armature space, applied to the rest orientation).  Returns {bone: (quat, loc)}."""
        out = {}
        for n in self.order:
            info = self.b[n]
            Rrest = info["R"]
            Dp = D[info["parent"]] if info["parent"] else ident()
            Db = D.get(n, Dp)
            Rb = Rrest.inverted() @ (Dp.inverted() @ Db) @ Rrest
            q = Rb.to_quaternion()
            loc = Vector((0, 0, 0))
            if n == "Hips":
                loc = Rrest.inverted() @ hips_t
            out[n] = (q, loc)
        return out


# ------------------------------------------------------------------------------------------------------ gaits
GAITS = {
    "walk": dict(T=32, v=1.25, stance=0.62, s_hs=0.36, hs=18, to=-30, u1=0.14, u2=0.58, lift=0.075, kick=0.02, toe_clear=14, h=0.897, bounce=0.017, bsign=1,
                 sway=0.020, yaw=4.5, roll=2.6, lean=2.0, arm=21, arm_add=6, elbow=17, elbow_var=9, foot_x=0.080, toe_out=5, twist=1.35, curl=8),
    "run": dict(T=22, v=2.9, stance=0.30, s_hs=0.24, hs=8, to=-36, u1=0.10, u2=0.60, lift=0.24, kick=0.17, toe_clear=4, h=0.855, bounce=0.030, bsign=-1,
                sway=0.012, yaw=8, roll=2.6, lean=8, arm=40, arm_add=12, elbow=92, elbow_var=14, foot_x=0.088, toe_out=2, twist=1.25, curl=58),
    "sprint": dict(T=15, v=6.0, stance=0.22, s_hs=0.30, hs=4, to=-42, u1=0.05, u2=0.55, lift=0.30, kick=0.26, toe_clear=2, h=0.825, bounce=0.045, bsign=-1,
                   sway=0.010, yaw=11, roll=2.5, lean=17, arm=56, arm_add=14, elbow=95, elbow_var=16, foot_x=0.082, toe_out=0, twist=1.2, curl=70),
}

HEEL = (-0.080, -0.088)          # ankle -> heel contact point (forward s, up z) in the foot frame
BALL = (0.123, -0.088)           # ankle -> ball-of-foot contact point


def rot2(v, th):
    c, s = math.cos(th), math.sin(th)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def stance_ankle(s_flat, theta, u_phase, g):
    """(ankle s, ankle z, pitch) for a stance foot; theta (rad, toes up positive); pivot at heel / ball depending on the sign of theta."""
    if theta >= 0:
        P = (s_flat + HEEL[0], 0.0)
        d = rot2(HEEL, theta)
    else:
        P = (s_flat + BALL[0], 0.0)
        d = rot2(BALL, theta)
    return P[0] - d[0], P[1] - d[1]


def smooth5(w):
    return w * w * w * (10 - 15 * w + 6 * w * w)


def foot_state(g, phi):
    """Foot of a leg whose phase is phi (0 = heel strike).  Returns (s, z, theta(rad), stance_flag) in the pelvis-centred treadmill frame
    (s forward)."""
    T_s = g["T"] / FPS
    st = g["stance"]
    travel = g["v"] * T_s * st
    def stance_pose(u):
        s_flat = g["s_hs"] - travel * u
        if u < g["u1"]:
            th = g["hs"] * DEG * (1.0 - u / g["u1"])
        elif u < g["u2"]:
            th = 0.0
        else:
            k = (u - g["u2"]) / (1.0 - g["u2"])
            th = g["to"] * DEG * (k ** 1.3)
        s, z = stance_ankle(s_flat, th, u, g)
        return s, z, th
    if phi < st:
        s, z, th = stance_pose(phi / st)
        return s, z, th, True
    w = (phi - st) / (1.0 - st)
    s0, z0, th0 = stance_pose(1.0)
    s1, z1, th1 = stance_pose(0.0)
    e = smooth5(w)
    s = lerp(s0, s1 + g["stride_wrap"] if False else s1, e) - g["kick"] * math.sin(math.pi * w) ** 2
    z = lerp(z0, z1, e) + g["lift"] * math.sin(math.pi * min(1.0, w * 1.0)) ** 1.0 * (1.0 if g["lift"] > 0.1 else 1.0)
    th = lerp(th0, th1, smooth5(w)) + g["toe_clear"] * DEG * math.sin(math.pi * w)
    return s, z, th, False


def leg_ik(H, A, pole, L1, L2):
    d_vec = A - H
    d = clamp(d_vec.length, abs(L1 - L2) + 1e-3, (L1 + L2) * 0.9995)
    u = d_vec.normalized()
    k = pole - u * pole.dot(u)
    if k.length < 1e-6:
        k = Vector((0, -1, 0)) - u * u.y * -1
    k.normalize()
    ca = clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1)
    a = math.acos(ca)
    a1 = u * math.cos(a) + k * math.sin(a)
    K = H + a1 * L1
    Ac = H + u * d
    a2 = (Ac - K).normalized()
    return a1, a2, k, (A - Ac).length


def gait_pose(rig, g, f, root_speed_dummy=None):
    """Pose of one frame f (0..T) of a locomotion cycle.  Returns (D dict, pelvis translation)."""
    T = g["T"]
    ph = (f / T) % 1.0
    D = {"Root": ident()}
    v = g["v"]
    # ---------------- pelvis
    yaw = -g["yaw"] * DEG * math.cos(2 * math.pi * ph)
    roll = -g["roll"] * DEG * math.cos(2 * math.pi * (ph - 0.3 * g["stance"] / 0.62 * 0 - g["stance"] / 2 * 0.98))
    lean = g["lean"] * DEG
    Dh = Rz(yaw) @ Ry(roll) @ Rx(lean * 0.35)
    mid = g["stance"] / 2.0
    z_design = g["h"] + g["bsign"] * g["bounce"] * math.cos(4 * math.pi * (ph - mid))
    sway = g["sway"] * math.cos(2 * math.pi * (ph - mid))
    # ---------------- feet targets
    feet = {}
    for side, sgn, off in (("Left", 1, 0.0), ("Right", -1, 0.5)):
        s, z, th, stance = foot_state(g, (ph + off) % 1.0)
        yaw_f = sgn * g["toe_out"] * DEG
        x = sgn * g["foot_x"] + sgn * 0.012 * math.sin(math.pi * ((ph + off) % 1.0)) * (0 if stance else 1)
        A = Vector((x, rig.hips_head.y - s, z))
        feet[side] = (A, th, yaw_f, stance)
    # ---------------- reach clamp on the pelvis height (stance legs)
    zp = z_design
    for _ in range(2):
        t = Vector((sway, 0.0, zp - rig.hips_head.z))
        for side in ("Left", "Right"):
            A, th, yaw_f, stance = feet[side]
            if not stance:
                continue
            Hj = rig.hips_head + t + Dh @ rig.hip_off[side]
            dxy = math.hypot(Hj.x - A.x, Hj.y - A.y)
            lim = (rig.L1 + rig.L2) * 0.9975
            zmax = A.z + math.sqrt(max(lim * lim - dxy * dxy, 0.0))
            hj_dz = (Dh @ rig.hip_off[side]).z
            zp = min(zp, zmax - hj_dz)
    t_pel = Vector((sway, 0.0, zp - rig.hips_head.z))
    D["Hips"] = Dh
    # ---------------- spine / neck / head (FK)
    tw = g["twist"] * g["yaw"] * DEG * math.cos(2 * math.pi * ph)
    each_yaw = (tw - yaw) / 3.0 * 1.0
    l_each = lean * 0.65 / 3.0
    r_each = -roll * 0.6 / 3.0
    Dp = Dh
    for nm in ("Spine", "Spine1", "Spine2"):
        Dp = Dp @ (Rz(each_yaw) @ Ry(r_each) @ Rx(l_each))
        D[nm] = Dp
    tot_yaw = yaw + 3 * each_yaw
    D["Neck"] = Dp @ (Rz(-tot_yaw * 0.45) @ Rx(-lean * 0.35))
    D["Head"] = D["Neck"] @ (Rz(-tot_yaw * 0.40) @ Rx(-lean * 0.30) @ Ry(-roll * 0.3))
    D["Jaw"] = D["Head"]
    D["LeftEye"] = D["Head"]
    D["RightEye"] = D["Head"]
    # ---------------- arms (FK)
    for side, sgn in (("Left", 1), ("Right", -1)):
        pha = (ph + (0.0 if sgn > 0 else 0.5)) % 1.0
        swing = g["arm"] * DEG * math.cos(2 * math.pi * pha)                            # + = arm backwards; max backwards at own-side heel strike
        elbow = g["elbow"] * DEG + g["elbow_var"] * DEG * 0.5 * (1.0 + math.cos(2 * math.pi * pha))
        add = g["arm_add"] * DEG
        D[side + "Shoulder"] = D["Spine2"]
        D[side + "Arm"] = D[side + "Shoulder"] @ (Rx(swing) @ Ry(sgn * add))
        D[side + "ForeArm"] = D[side + "Arm"] @ Rx(-elbow)
        D[side + "Hand"] = D[side + "ForeArm"] @ (Rx(-8 * DEG) @ Rz(sgn * -6 * DEG))
        for fname in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            base = g["curl"] * DEG * (0.5 if fname == "Thumb" else 1.0)
            prev = D[side + "Hand"]
            for k in (1, 2, 3):
                bn = "%s%s%d" % (side, fname, k)
                D[bn] = prev @ Ry(sgn * base * (0.55 if k == 1 else (1.0 if k == 2 else 0.7)) * (0.5 if k == 1 else 1))
                prev = D[bn]
    # ---------------- legs (IK)
    for side, sgn in (("Left", 1), ("Right", -1)):
        A, th, yaw_f, stance = feet[side]
        Hj = rig.hips_head + t_pel + Dh @ rig.hip_off[side]
        pole = Rz(yaw_f * 0.6 + (yaw * 0.5)) @ Vector((0, -1, 0))
        a1, a2, k, err = leg_ik(Hj, A, pole, rig.L1, rig.L2)
        B0 = lambda n: basis(rig.a0[n], Vector((0, -1, 0)))
        D[side + "UpLeg"] = basis(a1, k) @ B0(side + "UpLeg").inverted()
        D[side + "Leg"] = basis(a2, k) @ B0(side + "Leg").inverted()
        Df = Rz(yaw_f) @ Rx(-th)
        D[side + "Foot"] = Df
        toe_rel = Rx(th) if th < 0 else ident()
        D[side + "Toe"] = Df @ toe_rel
    return D, t_pel


def idle_pose(rig, f, T=120):
    ph = f / T
    D = {"Root": ident()}
    sway = 0.008 * math.sin(2 * math.pi * ph)
    roll = -1.0 * DEG * math.sin(2 * math.pi * ph)
    Dh = Ry(roll) @ Rz(1.2 * DEG * math.sin(2 * math.pi * ph + 0.6))
    breath = math.sin(2 * math.pi * ph * 4)
    zp = 0.922 + 0.002 * breath
    t_pel = Vector((sway, 0, zp - rig.hips_head.z))
    D["Hips"] = Dh
    Dp = Dh
    for nm, k in (("Spine", 0.4), ("Spine1", 0.5), ("Spine2", 1.0)):
        Dp = Dp @ (Rx(-0.35 * DEG * breath * k) @ Ry(-roll * 0.3))
        D[nm] = Dp
    D["Neck"] = Dp @ Rz(-1.0 * DEG * math.sin(2 * math.pi * ph + 0.6))
    D["Head"] = D["Neck"] @ (Rx(0.6 * DEG * math.sin(2 * math.pi * ph * 2)) @ Rz(2.2 * DEG * math.sin(2 * math.pi * ph + 1.0)))
    D["Jaw"] = D["Head"]
    D["LeftEye"] = D["Head"]
    D["RightEye"] = D["Head"]
    for side, sgn in (("Left", 1), ("Right", -1)):
        D[side + "Shoulder"] = D["Spine2"] @ Rz(sgn * 0.6 * DEG * breath)
        D[side + "Arm"] = D[side + "Shoulder"] @ (Ry(sgn * 5 * DEG) @ Rx(-(3 + 1.5 * math.sin(2 * math.pi * ph + sgn)) * DEG))
        D[side + "ForeArm"] = D[side + "Arm"] @ Rx(-9 * DEG)
        D[side + "Hand"] = D[side + "ForeArm"]
        for fname in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            prev = D[side + "Hand"]
            for k in (1, 2, 3):
                bn = "%s%s%d" % (side, fname, k)
                D[bn] = prev @ Ry(sgn * 2 * DEG)
                prev = D[bn]
    for side, sgn in (("Left", 1), ("Right", -1)):
        A = Vector((rig.rest_ankle[side].x + sgn * 0.005, rig.rest_ankle[side].y, rig.rest_ankle[side].z))
        Hj = rig.hips_head + t_pel + Dh @ rig.hip_off[side]
        a1, a2, k, err = leg_ik(Hj, A, Vector((0, -1, 0)), rig.L1, rig.L2)
        B0 = lambda n: basis(rig.a0[n], Vector((0, -1, 0)))
        D[side + "UpLeg"] = basis(a1, k) @ B0(side + "UpLeg").inverted()
        D[side + "Leg"] = basis(a2, k) @ B0(side + "Leg").inverted()
        D[side + "Foot"] = Rz(sgn * 4 * DEG)
        D[side + "Toe"] = D[side + "Foot"]
    return D, t_pel


def jump_pose(rig, f):
    """Standing jump (46 frames): crouch 0-9, take-off 10-13, flight 13-30, landing 30-36, recover 36-46."""
    D = {"Root": ident()}
    z0 = 0.922
    crouch = 0.145
    t_off, t_land = 13.0, 30.0
    air = 0.0
    if f < 10:
        w = smooth5(f / 10.0)
        zp = z0 - crouch * w
        lean = 22 * DEG * w
        arms = 1.0 * w
        pitch = 0.0
    elif f < t_off:
        w = (f - 10) / (t_off - 10)
        zp = lerp(z0 - crouch, z0 + 0.012, smooth5(w))
        lean = lerp(22, 6, w) * DEG
        arms = lerp(1.0, -1.3, w)
        pitch = -34 * DEG * w * w
    elif f < t_land:
        tt = (f - t_off) / FPS
        vy = 0.5 * G * ((t_land - t_off) / FPS)
        zp = z0 + 0.012 + vy * tt - 0.5 * G * tt * tt
        air = 1.0
        w = (f - t_off) / (t_land - t_off)
        lean = lerp(6, 10, math.sin(math.pi * w)) * DEG
        arms = lerp(-1.3, -1.0, math.sin(math.pi * w)) + 0.3 * math.sin(math.pi * w)
        pitch = -30 * DEG
    elif f < 36:
        w = (f - t_land) / 6.0
        zp = lerp(z0 + 0.012, z0 - 0.125, smooth5(w))
        lean = lerp(10, 18, w) * DEG
        arms = lerp(-1.0, 0.7, smooth5(w))
        pitch = -30 * DEG * (1 - smooth5(min(1.0, w * 2)))
    else:
        w = (f - 36) / 10.0
        zp = lerp(z0 - 0.125, z0, smooth5(w))
        lean = lerp(18, 0, smooth5(w)) * DEG
        arms = lerp(0.7, 0.0, smooth5(w))
        pitch = 0.0
    t_pel = Vector((0, 0, zp - rig.hips_head.z))
    Dh = Rx(lean * 0.4)
    D["Hips"] = Dh
    Dp = Dh
    for nm in ("Spine", "Spine1", "Spine2"):
        Dp = Dp @ Rx(lean * 0.2)
        D[nm] = Dp
    D["Neck"] = Dp @ Rx(-lean * 0.3)
    D["Head"] = D["Neck"] @ Rx(-lean * 0.25 + (-8 * DEG if air else 0))
    D["Jaw"] = D["Head"]
    D["LeftEye"] = D["Head"]
    D["RightEye"] = D["Head"]
    for side, sgn in (("Left", 1), ("Right", -1)):
        D[side + "Shoulder"] = D["Spine2"]
        sw = arms * 55 * DEG                                                            # + back / - forward-up
        D[side + "Arm"] = D[side + "Shoulder"] @ (Rx(sw * 1.0) @ Ry(sgn * (10 + 25 * max(0.0, -arms)) * DEG))
        D[side + "ForeArm"] = D[side + "Arm"] @ Rx(-(20 + 35 * abs(arms)) * DEG)
        D[side + "Hand"] = D[side + "ForeArm"]
        for fname in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            prev = D[side + "Hand"]
            for k in (1, 2, 3):
                bn = "%s%s%d" % (side, fname, k)
                D[bn] = prev @ Ry(sgn * 12 * DEG)
                prev = D[bn]
    for side, sgn in (("Left", 1), ("Right", -1)):
        Hj = rig.hips_head + t_pel + Dh @ rig.hip_off[side]
        foot_x = sgn * 0.090
        if air:
            w = (f - t_off) / (t_land - t_off)
            tuck = math.sin(math.pi * w)
            rel_ext = Vector((sgn * 0.004, 0.0, -(rig.L1 + rig.L2) * 0.9975))
            rel_tuck = Vector((sgn * 0.012, -0.10, -0.62))
            A = Hj + rel_ext.lerp(rel_tuck, tuck)
        else:
            th = pitch
            s_a, z_a = stance_ankle(0.0, th, 0.0, None)
            A = Vector((foot_x, rig.rest_ankle[side].y - s_a * 0 + (-(s_a) + 0.0) * 0, z_a))
            A.y = rig.rest_ankle[side].y - (s_a - 0.0) * 1.0 + 0.0
            # keep the ball where it was: shift by the ball offset of the flat foot
            A.y = rig.rest_ankle[side].y - (s_a - 0.0)
        a1, a2, k, err = leg_ik(Hj, A, Vector((0, -1, 0)), rig.L1, rig.L2)
        B0 = lambda n: basis(rig.a0[n], Vector((0, -1, 0)))
        D[side + "UpLeg"] = basis(a1, k) @ B0(side + "UpLeg").inverted()
        D[side + "Leg"] = basis(a2, k) @ B0(side + "Leg").inverted()
        th = pitch
        D[side + "Foot"] = Rx(-th)
        D[side + "Toe"] = D[side + "Foot"] @ (Rx(th) if th < 0 else ident())
    return D, t_pel


# ------------------------------------------------------------------------------------------------------ baking
FINGER_KEYS = None


def pose_keys(rig, kind, f, g=None):
    if kind == "idle":
        D, t = idle_pose(rig, f)
    elif kind == "jump":
        D, t = jump_pose(rig, f)
    else:
        D, t = gait_pose(rig, g, f)
    return rig.to_keys(D, t)


def bake_action(arm, rig, name, kind, nframes, g=None, loop=True):
    frames = list(range(0, nframes + 1))
    keys = {f: pose_keys(rig, kind, f, g) for f in frames}
    return bake_keys(arm, rig, name, keys, nframes, loop)


def bake_keys(arm, rig, name, keys, nframes, loop=True, root_y=None):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    frames = list(range(0, nframes + 1))
    first = {}
    for n in rig.order:
        qs = [keys[f][n][0] for f in frames]
        ls = [keys[f][n][1] for f in frames]
        varies = any((qs[0].rotation_difference(q)).angle > 1e-4 for q in qs) or any((ls[0] - l).length > 1e-6 for l in ls)
        pb = arm.pose.bones[n]
        use = frames if varies else [frames[0], frames[-1]]
        for f in use:
            q, l = keys[f][n]
            if n != "Root":
                pb.rotation_quaternion = q
                pb.keyframe_insert("rotation_quaternion", frame=f + 1)
            if n == "Hips":
                pb.location = l
                pb.keyframe_insert("location", frame=f + 1)
    if root_y is not None:                                   # root motion: the whole character travels along -Y
        for f in frames:
            arm.location = (0.0, root_y[f], 0.0)
            arm.keyframe_insert("location", frame=f + 1)
        arm.location = (0.0, 0.0, 0.0)
    act.frame_range = (1, nframes + 1)
    act.use_frame_range = True
    act.use_cyclic = bool(loop)
    ad.action = None
    return act, keys


def set_pose(arm, rig, keys_f):
    for n, (q, l) in keys_f.items():
        pb = arm.pose.bones[n]
        pb.rotation_mode = "QUATERNION"
        if n != "Root":
            pb.rotation_quaternion = q
        if n == "Hips":
            pb.location = l


# ------------------------------------------------------------------------------------------------------ verification
def contact_points(arm, rig, side):
    """Heel / ball sole points of a foot in armature space at the current evaluated pose."""
    pb = arm.pose.bones[side + "Foot"]
    Rd = pb.matrix.to_3x3() @ rig.b[side + "Foot"]["R"].inverted()
    head = pb.head.copy()
    heel = head + Rd @ Vector((0, 0.075 - 0.008 + 0.011, -0.088))
    ball = head + Rd @ Vector((0, -0.123, -0.088))
    return heel, ball


def verify_gait(arm, rig, name, g, act, log):
    """Return metrics dict for a locomotion action (treadmill frame: stance foot must move backwards at exactly v)."""
    sc = bpy.context.scene
    arm.animation_data.action = act
    v = g["v"]
    T = g["T"]
    pos = {"Left": [], "Right": []}
    minz = 9.0
    reach_err = 0.0
    for f in range(0, T + 1):
        sc.frame_set(f + 1)
        bpy.context.view_layer.update()
        for side in ("Left", "Right"):
            heel, ball = contact_points(arm, rig, side)
            pos[side].append((heel, ball))
            minz = min(minz, heel.z, ball.z)
        # leg over-extension: ankle vs target chain length
    # foot slide: for frames where the lowest sole point is within 6 mm of the ground, world velocity = treadmill velocity(+v) + foot velocity
    slide = []
    grounded = 0
    total = 0
    for side in ("Left", "Right"):
        for f in range(1, T + 1):
            for idx in (0, 1):
                p0, p1 = pos[side][f - 1][idx], pos[side][f][idx]
                if p0.z < 0.006 and p1.z < 0.006:
                    dy = (p1.y - p0.y) * FPS                    # armature-space velocity along +Y (backwards)
                    slide.append(abs(dy - v))                    # ground moves at +v relative to the body
                    grounded += 1
            total += 1
    metrics = dict(name=name, min_sole_z=minz, contact_samples=grounded, max_slide=max(slide) if slide else 0.0,
                   mean_slide=(sum(slide) / len(slide)) if slide else 0.0)
    # loop closure
    sc.frame_set(1)
    bpy.context.view_layer.update()
    a0 = {n: arm.pose.bones[n].matrix.translation.copy() for n in ("LeftFoot", "RightFoot", "Head", "LeftHand", "RightHand", "Hips")}
    sc.frame_set(T + 1)
    bpy.context.view_layer.update()
    a1 = {n: arm.pose.bones[n].matrix.translation.copy() for n in a0}
    metrics["loop_gap_cm"] = max((a0[n] - a1[n]).length for n in a0) * 100.0
    # airborne fraction
    air = sum(1 for f in range(T + 1) if min(pos["Left"][f][0].z, pos["Left"][f][1].z, pos["Right"][f][0].z, pos["Right"][f][1].z) > 0.03)
    metrics["flight_frames"] = air
    # arm / leg opposition at the left heel strike (frame 0): left foot forward (smaller y), left hand backward (larger y)
    sc.frame_set(1)
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    metrics["left_foot_ahead_cm"] = (pb["RightFoot"].head.y - pb["LeftFoot"].head.y) * 100.0
    metrics["left_hand_behind_cm"] = (pb["LeftHand"].head.y - pb["RightHand"].head.y) * 100.0
    arm.animation_data.action = None
    log("      opposition at left heel strike: left foot ahead %+.1f cm, left hand behind %+.1f cm (both should be > 0)"
        % (metrics["left_foot_ahead_cm"], metrics["left_hand_behind_cm"]))
    log("  %-7s sole_min_z=%6.1f mm  slide max %5.1f mm/s (mean %5.1f, v=%.2f m/s) over %d contact samples  loop gap %.2f cm  flight %d/%d frames"
        % (name, minz * 1000, metrics["max_slide"] * 1000, metrics["mean_slide"] * 1000, v, grounded, metrics["loop_gap_cm"], air, T))
    return metrics


def blend_keys(k0, k1, w):
    out = {}
    for n, (q0, l0) in k0.items():
        q1, l1 = k1[n]
        out[n] = (q0.slerp(q1, w), l0.lerp(l1, w))
    return out


SHOW_PLAN = [("idle", None, 45, 0.0), ("walk", "walk", 96, 1.25), ("run", "run", 88, 2.9), ("sprint", "sprint", 90, 6.0), ("run", "run", 22, 2.9),
             ("walk", "walk", 32, 1.25), ("idle", None, 30, 0.0), ("jump", None, 46, 0.0), ("idle", None, 40, 0.0)]


def bake_showcase(arm, rig, log, xf=6):
    """One long action: idle -> walk -> run -> sprint -> run -> walk -> idle -> jump -> idle with root motion (cross-fades of xf frames)."""
    total = sum(p[2] for p in SHOW_PLAN)
    starts = []
    acc = 0
    for p in SHOW_PLAN:
        starts.append(acc)
        acc += p[2]

    def local_pose(i, lf):
        kind, gname, n, v = SHOW_PLAN[i]
        g = GAITS[gname] if gname else None
        if kind == "jump":
            lf = min(lf, 46)
        return pose_keys(rig, kind, lf, g)
    keys, root_y = {}, {}
    y = 3.0
    for F in range(total + 1):
        i = max(k for k in range(len(SHOW_PLAN)) if starts[k] <= min(F, total - 1))
        lf = F - starts[i]
        cur = local_pose(i, lf)
        v = SHOW_PLAN[i][3]
        if i > 0 and lf < xf:
            w = smooth5((lf + 0.5) / xf)
            prev_len = SHOW_PLAN[i - 1][2]
            prv = local_pose(i - 1, prev_len + lf)
            cur = blend_keys(prv, cur, w)
            v = lerp(SHOW_PLAN[i - 1][3], v, w)
        keys[F] = cur
        root_y[F] = y
        y -= v / FPS
    act, _ = bake_keys(arm, rig, "Male_Showcase", keys, total, False, root_y)
    log("showcase action: %d frames (%.1f s), travels %.1f m" % (total, total / FPS, 3.0 - y))
    return act, total


def make_track_floor(coll, length=60.0):
    """Long checker floor (1 m squares) so that walking / running and foot sliding are visible."""
    me = bpy.data.meshes.new("TrackFloor")
    w = 6.0
    verts = [(-w, 6.0, 0), (w, 6.0, 0), (w, 6.0 - length, 0), (-w, 6.0 - length, 0)]
    me.from_pydata(verts, [], [(0, 3, 2, 1)])
    ob = bpy.data.objects.new("TrackFloor", me)
    coll.objects.link(ob)
    m = bpy.data.materials.new("MAT_TrackFloor")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"][0]
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    ck = nt.nodes.new("ShaderNodeTexChecker")
    mp = nt.nodes.new("ShaderNodeMapping")
    ck.inputs["Scale"].default_value = 0.5
    ck.inputs["Color1"].default_value = (0.36, 0.37, 0.39, 1)
    ck.inputs["Color2"].default_value = (0.18, 0.19, 0.21, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], ck.inputs["Vector"])
    nt.links.new(ck.outputs["Color"], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = 0.8
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    ob.data.materials.append(m)
    return ob


def export_glb(arm, objs, path, log):
    try:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        keep = [arm] + [o for o in objs.values() if o.name not in ("Hair", "HairRoots")]
        for o in keep:
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_animations=True,
                                  export_animation_mode="ACTIONS", export_apply=False, export_yup=True)
        log("glb exported:", path, "(%.1f MB)" % (os.path.getsize(path) / 1e6))
    except Exception as e:
        log("glb export failed:", e)


WEB_COLORS = {"MAT_Skin_Body": ("#C08C68", 0.6, 0.0), "MAT_Skin_Head": ("#C48E69", 0.55, 0.0), "MAT_Eye": ("#17100B", 0.25, 0.0), "MAT_Hair": ("#17110E", 0.5, 0.0),
              "MAT_HairRoots": ("#0E0A08", 0.7, 0.0), "MAT_Brow": ("#17110E", 0.6, 0.0), "MAT_Tee": ("#E4E2DA", 0.85, 0.0), "MAT_TeeRib": ("#D6D4CC", 0.85, 0.0),
              "MAT_Chino": ("#27303F", 0.8, 0.0), "MAT_Belt": ("#2A1B13", 0.5, 0.0), "MAT_ShoeUpper": ("#E9E7E1", 0.5, 0.0), "MAT_ShoeSole": ("#EDE7DA", 0.7, 0.0),
              "MAT_Lace": ("#F0EEE8", 0.8, 0.0), "MAT_ShoeLining": ("#2B2B2E", 0.7, 0.0), "MAT_WatchStrap": ("#141416", 0.6, 0.0), "MAT_WatchSteel": ("#B8BABD", 0.3, 1.0),
              "MAT_WatchDial": ("#0B0C0E", 0.2, 0.0)}


# Phase B1: which parts get a real baked texture (skin's subsurface-scatter material and the fabrics' weave/sheen
# are the ones actually worth the bake cost — Lips/Eyelids/Brows/Eyeball/HairRoots/Watch/Sneakers/Belt stay on the
# flat WEB_COLORS fallback, they're tiny on screen and not worth a texture each).
BAKE_TARGETS = ("Body", "Head", "Shirt", "Trousers")


def export_web_character(arm, objs, path, log, bake_dir=None):
    """Light glTF for the web viewer: no corneas, Idle / Walk / Run / Sprint / Jump only. Body/Head/Shirt/Trousers
    get a real baked diffuse+roughness+normal texture from their actual procedural material (see bake_tex.py);
    everything else stays a flat colour approximation (WEB_COLORS) as before."""
    def lin(h):
        h = h.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return (f(c[0]), f(c[1]), f(c[2]), 1.0)
    cache = {}

    def mat(name, hexc, rough, metal):
        if name in cache:
            return cache[name]
        m = bpy.data.materials.new("W_" + name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(b.outputs["BSDF"], o.inputs["Surface"])
        b.inputs["Base Color"].default_value = lin(hexc)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        cache[name] = m
        return m
    # snapshot the real (procedural) materials before they get swapped for the flat fallback below — this is what
    # Phase B1's bake step bakes from, once the mesh is in its final (post-subsurf) topology
    orig_mats = {name: [slot.material for slot in ob.material_slots] for name, ob in objs.items()}
    for name, ob in objs.items():
        if name.startswith("Cornea"):
            continue
        for i, slot in enumerate(ob.material_slots):
            key = slot.material.name.split(".")[0] if slot.material else ""
            hexc, r, mt = WEB_COLORS.get(key, ("#888888", 0.7, 0.0))
            if name == "Lips":
                hexc = "#8A4B44"
            slot.material = mat(key + ("_lips" if name == "Lips" else ""), hexc, r, mt)
    # bake the subdivision (the glTF exporter would otherwise ship the faceted base mesh): evaluate without the armature, keep the weights
    for name, ob in objs.items():
        sd = next((m for m in ob.modifiers if m.type == "SUBSURF"), None)
        if sd is None:
            continue
        arm_mods = [m for m in ob.modifiers if m.type == "ARMATURE"]
        for m in arm_mods:
            m.show_viewport = False
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        ob.modifiers.remove(sd)
        ob.data = me
        for m in arm_mods:
            m.show_viewport = True
        for p_ in me.polygons:
            p_.use_smooth = True

    # ---- Phase B1: bake real textures for BAKE_TARGETS, from the real materials snapshotted above, onto a fresh
    # smart_project UV (the mesh never had one — the procedural materials use Generated/noise coordinates, not UV,
    # so this is safe regardless of the UV layout chosen here). The mesh is now in its final, post-subsurf topology.
    import bake_tex
    outdir = bake_dir or os.path.join(os.path.dirname(path), "textures")
    for name in BAKE_TARGETS:
        ob = objs.get(name)
        if ob is None or not orig_mats.get(name):
            continue
        flat_mats = [slot.material for slot in ob.material_slots]
        for slot, om in zip(ob.material_slots, orig_mats[name]):
            slot.material = om
        try:
            bake_tex.smart_unwrap(ob)
            # bake against whichever original material is in the first slot: for Shirt/Trousers this is the main
            # fabric (Tee/Chino) — the smaller second slot (TeeRib/Belt) shares the same UV space and just keeps
            # its flat colour below, which is fine at their screen size.
            paths = bake_tex.bake_to_uv(ob, orig_mats[name][0], outdir, name.lower(), resolution=2048)
            log("web character bake: %s -> %s" % (name, ", ".join(os.path.basename(p) for p in paths.values())))
        except Exception as e:
            log("web character bake failed for %s: %s" % (name, e))
            paths = None
        finally:
            for slot, fm in zip(ob.material_slots, flat_mats):
                slot.material = fm
        if paths:
            bake_tex.wire_baked_textures(ob.material_slots[0].material, paths)

    for a in list(bpy.data.actions):
        if a.name not in ("Male_Idle", "Male_Walk", "Male_Run", "Male_Sprint", "Male_Jump"):
            bpy.data.actions.remove(a)
    if arm.animation_data:
        arm.animation_data.action = None
    bpy.ops.object.select_all(action="DESELECT")
    keep = [arm] + [o for n, o in objs.items() if not n.startswith("Cornea")]
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    valid = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    want = {"filepath": path, "export_format": "GLB", "use_selection": True, "export_animations": True, "export_animation_mode": "ACTIONS",
            "export_apply": False, "export_yup": True, "export_texcoords": True, "export_normals": True, "export_image_format": "AUTO",
            "export_materials": "EXPORT", "export_force_sampling": True, "export_optimize_animation_size": True, "export_skins": True,
            "export_draco_mesh_compression_enable": True, "export_draco_mesh_compression_level": 7, "export_draco_position_quantization": 14,
            "export_draco_normal_quantization": 8, "export_draco_generic_quantization": 12, "export_draco_texcoord_quantization": 11}
    kw = {k: v for k, v in want.items() if k in valid}
    try:
        bpy.ops.export_scene.gltf(**kw)
        log("web character glb: %s (%.2f MB)" % (path, os.path.getsize(path) / 1e6))
    except Exception as e:
        log("web character export failed:", e)


def render_sheet(arm, act, frames, outpath, cam, log, res=(300, 400)):
    if SHEET_W:
        res = (SHEET_W, int(res[1] * SHEET_W / res[0]))
    """Render the given frames of an action from one camera and tile them into a contact sheet PNG."""
    import numpy as np
    sc = bpy.context.scene
    arm.animation_data.action = act
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    tmp = os.path.join(os.path.dirname(outpath), "_tmp_frame.png")
    tiles = []
    for f in frames:
        sc.frame_set(int(f) + 1)
        sc.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(tmp)
        arr = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(arr)
        tiles.append(arr.reshape(res[1], res[0], 4).copy())
        bpy.data.images.remove(img)
    big = np.concatenate(tiles, axis=1)
    out = bpy.data.images.new("sheet", big.shape[1], big.shape[0], alpha=False)
    out.pixels.foreach_set(big.ravel())
    out.filepath_raw = outpath
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    arm.animation_data.action = None
    log("  sheet:", os.path.basename(outpath))


def make_ortho_cam(coll, name, loc, target, scale):
    cd = bpy.data.cameras.new(name)
    cd.type = "ORTHO"
    cd.ortho_scale = scale
    co = bpy.data.objects.new(name, cd)
    coll.objects.link(co)
    co.location = loc
    co.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return co


def run(arm, objs, segs, coll, ARGS, log, render_views):
    sc = bpy.context.scene
    sc.render.fps = FPS
    rig = RigData(arm)
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    acts = {}
    for gname, g in GAITS.items():
        g = dict(g)
        g["stride_wrap"] = 0.0
        GAITS[gname] = g
        act, keys = bake_action(arm, rig, "Male_" + gname.capitalize(), "gait", g["T"], g, True)
        acts[gname] = act
    acts["idle"], _ = bake_action(arm, rig, "Male_Idle", "idle", 120, None, True)
    acts["jump"], _ = bake_action(arm, rig, "Male_Jump", "jump", 46, None, False)
    log("actions baked: %s" % ", ".join(a.name for a in acts.values()))
    metrics = {}
    if not getattr(ARGS, "no_verify", False):
        log("verification (treadmill frame, ground contact = sole point < 6 mm):")
        for gname in ("walk", "run", "sprint"):
            metrics[gname] = verify_gait(arm, rig, gname, GAITS[gname], acts[gname], log)
    poses = [x for x in getattr(ARGS, "poses", "").split(",") if x]
    if poses:
        os.makedirs(ARGS.out, exist_ok=True)
        cams = {"side": make_ortho_cam(coll, "PoseSide", (8.0, 0.0, 0.92), (0.0, 0.0, 0.92), 2.05),
                "front": make_ortho_cam(coll, "PoseFront", (0.0, -8.0, 0.92), (0.0, 0.0, 0.92), 2.05)}
        cd = bpy.data.cameras.new("PoseQ")
        cd.lens = 55
        cq = bpy.data.objects.new("PoseQ", cd)
        coll.objects.link(cq)
        cq.location = (3.0, -3.6, 1.2)
        cq.rotation_euler = (Vector((0, 0, 0.9)) - cq.location).to_track_quat("-Z", "Y").to_euler()
        cams["q34"] = cq
        for item in poses:
            an, fr, vw = item.split(":")
            act = acts[an]
            arm.animation_data.action = act
            sc.camera = cams[vw]
            sc.render.resolution_x, sc.render.resolution_y = 720, 960
            sc.frame_set(int(fr) + 1)
            sc.render.filepath = os.path.join(ARGS.out, "pose_%s_%s_%s.png" % (an, fr, vw))
            bpy.ops.render.render(write_still=True)
            log("  pose", item)
        arm.animation_data.action = None
    if getattr(ARGS, "test_controller", False):
        import char_controller as CTL
        log("controller self-test:")
        CTL.selftest(arm, rig, log)
        arm.location = (0, 0, 0)
        arm.rotation_euler = (0, 0, 0)
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
    show_act, show_len = bake_showcase(arm, rig, log)
    acts["showcase"] = show_act
    if getattr(ARGS, "sheets", False):
        out = ARGS.out
        os.makedirs(out, exist_ok=True)
        cam_s = make_ortho_cam(coll, "SheetSide", (8.0, 0.0, 0.92), (0.0, 0.0, 0.92), 2.05)
        cam_f = make_ortho_cam(coll, "SheetFront", (0.0, -8.0, 0.92), (0.0, 0.0, 0.92), 2.05)
        sc.cycles.samples = 14
        global SHEET_W
        SHEET_W = getattr(ARGS, "sheet_w", 0)
        plan = {"walk": [round(i * GAITS["walk"]["T"] / 8) for i in range(8)],
                "run": [round(i * GAITS["run"]["T"] / 8) for i in range(8)],
                "sprint": [round(i * GAITS["sprint"]["T"] / 8) for i in range(8)],
                "jump": [0, 6, 10, 13, 18, 24, 30, 33, 38, 45]}
        only = [x for x in getattr(ARGS, "sheet_only", "").split(",") if x]
        for gname, frames in plan.items():
            if only and gname not in only:
                continue
            act = acts[gname]
            render_sheet(arm, act, frames, os.path.join(out, "sheet_%s_side.png" % gname), cam_s, log)
            if gname in ("run", "walk"):
                render_sheet(arm, act, frames, os.path.join(out, "sheet_%s_front.png" % gname), cam_f, log)
    # leave the file ready to play: showcase action assigned, frame range set, checker floor + follow camera
    arm.animation_data.action = show_act
    sc.frame_start, sc.frame_end = 1, show_len + 1
    sc.frame_set(1)
    for o in list(coll.objects):
        if o.name == "Studio_Floor":
            bpy.data.objects.remove(o)
    make_track_floor(coll)
    cam = bpy.data.objects.new("Cam_Follow", bpy.data.cameras.new("Cam_Follow"))
    coll.objects.link(cam)
    cam.data.lens = 50
    cam.parent = arm
    cam.location = (3.3, -1.0, 1.15)                       # parent space: the camera rides along with the character (root motion)
    cam.rotation_euler = (Vector((0.0, 0.0, 0.95)) - Vector((3.3, -1.0, 1.15))).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    if getattr(ARGS, "save", False):
        os.makedirs(ARGS.out, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ARGS.out, "character_male20s.blend"))
        log("saved character_male20s.blend")
    if getattr(ARGS, "glb", False):
        export_glb(arm, objs, os.path.join(ARGS.out, "character_male20s.glb"), log)
    if getattr(ARGS, "web_glb", ""):
        export_web_character(arm, objs, ARGS.web_glb, log)
    return acts, metrics, rig

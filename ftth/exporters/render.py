"""Presentation rendering for the construction drawings: elevations that read like an architect's rendered
elevation (wall materials, framed windows with sky reflections, panelled doors, shade under roofs, a sky, the
ground, trees and people for scale) and furniture on the plans (beds, desks, WCs...), so a planner and a client
can read the building at a glance. Everything is drawn from the building model with ReportLab vector graphics."""
from __future__ import annotations

import math
import random

from reportlab.lib import colors

from .. import building as B

C = colors.HexColor
WALL_FILL = {"block": C("#efe8dc"), "brick": C("#b8694c"), "stone": C("#cbbfa9"), "concrete": C("#d3d2cc")}
SKY_TOP, SKY_LOW = C("#9fc3e6"), C("#eef4f9")
GLASS_TOP, GLASS_LOW = C("#c9def0"), C("#4f7591")
FRAME, WOOD, WOOD_DARK = C("#3a3f44"), C("#8a5a33"), C("#6b4426")
GRASS, GRASS_DARK = C("#8db063"), C("#6e8f48")
LEAF = [C("#5f8f3e"), C("#4f7f35"), C("#76a24a")]
INK = C("#2b2f33")


def _rect(cv, x0, y0, x1, y1, fill=None, stroke=None, width=0.5, alpha=1.0):
    cv.saveState()
    if fill is not None:
        cv.setFillColor(fill)
        cv.setFillAlpha(alpha)
    if stroke is not None:
        cv.setStrokeColor(stroke)
        cv.setLineWidth(width)
    cv.rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), stroke=1 if stroke is not None else 0,
            fill=1 if fill is not None else 0)
    cv.restoreState()


def _vgrad(cv, x0, y0, x1, y1, top, low):
    """A rectangle shaded from `low` at the bottom to `top` at the top."""
    cv.saveState()
    p = cv.beginPath()
    p.rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    cv.clipPath(p, stroke=0, fill=0)
    cv.linearGradient(0, min(y0, y1), 0, max(y0, y1), (low, top), extend=False)
    cv.restoreState()


def _mix(c1, c2, t):
    return colors.Color(c1.red + (c2.red - c1.red) * t, c1.green + (c2.green - c1.green) * t,
                        c1.blue + (c2.blue - c1.blue) * t)


# ---------------------------------------------------------------------------------------------------------
# elevations
# ---------------------------------------------------------------------------------------------------------
def wall_texture(cv, mat, x0, y0, x1, y1, k):
    """Coursing on a wall: brick courses, stone blocks, concrete panels; render stays plain (k: points per m)."""
    cv.saveState()
    p = cv.beginPath()
    p.rect(x0, y0, x1 - x0, y1 - y0)
    cv.clipPath(p, stroke=0, fill=0)
    if mat == "brick" and k > 3:
        cv.setStrokeColor(C("#e7d3c4"))
        cv.setLineWidth(0.15)
        step = 0.3 * k  # every 4 courses (300 mm): reads as brick without filling the sheet with lines
        y = y0
        while y < y1:
            cv.line(x0, y, x1, y)
            y += step
    elif mat == "stone" and k > 2:
        rng = random.Random(int(x0 * 7 + y0 * 13))
        cv.setStrokeColor(C("#9d927e"))
        cv.setLineWidth(0.25)
        y = y0
        while y < y1:
            h = (0.35 + rng.random() * 0.25) * k
            cv.line(x0, y, x1, y)
            x = x0 + rng.random() * 0.6 * k
            while x < x1:
                cv.line(x, y, x, min(y1, y + h))
                x += (0.6 + rng.random() * 0.5) * k
            y += h
    elif mat == "concrete" and k > 2:
        cv.setStrokeColor(C("#b5b4ad"))
        cv.setLineWidth(0.2)
        x = x0
        while x < x1:
            cv.line(x, y0, x, y1)
            x += 2.4 * k
        y = y0
        while y < y1:
            cv.line(x0, y, x1, y)
            y += 1.2 * k
    cv.restoreState()


def window(cv, x0, z0, x1, z1, k):
    """A framed window: sky reflected in the glass, glazing bars, a transom on tall ones, and its sill."""
    _vgrad(cv, x0, z0, x1, z1, GLASS_TOP, GLASS_LOW)
    cv.saveState()  # a diagonal sheen across the glass
    p = cv.beginPath()
    p.rect(x0, z0, x1 - x0, z1 - z0)
    cv.clipPath(p, stroke=0, fill=0)
    cv.setFillColor(colors.white)
    cv.setFillAlpha(0.18)
    w = x1 - x0
    sh = cv.beginPath()
    sh.moveTo(x0 + w * 0.15, z0)
    sh.lineTo(x0 + w * 0.45, z0)
    sh.lineTo(x0 + w * 0.85, z1)
    sh.lineTo(x0 + w * 0.55, z1)
    sh.close()
    cv.drawPath(sh, stroke=0, fill=1)
    cv.restoreState()
    f = max(0.6, 0.05 * k)
    cv.saveState()
    cv.setStrokeColor(FRAME)
    cv.setLineWidth(f)
    cv.rect(x0, z0, x1 - x0, z1 - z0, stroke=1, fill=0)
    panes = max(1, round((x1 - x0) / (0.8 * k)))
    cv.setLineWidth(f * 0.6)
    for i in range(1, panes):
        x = x0 + (x1 - x0) * i / panes
        cv.line(x, z0, x, z1)
    if (z1 - z0) > 1.4 * k:
        zt = z1 - min(0.5 * k, (z1 - z0) * 0.3)
        cv.line(x0, zt, x1, zt)
    cv.restoreState()
    _rect(cv, x0 - 0.05 * k, z0 - 0.06 * k, x1 + 0.05 * k, z0, fill=C("#e3dfd6"), stroke=INK, width=0.3)


def door(cv, x0, z0, x1, z1, style, k):
    """A door: frame, one or two leaves with panels (glazed when sliding), and handles."""
    _rect(cv, x0, z0, x1, z1, fill=FRAME)
    f = 0.06 * k
    leaves = 2 if style in ("double", "sliding") else 1
    lw = (x1 - x0 - 2 * f) / leaves
    for i in range(leaves):
        a0, a1 = x0 + f + i * lw + (0.3 if leaves > 1 else 0), x0 + f + (i + 1) * lw - (0.3 if leaves > 1 else 0)
        if style == "sliding":
            _vgrad(cv, a0, z0, a1, z1 - f, GLASS_TOP, GLASS_LOW)
        else:
            _rect(cv, a0, z0, a1, z1 - f, fill=WOOD)
            for pz0, pz1 in ((0.15, 0.45), (0.53, 0.88)):  # raised panels
                _rect(cv, a0 + 0.1 * k, z0 + (z1 - z0) * pz0, a1 - 0.1 * k, z0 + (z1 - z0) * pz1, fill=WOOD_DARK,
                      stroke=C("#4e3018"), width=0.2, alpha=0.55)
        hx = (a1 - 0.08 * k) if (leaves == 1 or i == 0) else (a0 + 0.08 * k)
        _rect(cv, hx - 0.02 * k, z0 + 1.0 * k, hx + 0.02 * k, z0 + 1.08 * k, fill=C("#d6d9dc"))
    if style == "arched":
        cv.saveState()
        cv.setFillColor(FRAME)
        cv.wedge(x0, z1 - (x1 - x0) / 2, x1, z1 + (x1 - x0) / 2, 0, 180, stroke=0, fill=1)
        cv.restoreState()


def sky_and_ground(cv, x0, y0, x1, y1, ground_y):
    """The sky behind the building, shaded to a pale horizon, and a band of grass below the ground line."""
    _vgrad(cv, x0, ground_y, x1, y1, SKY_TOP, SKY_LOW)
    _vgrad(cv, x0, y0, x1, ground_y, GRASS, GRASS_DARK)
    rng = random.Random(3)  # a few soft clouds
    cv.saveState()
    cv.setFillColor(colors.white)
    cv.setFillAlpha(0.55)
    for _ in range(3):
        cx, cy, r = x0 + rng.random() * (x1 - x0), ground_y + (y1 - ground_y) * (0.65 + rng.random() * 0.3), 8 + rng.random() * 10
        for dx, dy, rr in ((0, 0, 1), (0.9, 0.2, 0.8), (-0.9, 0.1, 0.75), (0.3, 0.5, 0.7)):
            cv.circle(cx + dx * r, cy + dy * r * 0.6, r * rr, stroke=0, fill=1)
    cv.restoreState()


def tree(cv, x, ground, k, height=6.0, seed=0, alpha=1.0):
    """An elevation tree: a trunk and a crown of overlapping leafy clumps, with shade on one side."""
    rng = random.Random(seed)
    h = height * k
    crown = h * 0.32
    cv.saveState()
    cv.setFillAlpha(alpha)
    cv.setFillColor(C("#5b4330"))
    tw = max(1.2, 0.18 * k)
    p = cv.beginPath()
    p.moveTo(x - tw, ground)
    p.lineTo(x + tw, ground)
    p.lineTo(x + tw * 0.6, ground + h * 0.55)
    p.lineTo(x - tw * 0.6, ground + h * 0.55)
    p.close()
    cv.drawPath(p, stroke=0, fill=1)
    cy = ground + h - crown
    clumps = [(0, 0, 1.0)] + [(math.cos(a) * 0.55, math.sin(a) * 0.45, 0.6 + rng.random() * 0.25)
                              for a in (rng.random() * 6.28 for _ in range(6))]
    for dx, dy, r in clumps:  # shade first (offset), then the leaves, then a highlight
        cv.setFillColor(C("#3d6a2b"))
        cv.circle(x + dx * crown + crown * 0.12, cy + dy * crown - crown * 0.08, crown * r, stroke=0, fill=1)
    for i, (dx, dy, r) in enumerate(clumps):
        cv.setFillColor(LEAF[i % 3])
        cv.circle(x + dx * crown, cy + dy * crown, crown * r * 0.92, stroke=0, fill=1)
    cv.setFillColor(C("#a3c977"))
    cv.setFillAlpha(alpha * 0.5)
    cv.circle(x - crown * 0.3, cy + crown * 0.35, crown * 0.35, stroke=0, fill=1)
    cv.restoreState()


def person(cv, x, ground, k, seed=0):
    """A scale figure 1.75 m tall, in a muted tone so it does not compete with the building."""
    rng = random.Random(seed)
    h = (1.6 + rng.random() * 0.2) * k
    cv.saveState()
    cv.setFillColor(C("#5d6874"))
    cv.setFillAlpha(0.8)
    cv.circle(x, ground + h * 0.93, h * 0.07, stroke=0, fill=1)
    p = cv.beginPath()  # body and legs
    w = h * 0.13
    p.moveTo(x - w, ground + h * 0.82)
    p.lineTo(x + w, ground + h * 0.82)
    p.lineTo(x + w * 0.8, ground + h * 0.45)
    p.lineTo(x + w * 0.55, ground)
    p.lineTo(x + w * 0.1, ground)
    p.lineTo(x, ground + h * 0.4)
    p.lineTo(x - w * 0.1, ground)
    p.lineTo(x - w * 0.55, ground)
    p.lineTo(x - w * 0.8, ground + h * 0.45)
    p.close()
    cv.drawPath(p, stroke=0, fill=1)
    cv.restoreState()


def roof_shade(cv, x0, x1, z, k, depth=0.45):
    """The shadow a roof edge, parapet coping or eaves throws on the wall below it: bands fading downwards
    (transparent fills; PDF gradients have no transparency)."""
    cv.saveState()
    cv.setFillColor(colors.black)
    steps = 6
    for i in range(steps):
        cv.setFillAlpha(0.16 * (1 - i / steps))
        h = depth * k / steps
        cv.rect(x0, z - (i + 1) * h, x1 - x0, h, stroke=0, fill=1)
    cv.restoreState()


def roof_texture(cv, pts, covering, k, sheet_vertical=True):
    """Sheets as vertical ribs, tiles as horizontal courses, clipped to the roof outline."""
    cv.saveState()
    p = cv.beginPath()
    for i, (x, y) in enumerate(pts):
        (p.moveTo if i == 0 else p.lineTo)(x, y)
    p.close()
    cv.clipPath(p, stroke=0, fill=0)
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    cv.setLineWidth(0.25)
    if covering == "tiles":
        cv.setStrokeColor(C("#5a2a1e"))
        y = min(ys)
        while y < max(ys):
            cv.line(min(xs), y, max(xs), y)
            y += max(1.5, 0.3 * k)
    elif covering == "iron sheets":
        cv.setStrokeColor(C("#46525d"))
        x = min(xs)
        while x < max(xs):
            cv.line(x, min(ys), x, max(ys))
            x += max(1.2, 0.19 * k)
    cv.restoreState()


# ---------------------------------------------------------------------------------------------------------
# furniture on the plans
# ---------------------------------------------------------------------------------------------------------
def _sides(r: B.Room):
    """The room's rectangle, inset from the wall centrelines, and which side its door is on."""
    x0, y0, x1, y1 = r.rect
    x0, y0, x1, y1 = x0 + 0.15, y0 + 0.15, x1 - 0.15, y1 - 0.15
    side = "s"
    if r.door:
        dx, dy = r.door
        d = {"s": abs(dy - (y0 - 0.15)), "n": abs(dy - (y1 + 0.15)), "w": abs(dx - (x0 - 0.15)), "e": abs(dx - (x1 + 0.15))}
        side = min(d, key=d.get)
    return x0, y0, x1, y1, side


def furniture(cv, r: B.Room, T, k):
    """Typical furniture for the room's use, against the wall away from its door, in thin grey lines."""
    if not r.rect or k < 2.5:
        return
    x0, y0, x1, y1, side = _sides(r)
    W, D = x1 - x0, y1 - y0
    # work in a frame where the door is at the bottom (v = 0) and the far wall at the top (v = depth)
    if side in ("s", "n"):
        L, Dp = W, D
        P = (lambda u, v: T(x0 + u, y0 + v)) if side == "s" else (lambda u, v: T(x1 - u, y1 - v))
    else:
        L, Dp = D, W
        P = (lambda u, v: T(x0 + v, y1 - u)) if side == "w" else (lambda u, v: T(x1 - v, y0 + u))

    def box(u0, v0, u1, v1, fill=None):
        pts = [P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1)]
        p = cv.beginPath()
        for i, q in enumerate(pts):
            (p.moveTo if i == 0 else p.lineTo)(*q)
        p.close()
        if fill is not None:
            cv.setFillColor(fill)
        cv.drawPath(p, stroke=1, fill=1 if fill is not None else 0)

    def circle(u, v, rad):
        cx, cy = P(u, v)
        cv.circle(cx, cy, rad * k, stroke=1, fill=0)

    cv.saveState()
    cv.setStrokeColor(C("#7b858f"))
    cv.setLineWidth(0.35)
    name = r.name
    if name in ("Ward", "Bedroom", "Apartment"):
        double = name != "Ward"
        bw, bl = (1.5 if double else 0.95), 2.0
        n = 1 if double else max(1, min(4, int((L - 0.3) // 1.6)))
        if Dp < bl + 1.0:
            n = 0
        gap = (L - n * bw) / (n + 1) if n else 0
        for i in range(n):  # beds with their heads to the far wall, a pillow and a bedside cabinet
            u = gap + i * (bw + gap)
            box(u, Dp - bl, u + bw, Dp, C("#f6f3ee"))
            box(u + 0.1, Dp - 0.45, u + bw - 0.1, Dp - 0.1, C("#e4e9ee"))
            if u + bw + 0.5 < L:
                box(u + bw + 0.05, Dp - 0.45, u + bw + 0.5, Dp)
    elif name in ("Office", "Staff room", "Nurse station", "Reception"):
        dw = min(L - 0.4, 2.4 if name in ("Nurse station", "Reception") else 1.4)
        u = (L - dw) / 2
        box(u, Dp - 0.75, u + dw, Dp - 0.05, C("#efe7da"))
        circle(L / 2, Dp - 1.15, 0.25)
        if name == "Reception" and Dp > 3:  # waiting chairs
            for i in range(int((L - 0.6) // 0.6)):
                box(0.3 + i * 0.6, 0.6, 0.8 + i * 0.6, 1.1)
    elif name == "Classroom":
        cols, rows = max(1, int((L - 0.6) // 1.4)), max(1, int((Dp - 2.2) // 1.2))
        for i in range(cols):
            for j in range(rows):
                box(0.4 + i * 1.4, 0.8 + j * 1.2, 1.6 + i * 1.4, 1.3 + j * 1.2)
        box(L / 2 - 0.7, Dp - 0.9, L / 2 + 0.7, Dp - 0.3, C("#efe7da"))
    elif name in ("Toilets", "Bathroom"):
        n = max(1, min(6, int((L - 0.2) // 1.0)))
        for i in range(n):  # cubicles along the far wall, a WC in each, basins by the door
            u = 0.1 + i * 1.0
            if name == "Toilets":
                cv.line(*P(u, Dp), *P(u, Dp - 1.5))
            cx, cy = P(u + 0.5, Dp - 0.45)
            cv.ellipse(cx - 0.2 * k, cy - 0.28 * k, cx + 0.2 * k, cy + 0.28 * k, stroke=1, fill=0)
            box(u + 0.3, Dp - 0.2, u + 0.7, Dp)
        if Dp > 2.5:
            for i in range(max(1, min(3, int(L // 1.2)))):
                circle(0.6 + i * 1.0, 0.35, 0.2)
    elif name == "Meeting room":
        cx, cy = P(L / 2, Dp / 2)
        cv.ellipse(cx - L * 0.3 * k, cy - Dp * 0.18 * k, cx + L * 0.3 * k, cy + Dp * 0.18 * k, stroke=1, fill=0)
    elif name in ("Kitchen", "Kitchenette"):
        box(0.1, Dp - 0.6, L - 0.1, Dp, C("#efe7da"))
        box(L / 2 - 0.4, Dp - 0.5, L / 2 + 0.4, Dp - 0.1)
    elif name == "Living room":
        box(L * 0.2, Dp - 0.95, L * 0.8, Dp - 0.1, C("#e9edf1"))
        box(L * 0.35, Dp - 2.1, L * 0.65, Dp - 1.4)
    elif name == "Lift and lobby":
        s = min(2.0, L - 0.3, Dp - 0.3)
        box((L - s) / 2, Dp - s, (L + s) / 2, Dp)
        cv.line(*P((L - s) / 2, Dp - s), *P((L + s) / 2, Dp))
        cv.line(*P((L + s) / 2, Dp - s), *P((L - s) / 2, Dp))
    elif name in ("Store", "Sluice room", "Plant room", "Refuse room"):
        box(0.05, Dp - 0.5, L - 0.05, Dp - 0.05)
        for i in range(1, 4):
            cv.line(*P(0.05, Dp - 0.5 + i * 0.11), *P(L - 0.05, Dp - 0.5 + i * 0.11))
    cv.restoreState()


def wet_floor(cv, r: B.Room, T, k):
    """300 mm floor tiles in wet rooms."""
    if not r.rect or r.name not in ("Toilets", "Bathroom", "Sluice room", "Kitchen", "Kitchenette") or k < 2.5:
        return
    x0, y0, x1, y1 = r.rect
    cv.saveState()
    cv.setStrokeColor(C("#c9d2db"))
    cv.setLineWidth(0.15)
    x = x0 + 0.3
    while x < x1:
        cv.line(*T(x, y0), *T(x, y1))
        x += 0.3
    y = y0 + 0.3
    while y < y1:
        cv.line(*T(x0, y), *T(x1, y))
        y += 0.3
    cv.restoreState()

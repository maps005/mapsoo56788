"""Geometry of the drafting layer shared by the PDF sheets and the DXF (the drawing tab has the same rules in
cad.js). Coordinates are in a plane with y up (PDF points or DXF metres)."""
from __future__ import annotations

import math


def arc3(a, b, c):
    """The circle arc from a through b to c: (cx, cy, r, start, end) with angles in degrees, counter-clockwise
    from start to end (as DXF arcs are); None when the three points are in a line."""
    (ax, ay), (bx, by), (cx_, cy_) = a, b, c
    d = 2 * (ax * (by - cy_) + bx * (cy_ - ay) + cx_ * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy_) + (bx * bx + by * by) * (cy_ - ay) + (cx_ * cx_ + cy_ * cy_) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx_ - bx) + (bx * bx + by * by) * (ax - cx_) + (cx_ * cx_ + cy_ * cy_) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ang = lambda x, y: math.degrees(math.atan2(y - uy, x - ux)) % 360  # noqa: E731
    sa, sb, sc = ang(ax, ay), ang(bx, by), ang(cx_, cy_)
    ccw = (sb - sa) % 360 < (sc - sa) % 360  # b lies on the counter-clockwise way from a to c
    return (ux, uy, r, sa, sc) if ccw else (ux, uy, r, sc, sa)


def arc_points(a, b, c, n=32):
    """Points along the arc a -> b -> c (the straight line when they are in a line)."""
    g = arc3(a, b, c)
    if g is None:
        return [a, c]
    ux, uy, r, s, e = g
    sweep = (e - s) % 360 or 360
    pts = [(ux + r * math.cos(math.radians(s + sweep * k / n)), uy + r * math.sin(math.radians(s + sweep * k / n)))
           for k in range(n + 1)]
    # keep the drawing direction a -> c
    return pts if math.hypot(pts[0][0] - a[0], pts[0][1] - a[1]) < math.hypot(pts[-1][0] - a[0], pts[-1][1] - a[1]) else pts[::-1]


def dimension(kind, P, off):
    """Lines and text of a dimension: (lines [(x1, y1, x2, y2)], (tx, ty), text angle (deg), value).
    off is the distance of the dimension line from the measured points (same units as P)."""
    if kind == "radius":
        (cx, cy), (ex, ey) = P
        r = math.hypot(ex - cx, ey - cy)
        a = math.atan2(ey - cy, ex - cx)
        return [(cx, cy, ex, ey)], ((cx + ex) / 2 - math.sin(a) * off * 0.4, (cy + ey) / 2 + math.cos(a) * off * 0.4), \
            _upright(math.degrees(a)), r
    if kind == "angular":
        (ax, ay), (vx, vy), (bx, by) = P
        a1, a2 = math.atan2(ay - vy, ax - vx), math.atan2(by - vy, bx - vx)
        sweep = (a2 - a1) % (2 * math.pi)
        if sweep > math.pi:  # the smaller angle
            a1, a2, sweep = a2, a1, 2 * math.pi - sweep
        rr = min(math.hypot(ax - vx, ay - vy), math.hypot(bx - vx, by - vy)) * 0.6 or off
        pts = [(vx + rr * math.cos(a1 + sweep * k / 16), vy + rr * math.sin(a1 + sweep * k / 16)) for k in range(17)]
        mid = a1 + sweep / 2
        return [(p[0], p[1], q[0], q[1]) for p, q in zip(pts, pts[1:])], \
            (vx + (rr + off * 0.5) * math.cos(mid), vy + (rr + off * 0.5) * math.sin(mid)), \
            _upright(math.degrees(mid) - 90), math.degrees(sweep)
    (ax, ay), (bx, by) = P
    if kind == "horizontal":
        level = max(ay, by) + off
        d1, d2, value, ang = (ax, level), (bx, level), abs(bx - ax), 0.0
    elif kind == "vertical":
        level = max(ax, bx) + off
        d1, d2, value, ang = (level, ay), (level, by), abs(by - ay), 90.0
    else:  # aligned
        a = math.atan2(by - ay, bx - ax)
        nx, ny = -math.sin(a) * off, math.cos(a) * off
        d1, d2, value, ang = (ax + nx, ay + ny), (bx + nx, by + ny), math.hypot(bx - ax, by - ay), math.degrees(a)
    lines = [(ax, ay, d1[0], d1[1]), (bx, by, d2[0], d2[1]), (d1[0], d1[1], d2[0], d2[1])]
    t = math.radians(ang + 45)  # architectural ticks
    k = off * 0.25
    lines += [(x - k * math.cos(t), y - k * math.sin(t), x + k * math.cos(t), y + k * math.sin(t)) for x, y in (d1, d2)]
    na = math.radians(ang + 90)
    return lines, ((d1[0] + d2[0]) / 2 + math.cos(na) * off * 0.3, (d1[1] + d2[1]) / 2 + math.sin(na) * off * 0.3), \
        _upright(ang), value


def _upright(deg):
    """Text angle that never reads upside down."""
    deg = (deg + 180) % 360 - 180
    return deg + 180 if deg > 90 else deg - 180 if deg <= -90 else deg


def dim_label(m, value) -> str:
    if m.text:
        return m.text
    return f"{value:.1f}°" if m.dim == "angular" else (f"R{value:.1f} m" if m.dim == "radius" else f"{value:.1f} m")

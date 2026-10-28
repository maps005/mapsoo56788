"""Map label placement shared by the PDF sheets and the DXF drawing (the planner's drawing tab has the same
rules in overview.js labelPlacer).

Symbols, cable lines and placed labels are registered as boxes; a label tries the places around its point
(right, left, above, below, diagonals), then the same further out with a leader line, and takes the first free
place - or, if nothing is free, the least covered one. Coordinates have y growing upwards (PDF points, DXF metres).
"""
from __future__ import annotations

import math

DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def route_anchors(pts):
    """Where a cable's tag may go: its segment midpoints, from the middle of the route outwards."""
    mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:])]
    m = len(mids) // 2
    return [mids[i] for i in sorted(range(len(mids)), key=lambda i: abs(i - m))]


def stacked(placed: list, x, y, near, step):
    """Equipment at the same place (a closure and a JB on one pole): the next free spot below the point.
    The position is added to placed; the caller draws a leader from the true point when it moved."""
    while any(abs(x - px) < near and abs(y - py) < near for px, py in placed):
        y -= step
    placed.append((x, y))
    return x, y


class LabelPlacer:
    def __init__(self, cell: float, frame: tuple[float, float, float, float] | None = None, free: float = 1.0):
        """cell: grid size of the box index (a few label heights); frame: visible area (labels keep inside it);
        free: covered area still counted as free (a label just touching a cable line)."""
        self.cell, self.frame, self.free = cell, frame, free
        self.grid: dict[tuple[int, int], list] = {}

    def _cells(self, b):
        k = self.cell
        for i in range(int(b[0] // k), int(b[2] // k) + 1):
            for j in range(int(b[1] // k), int(b[3] // k) + 1):
                yield i, j

    def _add(self, b, weight=1.0):
        f = self.frame
        if f and (b[2] < f[0] or b[0] > f[2] or b[3] < f[1] or b[1] > f[3]):
            return  # outside the visible area
        entry = (b, weight)
        for c in self._cells(b):
            self.grid.setdefault(c, []).append(entry)

    def block(self, x, y, r):
        """A symbol of radius r at (x, y)."""
        self._add((x - r, y - r, x + r, y + r))

    def block_line(self, pts, step):
        """A cable: labels may cross it, but would rather not (lower weight than symbols and labels)."""
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(bx - ax, by - ay) // step))
            for t in range(n + 1):
                x, y = ax + (bx - ax) * t / n, ay + (by - ay) * t / n
                self._add((x - step / 4, y - step / 4, x + step / 4, y + step / 4), 0.3)

    def _cost(self, b):
        cost, seen = 0.0, set()
        for c in self._cells(b):
            for entry in self.grid.get(c, ()):
                if id(entry) in seen:
                    continue
                seen.add(id(entry))
                o, wt = entry
                ix, iy = min(b[2], o[2]) - max(b[0], o[0]), min(b[3], o[3]) - max(b[1], o[1])
                if ix > 0 and iy > 0:
                    cost += ix * iy * wt
        f = self.frame
        if f and (b[0] < f[0] or b[1] < f[1] or b[2] > f[2] or b[3] > f[3]):
            cost += (b[2] - b[0]) * (b[3] - b[1]) * 0.5  # partly outside the visible area
        return cost

    def inside(self, x, y) -> bool:
        f = self.frame
        return not f or (f[0] <= x <= f[2] and f[1] <= y <= f[3])

    def place(self, w, h, r, anchors, optional=False):
        """Place a w x h label for a symbol of radius r at the first free anchor (several anchors: along a cable).
        Returns (left, bottom, leader) where leader is (x1, y1, x2, y2) when the label sits away from its point;
        None for a point off the visible area, or for an optional label (pole, premise, drop) with no free place
        next to its point - in a crowded area those are left to the schedules rather than printed over others."""
        anchors = [a for a in anchors if self.inside(*a)]
        if not anchors:
            return None
        best = None
        for ring in range(2 if optional else 3):
            dist = r + h * 0.25 + ring * (h * 1.4)
            for ax, ay in anchors:
                for ux, uy in DIRS:
                    left = ax + dist * ux if ux > 0 else ax + dist * ux - w if ux < 0 else ax - w / 2
                    bottom = ay + dist * uy if uy > 0 else ay + dist * uy - h if uy < 0 else ay - h / 2
                    pad = h * 0.08
                    b = (left - pad, bottom - pad, left + w + pad, bottom + h + pad)
                    c = self._cost(b) + ring * 1e-6  # nearer wins a tie
                    if best is None or c < best[0]:
                        best = (c, left, bottom, b, ring, ax, ay)
                if best[0] < self.free:
                    break
            if best[0] < self.free:
                break
        if optional and best[0] >= self.free:
            return None
        _, left, bottom, b, ring, ax, ay = best
        self._add(b)
        leader = (ax, ay, min(max(ax, b[0]), b[2]), min(max(ay, b[1]), b[3])) if ring else None
        return left, bottom, leader

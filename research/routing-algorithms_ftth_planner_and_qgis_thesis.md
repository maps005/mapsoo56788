# Routing/topology references: ftth_planner and FTTH-Fiber-Optic-Network-Design-System

Source: code read of the clones in `reference/` on 2026-10-26. **Neither repo has a LICENSE file**, so re-implement the ideas below rather than copying code.

## ftth_planner (Cognizant proof of concept, Python; last commit 2022-10-12)
- Inputs: OSM roads and buildings for a bounding box (osmnx). Runs as a Streamlit UI.
- Steps covered: 3 (partial, matplotlib only), 4 (partial, flat rate list), 7 (partial, material and labour DataFrames). Steps 1, 2, 5, 6, 8, 9 and 10 are missing.
- **Trench graph** (`trenches.py:946-1160`): side-of-road trenches offset about 5 m, explicit road-crossing trenches, and each building snapped to its nearest trench with a spur.
- **Cabinet placement** (`fibers.py:352-400`): KMeansConstrained with size_max=48, then snapped to the nearest graph node (cKDTree).
- **Routing** (`fibers.py:480-528`): Dijkstra from each building to its cabinet. Used edges have their dig cost zeroed, which makes this a greedy "dig-once" Steiner approximation.
- Bugs: trench cost uses the crossing rate (`costs.py:~157`), install rate is never charged, and the dig-cost reset at `fibers.py:526` has no effect.

## FTTH-Fiber-Optic-Network-Design-System (2018 Czech thesis, QGIS 2 / Python 2, obsolete)
- Inputs: RÚIAN address and street SHP layers. Outputs: SHP plus a PDF/PNG map with a budget table.
- **Chamber placement** (`fonds.py:368-487`): greedy and capacity/distance-limited. It reuses a shaft on the same street, else the nearest free shaft, else creates a new one.
- **Topology choice**: Kruskal MST (minimum trench length; `graph.py:40-52`) or a Bellman-Ford shortest-path tree from the CO (`graph.py:105-127`).
- **Costing**: total length × Σ(excavation-type share × unit price) (`projectOutput.py:37-74`).

## What to take into our design
1. Dig-once weighted shortest paths for auto-suggested routes. On poles, use span cost instead of dig cost.
2. Capacity-constrained clustering of homes to FAT/serving points (for example, cap = FAT ports such as 8, 16 or 24).
3. Offer MST and shortest-path-tree as alternative auto-topologies, with the planner always able to edit.
4. Add what both lack: splitter ratios, cable sizing by downstream home count, core allocation, pole accessories, and exports.

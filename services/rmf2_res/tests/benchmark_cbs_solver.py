"""Benchmarks res_mapf's CBSAdapter/MAPFCoordinator directly — no HTTP, no AMQP —
by solving random non-overlapping, non-obstacle goals for increasing agent counts
on the warehouse map. Mirrors the goal-selection logic of POST /tasks/random
(rmf2_plan_server/api/v1/endpoints/tasks.py), minus the transport/db plumbing.

Run: uv run python tests/benchmark_cbs_solver.py
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from res_map import lif_parser
from res_map.grid.grid_utils import GridMap, infer_obstacles, snap_to_grid
from res_mapf_planning.mapf_solve.solvers.cbs_adapter import CBSAdapter
from res_mapf_planning.planning.mapf_coordinator import MAPFCoordinator
from res_mapf_planning.planning.multi_agent_context import MultiAgentContext
from res_plan_server.models.task import Task

WAREHOUSE_LIF = Path(__file__).resolve().parents[3] / "demos" / "warehouse" / "warehouse.lif.json"
AGENT_COUNTS = [1, 2, 5, 10, 15, 20, 25]
SEED = 42


def _reachable_node_names(grid_map: GridMap) -> list[str]:
    """Same source of truth as tasks.py's _reachable_node_names: nodes present in
    the grid that aren't an obstacle cell."""
    obstacles = set(grid_map.obstacles)
    return sorted(name for name, coord in grid_map.grid_nodes.items() if coord not in obstacles)


def _load_grid_map() -> GridMap:
    map_data = lif_parser.load_lif(str(WAREHOUSE_LIF))
    grid_map = snap_to_grid(map_data)
    grid_map.obstacles = infer_obstacles(map_data, grid_map)
    return grid_map


def _solve(agent_ids: list[str], starts: list[str], goals: list[str], grid_map: GridMap) -> float:
    """Builds a fresh context/coordinator and times a single coordinator.solve()
    call for the given agents. Doesn't check solver success — callers print that."""
    context = MultiAgentContext()
    for agent_id, start in zip(agent_ids, starts):
        context.initialise_agent(agent_id, start)

    coordinator = MAPFCoordinator(context, CBSAdapter(grid_map))
    tasks = [
        Task(task_id=f"t{i}", robot_id=agent_id, goal=goal)
        for i, (agent_id, goal) in enumerate(zip(agent_ids, goals))
    ]

    start_time = time.perf_counter()
    plans = coordinator.solve(
        new_tasks=tasks, committed_locations={}, stationary_agents=set(), obstacles=[]
    )
    elapsed = time.perf_counter() - start_time

    if not plans:
        print(f"  n={len(agent_ids):3d}: solver returned no plan (unexpected)")
    return elapsed


def _solve_random(grid_map: GridMap, node_names: list[str], n: int, rng: random.Random) -> float | None:
    """Random, usually-distant, disjoint start/goal pairs — the /tasks/random
    scenario. Returns None if skipped (not enough reachable nodes for n disjoint
    starts + n disjoint goals)."""
    if n * 2 > len(node_names):
        return None
    picks = rng.sample(node_names, k=n * 2)
    starts, goals = picks[:n], picks[n:]
    agent_ids = [f"bench/{i}" for i in range(n)]
    return _solve(agent_ids, starts, goals, grid_map)


def _reachable_coord_to_name(grid_map: GridMap) -> dict[tuple[int, int], str]:
    obstacles = set(grid_map.obstacles)
    return {coord: name for name, coord in grid_map.grid_nodes.items() if coord not in obstacles}


def _solve_shift_left(grid_map: GridMap, n: int, rng: random.Random) -> float | None:
    """Each agent's goal is exactly one grid cell to the left (x-1, same y) of its
    start — the shortest possible non-trivial move, same direction for everyone.
    A much smaller, much less conflict-prone problem than _solve_random's distant
    goals, to see how much of the solve cost is path length/conflict density
    rather than just per-agent solver overhead. Starts are unique by construction
    (built from a dict keyed by coordinate), and since a constant shift is
    injective, unique starts give unique goals too — no separate overlap check
    needed. Returns None if skipped (fewer than n cells have a left neighbour).
    """
    coord_to_name = _reachable_coord_to_name(grid_map)
    pairs = [
        (name, coord_to_name[(x - 1, y)])
        for (x, y), name in coord_to_name.items()
        if (x - 1, y) in coord_to_name
    ]
    if n > len(pairs):
        return None
    chosen = rng.sample(pairs, k=n)
    agent_ids = [f"bench/{i}" for i in range(n)]
    starts = [start for start, _ in chosen]
    goals = [goal for _, goal in chosen]
    return _solve(agent_ids, starts, goals, grid_map)


def main() -> None:
    grid_map = _load_grid_map()
    node_names = _reachable_node_names(grid_map)
    print(
        f"Loaded warehouse map: {len(grid_map.grid_nodes)} nodes, "
        f"{len(grid_map.obstacles)} obstacles, {len(node_names)} reachable"
    )

    print("\nScenario: each agent moves one waypoint to the left")
    rng = random.Random(SEED)
    for n in AGENT_COUNTS:
        elapsed = _solve_shift_left(grid_map, n, rng)
        if elapsed is None:
            print(f"n={n:3d} agents: skipped (not enough cells with a left neighbour)")
        else:
            print(f"n={n:3d} agents: {elapsed:8.3f}s")


if __name__ == "__main__":
    main()

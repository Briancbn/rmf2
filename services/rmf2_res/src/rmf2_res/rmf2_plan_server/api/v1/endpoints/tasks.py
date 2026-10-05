import fnmatch
import random
from collections import deque
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from res_mapf_planning.mapf_solve.exceptions import MapfSolverError
from res_mapf_planning.planning.mapf_coordinator import PlanningError
from res_mapf_planning.traffic_dependencies.models.plan import Plan
from res_mapf_planning.traffic_dependencies.models.plan_id import PlanId
from res_mapf_planning.traffic_dependencies.plan_generator import PlanGenerator
from res_plan_server.models.task import Task as PlanTask
from res_plan_server.task_status import TaskStatus, TaskStatusUpdate
from res_plan_server.transport.transport_messages import TaskRequestMsg

from rmf2_res import crud
from rmf2_res.models import TaskRecordStatus, TaskSubmitResponse
from rmf2_res.rmf2_plan_server.api.deps.context import ContextDeps
from rmf2_res.rmf2_plan_server.api.deps.db import DbSession

router = APIRouter()


@router.get("", response_model_exclude_none=True)
def get_task_statuses(db: DbSession, skip: int = 0, limit: int = 100) -> list[TaskRecordStatus]:
    records = crud.task_record.get_multi(db, skip=skip, limit=limit)
    return [TaskRecordStatus.model_validate(record) for record in records]


@router.get("/{task_id}", response_model_exclude_none=True)
def get_task_status(task_id: str, db: DbSession) -> TaskRecordStatus:
    record = crud.task_record.get(db, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRecordStatus.model_validate(record)


def _problem_key(tasks: list[TaskRequestMsg]) -> dict[str, str]:
    """Identifies the exact MAPF problem a batch of tasks poses — same robots
    wanting the same goals, regardless of task_id."""
    return {task.robot_id: task.goal for task in tasks}


def _blocked_goal_errors(tasks: list[TaskRequestMsg], context: ContextDeps) -> list[str]:
    """Rejects goals that coincide with a mapped obstacle cell before they reach
    the solver. res_mapf's low-level A* search is time-expanded with no time
    bound, so an unreachable (obstacle-blocked) goal state never gets added to
    open_set, open_set never empties, and the search hangs forever instead of
    failing — which would hang this endpoint (and block the whole process,
    since coordinator.solve() runs synchronously here).

    TODO: reaches into CBSAdapter's private _grid_map since nothing public
    exposes obstacle membership; should become a public API on CBSAdapter/
    MAPFCoordinator (res_mapf) instead.
    """
    if context.solver is None:
        return []
    grid_map = context.solver._grid_map
    errors = []
    for task in tasks:
        coord = grid_map.grid_nodes.get(task.goal)
        if coord is not None and coord in grid_map.obstacles:
            errors.append(f"Goal '{task.goal}' for robot {task.robot_id} is blocked by an obstacle")
    return errors


def _normalize_positions(plans: list[Plan]) -> None:
    for plan in plans:
        for waypoint in plan.waypoints:
            # res_mapf_planning's PlanGenerator builds position as a list even though
            # Waypoint.position is typed Tuple[float, float]; normalize it here so
            # pydantic's strict validation on TaskSubmitResponse.plans doesn't warn.
            waypoint.position = tuple(waypoint.position)


def _request_committed_locations(context: ContextDeps) -> tuple[dict, set] | str:
    """Returns ``(committed_locations, stationary_agents)`` on success, or an error string.

    TODO: _next_request_id/_wait_for_committed_locations/_parse_committed_locations
    are private on res_plan_server.PlanServer. Reusing them here avoids duplicating
    the request/response round trip, but this should become a public API on
    res_plan_server (or res_mapf_planning) instead of reaching into internals.
    """
    if context.plan_server is None:
        return "Plan server not started (no map configured)"
    request_id = context.plan_server._next_request_id()
    context.transport.publish_committed_locations_request(request_id)
    response = context.plan_server._wait_for_committed_locations(request_id, timeout=5.0)
    if response is None:
        return "Failed to retrieve committed locations from the executor."
    committed_locations = context.plan_server._parse_committed_locations(response.committed_locations)
    stationary_agents = set(response.stationary_agents)
    return committed_locations, stationary_agents


def _solve(
    context: ContextDeps,
    plan_tasks: list[PlanTask],
    plan_ids: dict[str, PlanId],
    committed_locations: dict,
    stationary_agents: set,
) -> tuple[dict[str, Plan], dict[str, int]] | None:
    """Returns ``(robot_to_plan, robot_to_final_waypoint)``, or ``None`` if the solver failed."""
    solver_plans = context.coordinator.solve(
        new_tasks=plan_tasks,
        committed_locations=committed_locations,
        stationary_agents=stationary_agents,
        obstacles=[],
    )
    if not solver_plans:
        return None

    plans = PlanGenerator().generate(solver_plans, plan_ids, committed_locations)
    _normalize_positions(plans)

    plan_id_to_robot = {plan_id: robot_id for robot_id, plan_id in plan_ids.items()}
    robot_to_plan = {plan_id_to_robot[plan.plan_id]: plan for plan in plans}

    robot_to_final_waypoint = {}
    for robot_id, plan in robot_to_plan.items():
        committed = committed_locations.get(robot_id)
        retained = committed.waypoint_index if committed else 0
        robot_to_final_waypoint[robot_id] = retained + len(plan.waypoints) - 1

    return robot_to_plan, robot_to_final_waypoint


@router.post("")
async def submit_tasks(
    tasks: list[TaskRequestMsg],
    context: ContextDeps,
    mode: Literal["dry_run", "plan", "submit"] = "dry_run",
) -> TaskSubmitResponse:
    """Compute or dispatch plans for a batch of tasks, depending on ``mode``:

    - ``"dry_run"`` (default): plan locally via the coordinator, using only the
      shared agent context's last-known state — no committed-locations round
      trip. Rejects if any robot has an ongoing plan, since a dry run assumes a
      static world snapshot and would otherwise silently ignore it; use
      ``"plan"`` instead (note that requesting committed locations can
      interrupt ongoing plans).
    - ``"plan"``: requests real committed locations from the executor and plans
      against them, so ongoing plans for other robots are properly accounted
      for. Still does not dispatch anything. The resulting plan is cached by
      the exact ``{robot_id: goal}`` problem it solved, so a follow-up
      ``"submit"`` for the same problem can dispatch it directly.
    - ``"submit"``: if a ``"plan"`` call already cached a plan for the exact
      same problem, dispatches that cached plan directly (skipping committed
      locations and solving entirely) and clears the cache entry. Otherwise
      blocks to plan the same way ``"plan"`` does, then dispatches — without
      caching, since only ``"plan"`` populates the cache. Either way,
      dispatching (publishing) the result registers it with the real
      PlanServer's tracking so its progress/error callbacks recognize it.
    """
    if context.agent_context is None or context.coordinator is None:
        return TaskSubmitResponse(
            decision="REJECTED", errors=["Plan server not started (no map configured)"], plans=[]
        )

    unknown = [task.robot_id for task in tasks if not context.agent_context.has_agent(task.robot_id)]
    if unknown:
        return TaskSubmitResponse(decision="REJECTED", errors=[f"Unknown robot(s): {unknown}"], plans=[])

    blocked = _blocked_goal_errors(tasks, context)
    if blocked:
        return TaskSubmitResponse(decision="REJECTED", errors=blocked, plans=[])

    problem_key = _problem_key(tasks)
    robot_to_task_id = {task.robot_id: task.task_id for task in tasks}

    def _dispatch(robot_id: str, plan: Plan, final_waypoint: int) -> None:
        # TODO: _task_id_to_plan_id/_robot_to_plan_id/_plan_final_waypoints are private
        # on res_plan_server.PlanServer. Registering into them here keeps its own
        # _on_progress/_on_plan_error callbacks (driven by the real executor) able to
        # recognize plans we publish ourselves and correctly call
        # MultiAgentContext.on_completed/on_failed. This should become a public API.
        context.plan_server._task_id_to_plan_id[robot_to_task_id[robot_id]] = plan.plan_id
        context.plan_server._robot_to_plan_id[robot_id] = plan.plan_id
        context.plan_server._plan_final_waypoints[plan.plan_id] = final_waypoint
        context.transport.publish_plan(robot_id, plan)
        context.transport.publish_task_status(
            TaskStatusUpdate(
                task_id=robot_to_task_id[robot_id],
                robot_id=robot_id,
                status=TaskStatus.PLANNED,
                source="plan_server",
            )
        )

    plan_tasks = [PlanTask(task_id=task.task_id, robot_id=task.robot_id, goal=task.goal) for task in tasks]

    if mode == "submit":
        if context.plan_server is None:
            return TaskSubmitResponse(
                decision="REJECTED", errors=["Plan server not started (no map configured)"], plans=[]
            )
        if context.plan_cache is not None and context.plan_cache[0] == problem_key:
            _, cached = context.plan_cache
            context.plan_cache = None
            plan_ids = {robot_id: plan.plan_id for robot_id, (plan, _) in cached.items()}
            context.agent_context.on_solve_success({}, plan_tasks, plan_ids)
            for robot_id, (plan, final_waypoint) in cached.items():
                _dispatch(robot_id, plan, final_waypoint)
            return TaskSubmitResponse(decision="ACCEPTED", errors=[], plans=[p for p, _ in cached.values()])

    if mode == "dry_run":
        if context.agent_context.has_executing_agents():
            return TaskSubmitResponse(
                decision="REJECTED",
                errors=[
                    "Cannot dry-run while other robots have ongoing plans — use "
                    "mode='plan' instead (this requests committed locations from "
                    "the executor and may interrupt ongoing plans)."
                ],
                plans=[],
            )
        committed_locations: dict = {}
        stationary_agents: set = set()
    else:  # mode == "plan" or "submit" (cache miss)
        result = _request_committed_locations(context)
        if isinstance(result, str):
            return TaskSubmitResponse(decision="REJECTED", errors=[result], plans=[])
        committed_locations, stationary_agents = result
        # The executor reports a robot as stationary once it has reached the end of
        # its current plan — including one that just finished and is now getting
        # this very batch's task. MAPFCoordinator.solve() unconditionally skips
        # stationary agents (and converts them into obstacles), so without this
        # exclusion a robot's second task always resolves to an empty plan.
        stationary_agents -= {task.robot_id for task in tasks}

    if mode == "submit":
        # Mint plan IDs through PlanServer itself so _task_id_to_plan_id /
        # _robot_to_plan_id are populated as a side effect (see TODO in _dispatch).
        plan_ids = {
            task.robot_id: context.plan_server._get_or_create_plan_id(task.task_id, task.robot_id)
            for task in tasks
        }
    else:
        plan_ids = {task.robot_id: PlanId(destination_session=uuid4(), plan_version=1) for task in tasks}

    try:
        solved = _solve(context, plan_tasks, plan_ids, committed_locations, stationary_agents)
    except (MapfSolverError, PlanningError) as exc:
        # e.g. an obstacle/unknown-waypoint goal, or a stationary agent occupying
        # another agent's destination — the solver raises these rather than just
        # returning no plan. Matches res_plan_server.PlanServer._process_batch's
        # own handling of the same exception types for its AMQP task-request path.
        return TaskSubmitResponse(decision="REJECTED", errors=[str(exc)], plans=[])
    if solved is None:
        return TaskSubmitResponse(decision="REJECTED", errors=["Solver failed to produce a plan"], plans=[])
    robot_to_plan, robot_to_final_waypoint = solved

    if mode == "plan":
        context.plan_cache = (
            problem_key,
            {robot_id: (plan, robot_to_final_waypoint[robot_id]) for robot_id, plan in robot_to_plan.items()},
        )

    if mode == "submit":
        context.agent_context.on_solve_success(committed_locations, plan_tasks, plan_ids)
        for robot_id, plan in robot_to_plan.items():
            _dispatch(robot_id, plan, robot_to_final_waypoint[robot_id])

    return TaskSubmitResponse(decision="ACCEPTED", errors=[], plans=list(robot_to_plan.values()))


def _reachable_node_names(context: ContextDeps) -> list[str]:
    """Node names the solver can actually route through — present in the grid and
    not an obstacle cell. Same source of truth as _blocked_goal_errors."""
    if context.solver is None:
        return []
    grid_map = context.solver._grid_map
    obstacles = set(grid_map.obstacles)
    return sorted(name for name, coord in grid_map.grid_nodes.items() if coord not in obstacles)


_WILDCARD_CHARS = set("*?[")


def _expand_robot_ids(patterns: list[str], db: DbSession) -> list[str]:
    """Expands glob patterns (e.g. ``Manufacturer/*``) in ``patterns`` against
    onboarded robot_ids, preserving order and dropping duplicates. An entry with
    no wildcard characters passes through unchanged — including one that isn't
    actually onboarded, so submit_tasks's own "Unknown robot(s)" check still
    reports it instead of this silently dropping it.
    """
    if not any(_WILDCARD_CHARS & set(pattern) for pattern in patterns):
        return patterns

    onboarded_ids = [record.robot_id for record in crud.robot_record.get_multi_from_attr(
        db, {"is_onboarded": True}, skip=0, limit=1000
    )]

    expanded: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches = fnmatch.filter(onboarded_ids, pattern) if _WILDCARD_CHARS & set(pattern) else [pattern]
        for match in matches:
            if match not in seen:
                seen.add(match)
                expanded.append(match)
    return expanded


@router.post("/random", response_model_exclude_none=True)
async def submit_random_tasks(
    context: ContextDeps,
    db: DbSession,
    mode: Literal["dry_run", "plan", "submit"] = "submit",
    robot_ids: list[str] | None = Query(default=None),
    seed: int | None = None,
) -> TaskSubmitResponse:
    """Generate a random reachable goal for each robot and submit it exactly like
    ``POST /tasks``. Useful for stress-testing without hand-picking waypoints.

    - ``robot_ids``: robots to generate a task for; defaults to all onboarded robots.
      Supports glob wildcards against onboarded robot_ids, e.g. ``Manufacturer/*``
      or just ``*`` for all of them.
    - ``seed``: makes the goal selection reproducible across calls.

    Goals are drawn, without replacement, from non-obstacle nodes present in the
    solver's grid — MAPFCoordinator.solve() rejects a batch outright if two robots
    are given the same goal, so goals in one batch are always distinct.
    """
    node_names = _reachable_node_names(context)
    if not node_names:
        return TaskSubmitResponse(
            decision="REJECTED", errors=["No layout loaded, or it has no reachable waypoints"], plans=[]
        )

    if robot_ids is None:
        records = crud.robot_record.get_multi_from_attr(db, {"is_onboarded": True}, skip=0, limit=1000)
        robot_ids = [record.robot_id for record in records]
    else:
        robot_ids = _expand_robot_ids(robot_ids, db)
    if not robot_ids:
        return TaskSubmitResponse(decision="REJECTED", errors=["No onboarded robots"], plans=[])

    if len(node_names) < len(robot_ids):
        return TaskSubmitResponse(
            decision="REJECTED",
            errors=[f"Only {len(node_names)} reachable waypoint(s) for {len(robot_ids)} robot(s)"],
            plans=[],
        )

    rng = random.Random(seed)
    goals = rng.sample(node_names, k=len(robot_ids))
    tasks = [
        TaskRequestMsg(task_id=str(uuid4()), robot_id=robot_id, goal=goal)
        for robot_id, goal in zip(robot_ids, goals)
    ]

    return await submit_tasks(tasks, context, mode)


def _nodes_within_steps(start: str, steps: int, grid_map) -> list[str]:
    """Node names reachable from ``start`` in 1..``steps`` grid hops (4-connected,
    non-obstacle), excluding ``start`` itself. Same CBSAdapter._grid_map source
    of truth as _reachable_node_names/_blocked_goal_errors."""
    obstacles = set(grid_map.obstacles)
    coord_to_name = {coord: name for name, coord in grid_map.grid_nodes.items() if coord not in obstacles}
    start_coord = grid_map.grid_nodes.get(start)
    if start_coord is None or start_coord in obstacles:
        return []

    visited = {start_coord}
    frontier = deque([(start_coord, 0)])
    reachable: list[str] = []
    while frontier:
        (x, y), dist = frontier.popleft()
        if dist == steps:
            continue
        for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if neighbor in coord_to_name and neighbor not in visited:
                visited.add(neighbor)
                reachable.append(coord_to_name[neighbor])
                frontier.append((neighbor, dist + 1))
    return reachable


@router.post("/random/nearby", response_model_exclude_none=True)
async def submit_random_nearby_tasks(
    context: ContextDeps,
    db: DbSession,
    steps: int = Query(..., ge=1, description="Max grid hops from each robot's start_location"),
    mode: Literal["dry_run", "plan", "submit"] = "submit",
    robot_ids: list[str] | None = Query(default=None),
    seed: int | None = None,
) -> TaskSubmitResponse:
    """Like ``POST /tasks/random``, but each robot's goal is drawn from nodes within
    ``steps`` grid hops of its ``start_location`` instead of anywhere reachable on
    the map — for exercising short, mostly-independent moves rather than long,
    conflict-heavy crossings.

    - ``robot_ids``: robots to generate a task for; defaults to all onboarded robots.
      Supports glob wildcards against onboarded robot_ids, e.g. ``Manufacturer/*``
      or just ``*`` for all of them.
    - ``seed``: makes the goal selection reproducible across calls.

    ``start_location`` only reflects where a robot was onboarded, not its live
    position, so the neighbourhood this draws from can be stale for a robot
    that has since moved. Goals are picked one robot at a time and excluded from
    later robots' candidate pools, so a batch never assigns the same goal twice —
    MAPFCoordinator.solve() would otherwise reject the whole batch.
    """
    if context.solver is None:
        return TaskSubmitResponse(
            decision="REJECTED", errors=["Plan server not started (no map configured)"], plans=[]
        )
    grid_map = context.solver._grid_map

    if robot_ids is None:
        records = crud.robot_record.get_multi_from_attr(db, {"is_onboarded": True}, skip=0, limit=1000)
        robot_ids = [record.robot_id for record in records]
    else:
        robot_ids = _expand_robot_ids(robot_ids, db)
    if not robot_ids:
        return TaskSubmitResponse(decision="REJECTED", errors=["No onboarded robots"], plans=[])

    rng = random.Random(seed)
    used_goals: set[str] = set()
    tasks: list[TaskRequestMsg] = []
    errors: list[str] = []
    for robot_id in robot_ids:
        record = crud.robot_record.get(db, robot_id)
        start = record.start_location if record else None
        candidates = [name for name in _nodes_within_steps(start, steps, grid_map) if name not in used_goals] \
            if start else []
        if not candidates:
            errors.append(f"No reachable waypoint within {steps} step(s) of robot {robot_id}'s start_location")
            continue
        goal = rng.choice(candidates)
        used_goals.add(goal)
        tasks.append(TaskRequestMsg(task_id=str(uuid4()), robot_id=robot_id, goal=goal))

    if errors:
        return TaskSubmitResponse(decision="REJECTED", errors=errors, plans=[])

    return await submit_tasks(tasks, context, mode)

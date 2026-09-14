from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException

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


def _problem_key(tasks: list[TaskRequestMsg]) -> frozenset[tuple[str, str]]:
    """Identifies the exact MAPF problem a batch of tasks poses — same robots
    wanting the same goals, regardless of task_id."""
    return frozenset((task.robot_id, task.goal) for task in tasks)


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
      for. Still does not dispatch anything.
    - ``"submit"``: always blocks to plan, the same way ``"plan"`` does, then
      dispatches (publishes) the result and registers it with the real
      PlanServer's tracking so its progress/error callbacks recognize it. The
      resulting plan is cached by the exact ``{robot_id: goal}`` problem it
      solved — an identical follow-up ``"submit"`` request skips committed
      locations and solving entirely and redispatches the cached plan.
    """
    if context.agent_context is None or context.coordinator is None:
        return TaskSubmitResponse(
            decision="REJECTED", errors=["Plan server not started (no map configured)"], plans=[]
        )

    unknown = [task.robot_id for task in tasks if not context.agent_context.has_agent(task.robot_id)]
    if unknown:
        return TaskSubmitResponse(decision="REJECTED", errors=[f"Unknown robot(s): {unknown}"], plans=[])

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

    if mode == "submit":
        if context.plan_server is None:
            return TaskSubmitResponse(
                decision="REJECTED", errors=["Plan server not started (no map configured)"], plans=[]
            )
        cached = context.plan_cache.get(problem_key)
        if cached is not None:
            for robot_id, (plan, final_waypoint) in cached.items():
                _dispatch(robot_id, plan, final_waypoint)
            return TaskSubmitResponse(decision="ACCEPTED", errors=[], plans=[p for p, _ in cached.values()])

    plan_tasks = [PlanTask(task_id=task.task_id, robot_id=task.robot_id, goal=task.goal) for task in tasks]

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

    if mode == "submit":
        # Mint plan IDs through PlanServer itself so _task_id_to_plan_id /
        # _robot_to_plan_id are populated as a side effect (see TODO in _dispatch).
        plan_ids = {
            task.robot_id: context.plan_server._get_or_create_plan_id(task.task_id, task.robot_id)
            for task in tasks
        }
    else:
        plan_ids = {task.robot_id: PlanId(destination_session=uuid4(), plan_version=1) for task in tasks}

    solved = _solve(context, plan_tasks, plan_ids, committed_locations, stationary_agents)
    if solved is None:
        return TaskSubmitResponse(decision="REJECTED", errors=["Solver failed to produce a plan"], plans=[])
    robot_to_plan, robot_to_final_waypoint = solved

    if mode == "submit":
        context.plan_cache[problem_key] = {
            robot_id: (plan, robot_to_final_waypoint[robot_id]) for robot_id, plan in robot_to_plan.items()
        }
        context.agent_context.on_solve_success(committed_locations, plan_tasks, plan_ids)
        for robot_id, plan in robot_to_plan.items():
            _dispatch(robot_id, plan, robot_to_final_waypoint[robot_id])

    return TaskSubmitResponse(decision="ACCEPTED", errors=[], plans=list(robot_to_plan.values()))

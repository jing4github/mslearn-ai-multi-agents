"""Adaptive decomposition starter with live Agents v2 calls."""
# Overall flow of this lab (planner -> validate -> execute DAG -> report):
#   1. A "research-planner" agent receives the user's query and breaks it into a
#      small plan of tasks (JSON). Each task names a specialist agent, an
#      objective, and which other tasks it depends on (depends_on).
#   2. validate_plan() checks that plan is safe to run (known agents, unique IDs,
#      no cycles, exactly one final thesis-synthesis task, ...).
#   3. The run loop executes the plan as a DAG (directed acyclic graph): it
#      repeatedly picks the tasks whose dependencies are done (ready_tasks),
#      sends each one to its specialist agent inside a "handoff envelope"
#      (build_handoff), and stores the result.
#   4. should_replan() decides whether a result is weak enough to justify a
#      replan (at most one).
#   5. Finally, run() returns metrics (task count, handoffs, elapsed time) plus
#      every task's result, printed as JSON by main().
from __future__ import annotations
import argparse, json, logging, os, time, uuid
from pathlib import Path
from typing import Any
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

LOGGER=logging.getLogger("decomposition")
# Load settings (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_NAME, MAX_HANDOFF_CHARS,
# ...) from the lab's .env file. parents[1] = the lab folder (one level above src/).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
def validate_plan(plan: dict[str, Any], registry: dict[str, Any]) -> None:
    """Learner task: validate IDs, capabilities, dependencies, DAG, and final task."""
    # The plan comes from an LLM, so it can't be trusted blindly. This function
    # raises ValueError on the first problem it finds; returning normally means
    # the plan is OK to execute.
    # LAB PLACEHOLDER 1: Replace this line with the Task 1 sample.

    # --- Check 1: the plan has a "tasks" list with 1 to 6 entries. ---
    # The cap keeps the planner from over-decomposing (more tasks = more calls,
    # cost, and latency).
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 6:
        raise ValueError("Plan must contain between 1 and 6 tasks")

    # --- Check 2: every task has a nonempty, unique string ID. ---
    # IDs are how tasks reference each other in depends_on, so they must be
    # unambiguous.
    task_ids = [task.get("id") for task in tasks]
    if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
        raise ValueError("Every task requires a nonempty string ID")
    if len(task_ids) != len(set(task_ids)):  # a set drops duplicates
        raise ValueError("Task IDs must be unique")

    # --- Check 3: per-task capability and dependency checks. ---
    known_ids = set(task_ids)
    for task in tasks:
        # The task must be assigned to an agent that exists in the registry
        # (the planner must not invent agents).
        if task.get("agent") not in registry:
            raise ValueError(f"Unknown agent for task {task['id']}")
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"depends_on must be a list for task {task['id']}")
        # A task can't depend on itself, and every dependency must point to a
        # real task ID in this plan (<= on sets means "is a subset of").
        if task["id"] in dependencies or not set(dependencies) <= known_ids:
            raise ValueError(f"Invalid dependency for task {task['id']}")

    # --- Check 4: the dependency graph has no cycles (it is a DAG). ---
    # Uses Kahn-style topological sorting: repeatedly "resolve" every task whose
    # dependencies are all already resolved. If at some point nothing can be
    # resolved but tasks remain, they must be waiting on each other in a cycle
    # (e.g. T1 -> T2 -> T1), which would deadlock execution.
    remaining = {
        task["id"]: set(task.get("depends_on", []))
        for task in tasks
    }  # task ID -> set of IDs it still waits on
    resolved: set[str] = set()
    while remaining:
        ready = {
            task_id
            for task_id, dependencies in remaining.items()
            if dependencies <= resolved
        }
        if not ready:
            raise ValueError("Plan dependencies contain a cycle")
        resolved.update(ready)
        # Drop the newly resolved tasks and loop again.
        remaining = {
            task_id: dependencies
            for task_id, dependencies in remaining.items()
            if task_id not in ready
        }

    # --- Check 5: exactly one thesis-synthesis task, and it comes last. ---
    synthesis_tasks = [
        task for task in tasks if task["agent"] == "thesis-synthesis"
    ]
    if len(synthesis_tasks) != 1:
        raise ValueError("The plan must contain exactly one thesis-synthesis task")
    synthesis = synthesis_tasks[0]
    # Every ID that some *other* (non-synthesis) task depends on. These are
    # intermediate tasks: their output is already consumed downstream.
    non_synthesis_dependency_ids = {
        dependency
        for task in tasks
        if task["id"] != synthesis["id"]
        for dependency in task.get("depends_on", [])
    }
    # "Terminal" evidence tasks = tasks nobody else consumes (the leaves at the
    # end of each evidence chain). Their output would be lost unless synthesis
    # reads it.
    terminal_evidence_ids = {
        task["id"]
        for task in tasks
        if task["id"] not in non_synthesis_dependency_ids and task["id"] != synthesis["id"]
    }
    # Synthesis must depend on exactly those terminal tasks, so no evidence is
    # dropped and it doesn't redundantly depend on intermediate tasks.
    if set(synthesis.get("depends_on", [])) != terminal_evidence_ids:
        raise ValueError(
            "The thesis-synthesis task must depend on every terminal evidence task"
        )
    # Synthesis is the final step: nothing may run after it.
    if any(synthesis["id"] in task.get("depends_on", []) for task in tasks):
        raise ValueError("No task can depend on the thesis-synthesis task")

def ready_tasks(tasks: list[dict[str, Any]], completed: dict[str, Any]) -> list[dict[str, Any]]:
    """Learner task: select dependency-ready tasks or identify a deadlock."""
    # Returns the next "batch" of tasks that can run now. `completed` maps
    # task ID -> result dict ({"status", "response_id", "summary"}).
    # LAB PLACEHOLDER 2: Replace this line with the Task 2 sample.
    unfinished = [task for task in tasks if task["id"] not in completed]
    # A task is ready when every dependency finished with status "success".
    # (A dependency that is missing or failed counts as not done.)
    ready = [
        task
        for task in unfinished
        if all(
            completed.get(dependency, {}).get("status") == "success"
            for dependency in task.get("depends_on", [])
        )
    ]
    # Work remains but nothing can start, e.g. because a dependency failed.
    # Fail loudly instead of looping forever.
    if unfinished and not ready:
        blocked = ", ".join(task["id"] for task in unfinished)
        raise RuntimeError(f"Plan deadlock: blocked tasks: {blocked}")
    return ready

def build_handoff(task: dict[str, Any], completed: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    """Learner task: construct and size-check a context-preserving envelope."""
    # The "envelope" is the message sent to a specialist agent. Specialists
    # don't share memory with each other, so the envelope must carry everything
    # the agent needs: its objective plus the results of the tasks it depends on.
    # LAB PLACEHOLDER 3: Replace this line with the Task 3 sample.
    max_chars = int(os.getenv("MAX_HANDOFF_CHARS", "6000"))
    dependencies = task.get("depends_on", [])
    # Split the character budget across the dependency summaries (leaving room
    # for the rest of the envelope), but give each one at least 256 chars.
    summary_limit = max(256, max_chars // max(2, len(dependencies) + 1))
    # Context from upstream tasks: a truncated summary of each one, plus its
    # response_id so the provenance of the evidence can be traced.
    dependency_context = [
        {
            "task_id": dependency,
            "response_id": completed[dependency]["response_id"],
            "summary": completed[dependency]["summary"][:summary_limit],
        }
        for dependency in dependencies
    ]
    envelope = {
        "task_id": task["id"],
        "objective": task["objective"],               # what this agent should do
        "dependency_context": dependency_context,      # evidence from upstream tasks
        "source_response_ids": [
            item["response_id"] for item in dependency_context
        ],                                             # audit trail of sources
        "expected_schema": task["expected_schema"],    # shape the answer should take
        "deadline_seconds": int(os.getenv("HANDOFF_DEADLINE_SECONDS", "45")),
        "correlation_id": correlation_id,              # same ID for every call in this run
    }
    # Hard size limit: an oversized handoff wastes tokens and can overflow the
    # model's context, so reject it instead of sending it.
    if len(json.dumps(envelope)) > max_chars:
        raise ValueError("Handoff envelope exceeds MAX_HANDOFF_CHARS")
    return envelope

def should_replan(result: dict[str, Any], replan_count: int) -> bool:
    """Learner task: allow one evidence-driven replan only."""
    # Decides whether a task's result is weak enough to justify replanning.
    # Replanning is capped at one to avoid endless plan -> run -> replan loops.
    # LAB PLACEHOLDER 4: Replace this line with the Task 4 sample.
    if replan_count >= 1:
        return False  # budget already used
    if result.get("status") != "success":
        return True   # the task itself failed

    # Specialists are told to answer in JSON, so look inside the answer for
    # signals that the evidence is weak. If it isn't valid JSON there is nothing
    # to inspect, so don't replan.
    try:
        payload = json.loads(result.get("summary", "{}"))
    except json.JSONDecodeError:
        return False

    status = str(payload.get("status", "")).lower()
    confidence = payload.get("confidence")
    low_confidence = isinstance(confidence, (int, float)) and confidence < 0.5
    # Replan if the agent says evidence/capability is missing, lists missing
    # evidence, or reports confidence below 0.5.
    return (
        status in {"missing_evidence", "capability_unavailable"}
        or bool(payload.get("missing_evidence"))
        or low_confidence
    )

def response_text(response: Any) -> str:
    # A Responses API result has an `output` list of items (messages, tool calls,
    # ...). Keep only "message" items and join the text of their content parts
    # into one string.
    return "\n".join(getattr(p,"text","") for i in response.output if getattr(i,"type",None)=="message" for p in getattr(i,"content",[])).strip()

def call_agent(openai: Any, content: str) -> Any:
    # Send one input to an agent. The client was created for a specific agent
    # (get_openai_client(agent_name=...)), so that agent's instructions apply.
    return openai.responses.create(input=content)

def run(path: Path) -> dict[str, Any]:
    # Input file (assets/research-query.json) holds: the user "query", a "complexity_hint" (simple/complex),
    # and a "registry" of specialist agents (name -> instructions).
    data=json.loads(path.read_text(encoding="utf-8"))
    started=time.perf_counter()
    # One ID shared by every handoff in this run, so the calls can be linked together in logs and traces.
    correlation_id=str(uuid.uuid4())

    # Connect to the Microsoft Foundry project. DefaultAzureCredential uses your
    # `az login` (or another available Azure identity).
    project=AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],credential=DefaultAzureCredential())
    model=os.environ["FOUNDRY_MODEL_NAME"]

    # Create (or add a new version of) the planner agent. Its instructions are ROOT_INSTRUCTIONS with 
    # the registry JSON appended, so it knows which specialists it may assign tasks to.
    planner=project.agents.create_version(agent_name="research-planner",definition=PromptAgentDefinition(model=model,instructions=(ROOT_INSTRUCTIONS + json.dumps(data["registry"]))))
    # Create one agent per registry entry, named after its key (financial-data,
    # macro-risk, ...). Result: registry name -> agent name.
    specialists={name:project.agents.create_version(agent_name=name,definition=PromptAgentDefinition(model=model,instructions=spec["instructions"])).name for name,spec in data["registry"].items()}
    # Get an OpenAI-compatible client bound to each agent, used to call it.
    planner_openai=project.get_openai_client(agent_name=planner.name)
    specialist_clients={name:project.get_openai_client(agent_name=agent_name) for name,agent_name in specialists.items()}

    # Step 1 - Plan: ask the planner to decompose the query into tasks.
    planner_response=call_agent(planner_openai,json.dumps({"query":data["query"],"complexity_hint":data["complexity_hint"]}))
    # Parse the planner's JSON reply and validate it, then initialize state:
    #   completed    = task ID -> result
    #   handoffs     = number of specialist calls made
    #   replan_count = number of replans triggered (max 1)
    plan=json.loads(response_text(planner_response)); validate_plan(plan,data["registry"]); completed={}; handoffs=0; replan_count=0
    # Step 2 - Execute: run the plan in waves until every task has a result.
    while len(completed)<len(plan["tasks"]):
        # All tasks whose dependencies are done. In wave 1 these are tasks with
        # no dependencies; the synthesis task runs in the last wave.
        batch=ready_tasks(plan["tasks"],completed)
        if not batch: raise RuntimeError("Plan deadlock: no task is dependency-ready")
        # Tasks in a batch are independent and could run in parallel; here they
        # run one after another for simplicity.
        for task in batch:
            # Package the task and its upstream context into an envelope.
            envelope=build_handoff(task,completed,correlation_id); handoffs+=1
            # Send the envelope to the task's specialist and record the result.
            # The status is always "success" here: if the call raises an error,
            # the whole run stops.
            response=call_agent(specialist_clients[task["agent"]],json.dumps(envelope)); completed[task["id"]]={"status":"success","response_id":response.id,"summary":response_text(response)}
            # Step 3 - Replan check. Note: this starter only *counts* the replan
            # decision; it doesn't actually call the planner again to revise the
            # plan.
            if should_replan(completed[task["id"]],replan_count): replan_count+=1
    # Step 4 - Report results and coordination metrics. coordination_ratio =
    # handoffs per completed task (1.0 means one specialist call per task).
    return {"planner_response_id":planner_response.id,"plan":plan["tasks"],"task_count":len(plan["tasks"]),"handoff_count":handoffs,"replan_count":replan_count,"coordination_ratio":round(handoffs/max(1,len(completed)),2),"elapsed_ms":round((time.perf_counter()-started)*1000),"results":completed}
# System instructions for the planner agent. They define the exact JSON shape
# of a plan and the decomposition rules (simple query -> 2 tasks; complex ->
# 3-6 tasks; always end with one thesis-synthesis task). run() appends the
# registry JSON after "Registry: ". It is defined below run() but that's fine:
# the name is only looked up when run() actually executes.
ROOT_INSTRUCTIONS=(
    "Return JSON only: {\"tasks\":[{\"id\":\"T1\",\"objective\":\"...\","
    "\"agent\":\"...\",\"depends_on\":[],\"expected_schema\":\"...\"}]}. "
    "Use only known agents and exactly one final thesis-synthesis task. If "
    "complexity_hint is simple, return exactly two tasks: one best-fit evidence "
    "task and a final synthesis task that depends on it. If complexity_hint is "
    "complex, return three through six tasks and decompose the query across "
    "relevant evidence specialists before final synthesis. Registry: "
)

def main()->None:
    # CLI entry point. Run from the lab folder: python src/main.py
    # (optionally with --input <path-to-query.json>).
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,default=Path("assets/research-query.json"))
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    # Run the full pipeline and print the result dict as formatted JSON.
    print(json.dumps(run(a.input),indent=2))
if __name__=="__main__":main()

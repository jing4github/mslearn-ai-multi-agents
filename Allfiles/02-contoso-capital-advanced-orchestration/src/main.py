"""Live Agents v2 fan-out/fan-in orchestration starter."""
# Flow: create the spoke agents and the supervisor agent in Foundry -> fan out the request to
# the spokes (in parallel or one after another) -> fan in their results -> check that the
# required spokes succeeded (quorum) -> have the supervisor combine the accepted evidence.
from __future__ import annotations
from asyncio import tasks
import argparse, asyncio, json, logging, os, time
from pathlib import Path
from typing import Any
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

LOGGER = logging.getLogger("orchestration")

# Loads the azd outputs (FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_NAME, ...) from the lab folder's .env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

def select_execution_pattern(tasks: list[dict[str, Any]]) -> str:
    """Learner task: return parallel only when this batch has no dependencies."""
    # LAB PLACEHOLDER 1: Replace this line with the Task 1 sample.
    # A task depends on another task in this batch if its optional "depends_on" list names it.
    # Then the batch can't fan out safely, so it runs sequentially. Dependencies on tasks
    # outside the batch don't count, because those are already done.
    task_names = {task["name"] for task in tasks}
    has_in_round_dependency = any(
        task_names.intersection(task.get("depends_on", []))
        for task in tasks
    )
    return "sequential" if has_in_round_dependency else "parallel"


def evaluate_quorum(results: list[dict[str, Any]], required: list[str]) -> dict[str, Any]:
    """Learner task: enforce critical-agent quorum and normalize evidence."""
    # LAB PLACEHOLDER 2: Replace this line with the Task 2 sample.
    # The fan-in step. It decides whether there is enough evidence to continue:
    # every agent in `required` must have succeeded. Optional agents can fail.
    successful = {
        result["agent"]: result
        for result in results
        if isinstance(result, dict) and result.get("status") == "success"
    }
    all_agents = [
        result.get("agent", "unknown")
        for result in results
        if isinstance(result, dict)
    ]
    # Any failed spoke: the supervisor has to add a caveat for each one.
    missing_agents = [name for name in all_agents if name not in successful]
    # Failed spokes that are required: any entry here blocks synthesis.
    missing_required = [name for name in required if name not in successful]
    # Only successful outputs go to the supervisor, reduced to the fields it needs.
    # response_id makes each piece of evidence traceable to its Foundry response.
    accepted_evidence = [
    {
    "agent": name,
    "response_id": result["response_id"],
    "text": result["text"],
    "elapsed_ms": result["elapsed_ms"],
    }
    for name, result in successful.items()
    ]
    return {
    "status": "ready" if not missing_required else "insufficient_quorum",
    "required_agents": required,
    "successful_count": len(successful),
    "missing_agents": missing_agents,
    "missing_required": missing_required,
    "accepted_evidence": accepted_evidence,

}

def text_from_response(response: Any) -> str:
    # A Responses API result has a list of output items (messages, tool calls, ...).
    # This keeps only the text of the message items.
    return "\n".join(getattr(part, "text", "") for item in response.output if getattr(item, "type", None) == "message" for part in getattr(item, "content", [])).strip()

async def invoke(openai: Any, agent_name: str, prompt: str, timeout: float, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    # Calls one spoke agent. It never raises: a failure comes back as a "failed" record,
    # so one bad spoke doesn't cancel the whole gather(). Quorum then decides if that matters.
    started = time.perf_counter()
    try:
        async def call_with_capacity() -> Any:
            # The semaphore caps how many agent calls are in flight (MAX_CONCURRENCY).
            # responses.create is a blocking call, so it runs in a worker thread
            # to let the calls overlap.
            async with semaphore:
                return await asyncio.to_thread(
                    openai.responses.create,
                    input=prompt,
                )

        # The timeout covers both waiting for a semaphore slot and the call itself.
        response = await asyncio.wait_for(call_with_capacity(), timeout)
        return {"agent": agent_name, "status": "success", "response_id": response.id, "text": text_from_response(response), "elapsed_ms": round((time.perf_counter()-started)*1000)}
    except Exception as exc:
        # Logs only the exception type, so the logs don't include prompt or response text.
        LOGGER.warning("Spoke failed agent=%s category=%s", agent_name, type(exc).__name__)
        return {"agent": agent_name, "status": "failed", "response_id": None, "text": None, "elapsed_ms": round((time.perf_counter()-started)*1000)}

def synthesize(openai: Any, request: str, quorum: dict[str, Any]) -> Any:
    """Learner task: invoke the supervisor with accepted evidence and caveats."""
    # LAB PLACEHOLDER 3: Replace this line with the Task 3 sample.
    # Stops here if quorum wasn't met. Without the required evidence the supervisor
    # would only be guessing, so the run fails loudly instead.
    if quorum["status"] != "ready":
        missing = ", ".join(quorum["missing_required"])
        raise RuntimeError(f"Critical quorum was not met: {missing}")

    # The supervisor gets only the accepted evidence and the list of missing agents,
    # not the raw spoke results.
    payload = {
    "request": request,
    "accepted_evidence": quorum["accepted_evidence"],
    "missing_agents": quorum["missing_agents"],
    }

    # `openai` is the supervisor agent's client, so its instructions apply on top of this prompt.
    return openai.responses.create(

    input=(
    "Synthesize the supplied specialist evidence. State a caveat for "
    "every missing agent, do not invent facts, and do not provide "
    "investment advice.\n"
    + json.dumps(payload)
    ),
)

async def run(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
    names = {}
    clients = {}
    # Registers each spoke and the supervisor as a Foundry agent: one new version per run,
    # all on the model deployment from the Bicep template. Each agent gets its own OpenAI client
    # bound to it, so responses.create on that client goes to that agent.
    for spec in data["agents"] + [data["supervisor"]]:
        version = project.agents.create_version(agent_name=spec["name"], definition=PromptAgentDefinition(model=os.environ["FOUNDRY_MODEL_NAME"], instructions=spec["instructions"]))
        names[spec["name"]] = version.name
        clients[spec["name"]] = project.get_openai_client(agent_name=version.name)
    pattern = select_execution_pattern(data["agents"])
    semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "3")))
    # Fan-out: one coroutine per spoke, combining the shared request with that spoke's assignment.
    # These are only created here; none of them runs until it is awaited below.
    tasks = [invoke(clients[item["name"]], names[item["name"]], f"Request: {data['request']}\nAssignment: {item['assignment']}", float(os.getenv("AGENT_TIMEOUT_SECONDS", "45")), semaphore) for item in data["agents"]]
    # Timing starts after the agents are created, so it measures only the orchestration.
    started = time.perf_counter()
    if pattern == "parallel":
        results = await asyncio.gather(*tasks)
    else:
        # Sequential: each spoke starts only after the previous one finishes.
        # Earlier outputs are not passed to later spokes, though.
        results = [await task for task in tasks]
    # Demo switch: marks the last spoke (compliance-spoke, which is optional) as failed
    # to show that quorum still passes and the supervisor adds a caveat.
    if data.get("simulate_optional_failure"):
        results[-1] = {**results[-1], "status": "failed", "text": None}
    # Fan-in: quorum gate, then supervisor synthesis.
    quorum = evaluate_quorum(results, data["required_agents"])
    supervisor = synthesize(clients[data["supervisor"]["name"]], data["request"], quorum)
    return {"pattern": pattern, "quorum": quorum, "spokes": results, "supervisor_response_id": supervisor.id, "answer": text_from_response(supervisor), "elapsed_ms": round((time.perf_counter()-started)*1000)}

def main() -> None:
    # --input lets you run another scenario file; by default it uses assets/portfolio-request.json.
    parser = argparse.ArgumentParser(); parser.add_argument("--input", type=Path, default=Path("assets/portfolio-request.json")); args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(asyncio.run(run(args.input)), indent=2))
if __name__ == "__main__": main()

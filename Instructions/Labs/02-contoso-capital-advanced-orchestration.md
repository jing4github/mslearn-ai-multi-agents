---
lab:
  title: 'Implement advanced multi-agent orchestration patterns in Microsoft Foundry'
  description: 'Build and validate a v2 fan-out/fan-in research workflow with quorum and partial-failure handling.'
  duration: 45
  level: 400
  islab: true
  status: 'released'
---

# Implement advanced multi-agent orchestration patterns in Microsoft Foundry

## Customer scenario

Contoso Capital needs market, risk, and compliance specialists to contribute to one investment brief. Independent work should run concurrently, dependent work must remain ordered, and a failed optional specialist must not silently invalidate the report.

## Lab scenario

Complete a hub-and-spoke orchestrator that creates versioned Agents v2 specialists, fans out live response calls, applies a configurable quorum, and sends accepted evidence to a supervisor. The supplied request concerns a synthetic balanced portfolio under a fictional interest-rate shock. No agent receives real customer data or recommends trades.

<!-- LAB DIAGRAM PLACEHOLDER: Show the hub-and-spoke fan-out, quorum decision, and supervisor fan-in. -->

### Agent responsibilities

Each spoke receives the same request plus its assignment and returns concise JSON based only on the supplied scenario.

| Agent | Contribution | Quorum policy |
|---|---|---|
| `market-spoke` | Market assumptions, uncertainties, and evidence gaps. | Required. |
| `risk-spoke` | Risk drivers, exposure limits, and uncertainty, without investment advice. | Required. |
| `compliance-spoke` | Disclosures, policy caveats, and limits on use of the research. | Optional; missing evidence must be disclosed. |
| `research-supervisor` | One brief from the original request, accepted spoke evidence, and missing-agent list; no invented facts or investment advice. | Runs only after both required spokes succeed. |

### How the agents collaborate

`src/main.py` creates agent versions from `assets/portfolio-request.json`, invokes independent spokes behind a bounded semaphore, normalizes their results, and evaluates quorum before synthesis. Spokes do not share a conversation, see sibling outputs, or invoke one another. Application code owns concurrency and failure policy; agents own analysis and synthesis.

By the end of this exercise, you will be able to:

- Justify when multi-agent coordination earns its cost.
- Implement a central hub with specialist spokes.
- Fan out independent calls and synchronize results.
- Apply supervisor, quorum, timeout, and partial-failure policy.
- Compare orchestration behavior across normal and optional-failure inputs.

> **Important**: Concurrent model calls consume quota faster than sequential calls. Use only the synthetic portfolio and remove resources after validation.

## Task 1: Prepare the lab

Use [Python 3.11+](https://www.python.org/downloads/), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)/[Bicep](https://learn.microsoft.com/azure/azure-resource-manager/bicep/install), [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd), [Visual Studio Code](https://code.visualstudio.com/download), and an authenticated Azure subscription. You need a supported model deployment and permission to create Foundry resources. Confirm quota can support three concurrent calls.

1. If you haven't already done so, clone the [lab source repository](https://github.com/MicrosoftLearning/mslearn-ai-multi-agents/tree/main), or fork the repository and clone your fork:

```console
git clone https://github.com/MicrosoftLearning/mslearn-ai-multi-agents.git
```

2. Open the cloned repository in Visual Studio Code.
3. From the VS Code terminal, validate the required tools, credentials, and active subscription:

```powershell
cd Allfiles\02-contoso-capital-advanced-orchestration
az version
azd version
python --version
az account show --output table
```

**Architecture checkpoint**

Review `infra/main.bicep`, `assets/portfolio-request.json`, and `src/main.py`. Before continuing, confirm that:

- the portfolio asset defines each specialist's assignment and required or optional status;
- the three agent-bound specialist calls can run concurrently;
- market and risk evidence are required while compliance evidence is optional;
- deterministic code evaluates quorum before supervisor synthesis.

## Task 2: Build the virtual environment

1. From the lab directory, create and activate the virtual environment:

```powershell
./scripts/setup.ps1
. ./.venv/Scripts/Activate.ps1
```

> On macOS/Linux, run `bash scripts/setup.sh` and `source .venv/bin/activate` instead.

## Task 3: Deploy the Azure resources

Check cost, quota, and access before provisioning. Model calls, Application Insights ingestion, and 30-day Log Analytics retention are billable. Use a unique environment and bounded scenarios. `azd` provisions the Bicep resources; the application runs separately.

**Set the deployment values**

1. Set `$azureRegion` to an approved region that supports the selected model; replace `eastus2` if needed.

> **Resource group:** If your lab environment provides a precreated resource group, set `$resourceGroupName` to its name. Otherwise, leave `$resourceGroupName` empty so the script creates a unique resource group in your subscription.

> **Note:** `AZURE_DEV_USER_AGENT` tags provisioning for attribution and is not exported to `.env`. Remove it afterward to avoid tagging unrelated commands.

**Validate and provision the infrastructure**

2. Validate Bicep, provision the resources, and export the environment:

```powershell
$azureRegion = 'eastus2'
$resourceGroupName = ''
if ([string]::IsNullOrWhiteSpace($resourceGroupName)) {
  $resourceGroupName = "rg-lab02-$((New-Guid).Guid.Substring(0, 8))"
  az group create --name $resourceGroupName --location $azureRegion | Out-Null
}
az bicep build --file infra/main.bicep
$env:AZURE_DEV_USER_AGENT='microsoft_foundry_skill'
azd env new lab02
azd env set AZURE_LOCATION $azureRegion
azd env set AZURE_RESOURCE_GROUP $resourceGroupName
azd env set FOUNDRY_MODEL_NAME gpt-5.4-mini
azd env set FOUNDRY_MODEL_CATALOG_NAME gpt-5.4-mini
azd env set FOUNDRY_MODEL_VERSION 2026-03-17
azd provision
azd env get-values | Out-File .env -Encoding utf8
Remove-Item Env:AZURE_DEV_USER_AGENT
```

3. If provisioning fails, inspect the first deployment error. Check model quota, model-version and regional availability, and role-assignment permissions. Correct the relevant setting or permission and rerun `azd provision`.

**Verify the generated environment**

4. Confirm that `.env` includes `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_PROJECT_ID`, `FOUNDRY_MODEL_NAME`, `APPLICATIONINSIGHTS_RESOURCE_ID`, and `LOG_ANALYTICS_WORKSPACE_ID`.

The Application Insights connection string is stored in the Foundry project connection and is not written to `.env`.

> **Network access for this lab:** The Bicep template enables the Foundry account's native public network access and sets the default network action to **Allow** so the local application can reach the project endpoint. Microsoft Entra authentication and Azure RBAC are still required. After deployment, confirm these settings on the Foundry account **Networking** page. Production environments should use an approved selected-network or private-endpoint design.

5. Do not add keys or tokens to `.env`.

## Task 4: Implement the solution

Each placeholder marks incomplete code. Copy each supplied snippet into its placeholder location, keep the `LAB PLACEHOLDER` comment, replace only the indicated incomplete line or block, and preserve the surrounding indentation.

**Select a safe execution pattern**

1. Open `src/main.py` and find **LAB PLACEHOLDER 1** in `select_execution_pattern`:

```python
# LAB PLACEHOLDER 1: Replace this line with the Task 1 sample.
raise NotImplementedError("Complete select_execution_pattern in Task 1")    
```

```python
task_names = {task["name"] for task in tasks}
has_in_round_dependency = any(
  task_names.intersection(task.get("depends_on", []))
  for task in tasks
)
return "sequential" if has_in_round_dependency else "parallel"
```

An in-batch dependency selects sequential execution; independent spokes remain eligible for parallel fan-out.

**Enforce critical-agent quorum**

2. Find **LAB PLACEHOLDER 2** in `evaluate_quorum`:

```python
# LAB PLACEHOLDER 2: Replace this line with the Task 2 sample.
raise NotImplementedError("Complete evaluate_quorum in Task 2")
```

```python
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
missing_agents = [name for name in all_agents if name not in successful]
missing_required = [name for name in required if name not in successful]
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
```

Quorum separates optional omissions from missing required evidence. Only normalized successful results proceed; exceptions, credentials, endpoints, and hidden agent state are excluded from the supervisor payload.

**Synthesize accepted evidence**

3. Find **LAB PLACEHOLDER 3** in `synthesize`:

```python
# LAB PLACEHOLDER 3: Replace this line with the Task 3 sample.
raise NotImplementedError("Complete synthesize in Task 3")
```

```python
if quorum["status"] != "ready":
  missing = ", ".join(quorum["missing_required"])
  raise RuntimeError(f"Critical quorum was not met: {missing}")

payload = {
  "request": request,
  "accepted_evidence": quorum["accepted_evidence"],
  "missing_agents": quorum["missing_agents"],
}
return openai.responses.create(
  input=(
    "Synthesize the supplied specialist evidence. State a caveat for "
    "every missing agent, do not invent facts, and do not provide "
    "investment advice.\n"
    + json.dumps(payload)
  ),
)
```

This fan-in boundary blocks synthesis on insufficient quorum and requires explicit caveats for missing optional evidence.

**Check failure isolation and concurrency controls**

The supplied runner honors the selected execution pattern. Independent spokes use `asyncio.gather(...)`, while dependent spokes are awaited sequentially. `invoke` catches each spoke failure and returns the same normalized result shape before quorum logic runs, so raw exception objects never enter `evaluate_quorum`. The `asyncio.Semaphore` bounds parallel calls, and each timeout includes time waiting for capacity as well as the model call.

4. Run the local checks before making a billable model call:

```powershell
python -m py_compile src/main.py scripts/preflight.py
python scripts/preflight.py
```

5. Confirm that preflight reports four `PASS` lines, all three markers remain, and `src/main.py` contains no `NotImplementedError`.

## Task 5: Run the solution

**Capture both scenarios**

1. Run the normal input once and capture its output:

```powershell
python -m py_compile src/main.py scripts/preflight.py
python -m src.main --input assets/portfolio-request.json *> artifacts-normal.txt
Select-String artifacts-normal.txt -Pattern 'pattern|quorum|elapsed_ms|missing_agents|supervisor_response_id'
```

2. Run the optional-failure input and capture its output separately:

```powershell
python -m src.main --input assets/portfolio-request-optional-failure.json *> artifacts-optional-failure.txt
```

The inputs differ only in `simulate_optional_failure`. The second run marks `compliance-spoke` as failed **after its live call**; it does not simulate an Azure service outage. Do not edit the normal input.

3. Display the orchestration fields from both runs:

```powershell
Select-String -Path artifacts-normal.txt,artifacts-optional-failure.txt -Pattern 'pattern|"agent"|"status"|missing_agents|missing_required|accepted_evidence|supervisor_response_id'
```

4. Retain both artifacts and their response IDs for trace validation. IDs, wording, and timing vary between live runs; those differences are not policy changes.

## Task 6: Validate the implementation

**Compare orchestration outcomes**

1. Compare the saved outputs against these acceptance criteria:

| Field | Normal input | Optional-failure input |
|---|---|---|
| `pattern` | `parallel` | `parallel` |
| `compliance-spoke.status` | `success` | `failed`; market and risk still succeed |
| `quorum.status` | `ready` | `ready` |
| `quorum.missing_agents` | Empty | Contains `compliance-spoke` |
| `quorum.missing_required` | Empty | Empty |
| `quorum.accepted_evidence` | Three spoke results | Only market and risk results |
| `supervisor_response_id` | Present | Present |
| Supervisor answer | Uses accepted evidence only | Explicitly states that compliance evidence is missing |

2. In the normal output, confirm that `spokes` contains three normalized successful results with response IDs, visible text, and durations, plus a separate supervisor response ID.
3. Compare `elapsed_ms` with the sum of spoke durations. The wall-clock value includes the spoke barrier and supervisor call; use trace overlap below to verify concurrency.
4. Review the required-failure path in `evaluate_quorum` and `synthesize`: a failed `market-spoke` or `risk-spoke` must produce `insufficient_quorum` and block the supervisor call. The optional-failure run does not exercise this path.

Local schema checks do not substitute for live response evidence.

**Validate agent definitions and role behavior**

5. Find the project name in the final segment of `FOUNDRY_PROJECT_ENDPOINT` in `.env`. Open the [Microsoft Foundry portal](https://ai.azure.com), enable **New Foundry**, and select that project.
6. Select **Build** > **Agents**. Confirm that `market-spoke`, `risk-spoke`, `compliance-spoke`, and `research-supervisor` exist as prompt agents.
7. Open each agent's newest version and confirm its model matches `FOUNDRY_MODEL_NAME` and its instructions match `assets/portfolio-request.json`. Each application run creates new versions.
8. Open each spoke's newest version in the **Playground** and submit the prompt shown for that agent:

**`market-spoke`**

  ```text
  Request: Assess a synthetic balanced portfolio under a fictional rate shock.
  Assignment: Return market assumptions and evidence gaps.
  ```

**`risk-spoke`**

  ```text
  Request: Assess a synthetic balanced portfolio under a fictional rate shock.
  Assignment: Return risk drivers and limits.
  ```

**`compliance-spoke`**

  ```text
  Request: Assess a synthetic balanced portfolio under a fictional rate shock.
  Assignment: Return compliance caveats.
  ```

9. Verify the role boundaries:
   - `market-spoke` identifies assumptions and missing market evidence.
   - `risk-spoke` identifies risk drivers and analysis limits without providing investment advice.
   - `compliance-spoke` identifies policy caveats without performing the market or risk analysis.
10. Open `research-supervisor` in the **Playground** and submit this complete synthetic fan-in payload:

  ```json
  {
    "request": "Assess a synthetic balanced portfolio under a fictional rate shock.",
    "accepted_evidence": [
      {
        "agent": "market-spoke",
        "response_id": "playground-market-001",
        "text": "Assumption: the fictional scenario includes a rate increase. Evidence gaps: no holdings, duration, rate-shock magnitude, or market data were supplied.",
        "elapsed_ms": 0
      },
      {
        "agent": "risk-spoke",
        "response_id": "playground-risk-001",
        "text": "Potential drivers include duration and concentration, but exposure cannot be quantified without portfolio data. This is risk analysis, not investment advice.",
        "elapsed_ms": 0
      }
    ],
    "missing_agents": [
      "compliance-spoke"
    ]
  }
  ```

11. Confirm that the supervisor:
    - Uses only the two supplied evidence records.
    - Explicitly states that compliance evidence is missing.
    - Does not invent a compliance conclusion, portfolio holdings, exposure values, or a rate-shock magnitude.

Playground calls test agents independently. They do not reproduce parallel orchestration or prove which agents a saved console run invoked.

**Correlate service traces with application evidence**

12. Select **Agents** > **Traces**, set the time range to cover the normal run, and search for its saved response IDs. Allow several minutes for ingestion.
13. Compare the three spoke traces: overlapping start times and durations demonstrate concurrent calls. Confirm that the supervisor trace starts after the spoke responses complete.
14. Repeat for the optional-failure run. A compliance trace can still exist because fault injection occurs after the live call. Use the final JSON to verify exclusion from accepted evidence, the quorum decision, and the supervisor's caveat.

Service traces show Foundry calls and timing, not the Python semaphore, `asyncio.gather`, fault injection, or quorum code. Correlate them with the saved JSON; do not expect one end-to-end parent span. Client-side instrumentation, KQL, sampling, and alerts are covered in Lab 13.

## Task 7: Review the design

Record brief answers:

- Why does `pattern` remain `parallel` in both runs?
- Why must optional failure leave quorum ready while removing compliance evidence and adding a caveat?
- Which decisions belong in deterministic code rather than agent judgment?
- When would these specialists justify their coordination cost over a single agent, and what additional measurements would support that decision?

## Optional challenge: Add a guarded route

Add a synthetic high-risk request that selects sequential execution and requires the compliance spoke before the remaining assignment.

**Expected output:** `pattern` is `sequential`, the compliance result completes before the dependent spoke starts, and the final response identifies the selected route.

**Failure investigation:** Force one optional spoke to fail and explain from the quorum output whether the orchestrator continued, fell back, or failed closed.

## Task 8: Clean up

**Remove Azure resources**

1. Run the following commands:

```powershell
$env:AZURE_DEV_USER_AGENT='microsoft_foundry_skill'
azd down --purge --force
Remove-Item Env:AZURE_DEV_USER_AGENT
```

2. Confirm the resource group is deleted.
3. Remove generated response artifacts.

**Deactivate the virtual environment**

4. Run this command in every terminal where `(.venv)` appears in the prompt:

```powershell
deactivate
```

5. Confirm that `(.venv)` no longer appears before changing to another lab directory.

## Summary

You implemented live parallel specialist calls, synchronization, quorum policy, failure isolation, and supervisor synthesis in Microsoft Foundry.

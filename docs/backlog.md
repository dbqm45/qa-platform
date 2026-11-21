# QA Automation Platform — Solo Developer Task Backlog

## Working Rules

- Work on one task at a time.
- Complete and verify each task before starting the next one.
- Keep every task small enough to implement, review, and test independently.
- Use AI to assist with implementation, but review all generated code.
- Do not introduce abstractions without a concrete use case.
- Do not modify application source code or repositories.
- Prefer deterministic execution over AI-driven execution.
- Keep the platform runnable locally throughout development.
- Update documentation whenever an architectural decision or public interface changes.

## Priority Definitions

- **P0 — Essential:** Required for the first working MVP.
- **P1 — Important:** Improves reliability, usability, or maintainability.
- **P2 — Later:** Can be postponed until after the MVP.

## Status

| Task | Status |
|------|--------|
| TASK-001 | Done |
| TASK-002 | Done |
| TASK-003 | Done |
| TASK-004 | Done |
| TASK-005 | Done |
| TASK-007 | Done |
| TASK-010 | Done |
| TASK-011 | Done |
| TASK-006 | Done |
| TASK-008 | Done |
| TASK-009 | Done |
| TASK-012 | Done |
| TASK-013 | Done |
| TASK-016 | Done |
| TASK-014 | Done (revised scope: `repo add` / `env add`) |
| TASK-017 | Done — Markdown deferred (ADR-010) |
| TASK-018 | Done |
| TASK-019 | Done |
| TASK-020 | Done |
| TASK-021 | Done |
| TASK-022 | Done |
| TASK-023 | Done |
| TASK-024 | Done |
| TASK-025 | Done — registry core (registration, conflicts, resolution); step categories and implementations in TASK-031 |
| TASK-026 | Done |
| TASK-027 | Done |
| TASK-028 | Done — coverage map in tests/unit/test_compilation_pipeline.py |
| TASK-029 | Done — adapters provide resources, runner executes steps (ADR-015) |
| TASK-030 | Done |
| TASK-032 | Done |
| TASK-034 | Done — local target only |
| TASK-035 | Done |
| TASK-036 | Done |
| TASK-038 | Done |
| TASK-039 | Done |
| TASK-040 | Done |
| TASK-041 | Done |
| TASK-042 | Done |
| TASK-043 | Done |
| TASK-044 | Done — screenshots, traces, console errors, page URL; failed step details are in the result |
| TASK-031 | Done — navigation, forms, UI assertions, API requests and assertions, token authentication |
| TASK-033 | Done |
| TASK-070 | Done |
| TASK-062 | Done |
| TASK-059 | Done |
| TASK-071 | Done |
| TASK-072 | Done — first milestone reached (tests/integration/test_vertical_slice.py) |
| TASK-066 | Done — logs follow with TASK-037 |
| TASK-045 | Done |
| TASK-046 | Done |
| TASK-047 | Done |
| TASK-048 | Done |
| TASK-049 | Done |
| TASK-067 | Done — hard limits need POSIX + main thread (ADR-019) |
| TASK-068 | Done |
| TASK-037 | Done |
| TASK-063 | Done |
| TASK-073 | Done — coverage map in tests/integration/test_platform_workflows.py; 98% line coverage |
| TASK-074 | Done — docs/getting-started.md, replayed literally in a fresh clone |
| TASK-055 | Done — dependency configuration (real/mock) is part of TASK-051 |
| TASK-053 | Done — FULL mode with correlated results and evidence; mocked dependencies are part of TASK-051 |
| TASK-052 | Done — BE mode runs API scenarios without a browser |
| TASK-051 | Done for the MVP — FE mode runs browser scenarios against real services; mocked dependencies deferred post-MVP (runner refuses `mock` plans) |
| TASK-050 | Done — plans from specification, mode, category, environment and adapter capabilities; unsupported combinations rejected |
| TASK-058 | Done — metadata in SQLite, results.json per execution, retrieval via qa execution |
| TASK-057 | Done — qa_schemas.results (TestResult, StepResult, Failure, ExecutionReport) |
| TASK-075 | Done — MVP frozen; review in docs/mvp-review.md |
| TASK-015 | Done — qa project show (no secret values) |
| TASK-065 | Done — qa --version, Ctrl-C exits 130 (execution cancelled), internal errors in one line (QA_DEBUG=1 for traceback) |
| TASK-128 | In progress — CI workflow (lint, types, tests with Chromium, pip-audit) in .github/workflows/ci.yml |

---

## Phase 0 — Project Setup

### TASK-001 — Create the project repository (P0)
- Create the `qa-platform` repository.
- Initialize Git.
- Add a `.gitignore`.
- Add a basic `README.md`.
- Define the initial Python version.

Acceptance criteria:
- The repository is initialized.
- The project can be cloned and opened locally.
- No temporary files or secrets are committed.

### TASK-002 — Configure the Python development environment (P0)
- Create the Python virtual environment.
- Configure dependency management.
- Add the initial development dependencies.
- Document installation commands.

Acceptance criteria:
- A new developer can install the environment using documented commands.
- Dependencies are reproducible.

### TASK-003 — Configure code quality tools (P0)
- Configure Ruff.
- Configure a static type checker.
- Configure pytest.
- Add basic test and lint commands.

Acceptance criteria:
- Linting and tests can be executed locally.
- The project has a consistent code quality baseline.

### TASK-004 — Create the initial project structure (P0)

```
qa-platform/
├── apps/
│   └── cli/
├── packages/
│   ├── qa_core/
│   ├── qa_schemas/
│   ├── qa_execution/
│   └── qa_reporting/
├── tests/
├── docs/
├── examples/
├── pyproject.toml
└── README.md
```

Acceptance criteria:
- All packages can be imported.
- The project has a clear separation between CLI, domain logic, execution, and reporting.

### TASK-005 — Add automated test execution (P0)
- Configure pytest.
- Add a test directory structure.
- Add one example unit test.
- Configure test discovery.

Acceptance criteria:
- Running the test command executes the example test successfully.

## Phase 1 — Core Domain and Configuration

### TASK-006 — Define core domain models (P0)
Project, Repository, Environment, Scenario, TestCase, TestSpecification,
ExecutionPlan, TestExecution, TestResult. Use Pydantic models.

Acceptance criteria:
- Models have explicit types and validation.
- Invalid data is rejected.
- Models can be serialized to and deserialized from JSON.

### TASK-007 — Define execution status values (P0)
READY, NEEDS_REVIEW, BLOCKED, UNSUPPORTED, PENDING, RUNNING, PASSED, FAILED, ERROR, CANCELLED.

Acceptance criteria:
- Statuses are defined centrally.
- Modules do not introduce their own conflicting status values.

### TASK-008 — Define the Test Specification schema (P0)
Specification ID, source scenario, test cases, preconditions, steps, expected
results, required capabilities, metadata.

Acceptance criteria:
- A test scenario can be represented without depending on a specific runner.
- The schema is versioned.
- A sample specification can be serialized to JSON.

### TASK-009 — Define the Execution Plan schema (P0)
Execution mode, test category, target environment, selected adapters,
dependency configuration, execution settings.

Acceptance criteria:
- The same Test Specification can be used to create different Execution Plans.
- Execution Plans can be serialized and validated independently.

### TASK-010 — Define execution modes (P0)
FE, BE, FULL, CONTRACT.

Acceptance criteria:
- Modes are defined centrally.
- Invalid modes are rejected.
- The mode is stored in the Execution Plan.

### TASK-011 — Define test categories (P0)
FUNCTIONAL, VISUAL, ACCESSIBILITY, PERFORMANCE, SECURITY, CONTRACT.

Acceptance criteria:
- Test category is independent of execution mode.
- The platform supports combinations such as `FULL + FUNCTIONAL` and `BE + FUNCTIONAL`.

### TASK-012 — Add YAML configuration support (P0)
- Define the project configuration format.
- Add YAML loading and validation.
- Add sensible defaults.
- Provide useful configuration errors.

Acceptance criteria:
- A valid YAML file can be loaded into typed configuration models.
- Invalid configuration produces a readable error.
- Configuration does not contain hardcoded credentials.

## Phase 2 — Project Management

### TASK-013 — Implement project initialization: `qa init` (P0)
- Create the local platform directory, default configuration, initial project structure, local storage.

Acceptance criteria:
- A new project can be initialized from an empty directory.
- Running initialization twice does not destroy existing data.

### TASK-014 — Implement project configuration: `qa project repo add` / `qa project env add` (P0)
> Revised after TASK-013: `qa init` already creates the project (id, name,
> scenario directory, default environment), so this task edits an existing
> `qa.yaml` instead of adding a project.

- `qa project repo add NAME [--path PATH] [--url URL]` — add a repository.
- `qa project env add NAME [--base-url URL] [--service NAME=URL ...] [--timeout S] [--default]`
  — add an environment, optionally making it the default.

Acceptance criteria:
- Project configuration is saved locally in `qa.yaml`.
- Configuration can be loaded after restarting the CLI.
- The resulting `qa.yaml` is validated before it is written; invalid input changes nothing.
- Duplicate names are rejected.
- Existing content of `qa.yaml` (including comments) is preserved.

### TASK-015 — Implement project inspection: `qa project show` (P1)
Project information, configured repositories, environments, scenario locations, available adapters.

Acceptance criteria:
- The command displays the current project configuration.

### TASK-016 — Add local persistence (P0)
- Introduce SQLite, database initialization, repositories for projects and executions, migrations.

Acceptance criteria:
- Project and execution metadata survive application restarts.
- Database access is separated from business logic.

## Phase 3 — Scenario Import and Parsing

### TASK-017 — Define the scenario source interface (P0)
Initial source types: local Gherkin files, Markdown files.

Acceptance criteria:
- Scenario loading is independent of the CLI.
- Additional sources can be added without changing the parser.

### TASK-018 — Implement Gherkin file discovery (P0)
- Discover `.feature` files; configurable directories; nested directories; ignore unsupported files.

Acceptance criteria:
- All supported scenario files in a configured directory can be discovered.

### TASK-019 — Implement Gherkin parsing (P0)
Feature, Rule, Background, Scenario, Scenario Outline, Examples, Given, When, Then, And, But.

Acceptance criteria:
- Valid Gherkin files are converted into normalized scenario models.
- Invalid syntax produces useful parsing errors.
- Parsing does not require an LLM.

### TASK-020 — Add scenario validation (P0)
Scenario structure, empty steps, missing scenario names, unsupported constructs, invalid Examples tables.

Acceptance criteria:
- Invalid scenarios are identified before compilation.
- Validation errors reference the source file and relevant location.

### TASK-021 — Preserve scenario traceability (P0)
Original file path, scenario name, feature name, source content hash, line information.

Acceptance criteria:
- Every normalized scenario can be traced back to its source file.
- Scenario changes can be detected using content hashes.

### TASK-022 — Add a scenario validation CLI command: `qa scenario validate` (P0)

Acceptance criteria:
- The command validates all configured scenarios.
- It displays validation errors and a summary.
- It returns a non-zero exit code when validation fails.

## Phase 4 — Test Specification and Compilation

### TASK-023 — Implement scenario-to-specification conversion (P0)

Acceptance criteria:
- Each supported scenario produces a valid Test Specification.
- Original scenario information is preserved.
- No execution-specific details are embedded in the specification.

### TASK-024 — Define the step representation (P0)
Step type, original text, normalized action, parameters, expected result, source location.

Acceptance criteria:
- Steps have a consistent structure.
- Unknown steps can be represented without inventing their meaning.

### TASK-025 — Implement step resolution (P0)
A Step Registry maps normalized steps to registered implementations.

Acceptance criteria:
- Registered steps can be resolved deterministically.
- Unknown steps are reported.
- Step resolution does not invoke an LLM.

### TASK-026 — Implement compilation statuses (P0)
READY, NEEDS_REVIEW, BLOCKED, UNSUPPORTED.

Acceptance criteria:
- Compilation produces an explicit status.
- Unknown expected results cannot silently become executable assertions.
- Blocked specifications cannot be executed.

### TASK-027 — Add a compilation CLI command: `qa scenario compile` (P0)

Acceptance criteria:
- The command parses and compiles scenarios.
- It saves generated Test Specifications.
- It displays compilation status and unresolved steps.

### TASK-028 — Add compilation tests (P0)
Valid/invalid scenarios, unknown steps, missing expected results, Scenario Outlines, multiple scenarios in one feature.

Acceptance criteria:
- Compilation behavior is covered by automated tests.
- Repeated compilation of unchanged input produces equivalent specifications.

## Phase 5 — Adapter and Step Registry

### TASK-029 — Define the TestAdapter interface (P0)

```python
class TestAdapter:
    def get_capabilities(self): ...
    def validate(self, specification): ...
    def prepare(self, execution_context): ...
    def execute(self, test_case): ...
    def collect_evidence(self): ...
    def cleanup(self): ...
```

Acceptance criteria:
- Adapters implement a common contract.
- The execution engine does not depend on a specific testing framework.

### TASK-030 — Implement the Adapter Registry (P0)
Register, discover, resolve by capability, reject unsupported requests.

Acceptance criteria:
- The platform can select an adapter based on declared capabilities.
- Missing capabilities produce explicit errors.

### TASK-031 — Implement the Step Registry (P0)
Categories: navigation, forms, UI assertions, API requests, API assertions, authentication.

Acceptance criteria:
- Steps can be registered and resolved.
- Duplicate or conflicting registrations are detected.
- Step implementations can be tested independently.

### TASK-032 — Implement parameter validation (P0)

Acceptance criteria:
- Invalid step parameters are rejected before execution.

### TASK-033 — Add step implementation tests (P0)

Acceptance criteria:
- Every initial step implementation has automated tests.

## Phase 6 — Execution Engine and Local Runner

### TASK-034 — Define the ExecutionTarget interface (P0)
Local, Remote, Kubernetes — initially implement only Local.

Acceptance criteria:
- Execution logic is separated from execution infrastructure.
- Local execution does not depend on remote services.

### TASK-035 — Implement the Local Runner (P0)

Acceptance criteria:
- A Test Specification can be executed locally.
- Execution results are returned in a normalized format.
- Cleanup runs even when a test fails.

### TASK-036 — Implement execution lifecycle management (P0)
PENDING, RUNNING, PASSED, FAILED, ERROR, CANCELLED.

Acceptance criteria:
- Every execution has a unique ID.
- Execution status is persisted.
- Failed executions do not get reported as successful.

### TASK-037 — Implement execution logging (P0)
Execution ID, scenario ID, timestamps, adapters, mode, results, errors.

Acceptance criteria:
- Logs can be associated with a specific execution.
- Logs do not expose secrets.

### TASK-038 — Add execution error handling (P0)
APPLICATION_BUG, TEST_IMPLEMENTATION_ERROR, ENVIRONMENT_ERROR, TEST_DATA_ERROR,
DEPENDENCY_ERROR, REQUIREMENT_AMBIGUITY.

Acceptance criteria:
- Execution errors have explicit classifications.
- An unhandled internal error cannot be reported as a normal test failure.

## Phase 7 — FE Testing with Playwright

### TASK-039 — Add Playwright integration (P0)
Acceptance: the platform can launch a browser through the adapter.

### TASK-040 — Implement browser navigation steps (P0)
Open URL, navigate to URL, reload, navigate back. Navigation failures produce useful evidence.

### TASK-041 — Implement UI interaction steps (P0)
Click, fill, select option, check checkbox, submit form. Validated parameters; element resolution failures reported explicitly.

### TASK-042 — Implement UI assertion steps (P0)
Visible, hidden, text present, URL matches, enabled, input value matches. Deterministic results with diagnostics.

### TASK-043 — Implement locator strategy (P1)
Preference: `data-testid` → role + accessible name → label → text → CSS.
Configurable; ambiguous/missing locators reported; CSS not silently preferred.

### TASK-044 — Add browser evidence collection (P0)
Screenshots, traces, console errors, page URL, failed step details.
Evidence linked to execution and test case; collection does not change the outcome.

## Phase 8 — BE/API Testing

### TASK-045 — Add HTTPX integration (P0)
HTTP adapter, configurable base URLs, request timeouts.

### TASK-046 — Implement API request steps (P0)
GET, POST, PUT, PATCH, DELETE. Validated inputs; sensitive headers masked in logs.

### TASK-047 — Implement API assertions (P0)
Status code, headers, JSON field values/existence, body validation. Deterministic; failures redacted.

### TASK-048 — Add API response evidence (P0)
Request metadata, status, headers, safe body, duration. Redacted, linked to execution.

### TASK-049 — Add API adapter tests (P0)
Success, HTTP errors, timeouts, invalid responses, auth failures, assertion failures.

## Phase 9 — Test Modes and Environments

### TASK-050 — Implement Execution Plan generation (P0)
From specification, mode, category, environment, adapter capabilities. Validated; unsupported combinations rejected.

### TASK-051 — Implement FE mode (P0)
### TASK-052 — Implement BE mode (P0) — no browser launched.
### TASK-053 — Implement FULL mode (P0) — UI + API, correlated results.
### TASK-054 — Implement CONTRACT mode (P1) — OpenAPI validation without the full stack.

### TASK-055 — Implement environment configuration (P0)
Local, Development, QA, Staging: base URLs, endpoints, timeouts, env vars, dependencies.
Secrets referenced securely, never stored in plain text.

### TASK-056 — Add test data isolation (P1)
Execution-specific identifiers, setup/cleanup hooks; production data never modified by default.

## Phase 10 — Reporting and Execution History

### TASK-057 — Define the normalized result schema (P0)
Test case ID, status, duration, failure classification, error message, evidence references.

### TASK-058 — Implement execution history (P0)
Retrievable after CLI restart.

### TASK-059 — Implement HTML reporting (P0)
Summary, passed/failed, durations, classifications, errors, evidence links; opens locally.

### TASK-060 — Implement JSON reporting (P1)
Versioned schema, consumable by CI/CD.

### TASK-061 — Implement execution fingerprinting (P1)
Scenario/spec hashes, repo SHAs, environment/config hashes, adapter and runner versions.

## Phase 11 — CLI Experience

### TASK-062 — Implement `qa test --scenario login.feature --mode full --environment staging` (P0)
### TASK-063 — Implement `qa execution show <execution_id>` (P0)
### TASK-064 — Implement `qa rerun --failed-only <execution_id>` (P1)
### TASK-065 — Improve CLI error messages (P1)

## Phase 12 — Security and Reliability

### TASK-066 — Implement secret redaction (P0)
### TASK-067 — Add execution timeouts (P0)
### TASK-068 — Add safe cleanup handling (P0)
### TASK-069 — Add execution safety policies (P1)

## Phase 13 — MVP Validation

### TASK-070 — Create an example test application (P0)
Login page, basic form, simple API, a few business rules.

### TASK-071 — Create example Gherkin scenarios (P0)
Successful/invalid login, form submission, API success, API validation error, UI-to-API interaction.

### TASK-072 — Execute the first complete vertical slice (P0)

```
Gherkin file → Scenario Parser → Test Specification → Step Registry
→ Execution Plan → Local Runner → Playwright / HTTPX
→ Test Results → Evidence → HTML Report
```

Acceptance criteria:
- A Gherkin scenario can be executed end to end.
- Results are deterministic in a stable test environment.
- Evidence and report are generated.
- The complete flow works without an LLM.

### TASK-073 — Add end-to-end platform tests (P0)
### TASK-074 — Write MVP installation documentation (P0)
### TASK-075 — Freeze and review MVP scope (P0)

---

## Post-MVP Backlog

**Knowledge and Integrations:** TASK-076 Git repository discovery · 077 repository
metadata extraction · 078 tech stack detection · 079 OpenAPI discovery · 080 service
dependency mapping · 081 GitHub · 082 Jira · 083 Figma · 084 SwaggerHub · 085 MCP
abstractions · 086 versioned Knowledge Snapshots · 087 incremental knowledge refresh.

**AI-Assisted Test Compilation:** TASK-088 Model Provider interface · 089 first LLM
provider · 090 task complexity classification · 091 Model Router · 092 requirement
analysis · 093 step mapping · 094 generated step implementations · 095 generated code
validation and sandboxing · 096 approval workflow · 097 failure diagnostics · 098 model
invocation logging and cost tracking · 099 version-aware AI result caching.

**Advanced Testing:** TASK-100 visual regression · 101 accessibility (axe-core) · 102
performance (k6) · 103 security testing · 104 contract testing (Schemathesis) · 105
event-driven testing · 106 database adapters · 107 flaky test detection · 108 change
impact analysis · 109 test coverage mapping.

**Central Platform and AWS:** TASK-110 FastAPI app · 111 project/execution API · 112
PostgreSQL · 113 remote runner communication · 114 background queue · 115 Docker
runners · 116 S3 evidence · 117 AWS Secrets Manager · 118 authn/authz · 119 audit
logging · 120 ECS evaluation · 121 Kubernetes evaluation · 122 centralized monitoring.

**User Interface and CI/CD:** TASK-123 Web UI requirements · 124 project overview · 125
scenario management · 126 execution history · 127 report/evidence viewer · 128 CI/CD
integration · 129 GitHub Actions examples · 130 webhook-triggered execution.

---

## Recommended Development Sequence

1. Project setup and quality tools.
2. Core domain models.
3. Project initialization and configuration.
4. Gherkin parsing and validation.
5. Test Specification generation.
6. Step Registry.
7. Adapter interface.
8. Local Runner.
9. Playwright integration.
10. First FE scenario execution.
11. HTTPX integration.
12. First BE scenario execution.
13. Execution modes and environments.
14. Evidence collection.
15. Reporting and persistence.
16. CLI improvements.
17. Security and reliability.
18. End-to-end MVP validation.

**Important:** Do not start AI agents, MCP integrations, AWS deployment, or a Web UI
before the deterministic local execution flow works.

## Definition of Done

A task is complete only when:
- The implementation works.
- Relevant automated tests pass.
- Code quality checks pass.
- Errors are handled explicitly.
- No application source code has been modified.
- Documentation is updated where necessary.
- The change has been reviewed by the developer.
- The result is committed to Git.

## First Milestone

Execute one Gherkin login scenario against a local or staging application using
Playwright, save a screenshot, and generate a test report. Do not expand the
architecture until this flow works reliably.

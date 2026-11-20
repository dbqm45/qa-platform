# qa-platform

Local-first QA automation platform. It turns Gherkin scenarios into normalized
Test Specifications and executes them deterministically through adapters
(Playwright for UI, HTTPX for APIs), producing results, evidence and reports.

> **Status:** early development — Phase 0 (project setup). Nothing is runnable yet.

## Principles

- Deterministic execution first; no LLM is required for the core flow.
- The platform never modifies the source code of the applications under test.
- Runs locally end to end; no remote services are required.
- No secrets in the repository or in configuration files.

## Requirements

- Python **3.12+** (pinned in `.python-version`)
- Git

Installation and development commands will be documented in TASK-002.

## Roadmap

The full task backlog lives in [`docs/backlog.md`](docs/backlog.md).

**First milestone:** execute one Gherkin login scenario against a local
application using Playwright, save a screenshot and generate a test report.

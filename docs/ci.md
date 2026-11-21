# CI/CD

Tests of a qa-platform project run in a pipeline the same way as locally:
`qa test` per scenario file with `--json`, then `qa summary` for one
overview. For GitHub Actions the repository provides a ready action.

## GitHub Actions

Copy [`examples/ci/qa.yml`](../examples/ci/qa.yml) to `.github/workflows/qa.yml`
in the repository of your test project (the one with `qa.yaml`):

```yaml
- uses: actions/checkout@v5
- uses: dbqm45/qa-platform/.github/actions/qa-test@main   # pin a commit SHA or tag
  with:
    environment: staging
  env:
    SHOP_PASSWORD: ${{ secrets.SHOP_PASSWORD }}
```

The action:

1. installs the platform with the exact dependency versions of its
   `uv.lock` (as tested by the platform's own CI) and, unless
   `browser: "false"`, Chromium;
2. runs `qa init` (a fresh checkout has no `.qa/`; nothing existing is
   changed), then `qa test --json` for every matching scenario file; one file that
   fails does not stop the others;
3. writes the Markdown overview to the job summary and the plain overview to
   the log;
4. uploads `.qa/executions` (results, HTML reports, evidence, logs) and the
   JSON summaries as an artifact, also when tests failed;
5. fails the job unless every scenario file was executed and passed.

| Input | Default | Meaning |
|-------|---------|---------|
| `project` | `.` | directory with `qa.yaml` |
| `scenarios` | `scenarios/**/*.feature` | files relative to the project; bash globs, several separated by spaces (no `{a,b}`) |
| `environment` | `default_environment` | target environment |
| `args` | | more `qa test` arguments, e.g. `--mode contract --mock api` |
| `browser` | `true` | install Chromium |
| `artifact-name` | `qa-results` | name of the uploaded artifact; use different names when the action runs twice in a job |

Output `ok` is `"true"` if everything passed.

- **Secrets** go into the `env:` of the step, from GitHub secrets, and are
  referenced as `${NAME}` in `qa.yaml` and scenarios; the platform masks them
  in every report ([secrets.md](secrets.md)).
- A scenario file that cannot run at all (e.g. an unknown environment) has
  no summary; the action reports it as an error with the file name.
- Pin the action to a commit SHA or a tag rather than `main`, so the platform
  version only changes when you decide; [fingerprints](execution.md#fingerprints)
  record the versions used in every execution.
- The platform's own CI runs this action against the Example Shop
  (`examples/`) on every push, including a contract-mode run, so the action
  and the example workflow are known to work.

## Other CI systems

The same steps with the CLI, here for any shell-based pipeline:

```bash
qa init .   # a fresh checkout has no .qa/; this only adds what is missing
status=0
for file in scenarios/*.feature; do
  qa test --scenario "$file" --environment staging --json "build/qa/$(basename "$file" .feature).json" || status=1
done
qa summary build/qa/*.json --markdown > qa-summary.md
qa summary build/qa/*.json || status=1
exit $status
```

Keep `.qa/executions/` as the pipeline's artifacts.

## `qa summary`

```bash
qa summary build/qa/*.json [--markdown]
```

reads the [JSON summaries](execution.md#json-summary-for-ci) of `qa test` or
`qa rerun` and prints one overview: one line per scenario file, every
failure with test case, step, classification and message, and the reports
of what did not pass. Exit code `0` only if every run passed; a file that
is missing or not a summary is an error (`1`).

```
OK    scenarios/api.feature on staging: 4 passed
FAIL  scenarios/login.feature on staging: 2 passed, 1 failed
      login.successful-login, step 7: application_bug: the page does not show 'Welcome, Bob' (page: https://staging.example.com/dashboard)

2 scenario files: 6 passed, 1 failed -- NOT all passed
```

# AgentLab — operational experiments

Observability tells you **what happened**. AgentLab tells you **which design should go to
production** — by comparing variants of the same agent workload on real operational telemetry
instead of answer quality.

## The idea

Most evaluation tools compare correctness, answer quality, benchmark scores. AgentLab compares
what actually matters when the system runs:

- cost
- latency
- token usage
- failures
- runaway loops
- circuit-breaker trips

All measured from telemetry SigNoz already collects. **SigNoz is the dashboard** — AgentLab
adds no UI and no separate database.

## One function call

```python
from taraol import Experiment

result = (
    Experiment("docs-assistant", description="prompt comparison", author="Fraol")
    .compare("terse", prompt="Explain OpenTelemetry in exactly one sentence.")
    .compare("verbose", prompt="Explain OpenTelemetry in three detailed paragraphs.")
    .compare("broken")  # a failing variant is recorded, not fatal
    .run(answer)  # answer(ctx) is called once per variant
)
```

- `.compare(name, **knobs)` and `.variant(name, **knobs)` are the same thing — knobs are plain
  keywords, read back as attributes: `ctx.prompt`, `ctx.model`, `ctx.loop_mode`.
- The workload receives the variant; run context (`id`, `run_id`, metadata) is available via
  `taraol.current_experiment()`.
- A variant that raises is recorded `status=failed` and the run continues — an experiment
  runner must never abort on one failure.
- `result.summary()` returns the same table as the CLI (needs the `[detection]` extra and a
  few seconds for batched telemetry to land).

## The hierarchy

```
Experiment
    │
    ├── Run (one .run() = one shared run_id)
    │      ├── Variant A ── Trace(s)
    │      ├── Variant B ── Trace(s)
    │      └── Variant C ── Trace(s)
    │
    └── Future runs — never mixed with today's
```

Every span produced during a variant automatically carries `experiment.id`,
`experiment.variant`, and `experiment.run_id` — including cross-process A2A hop spans.
Repeated executions stay isolated: filter by `run_id` for one run, widen the SigNoz time
range to watch regression across runs.

## A variant is just configuration

Anything that changes your agent can become a variant:

```python
.compare("gpt4",    model="gpt-4o")
.compare("gemini",  model="gemini-2.5-flash")

.compare("baseline", loop_mode="off")          # topology / routing
.compare("runaway",  loop_mode="storm")

.compare("comfort",    budget=2500)            # domain knobs
.compare("shoestring", budget=800)
```

**Privacy note:** knob *values* may contain prompt text, so they are treated as content — the
`experiment_run` log record carries them only when the process opted into content capture.
Knob *names* are always logged.

## Reproducibility metadata

`ExperimentMetadata.collect()` auto-fills description, author, git commit, Python version, and
taraol version onto every run record — six months later you know exactly what produced a run.

## The run record

Each variant emits one content-free `experiment_run` log record:
`experiment.status` (success | failed), `experiment.duration_ms`, the metadata above, and the
config keys. Failures include a truncated error string.

## Reading the results

### Bundled dashboard

```bash
taraol dump-dashboards ./dashboards     # then SigNoz → Dashboards → Import JSON
```

Panels split by `experiment.variant`: direct LLM cost, output tokens, P95 latency, runaway
loops, breaker trips, failures.

### CLI

```bash
taraol experiment summary <experiment-id> [--run <run_id>] [--since <sec>]
taraol experiment diff <run1> <run2>
```

The CLI uses a provider abstraction: the SigNoz Query API when `SIGNOZ_API_KEY` is set (Cloud),
else a direct ClickHouse fallback (`SIGNOZ_CLICKHOUSE_URL`, works on Community) — the same
selection the detection watcher uses.

A real run on the distributed 5-service mesh (live Gemini):

```
variant       cost$   tokens  agents   avg ms  loops  breakers  fails  health
baseline     0.0116     4127       5    42460      0         0      0    91.5
runaway      0.0266     9457       5   130972      1         1      0    58.8

Highest Operational Health: baseline
```

The `loops` and `breakers` columns come from the watcher detecting the runaway storm **in
telemetry** — the signals carry the experiment variant that caused them.

### Health score

```
health = 100 − 10·loops − 5·breaker_trips − 0.2·latency_s − 0.1·cost_usd − 20·failures
```

Every weight is overridable (`HealthScore(loop_weight=..., failure_weight=...)`). "Highest
Operational Health" is deliberately a factual read, not a universal "winner" — one team
optimizes cost, another latency, another stability. Tune the weights to what you optimize.

## Why this is different

Suppose two prompts produce equally good answers. Evaluation tools say "both are fine."
Telemetry says one costs 10× more and runs 3× slower. Or two routings both finish — but one
loops 12 times and trips a breaker on the way. Prompt evaluation never shows this. AgentLab
does — which makes it an **operational experimentation framework**, not another prompt-eval
tool.

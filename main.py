"""taraol — compare AI agent variants with one function call.

@agent + @chat are the entire instrumentation: tokens, cost, and (opted-in) prompt/completion
are read straight off the returned SDK response. Each variant owns its whole configuration —
here the prompt; swap in model / temperature / tools the same way. A deliberately broken
variant proves a failure is recorded, not fatal.

.env: GEMINI_API_KEY, OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://localhost:4317)
"""

import os

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, agent, chat, instrument

load_dotenv()
# Label this app in SigNoz's Environment filter (standard OTel resource attribute).
os.environ.setdefault("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=quickstart")
instrument("assistant", capture_content=True)  # OTLP endpoint comes from the environment

MODEL = "gemini-2.5-flash"
client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment


@chat(MODEL)  # tokens + cost + captured content — all read off the returned response
def think(prompt: str):
    return client.models.generate_content(model=MODEL, contents=prompt)


@agent(name="assistant")  # step span; experiment.id / variant / run_id ride along
def ask(ctx) -> None:
    print(f"  [{ctx.name}] {think(ctx.prompt).text[:64].strip()}...")


result = (
    Experiment("docs-assistant", description="terse vs verbose prompt", author="Fraol")
    .compare("terse", prompt="Explain what OpenTelemetry is in exactly one sentence.")
    .compare("verbose", prompt="Explain what OpenTelemetry is in three detailed paragraphs.")
    .compare("broken")  # owns no prompt -> AttributeError; the run continues
    .run(ask)
)

print(f"\nExperiment: {result.experiment_id}")
print(f"Run ID:     {result.run_id}\n")
print(f"{'variant':<12}{'status':<8}{'duration':>10}")
print("-" * 30)
for r in result.results:
    duration = f"{r.duration_ms:.0f} ms" if r.status == "success" else "-"
    print(f"{r.variant:<12}{'ok' if r.status == 'success' else 'FAIL':<8}{duration:>10}")
print("-" * 30)
ok = sum(r.status == "success" for r in result.results)
print(f"{ok} succeeded, {len(result.results) - ok} failed")
print(
    "\nCompare in SigNoz:\n  SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 "
    f"taraol experiment summary {result.experiment_id} --run {result.run_id}"
)

"""taraol quickstart — compare AI agent variants with one function call.

Two decorators are the entire instrumentation: @agent opens the step span, @chat reads
tokens, cost, and (opted-in) prompt/completion straight off the returned SDK response.
The experiment: a docs assistant — does a terse prompt beat a verbose one on cost and
latency? A third, intentionally broken variant proves a failure is recorded, not fatal.

Setup (.env): GEMINI_API_KEY, OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://localhost:4317).
Read back:    SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 \
                  taraol experiment summary docs-assistant --run <run_id>
"""

import os

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, Variant, agent, chat, instrument

# --- setup ---------------------------------------------------------------------------

load_dotenv()

MODEL = "gemini-2.5-flash"

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"])
instrument("assistant", capture_content=True)  # OTLP endpoint comes from the environment

QUESTION = "Explain what OpenTelemetry is."
PROMPTS = {
    "terse": f"{QUESTION} Answer in exactly one sentence.",
    "verbose": f"{QUESTION} Answer in three detailed paragraphs.",
}

# --- the agent (all telemetry = these two decorators) ----------------------------------


@chat(MODEL)  # tokens + cost + captured content, all read off the returned response
def think(prompt: str):
    return client.models.generate_content(model=MODEL, contents=prompt)


@agent(name="assistant")  # step span; experiment.id / variant / run_id ride along
def ask(variant: Variant) -> None:
    text = think(PROMPTS[variant.style]).text  # "broken" has no such style -> KeyError
    print(f"  [{variant.name}] {text[:64].strip()}...")


# --- run the experiment -----------------------------------------------------------------

result = (
    Experiment("docs-assistant", description="terse vs verbose prompt", author="Fraol")
    .variant("terse", style="terse")
    .variant("verbose", style="verbose")
    .variant("broken", style="does-not-exist")  # proves failure-capture
    .run(ask)
)

# --- report ------------------------------------------------------------------------------

WIDTH = 58
print(f"\nExperiment  {result.experiment_id}")
print(f"Run         {result.run_id}")
print("-" * WIDTH)
print(f"{'variant':<12}{'status':<12}{'duration':>12}")
for r in result.results:
    print(f"{r.variant:<12}{r.status:<12}{r.duration_ms:>9.0f} ms")
    if r.error:
        print(f"{'':<12}{r.error[:WIDTH - 12]}")
print("-" * WIDTH)
ok = sum(r.status == "success" for r in result.results)
print(f"{ok} succeeded, {len(result.results) - ok} failed")
print(
    "\nCompare:  SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 "
    f"taraol experiment summary {result.experiment_id} --run {result.run_id}"
)
# (result.summary() returns the same table from code — give the collector a few
#  seconds after .run() for the batched telemetry to land.)

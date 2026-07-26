"""taraol quickstart — compare AI agent variants with one function call.

@agent + @chat are the entire instrumentation: tokens, cost, and (opted-in) prompt/completion
are read straight off the returned SDK response. The experiment: a docs assistant — does a
terse prompt beat a verbose one on cost and latency? A deliberately broken variant proves a
failure is recorded, not fatal.

.env: GEMINI_API_KEY, OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://localhost:4317)
"""

import os

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, Variant, agent, chat, instrument

load_dotenv()
instrument("assistant", capture_content=True)  # OTLP endpoint comes from the environment

MODEL = "gemini-2.5-flash"
client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"])

PROMPTS = {
    "terse": "Explain what OpenTelemetry is. Answer in exactly one sentence.",
    "verbose": "Explain what OpenTelemetry is. Answer in three detailed paragraphs.",
}


@chat(MODEL)  # tokens + cost + captured content — all read off the returned response
def think(prompt: str):
    return client.models.generate_content(model=MODEL, contents=prompt)


@agent(name="assistant")  # step span; experiment.id / variant / run_id ride along
def ask(variant: Variant) -> None:
    print(f"  [{variant.name}] {think(PROMPTS[variant.style]).text[:64].strip()}...")


result = (
    Experiment("docs-assistant", description="terse vs verbose prompt", author="Fraol")
    .variant("terse", style="terse")
    .variant("verbose", style="verbose")
    .variant("broken", style="does-not-exist")  # unknown style -> KeyError; run continues
    .run(ask)
)

print(f"\n{result.experiment_id}  run {result.run_id}")
for r in result.results:
    mark = "ok  " if r.status == "success" else "FAIL"
    note = f"  ({r.error})" if r.error else ""
    print(f"  {mark} {r.variant:<9}{r.duration_ms:>7.0f} ms{note}")
print(
    "\nCompare:  SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 "
    f"taraol experiment summary {result.experiment_id} --run {result.run_id}"
)

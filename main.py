"""Real integration test: taraol against live Gemini + a running SigNoz.

The 2-decorator DX, end to end. ``@chat`` extracts tokens + cost from the returned SDK
response automatically (google-genai / OpenAI / Anthropic shapes) — the only explicit
telemetry call left is ``record_chat_content``, because content capture is opt-in by design.

The AgentLab experiment: a terse-vs-verbose prompt A/B, plus one intentionally broken
variant (unknown prompt style -> KeyError) to prove failure-capture. Every span carries
experiment.id / variant / run_id; each variant also emits one experiment_run log.

Read it back (the run_id is printed below):

    SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 taraol experiment summary prompt-style-ab --run <run_id>

Needs a running SigNoz, GEMINI_API_KEY (or GOOGLE_API_KEY), and
OTEL_EXPORTER_OTLP_ENDPOINT in .env — no endpoint is hardcoded here, so the same file
runs against local SigNoz, a team server, or SigNoz Cloud unchanged.
"""

import os

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, Variant, agent, chat, instrument, record_chat_content

load_dotenv()

# .env here holds GEMINI_API_KEY; the google-genai SDK reads GOOGLE_API_KEY.
API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash"
EXPERIMENT_ID = "prompt-style-ab"

client = genai.Client(api_key=API_KEY)

instrument("assistant", capture_content=True)  # endpoint comes from the environment

QUESTION = "Explain what OpenTelemetry is."
PROMPTS = {
    "terse": f"{QUESTION} Answer in exactly one sentence.",
    "verbose": f"{QUESTION} Answer in three detailed paragraphs.",
}


@chat(MODEL)  # tokens + cost auto-extracted from the returned response
def think(prompt: str):
    response = client.models.generate_content(model=MODEL, contents=prompt)
    record_chat_content(prompt=prompt, completion=response.text)  # content is opt-in
    return response


@agent(name="assistant")  # invoke_agent span around the step; experiment tags ride along
def ask(variant: Variant) -> None:
    text = think(PROMPTS[variant.style]).text  # "broken" has no such style -> KeyError
    print(f"[{variant.name:7}] {text[:70].strip()}...")


result = (
    Experiment(EXPERIMENT_ID, description="terse vs verbose prompt", author="Fraol")
    .variant("terse", config={"style": "terse"})
    .variant("verbose", config={"style": "verbose"})
    .variant("broken", config={"style": "does-not-exist"})
    .run(ask)
)

print(f"\nrun_id: {result.run_id}")
for r in result.results:
    tail = "" if r.status == "success" else f"  ({r.error})"
    print(f"  {r.variant:8} {r.status:8} {r.duration_ms:8.0f} ms{tail}")
print(
    "\nRead it:  SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 "
    f"taraol experiment summary {EXPERIMENT_ID} --run {result.run_id}"
)

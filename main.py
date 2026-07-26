"""Real integration test: taraol against live Gemini + a running SigNoz.

Decorator-style instrumentation (the 3-decorator DX) end to end —
  @agent / @chat wrap the plain functions below; record_chat / record_chat_content
  attach tokens + opt-in content from inside
  -> an AgentLab experiment: a terse-vs-verbose prompt A/B, plus one intentionally
     broken variant (unknown prompt style -> KeyError) to prove failure-capture.
Every span carries experiment.id / variant / run_id; each variant also emits one
experiment_run log (status + duration).

Then read it back (the run_id is printed below):

    SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 taraol experiment summary prompt-style-ab --run <run_id>

Needs a running SigNoz and GEMINI_API_KEY (or GOOGLE_API_KEY) in .env.
Dynamic per-call model/conversation ids need the context-manager form; decorators fix
them at decoration time — that is the one trade-off of the sugar.
"""

import os

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, Variant, agent, chat, instrument, record_chat, record_chat_content

load_dotenv()

# .env here holds GEMINI_API_KEY; the google-genai SDK reads GOOGLE_API_KEY.
API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash"
EXPERIMENT_ID = "prompt-style-ab"

client = genai.Client(api_key=API_KEY)

# gRPC OTLP to a local SigNoz (:4317); capture_content=True opts into prompt/completion capture.
instrument("assistant", capture_content=True, endpoint="http://localhost:4317")

QUESTION = "Explain what OpenTelemetry is."
PROMPTS = {
    "terse": f"{QUESTION} Answer in exactly one sentence.",
    "verbose": f"{QUESTION} Answer in three detailed paragraphs.",
}


@chat(MODEL)  # chat span: tokens + cost rollup + captured content
def think(prompt: str) -> str:
    response = client.models.generate_content(model=MODEL, contents=prompt)
    usage = response.usage_metadata
    record_chat(input_tokens=usage.prompt_token_count, output_tokens=usage.candidates_token_count)
    record_chat_content(prompt=prompt, completion=response.text)
    return response.text


@agent(name="assistant")  # invoke_agent span around the step; experiment tags ride along
def ask(variant: Variant) -> None:
    prompt = PROMPTS[variant.config["style"]]  # "broken" has no such style -> KeyError
    text = think(prompt)
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

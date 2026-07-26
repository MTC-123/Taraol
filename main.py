"""Real integration test: taraol against live Gemini + a running SigNoz.

Exercises the whole write path end to end —
  instrument -> real gemini-2.5-flash chat (tokens + cost + opt-in content capture)
  -> an AgentLab experiment: a terse-vs-verbose prompt A/B, plus one intentionally
     broken variant to prove failure-capture (the run must not abort).
Every span carries experiment.id / variant / run_id; each variant also emits one
experiment_run log (status + duration).

Then read it back:

    SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 taraol experiment summary prompt-style-ab

Needs a running SigNoz and GEMINI_API_KEY (or GOOGLE_API_KEY) in .env.
"""

import os
import uuid

from dotenv import load_dotenv
from google import genai

from taraol import Experiment, Variant, instrument

load_dotenv()

# .env here holds GEMINI_API_KEY; the google-genai SDK reads GOOGLE_API_KEY.
API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
MODEL = "gemini-2.5-flash"
EXPERIMENT_ID = "prompt-style-ab"

client = genai.Client(api_key=API_KEY)

# gRPC OTLP to a local SigNoz (:4317). capture_content=True turns on opt-in
# LangSmith-style prompt/completion capture on the chat span.
kit = instrument("assistant", capture_content=True, endpoint="http://localhost:4317")

QUESTION = "Explain what OpenTelemetry is."
PROMPTS = {
    "terse": f"{QUESTION} Answer in exactly one sentence.",
    "verbose": f"{QUESTION} Answer in three detailed paragraphs.",
}


def ask(variant: Variant) -> None:
    """One real Gemini call, tagged by the active experiment variant."""

    model = variant.config.get("model", MODEL)
    prompt = PROMPTS[variant.config["style"]]
    conversation_id = str(uuid.uuid4())
    with kit.agent("assistant", conversation_id), kit.chat(model) as chat:
        response = client.models.generate_content(model=model, contents=prompt)
        usage = response.usage_metadata
        chat.record(
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count,
        )
        chat.record_content(prompt=prompt, completion=response.text)
    print(f"[{variant.name:7}] {model}: {response.text[:70].strip()}...")


result = (
    Experiment(EXPERIMENT_ID, description="terse vs verbose prompt", author="Fraol")
    .variant("terse", config={"style": "terse"})
    .variant("verbose", config={"style": "verbose"})
    # Bad model id -> the SDK raises -> recorded status=failed, the run keeps going.
    .variant("broken", config={"style": "terse", "model": "gemini-does-not-exist"})
    .run(ask)
)

print(f"\nrun_id: {result.run_id}")
for r in result.results:
    tail = "" if r.status == "success" else f"  ({r.error})"
    print(f"  {r.variant:8} {r.status:8} {r.duration_ms:8.0f} ms{tail}")
print(f"\nRead it:  SIGNOZ_CLICKHOUSE_URL=http://localhost:8123 taraol experiment summary {EXPERIMENT_ID}")

import os
import uuid

from dotenv import load_dotenv
from google import genai

from taraol import instrument

load_dotenv()

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

kit = instrument("assistant")

conversation_id = str(uuid.uuid4())

prompt = "Explain what OpenTelemetry is in one paragraph."

with kit.agent("assistant", conversation_id):
    with kit.chat("gemini-2.5-flash") as chat:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        usage = response.usage_metadata

        chat.record(
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count,
        )

        chat.record_content(
            prompt=prompt,
            completion=response.text,
        )

print(response.text)

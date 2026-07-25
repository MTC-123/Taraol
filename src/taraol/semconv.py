"""Stable GenAI semantic-convention attribute names.

These are the vendor-neutral ``gen_ai.*`` keys and are never re-namespaced. Project
attributes (cost, taint, breaker, output) go through
:func:`taraol.attributes.attrs` instead.
"""

GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"

CHAT = "chat"
EXECUTE_TOOL = "execute_tool"
INVOKE_AGENT = "invoke_agent"

# Experiment tags (AgentLab) — group traces by variant to compare cost/latency/loops/
# breaker trips across prompt / model / topology variants (operational experiments).
EXPERIMENT_ID = "experiment.id"
EXPERIMENT_VARIANT = "experiment.variant"
EXPERIMENT_RUN_ID = "experiment.run_id"
EXPERIMENT_DESCRIPTION = "experiment.description"
EXPERIMENT_AUTHOR = "experiment.author"
EXPERIMENT_COMMIT = "experiment.commit"
EXPERIMENT_PYTHON = "experiment.python"
EXPERIMENT_KIT_VERSION = "experiment.kit_version"
# On the once-per-variant experiment_run log record (not on spans).
EXPERIMENT_STATUS = "experiment.status"  # "success" | "failed"
EXPERIMENT_DURATION_MS = "experiment.duration_ms"

# Content-bearing gen_ai keys, only set when capture_content is enabled (opt-in).
# These are the current GenAI-semconv message keys (structured JSON message lists).
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"
GEN_AI_SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"

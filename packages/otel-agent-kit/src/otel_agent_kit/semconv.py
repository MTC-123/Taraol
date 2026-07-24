"""Stable GenAI semantic-convention attribute names.

These are the vendor-neutral ``gen_ai.*`` keys and are never re-namespaced. Project
attributes (cost, taint, breaker, output) go through
:func:`otel_agent_kit.attributes.attrs` instead.
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

# Terraform is the only creation path for demo alert resources. The committed
# JSON exports under ../alerts are sanitized evidence, not raw-API payloads.
locals {
  controller_url = "http://controller:8000/alert"
  loop_condition = jsonencode(jsondecode(file("${path.module}/../alerts/loop-detected.json")).condition)
  budget_condition = jsonencode(jsondecode(file("${path.module}/../alerts/budget-exceeded.json")).condition)
  edge_breaker_condition = jsonencode(jsondecode(file("${path.module}/../alerts/edge-breaker.json")).condition)
  fast_evaluation = jsonencode({
    kind = "rolling"
    spec = { evalWindow = "30s", frequency = "10s", matchType = "at_least_once" }
  })
}

# The official provider currently manages alerts and route policies but not
# notification channels. Create this one webhook through the SigNoz UI exactly
# once (documented in docs/DEMO.md); no HTTP API is used by this repository.
resource "signoz_route_policy" "agentmesh_controller" {
  name        = "agentmesh-controller"
  description = "Route Agent Mesh Radar enforcement alerts to the controller webhook."
  expression  = "amr.enforcement == \"controller\""
  channels    = ["agentmesh-controller"]
}

resource "signoz_alert" "loop_detected" {
  alert                 = "loop-detected"
  alert_type            = "LOGS_BASED_ALERT"
  severity              = "critical"
  rule_type             = "threshold_rule"
  version               = "v5"
  schema_version        = "v2alpha1"
  eval_window           = "30s"
  frequency             = "10s"
  condition             = local.loop_condition
  evaluation            = local.fast_evaluation
  description           = "Pause candidate: conversation=$conversation_id edge=$edge trace=$trace_id"
  summary               = "Agent mesh loop detected for $conversation_id"
  preferred_channels    = ["agentmesh-controller"]
  notification_settings = { group_by = ["conversation_id", "edge", "trace_id"], use_policy = true }
  labels                = { "amr.enforcement" = "controller" }
}

resource "signoz_alert" "edge_breaker" {
  alert                 = "edge-breaker"
  alert_type            = "LOGS_BASED_ALERT"
  severity              = "critical"
  rule_type             = "threshold_rule"
  version               = "v5"
  schema_version        = "v2alpha1"
  eval_window           = "30s"
  frequency             = "10s"
  condition             = local.edge_breaker_condition
  evaluation            = local.fast_evaluation
  description           = "Trip breaker on unhealthy edge=$edge trace=$trace_id"
  summary               = "Agent mesh edge unhealthy: $edge"
  preferred_channels    = ["agentmesh-controller"]
  notification_settings = { group_by = ["edge", "trace_id"], use_policy = true }
  labels                = { "amr.enforcement" = "controller" }
}

resource "signoz_alert" "budget_exceeded" {
  alert                 = "budget-exceeded"
  alert_type            = "LOGS_BASED_ALERT"
  severity              = "warning"
  rule_type             = "threshold_rule"
  version               = "v5"
  schema_version        = "v2alpha1"
  eval_window           = "30s"
  frequency             = "10s"
  condition             = local.budget_condition
  evaluation            = local.fast_evaluation
  description           = "Pause writer: conversation=$conversation_id trace=$trace_id"
  summary               = "Agent mesh budget exceeded for $conversation_id"
  preferred_channels    = ["agentmesh-controller"]
  notification_settings = { group_by = ["conversation_id", "trace_id"], use_policy = true }
  labels                = { "amr.enforcement" = "controller" }
}

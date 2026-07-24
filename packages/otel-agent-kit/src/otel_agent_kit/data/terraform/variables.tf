variable "signoz_url" {
  type        = string
  description = "Self-hosted SigNoz URL. Supply through TF_VAR_signoz_url."
}

variable "signoz_api_key" {
  type        = string
  sensitive   = true
  description = "Service-account API key. Supply through TF_VAR_signoz_api_key."
}

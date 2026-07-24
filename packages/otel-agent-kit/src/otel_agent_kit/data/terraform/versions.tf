terraform {
  required_version = ">= 1.8.0"
  required_providers {
    signoz = {
      source  = "SigNoz/signoz"
      version = "0.0.15"
    }
  }
}

provider "signoz" {
  endpoint     = var.signoz_url
  access_token = var.signoz_api_key
}

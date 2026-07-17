# SigNoz deployment

This directory contains the official SigNoz Foundry Compose output committed for reproducible
local development. The legacy Compose files in the SigNoz repository were deprecated upstream;
Foundry is the supported replacement.

## Pinned inputs

- Foundry: `v0.2.11`
- SigNoz: `signoz/signoz:v0.128.0`
- UI: `http://localhost:8080`
- OTLP: `4317` (gRPC) and `4318` (HTTP)

`pours/deployment/` and `casting.yaml.lock` are generated artifacts. Do not hand-edit them.
To regenerate from WSL 2 with native Docker Engine and Foundry v0.2.11 installed:

```sh
foundryctl forge -f deploy/signoz/casting.yaml
```

Foundry renders relative to the casting file. Run the command from this directory instead when
using an older Foundry version that requires the casting file to be in the working directory:

```sh
cd deploy/signoz
foundryctl forge -f casting.yaml
```

Review and commit the regenerated `pours/` output and `casting.yaml.lock` together. Start the
committed stack from the repository root with `make up`; stop and remove its data with
`make down`.



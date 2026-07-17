"""Continuously invoke Beta to create the first mesh edge."""

import logging
import os
import time

from amr.a2a import A2AClient, A2AError
from amr.otel_setup import init_tracing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    service_name = os.getenv("OTEL_SERVICE_NAME", "agent_alpha")
    target_url = os.getenv("BETA_A2A_URL", "http://beta:8001/a2a")
    tracer = init_tracing(service_name)
    client = A2AClient(service_name, "agent_beta", tracer=tracer)
    while True:
        try:
            response = client.call("ping", {"from": service_name}, target_url)
            logger.info("beta response: %s", response)
        except A2AError:
            logger.exception("A2A call to beta failed")
        time.sleep(2)


if __name__ == "__main__":
    main()

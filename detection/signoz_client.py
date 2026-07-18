"""Thin, read-only SigNoz v5 Query Builder client and reusable query shapes."""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx


class SigNozQueryError(RuntimeError):
    """SigNoz rejected a query or returned a response the watcher cannot use."""


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_ms: int
    end_ms: int


def _field(name: str, context: str = "span") -> dict[str, str]:
    return {"name": name, "fieldContext": context}


def velocity_query() -> dict[str, Any]:
    return {
        "type": "builder_query",
        "spec": {
            "name": "velocity",
            "signal": "traces",
            "stepInterval": 1,
            "aggregations": [{"expression": "count()", "alias": "hop_count"}],
            "filter": {
                "expression": "name = 'a2a.call' AND agentmesh.src EXISTS AND peer.service EXISTS"
            },
            "groupBy": [_field("trace_id"), _field("agentmesh.src"), _field("peer.service")],
            "disabled": False,
        },
    }


def active_conversations_query() -> dict[str, Any]:
    return {
        "type": "builder_query",
        "spec": {
            "name": "active_conversations",
            "signal": "traces",
            "filter": {
                "expression": "gen_ai.operation.name = 'chat' AND gen_ai.conversation.id EXISTS "
                "AND agentmesh.cost.usd EXISTS"
            },
            "selectFields": [_field("gen_ai.conversation.id"), _field("trace_id")],
            "disabled": False,
            "limit": 1000,
        },
    }


def conversation_cost_query(conversation_id: str) -> dict[str, Any]:
    escaped = conversation_id.replace("'", "\\'")
    return {
        "type": "builder_query",
        "spec": {
            "name": "conversation_cost",
            "signal": "traces",
            "aggregations": [{"expression": "sum(agentmesh.cost.usd)", "alias": "cost_usd"}],
            "filter": {
                "expression": "gen_ai.operation.name = 'chat' AND agentmesh.cost.usd EXISTS "
                f"AND gen_ai.conversation.id = '{escaped}'"
            },
            "disabled": False,
        },
    }


def trace_query(trace_id: str) -> dict[str, Any]:
    escaped = trace_id.replace("'", "\\'")
    return {
        "type": "builder_query",
        "spec": {
            "name": "trace_spans",
            "signal": "traces",
            "filter": {"expression": f"trace_id = '{escaped}'"},
            "selectFields": [
                _field("trace_id"),
                _field("span_id"),
                _field("parent_span_id"),
                _field("timestamp"),
                _field("name"),
                _field("service.name", "resource"),
                _field("gen_ai.conversation.id"),
                _field("agentmesh.src"), _field("peer.service"), _field("agentmesh.cost.usd"),
            ],
            "disabled": False,
            "limit": 1000,
        },
    }


class SigNozClient:
    def __init__(self, url: str, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def run_builder_query(
        self, query: Mapping[str, Any], time_range: TimeRange
    ) -> list[dict[str, Any]]:
        spec = query.get("spec", {})
        request_type = "raw" if isinstance(spec, dict) and "selectFields" in spec else "table"
        payload = {
            "start": time_range.start_ms,
            "end": time_range.end_ms,
            "requestType": request_type,
            "variables": {},
            "compositeQuery": {"queries": [dict(query)]},
        }
        try:
            response = self._client.post(
                f"{self.url}/api/v5/query_range",
                headers={"SIGNOZ-API-KEY": self.api_key},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SigNozQueryError(f"SigNoz query failed: {exc}") from exc
        return self._rows(body)

    def get_trace(
        self, trace_id: str, time_range: TimeRange | None = None
    ) -> list[dict[str, Any]]:
        if time_range is None:
            end_ms = int(time.time() * 1000)
            time_range = TimeRange(end_ms - 86_400_000, end_ms)
        return self.run_builder_query(trace_query(trace_id), time_range)

    @staticmethod
    def _rows(body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            raise SigNozQueryError("SigNoz returned a non-object response")
        data = body.get("data")
        candidates = [data, data.get("result") if isinstance(data, dict) else None]
        for candidate in candidates:
            if isinstance(candidate, list) and all(isinstance(row, dict) for row in candidate):
                return candidate
            if isinstance(candidate, dict):
                for key in ("rows", "result"):
                    rows = candidate.get(key)
                    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                        return rows
        raise SigNozQueryError("SigNoz response did not contain object rows")


class ClickHouseClient:
    """Self-hosted, read-only fallback for local SigNoz ClickHouse deployments.

    This is intentionally limited to the query shapes the watcher owns. It does not expose a
    general SQL execution API and should be reachable only on a private Compose network.
    """

    _TABLE = "signoz_traces.distributed_signoz_index_v3"

    def __init__(self, url: str, *, client: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _seconds(time_range: TimeRange) -> str:
        # SigNoz's ClickHouse build rejects epoch conversion functions at the current
        # nanosecond scale. The watcher only queries trailing windows, so anchor that
        # interval on ClickHouse's clock and avoid a lossy client/server clock conversion.
        window_sec = max(1, (time_range.end_ms - time_range.start_ms + 999) // 1000)
        return (
            f"timestamp >= now64(9) - toIntervalSecond({window_sec}) AND timestamp <= now64(9)"
        )

    def run_builder_query(
        self, query: Mapping[str, Any], time_range: TimeRange
    ) -> list[dict[str, Any]]:
        spec = query.get("spec", {})
        if not isinstance(spec, Mapping) or not isinstance(spec.get("name"), str):
            raise SigNozQueryError("ClickHouse fallback requires a named watcher query")
        name = spec["name"]
        sql = self._sql(name, spec, time_range)
        try:
            response = self._client.post(
                f"{self.url}/?default_format=JSONEachRow", content=sql.encode("utf-8")
            )
            response.raise_for_status()
            return [json.loads(line) for line in response.text.splitlines() if line]
        except (httpx.HTTPError, ValueError) as exc:
            raise SigNozQueryError(f"ClickHouse watcher query failed: {exc}") from exc

    def get_trace(
        self, trace_id: str, time_range: TimeRange | None = None
    ) -> list[dict[str, Any]]:
        if time_range is None:
            end_ms = int(time.time() * 1000)
            time_range = TimeRange(end_ms - 86_400_000, end_ms)
        return self.run_builder_query(trace_query(trace_id), time_range)

    def _sql(self, name: str, spec: Mapping[str, Any], time_range: TimeRange) -> str:
        bounded = self._seconds(time_range)
        attrs = "attributes_string"
        if name == "velocity":
            return f"""
                SELECT trace_id, {attrs}['agentmesh.src'] AS `agentmesh.src`,
                       {attrs}['peer.service'] AS `peer.service`, count() AS hop_count
                FROM {self._TABLE}
                WHERE {bounded} AND name = 'a2a.call'
                  AND mapContains({attrs}, 'agentmesh.src') AND mapContains({attrs}, 'peer.service')
                GROUP BY trace_id, `agentmesh.src`, `peer.service`
            """
        if name == "active_conversations":
            return f"""
                SELECT {attrs}['gen_ai.conversation.id'] AS `gen_ai.conversation.id`, trace_id
                FROM {self._TABLE}
                WHERE {bounded} AND {attrs}['gen_ai.operation.name'] = 'chat'
                  AND mapContains({attrs}, 'gen_ai.conversation.id')
                  AND mapContains(attributes_number, 'agentmesh.cost.usd')
                GROUP BY `gen_ai.conversation.id`, trace_id
            """
        if name == "conversation_cost":
            expression = spec.get("filter", {})
            if not isinstance(expression, Mapping) or not isinstance(
                expression.get("expression"), str
            ):
                raise SigNozQueryError("conversation cost query has no filter expression")
            conversation_id = expression["expression"].rsplit("'", 2)[-2].replace("\\'", "'")
            escaped = conversation_id.replace("'", "\\'")
            return f"""
                SELECT sum(attributes_number['agentmesh.cost.usd']) AS cost_usd
                FROM {self._TABLE}
                WHERE {bounded} AND {attrs}['gen_ai.operation.name'] = 'chat'
                  AND {attrs}['gen_ai.conversation.id'] = '{escaped}'
            """
        if name == "trace_spans":
            expression = spec.get("filter", {})
            if not isinstance(expression, Mapping) or not isinstance(
                expression.get("expression"), str
            ):
                raise SigNozQueryError("trace query has no filter expression")
            trace_id = expression["expression"].rsplit("'", 2)[-2].replace("\\'", "'")
            escaped = trace_id.replace("'", "\\'")
            return f"""
                SELECT trace_id, span_id, parent_span_id,
                       toUnixTimestamp64Nano(timestamp) AS timestamp,
                       name, resource.service.name::String AS serviceName,
                       attributes_string AS attributes
                FROM {self._TABLE}
                WHERE {bounded} AND trace_id = '{escaped}'
                ORDER BY timestamp, span_id
            """
        raise SigNozQueryError(f"unsupported ClickHouse watcher query: {name}")

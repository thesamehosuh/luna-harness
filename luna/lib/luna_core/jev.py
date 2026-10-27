"""Thin jev ("System One") client.

Backend: ``POST {base_url}/systemone`` with ``{state, model, questions}`` → ``{answers, usage}``.

- Default backend is OpenCode **Zen** (``https://opencode.ai/zen/v1``) with ``jev-1.13-free``.
  OpenCode **Go** does *not* serve ``systemone``.
- TypeSafe direct (``https://api.typesafe.ai/v1``, model ``jev-latest``) is a drop-in via config.
- ``state`` may be a string or structured JSON; ``questions`` is a map keyed by id (the API rejects
  a list).
- Fails **closed**: transport/parse errors raise :class:`JevError`; callers treat that as silence.
- Retries ``429``/``529`` with exponential backoff (per the TypeSafe API reference).

Reference: https://docs.typesafe.ai/api
"""

from __future__ import annotations

import json
import math
import hashlib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MODEL = "jev-1.13-free"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF = 0.75
# Cloudflare fronts opencode.ai and returns 403 (error 1010) to urllib's default UA.
DEFAULT_USER_AGENT = "LunaHarness/0.1"

RETRYABLE_STATUS = {429, 529}
# Don't retry a 429 in-request if the server asks us to wait longer than this; the caller
# (the ambient poller) will naturally try again on its next scan.
RETRY_AFTER_IN_REQUEST_MAX = 10.0


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    except (TypeError, ValueError):
        return None

State = Union[str, Dict[str, Any], List[Any]]


class JevError(RuntimeError):
    """Transport, HTTP, or parse failure. Callers must fail closed (silence)."""

    def __init__(self, message: str, *, status: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass
class JevAnswer:
    id: str
    type: str
    value: Any
    probabilities: Dict[str, float] = field(default_factory=dict)
    confidence: Optional[float] = None
    legend: Dict[str, str] = field(default_factory=dict)

    def as_probability(self) -> float:
        """For ``noul``: the 0–1 yes-probability. For others: best-effort numeric value."""
        return _number(self.value, 0, 1)

    def as_score(self) -> float:
        """Probability-weighted score position (Score answers)."""
        return _number(self.value)


def noul(qid: str, instructions: str, criteria: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Yes/no question. ``criteria`` maps ``true``/``false`` to what each means.

    (The API names these ``true``/``false``; ``yes``/``no`` are accepted here and normalized.)
    """
    spec: Dict[str, Any] = {"id": qid, "type": "noul", "instructions": instructions}
    if criteria:
        normalized = dict(criteria)
        if "yes" in normalized and "true" not in normalized:
            normalized["true"] = normalized.pop("yes")
        if "no" in normalized and "false" not in normalized:
            normalized["false"] = normalized.pop("no")
        spec["criteria"] = normalized
    return spec


def choice(qid: str, instructions: str, criteria: Mapping[str, str]) -> Dict[str, Any]:
    """Choice question. ``criteria`` maps each option to its rubric description."""
    return {"id": qid, "type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(qid: str, instructions: str, criteria: List[str]) -> Dict[str, Any]:
    """Score question. ``criteria`` is an ordered list of 2–10 level descriptions (low → high)."""
    return {"id": qid, "type": "score", "instructions": instructions, "criteria": list(criteria)}


def _number(value, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevError("protocol error: expected a number")
    value = float(value)
    if not math.isfinite(value) or value < low or (high is not None and value > high):
        raise JevError("protocol error: number outside permitted range")
    return value


def validate_answers(answers, questions, *, require_all=True):
    """Validate against the requested schema, including clients supplied by plugins/tests."""
    if require_all and set(answers) - {q['id'] for q in questions}:
        raise JevError("protocol error: unsolicited answer IDs")
    for question in questions:
        qid, kind = question['id'], question['type']
        answer = answers.get(qid)
        if answer is None:
            if require_all:
                raise JevError(f"protocol error: missing answer {qid}")
            continue
        if answer.type != kind:
            raise JevError(f"protocol error: wrong type for {qid}")
        criteria = question.get('criteria') or {}
        if kind == 'noul':
            _number(answer.value, 0, 1)
        elif kind == 'score':
            _number(answer.value, 0, len(criteria) - 1)
        elif not isinstance(answer.value, str) or answer.value not in criteria:
            raise JevError(f"protocol error: unknown choice for {qid}")
        if answer.confidence is not None:
            _number(answer.confidence, 0, 1)
        if answer.probabilities:
            keys = ({str(i) for i in range(len(criteria))} if kind == 'score'
                    else set(criteria) if kind == 'choice' else {'true', 'false'})
            if not set(answer.probabilities).issubset(keys):
                raise JevError(f"protocol error: unknown probability label for {qid}")
            values = [_number(v, 0, 1) for v in answer.probabilities.values()]
            if sum(values) > 1.001:
                raise JevError(f"protocol error: probability mass exceeds one for {qid}")


def parse_answers(payload: Mapping[str, Any], questions=None) -> Dict[str, JevAnswer]:
    if not isinstance(payload, Mapping):
        raise JevError(f"response is not a JSON object: {type(payload).__name__}")
    raw = payload.get("answers")
    if not isinstance(raw, Mapping):
        raise JevError("response missing 'answers'")
    out: Dict[str, JevAnswer] = {}
    for qid, ans in raw.items():
        if not isinstance(ans, Mapping):
            raise JevError(f"answer for {qid!r} is not an object")
        qtype = str(ans.get("type") or "")
        if qtype == "noul":
            value = ans.get("noul", ans.get("value"))
        elif qtype == "choice":
            value = ans.get("choice", ans.get("value"))
        elif qtype == "score":
            value = ans.get("score", ans.get("value"))
        else:
            value = ans.get("value")
        if qtype not in {'noul', 'score', 'choice'}:
            raise JevError(f"protocol error: unknown answer type for {qid}")
        if value is None:
            raise JevError(f"answer for {qid!r} has no value")
        if qtype in {'noul', 'score'}:
            _number(value, 0, 1 if qtype == 'noul' else None)
        elif not isinstance(value, str):
            raise JevError(f"protocol error: expected a choice for {qid}")
        probs = ans.get("probabilities") or {}
        conf = ans.get("confidence")
        legend = ans.get("legend") or {}
        try:
            if not isinstance(probs, Mapping) or not isinstance(legend, Mapping):
                raise JevError("protocol error: expected probability/legend maps")
            for probability in probs.values():
                _number(probability, 0, 1)
            if sum(probs.values()) > 1.001:
                raise JevError("protocol error: probability mass exceeds one")
            if conf is not None:
                _number(conf, 0, 1)
            out[str(qid)] = JevAnswer(
                id=str(qid),
                type=qtype,
                value=value,
                probabilities={str(k): float(v) for k, v in probs.items()} if probs else {},
                confidence=float(conf) if conf is not None else None,
                legend={str(k): str(v) for k, v in legend.items()} if legend else {},
            )
        except (TypeError, ValueError) as exc:
            # A malformed 200 is a bug, not quota: raise JevError (never a bare ValueError) so the
            # fallback chain refuses to spend the paid route on it and the caller fails closed.
            raise JevError(f"answer for {qid!r} has malformed fields: {exc}") from exc
    if questions is not None:
        validate_answers(out, questions)
    return out


def _is_retryable_status(exc: Exception) -> bool:
    """A quota/transport failure is worth trying elsewhere; a bad response is not."""
    status = getattr(exc, "status", None)
    if status is not None:
        return status in RETRYABLE_STATUS
    return isinstance(exc, JevError) and str(exc).startswith("transport error")


def normalize_fallback_entries(fallback) -> List[Dict[str, Any]]:
    """Normalize a fallback chain to ``[{provider, model, base_url?, api_key_env?}, …]``.

    Mirrors hermes' own ``fallback_model`` / ``fallback_providers`` shape (see
    ``agent/agent_init.py::_fallback_entries``): a single dict or a list, entries need at least a
    provider and a model. Entries may add ``base_url`` and ``api_key_env`` so a different jev host
    (e.g. a paid route) can back up the free one.
    """
    if isinstance(fallback, dict):
        fallback = [fallback]
    if not isinstance(fallback, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in fallback:
        if not isinstance(entry, dict) or not entry.get("model"):
            continue
        item = dict(entry)
        item.setdefault("provider", "unknown")
        out.append(item)
    return out


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def route_tier(entry: Mapping[str, Any]) -> str:
    """Cost class of a jev route: ``free`` | ``local`` | ``paid``.

    An explicit ``tier`` on the route/provider entry wins. Otherwise infer from the target: a
    loopback/private host is ``local``; a model/provider/base_url that says ``free`` is ``free``;
    anything else is ``paid``. Drives the ``via=`` field of the verdict stream so the operator reads
    cost, not internal route names.
    """
    explicit = str(entry.get("tier") or "").strip().lower()
    if explicit in {"free", "local", "paid"}:
        return explicit
    model = str(entry.get("model") or "").lower()
    provider = str(entry.get("provider") or "").lower()
    base = str(entry.get("base_url") or "").lower()
    host = ""
    if "://" in base:
        host = base.split("://", 1)[1].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    if host in _LOCAL_HOSTS or "local" in provider:
        return "local"
    if host:
        try:
            import ipaddress

            if ipaddress.ip_address(host).is_private:
                return "local"
        except ValueError:
            pass
    if "free" in model or "free" in provider or "free" in base:
        return "free"
    return "paid"


def resolve_jev_chain(jev_cfg: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Ordered jev route chain (primary first) from the ``ambient.jev`` config block.

    Mirrors hermes' named ``providers:`` registry: routes are **names** into the registry and
    the order is the ``route`` list — swap a route by renaming it, reprioritise by reordering,
    add one by dropping a registry entry anywhere in the list. An entry in ``route`` (or in the
    legacy ``fallbacks`` list) may also be an inline dict.

    Two accepted shapes, mixable::

        # registry + order (preferred)
        route: [zen-free, local, typesafe]
        providers:
          zen-free: {base_url: …, model: …, api_key_env: …}

        # legacy (still supported): flat primary keys + inline/name fallbacks
        base_url: …; model: …; api_key_env: …
        fallbacks: [local, {provider: …, model: …}]

    Unknown names and entries without a model are skipped — a config typo must fail closed
    (quieter chain), never crash the poller. An empty chain means "primary defaults only".
    """
    cfg = jev_cfg if isinstance(jev_cfg, Mapping) else {}
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), Mapping) else {}

    def resolve(item: Any) -> Optional[Dict[str, Any]]:
        if isinstance(item, str):
            entry = providers.get(item)
            if not isinstance(entry, Mapping) or not entry.get("model"):
                return None
            out = dict(entry)
            out.setdefault("provider", item)
            return out
        if isinstance(item, Mapping) and item.get("model"):
            out = dict(item)
            out.setdefault("provider", "unknown")
            return out
        return None

    routes = cfg.get("route")
    if isinstance(routes, list) and routes:
        return [e for e in (resolve(i) for i in routes) if e]

    chain: List[Dict[str, Any]] = []
    if cfg.get("model"):
        head = {"provider": "primary", "model": cfg["model"]}
        for k in ("base_url", "api_key_env", "endpoint", "instructions", "timeout_seconds", "tier"):
            if cfg.get(k) is not None:
                head[k] = cfg[k]
        chain.append(head)
    for item in (cfg.get("fallbacks") or []):
        e = resolve(item)
        if e:
            chain.append(e)
    return chain


class FallbackJevClient:
    """Try a primary jev route, then each fallback in order.

    Hermes already does this for normal models (``fallback_model`` / ``fallback_providers``); this is
    the same idea for jev, so Luna keeps deciding when the free tier is exhausted instead of going
    mute. Only *retryable* upstream failures (429/529, and transport errors) advance the chain — a
    malformed response is a bug, not a reason to spend the paid route.
    """

    def __init__(self, primary: JevClient, fallbacks: Optional[List[Dict[str, Any]]] = None,
                 *, api_key_resolver: Optional[Callable[[str], str]] = None,
                 on_switch: Optional[Callable[[str, str], None]] = None,
                 client_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 route_names: Optional[List[str]] = None,
                 route_tiers: Optional[List[str]] = None):
        self.primary = primary
        self.fallbacks = normalize_fallback_entries(fallbacks or [])
        self._resolve_key = api_key_resolver or (lambda env: os.getenv(env, ""))
        self._on_switch = on_switch
        self._factory = client_factory
        # Human-readable route labels, primary first (e.g. ["zen-free", "local", "typesafe"]).
        names = list(route_names or [])
        if names and len(names) == len(self.fallbacks) + 1:
            self._route_names = names
        else:
            self._route_names = (["primary"] + [f.get("provider", "unknown")
                                                for f in self.fallbacks])
        # Cost class per route, primary first (free | local | paid), for the verdict stream.
        tiers = [str(t).strip().lower() for t in (route_tiers or [])]
        if len(tiers) != len(self._route_names):
            tiers = [route_tier({"model": getattr(primary, "model", ""),
                                 "base_url": getattr(primary, "base_url", "")})]
            tiers += [route_tier(entry) for entry in self.fallbacks]
        self._route_tiers = tiers
        self._index = 0
        self.served_by: str = ""
        self._active_cache = None
        self._active_index = -1

    # -- introspection -------------------------------------------------------
    @property
    def active_route(self) -> str:
        """Config name of the serving route (primary first), e.g. ``local``."""
        i = min(self._index, len(self._route_names) - 1) if self._route_names else 0
        return self._route_names[i] if self._route_names else "primary"

    @property
    def active_tier(self) -> str:
        """Cost class of the serving route: ``free`` | ``local`` | ``paid``."""
        if not self._route_tiers:
            return ""
        i = min(self._index, len(self._route_tiers) - 1)
        return self._route_tiers[i]

    @property
    def active(self):
        if self._index == 0:
            return self.primary
        # Memoised: the instance carries `last_usage` from the call, so rebuilding it per access
        # would throw away the provider-reported cost we just paid for.
        if self._active_cache is not None and self._active_index == self._index:
            return self._active_cache
        entry = self.fallbacks[self._index - 1]
        client = self._build(entry)
        self._active_cache = client
        self._active_index = self._index
        return client

    def _build(self, entry: Dict[str, Any]):
        if self._factory is not None:
            return self._factory(entry)
        base = getattr(self.primary, "base_url", DEFAULT_BASE_URL)
        timeout = getattr(self.primary, "timeout", DEFAULT_TIMEOUT)
        retries = getattr(self.primary, "max_retries", DEFAULT_MAX_RETRIES)
        backoff = getattr(self.primary, "backoff", DEFAULT_BACKOFF)
        return JevClient(
            base_url=entry.get("base_url") or base,
            api_key=self._resolve_key(str(entry["api_key_env"])) if entry.get("api_key_env") else "",
            model=str(entry["model"]),
            endpoint=entry.get("endpoint"),
            timeout=float(entry.get("timeout_seconds") or timeout),
            max_retries=retries,
            backoff=backoff,
            transport=getattr(self.primary, "_transport", None),
            sleep=getattr(self.primary, "_sleep", time.sleep),
            instructions=entry.get("instructions") or getattr(self.primary, "instructions", None),
            operation=getattr(self.primary, 'operation', None),
        )

    def _advance(self) -> bool:
        if self._index >= len(self.fallbacks):
            return False
        entry = self.fallbacks[self._index]
        self._index += 1
        self.served_by = f"{entry['model']} ({entry.get('provider', 'unknown')})"
        if self._on_switch:
            try:
                self._on_switch(self.primary.model, self.served_by)
            except Exception:
                pass
        return True

    @property
    def last_usage(self) -> Optional[Dict[str, Any]]:
        return getattr(self.active, "last_usage", None)

    def reset(self) -> None:
        self._index = 0
        self.served_by = ""
        self._active_cache = None
        self._active_index = -1

    def ask(self, state: State, questions: list) -> Dict[str, JevAnswer]:
        last: Optional[Exception] = None
        while True:
            try:
                answers = self.active.ask(state, questions)
                if self._index == 0:
                    self.served_by = f"{self.primary.model} (primary)"
                return answers
            except JevError as exc:
                last = exc
                if not _is_retryable_status(exc) or not self._advance():
                    raise
            except (OSError, TimeoutError, ConnectionError) as exc:
                # Raw transport failures (injected transports raise unwrapped): a different host
                # may still work.
                last = exc
                if not self._advance():
                    raise
            except Exception:
                # Everything else is a bug — a malformed response is not an exhausted quota and
                # must never spend the paid route.
                raise
        raise last if last else JevError("jev unavailable")


class JevClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        endpoint: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        transport: Optional[Callable[[str, bytes, Mapping[str, str], float], Mapping[str, Any]]] = None,
        sleep: Callable[[float], None] = time.sleep,
        instructions: Optional[str] = None,
        operation=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint or f"{self.base_url}/systemone"
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.backoff = backoff
        self._transport = transport
        self._sleep = sleep
        # Optional route-level guidance precedes each question's own rubric. Unconfigured
        # TypeSafe/Zen requests retain their original shape.
        self.instructions = instructions
        self.last_usage: Optional[Dict[str, Any]] = None
        self.operation = operation
        self.validated = False

    def build_request(self, state: State, questions: list) -> Dict[str, Any]:
        """Build the request body. ``questions`` is a list of specs each carrying an ``id``; the API
        expects a map keyed by question id."""
        qmap: Dict[str, Any] = {}
        for spec in questions:
            spec = dict(spec)
            qid = spec.pop("id")
            if self.instructions:
                spec["instructions"] = self.instructions + ("\n\n" + spec["instructions"] if spec.get("instructions") else "")
            qmap[qid] = spec
        return {"model": self.model, "state": state, "questions": qmap}

    def _post(self, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
        if self._transport is not None:
            # Authorization is added here (not passed by the caller) so the key never becomes a
            # local in the caller's frame — e.g. pytest tracebacks.
            sent = dict(headers)
            if self.api_key:
                sent["Authorization"] = f"Bearer {self.api_key}"
            try:
                timeout = self.operation.reserve(timeout) if self.operation else timeout
                response = self._transport(url, body, sent, timeout)
                if self.operation:
                    self.operation.observe(self, response)
                return response
            except JevError:
                raise
            except (OSError, TimeoutError, ConnectionError) as exc:
                # Wrapped as a transport JevError so the fallback chain classifies it retryable
                # and callers only ever see JevError (the module's fail-closed contract).
                raise JevError(f"transport error: {exc}", status=None) from exc

        last_error: Optional[JevError] = None
        for attempt in range(self.max_retries + 1):
            attempt_timeout = self.operation.reserve(timeout) if self.operation else timeout
            req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            try:
                with urllib.request.urlopen(req, timeout=attempt_timeout) as resp:
                    raw = resp.read(1_048_577)
                    if len(raw) > 1_048_576:
                        raise JevError('protocol error: response too large')
                    response = json.loads(raw.decode("utf-8"))
                    if self.operation:
                        self.operation.observe(self, response)
                    return response
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if self.operation:
                    self.operation.observe(self, None)
                raise JevError('protocol error: invalid JSON response') from exc
            except urllib.error.HTTPError as exc:  # pragma: no cover - network path
                if self.operation:
                    self.operation.observe(self, None)
                detail = exc.read(500).decode("utf-8", "replace")
                retry_after = _parse_retry_after(exc.headers.get("retry-after") if exc.headers else None)
                suffix = f" (retry-after {retry_after:g}s)" if retry_after else ""
                last_error = JevError(f"HTTP {exc.code}: {detail}{suffix}",
                                      status=exc.code, retry_after=retry_after)
                # A long retry-after means the quota is exhausted; fail closed now rather than
                # hammering. The poller retries on its next scan.
                if exc.code == 429 and retry_after and retry_after > RETRY_AFTER_IN_REQUEST_MAX:
                    raise last_error from exc
                if exc.code in RETRYABLE_STATUS and attempt < self.max_retries:
                    wait = retry_after if retry_after else self.backoff * (2 ** attempt)
                    self._sleep(self.operation.wait(wait) if self.operation else min(wait, 30.0))
                    continue
                raise last_error from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if self.operation:
                    self.operation.observe(self, None)
                last_error = JevError(f"transport error: {exc}", status=None)
                if attempt < self.max_retries:
                    wait = self.backoff * (2 ** attempt)
                    self._sleep(self.operation.wait(wait) if self.operation else wait)
                    continue
                raise last_error from exc
        raise last_error or JevError("unknown error")

    def ask(self, state: State, questions: list) -> Dict[str, JevAnswer]:
        """One batch call. Raises :class:`JevError` on any failure."""
        self.last_usage = None
        self.validated = False
        if not questions:
            return {}
        payload = self.build_request(state, questions)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._post(self.endpoint, body, headers, self.timeout)
        if isinstance(response, dict):
            usage = response.get("usage")
            self.last_usage = {
                "input_tokens": (usage or {}).get("input_tokens"),
                "output_tokens": (usage or {}).get("output_tokens"),
                "cost": (usage or {}).get("cost"),
                "provider": response.get("provider"),
                "served_model": response.get("model"),
                "request_id": response.get("id"),
            }
        answers = parse_answers(response, questions)
        self.validated = True
        return answers


class AttemptBudget:
    """One bounded operation shared by every route and retry, with per-attempt admission."""
    def __init__(self, seconds, guard=None, observer=None, clock=time.monotonic):
        self.seconds, self.guard, self.observer, self.clock = seconds, guard, observer, clock
        self.deadline = 0

    def reserve(self, timeout):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise JevError('judgment deadline exhausted')
        if self.guard is not None and not self.guard():
            raise JevError('judgment resource guard exhausted')
        return max(0.001, min(timeout, remaining))

    def wait(self, seconds):
        remaining = self.deadline - self.clock()
        if seconds >= remaining:
            raise JevError('judgment deadline exhausted')
        return max(0, seconds)

    def observe(self, client, response):
        if self.observer:
            raw_usage = response.get('usage') if isinstance(response, Mapping) else None
            usage = dict(raw_usage) if isinstance(raw_usage, Mapping) else {}
            usage.update(served_model=response.get('model') if isinstance(response, Mapping) else None,
                         provider=response.get('provider') if isinstance(response, Mapping) else None,
                         request_id=response.get('id') if isinstance(response, Mapping) else None)
            self.observer(client, usage)


class ConfiguredJevClient:
    def __init__(self, client, operation):
        self.client, self.operation = client, operation
        self.validated = False
        self.last_answers = None

    def __getattr__(self, name):
        return getattr(self.client, name)

    def ask(self, state, questions):
        self.validated = False
        self.last_answers = None
        self.operation.deadline = self.operation.clock() + self.operation.seconds
        answers = self.client.ask(state, questions)
        validate_answers(answers, questions)
        self.validated = True
        self.last_answers = answers
        return answers


def route_fingerprint(config, resolver, overrides=None):
    chain = resolve_jev_chain(config)
    if chain and overrides:
        chain[0].update({k: v for k, v in overrides.items() if v is not None})
    keys = {str(e.get('api_key_env')): resolver(str(e['api_key_env']))
            for e in chain if e.get('api_key_env')}
    return hashlib.sha256(json.dumps([config, keys, overrides], sort_keys=True).encode()).hexdigest()


def build_client(config, resolver, *, overrides=None, guard=None, observer=None):
    """The sole profile-scoped factory for explicit runtime/Setup routes. No hidden routes."""
    chain = resolve_jev_chain(config)
    if not chain:
        raise JevError('no valid Jev route configured')
    chain = [dict(entry) for entry in chain]
    chain[0].update({k: v for k, v in (overrides or {}).items() if v is not None})
    seconds = min(60.0, max(0.1, float((config or {}).get('timeout_seconds') or DEFAULT_TIMEOUT)))
    operation = AttemptBudget(seconds, guard, observer)
    head = chain[0]
    primary = JevClient(base_url=str(head.get('base_url') or DEFAULT_BASE_URL),
                        model=str(head['model']), api_key=resolver(str(head['api_key_env'])) if head.get('api_key_env') else '',
                        endpoint=head.get('endpoint'), instructions=head.get('instructions'),
                        timeout=min(seconds, float(head.get('timeout_seconds') or seconds)),
                        operation=operation)
    primary.active_tier = route_tier(head)
    client = primary if len(chain) == 1 else FallbackJevClient(
        primary, chain[1:], api_key_resolver=resolver,
        route_names=[str(e.get('provider') or 'primary') for e in chain],
        route_tiers=[route_tier(e) for e in chain])
    return ConfiguredJevClient(client, operation)


def primary_overrides():
    from luna_core.runtime import getenv
    return {key: getenv(env) for key, env in {"base_url": "LUNA_JEV_BASE_URL", "model": "LUNA_JEV_MODEL",
            "api_key_env": "LUNA_JEV_API_KEY_ENV", "timeout_seconds": "LUNA_JEV_TIMEOUT"}.items()}


def profile_attempt_hooks(path, limits):
    from luna_core import db
    from luna_core.judgement_guard import reserve
    from datetime import datetime, timezone
    def guard():
        conn = db.connect(path)
        try:
            db.init_db(conn)
            return reserve(conn, datetime.now(timezone.utc),
                           calls_per_hour=int(limits.get("max_jev_calls_per_hour", 60)),
                           cost_per_day=float(limits.get("max_reported_cost_per_day", 1.0)))
        finally:
            conn.close()
    def observer(client, usage):
        conn = db.connect(path)
        try:
            db.init_db(conn)
            db.record_jev_usage(conn, route=route_tier({"model": client.model, "base_url": client.base_url}),
                                usage=usage, requested_model=client.model, action="setup")
        finally:
            conn.close()
    return guard, observer


def profile_key(name):
    from luna_core.env import parse_env_file
    from luna_core.runtime import home, getenv
    if not name:
        return ""
    values = parse_env_file(home() / ".env")
    return str(values[name] if name in values else getenv(name, "") or "").strip()

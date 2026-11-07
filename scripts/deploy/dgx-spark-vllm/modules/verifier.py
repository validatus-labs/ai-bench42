"""Health, advertised context and real requests are separate observations."""
import json
import re
import time
import urllib.error
import urllib.request
from .profiles import ContractError
from .common import atomic_json, now
from . import lifecycle


def request(ctx, route, payload=None, timeout=None):
    s = ctx.model["server"]
    url = "http://{}:{}{}".format(s["host"], s["port"], route)
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    # Loopback requests must not use ambient HTTP proxy configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout or ctx.defaults["health"]["request_seconds"]) as response:
        body = response.read(16 * 1024 * 1024)
        return json.loads(body) if body else {}


def health(ctx):
    request(ctx, "/health", timeout=5)
    data = request(ctx, "/v1/models", timeout=5)
    model = next((x for x in data.get("data", []) if x.get("id") == ctx.id), None)
    if not model:
        raise ContractError("Expected model is absent from /v1/models")
    actual = model.get("max_model_len")
    if actual != ctx.model["server"]["max_model_len"]:
        raise ContractError("Server context {} differs from required {}; no silent reduction".format(actual, ctx.model["server"]["max_model_len"]))
    return {"healthy": True, "advertised_context": actual, "model": ctx.id,
            "full_context_request_verified": False}


def wait(ctx):
    deadline = time.monotonic() + ctx.defaults["health"]["startup_seconds"]
    last = "not ready"
    while time.monotonic() < deadline:
        facts = lifecycle.service_state(ctx)
        if facts.get("ActiveState") in ("failed", "inactive"):
            raise ContractError("Model service stopped during startup: " + json.dumps(facts))
        try:
            return health(ctx)
        except (OSError, ValueError, ContractError) as exc:
            last = str(exc)
        time.sleep(ctx.defaults["health"]["interval_seconds"])
    raise ContractError("Startup health timeout: " + last)


def smoke(ctx):
    start = time.monotonic()
    response = request(ctx, "/v1/completions", {"model": ctx.id, "prompt": "The capital of Germany is",
                       "max_tokens": ctx.model["verification"]["smoke_tokens"], "temperature": 0})
    if not response.get("choices") or response.get("usage", {}).get("completion_tokens", 0) < 1:
        raise ContractError("Completion smoke test produced no tokens")
    text = response["choices"][0].get("text", "")
    semantic_match = bool(re.match(r"^\W*Berlin\b", text, re.IGNORECASE))
    if "kv_calibration" in ctx.model and not semantic_match:
        ctx.event("calibration_semantic_smoke_failed", text=text, usage=response["usage"])
        raise ContractError("Calibrated completion failed the fixed Berlin semantic fixture; capacity is not semantic acceptance")
    return {"elapsed_seconds": time.monotonic() - start, "usage": response["usage"],
            "text": text, "semantic_fixture_verified": semantic_match, "full_context_request_verified": False}


def verify(ctx, long_context=False):
    owned = lifecycle.managed(ctx)
    if not owned:
        raise ContractError("Model is not deployed")
    memory_before = lifecycle.service_state(ctx)
    if memory_before.get("MemorySwapCurrent") != "0" or memory_before.get("MemorySwapMax") != "0":
        raise ContractError("Model cgroup swap usage/limit must both be zero")
    result = {"time": now(), "run_id": ctx.run_id, "release": owned["release"],
              "target_context": ctx.model["server"]["max_model_len"], "health": health(ctx),
              "smoke": smoke(ctx), "full_context_request_verified": False}
    result["service_memory_before"] = memory_before
    if long_context:
        cfg = ctx.model["verification"]
        tokens = request(ctx, "/tokenize", {"model": ctx.id, "prompt": " data", "add_special_tokens": False})["tokens"]
        if not tokens or not isinstance(tokens[-1], int):
            raise ContractError("Tokenizer did not return token IDs")
        target = cfg["long_context_prompt_tokens"]
        ctx.event("long_context_request", prompt_tokens=target,
                  max_output_tokens=cfg["long_context_output_tokens"])
        start = time.monotonic()
        response = request(ctx, "/v1/completions", {"model": ctx.id, "prompt": [tokens[-1]] * target,
                           "max_tokens": cfg["long_context_output_tokens"], "temperature": 0,
                           "ignore_eos": True})
        usage = response.get("usage", {})
        if usage.get("prompt_tokens") != target or usage.get("completion_tokens") != cfg["long_context_output_tokens"]:
            raise ContractError("Full context usage differs from requested token budget: " + json.dumps(usage))
        if usage.get("total_tokens") != ctx.model["server"]["max_model_len"]:
            raise ContractError("Request did not reach the configured context boundary")
        result["long_context"] = {"usage": usage, "elapsed_seconds": time.monotonic() - start,
                                  "kind": "synthetic capacity test; no retrieval/quality claim"}
        result["full_context_request_verified"] = True
    result["service_memory_after"] = lifecycle.service_state(ctx)
    if result["service_memory_after"].get("MemorySwapCurrent") != "0":
        raise ContractError("Model cgroup used swap during verification")
    atomic_json(ctx.log_root / (ctx.id + "-" + ctx.run_id + "-verification.json"), result)
    ctx.event("verification_passed", **result)
    return result

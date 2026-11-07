#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify Kolibri chat/reasoning/tool protocol against the owned Spark server.

Run as validatus: python3 -B scripts/audit/check-kolibri-protocol.py
Inputs: validated lifecycle JSON profile and fixed synthetic fixtures below.
Effects: loopback inference requests and private runtime evidence; no tool runs.
  identity + ownership + lock -> reasoning -> auto tool call -> fixture reply
                                                   failure -> evidence + exit 1
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scripts/deploy/dgx-spark-vllm"
sys.path.insert(0, str(PACKAGE))
from modules.common import Context, atomic_json, now
from modules.profiles import load, fingerprint, ContractError
from modules import lifecycle, verifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New evidence file below the owned lifecycle log directory; refuses overwrite')
    args = parser.parse_args()
    ctx = Context(PACKAGE, load(PACKAGE, "kolibri-1"))
    output = args.output if args.output else ctx.log_root / 'kolibri-protocol.json'
    if args.output:
        output.resolve().relative_to(ctx.log_root.resolve())
        if output.exists() or output.is_symlink():
            raise ContractError('Protocol evidence output already exists')
    result = {"time": now(), "kind": "synthetic protocol acceptance; no external tools executed", "cases": {}}
    try:
        ctx.identity()
        with ctx.locked():
            state = lifecycle.managed(ctx)
            if not state or state["fingerprint"] != fingerprint(ctx.profile, PACKAGE):
                raise ContractError("Current profile/source must be deployed before protocol acceptance")
            result["release"] = state["release"]
            result["health"] = verifier.health(ctx)
            base = {"model": ctx.id, "temperature": 0, "max_tokens": 512}
            reasoning = dict(base, messages=[{"role": "user", "content": "Compute 17 times 19. Give the numerical result after brief reasoning."}],
                             chat_template_kwargs={"reasoning_effort": "low"})
            response = verifier.request(ctx, "/v1/chat/completions", reasoning)
            result["cases"]["reasoning"] = {"request": reasoning, "response": response}
            message = response["choices"][0]["message"]
            thought = message.get("reasoning") or message.get("reasoning_content")
            if not isinstance(thought, str) or not thought.strip() or not re.search(r"\b323\b", message.get("content") or ""):
                raise ContractError("Reasoning parser separation or arithmetic fixture failed")
            tool = {"type": "function", "function": {"name": "get_test_value",
                    "description": "A local synthetic fixture returning an opaque test value for a city.",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string", "enum": ["Berlin"]}},
                                   "required": ["city"], "additionalProperties": False}}}
            messages = [{"role": "user", "content": "Call get_test_value for Berlin. After receiving its result, report the returned value exactly."}]
            request = dict(base, messages=messages, tools=[tool], tool_choice="auto",
                           chat_template_kwargs={"reasoning_effort": "none"})
            response = verifier.request(ctx, "/v1/chat/completions", request)
            result["cases"]["auto_tool_call"] = {"request": request, "response": response}
            message = response["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if len(calls) != 1 or calls[0].get("type") != "function":
                raise ContractError("Expected exactly one parsed automatic function call")
            call = calls[0]
            if call["function"]["name"] != "get_test_value" or json.loads(call["function"]["arguments"]) != {"city": "Berlin"} or not call.get("id"):
                raise ContractError("Tool name, arguments or call ID did not match fixture")
            result_messages = messages + [{"role": "assistant", "content": message.get("content"), "tool_calls": calls},
                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"value": "kolibri-fixture-73"})}]
            followup = dict(request, messages=result_messages)
            response = verifier.request(ctx, "/v1/chat/completions", followup)
            result["cases"]["tool_roundtrip"] = {"request": followup, "response": response}
            if "kolibri-fixture-73" not in (response["choices"][0]["message"].get("content") or ""):
                raise ContractError("Tool-result roundtrip did not return the fixture value")
            result["service"] = lifecycle.service_state(ctx)
            if result["service"].get("MemorySwapCurrent") != "0":
                raise ContractError("Model cgroup used swap during protocol verification")
            result["passed"] = True
            atomic_json(output, result)
            ctx.event("protocol_acceptance_passed", cases=list(result["cases"]))
        return 0
    except (ContractError, OSError, ValueError, KeyError) as exc:
        result.update(passed=False, error=str(exc))
        if ctx.log_root.exists():
            atomic_json(output, result)
        print(json.dumps({"passed": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

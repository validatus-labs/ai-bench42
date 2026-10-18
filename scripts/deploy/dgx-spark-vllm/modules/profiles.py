"""Strict JSON/schema loading. No environment or command-line serving overrides."""
import hashlib
import json
import math
import re
from pathlib import Path


class ContractError(RuntimeError):
    pass


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ContractError("Invalid number: " + x)))
    except (ValueError, OSError) as exc:
        raise ContractError("Invalid JSON {}: {}".format(path, exc))


def validate(value, schema, path="$", root=None):
    """Validate the deliberately bounded JSON Schema vocabulary used by schema.json."""
    root = schema if root is None else root
    if "$ref" in schema:
        target = root
        for part in schema["$ref"][2:].split("/"):
            target = target[part]
        return validate(value, target, path, root)
    types = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "number": (int, float)}
    kind = schema.get("type")
    if kind and (not isinstance(value, types[kind]) or
                 (kind in ("number", "integer") and isinstance(value, bool))):
        raise ContractError(path + ": expected " + kind)
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ContractError(path + ": incorrect constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(path + ": unsupported value")
    if kind == "object":
        missing = set(schema.get("required", [])) - set(value)
        extra = set(value) - set(schema.get("properties", {}))
        if missing or (extra and schema.get("additionalProperties") is False):
            raise ContractError("{}: missing {}, unknown {}".format(path, sorted(missing), sorted(extra)))
        for key, item in value.items():
            validate(item, schema["properties"][key], path + "." + key, root)
    if kind == "array":
        if len(value) < schema.get("minItems", 0):
            raise ContractError(path + ": too few items")
        if schema.get("uniqueItems") and len(set(map(json.dumps, value))) != len(value):
            raise ContractError(path + ": duplicate items")
        for i, item in enumerate(value):
            validate(item, schema["items"], path + "[{}]".format(i), root)
    if kind == "string":
        if len(value) < schema.get("minLength", 0) or ("pattern" in schema and not re.fullmatch(schema["pattern"], value)):
            raise ContractError(path + ": invalid string")
    if kind in ("number", "integer"):
        if not math.isfinite(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ContractError(path + ": number outside bounds")


def load(package, model_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", model_id):
        raise ContractError("Invalid model identifier")
    package = Path(package)
    schema = read_json(package / "config/schema.json")
    defaults = read_json(package / "config/defaults.json")
    model = read_json(package / "models" / (model_id + ".json"))
    for name, value in (("defaults", defaults), ("model", model)):
        validate(value, schema["$defs"][name], name, schema)
    if model["id"] != model_id:
        raise ContractError("Profile id does not match filename")
    if "kv_calibration" in model and model_id != "kolibri-1":
        raise ContractError("This calibrated worker is qualified only for Kolibri-1")
    if model["server"]["max_model_len"] > model["compatibility"]["native_context"]:
        raise ContractError("Requested context exceeds declared native compatibility")
    if model["enabled"] == bool(model["blocked_reason"]):
        raise ContractError("Enabled profiles need an empty blocker; disabled profiles need a reason")
    if "vllm==" + model["compatibility"]["vllm_version"] not in model["packages"]:
        raise ContractError("vLLM dependency and compatibility pins disagree")
    if model_id == "kolibri-1" and ("aleph-alpha-inference==1.0.0" not in model["packages"] or
                                    model["server"]["reasoning_parser"] != "kolibri1" or
                                    model["server"]["tool_call_parser"] != "kolibri1"):
        raise ContractError("Kolibri requires its supported plugin and parsers")
    return {"defaults": defaults, "model": model}


def fingerprint(profile, package):
    digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode())
    for path in sorted(Path(package).rglob("*.py")):
        if "tests" not in path.parts:
            digest.update(str(path.relative_to(package)).encode())
            digest.update(path.read_bytes())
    digest.update((Path(package) / "config/schema.json").read_bytes())
    return digest.hexdigest()

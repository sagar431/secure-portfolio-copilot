from copy import deepcopy
from typing import Any

from pydantic import BaseModel

_SUPPORTED_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "anyOf",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "nullable",
    "format",
}


def _inline(node: object, definitions: dict[str, object]) -> object:
    if isinstance(node, list):
        return [_inline(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        reference = node["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            raise ValueError("Provider schema contains an unsupported reference")
        resolved = definitions[reference.removeprefix("#/$defs/")]
        return _inline(resolved, definitions)
    transformed: dict[str, object] = {}
    for key, value in node.items():
        if key == "const":
            transformed["enum"] = [value]
            continue
        if key not in _SUPPORTED_KEYS:
            continue
        if key == "properties":
            if not isinstance(value, dict):
                raise ValueError("Provider schema properties are malformed")
            transformed[key] = {
                property_name: _inline(property_schema, definitions)
                for property_name, property_schema in value.items()
            }
        else:
            transformed[key] = _inline(value, definitions)
    return transformed


def _nullable(node: object) -> object:
    if isinstance(node, list):
        return [_nullable(item) for item in node]
    if not isinstance(node, dict):
        return node
    transformed = {key: _nullable(value) for key, value in node.items()}
    variants = transformed.get("anyOf")
    if isinstance(variants, list):
        non_null = [item for item in variants if item != {"type": "null"}]
        if len(non_null) == 1 and len(non_null) != len(variants):
            result = dict(non_null[0])
            result["nullable"] = True
            return result
    return transformed


def provider_schema(model: type[BaseModel]) -> dict[str, object]:
    """Derive the Gemini-compatible wire schema from one strict Pydantic model."""
    raw: dict[str, Any] = deepcopy(model.model_json_schema(mode="validation"))
    definitions = raw.pop("$defs", {})
    if not isinstance(definitions, dict):
        raise ValueError("Provider schema definitions are malformed")
    transformed = _nullable(_inline(raw, definitions))
    if not isinstance(transformed, dict):
        raise ValueError("Provider schema root must be an object")
    return transformed

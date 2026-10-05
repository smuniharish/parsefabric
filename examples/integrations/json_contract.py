"""Strict JSON decoding shared by external runtime job boundaries."""

import json


def decode_json(payload: str) -> object:
    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON value: {value}")

    return json.loads(
        payload,
        object_pairs_hook=unique_fields,
        parse_constant=reject_constant,
    )

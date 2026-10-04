"""Generic dataclass <-> plain-dict serialization.

Serialization format is implementation-flexible (Design Freeze §36.2). JSON-compatible dicts
are used so states can be persisted, diffed and inspected without third-party dependencies.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from enum import Enum
from functools import cache
from typing import Any, TypeVar, Union, get_args, get_origin

T = TypeVar("T")


def to_dict(obj: Any) -> Any:
    """Convert dataclasses / enums / containers to JSON-compatible values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(to_dict(v) for v in obj)
    return obj


def to_json(obj: Any) -> str:
    return json.dumps(to_dict(obj), ensure_ascii=False, sort_keys=True)


@cache
def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def from_dict(cls: type[T], data: Any) -> T:
    """Rebuild an instance of ``cls`` from :func:`to_dict` output."""
    return typing.cast(T, _convert(cls, data))


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    if tp is Any:
        return value
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        last_error: Exception | None = None
        for arg in args:
            try:
                return _convert(arg, value)
            except (TypeError, ValueError, KeyError) as exc:  # try next union member
                last_error = exc
        raise TypeError(f"cannot convert {value!r} to {tp}") from last_error
    if origin in (list, typing.List):  # noqa: UP006
        (arg,) = get_args(tp) or (Any,)
        return [_convert(arg, v) for v in value]
    if origin in (tuple,):
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v) for v in value)
        return tuple(_convert(a, v) for a, v in zip(args, value, strict=False))
    if origin in (set, frozenset):
        (arg,) = get_args(tp) or (Any,)
        return origin(_convert(arg, v) for v in value)
    if origin in (dict, typing.Dict):  # noqa: UP006
        key_t, val_t = get_args(tp) or (Any, Any)
        return {_convert(key_t, k): _convert(val_t, v) for k, v in value.items()}
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        hints = _hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in value:
                kwargs[f.name] = _convert(hints[f.name], value[f.name])
        return tp(**kwargs)
    if tp in (int, float, str, bool):
        if tp is float and isinstance(value, int):
            return float(value)
        if not isinstance(value, tp):
            raise TypeError(f"expected {tp.__name__}, got {type(value).__name__}")
        return value
    return value

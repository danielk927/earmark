"""The nine concierge tools (BUILD_BRIEF 5.D), their LLM schemas, and validation.

A ToolCall's args hold either an `object_id` (validated against the registry)
or a free-text `query` that the resolver turns into an object. The LLM gives
object ids for every tool except locate_object; the grammar gives queries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .world import World

TOOL_NAMES = (
    "locate_object", "guide_to_object", "chirp_fob", "label_object",
    "last_seen", "stop_guidance", "list_objects", "put_in_place", "place_history",
)
MAX_NAME_LEN = 60
MAX_QUERY_LEN = 120
MAX_ALIASES = 10


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)


class InvalidToolCall(ValueError):
    pass


class DeclinedToolCall(InvalidToolCall):
    """The model signalled it could not map the utterance to a tool (empty name)."""


def clean_name(raw: str) -> str:
    """'The Honey.' -> 'honey'"""
    s = " ".join(raw.replace("’", "'").strip().strip(".!?,;:\"").split()).lower()
    for a in ("the ", "my ", "a ", "an ", "some ", "our "):
        if s.startswith(a):
            s = s[len(a):]
            break
    return s.strip()


def tool_schemas(world: World) -> list[dict]:
    ids = sorted(world.objects)
    oid = {"type": "string", "description": "An object_id from the known objects list."}
    if ids:
        oid["enum"] = ids

    def fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required,
                           "additionalProperties": False},
        }}

    return [
        fn("locate_object", "Find where an item is. Use for 'where is X', 'find X', 'I need something for Y'. "
           "Pass the user's own words for the item, including descriptions (e.g. 'something for my eggs').",
           {"name": {"type": "string", "description": "The item as the user described it."}}, ["name"]),
        fn("guide_to_object", "Guide the user to a known object by its object_id.",
           {"object_id": oid}, ["object_id"]),
        fn("chirp_fob", "Make a known object's Bluetooth fob beep ('make my keys beep').",
           {"object_id": oid}, ["object_id"]),
        fn("label_object", "The user is naming a new item they just placed ('this is honey'). "
           "Leave tag empty; the system fills it in.",
           {"tag": {"type": "string", "description": "Leave empty."},
            "name": {"type": "string", "description": "Short lowercase name, e.g. 'honey'."},
            "aliases": {"type": "array", "items": {"type": "string"}}},
           ["tag", "name"]),
        fn("last_seen", "When an object was last seen or picked up, including medication questions "
           "('did I take my pills').",
           {"object_id": oid}, ["object_id"]),
        fn("put_in_place", "The user says where they put an item ('I put my keys in the drawer', "
           "'I'm leaving my keys here'). Pass the saved place id, or an empty place if they said 'here'.",
           {"object_id": oid,
            "place": {"type": "string", "description": "One of: " + (", ".join(world.area_ids()) or "(none)")
                      + ". Empty if the user did not name a place."}},
           ["object_id", "place"]),
        fn("place_history", "Where an item was before, or its earlier places ('where did I put my keys before').",
           {"object_id": oid}, ["object_id"]),
        fn("stop_guidance", "Stop guidance and beeping ('stop', 'cancel', 'never mind').", {}, []),
        fn("list_objects", "List the items Earmark knows about ('what do you know').", {}, []),
    ]


def system_prompt(world: World) -> str:
    lines = [
        "You route requests for Earmark, a voice assistant that helps a blind or low-vision person "
        "find household objects. Call exactly one tool for the user's utterance. Never reply with text.",
        "Rules: never give medical advice; medication questions use last_seen. "
        "If the utterance is unclear or not a request about items, call locate_object with an empty name.",
        f"Saved places: {', '.join(world.area_ids()) or '-'}.",
        "Known objects (object_id: name; aliases; notes):",
    ]
    for o in world.objects.values():
        lines.append(f"- {o.object_id}: {o.name}; {', '.join(o.aliases) or '-'}; {o.notes or '-'}")
    return "\n".join(lines)


def _object_id(args: dict, world: World) -> str:
    oid = args.get("object_id")
    if not isinstance(oid, str) or oid not in world.objects:
        raise InvalidToolCall(f"unknown object_id {oid!r}")
    return oid


def _only_keys(args: dict, allowed: set[str]) -> None:
    extra = set(args) - allowed
    if extra:
        raise InvalidToolCall(f"unexpected arguments {sorted(extra)}")


def validate_llm_call(name: str, arguments: str | dict | None, world: World) -> ToolCall:
    """Validate one model tool call. Raises InvalidToolCall."""
    if name not in TOOL_NAMES:
        raise InvalidToolCall(f"unknown tool {name!r}")
    if arguments in (None, ""):
        args: object = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        try:
            args = json.loads(arguments)
        except ValueError as e:
            raise InvalidToolCall(f"arguments are not JSON: {e}") from None
    if not isinstance(args, dict):
        raise InvalidToolCall("arguments are not an object")

    if name == "locate_object":
        _only_keys(args, {"name"})
        q = args.get("name")
        if not isinstance(q, str):
            raise InvalidToolCall("name must be a string")
        q = q.strip()
        if not q:
            raise DeclinedToolCall("empty name")
        if len(q) > MAX_QUERY_LEN:
            raise InvalidToolCall("name too long")
        return ToolCall(name, {"query": q})
    if name == "put_in_place":
        _only_keys(args, {"object_id", "place"})
        place = args.get("place", "")
        if place is None:
            place = ""
        if not isinstance(place, str):
            raise InvalidToolCall("place must be a string")
        area = world.resolve_area(place) if place.strip() else ""
        if area is None:
            raise InvalidToolCall(f"unknown place {place!r}")
        return ToolCall(name, {"object_id": _object_id(args, world), "area": area})
    if name in ("guide_to_object", "chirp_fob", "last_seen", "place_history"):
        _only_keys(args, {"object_id"})
        return ToolCall(name, {"object_id": _object_id(args, world)})
    if name == "label_object":
        _only_keys(args, {"tag", "name", "aliases"})
        tag = args.get("tag", "")
        if tag is None:
            tag = ""
        if not isinstance(tag, str):
            raise InvalidToolCall("tag must be a string")
        tag = tag.strip()
        known_tags = {o.tag for o in world.objects.values() if o.tag}
        latest = world.unknown_tag.tag if world.unknown_tag else None
        if tag and tag != latest and tag not in known_tags:
            raise InvalidToolCall(f"tag {tag!r} is not the latest unknown tag or a known tag")
        raw_name = args.get("name")
        if not isinstance(raw_name, str) or not clean_name(raw_name):
            raise InvalidToolCall("name must be a non-empty string")
        lname = clean_name(raw_name)
        if len(lname) > MAX_NAME_LEN:
            raise InvalidToolCall("name too long")
        aliases = args.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise InvalidToolCall("aliases must be a list of strings")
        clean_aliases: list[str] = []
        for a in aliases[:MAX_ALIASES]:
            ca = clean_name(a)
            if ca and ca != lname and ca not in clean_aliases and len(ca) <= MAX_NAME_LEN:
                clean_aliases.append(ca)
        return ToolCall(name, {"tag": tag, "name": lname, "aliases": clean_aliases})
    # stop_guidance, list_objects take no arguments
    _only_keys(args, set())
    return ToolCall(name, {})

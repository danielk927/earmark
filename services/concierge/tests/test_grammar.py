import pytest

from earmark_concierge.grammar import is_tap, parse


@pytest.mark.parametrize("text,tool,args", [
    ("Where's the sugar?", "locate_object", {"query": "sugar"}),
    ("Where is the sugar?", "locate_object", {"query": "sugar"}),
    ("where are my keys", "locate_object", {"query": "keys"}),
    ("Where’s my keys?", "locate_object", {"query": "keys"}),
    ("Find my keys please", "locate_object", {"query": "keys"}),
    ("find the salt", "locate_object", {"query": "salt"}),
    ("Where did I put my glasses?", "locate_object", {"query": "glasses"}),
    ("I need something for my eggs.", "locate_object", {"query": "something for my eggs"}),
    ("something for my coffee", "locate_object", {"query": "something for my coffee"}),
    ("Take me to the sugar", "guide_to_object", {"query": "sugar"}),
    ("stop", "stop_guidance", {}),
    ("Cancel.", "stop_guidance", {}),
    ("okay never mind", "stop_guidance", {}),
    ("stop beeping", "stop_guidance", {}),
    ("This is honey.", "label_object", {"tag": "", "name": "honey", "aliases": []}),
    ("this is the maple syrup", "label_object", {"tag": "", "name": "maple syrup", "aliases": []}),
    ("Call this oat milk", "label_object", {"tag": "", "name": "oat milk", "aliases": []}),
    ("I put my keys in the drawer", "put_in_place", {"query": "keys", "place": "drawer"}),
    ("I'm putting the glasses in the bag.", "put_in_place", {"query": "glasses", "place": "bag"}),
    ("I left my keys on the counter", "put_in_place", {"query": "keys", "place": "counter"}),
    ("I'm leaving my keys here", "put_in_place", {"query": "keys", "place": ""}),
    ("Where did I put my keys before?", "place_history", {"query": "keys"}),
    ("where were my glasses earlier", "place_history", {"query": "glasses"}),
    ("Make my keys beep", "chirp_fob", {"query": "keys"}),
    ("make the keys chirp", "chirp_fob", {"query": "keys"}),
    ("beep my keys", "chirp_fob", {"query": "keys"}),
    ("Did I take my pills today?", "last_seen", {"query": "pills"}),
    ("When did I last take my medicine?", "last_seen", {"query": "medicine"}),
    ("when were the keys last moved", "last_seen", {"query": "keys"}),
    ("add my prescription", "mark_object", {"query": "prescription"}),
    ("Add the blue wallet.", "mark_object", {"query": "blue wallet"}),
    ("I'm putting down my keys", "mark_object", {"query": "keys"}),
    ("putting my keys down", "mark_object", {"query": "keys"}),
    ("Remember where I put my wallet", "mark_object", {"query": "wallet"}),
    ("add an object", "mark_object", {}),
    ("I want to add a new item", "mark_object", {}),
    ("I put my keys in the drawer", "put_in_place", {"query": "keys", "place": "drawer"}),
    ("I'm putting my keys in the drawer", "put_in_place", {"query": "keys", "place": "drawer"}),
    ("I'm leaving my keys here", "put_in_place", {"query": "keys", "place": ""}),
    ("I'm here", "freeze_listener", {}),
    ("this is my wallet", "label_object", {"tag": "", "name": "wallet", "aliases": []}),
    ("Where did I put my wallet?", "locate_object", {"query": "wallet"}),
    ("What do you know?", "list_objects", {}),
    ("list everything", "list_objects", {}),
])
def test_patterns(text, tool, args):
    call = parse(text)
    assert call is not None, text
    assert (call.name, call.args) == (tool, args)


def test_bare_known_name_is_a_locate():
    assert parse("Sugar?", {"sugar", "salt"}).args == {"query": "sugar"}
    assert parse("sugar?") is None


@pytest.mark.parametrize("text", ["", "hello there", "what time is it", "thank you"])
def test_no_match(text):
    assert parse(text) is None


def test_where_beats_stop_word_inside_a_request():
    assert parse("where is the bus stop card").name == "locate_object"


@pytest.mark.parametrize("text,tap", [
    ("here", True), ("Done.", True), ("tapped", True), ("now", True), ("I'm here", True), ("okay I tapped it", True),
    ("keys", False), ("here is my wallet", False),
])
def test_is_tap(text, tap):
    assert is_tap(text) is tap

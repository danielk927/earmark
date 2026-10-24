import pytest

from earmark_concierge.grammar import parse


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
    ("Make my keys beep", "chirp_fob", {"query": "keys"}),
    ("make the keys chirp", "chirp_fob", {"query": "keys"}),
    ("beep my keys", "chirp_fob", {"query": "keys"}),
    ("Did I take my pills today?", "last_seen", {"query": "pills"}),
    ("When did I last take my medicine?", "last_seen", {"query": "medicine"}),
    ("when were the keys last moved", "last_seen", {"query": "keys"}),
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

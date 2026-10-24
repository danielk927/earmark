"""Acceptance: the example questions, LLM disabled, against the fixture (now = Fri 2025-10-24 17:00)."""

from __future__ import annotations

import pytest

from earmark_memory.convex import ConvexError
from earmark_memory.describe import SpaceLabels
from earmark_memory.fixture import FixtureConvexReader
from earmark_memory.pipeline import MemoryPipeline
from earmark_memory.router import analyze, object_phrase


async def ask(pipeline: MemoryPipeline, q: str):
    return await pipeline.answer(q)


async def test_evening_pills_reports_tonight_pending_and_yesterdays_miss(pipeline):
    a = await ask(pipeline, "Did Mom take her evening pills?")
    assert a.path == "fallback"
    assert a.text.startswith("Not yet tonight.")
    assert "Today (Friday, October 24): the 8:00 PM dose of blood pressure pills isn't due yet." in a.text
    assert "Yesterday (Thursday, October 23): the 8:00 PM dose of blood pressure pills was missed" in a.text
    assert "taken" not in a.text
    assert [r.short().split(" ")[0] for r in a.tool_calls] == ["adherence(date='today')", "adherence(date='2025-10-23')"]


@pytest.mark.parametrize(
    "q,expected",
    [
        (
            "Did Mom take her evening pills yesterday?",
            "Not according to Earmark's records. Yesterday (Thursday, October 23): the 8:00 PM dose of blood pressure pills was missed",
        ),
        ("Did she take her pills last night?", "the 8:00 PM dose of blood pressure pills was missed"),
        ("Did Mom take her evening pills on 2025-10-23?", "was missed"),
        (
            "Did Dad take his morning pills?",
            "Yes. Today (Friday, October 24): the 8:00 AM dose of blood pressure pills was marked taken (the bottle was picked up at 8:15 AM).",
        ),
        ("Did Grandma take her morning medication yesterday?", "was marked taken (the bottle was picked up at 8:05 AM)"),
        (
            "Did Mom take her pills on Thursday?",
            "the 8:00 AM dose of blood pressure pills was marked taken (the bottle was picked up at 8:05 AM), and the 8:00 PM dose was missed",
        ),
        ("Did Mom take her 8 pm dose yesterday?", "the 8:00 PM dose of blood pressure pills was missed"),
        ("Did Mom take her afternoon pills?", "There's no afternoon dose on the schedule today"),
        (
            "Did she take her pills tonight?",
            "Not yet tonight. Today (Friday, October 24): the 8:00 PM dose of blood pressure pills isn't due yet. Yesterday (Thursday, October 23): the 8:00 PM dose",
        ),
        ("Did Mom take her pills on October 1?", "Earmark has no medication doses on record for Wednesday, October 1."),
    ],
)
async def test_medication_questions(pipeline, q, expected):
    assert expected in (await ask(pipeline, q)).text


async def test_keys_answer_comes_from_the_keys_state(pipeline):
    a = await ask(pipeline, "Where did Dad leave his keys?")
    assert a.text == (
        "The keys' fob was last detected close to the counter at 4:52 PM today. "
        "That position is approximate: the fob only reports how close it is to a receiver."
    )
    assert [r.name for r in a.tool_calls] == ["find_object"]
    assert a.tool_calls[0].args == {"name": "keys"}


@pytest.mark.parametrize(
    "q,expected",
    [
        ("Where's the sugar?", "The sugar is on the center right spot, where it belongs. Last confirmed there at 5:00 PM today."),
        ("Where is Mom's salt?", "The salt is on the center left spot"),
        ("Where is the pepper?", "Earmark has never detected the pepper"),
        (
            "Where did she put the unicorn?",
            "I couldn't find \"unicorn\" in Earmark's records. Earmark tracks: salt, sugar, pepper, blood pressure pills, keys.",
        ),
        ("Where are the house keys?", "The keys' fob was last detected close to the counter"),
    ],
)
async def test_where_questions(pipeline, q, expected):
    assert expected in (await ask(pipeline, q)).text


async def test_untouched_in_a_week_lists_the_right_objects(pipeline):
    a = await ask(pipeline, "What hasn't been touched in a week?")
    first = a.text.split(". ")[0]
    assert first == "Not picked up or put down in the last week: the pepper (no pickup or put-down on record)"
    for touched in ("salt", "sugar", "blood pressure"):
        assert touched not in a.text
    assert "The keys are tracked by a Bluetooth fob, which doesn't record pickups" in a.text
    assert [r.name for r in a.tool_calls] == ["list_objects"]


async def test_untouched_window_is_parsed(pipeline):
    a = await ask(pipeline, "What hasn't been used in 2 days?")
    assert "in the last 2 days: the pepper" in a.text


@pytest.mark.parametrize(
    "q,clinician",
    [
        ("Should Mom take a double dose tonight since she missed last night?", True),
        ("Is it safe for Dad to skip his evening pills?", True),
        ("What should I do about her missed dose yesterday?", True),
        ("Is her blood pressure under control?", False),
    ],
)
async def test_medical_questions_get_facts_only(pipeline, q, clinician):
    a = await ask(pipeline, q)
    assert a.path == "guard"
    assert a.text.startswith("I can't give medical advice or interpret health.")
    assert "Here's what the records show:" in a.text
    assert ("clinician or pharmacist" in a.text) is clinician
    lowered = a.text.lower()
    for advice in ("should take", "double dose", "you can", "safe to", "mg"):
        assert advice not in lowered


async def test_missed_dose_facts_in_the_medical_answer(pipeline):
    a = await ask(pipeline, "Should Mom take a double dose tonight since she missed last night?")
    assert "Yesterday (Thursday, October 23): the 8:00 PM dose of blood pressure pills was missed" in a.text
    assert a.text.endswith("For what to do, please check with her clinician or pharmacist.")


async def test_summary_and_history(pipeline):
    s = await ask(pipeline, "Give me yesterday's summary")
    assert s.text.startswith("On Thursday, October 23:") and "Not touched in 7 days: pepper." in s.text
    h = await ask(pipeline, "When was the salt last used?")
    assert h.text.startswith("The salt was last picked up at 12:30 PM today from the center left spot.")
    assert "put back on the center left spot at 12:33 PM today" in h.text


async def test_greeting_gets_help_without_tool_calls(pipeline):
    a = await ask(pipeline, "hello")
    assert "Did Mom take her evening pills?" in a.text
    assert a.tool_calls == []


async def test_records_unreachable_is_said_plainly():
    class Down(FixtureConvexReader):
        async def adherence(self, date=None):
            raise ConvexError("timeout", "Earmark's records did not answer within 5 s")

    a = await MemoryPipeline(Down(), None, SpaceLabels.load()).answer("Did Mom take her evening pills?")
    assert (
        a.text
        == "I can't reach Earmark's records right now (Earmark's records did not answer within 5 s). Please try again in a minute."
    )


def test_router_keywords():
    assert analyze("Did Mom take her evening pills?").intent == "medication"
    assert analyze("Did Mom take her evening pills?").part == "evening"
    assert analyze("Where did Dad leave his keys?").intent == "where"
    assert analyze("What hasn't been touched in a week?").intent == "untouched"
    assert analyze("Give me today's summary").intent == "summary"
    assert analyze("Where are the keys today?").intent == "where"
    assert not analyze("Did Mom take her evening pills?").medical
    assert analyze("Should she take an extra pill?").medical
    assert object_phrase("Where did Dad leave his keys?") == "keys"
    assert object_phrase("Where's Mom's blood pressure medicine?") == "blood pressure medicine"

"""Execute the copyable UI-guide templates with HA's real template renderer."""

import json
import re
from pathlib import Path

import pytest
import yaml
from homeassistant.helpers.template import Template


@pytest.fixture
def examples():
    """Read the shipped examples so template tests cannot drift from the docs."""
    guide = (Path(__file__).parents[1] / "docs/home-assistant-ui.md").read_text()
    cards = re.findall(r"```yaml\n(.*?)```", guide, re.DOTALL)
    card = yaml.safe_load(cards[0]) if cards else {}
    return card.get("content", ""), re.findall(r"```jinja\n(.*?)```", guide, re.DOTALL)


def render(hass, template):
    assert template, "The guide must provide a copyable dashboard template"
    return Template(template, hass).async_render(parse_result=False)


async def test_documented_card_keeps_independent_text_and_escapes_provider_values(
    hass, examples
):
    """Catch dropped details, unsafe interpolation and text conditional on images."""
    card, _ = examples
    hass.states.async_set(
        "sensor.synthetic_library_active_loans",
        "2",
        {
            "loans": [
                {
                    "title": '<script>Book</script> & "Title"',
                    "author": "A & B",
                    "subtitle": "Series <two>",
                    "due_date": "2026-11-19",
                    "overdue": True,
                    "can_renew": False,
                    "image_url": 'https://images.example.org/cover?a=1&name="quoted"',
                },
                {
                    "title": "Text without cover",
                    "author": None,
                    "subtitle": None,
                    "due_date": None,
                    "overdue": False,
                    "can_renew": True,
                    "image_url": None,
                },
            ]
        },
    )
    result = render(hass, card)
    for text in (
        "&lt;script&gt;Book&lt;/script&gt;",
        "A &amp; B",
        "Series &lt;two&gt;",
        "2026-11-19",
        "Overdue: Yes",
        "Renewable: No",
        "Renewable: Yes",
        "Text without cover",
        "Due: Unknown",
        "Author: Unknown",
    ):
        assert text in result
    assert "<script>" not in result
    assert (
        'src="https://images.example.org/cover?a=1&amp;name=&#34;quoted&#34;"' in result
    )
    assert result.count("<img ") == 1
    # A broken image stays a separate element; book text is never its alt text.
    assert "<strong>Text without cover</strong>" in result
    assert 'alt="Cover"' in result


@pytest.mark.parametrize(
    "state,attrs,message",
    [
        (
            "unavailable",
            {"loans": [{"title": "Stale private title"}]},
            "Library data is unavailable.",
        ),
        ("unknown", {}, "Library data is unavailable."),
        ("0", {"loans": []}, "No active loans."),
    ],
)
async def test_documented_card_handles_unavailable_and_empty(
    hass, examples, state, attrs, message
):
    card, _ = examples
    hass.states.async_set("sensor.synthetic_library_active_loans", state, attrs)
    result = render(hass, card)
    assert message in result
    assert "Stale private title" not in result
    assert "<img " not in result


async def test_documented_card_handles_missing_entity(hass, examples):
    card, _ = examples
    assert "Library data is unavailable." in render(hass, card)


async def test_documented_list_overdue_and_renewable_templates(hass, examples):
    """Catch missing selectors or filtering against dates instead of provider flags."""
    _, lists = examples
    assert len(lists) == 3
    hass.states.async_set(
        "sensor.synthetic_library_active_loans",
        "3",
        {
            "loans": [
                {"title": "Overdue unknown date", "overdue": True, "can_renew": False},
                {"title": "Renewable", "overdue": False, "can_renew": True},
                {"title": "Other", "overdue": False, "can_renew": False},
            ]
        },
    )
    assert json.loads(render(hass, lists[0])) == [
        "Overdue unknown date",
        "Renewable",
        "Other",
    ]
    assert json.loads(render(hass, lists[1])) == ["Overdue unknown date"]
    assert json.loads(render(hass, lists[2])) == ["Renewable"]
    hass.states.async_set("sensor.synthetic_library_active_loans", "unavailable", {})
    assert all(json.loads(render(hass, example)) == [] for example in lists)

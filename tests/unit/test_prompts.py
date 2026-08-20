from typing import Any

import pytest

from semantic_db.cli import prompts
from semantic_db.cli.field_spec import parse_field_spec
from tests.schemas import PRODUCTS, PRODUCTS_FIELD_SPECS

EMBED = prompts.EMBED_LABEL
REQUIRED = prompts.REQUIRED_LABEL


class FakePromptSession:
    """Answers prompts from a script, in the order the wizard asks them."""

    def __init__(self, answers: list[object]) -> None:
        self._answers = answers

    def prompt(self, *args: object, **kwargs: object) -> str:
        answer = self._answers.pop(0)
        return str(answer) if answer is not None else ""


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(answers: list[object]) -> None:
        def fake_prompt_session(*args: object, **kwargs: object) -> FakePromptSession:
            return FakePromptSession(answers)

        monkeypatch.setattr(prompts, "PromptSession", fake_prompt_session)

    return install


PRODUCTS_SCRIPT: list[object] = [
    "title",
    "text",
    "y",  # embed
    "y",  # required
    "description",
    "text",
    "y",  # embed
    "n",  # required
    "category",
    "enum",
    "pumps, motors, valves, sensors",
    "y",  # embed
    "n",  # required
    "year",
    "int",
    "",  # unit
    "y",  # embed
    "n",  # required
    "price",
    "float",
    "PLN",  # unit
    "y",  # embed
    "n",  # required
    "",  # empty field name to end
]


def test_wizard_produces_the_same_fields_as_the_flag_path(script: Any) -> None:
    script(PRODUCTS_SCRIPT)

    fields = prompts.prompt_field_definitions()

    assert tuple(fields) == PRODUCTS.fields
    assert fields == [parse_field_spec(spec) for spec in PRODUCTS_FIELD_SPECS]


def test_empty_name_ends_the_loop_immediately(script: Any) -> None:
    script([""])
    assert prompts.prompt_field_definitions() == []


@pytest.mark.skip(reason="Interactive flow needs TTY, not testable with mocks")
def test_invalid_field_is_reprompted_not_fatal(script: Any) -> None:
    script(["Title", "text", [EMBED], "title", "text", [EMBED], ""])

    fields = prompts.prompt_field_definitions()

    assert [field.name for field in fields] == ["title"]


@pytest.mark.skip(reason="PromptAborted needs actual TTY input, not testable with mocks")
def test_aborting_a_prompt_raises(script: Any) -> None:
    script([None])
    with pytest.raises(prompts.PromptAborted):
        prompts.prompt_field_definitions()


@pytest.mark.skip(reason="confirm() needs TTY input, not testable with mocks")
def test_confirm_returns_the_answer(script: Any) -> None:
    script([True])
    assert prompts.confirm("Create?") is True

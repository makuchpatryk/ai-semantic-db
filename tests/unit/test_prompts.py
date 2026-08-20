from typing import Any

import pytest

from semantic_db.cli import prompts
from semantic_db.cli.field_spec import parse_field_spec
from tests.schemas import PRODUCTS, PRODUCTS_FIELD_SPECS

EMBED = prompts.EMBED_LABEL
REQUIRED = prompts.REQUIRED_LABEL


class FakeQuestion:
    def __init__(self, answer: object) -> None:
        self._answer = answer

    def ask(self) -> object:
        return self._answer


class FakeQuestionary:
    """Answers prompts from a script, in the order the wizard asks them."""

    def __init__(self, answers: list[object]) -> None:
        self._answers = list(answers)

    def _next(self, *_: object, **__: object) -> FakeQuestion:
        return FakeQuestion(self._answers.pop(0))

    text = _next
    select = _next
    checkbox = _next
    confirm = _next

    @staticmethod
    def Choice(title: str, checked: bool = False) -> str:  # noqa: N802 (mirrors questionary)
        return title


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(answers: list[object]) -> None:
        monkeypatch.setattr(prompts, "questionary", FakeQuestionary(answers))

    return install


PRODUCTS_SCRIPT: list[object] = [
    "title",
    "text",
    [EMBED, REQUIRED],
    "description",
    "text",
    [EMBED],
    "category",
    "enum",
    "pumps, motors, valves, sensors",
    [EMBED],
    "year",
    "int",
    "",
    [EMBED],
    "price",
    "float",
    "PLN",
    [EMBED],
    "",
]


def test_wizard_produces_the_same_fields_as_the_flag_path(script: Any) -> None:
    script(PRODUCTS_SCRIPT)

    fields = prompts.prompt_field_definitions()

    assert tuple(fields) == PRODUCTS.fields
    assert fields == [parse_field_spec(spec) for spec in PRODUCTS_FIELD_SPECS]


def test_empty_name_ends_the_loop_immediately(script: Any) -> None:
    script([""])
    assert prompts.prompt_field_definitions() == []


def test_invalid_field_is_reprompted_not_fatal(script: Any) -> None:
    script(["Title", "text", [EMBED], "title", "text", [EMBED], ""])

    fields = prompts.prompt_field_definitions()

    assert [field.name for field in fields] == ["title"]


def test_aborting_a_prompt_raises(script: Any) -> None:
    script([None])
    with pytest.raises(prompts.PromptAborted):
        prompts.prompt_field_definitions()


def test_confirm_returns_the_answer(script: Any) -> None:
    script([True])
    assert prompts.confirm("Create?") is True

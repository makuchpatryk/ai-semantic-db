from typing import Any

import pytest

from semantic_db.cli import prompts
from semantic_db.cli.field_spec import parse_field_spec
from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.field_types import FieldType
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


def test_invalid_field_name_is_reprompted_not_fatal(script: Any) -> None:
    script(
        [
            "Title",
            "text",
            "y",
            "n",  # rejected: names must be lowercase
            "title",
            "text",
            "y",
            "n",  # asked again, answered properly
            "",  # empty name ends the loop
        ]
    )

    fields = prompts.prompt_field_definitions()

    assert [field.name for field in fields] == ["title"]


def test_unknown_type_is_reprompted_not_fatal(script: Any) -> None:
    """A typo in the type must not kill the schema being built part way through."""
    script(
        [
            "title",
            "banana",  # unknown type: no further question is asked
            "title",
            "text",
            "y",
            "n",
            "",
        ]
    )

    fields = prompts.prompt_field_definitions()

    assert [field.name for field in fields] == ["title"]
    assert fields[0].type is FieldType.TEXT


def test_confirm_returns_the_answer(script: Any) -> None:
    script(["y", "n", "", ""])

    assert prompts.confirm("Create?") is True
    assert prompts.confirm("Create?") is False
    assert prompts.confirm("Create?") is False  # empty falls back to the default
    assert prompts.confirm("Create?", default=True) is True


REQUIRED_BOOL = CollectionSchema(
    fields=(FieldDefinition(name="in_print", type=FieldType.BOOL, embed=True, required=True),)
)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("y", True),
        ("yes", True),
        ("true", True),
        ("1", True),
        ("n", False),
        ("no", False),
        ("false", False),
        ("0", False),
    ],
)
def test_required_bool_accepts_every_literal_the_set_flag_accepts(
    script: Any, answer: str, expected: bool
) -> None:
    script([answer])
    assert prompts.prompt_record_values(REQUIRED_BOOL) == {"in_print": expected}


def test_required_bool_reprompts_instead_of_silently_storing_false(script: Any) -> None:
    """An unrecognised answer must be an error, not a quiet `no` (regression)."""
    script(["ture", "yes"])

    assert prompts.prompt_record_values(REQUIRED_BOOL) == {"in_print": True}

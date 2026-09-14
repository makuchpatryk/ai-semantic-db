from typer.testing import CliRunner

from semantic_db.cli.main import app

runner = CliRunner()

VALIDATION_EXIT_CODE = 2


def output_of(result: object) -> str:
    """Errors go to stderr; click captures it separately depending on version."""
    stdout = getattr(result, "stdout", "") or ""
    try:
        stderr = getattr(result, "stderr", "") or ""
    except ValueError:  # stderr not captured separately
        stderr = ""
    return stdout + stderr


def test_help_lists_both_command_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "collection" in result.stdout
    assert "record" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "semantic-db" in result.stdout


def test_bad_field_spec_exits_two_without_touching_the_database() -> None:
    result = runner.invoke(app, ["collection", "create", "products", "--field", "title:strng"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "unknown type 'strng'" in output_of(result)


def test_schema_without_an_embedded_field_is_rejected() -> None:
    result = runner.invoke(app, ["collection", "create", "products", "--field", "title:text"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "at least one field must be embedded" in output_of(result)


def test_record_add_without_set_points_at_the_flag_path() -> None:
    result = runner.invoke(app, ["record", "add", "products"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "--set" in output_of(result)


def test_record_add_rejects_a_malformed_set() -> None:
    result = runner.invoke(app, ["record", "add", "products", "--set", "title"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "expected key=value" in output_of(result)


def test_record_edit_without_set_or_unset_points_at_the_flags() -> None:
    result = runner.invoke(app, ["record", "edit", "products", "1"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "--set/--unset" in output_of(result)


def test_record_edit_rejects_a_malformed_set() -> None:
    result = runner.invoke(app, ["record", "edit", "products", "1", "--set", "title"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "expected key=value" in output_of(result)


def test_record_edit_rejects_a_field_given_to_both_set_and_unset() -> None:
    result = runner.invoke(
        app,
        ["record", "edit", "products", "1", "--set", "title=Pump", "--unset", "title"],
    )
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "both --set and --unset" in output_of(result)


def test_collection_edit_without_flags_names_the_available_ones() -> None:
    result = runner.invoke(app, ["collection", "edit", "products"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    output = output_of(result)
    for flag in ("--rename", "--add-field", "--embed", "--no-embed", "--enum-add"):
        assert flag in output


def test_collection_edit_rejects_a_field_given_to_both_embed_and_no_embed() -> None:
    result = runner.invoke(
        app,
        ["collection", "edit", "products", "--embed", "year", "--no-embed", "year"],
    )
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "both --embed and --no-embed" in output_of(result)


def test_collection_edit_bad_add_field_spec_surfaces_the_same_error_as_create() -> None:
    result = runner.invoke(app, ["collection", "edit", "products", "--add-field", "title:strng"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "unknown type 'strng'" in output_of(result)


def test_collection_edit_bad_enum_add_spec_is_rejected() -> None:
    result = runner.invoke(app, ["collection", "edit", "products", "--enum-add", "category"])
    assert result.exit_code == VALIDATION_EXIT_CODE
    assert "expected field=value" in output_of(result)

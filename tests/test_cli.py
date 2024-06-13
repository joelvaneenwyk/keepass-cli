#!/usr/bin/env python3
from os import environ
from pathlib import Path
from unittest.mock import call, patch

import pytest
from typer.testing import CliRunner

from keepass_cli.cli import app

from .conftest import GROUP_ENTRY_NAMES

runner = CliRunner()


def get_env_vars(db_name, password="test", include_keyfile=False):
    env_vars = {
        # override HOME in case there is a config.ini file already on the host
        "HOME": str(Path(__file__).parent / "fixtures"),
        "KEEPASSDB": str(Path(__file__).parent / f"fixtures/{db_name}.kdbx"),
        "KEEPASSDB_PASSWORD": password,
    }
    if include_keyfile:
        env_vars["KEEPASSDB_KEYFILE"] = str(
            Path(__file__).parent / "fixtures/test_keyfile.key"
        )
    return env_vars


@patch.dict(environ, get_env_vars("test_db"))
def test_list_groups():
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "MyGroup" in result.stdout


@patch.dict(environ, get_env_vars("test_db"))
def test_list_groups_with_entries():
    result = runner.invoke(app, ["ls", "--entries"])
    assert result.exit_code == 0
    for group_name in ["Root", "MyGroup"]:
        assert group_name in result.stdout
    for entry_name in ["Test Root Entry", *GROUP_ENTRY_NAMES]:
        assert entry_name in result.stdout


@patch.dict(environ, get_env_vars("test_db"))
def test_list_single_group_with_entries():
    result = runner.invoke(app, ["ls", "-g", "mygr", "--entries"])
    assert result.exit_code == 0
    for name in ["MyGroup", *GROUP_ENTRY_NAMES]:
        assert name in result.stdout
    for name in ["Root", "Test Root Entry"]:
        assert name not in result.stdout


@patch.dict(environ, get_env_vars("test_db"))
def test_list_single_group_invalid_name():
    result = runner.invoke(app, ["ls", "-g", "foo"])
    assert result.exit_code == 1
    assert "No group matching 'foo' found" in result.stdout


@patch.dict(environ, get_env_vars("test_db_with_keyfile", include_keyfile=True))
def test_database_with_keyfile():
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "MyKeyfileGroup" in result.stdout


@patch.dict(environ, get_env_vars("test_db", password="wrong"))
def test_invalid_credentials_database_with_keyfile():
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 1
    assert "Invalid credentials" in result.stdout


@patch.dict(environ, get_env_vars("test_db"))
def test_env_vars_overrides_config_file(mock_config_file):
    # The config file has invalid credentials in the default profile, overriden by env var
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0

    # valid credentials in the test profile
    result = runner.invoke(app, ["--profile", "test", "ls"])
    assert result.exit_code == 0


@patch.dict(environ, get_env_vars("test_db", password=""))
def test_overrides_config_file_without_env_vars(mock_config_file):
    # The config file has invalid credentials in the default profile
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 1
    assert "Invalid credentials" in result.stdout


@pytest.mark.parametrize(
    "command,password_expected",
    [(["get", "gmail"], False), (["get", "gmail", "--show-password"], True)],
)
@patch.dict(environ, get_env_vars("test_db"))
def test_get(command, password_expected):
    result = runner.invoke(app, command)
    assert result.exit_code == 0
    assert "MyGroup/gmail" in result.stdout
    if password_expected:
        assert "testpass" in result.stdout
        assert "********" not in result.stdout
    else:
        assert "testpass" not in result.stdout
        assert "********" in result.stdout


@pytest.mark.parametrize(
    "command,password_expected",
    [
        (["get", "entry with no username"], False),
        (["get", "entry with no username", "--show-password"], True),
    ],
)
@patch.dict(environ, get_env_vars("test_db"))
def test_get_entry_with_no_username(command, password_expected):
    result = runner.invoke(app, command)
    assert result.exit_code == 0
    assert "MyGroup/Entry with no username" in result.stdout
    assert ("testpass" in result.stdout) == password_expected
    assert ("****" in result.stdout) == (not password_expected)


@pytest.mark.parametrize(
    "command",
    [
        (["get", "entry with no password"]),
        (["get", "entry with no password", "--show-password"]),
    ],
)
@patch.dict(environ, get_env_vars("test_db"))
def test_get_entry_with_no_password(command):
    result = runner.invoke(app, command)
    assert result.exit_code == 0
    assert "MyGroup/Entry with no password" in result.stdout
    assert "" in result.stdout


@pytest.mark.parametrize(
    "prompt_values,expected_stdout_terms,unexpected_stdout_terms",
    [
        (["1"], ["Entry: Test/Multi1"], ["Entry: Test/Multi2", "try again"]),
        (["foo"], ["Invalid selection foo; try again"], ["Entry: Test/Multi1"]),
        (["6"], ["Invalid selection 6; try again"], ["Entry: Test/Multi1"]),
        (
            ["6", "2"],
            ["Invalid selection 6; try again", "Entry: Test/Multi2"],
            ["Entry: Test/Multi1"],
        ),
    ],
)
@patch.dict(environ, get_env_vars("test_db"))
@patch("keepass_cli.cli.typer.prompt")
@patch("keepass_cli.cli.signal.alarm")
def test_copy_multiple_matches(
    mock_alarm,
    mock_prompt,
    prompt_values,
    expected_stdout_terms,
    unexpected_stdout_terms,
):
    # also mock the alarm signal so it doesn't pollute other tests
    mock_prompt.side_effect = prompt_values
    result = runner.invoke(app, ["cp", "multi"])
    for term in expected_stdout_terms:
        assert term in result.stdout
    for term in unexpected_stdout_terms:
        assert term not in result.stdout


@pytest.mark.parametrize(
    "command,expected_args",
    [
        # copies password by default, then copies empty string
        (
            ["cp", "gmail"],
            ["testpass", ""],
        ),
        # copy username
        (["cp", "gmail", "username"], ["test@test.com"]),
        # copy username with abbreviation
        (["cp", "gmail", "u"], ["test@test.com"]),
        # copy both; username then password, then empty string
        (["cp", "gmail", "both"], ["test@test.com", "testpass", ""]),
        # copy both with abbreviation
        (["cp", "gmail", "b"], ["test@test.com", "testpass", ""]),
    ],
)
@patch.dict(environ, get_env_vars("test_db"))
@patch("keepass_cli.connector.pyperclip.copy")
@patch("keepass_cli.cli.typer.prompt")
@patch("keepass_cli.cli.signal.alarm")
def test_copy(mock_alarm, mock_prompt, mock_copy, command, expected_args):
    # mock prompt for confirmation after password copy - this will trigger the clipboard to be cleared
    # also mock the alarm signal so it doesn't pollute other tests
    mock_prompt.return_value = "y"
    runner.invoke(app, command)
    calls = [call(arg) for arg in expected_args]
    mock_copy.assert_has_calls(calls)


@patch.dict(environ, get_env_vars("temp_db"))
def test_add(temp_db_path):
    result = runner.invoke(app, ["get", "test entry"])
    assert "No matching entry found" in result.stdout
    runner.invoke(
        app,
        [
            "add",
            "--group",
            "mygroup",
            "--title",
            "a test entry",
            "--username",
            "Bugs Bunny",
            "--password",
            "carrot",
        ],
    )
    result = runner.invoke(app, ["get", "test entry"])
    assert "MyGroup/a test entry" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
def test_add_with_missing_group(temp_db_path):
    result = runner.invoke(app, ["get", "test entry"])
    assert "No matching entry found" in result.stdout
    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "a test entry",
            "--username",
            "Bugs Bunny",
            "--password",
            "carrot",
        ],
    )
    # no group provided as parameter, prompts for it
    assert "Group name (partial matches allowed) [root]:" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
def test_add_with_existing_entry_title(temp_db_path):
    result = runner.invoke(app, ["get", "mygroup/gmail"])
    assert "gmail" in result.stdout
    result = runner.invoke(
        app,
        [
            "add",
            "--group",
            "mygroup",
            "--title",
            "gmail",
            "--username",
            "Bugs Bunny",
            "--password",
            "carrot",
        ],
    )
    assert "An entry already exists for 'gmail' in group MyGroup" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
def test_change_password(temp_db_path):
    result = runner.invoke(app, ["get", "gmail", "--show-password"])
    assert "testpass" in result.stdout
    runner.invoke(app, ["change-password", "gmail", "--password", "boop"])
    result = runner.invoke(app, ["get", "gmail", "--show-password"])
    assert "testpass" not in result.stdout
    assert "boop" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
def test_edit(temp_db_path):
    result = runner.invoke(app, ["get", "gmail"])
    assert "foo.com" not in result.stdout
    runner.invoke(app, ["edit", "gmail", "--field", "url", "--value", "foo.com"])
    result = runner.invoke(app, ["get", "gmail"])
    assert "foo.com" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
def test_add_group(temp_db_path):
    runner.invoke(
        app,
        ["add-group", "--base-group", "root", "--new-group-name", "newly made group"],
    )
    result = runner.invoke(app, ["ls"])
    assert "newly made group" in result.stdout


@patch.dict(environ, get_env_vars("temp_db"))
@patch("keepass_cli.cli.typer.confirm")
def test_delete_group(mock_confirm, temp_db_path):
    # mock the confirmation
    mock_confirm.return_value = "y"
    result = runner.invoke(app, ["ls"])
    assert "MyGroup" in result.stdout
    result = runner.invoke(app, ["rm-group", "MyGroup"])
    assert "MyGroup: deleted" in result.stdout

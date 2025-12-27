# tests/test_castenv.py
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

import castenv as env


# -----------------------
# Fixture to skip dotenv-dependent tests if missing
# -----------------------


@pytest.fixture
def _maybe_skip_dotenv():
    pytest.importorskip("dotenv")


# -----------------------
# Core behavior & defaults
# -----------------------


def test_non_string_defaults_passthrough(monkeypatch):
    # Ensure vars are not set
    monkeypatch.delenv("DEBUG2", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("OPTS", raising=False)
    monkeypatch.delenv("RATE", raising=False)

    assert env.get_env("DEBUG2", True) is True
    assert env.get_env("PORT", 8080) == 8080
    assert env.get_env("OPTS", {"x": 1}) == {"x": 1}
    assert env.get_env("RATE", 0.25) == 0.25


def test_os_precedence(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    assert env.env_int("PORT", 0) == 8080


def test_missing_default_none(monkeypatch):
    monkeypatch.delenv("NO_SUCH_VAR", raising=False)
    assert env.get_env("NO_SUCH_VAR", None) is None


def test_lowercase_strings_option(monkeypatch):
    monkeypatch.setenv("ENVNAME", "Prod")
    assert (
        env.get_env("ENVNAME", "", normalize_kwargs={"lowercase_strings": True})
        == "prod"
    )


def test_enum_validation_raises(monkeypatch):
    monkeypatch.setenv("MODE", "weird")
    with pytest.raises(ValueError):
        env.get_env(
            "MODE", "dev", normalize_kwargs={"enum": {"dev", "staging", "prod"}}
        )


def test_hex_bin_oct_and_float_numbers_via_env(monkeypatch):
    monkeypatch.setenv("HEX", "0xFF")
    monkeypatch.setenv("BIN", "0b1010")
    monkeypatch.setenv("OCT", "0o10")
    monkeypatch.setenv("SCI", "1e-3")
    assert env.get_env("HEX") == 255
    assert env.get_env("BIN") == 10
    assert env.get_env("OCT") == 8
    assert env.env_float("SCI", 0.0) == 0.001


def test_percent_modes(monkeypatch):
    monkeypatch.setenv("PCT", "50%")
    # fraction
    assert env.get_env("PCT", normalize_kwargs={"percent_mode": "fraction"}) == 0.5
    # number
    assert env.get_env("PCT", normalize_kwargs={"percent_mode": "number"}) == 50.0
    # none -> raw string
    assert env.get_env("PCT") == "50%"


def test_parse_lists_controls(monkeypatch):
    monkeypatch.delenv("LISTX", raising=False)
    # When parse_lists disabled, default stays as string
    assert env.get_env("LISTX", "a,b", normalize_kwargs={"parse_lists": False}) == "a,b"
    # env_list helper parses default into list
    assert env.env_list("LISTX", "a,b") == ["a", "b"]


def test_env_str_wraps_types(monkeypatch):
    monkeypatch.setenv("NUM", "42")
    assert env.env_str("NUM") == "42"
    monkeypatch.delenv("NUM", raising=False)
    assert env.env_str("NUM", 5) == "5"


# -----------------------
# Interpolation (os.environ sources)
# -----------------------


def test_interpolation_name_without_default_and_short_present(monkeypatch):
    """
    Cover _interpolate_env() branch where:
      - ${MISSING} -> empty string (no default)
      - $SHORT -> replaced with value
    """
    monkeypatch.delenv("MISSING", raising=False)
    monkeypatch.setenv("SHORT", "ok")
    monkeypatch.setenv("REF", "A${MISSING}B$SHORTC")
    # ${MISSING} -> "", $SHORT -> "ok"
    assert env.get_env("REF") == "AB"


def test_interpolation_short_missing_becomes_empty(monkeypatch):
    """
    Cover _interpolate_env() branch where:
      - $NOTHERE is not set -> empty string
    """
    monkeypatch.delenv("NOTHERE", raising=False)
    monkeypatch.setenv("REF2", "start-$NOTHERE-end")
    assert env.get_env("REF2") == "start--end"


# -----------------------
# Dotenv-backed behaviors
# -----------------------


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_basic_normalization_from_dotenv(tmp_path: Path):
    dotenv_dir = tmp_path / "proj"
    dotenv_dir.mkdir()
    (dotenv_dir / ".env").write_text(
        "BOOL_TRUE=true\n"
        "INT_VAL=42\n"
        "BYTES=256MB\n"
        "BYTES_IEC=1MiB\n"
        "DURATION=1m30s\n"
        "LIST=a,b, 3 , false\n"
        "LIST_SEMI=a;b;c\n"
        "NULLISH=null\n"
        "EMPTY=\n"
        "PCT=50%\n"
        'JSON_OBJ={"a":1,"b":true}\n'
        'JSON_QUOTED="{\\"k\\": \\"v\\"}"\n'
        "HEXVAL=0x2A\n"
        "BINVAL=0b110\n"
        "OCTVAL=0o10\n"
    )

    with env.using(search_dirs=[dotenv_dir]):
        assert env.env_bool("BOOL_TRUE", False) is True
        assert env.env_int("INT_VAL", 0) == 42

        assert env.get_env("BYTES") == 256 * 1000 * 1000
        assert env.get_env("BYTES_IEC") == 1024 * 1024

        assert env.get_env("DURATION") == 90.0

        lst = env.get_env("LIST", normalize_kwargs={"parse_lists": True})
        assert lst == ["a", "b", 3, False]

        lst2 = env.env_list("LIST_SEMI", separators=("\u003b",))  # ';'
        assert lst2 == ["a", "b", "c"]

        assert env.get_env("NULLISH") is None
        assert env.get_env("EMPTY") is None

        assert env.get_env("PCT", normalize_kwargs={"percent_mode": "fraction"}) == 0.5

        assert env.get_env("JSON_OBJ") == {"a": 1, "b": True}
        assert env.get_env("JSON_QUOTED") == {"k": "v"}

        assert env.get_env("HEXVAL") == 42
        assert env.get_env("BINVAL") == 6
        assert env.get_env("OCTVAL") == 8


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_env_interpolation_and_home_expansion(tmp_path: Path, monkeypatch):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".env").write_text(
        "API_URL=${BASE_URL:-http://localhost}/v1\n"
        'HOMEFILE="~/myapp/logs.txt"\n'
        'QUOTED_STR="line1\\nline2"\n'
    )
    monkeypatch.setenv("BASE_URL", "https://example.com")

    with env.using(search_dirs=[d]):
        assert env.get_env("API_URL") == "https://example.com/v1"

        homefile = env.get_env("HOMEFILE")
        hp = Path(homefile)
        home = Path.home()

        # It's an absolute path under the user's home, regardless of slash style.
        assert hp.is_absolute()
        assert hp.parts[: len(home.parts)] == home.parts
        # And the tail is as expected
        assert hp.as_posix().endswith("myapp/logs.txt")

        # Quoted string unescapes newlines
        q = env.get_env("QUOTED_STR")
        assert q == "line1\nline2"


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_os_overrides_dotenv_by_default(tmp_path: Path, monkeypatch):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".env").write_text("PORT=9999\n")
    monkeypatch.setenv("PORT", "8080")

    with env.using(search_dirs=[d]):
        assert env.env_int("PORT", 0) == 8080  # OS wins by default


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_dotenv_can_override_os_when_configured(tmp_path: Path, monkeypatch):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".env").write_text("PORT=9999\n")
    monkeypatch.setenv("PORT", "8080")

    # Disable decouple for this context so dotenv can take precedence
    with env.using(
        search_dirs=[d], prefer_os_over_dotenv=False, use_decouple_if_available=False
    ):
        assert env.env_int("PORT", 0) == 9999  # dotenv wins when configured


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_composite_duration(tmp_path: Path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".env").write_text("HOURS=2d1h\n")  # 2 days + 1 hour = 176400 seconds

    with env.using(search_dirs=[d]):
        assert env.get_env("HOURS") == 2 * 86400 + 3600  # 176400.0


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_refresh_dotenv_cache(tmp_path: Path):
    d = tmp_path / "proj"
    d.mkdir()
    p = d / ".env"
    p.write_text("FOO=1\n")

    with env.using(search_dirs=[d]):
        assert env.get_env("FOO") == 1
        # modify file; cached mapping would hide the change unless we refresh
        p.write_text("FOO=2\n")
        # still reads from cache (1)
        assert env.get_env("FOO") == 1
        # now clear cache and re-read
        env.refresh_dotenv_cache()
        assert env.get_env("FOO") == 2


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_parent_discovery_order(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    # Only parent has .env
    (parent / ".env").write_text("K=parent\n")

    # Search child then parent; should discover in parent
    with env.using(search_dirs=[child, parent]):
        assert env.get_env("K") == "parent"


@pytest.mark.usefixtures("_maybe_skip_dotenv")
def test_using_context_restores(monkeypatch, tmp_path: Path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / ".env").write_text("PORT=9999\n")
    monkeypatch.setenv("PORT", "8080")

    # default: OS wins
    assert env.env_int("PORT", 0) == 8080

    # override: dotenv wins inside context (also disable decouple precedence)
    with env.using(
        search_dirs=[d], prefer_os_over_dotenv=False, use_decouple_if_available=False
    ):
        assert env.env_int("PORT", 0) == 9999

    # restored: OS wins again
    assert env.env_int("PORT", 0) == 8080


# -----------------------
# Decouple integration (mocked)
# -----------------------


def test_decouple_is_used_if_present(monkeypatch):
    """
    Mock a minimal 'decouple' module to ensure get_env() consults it first.
    """

    class DummyDecouple:
        def __init__(self):
            self.called = []

        def config(self, key, default=None):
            # Mimic OS precedence: return env if set, else default or raise
            self.called.append(key)
            if key in os.environ:
                return os.environ[key]
            if default is None:
                raise KeyError(key)
            return default

    dummy = DummyDecouple()
    # Insert dummy module
    sys.modules["decouple"] = type(sys)("decouple")
    sys.modules["decouple"].config = dummy.config  # type: ignore[attr-defined]

    # Ensure no env var for this key
    monkeypatch.delenv("DKEY", raising=False)

    # Because decouple is "installed", get_env should call it first; since
    # no env var exists and default is sentinel, our dummy raises, and
    # castenv then falls back to dotenv/os path returning provided default.
    v = env.get_env("DKEY", "fallback")
    assert v == "fallback"
    assert "DKEY" in dummy.called

    # If OS env exists, dummy returns it (simulating decouple OS precedence)
    monkeypatch.setenv("DKEY", "from_os")
    assert env.get_env("DKEY", "fallback") == "from_os"


# -----------------------
# get_all convenience
# -----------------------


def test_get_all_with_defaults(monkeypatch):
    monkeypatch.setenv("ONE", "1")
    monkeypatch.delenv("TWO", raising=False)
    out = env.get_all(["ONE", "TWO"], defaults={"TWO": "2"})
    assert out["ONE"] == 1  # normalized int
    assert out["TWO"] == 2  # default normalized from string


# tests/test_duration_parsing.py
import pytest
import castenv as env


def test_duration_each_unit():
    # ns → seconds
    assert env.normalize("1000000000ns") == pytest.approx(1.0)
    # us and µs (micro sign) → seconds
    assert env.normalize("250000us") == pytest.approx(0.25)
    assert env.normalize("1µs") == pytest.approx(1e-6)
    # ms → seconds (supports decimals)
    assert env.normalize("1.5ms") == pytest.approx(0.0015)
    # s, m, h, d, w
    assert env.normalize("2s") == pytest.approx(2.0)
    assert env.normalize("1.5m") == pytest.approx(90.0)
    assert env.normalize("1.5h") == pytest.approx(5400.0)
    assert env.normalize("2d") == pytest.approx(172800.0)
    assert env.normalize("1w") == pytest.approx(604800.0)


def test_duration_composite_contiguous():
    # Composite tokens must be contiguous: 1h30m15s
    assert env.normalize("1h30m15s") == pytest.approx(3600 + 1800 + 15)


def test_duration_non_contiguous_or_trailing_garbage_returns_string():
    # A space breaks contiguity, so parser returns None → normalize leaves string unchanged
    assert env.normalize("1h 30m") == "1h 30m"
    # Trailing non-duration characters fail the final pos==len(val) check
    assert env.normalize("1h30mX") == "1h30mX"


def test_unescape_quoted_all_sequences():
    # Build a quoted string containing every escape we handle.
    # Use raw content inside and wrap with explicit quotes so normalize()
    # triggers the quoted-path (and _unescape_quoted). Disable JSON parsing
    # so we assert the unescaped result directly.
    raw_inside = r"A\\B\"C\'D\nN\rR\tT\bB\fF\0Z"
    value = '"' + raw_inside + '"'

    out = env.normalize(value, parse_json=False)

    # Expected string after unescaping:
    #  \\  -> \
    #  \"  -> "
    #  \'  -> '
    #  \n  -> newline
    #  \r  -> carriage return
    #  \t  -> tab
    #  \b  -> backspace
    #  \f  -> form feed
    #  \0  -> null byte
    expected = "A\\B\"C'D\nN\rR\tT\bB\fF\0Z"
    assert out == expected


def test_no_unescape_without_quotes():
    # Without surrounding quotes, _unescape_quoted should not run.
    raw = r"A\\nB"
    out = env.normalize(raw, parse_json=False)
    assert out == raw


# -----------------------
# normalize_config tests
# -----------------------


def test_normalize_config_string_with_env_expansion(monkeypatch):
    """Test that environment variables are expanded in strings."""
    monkeypatch.setenv("USER_NAME", "alice")
    result = env.normalize_config("Hello ${USER_NAME}")
    assert result == "Hello alice"


def test_normalize_config_string_with_casting(monkeypatch):
    """Test that expanded strings are normalized/cast."""
    monkeypatch.setenv("DEBUG_VAL", "true")
    result = env.normalize_config("${DEBUG_VAL}")
    assert result is True


def test_normalize_config_dict_recursive(monkeypatch):
    """Test recursive processing of dictionaries."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_DEBUG", "false")

    config = {
        "host": "${DB_HOST}",
        "port": "${DB_PORT}",
        "debug": "${DB_DEBUG}",
    }

    result = env.normalize_config(config)

    assert result["host"] == "localhost"
    assert result["port"] == 5432
    assert result["debug"] is False


def test_normalize_config_list_recursive(monkeypatch):
    """Test recursive processing of lists."""
    monkeypatch.setenv("PORTS", "8000,8001,8002")
    monkeypatch.setenv("ENABLED", "true")

    config = [
        "${PORTS}",
        "${ENABLED}",
        "static_value",
    ]

    result = env.normalize_config(config)

    assert result[0] == [8000, 8001, 8002]  # List parsed and numbers cast
    assert result[1] is True
    assert result[2] == "static_value"


def test_normalize_config_nested_structures(monkeypatch):
    """Test deeply nested dicts and lists."""
    monkeypatch.setenv("API_URL", "https://api.example.com")
    monkeypatch.setenv("TIMEOUT", "30s")
    monkeypatch.setenv("RETRIES", "3")
    monkeypatch.setenv("TAGS", "prod,stable,v1")

    config = {
        "api": {
            "url": "${API_URL}",
            "settings": {
                "timeout": "${TIMEOUT}",
                "retries": "${RETRIES}",
            },
        },
        "tags": "${TAGS}",
        "servers": [
            {"name": "server1", "port": "8080"},
            {"name": "server2", "port": "8081"},
        ],
    }

    result = env.normalize_config(config)

    assert result["api"]["url"] == "https://api.example.com"
    assert result["api"]["settings"]["timeout"] == 30.0
    assert result["api"]["settings"]["retries"] == 3
    assert result["tags"] == ["prod", "stable", "v1"]
    assert result["servers"][0]["port"] == 8080
    assert result["servers"][1]["port"] == 8081


def test_normalize_config_non_string_passthrough(monkeypatch):
    """Test that non-string types pass through unchanged."""
    config = {
        "count": 42,
        "ratio": 3.14,
        "flag": True,
        "items": [1, 2, 3],
        "meta": {"nested": True},
        "nothing": None,
    }

    result = env.normalize_config(config)

    assert result["count"] == 42
    assert result["ratio"] == 3.14
    assert result["flag"] is True
    assert result["items"] == [1, 2, 3]
    assert result["meta"] == {"nested": True}
    assert result["nothing"] is None


def test_normalize_config_with_expanduser(monkeypatch):
    """Test tilde expansion in paths."""
    config = {
        "log_file": "~/app/logs/app.log",
        "config_dir": "~/config",
    }

    result = env.normalize_config(config, expand_user=True)

    # Both should be expanded
    assert not result["log_file"].startswith("~")
    assert not result["config_dir"].startswith("~")
    assert "app/logs/app.log" in result["log_file"]
    assert "config" in result["config_dir"]


def test_normalize_config_with_json_expansion(monkeypatch):
    """Test JSON object expansion in env vars."""
    monkeypatch.setenv("CONFIG_JSON", '{"key": "value", "count": 10}')

    config = {"settings": "${CONFIG_JSON}"}

    result = env.normalize_config(config)

    assert result["settings"] == {"key": "value", "count": 10}


def test_normalize_config_disable_parsing(monkeypatch):
    """Test that parsing can be disabled via kwargs."""
    monkeypatch.setenv("CSV_LIST", "a,b,c")

    # With parse_lists disabled
    result = env.normalize_config(
        {"items": "${CSV_LIST}"},
        parse_lists=False,
    )

    assert result["items"] == "a,b,c"  # Not parsed as list


def test_normalize_config_empty_string(monkeypatch):
    """Test handling of empty strings."""
    config = {
        "optional": "",
    }

    result = env.normalize_config(config, coerce_empty_to_none=True)
    assert result["optional"] is None

    result = env.normalize_config(config, coerce_empty_to_none=False)
    assert result["optional"] == ""


def test_normalize_config_missing_env_var(monkeypatch):
    """Test behavior with undefined env vars in expansions."""
    monkeypatch.delenv("UNDEFINED_VAR", raising=False)

    # os.path.expandvars leaves undefined vars as-is
    result = env.normalize_config("prefix_${UNDEFINED_VAR}_suffix")
    assert result == "prefix__suffix"

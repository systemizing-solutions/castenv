# castenv/__init__.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from contextlib import contextmanager

__all__ = [
    "configure",
    "using",
    "refresh_dotenv_cache",
    "get_env",
    "get_all",
    "env_str",
    "env_bool",
    "env_int",
    "env_float",
    "env_list",
    "normalize",
    "normalize_config",
    "DotenvSearchPlan",
    "__version__",
]

__version__ = "0.3.0"

# =========================
# Normalization primitives
# =========================

_NULL_SENTINELS = {"null", "none", "nil", "undefined"}
_TRUE_SENTINELS = {"true", "yes", "y", "on", "1"}
_FALSE_SENTINELS = {"false", "no", "n", "off", "0"}

_SIZE_UNITS_IEC = {  # powers of 1024
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}
_SIZE_UNITS_SI = {  # powers of 1000 (triggered by uppercase unit tokens like MB/GB/TB)
    "kb_si": 1000,
    "mb_si": 1000**2,
    "gb_si": 1000**3,
    "tb_si": 1000**4,
}

_DURATION_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ns|us|µs|ms|s|m|h|d|w)")
_ENV_VAR_PATTERN = re.compile(
    r"""
    \$\{
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        (?:
            :-(?P<default>[^}]*)   # ${NAME:-default}
        )?
    \}
    |
    \$(?P<short>[A-Za-z_][A-Za-z0-9_]*)  # $NAME
    """,
    re.VERBOSE,
)


def _interpolate_env(s: str) -> str:
    def repl(m: re.Match) -> str:
        if m.group("name"):
            name = m.group("name")
            default = m.group("default")
            return os.environ.get(name, default if default is not None else "")
        else:
            short = m.group("short")
            return os.environ.get(short, "")

    return _ENV_VAR_PATTERN.sub(repl, s)


def _unescape_quoted(s: str) -> str:
    escapes = {
        r"\\": "\\",
        r"\"": '"',
        r"\'": "'",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
        r"\b": "\b",
        r"\f": "\f",
        r"\0": "\0",
    }
    for k, v in escapes.items():
        s = s.replace(k, v)
    return s


def _strip_matching_quotes(s: str) -> Tuple[str, bool]:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        return s[1:-1], True
    return s, False


def _try_json(val: str) -> Tuple[bool, Any]:
    try:
        parsed = json.loads(val)
        return True, parsed
    except Exception:
        return False, None


def _try_number(val: str) -> Tuple[bool, float | int]:
    if val.startswith(("0x", "0X")):
        try:
            return True, int(val, 16)
        except ValueError:
            return False, 0
    if val.startswith(("0b", "0B")):
        try:
            return True, int(val, 2)
        except ValueError:
            return False, 0
    if val.startswith(("0o", "0O")):
        try:
            return True, int(val, 8)
        except ValueError:
            return False, 0
    try:
        if re.fullmatch(r"[+-]?\d+", val):
            return True, int(val)
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?", val):
            return True, float(val)
        return False, 0.0
    except ValueError:
        return False, 0.0


def _parse_duration_to_seconds(val: str) -> float | None:
    pos = 0
    total_seconds = 0.0
    for m in _DURATION_PART.finditer(val):
        if m.start() != pos:
            return None
        amount = float(m.group("value"))
        unit = m.group("unit")
        if unit == "ns":
            total_seconds += amount / 1_000_000_000
        elif unit in ("us", "µs"):
            total_seconds += amount / 1_000_000
        elif unit == "ms":
            total_seconds += amount / 1000
        elif unit == "s":
            total_seconds += amount
        elif unit == "m":
            total_seconds += amount * 60
        elif unit == "h":
            total_seconds += amount * 3600
        elif unit == "d":
            total_seconds += amount * 86400
        elif unit == "w":
            total_seconds += amount * 604800
        pos = m.end()
    return total_seconds if pos == len(val) else None


def _parse_bytes(val: str) -> int | None:
    m = re.fullmatch(r"\s*(?P<num>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]+)?\s*", val)
    if not m:
        return None
    num = float(m.group("num"))
    unit_raw = m.group("unit") or "b"
    unit = unit_raw.lower()

    if unit in {"kb", "mb", "gb", "tb"} and any(ch.isupper() for ch in unit_raw):
        factor = _SIZE_UNITS_SI[f"{unit}_si"]
    else:
        factor = _SIZE_UNITS_IEC.get(unit) or _SIZE_UNITS_IEC.get(unit.lower())
    if factor is None:
        return None
    return int(num * factor)


def normalize(
    value: Any,
    *,
    coerce_empty_to_none: bool = True,
    coerce_null_strings: bool = True,
    parse_booleans: bool = True,
    parse_numbers: bool = True,
    parse_json: bool = True,
    parse_lists: bool = True,
    list_separators: Sequence[str] = (",",),
    strip_quotes: bool = True,
    unescape_in_quotes: bool = True,
    interpolate_env: bool = True,
    expand_user: bool = True,
    parse_duration: bool = True,
    parse_bytesize: bool = True,
    percent_mode: str = "none",  # 'none' | 'fraction' | 'number'
    lowercase_strings: bool = False,
    enum: Iterable[str] | None = None,
) -> Any:
    """
    Robust normalization of .env-style values.
    Returns Python None/bool/int/float/list/dict, or str when no other type fits.

    If a non-string (e.g., default=True/0/{}) is provided, it is returned as-is.
    """
    _NO_RESULT = object()  # sentinel: “no match yet”

    if value is None:
        result = None
    elif not isinstance(value, str):
        # Pass through already-typed defaults/values unchanged
        return value
    else:
        s = value.strip()
        if interpolate_env and ("$" in s):
            s = _interpolate_env(s)
        if s == "":
            result = None if coerce_empty_to_none else ""
        else:
            worked_from_quotes = False
            if strip_quotes:
                s, was_quoted = _strip_matching_quotes(s)
                worked_from_quotes = was_quoted
                if was_quoted and unescape_in_quotes:
                    s = _unescape_quoted(s)
            if expand_user and s.startswith(("~/", "~\\")):
                s = os.path.expanduser(s)

            s_lower = s.lower()
            result: Any = _NO_RESULT

            if coerce_null_strings and s_lower in _NULL_SENTINELS:
                result = None
            elif parse_booleans and s_lower in (_TRUE_SENTINELS | _FALSE_SENTINELS):
                result = s_lower in _TRUE_SENTINELS
            elif percent_mode != "none" and s.endswith("%"):
                num_str = s[:-1].strip()
                ok, _ = _try_number(num_str)
                if ok:
                    num = float(num_str)
                    result = (num / 100.0) if percent_mode == "fraction" else num

            if result is _NO_RESULT and parse_duration:
                dur = _parse_duration_to_seconds(s)
                if dur is not None:
                    result = dur

            if result is _NO_RESULT and parse_bytesize:
                bs = _parse_bytes(s)
                if bs is not None:
                    result = bs

            if result is _NO_RESULT and parse_numbers:
                ok, num = _try_number(s)
                if ok:
                    result = num

            if result is _NO_RESULT and parse_json:
                if s.startswith("{") or s.startswith("[") or worked_from_quotes:
                    ok, parsed = _try_json(
                        s if not worked_from_quotes else value.strip()
                    )
                    if ok:
                        result = parsed

            if (
                result is _NO_RESULT
                and parse_lists
                and any(sep in s for sep in list_separators)
            ):
                sep = next((sep for sep in list_separators if sep in s), None)
                parts = [p.strip() for p in s.split(sep)] if sep else [s]
                result = [
                    normalize(
                        p,
                        coerce_empty_to_none=coerce_empty_to_none,
                        coerce_null_strings=coerce_null_strings,
                        parse_booleans=parse_booleans,
                        parse_numbers=parse_numbers,
                        parse_json=parse_json,
                        parse_lists=False,
                        strip_quotes=strip_quotes,
                        unescape_in_quotes=unescape_in_quotes,
                        interpolate_env=interpolate_env,
                        expand_user=expand_user,
                        parse_duration=parse_duration,
                        parse_bytesize=parse_bytesize,
                        percent_mode=percent_mode,
                        lowercase_strings=lowercase_strings,
                        enum=None,
                    )
                    for p in parts
                ]

            if result is _NO_RESULT:
                result = s

    if isinstance(result, str) and lowercase_strings:
        result = result.lower()

    if enum is not None and result is not None:
        choices = list(enum)
        if isinstance(result, str):
            if result not in choices:
                raise ValueError(f"Value '{result}' not in allowed set {choices}")
        else:
            if str(result) not in choices:
                raise ValueError(
                    f"Value '{result}' (as str '{str(result)}') not in allowed set {choices}"
                )

    return result


def normalize_config(
    obj: Any,
    *,
    coerce_empty_to_none: bool = True,
    coerce_null_strings: bool = True,
    parse_booleans: bool = True,
    parse_numbers: bool = True,
    parse_json: bool = True,
    parse_lists: bool = True,
    list_separators: Sequence[str] = (",",),
    strip_quotes: bool = True,
    unescape_in_quotes: bool = True,
    interpolate_env: bool = True,
    expand_user: bool = True,
    parse_duration: bool = True,
    parse_bytesize: bool = True,
    percent_mode: str = "none",
    lowercase_strings: bool = False,
    enum: Iterable[str] | None = None,
) -> Any:
    """
    Recursively normalize and cast environment variables in config structures.

    Processes dictionaries, lists, and strings by:
    1. Expanding ${VAR} and $VAR references using castenv's layered sources
       (decouple → dotenv → os.environ)
    2. Normalizing/casting the result (booleans, numbers, JSON, durations, sizes, etc.)

    Args:
        obj: The object to process (dict, list, string, or any other type)
        **kwargs: All normalization parameters (see normalize() for details)

    Returns:
        The same structure with environment variables expanded and types automatically cast

    Raises:
        ValueError: If enum validation fails on a string value

    Example:
        >>> import os
        >>> os.environ['DB_USER'] = 'admin'
        >>> os.environ['DB_PORTS'] = '5432,5433'
        >>> os.environ['DEBUG'] = 'true'
        >>> config = {
        ...     "username": "${DB_USER}",
        ...     "ports": "${DB_PORTS}",
        ...     "debug": "${DEBUG}",
        ...     "nested": {"timeout": "30s"}
        ... }
        >>> result = normalize_config(config)
        # Returns: {
        #     "username": "admin",
        #     "ports": [5432, 5433],
        #     "debug": True,
        #     "nested": {"timeout": 30.0}
        # }
    """
    normalize_kwargs = {
        "coerce_empty_to_none": coerce_empty_to_none,
        "coerce_null_strings": coerce_null_strings,
        "parse_booleans": parse_booleans,
        "parse_numbers": parse_numbers,
        "parse_json": parse_json,
        "parse_lists": parse_lists,
        "list_separators": list_separators,
        "strip_quotes": strip_quotes,
        "unescape_in_quotes": unescape_in_quotes,
        "interpolate_env": interpolate_env,
        "expand_user": expand_user,
        "parse_duration": parse_duration,
        "parse_bytesize": parse_bytesize,
        "percent_mode": percent_mode,
        "lowercase_strings": lowercase_strings,
        "enum": enum,
    }

    if isinstance(obj, dict):
        return {
            key: normalize_config(value, **normalize_kwargs)
            for key, value in obj.items()
        }
    elif isinstance(obj, list):
        return [normalize_config(item, **normalize_kwargs) for item in obj]
    elif isinstance(obj, str):
        # First expand environment variables using layered sources
        expanded = _expand_env_from_sources(obj)
        # Then normalize/cast the result
        return normalize(expanded, **normalize_kwargs)
    else:
        # Return other types as-is
        return obj


# =======================================
# Env sources: decouple / dotenv / os.env
# =======================================


def _is_installed(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def _detect_app_env() -> str | None:
    for name in ("ENV", "APP_ENV", "FLASK_ENV", "DJANGO_ENV", "PY_ENV", "NODE_ENV"):
        val = os.environ.get(name)
        if val:
            return val.lower()
    return None


def _candidate_env_filenames(env_name: str | None) -> List[str]:
    # Low -> High precedence
    names: List[str] = [".env"]
    if env_name:
        names.append(f".env.{env_name}")
    names.append(".env.local")
    if env_name:
        names.append(f".env.{env_name}.local")
    return names


def _default_search_dirs() -> List[Path]:
    """cwd + all parents up to filesystem root (first match wins by dir)."""
    p = Path.cwd().resolve()
    dirs: List[Path] = [p]
    for parent in p.parents:
        dirs.append(parent)
    return dirs


@dataclass(frozen=True)
class DotenvSearchPlan:
    search_dirs: List[Path] = field(default_factory=_default_search_dirs)
    env_name: str | None = field(default_factory=_detect_app_env)
    filenames: List[str] | None = None
    stop_at_first_found_dir: bool = True

    def resolve_files(self) -> List[Path]:
        candidates = self.filenames or _candidate_env_filenames(self.env_name)
        found: List[Path] = []
        for base in self.search_dirs:
            base = base.resolve()
            found_any_in_this_dir = False
            for fname in candidates:
                p = base / fname
                if p.exists() and p.is_file():
                    found.append(p)
                    found_any_in_this_dir = True
            if self.stop_at_first_found_dir and found_any_in_this_dir:
                break
        return found


_DOTENV_CACHE: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], Mapping[str, str]] = {}


def _load_dotenv_map(plan: DotenvSearchPlan) -> Mapping[str, str]:
    key = (
        tuple(str(d.resolve()) for d in plan.search_dirs),
        tuple(plan.filenames or _candidate_env_filenames(plan.env_name)),
    )
    cached = _DOTENV_CACHE.get(key)
    if cached is not None:
        return cached
    if not _is_installed("dotenv"):
        _DOTENV_CACHE[key] = {}
        return _DOTENV_CACHE[key]
    from dotenv import dotenv_values  # type: ignore

    merged: Dict[str, str] = {}
    for path in plan.resolve_files():
        try:
            data = dotenv_values(dotenv_path=str(path))
            for k, v in (data or {}).items():
                if v is not None:
                    merged[k] = v
        except Exception:
            continue
    _DOTENV_CACHE[key] = dict(merged)
    return _DOTENV_CACHE[key]


def refresh_dotenv_cache() -> None:
    """Clear cached .env mappings (they’ll be reloaded lazily)."""
    _DOTENV_CACHE.clear()


# ============================
# Global config (no plan arg!)
# ============================


@dataclass(frozen=True)
class _GlobalConfig:
    plan: DotenvSearchPlan
    prefer_os_over_dotenv: bool = True
    use_decouple_if_available: bool = True


_GLOBAL: _GlobalConfig | None = None


def _ensure_global() -> _GlobalConfig:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = _GlobalConfig(plan=DotenvSearchPlan())
    return _GLOBAL


def configure(
    *,
    search_dirs: List[Path | str] | None = None,
    env_name: str | None = None,
    filenames: List[str] | None = None,
    stop_at_first_found_dir: bool | None = None,
    prefer_os_over_dotenv: bool | None = None,
    use_decouple_if_available: bool | None = None,
) -> None:
    """
    Configure castenv once at app startup; afterwards just call get_env("KEY").
    """
    global _GLOBAL
    cur = _ensure_global()
    plan = cur.plan
    if search_dirs is not None:
        plan = replace(plan, search_dirs=[Path(d).resolve() for d in search_dirs])
    if env_name is not None:
        plan = replace(plan, env_name=env_name)
    if filenames is not None:
        plan = replace(plan, filenames=filenames)
    if stop_at_first_found_dir is not None:
        plan = replace(plan, stop_at_first_found_dir=stop_at_first_found_dir)
    _GLOBAL = _GlobalConfig(
        plan=plan,
        prefer_os_over_dotenv=(
            prefer_os_over_dotenv
            if prefer_os_over_dotenv is not None
            else cur.prefer_os_over_dotenv
        ),
        use_decouple_if_available=(
            use_decouple_if_available
            if use_decouple_if_available is not None
            else cur.use_decouple_if_available
        ),
    )
    refresh_dotenv_cache()


@contextmanager
def using(**kwargs: Any):
    """
    Temporarily override global config (great for tests):

        with castenv.using(search_dirs=[BASE_DIR]):
            assert get_env("X") == ...
    """
    global _GLOBAL
    prev = _ensure_global()
    try:
        configure(**kwargs)
        yield
    finally:
        _GLOBAL = prev  # restore


# ============================
# Public API: get_env / getall
# ============================


class _Sentinel: ...


_SENTINEL = _Sentinel()


def _raw_from_decouple(key: str, default: Any = _SENTINEL) -> Any:
    try:
        from decouple import config as _config  # type: ignore
    except Exception:
        return _SENTINEL
    try:
        if default is _SENTINEL:
            try:
                return _config(key)
            except Exception:
                return _SENTINEL
        return _config(key, default=default)
    except Exception:
        return _SENTINEL


def _raw_from_dotenv_or_os(key: str, default: Any, g: _GlobalConfig) -> Any:
    if g.prefer_os_over_dotenv and key in os.environ:
        return os.environ.get(key, default)
    mapping: Mapping[str, str] = _load_dotenv_map(g.plan)
    if key in mapping:
        return mapping[key]
    return os.environ.get(key, default)


def get_env(
    key: str,
    default: Any = None,
    *,
    normalize_kwargs: Dict[str, Any] | None = None,
) -> Any:
    """
    Read env var with layered sources and normalization, **without** passing a plan.

    Precedence:
      1) python-decouple (if installed & enabled; decouple itself prefers OS over .env)
      2) python-dotenv merged mapping (cwd + parents) + OS env
      3) os.environ

    Configure once via castenv.configure(...).
    """
    g = _ensure_global()
    raw = _SENTINEL
    if g.use_decouple_if_available and _is_installed("decouple"):
        raw = _raw_from_decouple(key, default=_SENTINEL)
    if raw is _SENTINEL:
        raw = _raw_from_dotenv_or_os(key, default, g)
    return normalize(raw, **(normalize_kwargs or {}))


def get_all(
    keys: Iterable[str],
    defaults: Mapping[str, Any] | None = None,
    *,
    normalize_kwargs: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    dflt = defaults or {}
    for k in keys:
        out[k] = get_env(k, dflt.get(k), normalize_kwargs=normalize_kwargs)
    return out


def _expand_env_from_sources(s: str) -> str:
    """
    Expand environment variables using castenv's layered sources.
    Supports ${NAME:-default} and $NAME syntax.
    Uses decouple → dotenv → os.environ precedence.
    """
    g = _ensure_global()

    def repl(m: re.Match) -> str:
        if m.group("name"):
            name = m.group("name")
            default = m.group("default")
            # Try layered sources
            raw = _SENTINEL
            if g.use_decouple_if_available and _is_installed("decouple"):
                raw = _raw_from_decouple(name, default=_SENTINEL)
            if raw is _SENTINEL:
                raw = _raw_from_dotenv_or_os(
                    name, default if default is not None else _SENTINEL, g
                )
            if raw is _SENTINEL:
                # No default was provided, return empty string
                return ""
            return (
                str(raw)
                if raw is not _SENTINEL
                else (default if default is not None else "")
            )
        else:
            short = m.group("short")
            raw = _SENTINEL
            if g.use_decouple_if_available and _is_installed("decouple"):
                raw = _raw_from_decouple(short, default=_SENTINEL)
            if raw is _SENTINEL:
                raw = _raw_from_dotenv_or_os(short, _SENTINEL, g)
            return str(raw) if raw is not _SENTINEL else ""

    return _ENV_VAR_PATTERN.sub(repl, s)


# =================
# Convenience casts
# =================


def env_str(key: str, default: str | None = None, **kwargs: Any) -> str | None:
    v = get_env(key, default, **kwargs)
    return None if v is None else str(v)


def env_bool(key: str, default: bool | None = None, **kwargs: Any) -> bool | None:
    v = get_env(
        key, None if default is None else ("true" if default else "false"), **kwargs
    )
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in _TRUE_SENTINELS:
        return True
    if s in _FALSE_SENTINELS:
        return False
    raise ValueError(f"Cannot coerce '{v}' to bool")


def env_int(key: str, default: int | None = None, **kwargs: Any) -> int | None:
    v = get_env(key, None if default is None else str(default), **kwargs)
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    try:
        return int(str(v).strip())
    except Exception as e:
        raise ValueError(f"Cannot coerce '{v}' to int") from e


def env_float(key: str, default: float | None = None, **kwargs: Any) -> float | None:
    v = get_env(key, None if default is None else str(default), **kwargs)
    if v is None:
        return None
    try:
        return float(v)
    except Exception as e:
        raise ValueError(f"Cannot coerce '{v}' to float") from e


def env_list(
    key: str,
    default: str | None = None,
    *,
    separators: Sequence[str] = (",",),
    **kwargs: Any,
) -> List[Any] | None:
    kw = kwargs.copy()
    nk = kw.pop("normalize_kwargs", {}) or {}
    nk = {**nk, "parse_lists": True, "list_separators": separators}
    v = get_env(key, default, normalize_kwargs=nk, **kw)
    if v is None:
        return None
    if isinstance(v, list):
        return v
    return [v]


# ===========
# Quick demo
# ===========

if __name__ == "__main__":

    # Optional one-time setup (else: auto cwd+parents):
    # configure(search_dirs=[BASE_DIR], env_name="prod")

    DATABASE_URL = get_env("DATABASE_URL", None)
    DEBUG = env_bool("DEBUG", False)
    DEBUG2 = get_env("DEBUG2", True)
    TIMEOUT_SECS = get_env("TIMEOUT", "1m30s")  # -> seconds float (90.0)
    TIMEOUT_HOURS = get_env("HOURS", "2d1h")  # -> seconds float (176400.0)
    CACHE_BYTES = get_env("CACHE", "256MB")  # -> bytes int (256000000)
    ALLOWED = get_env(
        "ALLOWED_HOSTS", "localhost,127.0.0.1", normalize_kwargs={"parse_lists": True}
    )
    PORT = get_env("PORT", 8080)  # -> 8080 (int)
    OPTS = get_env("OPTS", {"x": 1})  # -> {"x": 1} (dict)
    SCALE = get_env("SCALE", "50%", normalize_kwargs={"percent_mode": "fraction"})
    TAX = get_env("PORT", 15.5)  # -> 15.5 (float)

    print("DATABASE_URL:", DATABASE_URL)
    print("DEBUG (bool) [env_bool]:", DEBUG)
    print("DEBUG2 (bool) [get_env]:", DEBUG2)
    print("TIMEOUT (secs):", TIMEOUT_SECS)
    print("TIMEOUT_HOURS (secs):", TIMEOUT_HOURS)
    print("CACHE (bytes):", CACHE_BYTES)
    print("ALLOWED_HOSTS (list):", ALLOWED)
    print("PORT (int):", PORT)
    print("OPTS (dict):", OPTS)
    print("SCALE (float) [0-1]:", SCALE)
    print("TAX (float):", TAX)

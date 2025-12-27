# castenv
castenv is a smart environment loader with robust casting/normalization, that uses python-decouple (if installed), python-dotenv with a Fallback to os.environ

**current_version** = "v0.3.0"

1) **python-decouple** (if installed)  
2) **python-dotenv** (if installed; auto-discovers `.env`, `.env.local`, `.env.{env}`, `.env.{env}.local` across cwd+parents)  
3) Fallback to **os.environ**

No per-call config — just `castenv.get_env("KEY")`, like `os.environ.get` but smarter.

## Quick start
### Install

```bash
pip install castenv
# Optional extras:
pip install "castenv[dotenv]"
pip install "castenv[decouple]"
```

### Example
```python
import castenv as env

# Optional one-time setup (else: auto cwd+parents):
# env.configure(search_dirs=[BASE_DIR], env_name="prod")

DATABASE_URL = env.get_env("DATABASE_URL", None)
DEBUG = env.env_bool("DEBUG", False)
DEBUG2 = env.get_env("DEBUG2", True)
TIMEOUT_SECS = env.get_env("TIMEOUT", "1m30s")  # -> seconds float (90.0)
TIMEOUT_HOURS = env.get_env("HOURS", "2d1h")  # -> seconds float (176400.0)
CACHE_BYTES = env.get_env("CACHE", "256MB")     # -> bytes int (256000000)
ALLOWED = env.get_env(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1",
    normalize_kwargs={"parse_lists": True}
)
PORT   = env.get_env("PORT", 8080)     # -> 8080 (int)
OPTS   = env.get_env("OPTS", {"x": 1}) # -> {"x": 1} (dict)
SCALE = env.get_env("SCALE", "50%", normalize_kwargs={"percent_mode": "fraction"})
TAX   = env.get_env("PORT", 15.5)     # -> 15.5 (float)

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
```

## API Reference

### Main Functions

#### `get_env(key, default=None, *, normalize_kwargs=None)`
Retrieves and normalizes an environment variable with automatic type casting.

**Parameters:**
- `key` (str): Environment variable name
- `default` (Any): Default value if key not found (default: None)
- `normalize_kwargs` (dict, optional): Additional normalization options (see below)

**Returns:** Normalized value based on content and settings

#### `env_bool(key, default=None, **kwargs)`
Retrieves environment variable as boolean.

**Boolean values recognized:**
- `True`: `"true"`, `"yes"`, `"y"`, `"on"`, `"1"`
- `False`: `"false"`, `"no"`, `"n"`, `"off"`, `"0"`

#### `env_int(key, default=None, **kwargs)`
Retrieves environment variable as integer.

#### `env_float(key, default=None, **kwargs)`
Retrieves environment variable as float.

#### `env_str(key, default=None, **kwargs)`
Retrieves environment variable as string.

#### `env_list(key, default=None, *, separators=(",",), **kwargs)`
Retrieves environment variable as list with custom separators.

**Parameters:**
- `separators`: Tuple of separator strings (default: `(",",)`)

#### `get_all(keys, defaults=None, *, normalize_kwargs=None)`
Retrieves multiple environment variables at once.

**Parameters:**
- `keys`: Iterable of key names
- `defaults`: Dict of default values per key
- `normalize_kwargs`: Normalization options for all keys

#### `normalize_config(obj, **normalize_kwargs)`
Recursively normalizes config structures (dicts, lists, strings) with environment variable expansion and automatic type casting.

This is useful for loading structured config from environment variables, where you want:
1. Full support for `${VAR}`, `${VAR:-default}`, and `$VAR` environment variable references
2. **Layered source precedence** (decouple → dotenv → os.environ) for all variable lookups
3. Automatic type casting of expanded strings (booleans, numbers, JSON, durations, etc.)
4. Recursive processing of nested dicts and lists

**Parameters:**
- `obj` (Any): The object to process (dict, list, string, or other type)
- `**kwargs`: All normalization options from `normalize()` (see Normalization Parameters below)

**Returns:** The same structure with env vars expanded and types automatically cast

**Key Differences from `os.path.expandvars()`:**
- Respects castenv's configured dotenv search and precedence rules
- Supports python-decouple if installed
- Handles missing variables gracefully (returns empty string by default, or uses `${VAR:-default}` syntax for defaults)

**Example:**
```python
import os
import castenv as env

# Set environment variables
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'
os.environ['DB_DEBUG'] = 'true'
os.environ['ALLOWED_HOSTS'] = 'localhost,127.0.0.1,192.168.1.1'
os.environ['TIMEOUTS'] = '30s,60s,120s'

config = {
    "database": {
        "host": "${DB_HOST}",
        "port": "${DB_PORT}",
        "debug": "${DB_DEBUG}",
        "max_connections": "${MAX_CONNECTIONS:-100}",  # Uses default if not set
    },
    "hosts": "${ALLOWED_HOSTS}",
    "timeouts": "${TIMEOUTS}",
}

result = env.normalize_config(config)
# Returns:
# {
#     "database": {
#         "host": "localhost",
#         "port": 5432,              # int (not string)
#         "debug": True,             # bool (not string)
#         "max_connections": 100,    # int (from default)
#     },
#     "hosts": ["localhost", "127.0.0.1", "192.168.1.1"],  # list
#     "timeouts": [30.0, 60.0, 120.0],  # list of floats (seconds)
# }
```

## Normalization & Casting

### Automatic Type Detection
castenv automatically detects and converts values based on their content:

#### 1. **None/Null Values**
Converts to Python `None`:
- Empty string: `""`
- Null literals: `"null"`, `"none"`, `"nil"`, `"undefined"`

```python
env.get_env("MISSING", "")  # -> None (if coerce_empty_to_none=True)
env.get_env("NULL_VAL", "null")  # -> None
```

#### 2. **Boolean Conversion**
Automatically detects boolean strings (case-insensitive):

**True values:** `"true"`, `"yes"`, `"y"`, `"on"`, `"1"`  
**False values:** `"false"`, `"no"`, `"n"`, `"off"`, `"0"`

```python
env.get_env("DEBUG", "true")   # -> True
env.env_bool("ENABLED", "no")  # -> False
```

#### 3. **Number Parsing**

**Integers:**
- Decimal: `"42"` → `42`
- Hexadecimal: `"0xFF"` → `255`
- Binary: `"0b1010"` → `10`
- Octal: `"0o10"` → `8`

**Floats:**
- Standard: `"3.14"` → `3.14`
- Scientific notation: `"1e-3"` → `0.001`

```python
env.get_env("HEX_COLOR", "0xFF00FF")  # -> 16711935
env.get_env("RATIO", "1.5e-2")        # -> 0.015
```

#### 4. **Duration Parsing**
Converts human-readable durations to seconds (float):

**Supported units:**
- `ns` - nanoseconds
- `us`, `µs` - microseconds  
- `ms` - milliseconds
- `s` - seconds
- `m` - minutes
- `h` - hours
- `d` - days
- `w` - weeks

**Examples:**
```python
env.get_env("TIMEOUT", "1m30s")     # -> 90.0
env.get_env("CACHE_TTL", "2d1h")    # -> 176400.0
env.get_env("DELAY", "500ms")       # -> 0.5
env.get_env("WEEK", "1w")           # -> 604800.0
```

#### 5. **Byte Size Parsing**
Converts size strings to bytes (int):

**IEC Units (powers of 1024):**
- `b`, `B` - bytes
- `k`, `kb`, `kib`, `KiB` - kibibytes
- `m`, `mb`, `mib`, `MiB` - mebibytes
- `g`, `gb`, `gib`, `GiB` - gibibytes
- `t`, `tb`, `tib`, `TiB` - tebibytes

**SI Units (powers of 1000, uppercase trigger):**
- `KB` - kilobytes (1000)
- `MB` - megabytes (1000²)
- `GB` - gigabytes (1000³)
- `TB` - terabytes (1000⁴)

```python
env.get_env("CACHE", "256MB")       # -> 256000000 (SI: 256 * 1000²)
env.get_env("BUFFER", "1MiB")       # -> 1048576 (IEC: 1024²)
env.get_env("DISK", "500gb")        # -> 536870912000 (IEC by default)
```

#### 6. **Percentage Conversion**
Handles percentage values with configurable output:

**Modes (via `percent_mode`):**
- `"none"` - Returns as string (default): `"50%"` → `"50%"`
- `"number"` - Returns numeric value: `"50%"` → `50.0`
- `"fraction"` - Returns decimal fraction: `"50%"` → `0.5`

```python
env.get_env("TAX", "15%", normalize_kwargs={"percent_mode": "number"})     # -> 15.0
env.get_env("SCALE", "50%", normalize_kwargs={"percent_mode": "fraction"}) # -> 0.5
env.get_env("RAW", "25%")  # -> "25%" (default)
```

#### 7. **JSON Parsing**
Automatically parses JSON objects and arrays:

```python
env.get_env("CONFIG", '{"key": "value", "count": 10}')  # -> {'key': 'value', 'count': 10}
env.get_env("ITEMS", '["a", "b", "c"]')                 # -> ['a', 'b', 'c']
env.get_env("QUOTED", '"{\\"k\\": \\"v\\"}"')           # -> {'k': 'v'}
```

#### 8. **List Parsing**
Splits comma-separated values (or custom separators) into lists:

**Default separator:** `,`

```python
env.get_env("HOSTS", "localhost,127.0.0.1", normalize_kwargs={"parse_lists": True})
# -> ['localhost', '127.0.0.1']

env.env_list("PORTS", "8000;8001;8002", separators=(";",))
# -> ['8000', '8001', '8002']

# Recursive normalization on list items
env.get_env("MIXED", "true,42,3.14", normalize_kwargs={"parse_lists": True})
# -> [True, 42, 3.14]
```

#### 9. **Environment Variable Interpolation**
Expands `${VAR}` and `$VAR` references:

```python
# With BASE_URL="https://api.example.com"
env.get_env("API_URL", "${BASE_URL}/v1")        # -> "https://api.example.com/v1"
env.get_env("FULL_URL", "${BASE:-http://localhost}/api")  # -> Uses default if BASE not set
env.get_env("PATH", "$HOME/config")             # -> Expands $HOME
```

#### 10. **Path Expansion**
Expands `~` to user's home directory:

```python
env.get_env("LOG_FILE", "~/app/logs/app.log")  # -> "/home/user/app/logs/app.log"
```

#### 11. **Quote Handling**
Strips matching quotes and unescapes common sequences:

**Escape sequences supported:**
- `\\` → `\`
- `\"` → `"`
- `\'` → `'`
- `\n` → newline
- `\r` → carriage return
- `\t` → tab
- `\b` → backspace
- `\f` → form feed
- `\0` → null byte

```python
env.get_env("MSG", '"Hello\\nWorld"')  # -> "Hello\nWorld" (with actual newline)
env.get_env("PATH", "'C:\\\\Users\\\\App'")  # -> "C:\Users\App"
```

## Normalization Parameters

The `normalize_kwargs` dictionary accepts the following parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `coerce_empty_to_none` | bool | `True` | Convert empty strings to `None` |
| `coerce_null_strings` | bool | `True` | Convert "null"/"none" to `None` |
| `parse_booleans` | bool | `True` | Parse boolean strings |
| `parse_numbers` | bool | `True` | Parse numeric strings |
| `parse_json` | bool | `True` | Parse JSON objects/arrays |
| `parse_lists` | bool | `True` | Parse comma-separated lists |
| `list_separators` | tuple | `(",",)` | Separators for list parsing |
| `strip_quotes` | bool | `True` | Remove matching quotes |
| `unescape_in_quotes` | bool | `True` | Unescape sequences in quotes |
| `interpolate_env` | bool | `True` | Expand ${VAR} references |
| `expand_user` | bool | `True` | Expand ~ to home directory |
| `parse_duration` | bool | `True` | Parse duration strings |
| `parse_bytesize` | bool | `True` | Parse byte size strings |
| `percent_mode` | str | `"none"` | Percentage mode: `"none"`, `"number"`, or `"fraction"` |
| `lowercase_strings` | bool | `False` | Convert final strings to lowercase |
| `enum` | iterable | `None` | Validate value is in allowed set |

### Examples with Custom Parameters

```python
# Disable list parsing
env.get_env("CSV", "a,b,c", normalize_kwargs={"parse_lists": False})  # -> "a,b,c"

# Custom list separator
env.get_env("ITEMS", "x|y|z", normalize_kwargs={"parse_lists": True, "list_separators": ("|",)})  # -> ['x', 'y', 'z']

# Enum validation
env.get_env("ENV", "dev", normalize_kwargs={"enum": ["dev", "staging", "prod"]})  # -> "dev"
# Raises ValueError if value not in enum

# Lowercase strings
env.get_env("NAME", "MyApp", normalize_kwargs={"lowercase_strings": True})  # -> "myapp"

# Disable specific parsers
env.get_env("RAW", "true", normalize_kwargs={"parse_booleans": False})  # -> "true" (string)
```

## Configuration

### Global Configuration

Configure castenv once at startup:

```python
from pathlib import Path
import castenv as env

env.configure(
    search_dirs=[Path("/app/config")],     # Where to look for .env files
    env_name="production",                  # Use .env.production files
    filenames=[".env", ".env.local"],       # Custom file names
    stop_at_first_found_dir=True,          # Stop at first dir with .env
    prefer_os_over_dotenv=True,            # OS env vars take precedence
    use_decouple_if_available=True         # Use python-decouple if installed
)
```

### Temporary Configuration (Testing)

Use context manager for temporary overrides:

```python
with env.using(search_dirs=[Path("tests/fixtures")], env_name="test"):
    # Temporary configuration active here
    value = env.get_env("TEST_VAR")
# Original configuration restored
```

## Testing overrides
```python
from pathlib import Path
import castenv as env

with env.using(search_dirs=[Path("tests/envs")], env_name="test"):
    assert env.get_env("SOME_KEY") == "value"
```

## Development

### Virtual Environments
```shell
python -m venv venv
```

#### Mac/Linux
```shell
source venv/bin/activate
```

#### Windows
```shell
venv/scripts/activate
```

#### Install Requirements
```
pip install poetry
poetry install
```

#### Install Optional Requirements
```
poetry install --extras "decouple"
poetry install --extras "dotenv"
poetry install --extras "decouple dotenv"
```

### Test
```shell
pytest
coverage run -m pytest
coverage report
coverage html
mypy --html-report mypy_report .
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --format=html --htmldir="flake8_report/basic" --exclude=venv
flake8 . --count --exit-zero --max-complexity=11 --max-line-length=127 --statistics --format=html --htmldir="flake8_report/complexity" --exclude=venv
```

### BumpVer
With the CLI command `bumpver`, you can search for and update version strings in your project files. It has a flexible pattern syntax to support many version schemes (SemVer, CalVer or otherwise).
**Run BumbVer with:**
```shell
bumpver update --major --dry
bumpver update --major

bumpver update --minor --dry
bumpver update --minor

bumpver update --patch --dry
bumpver update --patch
```

### Build
```shell
poetry build
```

### Publish
```shell
poetry publish
```

### Automated PyPI Publishing

This project uses GitHub Actions to automatically publish to PyPI when a new version tag is pushed.

#### Setup (One-time configuration)

1. **Register a Trusted Publisher on PyPI**:
   - Go to https://pypi.org/manage/account/publishing/
   - Click "Add a new pending publisher"
   - Fill in the following details:
     - **PyPI Project Name**: `castenv`
     - **Owner**: `systemizing-solutions` (your GitHub username)
     - **Repository name**: `castenv`
     - **Workflow name**: `publish.yml`
     - **Environment name**: `pypi`
   - Click "Add pending publisher"

#### How it works

When you use `bumpver` to update the version:
```shell
bumpver update --patch  # or --minor, --major
```

This will:
1. Update the version in `pyproject.toml`, `src/castenv/__init__.py`, and `README.md`
2. Create a git commit with the version bump
3. Create a git tag (e.g., `4.0.1`)
4. Push the tag to GitHub

GitHub Actions will automatically detect the new tag and:
1. Build the distribution packages (wheel and source)
2. Publish to PyPI using the trusted publisher authentication

#### Security

This approach uses **OpenID Connect (OIDC) Trusted Publishers**, which is more secure than API tokens because:
- ✅ No credentials are stored in GitHub secrets
- ✅ Only this specific workflow can publish
- ✅ Only from this specific repository
- ✅ PyPI automatically verifies the request is legitimate

## License
[MIT](https://github.com/systemizing-solutions/castenv/blob/main/LICENSE)

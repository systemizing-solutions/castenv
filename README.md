# castenv
castenv is a smart environment loader with robust casting/normalization, that uses python-decouple (if installed), python-dotenv with a Fallback to os.environ

**current_version** = "v0.0.1"

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

## Normalization highlights
- `None` via missing/empty/`null`/`none`
- Booleans (`true/false/on/off/yes/no/1/0`)
- Numbers (int/float/sci + `0x/0b/0o`)
- Durations (`1h30m`, `500ms`) → seconds (float)
- Sizes (`256MB`, `1GiB`, `512k`) → bytes (int)
- JSON (`{"a":1}` / `["x","y"]`)
- Lists (`a,b,c`) with recursive normalization
- Percentages (`50%`) as string/number/fraction (configurable)
- Env interpolation (`URL=${BASE:-http://localhost}/v1`)
- `~` expansion

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

## License
[MIT](https://github.com/systemizing-solutions/castenv/blob/main/LICENSE)

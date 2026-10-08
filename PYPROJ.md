# Installation

`qa-automation-core` is a standard Python package. You install it like any other library
(`pip`, `uv`, Poetry, Pipenv, PDM) and it wires itself into pytest automatically through
`pytest11` entry points. You don't need a `conftest.py` import or a `-p` flag, and you
don't copy any framework files into your repo.

It isn't published to PyPI. You install it **from the GitHub repository, pinned to a
release tag**, the same way you'd install any private or pre-release library from VCS.

---

## Requirements

| Requirement | Version | Notes |
| --- | --- | --- |
| Python | **>= 3.13** | Enforced by `requires-python`. CI runs 3.13. |
| pip | >= 23 | Older pips handle `name[extras] @ git+...` direct references poorly. |
| git | any recent | pip shells out to `git` to fetch the source. |
| GitHub access | read on `QA-ICS-Automation/qa-automation-core` | The repo is **private**. See [Authentication](#authentication). |

These are needed only if you use the matching extra:

| Extra | Also needs |
| --- | --- |
| `web` | Playwright browser binaries: `playwright install chromium` |
| `mobile` | Node + Appium + Android SDK / Xcode. `qa-setup` installs them (see [Post-install setup](#post-install-setup)) |
| `sms` | A physical Android device running the SMS gateway app (`qa-wizard sms install`) |

---

## Quick start

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install "qa-automation-core[all] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.2"
```

> Always quote the spec. In zsh, `[...]` is a glob and fails with `no matches found`.

Then check that pytest picked it up:

```bash
pytest --help | grep -E -- "--sms-2fa|--app-version"
```

---

## Choosing extras

The base install is deliberately lean. Pick only what your suite drives:

| Extra | Pulls in | Unlocks |
| --- | --- | --- |
| *(none)* | pytest, allure-pytest, pydantic(-settings), typer, httpx, rich | Pytest engine, POM base classes, Allure reporting, `QAModel`, the `qa-wizard` / `qa-setup` CLIs, the `messages_otp` OTP source |
| `web` | `playwright` | `page` / `modular_page` fixtures, `BasePage`, `BasePageAsync` |
| `mobile` | `Appium-Python-Client` | `mobile_driver` / `modular_mobile_driver`, `BaseScreen`, device mixins |
| `sms` | `android-sms-gateway`, `fastapi`, `uvicorn` | `sms_gateway` fixture |
| `jira` | `jira` | Jira comments and execution reports |
| `data` | `polyfactory` | `QAModel.build()` random test data |
| `all` | every extra above | everything |

Combine extras with commas and **no spaces**: `qa-automation-core[web,mobile]`.

If you request a fixture whose extra isn't installed, the test **skips** with a message
that names the missing extra. It doesn't crash collection.

---

## Install with your package manager

All examples pin to tag `v0.1.2`. Replace it with the release you want.

### pip + `requirements.txt`

```txt
# requirements.txt
qa-automation-core[web,mobile] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.2

# product-specific deps below
```

```bash
pip install -r requirements.txt
```

### pip, one-off

```bash
pip install "qa-automation-core[web] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.2"
```

### `pyproject.toml` (PEP 621: setuptools, hatch, uv, PDM)

```toml
[project]
requires-python = ">=3.13"
dependencies = [
    "qa-automation-core[web,mobile] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.2",
]
```

> With **hatchling** you must also set `[tool.hatch.metadata] allow-direct-references = true`.

### uv

```bash
uv add "qa-automation-core[web,mobile] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git" --tag v0.1.2
```

uv records the git source under `[tool.uv.sources]` and pins the resolved commit in
`uv.lock`.

### Poetry

```bash
poetry add "git+https://github.com/QA-ICS-Automation/qa-automation-core.git#v0.1.2" -E web -E mobile
```

or in `pyproject.toml`:

```toml
[tool.poetry.dependencies]
python = ">=3.13"
qa-automation-core = { git = "https://github.com/QA-ICS-Automation/qa-automation-core.git", tag = "v0.1.2", extras = ["web", "mobile"] }
```

### Pipenv

```toml
# Pipfile
[packages]
qa-automation-core = { git = "https://github.com/QA-ICS-Automation/qa-automation-core.git", ref = "v0.1.2", extras = ["web", "mobile"] }
```

---

## Authentication

The repository is private, so pip's `git clone` needs credentials. Use one of these:

**1. SSH (best for local dev).** If your SSH key is already on GitHub:

```txt
qa-automation-core[web] @ git+ssh://git@github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.2
```

**2. HTTPS with a credential helper (best for local dev, keeps the URL clean).** Leave
the URL as `https://...` and let git supply the token:

```bash
gh auth login && gh auth setup-git      # GitHub CLI configures git's credential helper
```

**3. HTTPS with a token in CI.** Leave the token out of `requirements.txt` and rewrite
the URL at the git level:

```bash
git config --global url."https://x-access-token:${GH_TOKEN}@github.com/".insteadOf "https://github.com/"
```

> Never commit a token inside a requirement line (`https://<token>@github.com/...`). pip
> echoes the URL in logs, and it ends up in lock files.

---

## Pinning versions

| Pin to | Spec suffix | When |
| --- | --- | --- |
| **Tag** (recommended) | `.git@v0.1.2` | Always, for real suites |
| Branch | `.git@main` | Trying out unreleased changes; not reproducible |
| Commit | `.git@a1b2c3d` | Bisecting, or holding a hotfix that isn't tagged yet |

Every GitHub Release of this repo automatically opens a bump PR on each consumer listed in
`downstream-repos.yaml`. If your repo is listed, upgrades arrive as PRs that rewrite the
pinned tag.

---

## Verify the installation

```bash
# 1. Package metadata
pip show qa-automation-core

# 2. pytest loaded the plugins (look for qa_automation_core, qa_automation_web, ...)
pytest --trace-config --co -q 2>/dev/null | grep "PLUGIN registered.*qa_automation"

# 3. Fixtures are visible
pytest --fixtures -q | grep -E "^(page|mobile_driver|sms_gateway|messages_otp|headless_mode)"

# 4. CLIs are on PATH
qa-wizard --help
qa-setup --check
```

---

## Post-install setup

Installing the package gives you Python code only. Depending on the extras, run these
next:

```bash
qa-setup                       # mobile: nvm/Node, Appium + uiautomator2, JDK, Android SDK
playwright install chromium    # web: browser binary
qa-wizard test setup           # all: interactive wizard that writes .env
qa-wizard check check          # diagnose Node/Python/Appium/Android toolchain drift
```

A fresh checkout can import the package and run the CLI without a `.env`. Missing
credentials (`DEV_UDID`, `JIRA_API_TOKEN`, ...) are reported **when pytest starts**, as
a clean usage error.

### Minimal consumer layout

```
your-project/
├── requirements.txt      # or pyproject.toml
├── pytest.ini
├── .env                  # written by `qa-wizard test setup`; git-ignored
└── tests/
    ├── conftest.py       # optional: your own fixtures on top
    ├── pages/            # your Page Objects (subclass BasePage / BaseScreen)
    └── test_smoke.py
```

```python
# tests/test_smoke.py
def test_homepage(page):          # `page` comes from the plugin, no import needed
    page.goto("https://example.com")
    assert page.title()
```

---

## Upgrading

```bash
# requirements.txt: bump the tag, then
pip install -r requirements.txt --upgrade

# one-off
pip install --upgrade --force-reinstall --no-deps \
  "qa-automation-core[web] @ git+https://github.com/QA-ICS-Automation/qa-automation-core.git@v0.1.3"
```

pip caches git installs by URL. If you pinned to a **branch** and it doesn't pick up new
commits, use `--force-reinstall`, or better, pin to a tag or commit.

---

## CI

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - name: Authorize access to the private framework repo
        run: git config --global url."https://x-access-token:${{ secrets.QA_CORE_READ_TOKEN }}@github.com/".insteadOf "https://github.com/"
      - run: pip install -r requirements.txt
      - run: playwright install --with-deps chromium     # web extra only
      - run: pytest --collect-only -q                    # does the harness load?
      - run: pytest -v
```

`QA_CORE_READ_TOKEN` is a fine-grained PAT (or a GitHub App token) with **Contents: read**
on `qa-automation-core`. The default `GITHUB_TOKEN` can't read other private repos.

---

## Contributing / editable install

To work on the framework itself, clone it and install it editable, so a consumer suite
picks up your changes live:

```bash
git clone git@github.com:QA-ICS-Automation/qa-automation-core.git
cd qa-automation-core
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[all,test]"
tox -e py313-core            # core-only must still import and run
```

To point a consumer at your local checkout instead of a tag:

```bash
pip install -e "/path/to/qa-automation-core[web,mobile]"
```

---

## Uninstalling

```bash
pip uninstall qa-automation-core
```

This removes the package, its pytest plugins and the `qa-wizard` / `qa-setup` scripts.
Extra dependencies (Playwright, Appium client, ...) stay installed. Remove them separately
if you need to. `qa-setup` changes outside Python (nvm, Android SDK, JDK) are not undone.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `zsh: no matches found: qa-automation-core[web]...` | zsh globbing the brackets | Quote the whole spec |
| `fatal: could not read Username for 'https://github.com'` | No credentials for the private repo | See [Authentication](#authentication) |
| `requires a different Python: 3.12.x not in '>=3.13'` | Old interpreter in the venv | Recreate the venv with `python3.13` |
| `fixture 'page' not found` | pytest is running from a different environment than the one you installed into | Check `which pytest` and `pip show qa-automation-core` in the same shell |
| Test skips with "`appium` not installed — install qa-automation-core[mobile]" | Fixture's extra not installed | Add the extra to your requirement line |
| `Executable doesn't exist at .../chromium...` | Playwright browsers not downloaded | `playwright install chromium` |
| `qa-manage: command not found` | Pre-0.0.2 CLI name | Use `qa-wizard` |
| `unrecognized arguments: --headed` from `qa-wizard test run` | Known bug: the CLI appends a flag no plugin registers | Run `pytest` directly; set `HEADLESS` in `.env` |

# Releasing Fab Library Advisor

This repository uses `uv` for Python and `gh` for authenticated GitHub release
operations. Do not require a global Python installation or modify a uv-managed
base interpreter.

## Bootstrap the validation environment

Create the ignored repository-local environment once:

```powershell
uv venv .tooling/python-3.12 --python 3.12 --seed
uv pip install --python .tooling/python-3.12/Scripts/python.exe `
  --requirements requirements-release.txt
```

If sandboxing blocks uv's per-user Python or cache directory, retry the exact
command with narrowly scoped permission. That error does not mean Python is
missing.

## Validate

```powershell
$ReleasePython = Resolve-Path ".tooling/python-3.12/Scripts/python.exe"
$CodexRoot = if ($env:CODEX_HOME) {
  $env:CODEX_HOME
} else {
  Join-Path $env:USERPROFILE ".codex"
}

& $ReleasePython `
  (Join-Path $CodexRoot "skills/.system/skill-creator/scripts/quick_validate.py") `
  "plugins/fab-library-advisor/skills/fab-library-advisor"

& $ReleasePython `
  (Join-Path $CodexRoot "skills/.system/plugin-creator/scripts/validate_plugin.py") `
  "plugins/fab-library-advisor"

& $ReleasePython -m unittest discover -s tests -v
git diff --check
```

Both official validators import `yaml`; `requirements-release.txt` pins that
dependency. When generating `agents/openai.yaml` from PowerShell, single-quote
every `--interface` value containing `$fab-library-advisor`. Otherwise
PowerShell expands `$fab` and silently corrupts the skill name. Confirm the
literal `$fab-library-advisor` remains in the generated diff.

Run commands that require sandbox escalation sequentially. Do not group multiple
approval-gated validators into one parallel tool call; simultaneous approval
requests can remain waiting even though each validator normally finishes in less
than a second.

## Publish through GitHub

Check `gh auth status` before repository writes. Prefer the connected GitHub app,
but if it returns `Resource not accessible by integration`, do not retry the same
connector write. Use the authenticated `gh` CLI for the remaining PR, merge, and
release operations.

After validation:

1. Bump the smallest appropriate semantic version and update README release
   links.
2. Create a release branch, stage only intended files, commit, and push.
3. Open a PR and merge it after required checks pass.
4. Update local `main` with `git pull --ff-only origin main`.

## Build and verify the ZIP

Build only from tracked files in the merged commit:

```powershell
New-Item -ItemType Directory -Force ".package-test"
git archive --format=zip --prefix=fab-library-advisor/ `
  -o .package-test/fab-library-advisor-X.Y.Z.zip `
  HEAD:plugins/fab-library-advisor
```

List and extract the archive, then:

- run plugin validation on the extracted directory;
- validate that `catalog_template.json` contains zero indexed and total products;
- reject `__pycache__`, `.pyc`, populated catalogs, credentials, tokens, account
  data, signed download URLs, and expiring CDN URLs;
- compute SHA-256 before publishing.

Publish a non-draft GitHub Release with the matching tag and ZIP. Download the
published asset again and require its SHA-256 to match the locally verified ZIP.

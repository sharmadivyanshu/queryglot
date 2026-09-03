# Publishing queryglot v0.1.0 to PyPI

Owner-driven runbook, same shape as quietfail's: one step at a time, verify
each output before the next. Total ~1–2h including the TestPyPI dry run.

Two decisions are baked into metadata and are permanent once uploaded — make
them before step 1:

- **Author email** (`pyproject.toml` line 5): PyPI metadata is public and
  cannot be rewritten for a released version. Decide whether the current
  work address stays or a personal one goes in.
- **Repository link**: adding `repository = "https://github.com/sharmadivyanshu/queryglot"`
  under `[tool.poetry]` puts a source link on the PyPI page — which 404s for
  everyone while the repo is private. Either flip the repo public as part of
  this release (the natural moment) or omit the link until then.

## 0. Pre-flight (all local, nothing leaves the machine)

```bash
cd ~/git/predator-labs/queryglot
git status                      # must be clean, on main, synced with origin
poetry run pytest -q            # 129 passed locally (12 live tests skip without QUERYGLOT_TEST_PROM)
poetry run ruff check . && poetry run ruff format --check .
poetry run mypy src/queryglot --ignore-missing-imports
cd frontend && npm test -- --run && npm run build:all && cd ..
```

`build:all` matters: it regenerates `src/queryglot/_static/` (playground +
widget) — the wheel ships whatever is in that directory, so a stale build
here means shipping a stale UI forever under this version number.

## 1. Metadata edits (the two decisions above)

Edit `pyproject.toml`; then verify Poetry still parses it:

```bash
poetry check
```

Commit the metadata change before building — the wheel should be
reproducible from a commit, not from a dirty tree.

## 2. Build and inspect the artifacts

```bash
poetry build
```

Expect `dist/queryglot-0.1.0.tar.gz` and `dist/queryglot-0.1.0-py3-none-any.whl`.
Then LOOK INSIDE before uploading anything:

```bash
unzip -l dist/queryglot-0.1.0-py3-none-any.whl | grep -c "_static"
unzip -l dist/queryglot-0.1.0-py3-none-any.whl | grep -E "widget.js|index.html"
tar -tzf dist/queryglot-0.1.0.tar.gz | grep -c "_static"
```

The `_static` count must be >0 in BOTH artifacts (the `include` stanza in
pyproject covers sdist and wheel; this verifies it). No `.env`, no
`finetune/adapters` weights, no `HANDOFF.md`/`PROJECT_CORE.md` should appear
in either listing:

```bash
tar -tzf dist/queryglot-0.1.0.tar.gz | grep -iE "handoff|project_core|\.env|adapters" || echo "clean"
```

## 3. Clean-room install test (catches packaging bugs PyPI can't undo)

```bash
python3 -m venv /tmp/qg-smoke && source /tmp/qg-smoke/bin/activate
pip install "dist/queryglot-0.1.0-py3-none-any.whl[serve]"
queryglot --help
queryglot-mcp --help
queryglot-serve --help
python -c "from queryglot._static import __path__" 2>/dev/null; ls "$(python -c 'import queryglot, pathlib; print(pathlib.Path(queryglot.__file__).parent / \"_static\"')")" | head
deactivate
```

The last command must list `index.html`, `widget.js`, `assets/` — proof the
UI actually installed from the wheel, not from your working tree.

## 4. TestPyPI dry run (teaches the full flow with zero blast radius)

Create a token at https://test.pypi.org/manage/account/token/ (separate
account/token from real PyPI), then:

```bash
poetry config repositories.testpypi https://test.pypi.org/legacy/
poetry config pypi-token.testpypi <the-test-token>
poetry publish -r testpypi
```

Verify on https://test.pypi.org/project/queryglot/ — check the rendered
README (Markdown rendering differences show up HERE, not on your editor),
the metadata, the file list. Then install from TestPyPI in another clean
venv (deps come from real PyPI, only queryglot from test):

```bash
python3 -m venv /tmp/qg-testpypi && source /tmp/qg-testpypi/bin/activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "queryglot[serve]"
queryglot --help && deactivate
```

## 5. The real upload (IRREVERSIBLE for this version number)

A published version can be yanked but never replaced — a broken 0.1.0 means
shipping 0.1.1. That's why steps 2–4 exist.

Token from https://pypi.org/manage/account/token/ (scope it to the project
after the first upload; first upload needs an account-scoped token):

```bash
poetry config pypi-token.pypi <the-real-token>
poetry publish
```

Verify: https://pypi.org/project/queryglot/ — README rendering, metadata,
both files present. Then one final clean-venv install from real PyPI
(same commands as step 4 without the index-url flags).

## 6. Tag, release, and the public-flip decision

```bash
git tag v0.1.0 && git push origin v0.1.0
```

If the repo goes public now: flip it in GitHub settings, then create the
GitHub release from the tag (`gh release create v0.1.0 --title "queryglot 0.1.0" --notes-file <notes>`)
— release notes can lift the Status section of the README. If it stays
private, tag only; the release waits.

## 7. Afterwards

- Update HANDOFF.md: publish milestone closed.
- `pip install queryglot` in a fresh venv one week later still working is
  the real definition of done.

# Contributing

Contributions are welcome under the Apache License 2.0. By submitting a pull request you agree that your
contribution is licensed under the same terms (Apache-2.0, section 5). Please add your name to `AUTHORS`.

Do not submit code copied from GPL projects (for example Bonsai) or third-party binaries.
Keep third-party libraries out of the repository (`vendor/` is git-ignored).

## Development layout

The repository is never loaded by Houdini. The Houdini package (`HIFC.json` in the packages folder) points at the
**installed** copy, by default `~/tools_houdini/HIFC`. Edit the repository, then install:

```bash
python3 deploy.py ~/tools_houdini/HIFC      # --dry-run to preview, --clean to drop files a previous install left
```

`deploy.py` copies only changed files and writes `INSTALL.json` (version, commit, date, file list) into the
installation; it never touches files it did not install, and it leaves `vendor/` alone.

If you changed the node interface or the help text, rebuild the assets **after** installing the new code, because
`build_all` reads the package Houdini has loaded — that is, the installed one:

1. `python3 deploy.py ~/tools_houdini/HIFC`
2. in Houdini: drop `hifc*` from `sys.modules`
3. `import hifc.hda_build as b; b.build_all(otls="<repo>/otls")` — assets are written into the repository
4. `python3 deploy.py ~/tools_houdini/HIFC` again, then `hou.hda.reloadFile(...)`

## Versions and dependencies

`python3.13libs/hifc/__init__.py` holds `__version__`, `HDA_VERSION` (the asset version, `hifc::*::<HDA_VERSION>`)
and `VENDOR` — the exact versions of the third-party modules HIFC is tested with. The same set is recorded in
`VERSIONS.json`, `vendor/README.md` and `THIRD_PARTY_NOTICES.md`; change them in one commit, after running the full
test suite against the new module version. Node type names are only ever built from these constants.

## Tests

```bash
python3 tests/test_repo.py                  # repository consistency, no Houdini needed
hython tests/test_core.py                   # reader/writer without Houdini nodes
hython tests/roundtrip.py                   # 35 buildingSMART certification files
hython tests/houdini_regression.py          # the HDAs in a Houdini session
```

Every fixed behaviour gets a test that fails without the fix. The README banner (`docs/HIFC.jpg`) stays right after
the title in both READMEs; `tests/test_repo.py` checks that.

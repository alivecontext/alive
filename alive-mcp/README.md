# alive-mcp

Read-only MCP server exposing the ALIVE Context System. v0.1 scaffold. Full README lands in T16 (`fn-10-60k.16`).

## `alive://` URI scheme

Kernel files are exposed as MCP resources under the `alive://` custom scheme:

```
alive://walnut/{walnut_path}/kernel/{file}
```

- `{walnut_path}` -- POSIX relative path from the World root. Forward slashes are preserved as literal separators; every other reserved character is percent-encoded (RFC 3986 path segment). Spaces -> `%20`. Unicode is NFC-normalized before encoding.
- `{file}` -- one of `key`, `log`, `insights`, `now` (no encoding).

Examples:

- `alive://walnut/02_Life/people/ben-flint/kernel/log`
- `alive://walnut/04_Ventures/supernormal-systems/clients/elite-oceania/kernel/key`

Codified in `src/alive_mcp/uri.py` (encoder + decoder + tests in `tests/test_uri.py`).

Resources duplicate the tool layer intentionally: resources serve HOST-controlled attach/subscribe workflows (Claude Desktop's "attach as context" UI), tools serve MODEL-controlled parameterized retrieval. Same data on disk, different control surface -- each primitive is authoritative for its own use case.

## Dev env

The monorepo's system Python is 3.14. alive-mcp pins to `>=3.10,<3.14` — contributors install a pinned interpreter:

```bash
cd claude-code/alive-mcp
uv python install 3.12
uv venv --python 3.12

uv run alive-mcp --version        # prints 0.1.0
uvx --from . alive-mcp --version  # same

# Tests run from a bare checkout -- tests/__init__.py adds src/ to sys.path
# so you don't need the package installed or PYTHONPATH set.
python3 -m unittest discover tests
# Or, if you've already set up the uv venv:
uv run python -m unittest discover tests
```

Full design: `.flow/specs/fn-10-60k.md` at the walnut root.

"""Unit tests for ``alive_mcp.errors`` and ``alive_mcp.envelope``.

Covers the T4 acceptance criteria:

1. All 9 error codes are defined with message templates and suggestions.
2. ``envelope.ok()`` and ``envelope.error()`` return the canonical
   ``CallToolResult``-shaped dict.
3. Error envelope shape matches the MCP spec fields (``content``,
   ``structuredContent``, ``isError``).
4. No message template in the codebook contains an absolute filesystem
   path — the mask IS the template.

Uses stdlib ``unittest``. No third-party deps — matches the
T2/T3 convention.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import unittest

# Ensure ``python3 -m unittest discover tests`` works from a clean
# checkout without requiring ``pip install -e .``. Mirrors the shim in
# ``test_paths.py`` / ``test_vendor_smoke.py``.
_SRC_DIR = str(pathlib.Path(__file__).resolve().parent.parent / "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from alive_mcp import envelope, errors  # noqa: E402


class ErrorCodebookTests(unittest.TestCase):
    """Acceptance: all 9 codes have templates and suggestions."""

    EXPECTED_CODES = (
        "ERR_NO_WORLD",
        "ERR_WALNUT_NOT_FOUND",
        "ERR_BUNDLE_NOT_FOUND",
        "ERR_KERNEL_FILE_MISSING",
        "ERR_PERMISSION_DENIED",
        "ERR_PATH_ESCAPE",
        "ERR_INVALID_CURSOR",
        "ERR_TOOL_TIMEOUT",
        "ERR_AUDIT_DISK_FULL",
    )

    def test_all_codes_exported_as_constants(self) -> None:
        """Every expected code is exposed as a module-level string constant."""
        for name in self.EXPECTED_CODES:
            self.assertEqual(
                getattr(errors, name),
                name,
                msg=f"{name} constant does not equal its string value",
            )

    def test_error_codes_tuple_matches_expected_set(self) -> None:
        """``ERROR_CODES`` is the authoritative frozen set of v0.1 codes."""
        self.assertEqual(
            set(errors.ERROR_CODES),
            set(self.EXPECTED_CODES),
            msg="ERROR_CODES drift — spec freezes exactly 9 codes for v0.1",
        )

    def test_every_code_has_message_template(self) -> None:
        """MESSAGES maps each code to a non-empty template string."""
        for code in self.EXPECTED_CODES:
            self.assertIn(code, errors.MESSAGES)
            self.assertIsInstance(errors.MESSAGES[code], str)
            self.assertGreater(len(errors.MESSAGES[code]), 10)

    def test_every_code_has_suggestions(self) -> None:
        """SUGGESTIONS maps each code to a non-empty tuple of strings."""
        for code in self.EXPECTED_CODES:
            self.assertIn(code, errors.SUGGESTIONS)
            suggestions = errors.SUGGESTIONS[code]
            self.assertIsInstance(suggestions, tuple)
            self.assertGreaterEqual(
                len(suggestions),
                1,
                msg=f"{code} has no suggestions — LLM cannot self-recover",
            )
            for hint in suggestions:
                self.assertIsInstance(hint, str)
                self.assertGreater(len(hint), 0)


class NoAbsolutePathsInMessagesTests(unittest.TestCase):
    """Acceptance: templates never leak absolute filesystem paths.

    The ``mask_error_details=True`` FastMCP promise is that user-facing
    messages do not leak server-internal paths. This test asserts the
    promise at the template level — the templates themselves contain
    zero absolute-path literals.
    """

    # POSIX absolute paths (``/etc``, ``/Users/foo``) and Windows drive
    # paths (``C:\``, ``D:/``). The ``{placeholders}`` that carry
    # caller-facing identifiers (walnut, bundle, file, query, tool) are
    # not absolute paths.
    POSIX_ABS = re.compile(r"(?:^|[\s'\"`(])/[A-Za-z]")
    WINDOWS_ABS = re.compile(r"[A-Za-z]:[\\/]")

    def test_no_posix_absolute_path_in_any_message(self) -> None:
        for code, template in errors.MESSAGES.items():
            match = self.POSIX_ABS.search(template)
            self.assertIsNone(
                match,
                msg=(
                    f"Message template for {code} contains a POSIX-shaped "
                    f"absolute path: {template!r} (match={match.group() if match else None})"
                ),
            )

    def test_no_windows_absolute_path_in_any_message(self) -> None:
        for code, template in errors.MESSAGES.items():
            self.assertIsNone(
                self.WINDOWS_ABS.search(template),
                msg=f"Message template for {code} contains a Windows drive path: {template!r}",
            )

    def test_no_windows_absolute_path_in_any_suggestion(self) -> None:
        for code, suggestions in errors.SUGGESTIONS.items():
            for hint in suggestions:
                self.assertIsNone(
                    self.WINDOWS_ABS.search(hint),
                    msg=f"Suggestion for {code} contains a Windows drive path: {hint!r}",
                )


class ExceptionToCodeMappingTests(unittest.TestCase):
    """Each code-emitting seam has a matching ``AliveMcpError`` subclass."""

    def test_path_escape_exception_carries_code(self) -> None:
        exc = errors.PathEscapeError("candidate escaped")
        self.assertEqual(exc.code, errors.ERR_PATH_ESCAPE)
        self.assertIsInstance(exc, errors.AliveMcpError)

    def test_walnut_not_found_exception_carries_code(self) -> None:
        exc = errors.WalnutNotFoundError("no such walnut")
        self.assertEqual(exc.code, errors.ERR_WALNUT_NOT_FOUND)

    def test_bundle_not_found_exception_carries_code(self) -> None:
        exc = errors.BundleNotFoundError("no such bundle")
        self.assertEqual(exc.code, errors.ERR_BUNDLE_NOT_FOUND)

    def test_kernel_file_missing_exception_carries_code(self) -> None:
        exc = errors.KernelFileMissingError("log.md missing")
        self.assertEqual(exc.code, errors.ERR_KERNEL_FILE_MISSING)

    def test_permission_denied_exception_carries_code(self) -> None:
        exc = errors.PermissionDeniedError("EACCES")
        self.assertEqual(exc.code, errors.ERR_PERMISSION_DENIED)

    def test_invalid_cursor_exception_carries_code(self) -> None:
        exc = errors.InvalidCursorError("bad token")
        self.assertEqual(exc.code, errors.ERR_INVALID_CURSOR)

    def test_tool_timeout_exception_carries_code(self) -> None:
        exc = errors.ToolTimeoutError("exceeded")
        self.assertEqual(exc.code, errors.ERR_TOOL_TIMEOUT)

    def test_audit_disk_full_exception_carries_code(self) -> None:
        exc = errors.AuditDiskFullError("ENOSPC")
        self.assertEqual(exc.code, errors.ERR_AUDIT_DISK_FULL)

    def test_kernel_file_error_reexported_from_vendor(self) -> None:
        """``KernelFileError`` comes from ``_vendor._pure`` — present on errors."""
        self.assertTrue(hasattr(errors, "KernelFileError"))
        self.assertTrue(issubclass(errors.KernelFileError, Exception))

    def test_world_not_found_error_reexported_from_vendor(self) -> None:
        self.assertTrue(hasattr(errors, "WorldNotFoundError"))
        self.assertTrue(issubclass(errors.WorldNotFoundError, Exception))

    def test_malformed_yaml_warning_reexported_from_vendor(self) -> None:
        self.assertTrue(hasattr(errors, "MalformedYAMLWarning"))
        self.assertTrue(issubclass(errors.MalformedYAMLWarning, Warning))


class EnvelopeOkShapeTests(unittest.TestCase):
    """Acceptance: ``envelope.ok`` returns the MCP ``CallToolResult`` shape."""

    def test_ok_with_dict_payload(self) -> None:
        resp = envelope.ok({"walnuts": ["a", "b"], "count": 2})
        self.assertEqual(set(resp.keys()), {"content", "structuredContent", "isError"})
        self.assertFalse(resp["isError"])
        self.assertEqual(resp["structuredContent"], {"walnuts": ["a", "b"], "count": 2})
        # content[0] is a TextContent-shaped block.
        self.assertIsInstance(resp["content"], list)
        self.assertEqual(len(resp["content"]), 1)
        self.assertEqual(resp["content"][0]["type"], "text")
        # content text parses back to the structured payload.
        parsed = json.loads(resp["content"][0]["text"])
        self.assertEqual(parsed, {"walnuts": ["a", "b"], "count": 2})

    def test_ok_merges_meta_into_structured_content(self) -> None:
        resp = envelope.ok({"matches": [1, 2]}, next_cursor="abc123", total=17)
        self.assertEqual(
            resp["structuredContent"],
            {"matches": [1, 2], "next_cursor": "abc123", "total": 17},
        )
        self.assertFalse(resp["isError"])

    def test_ok_wraps_list_payload_under_data_key(self) -> None:
        """Non-dict payloads go under ``data`` so structuredContent stays an object."""
        resp = envelope.ok([{"id": 1}, {"id": 2}])
        self.assertEqual(resp["structuredContent"], {"data": [{"id": 1}, {"id": 2}]})

    def test_ok_wraps_scalar_payload_under_data_key(self) -> None:
        resp = envelope.ok("ok")
        self.assertEqual(resp["structuredContent"], {"data": "ok"})

    def test_ok_raises_on_meta_key_collision(self) -> None:
        """Silent shadowing is a bug, not a feature — collision raises."""
        with self.assertRaises(ValueError):
            envelope.ok({"total": 5}, total=10)

    def test_ok_renders_unicode_without_escape(self) -> None:
        """``ensure_ascii=False`` lets bundle/walnut names with unicode pass through."""
        resp = envelope.ok({"name": "北極星"})
        self.assertIn("北極星", resp["content"][0]["text"])


class EnvelopeErrorShapeTests(unittest.TestCase):
    """Acceptance: ``envelope.error`` returns a well-shaped error envelope."""

    def test_error_shape_is_call_tool_result(self) -> None:
        resp = envelope.error(errors.ERR_WALNUT_NOT_FOUND, walnut="nova-station")
        self.assertEqual(set(resp.keys()), {"content", "structuredContent", "isError"})
        self.assertTrue(resp["isError"])

    def test_error_code_strips_err_prefix(self) -> None:
        """Surface ``error`` field drops ``ERR_`` per Merge/Workato convention."""
        resp = envelope.error(errors.ERR_WALNUT_NOT_FOUND, walnut="nova-station")
        self.assertEqual(resp["structuredContent"]["error"], "WALNUT_NOT_FOUND")

    def test_error_message_formats_placeholders(self) -> None:
        resp = envelope.error(errors.ERR_WALNUT_NOT_FOUND, walnut="nova-station")
        self.assertIn("nova-station", resp["structuredContent"]["message"])

    def test_error_includes_suggestions_list(self) -> None:
        resp = envelope.error(errors.ERR_WALNUT_NOT_FOUND, walnut="nova-station")
        self.assertIsInstance(resp["structuredContent"]["suggestions"], list)
        self.assertGreater(len(resp["structuredContent"]["suggestions"]), 0)

    def test_error_content_text_parses_as_structured_content(self) -> None:
        resp = envelope.error(errors.ERR_BUNDLE_NOT_FOUND, walnut="nova-station", bundle="shielding-review")
        parsed = json.loads(resp["content"][0]["text"])
        self.assertEqual(parsed, resp["structuredContent"])

    def test_error_missing_template_placeholder_degrades_gracefully(self) -> None:
        """Missing kwarg for a referenced placeholder must not crash."""
        # ERR_TOOL_TIMEOUT expects ``{tool}`` and ``{timeout_s}`` —
        # supply neither and confirm we get a well-formed envelope.
        resp = envelope.error(errors.ERR_TOOL_TIMEOUT)
        self.assertTrue(resp["isError"])
        self.assertIn("template missing placeholder", resp["structuredContent"]["message"])

    def test_error_unknown_code_returns_unknown_envelope(self) -> None:
        """Unknown codes degrade to a well-formed ``UNKNOWN`` envelope."""
        resp = envelope.error("ERR_BOGUS_NEVER_DEFINED")
        self.assertTrue(resp["isError"])
        # Strips the ``ERR_`` prefix even for unknown codes.
        self.assertEqual(resp["structuredContent"]["error"], "BOGUS_NEVER_DEFINED")

    def test_error_envelopes_render_for_every_frozen_code(self) -> None:
        """Every frozen code produces a well-formed envelope.

        Builds the minimal kwarg set each template needs — if a template
        is added later that references a new placeholder, either this
        test or the missing-placeholder fallback catches it.
        """
        kwarg_matrix = {
            errors.ERR_NO_WORLD: {},
            errors.ERR_WALNUT_NOT_FOUND: {"walnut": "nova-station"},
            errors.ERR_BUNDLE_NOT_FOUND: {"walnut": "nova-station", "bundle": "shielding-review"},
            errors.ERR_KERNEL_FILE_MISSING: {"walnut": "nova-station", "file": "log"},
            errors.ERR_PERMISSION_DENIED: {"walnut": "nova-station", "file": "log"},
            errors.ERR_PATH_ESCAPE: {},
            errors.ERR_INVALID_CURSOR: {},
            errors.ERR_TOOL_TIMEOUT: {"tool": "search_world", "timeout_s": 5.0},
            errors.ERR_AUDIT_DISK_FULL: {},
        }
        for code, kwargs in kwarg_matrix.items():
            resp = envelope.error(code, **kwargs)
            self.assertTrue(resp["isError"], msg=f"{code} envelope isError not True")
            sc = resp["structuredContent"]
            self.assertEqual(sc["error"], code.removeprefix("ERR_"), msg=code)
            self.assertGreater(len(sc["message"]), 0, msg=code)
            self.assertIsInstance(sc["suggestions"], list, msg=code)
            self.assertNotIn("{", sc["message"], msg=f"{code} has unfilled placeholder")


class EnvelopeErrorFromExceptionTests(unittest.TestCase):
    """``error_from_exception`` bridges ``AliveMcpError`` to envelope."""

    def test_walnut_not_found_exception_maps_to_envelope(self) -> None:
        try:
            raise errors.WalnutNotFoundError("nova-station")
        except errors.AliveMcpError as exc:
            resp = envelope.error_from_exception(exc, walnut="nova-station")
        self.assertTrue(resp["isError"])
        self.assertEqual(resp["structuredContent"]["error"], "WALNUT_NOT_FOUND")
        self.assertIn("nova-station", resp["structuredContent"]["message"])

    def test_path_escape_exception_maps_to_envelope(self) -> None:
        try:
            raise errors.PathEscapeError("candidate escaped root")
        except errors.AliveMcpError as exc:
            resp = envelope.error_from_exception(exc)
        self.assertTrue(resp["isError"])
        self.assertEqual(resp["structuredContent"]["error"], "PATH_ESCAPE")
        # PATH_ESCAPE message is generic — no placeholders, so the
        # template wins and the exception string is discarded (mask
        # promise upheld).
        self.assertNotIn("candidate escaped root", resp["structuredContent"]["message"])

    def test_unknown_code_exception_falls_back_to_exception_message(self) -> None:
        class BogusError(errors.AliveMcpError):
            code = "ERR_NEVER_DEFINED"

        try:
            raise BogusError("fallback message")
        except errors.AliveMcpError as exc:
            resp = envelope.error_from_exception(exc)
        self.assertTrue(resp["isError"])
        self.assertEqual(resp["structuredContent"]["error"], "NEVER_DEFINED")
        # No template, so the exception string IS the message.
        self.assertEqual(resp["structuredContent"]["message"], "fallback message")


class EnvelopeSerializableTests(unittest.TestCase):
    """Envelopes are JSON-round-trippable — they go over stdio as JSON-RPC."""

    def test_ok_envelope_round_trips_through_json(self) -> None:
        resp = envelope.ok({"walnuts": [{"name": "a"}, {"name": "b"}]}, next_cursor="x")
        serialized = json.dumps(resp)
        parsed = json.loads(serialized)
        self.assertEqual(parsed, resp)

    def test_error_envelope_round_trips_through_json(self) -> None:
        resp = envelope.error(errors.ERR_BUNDLE_NOT_FOUND, walnut="w", bundle="b")
        serialized = json.dumps(resp)
        parsed = json.loads(serialized)
        self.assertEqual(parsed, resp)


if __name__ == "__main__":
    unittest.main()

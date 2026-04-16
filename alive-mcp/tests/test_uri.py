"""Unit tests for the ``alive://`` URI codec (fn-10-60k.10 / T10).

Locks the encoder/decoder contract so resource URIs stay stable as T11,
T13, and downstream clients ship. Every acceptance criterion in the task
spec maps to at least one test here; the CONTRACT tests near the top
enforce the frozen properties of the scheme (round-trip, unicode
handling, error surface) independent of implementation detail.
"""
from __future__ import annotations

import unicodedata
import unittest

# Make ``src/`` importable the same way tests/__init__.py does.
import tests  # noqa: F401

from alive_mcp.uri import (  # noqa: E402
    AUTHORITY,
    KERNEL_FILES,
    SCHEME,
    InvalidURIError,
    decode_kernel_uri,
    encode_kernel_uri,
)


# ---------------------------------------------------------------------------
# Contract: the frozen scheme properties.
# ---------------------------------------------------------------------------


class SchemeConstants(unittest.TestCase):
    """The three frozen constants MUST NOT change without a scheme revision.

    Clients hard-code ``alive://walnut/...`` in their config snippets
    (T16); a silent rename would break every existing deployment.
    """

    def test_scheme_is_alive(self) -> None:
        self.assertEqual(SCHEME, "alive")

    def test_authority_is_walnut(self) -> None:
        self.assertEqual(AUTHORITY, "walnut")

    def test_kernel_files_are_exactly_four(self) -> None:
        # The four-file literal set is shared with the tool layer
        # (:data:`walnut.KernelFile`) and the bundle-resource plan
        # for v0.2. Lock the set here so adding a fifth file (or
        # dropping one) is a deliberate decision that fails this
        # test first.
        self.assertEqual(KERNEL_FILES, frozenset({"key", "log", "insights", "now"}))


# ---------------------------------------------------------------------------
# Encoder tests.
# ---------------------------------------------------------------------------


class EncoderHappyPath(unittest.TestCase):
    """The encoder produces the exact strings downstream tasks expect."""

    def test_simple_path_encodes_verbatim(self) -> None:
        uri = encode_kernel_uri("04_Ventures/alive", "log")
        self.assertEqual(uri, "alive://walnut/04_Ventures/alive/kernel/log")

    def test_epic_spec_examples_round_trip(self) -> None:
        # From fn-10-60k.10 task brief -- these exact strings are the
        # contract for the scheme.
        self.assertEqual(
            encode_kernel_uri("02_Life/people/ben-flint", "log"),
            "alive://walnut/02_Life/people/ben-flint/kernel/log",
        )
        self.assertEqual(
            encode_kernel_uri(
                "04_Ventures/supernormal-systems/clients/elite-oceania", "key"
            ),
            "alive://walnut/04_Ventures/supernormal-systems/clients/"
            "elite-oceania/kernel/key",
        )

    def test_forward_slashes_in_walnut_path_preserved(self) -> None:
        """A multi-segment walnut_path emits literal ``/`` separators.

        The FastMCP template matcher cannot capture ``/`` inside a
        ``{param}``; preserving them here means the matcher never
        gets the chance to reject a legitimate path.
        """
        uri = encode_kernel_uri("a/b/c/d", "key")
        self.assertEqual(uri, "alive://walnut/a/b/c/d/kernel/key")
        # Slash tally:
        #   ``://``             -> 2
        #   authority -> walnut -> 1
        #   walnut segments a/b/c/d -> 3
        #   walnut -> kernel    -> 1
        #   kernel -> file      -> 1
        # Total: 8 forward slashes.
        self.assertEqual(uri.count("/"), 8)
        # And none are percent-encoded.
        self.assertNotIn("%2F", uri)
        self.assertNotIn("%2f", uri)

    def test_space_in_walnut_path_is_percent_encoded(self) -> None:
        uri = encode_kernel_uri("People/ryn okata", "insights")
        self.assertEqual(uri, "alive://walnut/People/ryn%20okata/kernel/insights")

    def test_unicode_is_nfc_normalized_then_percent_encoded(self) -> None:
        """NFC form drives the byte sequence that gets percent-encoded.

        ``\u00e9`` (NFC) and ``e\u0301`` (NFD) are visually identical
        but differ in bytes. After NFC normalization both collapse to
        the same byte sequence (``\u00e9`` -> ``%C3%A9`` in UTF-8).
        """
        nfc_input = "04_Ventures/h\u00e9l\u00e8ne"
        nfd_input = unicodedata.normalize("NFD", nfc_input)
        self.assertNotEqual(nfc_input, nfd_input)  # precondition: they differ
        self.assertEqual(
            encode_kernel_uri(nfc_input, "now"),
            encode_kernel_uri(nfd_input, "now"),
        )
        # And the concrete output: ``é`` -> ``%C3%A9``, ``è`` -> ``%C3%A8``.
        self.assertEqual(
            encode_kernel_uri(nfc_input, "now"),
            "alive://walnut/04_Ventures/h%C3%A9l%C3%A8ne/kernel/now",
        )

    def test_reserved_characters_encoded(self) -> None:
        """Reserved URI characters (``?``, ``#``, ``&``) must be escaped.

        If a walnut name happens to contain ``?`` or ``#``, passing it
        through unquoted would be interpreted as the start of the
        URI query / fragment. The encoder must escape these.
        """
        uri = encode_kernel_uri("experiments/what?", "log")
        self.assertIn("%3F", uri)
        self.assertNotIn("?", uri)

    def test_percent_sign_round_trips(self) -> None:
        """Literal ``%`` in the walnut name encodes as ``%25``.

        Guards against double-encoding on round-trip -- a second
        encode of the already-encoded output would add another layer
        of escapes.
        """
        uri = encode_kernel_uri("weird/50% off", "now")
        self.assertIn("50%25", uri)
        # Decoder reverses the encoding exactly.
        walnut_path, file = decode_kernel_uri(uri)
        self.assertEqual(walnut_path, "weird/50% off")
        self.assertEqual(file, "now")


class EncoderRejectsMalformedInputs(unittest.TestCase):
    """The encoder enforces the canonical walnut-path shape."""

    def test_empty_walnut_path(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("", "log")

    def test_leading_slash_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("/absolute/path", "log")

    def test_trailing_slash_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures/alive/", "log")

    def test_double_slash_is_an_empty_segment(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures//alive", "log")

    def test_dot_segment_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures/./alive", "log")

    def test_dotdot_segment_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures/../../etc", "log")

    def test_unknown_file_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures/alive", "tasks")

    def test_empty_file_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            encode_kernel_uri("04_Ventures/alive", "")


# ---------------------------------------------------------------------------
# Decoder tests.
# ---------------------------------------------------------------------------


class DecoderHappyPath(unittest.TestCase):
    """Every shape the encoder emits must round-trip through the decoder."""

    def test_simple_round_trip(self) -> None:
        for walnut_path in (
            "04_Ventures/alive",
            "02_Life/people/ben-flint",
            "04_Ventures/supernormal-systems/clients/elite-oceania",
            "People/ryn-okata",
            "05_Experiments/lock-in-lab",
        ):
            for file in sorted(KERNEL_FILES):
                with self.subTest(walnut_path=walnut_path, file=file):
                    uri = encode_kernel_uri(walnut_path, file)
                    decoded_path, decoded_file = decode_kernel_uri(uri)
                    self.assertEqual(decoded_path, walnut_path)
                    self.assertEqual(decoded_file, file)

    def test_space_round_trip(self) -> None:
        uri = encode_kernel_uri("People/ryn okata", "insights")
        walnut_path, file = decode_kernel_uri(uri)
        self.assertEqual(walnut_path, "People/ryn okata")
        self.assertEqual(file, "insights")

    def test_unicode_round_trip(self) -> None:
        walnut_path = "04_Ventures/h\u00e9l\u00e8ne"
        uri = encode_kernel_uri(walnut_path, "now")
        decoded_path, decoded_file = decode_kernel_uri(uri)
        self.assertEqual(decoded_path, walnut_path)  # NFC form preserved
        self.assertEqual(decoded_file, "now")

    def test_decoder_normalizes_nfd_input(self) -> None:
        """A client-supplied NFD-encoded URI decodes to the NFC walnut_path.

        Some clients on macOS will percent-encode NFD bytes (from the
        filesystem) and send those. The decoder normalizes to NFC so
        our path-safety layer sees the same walnut_path whether the
        URI arrived in NFC or NFD form.
        """
        nfc = "04_Ventures/h\u00e9l\u00e8ne"
        nfd = unicodedata.normalize("NFD", nfc)
        # Build the NFD URI by hand -- ``encode`` always NFC-normalizes.
        nfd_uri = "alive://walnut/" + "/".join(
            __import__("urllib.parse").parse.quote(s, safe="") for s in nfd.split("/")
        ) + "/kernel/now"
        decoded_path, decoded_file = decode_kernel_uri(nfd_uri)
        self.assertEqual(decoded_path, nfc)
        self.assertEqual(decoded_file, "now")

    def test_scheme_case_insensitive(self) -> None:
        """RFC 3986 says scheme is case-insensitive; accept upper-case on input."""
        walnut_path, file = decode_kernel_uri(
            "ALIVE://walnut/04_Ventures/alive/kernel/log"
        )
        self.assertEqual(walnut_path, "04_Ventures/alive")
        self.assertEqual(file, "log")


class DecoderRejectsMalformedURIs(unittest.TestCase):
    """Every malformed URI must raise :class:`InvalidURIError`."""

    def test_empty_string(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("")

    def test_non_string_input(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(None)  # type: ignore[arg-type]

    def test_wrong_scheme(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("file:///etc/passwd")
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("http://walnut/04_Ventures/alive/kernel/log")

    def test_wrong_authority(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("alive://bundle/04_Ventures/alive/kernel/log")

    def test_missing_kernel_literal(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("alive://walnut/04_Ventures/alive/notkernel/log")

    def test_unknown_file(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("alive://walnut/04_Ventures/alive/kernel/tasks")

    def test_missing_walnut_path(self) -> None:
        with self.assertRaises(InvalidURIError):
            # Two segments only -- no walnut path before ``kernel``.
            decode_kernel_uri("alive://walnut/kernel/log")

    def test_double_slash_empty_segment(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(
                "alive://walnut/04_Ventures//alive/kernel/log"
            )

    def test_dot_segment_rejected_after_decoding(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("alive://walnut/04_Ventures/./alive/kernel/log")

    def test_dotdot_segment_rejected_after_decoding(self) -> None:
        """Rejects ``..`` whether literal or percent-encoded as ``%2E%2E``."""
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri("alive://walnut/04_Ventures/../etc/kernel/log")
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(
                "alive://walnut/04_Ventures/%2E%2E/etc/kernel/log"
            )

    def test_encoded_slash_rejected(self) -> None:
        """A ``%2F`` inside a walnut segment decodes to ``/`` and would
        sneak a directory separator through the boundary -- rejected.
        """
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(
                "alive://walnut/04_Ventures%2Falive/kernel/log"
            )

    def test_query_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(
                "alive://walnut/04_Ventures/alive/kernel/log?foo=bar"
            )

    def test_fragment_rejected(self) -> None:
        with self.assertRaises(InvalidURIError):
            decode_kernel_uri(
                "alive://walnut/04_Ventures/alive/kernel/log#frag"
            )


# ---------------------------------------------------------------------------
# Cross-checks: every legal walnut path shape produces a unique URI.
# ---------------------------------------------------------------------------


class UniquenessInvariants(unittest.TestCase):
    """Distinct walnut paths must map to distinct URIs, and vice versa."""

    def test_distinct_paths_produce_distinct_uris(self) -> None:
        paths = [
            "04_Ventures/alive",
            "04_Ventures/aliveness",
            "04_Ventures/alive/sub",
            "02_Life/people/alive",
        ]
        uris = {encode_kernel_uri(p, "log") for p in paths}
        self.assertEqual(len(uris), len(paths))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

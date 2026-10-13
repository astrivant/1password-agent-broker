"""
Exercise immutable PyPI file identity and the distinction between absence and failure.
"""

from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.release.check_pypi import read_release, release_files, verify_files


class PublicationTests(unittest.TestCase):
    """
    Keep partial retries safe without accepting changed, yanked or unexpected files.
    """

    def test_partial_and_complete_publication(self) -> None:
        """
        Permit absent files only before upload and accept identical complete retries.

        Returns:
            None: The publication phase contract holds.
        """
        expected = {"package.whl": "a" * 64, "package.tar.gz": "b" * 64}
        verify_files(expected, {}, allow_missing=True)
        verify_files(expected, {"package.whl": "a" * 64}, allow_missing=True)
        verify_files(expected, expected, allow_missing=False)
        with self.assertRaises(ValueError):
            verify_files(expected, {"package.whl": "a" * 64}, allow_missing=False)

    def test_mismatch_and_extra_file_fail_before_upload(self) -> None:
        """
        Reject different bytes and extra filenames even during a partial retry.

        Returns:
            None: Neither unsafe existing release is accepted.
        """
        expected = {"package.whl": "a" * 64}
        for published in ({"package.whl": "b" * 64}, {"other.whl": "a" * 64}):
            with self.subTest(published=published), self.assertRaises(ValueError):
                verify_files(expected, published, allow_missing=True)

    def test_metadata_validation(self) -> None:
        """
        Require explicit non-yanked files, unique names and valid SHA-256 values.

        Returns:
            None: Valid metadata survives and ambiguous metadata fails.
        """
        item = {"filename": "package.whl", "digests": {"sha256": "a" * 64}, "yanked": False}
        self.assertEqual(release_files({"urls": [item]}), {"package.whl": "a" * 64})
        for payload in (
            {},
            {"urls": "invalid"},
            {"urls": [None]},
            {"urls": [item, item]},
            {"urls": [{**item, "yanked": True}]},
            {"urls": [{**item, "yanked": None}]},
            {"urls": [{**item, "digests": {"sha256": "invalid"}}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                release_files(payload)

    def test_only_404_is_absence(self) -> None:
        """
        Keep rate limits, authorization failures and server errors visible.

        Returns:
            None: Only an authoritative missing-version response becomes empty.
        """
        for code in (404, 403, 429, 500):
            error = HTTPError("https://pypi.org/", code, "synthetic", Message(), None)
            with self.subTest(code=code), patch("scripts.release.check_pypi.urlopen", side_effect=error):
                if code == 404:
                    self.assertEqual(read_release("0.1.0"), {})
                else:
                    with self.assertRaises(HTTPError):
                        read_release("0.1.0")

    def test_live_response_boundary(self) -> None:
        """
        Feed registry bytes through the production parser without contacting PyPI.

        Returns:
            None: The exact version endpoint and bounded request are used.
        """
        payload = {"urls": [{"filename": "package.whl", "digests": {"sha256": "a" * 64}, "yanked": False}]}
        with patch("scripts.release.check_pypi.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            self.assertEqual(read_release("0.1.0"), {"package.whl": "a" * 64})
            request.assert_called_once_with("https://pypi.org/pypi/1password-agent-broker/0.1.0/json", timeout=20)

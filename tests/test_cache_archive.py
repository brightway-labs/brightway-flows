"""Handing the caches to another machine, without handing over anything else.

The first run of this pipeline is hours of rate-limited requests, so the caches
are worth moving between machines rather than refetching. That makes an archive
arriving from somewhere else a thing the pipeline writes to disk, and these are
the checks that stop it writing the wrong thing:

- **Only known names are unpacked.** A tar member can be called
  `../../.ssh/config`, and `settings.json` holds the Common Chemistry API key.
  Neither is in `CACHED_FILES`, so neither is written -- checked by unpacking
  an archive that contains both.
- **Only known names are packed.** The licensed source lists and the build
  outputs share the data directory with the caches, and an archive made to be
  uploaded must not carry them.
- **A local cache is not silently replaced.** The receiving machine may hold
  lookups the archive predates.

The archive also arrives from an untrusted place *as a file*, which is a
separate class of defect from the names inside it: a manifest that is valid
JSON but the wrong shape used to raise out of the first member and abort the
whole unpack, and a cache stored as a symlink used to pack as an empty member
that every receiver silently skipped. Both are pinned below.
"""

import io
import os
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.cache_archive import (
    CACHE_URL_ENV_VAR,
    CACHED_FILES,
    MANIFEST_MAX_BYTES,
    MANIFEST_MEMBER_NAME,
    cache_url,
    cached_file_names,
    fetch_cache,
    pack_cache,
    present_cache_files,
    unpack_cache,
)


def _write_caches(data_dir: Path, names: list[str]) -> None:
    for name in names:
        (data_dir / name).write_bytes(f"contents of {name}".encode())


def _archive(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return path


class RegistryTestCase(unittest.TestCase):
    def test_every_member_name_is_a_bare_filename(self):
        """The whole safety argument for unpacking rests on this.

        A member is accepted because its name is in the registry, and joined
        onto the data directory unmodified. That is only safe while no name in
        the registry can leave the directory it is joined onto.
        """
        for name in sorted(cached_file_names()):
            with self.subTest(name=name):
                self.assertEqual(Path(name).name, name)
                self.assertNotIn("..", name)
                self.assertFalse(Path(name).is_absolute())

    def test_the_settings_file_is_not_in_the_archive(self):
        """It holds the Common Chemistry API key, and archives are shared."""
        from brightway_flows.filesystem import APP_SETTINGS_FILEPATH

        self.assertNotIn(APP_SETTINGS_FILEPATH.name, cached_file_names())

    def test_licensed_and_derived_files_are_not_in_the_archive(self):
        """ecoinvent and BAFU arrive under terms this tool does not get to set,
        and the build outputs are what a run produces rather than what it
        fetches -- an archive carrying them would make a machine that has never
        built one look like it had.
        """
        from brightway_flows.filesystem import (
            CONSENSUS_DB_FILEPATH,
            HARMONISED_FLOWS_SIMPLE_FILEPATH,
            OPSIN_LOG_FILEPATH,
            RDKIT_LOG_FILEPATH,
            bafu_ecospold_zip_path,
        )

        names = cached_file_names()
        for path in (
            CONSENSUS_DB_FILEPATH,
            HARMONISED_FLOWS_SIMPLE_FILEPATH,
            OPSIN_LOG_FILEPATH,
            RDKIT_LOG_FILEPATH,
            bafu_ecospold_zip_path("2026-v1"),
        ):
            with self.subTest(name=path.name):
                self.assertNotIn(path.name, names)
        for name in names:
            with self.subTest(name=name):
                self.assertNotIn("ecoinvent", name)

    def test_the_ef_vendor_archive_is_not_in_it_either(self):
        """200 MB -- three quarters of the archive -- for one public GET.

        `download` makes that request from a URL the code already holds, so the
        archive would be carrying the one thing on this list that is not slow to
        re-fetch.
        """
        from brightway_flows.filesystem import EF31_ZIP_FILEPATH
        from brightway_flows.integrations.ef31 import EF31_URL

        self.assertNotIn(EF31_ZIP_FILEPATH.name, cached_file_names())
        self.assertTrue(EF31_URL.startswith("https://"))

    def test_every_entry_says_where_it_came_from(self):
        for entry in CACHED_FILES:
            with self.subTest(name=entry.name):
                self.assertTrue(entry.origin.strip())


class RoundTripTestCase(unittest.TestCase):
    def test_pack_then_unpack_reproduces_the_caches(self):
        packed = sorted(cached_file_names())[:3]
        with TemporaryDirectory() as source, TemporaryDirectory() as target:
            source_dir, target_dir = Path(source), Path(target)
            _write_caches(source_dir, packed)
            # Not a cache: it shares the directory and must not travel.
            (source_dir / "settings.json").write_text(
                '{"commonchemistry_api_key": "s3cret"}'
            )

            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)
            result = unpack_cache(archive, data_dir=target_dir)

            self.assertEqual(sorted(result.written), packed)
            self.assertEqual(result.kept, [])
            self.assertEqual(result.ignored, [])
            for name in packed:
                self.assertEqual(
                    (target_dir / name).read_bytes(), (source_dir / name).read_bytes()
                )
            self.assertFalse((target_dir / "settings.json").exists())
            self.assertFalse((target_dir / MANIFEST_MEMBER_NAME).exists())

    def test_packing_a_directory_writes_the_default_name(self):
        with TemporaryDirectory() as source, TemporaryDirectory() as out:
            source_dir = Path(source)
            _write_caches(source_dir, [sorted(cached_file_names())[0]])
            archive = pack_cache(Path(out), data_dir=source_dir)
            self.assertEqual(archive.parent, Path(out))
            self.assertTrue(tarfile.is_tarfile(archive))

    def test_absent_caches_are_skipped_rather_than_failing(self):
        """Nobody has every cache: a machine that never merged a
        SimaPro-derived list has no GLAD workbook.
        """
        name = sorted(cached_file_names())[0]
        with TemporaryDirectory() as source:
            source_dir = Path(source)
            _write_caches(source_dir, [name])
            self.assertEqual(
                [entry.name for entry in present_cache_files(source_dir)], [name]
            )
            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)
            with tarfile.open(archive) as tar:
                members = set(tar.getnames())
            self.assertEqual(members, {MANIFEST_MEMBER_NAME, name})

    def test_packing_nothing_says_so(self):
        with TemporaryDirectory() as source:
            with self.assertRaises(FileNotFoundError):
                pack_cache(Path(source) / "archive.tar.gz", data_dir=Path(source))

    def test_no_half_written_archive_is_left_behind(self):
        """A truncated archive is indistinguishable from a good one until it is
        unpacked, so the name only appears once the bytes are all there.
        """
        with TemporaryDirectory() as source:
            source_dir = Path(source)
            _write_caches(source_dir, [sorted(cached_file_names())[0]])
            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)
            self.assertFalse(archive.with_name(archive.name + ".part").exists())

    def test_a_cache_stored_as_a_symlink_is_packed_whole(self):
        """A 50 MB dump moved to a bigger disk is still a cache.

        `tar.add` stores a symlink as a member of size 0, which every receiver
        skips as not-a-file -- while the packer logs the size it stat()ed
        through the link and reports success. Nobody would find out until a
        downloader re-fetched ChEBI for no visible reason.
        """
        name = sorted(cached_file_names())[0]
        with TemporaryDirectory() as source, TemporaryDirectory() as target:
            source_dir, target_dir = Path(source), Path(target)
            elsewhere = source_dir / "on-another-disk"
            elsewhere.write_bytes(b"the real contents")
            os.symlink(elsewhere, source_dir / name)

            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)
            with tarfile.open(archive) as tar:
                member = tar.getmember(name)
            self.assertFalse(member.issym())
            self.assertEqual(member.size, len(b"the real contents"))

            result = unpack_cache(archive, data_dir=target_dir)
            self.assertEqual(result.written, [name])
            self.assertEqual((target_dir / name).read_bytes(), b"the real contents")


class HostileArchiveTestCase(unittest.TestCase):
    """An archive comes from a URL, so its contents are somebody else's choice."""

    def test_a_member_outside_the_data_directory_is_ignored(self):
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            archive = _archive(
                Path(work) / "hostile.tar.gz",
                {
                    known: b"legitimate",
                    "../escaped.json": b"traversal",
                    "settings.json": b'{"commonchemistry_api_key": "stolen"}',
                    "subdir/nested.json": b"nested",
                },
            )
            result = unpack_cache(archive, data_dir=target_dir)

            self.assertEqual(result.written, [known])
            self.assertEqual(len(result.ignored), 3)
            self.assertFalse((target_dir.parent / "escaped.json").exists())
            self.assertFalse((target_dir / "settings.json").exists())
            self.assertEqual([p.name for p in target_dir.iterdir()], [known])

    def test_a_traversal_dressed_as_a_relative_path_is_still_ignored(self):
        """`./` is stripped from member names, and must not strip more.

        GNU tar writes `./chebi.json.gz`, so the names are normalised -- but
        normalising down to the basename would make `../../evil/chebi.json.gz`
        match the registry.
        """
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            archive = _archive(
                Path(work) / "sneaky.tar.gz", {f"../../evil/{known}": b"payload"}
            )
            self.assertEqual(unpack_cache(archive, data_dir=target_dir).written, [])
            self.assertEqual(list(target_dir.iterdir()), [])

    def test_a_symlink_member_is_ignored(self):
        """`tarfile` would happily create a link pointing anywhere."""
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            archive_path = Path(work) / "links.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                link = tarfile.TarInfo(known)
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                tar.addfile(link)

            result = unpack_cache(archive_path, data_dir=target_dir)
            self.assertEqual(result.written, [])
            self.assertEqual(result.ignored, [known])
            self.assertFalse((target_dir / known).exists())

    def test_a_manifest_of_the_wrong_shape_does_not_stop_the_unpack(self):
        """The manifest is the archive's first member and describes the caches
        without being one of them. Every one of these shapes used to raise
        `AttributeError` before a single cache was written.
        """
        known = sorted(cached_file_names())[0]
        for manifest in (
            b"[]",
            b'{"files": ["x"]}',
            b'{"files": {"a": 1}}',
            b'{"files": [{"name": 5, "bytes": "big"}]}',
            b'"a string"',
            b"null",
            b"not json at all",
            b"",
        ):
            with self.subTest(manifest=manifest):
                with TemporaryDirectory() as work, TemporaryDirectory() as target:
                    target_dir = Path(target)
                    archive = _archive(
                        Path(work) / "m.tar.gz",
                        {MANIFEST_MEMBER_NAME: manifest, known: b"real"},
                    )
                    result = unpack_cache(archive, data_dir=target_dir)
                    self.assertEqual(result.written, [known])
                    self.assertEqual((target_dir / known).read_bytes(), b"real")

    def test_an_oversized_manifest_is_not_read_into_memory(self):
        """The one read that happens before any name check."""
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            archive = _archive(
                Path(work) / "big.tar.gz",
                {
                    MANIFEST_MEMBER_NAME: b"{}" + b" " * (MANIFEST_MAX_BYTES + 1),
                    known: b"real",
                },
            )
            self.assertEqual(unpack_cache(archive, data_dir=target_dir).written, [known])

    def test_a_gnu_tar_style_member_name_is_recognised(self):
        """`tar czf archive.tar.gz .` writes `./chebi.json.gz`."""
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            archive = _archive(Path(work) / "dot.tar.gz", {f"./{known}": b"real"})
            result = unpack_cache(archive, data_dir=target_dir)
            self.assertEqual(result.written, [known])
            self.assertEqual((target_dir / known).read_bytes(), b"real")

    def test_a_truncated_archive_leaves_no_part_file(self):
        """An interrupted upload, served as if whole.

        The write raises mid-file, out of gzip's end-of-stream check; without
        cleanup the `.part` stays in the data directory for good, read by
        nothing and reported by nothing.
        """
        known = sorted(cached_file_names())[0]
        with TemporaryDirectory() as work, TemporaryDirectory() as target:
            target_dir = Path(target)
            # Incompressible, so that cutting the file really does cut the
            # member: 200 kB of one repeated byte fits in a few hundred, and a
            # truncation past that point loses only the end-of-stream marker.
            whole = _archive(Path(work) / "whole.tar.gz", {known: os.urandom(200_000)})
            truncated = Path(work) / "truncated.tar.gz"
            truncated.write_bytes(whole.read_bytes()[: whole.stat().st_size // 2])

            with self.assertRaises(EOFError):
                unpack_cache(truncated, data_dir=target_dir)
            self.assertEqual(list(target_dir.iterdir()), [])


class LocalCacheTestCase(unittest.TestCase):
    def test_an_existing_cache_is_kept_unless_overwrite(self):
        name = sorted(cached_file_names())[0]
        with TemporaryDirectory() as source, TemporaryDirectory() as target:
            source_dir, target_dir = Path(source), Path(target)
            _write_caches(source_dir, [name])
            (target_dir / name).write_bytes(b"local lookups the archive predates")
            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)

            result = unpack_cache(archive, data_dir=target_dir)
            self.assertEqual(result.written, [])
            self.assertEqual(result.kept, [name])
            self.assertEqual(
                (target_dir / name).read_bytes(), b"local lookups the archive predates"
            )

            result = unpack_cache(archive, data_dir=target_dir, overwrite=True)
            self.assertEqual(result.written, [name])
            self.assertEqual(
                (target_dir / name).read_bytes(), (source_dir / name).read_bytes()
            )


class UrlTestCase(unittest.TestCase):
    def setUp(self):
        self._previous = os.environ.pop(CACHE_URL_ENV_VAR, None)

    def tearDown(self):
        if self._previous is None:
            os.environ.pop(CACHE_URL_ENV_VAR, None)
        else:
            os.environ[CACHE_URL_ENV_VAR] = self._previous

    def test_the_environment_variable_is_the_default(self):
        os.environ[CACHE_URL_ENV_VAR] = "https://example.invalid/cache.tar.gz"
        self.assertEqual(cache_url(), "https://example.invalid/cache.tar.gz")
        self.assertEqual(cache_url("https://other.invalid/x"), "https://other.invalid/x")

    def test_no_url_anywhere_names_the_variable(self):
        with self.assertRaises(ValueError) as raised:
            fetch_cache()
        self.assertIn(CACHE_URL_ENV_VAR, str(raised.exception))

    def test_a_local_archive_is_unpacked_where_it_lies(self):
        """A shared drive, a USB stick, an artifact CI already downloaded."""
        name = sorted(cached_file_names())[0]
        with TemporaryDirectory() as source, TemporaryDirectory() as target:
            source_dir, target_dir = Path(source), Path(target)
            _write_caches(source_dir, [name])
            archive = pack_cache(source_dir / "archive.tar.gz", data_dir=source_dir)

            self.assertEqual(fetch_cache(str(archive), data_dir=target_dir).written, [name])
            self.assertEqual(
                fetch_cache(
                    archive.as_uri(), data_dir=target_dir, overwrite=True
                ).written,
                [name],
            )
            self.assertTrue(archive.exists())

    def test_a_missing_local_path_says_which_file(self):
        """An unmounted share and a typo are the two commonest mistakes here,
        and both used to reach the downloader and come back as "Request URL is
        missing an 'http://' or 'https://' protocol".
        """
        with TemporaryDirectory() as target:
            target_dir = Path(target)
            missing = target_dir / "not-here.tar.gz"
            for value in (str(missing), missing.as_uri(), "~/typo/cach.tar.gz"):
                with self.subTest(url=value):
                    with self.assertRaises(FileNotFoundError) as raised:
                        fetch_cache(value, data_dir=target_dir)
                    self.assertIn(
                        Path(value).name, str(raised.exception),
                        "the error must name the file it could not find",
                    )


if __name__ == "__main__":
    unittest.main()

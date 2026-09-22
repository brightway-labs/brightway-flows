"""OPSIN parse errors go to the log file, not stderr."""

import warnings
from pathlib import Path

import pytest

from brightway_flows.transformers import opsin_iupac
from brightway_flows.transformers.opsin_iupac import (
    _opsin_batch,
    configure_opsin_logging,
)

# The shape py2opsin produces: a header line, then one " > "-prefixed line per
# unparseable name.
OPSIN_WARNING_TEXT = (
    "OPSIN raised the following error(s) while parsing:\n"
    " > proton is unparsable due to the following being uninterpretable: proton\n"
    " > Unable to assign all locants. This locant was not assigned: As \n"
)


@pytest.fixture
def stub_py2opsin(monkeypatch):
    """Replace py2opsin with a stub that warns exactly as the real one does."""
    import sys
    import types

    def fake_py2opsin(chemical_name, output_format="SMILES"):
        warnings.warn(OPSIN_WARNING_TEXT, RuntimeWarning)
        return ["C" for _ in chemical_name]

    module = types.ModuleType("py2opsin")
    module.py2opsin = fake_py2opsin
    monkeypatch.setitem(sys.modules, "py2opsin", module)


def test_opsin_errors_are_logged_not_printed(stub_py2opsin, tmp_path, capfd) -> None:
    log_path = tmp_path / "opsin.log"
    configure_opsin_logging(log_path)

    assert _opsin_batch(["proton", "arsenic"]) == ["C", "C"]

    captured = capfd.readouterr()
    assert "unparsable" not in captured.err
    assert "unparsable" not in captured.out

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    messages = [line.split("\t", 1)[1] for line in lines]
    assert messages[0].startswith("proton is unparsable")
    assert messages[1].startswith("Unable to assign all locants")
    # The py2opsin header and line prefix are stripped.
    assert not any(m.startswith(">") or m.startswith("OPSIN raised") for m in messages)


def test_unrelated_warnings_are_not_swallowed(monkeypatch, tmp_path) -> None:
    import sys
    import types

    def fake_py2opsin(chemical_name, output_format="SMILES"):
        warnings.warn("something else entirely", DeprecationWarning)
        return ["C"]

    module = types.ModuleType("py2opsin")
    module.py2opsin = fake_py2opsin
    monkeypatch.setitem(sys.modules, "py2opsin", module)
    configure_opsin_logging(tmp_path / "opsin.log")

    with pytest.warns(DeprecationWarning, match="something else entirely"):
        _opsin_batch(["methane"])


def test_errors_are_dropped_when_no_log_file_is_configured(
    stub_py2opsin, capfd, monkeypatch
) -> None:
    monkeypatch.setattr(opsin_iupac, "_opsin_log_path", None)

    _opsin_batch(["proton"])

    captured = capfd.readouterr()
    assert "unparsable" not in captured.err
    assert "unparsable" not in captured.out


def test_configure_clears_the_log_file(tmp_path: Path) -> None:
    log_path = tmp_path / "opsin.log"
    log_path.write_text("stale content\n", encoding="utf-8")
    configure_opsin_logging(log_path)
    assert log_path.read_text(encoding="utf-8") == ""

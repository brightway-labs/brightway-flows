"""RDKit must never write to stdout/stderr; messages go to the log file."""

import os
import tempfile
from pathlib import Path

from rdkit import Chem
from rdkit.Chem.inchi import MolFromInchi, MolToInchi

from brightway_flows.chem import capture_rdkit_logs, configure_rdkit_logging


def _noisy_rdkit_calls() -> None:
    """Exercise the RDKit calls known to emit errors and warnings."""
    Chem.MolFromSmiles("C1CC")  # unclosed ring -> rdApp.error
    Chem.MolFromSmiles("N(C)(C)(C)C")  # bad valence -> rdApp.error
    Chem.MolFromSmarts("C1CC")  # unclosed ring -> rdApp.error
    Chem.MolFromMolBlock("junk\n\n\n  0  0\n")  # -> rdApp.warning
    MolFromInchi("InChI=1S/garbage")  # -> rdApp.error
    mol = Chem.MolFromSmiles("[Fe+2].[O-]S(=O)(=O)[O-]")
    assert mol is not None
    MolToInchi(mol)  # "Proton(s) added/removed" -> rdApp.warning


def _run_capturing_fds(fn) -> str:
    """Run *fn* with fds 1 and 2 pointed at a file; return what was written.

    Capturing at the file-descriptor level rather than swapping ``sys.stdout``
    catches writes from RDKit's C++ streams, which Python-level redirection
    would miss.
    """
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".fd") as sink:
        saved_out, saved_err = os.dup(1), os.dup(2)
        try:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            try:
                fn()
            finally:
                os.dup2(saved_out, 1)
                os.dup2(saved_err, 2)
        finally:
            os.close(saved_out)
            os.close(saved_err)
        sink.flush()
        sink.seek(0)
        return sink.read()


def test_rdkit_messages_never_reach_stdout_or_stderr(tmp_path: Path) -> None:
    configure_rdkit_logging(tmp_path / "rdkit.log")

    def work() -> None:
        with capture_rdkit_logs("some-uuid Some Flow"):
            _noisy_rdkit_calls()

    assert _run_capturing_fds(work) == ""


def test_rdkit_messages_are_written_to_the_log_file(tmp_path: Path) -> None:
    log_path = tmp_path / "rdkit.log"
    configure_rdkit_logging(log_path)

    with capture_rdkit_logs("some-uuid Some Flow"):
        _noisy_rdkit_calls()

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    assert lines, "expected RDKit messages to be logged"
    assert all(line.split("\t")[1] == "some-uuid Some Flow" for line in lines)

    messages = [line.split("\t", 2)[2] for line in lines]
    # The two warnings that CaptureErrorLog could not intercept.
    assert any("Proton(s) added/removed" in message for message in messages)
    assert any("Problems encountered parsing Mol data" in message for message in messages)
    # Errors are still captured.
    assert any("SMILES Parse Error" in message for message in messages)


def test_messages_are_dropped_when_no_log_file_is_configured() -> None:
    import brightway_flows.chem as chem

    saved = chem._rdkit_log_path
    chem._rdkit_log_path = None
    try:
        assert _run_capturing_fds(_noisy_rdkit_calls) == ""
    finally:
        chem._rdkit_log_path = saved

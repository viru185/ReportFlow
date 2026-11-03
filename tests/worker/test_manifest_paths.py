"""Parse registered VSTO paths without starting Excel or its COM event loop."""

from pathlib import Path

import pytest

from reportflow.worker.diagnostics import _manifest_path


@pytest.mark.parametrize(
    "manifest",
    [
        r"file:\\D:\Program Files\PIPC\Excel\OSIsoft.PIDataLink.UI.vsto|vstolocal",
        "file:///D:/Program%20Files/PIPC/Excel/OSIsoft.PIDataLink.UI.vsto|vstolocal",
        "file://localhost/D:/Program Files/PIPC/Excel/OSIsoft.PIDataLink.UI.vsto|vstolocal",
    ],
)
def test_registered_pi_manifest_uri_does_not_become_a_false_missing_unc_path(manifest):
    assert _manifest_path(manifest) == Path(
        "D:/Program Files/PIPC/Excel/OSIsoft.PIDataLink.UI.vsto"
    )


def test_network_manifest_retains_its_server():
    assert _manifest_path("file://server/share/PI.vsto|vstolocal") == Path("//server/share/PI.vsto")

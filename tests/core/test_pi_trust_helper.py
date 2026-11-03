"""The administrator helper must inspect without granting trust or accepting a bad pin."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "repair-pi-publisher-trust.ps1"


def _shell(exe, *args):
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.mark.parametrize("shell_name", ["powershell.exe", "pwsh.exe"])
def test_inspect_and_invalid_approval_never_add_a_certificate(tmp_path, shell_name):
    exe = shutil.which(shell_name)
    if not exe:
        pytest.skip(f"{shell_name} is not installed")
    fixture = tmp_path / "make-fixture.ps1"
    manifest = tmp_path / "test.vsto"
    fixture.write_text(
        r"""
param([string] $OutputPath)
$ErrorActionPreference = 'Stop'
$rsa = [Security.Cryptography.RSACng]::new(2048)
try {
    $dn = 'CN=ReportFlow trust inspection test'
    $name = New-Object Security.Cryptography.X509Certificates.X500DistinguishedName($dn)
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        $name, $rsa, [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
    $cert = $request.CreateSelfSigned(
        [DateTimeOffset]::Now.AddDays(-1), [DateTimeOffset]::Now.AddDays(1)
    )
    try {
        $b64 = [Convert]::ToBase64String($cert.RawData)
        $xml = '<assembly><Signature xmlns="http://www.w3.org/2000/09/xmldsig#">' +
            '<KeyInfo><X509Data><X509Certificate>' + $b64 +
            '</X509Certificate></X509Data></KeyInfo></Signature></assembly>'
        [IO.File]::WriteAllText($OutputPath, $xml)
    } finally { $cert.Dispose() }
} finally { $rsa.Dispose() }
""",
        encoding="utf-8",
    )
    created = _shell(exe, "-File", fixture, manifest)
    if "AuthorizationManager check failed" in created.stderr:
        pytest.skip(f"{shell_name} policy blocks local script execution")
    assert created.returncode == 0, created.stderr
    inspected = _shell(exe, "-File", SCRIPT, "-ManifestPath", manifest)
    assert inspected.returncode == 0, inspected.stderr
    rows = json.loads(inspected.stdout.lstrip("\ufeff"))
    assert len(rows) == 1 and rows[0]["Action"] == "Inspection only"
    assert not rows[0]["TrustedBefore"] and len(rows[0]["Sha256"]) == 64
    invalid = _shell(
        exe,
        "-File",
        SCRIPT,
        "-ManifestPath",
        manifest,
        "-ApprovedSha256",
        "0" * 64,
        "-Apply",
        "-WhatIf",
    )
    assert invalid.returncode != 0
    assert "does not match any supplied manifest" in invalid.stderr
    no_pin = _shell(exe, "-File", SCRIPT, "-ManifestPath", manifest, "-Apply", "-WhatIf")
    assert no_pin.returncode != 0 and "independently approved" in no_pin.stderr
    after = _shell(exe, "-File", SCRIPT, "-ManifestPath", manifest)
    assert not json.loads(after.stdout.lstrip("\ufeff"))[0]["TrustedBefore"]

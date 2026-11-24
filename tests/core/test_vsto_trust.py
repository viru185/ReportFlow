"""Trusting PI DataLink for the service account (VSTO inclusion list), on a fake registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from reportflow.core import vsto_trust

_MODULUS = "rF05qnWeiZkD5bSwhhGDuZQb6HBJ\n      tMIvpG4ANMfOrzl7Qv5yqwqEKH7=="
_KEY = (
    "<RSAKeyValue><Modulus>rF05qnWeiZkD5bSwhhGDuZQb6HBJtMIvpG4ANMfOrzl7Qv5yqwqEKH7==</Modulus>"
    "<Exponent>AQAB</Exponent></RSAKeyValue>"
)


def _manifest(path: Path, signature_id: str = "StrongNameSignature") -> Path:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<asmv1:assembly xmlns:asmv1="urn:schemas-microsoft-com:asm.v1">
  <Signature Id="{signature_id}" xmlns="http://www.w3.org/2000/09/xmldsig#">
    <KeyInfo><KeyValue><RSAKeyValue>
      <Modulus>{_MODULUS}</Modulus>
      <Exponent>AQAB</Exponent>
    </RSAKeyValue></KeyValue></KeyInfo>
  </Signature>
</asmv1:assembly>""",
        encoding="utf-8",
    )
    return path


def test_public_key_comes_out_in_the_inclusion_list_format(tmp_path):
    # Same text .NET's RSA.ToXmlString(false) / UserInclusionList store: no namespace, no
    # whitespace (checked against the installed VSTO runtime).
    assert vsto_trust.manifest_public_key(_manifest(tmp_path / "PI.vsto")) == _KEY
    authenticode_only = _manifest(tmp_path / "A.vsto", "AuthenticodeSignature")
    assert vsto_trust.manifest_public_key(authenticode_only) == _KEY
    (tmp_path / "bad.vsto").write_text("not xml", encoding="utf-8")
    assert vsto_trust.manifest_public_key(tmp_path / "bad.vsto") is None
    assert vsto_trust.manifest_public_key(tmp_path / "missing.vsto") is None


def test_manifest_urls_lead_with_the_form_vsto_writes():
    urls = vsto_trust.manifest_urls(Path("D:/Program Files (x86)/PIPC/Excel/PI.vsto"))
    assert urls == [
        "file:///D:/Program Files (x86)/PIPC/Excel/PI.vsto",  # what UserInclusionList.Add stores
        "file:///D:/Program%20Files%20(x86)/PIPC/Excel/PI.vsto",  # Uri.AbsoluteUri spelling
    ]


def test_only_admin_installed_pi_addins_with_a_manifest_count(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path / "PI.vsto")
    rows = [
        {"root": "HKLM", "bits": 64, "progid": "PI DataLink", "Manifest": f"file:///{manifest}"},
        # same file through the other registry view -> one add-in, not two
        {"root": "HKLM", "bits": 32, "progid": "PI DataLink", "Manifest": f"{manifest}|vstolocal"},
        # a per-user registration is never trusted on the user's behalf
        {"root": "HKCU", "bits": 64, "progid": "PIAFBuilder", "Manifest": f"file:///{manifest}"},
        {"root": "HKLM", "bits": 64, "progid": "PIAFBuilder", "Manifest": "file:///C:/gone.vsto"},
    ]
    monkeypatch.setattr(vsto_trust, "pi_registrations", lambda: rows)
    [addin] = vsto_trust.pi_addins()
    assert addin.name == "PI DataLink" and addin.public_key == _KEY
    assert addin.label == "PI DataLink"  # one file serves both Excels: no suffix


def test_separate_32_and_64_bit_copies_are_labelled_by_excel(tmp_path, monkeypatch):
    # A typical PI install (the owner's laptop, Nov 2026): PI DataLink twice, one file per
    # Excel, and one PIAFBuilder file that both register.
    (tmp_path / "x64").mkdir()
    (tmp_path / "x86").mkdir()
    dl64 = _manifest(tmp_path / "x64" / "OSIsoft.PIDataLink.UI.vsto")
    dl32 = _manifest(tmp_path / "x86" / "OSIsoft.PIDataLink.UI.vsto")
    af = _manifest(tmp_path / "x86" / "PIAFBuilder.vsto")
    rows = [
        {"root": "HKLM", "bits": 32, "progid": "PI DataLink", "Manifest": f"file:\\\\{dl32}"},
        {"root": "HKLM", "bits": 32, "progid": "PIAFBuilder", "Manifest": f"file:///{af}"},
        {"root": "HKLM", "bits": 64, "progid": "PI DataLink", "Manifest": f"file:\\\\{dl64}"},
        {"root": "HKLM", "bits": 64, "progid": "PIAFBuilder", "Manifest": f"file:///{af}"},
    ]
    monkeypatch.setattr(vsto_trust, "pi_registrations", lambda: rows)
    _FakeInclusion().install(monkeypatch)

    addins = vsto_trust.pi_addins()
    assert [(a.label, a.manifest) for a in addins] == [
        ("PI DataLink (64-bit Excel)", dl64),
        ("PI DataLink (32-bit Excel)", dl32),
        ("PIAFBuilder", af),
    ]
    assert [r["label"] for r in vsto_trust.trust_status()] == [a.label for a in addins]
    results = vsto_trust.trust_pi_addins()
    assert [(r["label"], r["result"]) for r in results] == [
        ("PI DataLink (64-bit Excel)", "trusted"),
        ("PI DataLink (32-bit Excel)", "trusted"),
        ("PIAFBuilder", "trusted"),
    ]
    assert {r["name"] for r in results} == {"PI DataLink", "PIAFBuilder"}  # names unchanged


class _FakeInclusion:
    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def install(self, monkeypatch):
        monkeypatch.setattr(vsto_trust, "_read_inclusion", lambda: [dict(e) for e in self.entries])
        monkeypatch.setattr(vsto_trust, "_write_inclusion", self.write)
        monkeypatch.setattr(vsto_trust, "_delete_inclusion", self.delete)
        return self

    def write(self, url, public_key):
        self.entries.append({"key": f"k{len(self.entries)}", "url": url, "public_key": public_key})

    def delete(self, key):
        self.entries = [e for e in self.entries if e["key"] != key]


def _addin(tmp_path, key=_KEY):
    path = tmp_path / "Program Files" / "PI.vsto"  # a space: two URL spellings
    return vsto_trust.PiAddin("PI DataLink", path, key, vsto_trust.manifest_urls(path))


def test_trusting_writes_one_entry_then_reports_already_trusted(tmp_path, monkeypatch):
    addin = _addin(tmp_path)
    monkeypatch.setattr(vsto_trust, "pi_addins", lambda: [addin])
    reg = _FakeInclusion().install(monkeypatch)

    assert vsto_trust.untrusted_pi_addins() == ["PI DataLink"]
    assert [r["result"] for r in vsto_trust.trust_pi_addins()] == ["trusted"]
    assert reg.entries == [{"key": "k0", "url": addin.urls[0], "public_key": _KEY}]
    assert [r["result"] for r in vsto_trust.trust_pi_addins()] == ["already trusted"]
    assert vsto_trust.untrusted_pi_addins() == []
    assert vsto_trust.trust_status()[0]["trusted"] is True


def test_an_entry_with_an_old_key_is_replaced(tmp_path, monkeypatch):
    # After a PI upgrade re-signs the manifest, VSTO refuses the old entry again.
    addin = _addin(tmp_path)
    monkeypatch.setattr(vsto_trust, "pi_addins", lambda: [addin])
    reg = _FakeInclusion([{"key": "old", "url": addin.urls[1], "public_key": "<old/>"}])
    reg.install(monkeypatch)

    assert vsto_trust.untrusted_pi_addins() == ["PI DataLink"]
    assert [r["result"] for r in vsto_trust.trust_pi_addins()] == ["trusted"]
    assert [e["public_key"] for e in reg.entries] == [_KEY]


def test_failures_are_reported_per_addin(tmp_path, monkeypatch):
    no_key = _addin(tmp_path, key=None)
    monkeypatch.setattr(vsto_trust, "pi_addins", lambda: [no_key])
    _FakeInclusion().install(monkeypatch)
    assert vsto_trust.trust_pi_addins()[0]["result"].startswith("failed: ")

    def denied(url, key):
        raise PermissionError("access denied")

    monkeypatch.setattr(vsto_trust, "pi_addins", lambda: [_addin(tmp_path)])
    monkeypatch.setattr(vsto_trust, "_write_inclusion", denied)
    assert vsto_trust.trust_pi_addins()[0]["result"] == "failed: access denied"


@pytest.mark.parametrize(
    ("untrusted", "disabled"),
    [(["PI DataLink"], []), ([], []), ([], ["PI DataLink"]), (["PI DataLink"], ["PI DataLink"])],
)
def test_run_warning_names_the_reason_and_the_fix_button(monkeypatch, untrusted, disabled):
    from reportflow.worker import runner

    monkeypatch.setattr(runner, "untrusted_pi_addins", lambda: untrusted)
    monkeypatch.setattr(runner, "disabled_pi_addins", lambda: disabled)
    monkeypatch.setattr(runner, "windows_identity", lambda: r"NMC\SVC_PI")
    warning = runner._addin_warning("PI DataLink")
    if disabled:  # the HIL case: Excel switched it off — said first, it's what blocks it
        assert r"Excel has switched it off for NMC\SVC_PI" in warning
        assert "Disabled Items" in warning and "Fix PI DataLink" in warning
    elif untrusted:
        assert r"has not trusted it for NMC\SVC_PI" in warning
        assert "Fix PI DataLink" in warning
    else:
        assert "see pi_diagnostics" in warning
    # a non-PI add-in never gets the PI hint
    assert "Fix PI DataLink" not in runner._addin_warning("Inquire")

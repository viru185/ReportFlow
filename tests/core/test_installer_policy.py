"""Static safety checks on the executable installer account-write path.

Inno compilation and a disposable-machine upgrade are separate validation stages;
these guards catch removal of the protections without touching Windows services.
"""

import re
from pathlib import Path

SOURCE = (Path(__file__).parents[2] / "packaging/innosetup/reportflow.iss").read_text(
    encoding="utf-8"
)


def function(name):
    match = re.search(rf"function {name}\b[^\n]*;\n(?:var\n.*?\n)?begin\n.*?\nend;", SOURCE, re.S)
    assert match is not None
    return match.group()


def test_upgrade_account_write_is_guarded_independently_of_wizard_mode():
    commands = [
        line for line in SOURCE.splitlines() if "Parameters:" in line and "ObjectName" in line
    ]
    assert len(commands) == 1
    assert "Check: HasServiceAccount" in commands[0]
    guard = function("HasServiceAccount")
    assert "(not ExistingService) and (not WizardSilent)" in guard
    # The parameter expansion is guarded too, before credentials are assembled.
    expansion = function("NssmObjectNameArgs")
    assert expansion.index("if ExistingService then") < expansion.index("ObjectName ")


def test_upgrade_detection_precedes_fresh_install_and_skips_account_page():
    assert "ExistingService := ServiceExists;" in function("InitializeSetup")
    assert "and ExistingService" in function("ShouldSkipPage")
    assert "if WizardSilent or ExistingService then" in function("NextButtonClick")
    install = next(line for line in SOURCE.splitlines() if 'Parameters: "install ' in line)
    assert "Check: ServiceNotInstalled" in install
    assert "(Trim(AccountPage.Values[0]) <> '')" in function("HasServiceAccount")


def test_unknown_service_detection_stops_setup_instead_of_reconfiguring_account():
    detection = function("ServiceExists")
    assert "if not Exec(" in detection
    assert "(ResultCode <> 0) and (ResultCode <> 1060)" in detection
    assert detection.count("RaiseException(") == 2

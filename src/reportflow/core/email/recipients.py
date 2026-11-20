"""Expand email groups into the addresses an email actually goes to.

A job's To/Cc/Bcc can mix single addresses and email groups (Settings → Email groups), and
groups often overlap: the plant manager is in both "Plant leads" and "Energy team". Every
address goes out once, case-insensitively, in the first field that names it — To before Cc
before Bcc — so nobody gets the report twice or appears in To and Cc at the same time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from reportflow.core.config.models import EmailGroup, Recipients


@dataclass
class ResolvedRecipients:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)

    def all_addresses(self) -> list[str]:
        """Every envelope address; already unique across To/Cc/Bcc."""
        return [*self.to, *self.cc, *self.bcc]


def resolve(recipients: Recipients, groups: Iterable[EmailGroup]) -> ResolvedRecipients:
    """Addresses + expanded groups per field, each address once (To > Cc > Bcc).

    The first spelling of an address wins. A group that no longer exists contributes
    nothing — the config validator refuses such references before they are saved.
    """
    members = {g.name.casefold(): [str(m) for m in g.members] for g in groups}
    seen: set[str] = set()

    def take(addresses: Iterable[object], group_names: list[str]) -> list[str]:
        out: list[str] = []
        expanded = [m for name in group_names for m in members.get(name.casefold(), [])]
        for address in [*(str(a) for a in addresses), *expanded]:
            key = address.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                out.append(address.strip())
        return out

    return ResolvedRecipients(
        to=take(recipients.to, recipients.to_groups),
        cc=take(recipients.cc, recipients.cc_groups),
        bcc=take(recipients.bcc, recipients.bcc_groups),
    )

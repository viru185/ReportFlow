"""Expand email groups into the addresses an email actually goes to.

A job's To/Cc/Bcc can mix single addresses and email groups (Settings → Email groups), and
groups often overlap: the plant manager is in both "Plant leads" and "Energy team". Every
address goes out once, case-insensitively, in the first field that names it — To before Cc
before Bcc — so nobody gets the report twice or appears in To and Cc at the same time.

Order is kept: each field lists people in the order the job arranges them, and a group's
members go out at the group's place, in the group's own order (0.15 — corporate readers
care who is named first).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from reportflow.core.config.models import EmailGroup, GroupRef, Recipients


@dataclass
class ResolvedRecipients:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)

    def all_addresses(self) -> list[str]:
        """Every envelope address; already unique across To/Cc/Bcc."""
        return [*self.to, *self.cc, *self.bcc]


def resolve(recipients: Recipients, groups: Iterable[EmailGroup]) -> ResolvedRecipients:
    """Addresses + expanded groups per field, in order, each address once (To > Cc > Bcc).

    The first spelling of an address wins. A group that no longer exists contributes
    nothing — the config validator refuses such references before they are saved.
    """
    members = {g.name.casefold(): [str(m) for m in g.members] for g in groups}
    seen: set[str] = set()

    def take(entries: Iterable[object]) -> list[str]:
        out: list[str] = []
        for entry in entries:
            if isinstance(entry, GroupRef):
                addresses = members.get(entry.group.casefold(), [])
            else:
                addresses = [str(entry)]
            for address in addresses:
                key = address.strip().casefold()
                if key and key not in seen:
                    seen.add(key)
                    out.append(address.strip())
        return out

    return ResolvedRecipients(
        to=take(recipients.to),
        cc=take(recipients.cc),
        bcc=take(recipients.bcc),
    )

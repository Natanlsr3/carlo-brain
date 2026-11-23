"""Search macOS Contacts (AddressBook), read-only.

Usage: contacts.py "<name>" [--max 20]   |   contacts.py --phone <number>
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import AccessError, fold, open_ro, same_number  # noqa: E402

ROOT = os.path.expanduser("~/Library/Application Support/AddressBook")


@dataclass
class Contact:
    """One contact card, merged across sources."""

    first: str = ""
    last: str = ""
    organisation: str = ""
    phones: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)

    @property
    def display(self) -> str:
        return " ".join(x for x in (self.first, self.last) if x) or self.organisation or "(no name)"


def find_databases(root: str = ROOT) -> List[str]:
    """Every AddressBook database (iCloud and local sources)."""
    bases = sorted(glob.glob(os.path.join(root, "Sources", "*", "AddressBook-v22.abcddb")))
    top = os.path.join(root, "AddressBook-v22.abcddb")
    if os.path.exists(top):
        bases.append(top)
    return bases


def _read(path: str) -> List[Contact]:
    with open_ro(path) as conn:
        records = conn.execute(
            "select Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION from ZABCDRECORD"
            " where ZFIRSTNAME is not null or ZLASTNAME is not null or ZORGANIZATION is not null"
        ).fetchall()
        phones: dict = {}
        for owner, number in conn.execute("select ZOWNER, ZFULLNUMBER from ZABCDPHONENUMBER"):
            if number:
                phones.setdefault(owner, []).append(number)
        emails: dict = {}
        for owner, address in conn.execute("select ZOWNER, ZADDRESS from ZABCDEMAILADDRESS"):
            if address:
                emails.setdefault(owner, []).append(address)
    return [Contact(f or "", l or "", o or "", phones.get(pk, []), emails.get(pk, [])) for pk, f, l, o in records]


def load_contacts(bases: Optional[List[str]] = None) -> List[Contact]:
    """Load and merge contacts from all databases (key: first + last + organisation)."""
    merged: dict = {}
    for base in bases if bases is not None else find_databases():
        for c in _read(base):
            key = (fold(c.first), fold(c.last), fold(c.organisation))
            target = merged.setdefault(key, Contact(c.first, c.last, c.organisation))
            for number in c.phones:
                if not any(same_number(number, x) for x in target.phones):
                    target.phones.append(number)
            for address in c.emails:
                if address.lower() not in (x.lower() for x in target.emails):
                    target.emails.append(address)
    return list(merged.values())


def by_name(query: str, contacts: List[Contact]) -> List[Contact]:
    """Contacts whose name or organisation contains every word of the query."""
    words = fold(query).split()
    if not words:
        return []
    return [c for c in contacts if all(w in fold(" ".join((c.first, c.last, c.organisation))) for w in words)]


def by_phone(number: str, contacts: List[Contact]) -> List[Contact]:
    """Contacts that own this number."""
    return [c for c in contacts if any(same_number(number, p) for p in c.phones)]


def format_contact(c: Contact) -> str:
    """One readable line."""
    parts = [c.display]
    if c.organisation and c.organisation != c.display:
        parts.append(c.organisation)
    if c.phones:
        parts.append("phone: " + ", ".join(c.phones))
    if c.emails:
        parts.append("mail: " + ", ".join(c.emails))
    return " | ".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Search Contacts (read-only)")
    parser.add_argument("name", nargs="?", help="first name, last name or organisation")
    parser.add_argument("--phone", help="find who owns this number")
    parser.add_argument("--max", type=int, default=20)
    args = parser.parse_args(argv)
    if not args.name and not args.phone:
        parser.error("give a name or --phone")
    try:
        contacts = load_contacts()
    except (AccessError, FileNotFoundError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    found = by_phone(args.phone, contacts) if args.phone else by_name(args.name, contacts)
    for c in found[: args.max]:
        print(format_contact(c))
    print(f"{len(found)} result(s)" + (f", {args.max} shown" if len(found) > args.max else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Functional roles, kept apart from the parties that play them.

A role names what an agent *does* in a protocol; the party -- who it is -- is a
separate field of :class:`AgentRef`. The standards these protocols align to
separate the two as well: USEF "does not prescribe a single business model but
rather a role model", so one utility can be the distribution operator
requesting flexibility in one conversation and the program administrator
publishing a demand-response event in another.

:data:`ROLE_ALIGNMENT` states how each role reads in USEF 2021 and in OpenADR
3.1.0, with ``None`` where a standard defines no such role. OpenADR 3.1.0 names
two kinds of client of its server (the VTN): the business logic, ``BL`` -- the
only client its API scopes allow to write programs and events -- and the
``VEN``. Sources: ``docs/reference/standards-alignment.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from gridalyn.operations.interaction.vocabulary import RoleId, parse_role


@dataclass(frozen=True)
class RoleAlignment:
    """How a gridalyn role reads in the standards it is aligned to.

    Attributes:
        role: The gridalyn role.
        usef: The USEF 2021 role, or ``None`` when USEF defines none.
        openadr: The OpenADR 3.1.0 client that plays it, or ``None``.
        responsibility: What the role does in gridalyn's protocols.
    """

    role: RoleId
    usef: str | None
    openadr: str | None
    responsibility: str


#: Alignment of every role, keyed by role.
ROLE_ALIGNMENT: Mapping[RoleId, RoleAlignment] = MappingProxyType(
    {
        "distribution_operator": RoleAlignment(
            role="distribution_operator",
            usef="DSO",
            openadr=None,
            responsibility=(
                "Requests flexibility to relieve a constraint on its network, "
                "orders offers and settles them (flex_trading)."
            ),
        ),
        "aggregator": RoleAlignment(
            role="aggregator",
            usef="AGR",
            openadr="VEN",
            responsibility=(
                "Offers flexibility pooled from the resources it represents "
                "(flex_trading); receives events for them (dr_program)."
            ),
        ),
        "program_administrator": RoleAlignment(
            role="program_administrator",
            usef=None,
            openadr="BL",
            responsibility=(
                "Publishes demand-response events, cancels them and receives "
                "reports (dr_program). USEF has no demand-response program role."
            ),
        ),
        "active_customer": RoleAlignment(
            role="active_customer",
            usef="Active Customer",
            openadr="VEN",
            responsibility=(
                "A site responding to events itself, without an aggregator "
                "(dr_program). USEF 2021 name, formerly Prosumer."
            ),
        ),
    }
)


@dataclass(frozen=True)
class AgentRef:
    """An agent, the party it belongs to, and the role it plays.

    Attributes:
        agent_id: Identifier of the agent; unique within a run.
        party_id: Identifier of the party the agent acts for. Several agents,
            in different roles, may share one party.
        role: The functional role the agent plays.
    """

    agent_id: str
    party_id: str
    role: RoleId

    def __post_init__(self) -> None:
        """Refuse an empty identifier or a role outside the vocabulary.

        Raises:
            ValueError: Naming the field and the value found.
        """
        for label, value in (("agent_id", self.agent_id), ("party_id", self.party_id)):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"AgentRef.{label} must be a non-empty string; found {value!r}"
                )
        parse_role(self.role)

    def as_dict(self) -> dict[str, str]:
        """Return a plain-JSON view."""
        return {"agent_id": self.agent_id, "party_id": self.party_id, "role": self.role}


__all__ = ["ROLE_ALIGNMENT", "AgentRef", "RoleAlignment"]

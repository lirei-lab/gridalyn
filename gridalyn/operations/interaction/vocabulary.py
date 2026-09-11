"""Closed vocabularies of agent interaction: roles, communicative acts, protocols.

Three sets, each a ``Literal`` for the type checker and a ``parse_*`` guard for
values that arrive as data (a message-log row, a JSON payload):

* **Roles** are *functional*: what an agent does in a protocol, not who it is.
  One party -- a utility -- can play ``distribution_operator`` in one
  conversation and ``program_administrator`` in another; the party is carried
  separately on :class:`~gridalyn.operations.interaction.roles.AgentRef`. The
  alignment of each role to USEF 2021 and OpenADR 3 lives in
  :mod:`gridalyn.operations.interaction.roles`.
* **Performatives** are the 22 communicative acts of FIPA SC00037J, spelled as
  that specification spells them (``accept-proposal``, ``cfp``). All 22 are
  accepted as values; a protocol states which one each of its messages uses.
* **Protocols** are the two gridalyn ships: ``flex_trading`` (UFTP 3.1.0
  message names, USEF roles) and ``dr_program`` (OpenADR 3.1.0 objects).
"""

from __future__ import annotations

from typing import Literal, get_args

from gridalyn.operations.vocabulary import _parse_term

RoleId = Literal[
    "distribution_operator",
    "aggregator",
    "program_administrator",
    "active_customer",
]
Performative = Literal[
    "accept-proposal",
    "agree",
    "cancel",
    "cfp",
    "confirm",
    "disconfirm",
    "failure",
    "inform",
    "inform-if",
    "inform-ref",
    "not-understood",
    "propagate",
    "propose",
    "proxy",
    "query-if",
    "query-ref",
    "refuse",
    "reject-proposal",
    "request",
    "request-when",
    "request-whenever",
    "subscribe",
]
ProtocolId = Literal["flex_trading", "dr_program"]

ROLE_IDS: tuple[RoleId, ...] = get_args(RoleId)
PERFORMATIVES: tuple[Performative, ...] = get_args(Performative)
PROTOCOL_IDS: tuple[ProtocolId, ...] = get_args(ProtocolId)


def parse_role(value: object) -> RoleId:
    """Return ``value`` as a functional role, refusing anything outside the set.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, ROLE_IDS, "role")


def parse_performative(value: object) -> Performative:
    """Return ``value`` as a FIPA communicative act, spelled as SC00037J spells it.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, PERFORMATIVES, "performative")


def parse_protocol_id(value: object) -> ProtocolId:
    """Return ``value`` as a shipped protocol id, refusing anything else.

    Raises:
        ValueError: Naming the field, the value found and the accepted set.
    """
    return _parse_term(value, PROTOCOL_IDS, "protocol")


__all__ = [
    "PERFORMATIVES",
    "PROTOCOL_IDS",
    "ROLE_IDS",
    "Performative",
    "ProtocolId",
    "RoleId",
    "parse_performative",
    "parse_protocol_id",
    "parse_role",
]

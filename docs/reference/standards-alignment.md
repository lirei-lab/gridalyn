# Standards Alignment

The semantic graph and the planned agent-interaction layer name external
standards: IEC CIM, Brick, EFOnt, IEEE 2030.5, OpenADR, USEF/UFTP, S2,
SAREF4ENER and FIPA ACL. This page records what each of those standards
actually publishes — identifiers, versions, term spellings — **verified against
primary sources on 2026-09-10**, and where the current profile agrees or does
not.

It exists so that no field name, predicate or namespace IRI is frozen from
memory. When a row says a gridalyn identifier is wrong, that is a finding to
fix, not a description of intended behaviour.

"Primary" below means the standard body's or author's own artifact. "Mirror"
means a byte copy hosted by a third party because the official host is gated.
A statement that something does not exist means it was not found in the
artifacts listed, not a proof of absence everywhere.

## Summary against the current profile

The profile in question is declared in `gridalyn/twin/semantic/profile.py` and
`gridalyn/twin/semantic/capabilities/flexibility.py`.

| Prefix / term in gridalyn | Verified fact | Status |
| --- | --- | --- |
| `brick: https://brickschema.org/schema/Brick#` | Declared by the published Brick TTL (served file 1.4.1; latest release 1.4.4) | Correct |
| `efont: http://www.semanticweb.org/hlee9/ontologies/2021/4/EF-core#` | Exactly the namespace the published EFOnt TTL declares | Correct |
| `efont:allows`, `efont:enables`, `efont:Quantifies` | Exist with these spellings; `Quantifies` and `Characterizes` are capitalized in EFOnt itself | Correct |
| `efont:hasNetworkImpact`, `efont:providesFlexibility` (network-impact surrogate) | No such terms in EFOnt | **Fixed 2026-09-11** — local predicates `flexint:hasNetworkImpact` and `flexint:providesFlexibility` |
| `cim: http://iec.ch/TC57/CIM100#` | CGMES 3.0 and North American distribution tooling (GridAPPS-D, CIMHub) use it; ENTSO-E's Network Code Profiles use `https://cim.ucaiug.io/ns#` | **Decided 2026-09-11** — primary; the CIM18 spellings are ingest aliases mapped per term, never emitted |
| `ieee2030_5: https://standards.ieee.org/ieee/2030.5#` | Not a namespace (redirects to a site search); the XSD namespace is `urn:ieee:std:2030.5:ns` and IEEE publishes no RDF | **Removed 2026-09-11** |
| `ieee2030_5:EVSE` | No `EVSE` type in the 2013, 2018 or 2023 schemas | **Fixed 2026-09-11** — Brick's `Electric_Vehicle_Charging_Station`, crosswalked to a 2030.5 `EndDevice` with `PEVInfo` |
| `openadr: https://openadr.org/ns#` | Returns 404; the OpenADR Alliance publishes no RDF vocabulary | **Removed 2026-09-11** — it was declared but never emitted |
| `dt:`, `cls:` on `gridalyn.local` | Not dereferenceable | **Fixed 2026-09-11** — `dt:` and `flexint:` (which replaces `cls:`) under `https://w3id.org/gridalyn/ontology/`; `cls:` terms are deprecated aliases for one release |
| Topology shortcut predicates `dt:connects`, `dt:connectedTo`, `dt:feeds` | CGMES serializes `Terminal.ConductingEquipment` and `Terminal.ConnectivityNode`; the graph collapses the `Terminal` | Correct as documented local shortcuts |

## IEC CIM

- CGMES 3.0 (IEC 61970-600:2021, on CIM17) declares `http://iec.ch/TC57/CIM100#`
  in all of its RDFS files; ENTSO-E's Network Code Profiles declare
  `https://cim.ucaiug.io/ns#`. Source:
  [ENTSO-E Application Profiles Library](https://github.com/entsoe/application-profiles-library).
- `Terminal.ConnectivityNode` (multiplicity 0..1) and `Terminal.ConductingEquipment`
  (multiplicity 1) are the association ends CGMES exchanges
  (`AssociationUsed=Yes`). Their inverses `ConnectivityNode.Terminals` and
  `ConductingEquipment.Terminals` are valid CIM roles but are not exchanged.
- Not established: which CIM release first used `cim.ucaiug.io`.

## EFOnt

- Li, H.; Hong, T. "A semantic ontology for representing and quantifying energy
  flexibility of buildings". *Advances in Applied Energy* 8 (2022) 100113,
  [doi:10.1016/j.adapen.2022.100113](https://doi.org/10.1016/j.adapen.2022.100113).
- Published file:
  [LBNL-ETA/EnergyFlexibilityOntology](https://github.com/LBNL-ETA/EnergyFlexibilityOntology),
  file EFOnt.ttl in its ontology directory. **The repository declares no licence**
  — check before redistributing EFOnt content.
- `allows`: domain `FlexibilityResources`, range `FlexibleOperation`.
  `enables`: domain `FlexibleOperation`, range `EnergyFlexibility`.
  `Quantifies`: domain `EnergyFlexibilityKPI`, range `EnergyFlexibility`.
  `Characterizes`: domain `FlexibleLoadCharacteristic`, range `FlexibleOperation`.

## IEEE 2030.5

- Official schema packages:
  [IEEE SA downloads](https://standards.ieee.org/downloads/). XSD target
  namespace `urn:ieee:std:2030.5:ns` in the 2018 (schema 2.1.0) and 2023
  (schema 2.2) packages; `http://zigbee.org/sep` in 2013.
- Names relevant to EV charging and DER control (2018 schema): `EndDevice`,
  `PEVInfo`, `FlowReservationRequest`, `FlowReservationResponse`,
  `DemandResponseProgram`, `EndDeviceControl`, `DERProgram`, `DERControl`,
  `DER`, `DERCapability`, `DERSettings`, `DERStatus`, `DERAvailability`.

## OpenADR 3

- Current release **3.1.0** (Definitions document dated 2025-08-07), declared
  **not backward compatible** with 3.0.1. The Alliance's own repository is
  gated; the public mirror is
  [grid-coordination/openadr3-specification](https://github.com/grid-coordination/openadr3-specification).
  Distribution and terms: [openadr.org/specification](https://www.openadr.org/specification).
- Object types: `PROGRAM`, `EVENT`, `REPORT`, `SUBSCRIPTION`, `VEN`, `RESOURCE`.
- Parties, from the OAuth2 scopes in the 3.1.0 `openadr3.yaml`: the VTN is the
  server, and its clients are the business logic, `BL` ("Only BL can write to
  programs", "Only BL can write to events"), and the `VEN`s ("VENs and BL can
  write to subscriptions").
- `program` (3.1.0): `programName` (required), `intervalPeriod`,
  `programDescriptions`, `payloadDescriptors`, `attributes`, `targets`. The 3.0.1
  direct fields (`programLongName`, `retailerName`, `programType`,
  `bindingEvents`, `localPrice`, …) moved into `attributes` value-map types.
- `event` (3.1.0): `programID` (required), `eventName`, `duration` (new),
  `priority`, `targets`, `reportDescriptors`, `payloadDescriptors`,
  `intervalPeriod`, `intervals`.
- `report` (3.1.0): `clientID`, `eventID`, `clientName`, `resources` (all
  required), `reportName`, `payloadDescriptors`; `programID` was removed.
- `intervalPeriod`: `start`, `duration`, `randomizeStart`. `payloadType` is an
  open string with defined values (38 event types, 24 report types in 3.1.0).
- `priority` is an integer ≥ 0; **0 is the highest priority**.
- **Not in OpenADR 3.1.0**, and therefore extensions whenever a gridalyn
  protocol needs them:
    - *cancellation* — the User Guide says to delete the event, or set its start
      to `0001-01-01` and duration to `PT0S`;
    - *opt-out* — present only as the `IDLE_OPTED_OUT` / `RUNNING_OPTED_OUT`
      values of the `OPERATING_STATE` report payload;
    - *lead time / notice* — "notification" in 3.x means subscription
      notifications, not advance notice.
- OpenADR 2.0b: XML namespace `http://openadr.org/oadr-2.0b/2012/07`; approved as
  IEC 62746-10-1 Ed. 1 (2018). A third-party, 2.0-era academic ontology exists at
  `https://w3id.org/def/openadr`; it is not an Alliance product.

## USEF and UFTP

- Latest framework document: *USEF: The Framework Explained*, update of
  25 May 2021 ([usef.energy](https://www.usef.energy/download-the-framework/)).
  The USEF Foundation states it is no longer active.
- Roles (2021 names): Active Customer (formerly Prosumer), Aggregator (AGR),
  Supplier, BRP, DSO, TSO, Producer, ESCo, Trader, Exchange, CRO, MDR (formerly
  MDC), ISR (formerly ARP), BSP, CMSP, CSP; FRP generalizes BRP, DSO and TSO.
  USEF "does not prescribe a single business model but rather a role model", and
  the Aggregator role "can be taken by either existing market parties … or new
  entrants" (§2.1.2, §2.1.4).
- Market coordination phases: Contract, Plan, Validate, Operate, Settle.
- UFTP **3.1.0** (released 2025-11-27), maintained by the LF Energy project
  Shapeshifter:
  [shapeshifter/shapeshifter-specification](https://github.com/shapeshifter/shapeshifter-specification).
  Messages include `FlexReservationUpdate`, `D-Prognosis` (with the hyphen),
  `FlexRequest`, `FlexOffer`, `FlexOfferRevocation`, `FlexOrder`, `Metering`,
  `FlexSettlement`, the portfolio update and query messages and `TestMessage`,
  each with a `…Response`. The UFTP schemas declare **no XML namespace**, so any
  IRI for a UFTP message is necessarily gridalyn's own.

## S2 and SAREF4ENER

- S2 is EN 50491-12-2:2022. JSON schemas:
  [flexiblepower/s2-json](https://github.com/flexiblepower/s2-json) v1.0.0.
  Roles: CEM (Customer Energy Manager) and RM (Resource Manager). Control types:
  `POWER_ENVELOPE_BASED_CONTROL`, `POWER_PROFILE_BASED_CONTROL`,
  `OPERATION_MODE_BASED_CONTROL`, `FILL_RATE_BASED_CONTROL`,
  `DEMAND_DRIVEN_BASED_CONTROL`, `NOT_CONTROLABLE` (sic), `NO_SELECTION`. Use the
  enum values: the schema's descriptions for fill-rate and demand-driven control
  are swapped.
- SAREF4ENER v2.1.1 (2025-06-05, ETSI TS 103 410-1 V2.1.1): namespace
  `https://saref.etsi.org/saref4ener/` (trailing slash, no `#`), preferred prefix
  `s4ener`. Declares `PowerProfile`, `AlternativesGroup`, `PowerSequence`,
  `Slot` and `FlexibilityProfile`. Source:
  [saref.etsi.org/saref4ener](https://saref.etsi.org/saref4ener/).

## FIPA ACL

FIPA Communicative Act Library Specification SC00037J (Standard, 2002-12-03)
defines 22 acts: `accept-proposal`, `agree`, `cancel`, `cfp`, `confirm`,
`disconfirm`, `failure`, `inform`, `inform-if`, `inform-ref`, `not-understood`,
`propagate`, `propose`, `proxy`, `query-if`, `query-ref`, `refuse`,
`reject-proposal`, `request`, `request-when`, `request-whenever`, `subscribe`.

The `fipa.org` domain no longer hosts FIPA; cite the
[archived specification](https://web.archive.org/web/20060924061057/http://www.fipa.org/specs/fipa00037/SC00037J.pdf)
and never link the live domain.

## How the interaction protocols use these

`gridalyn.operations.interaction` keeps roles apart from parties. Each role is
aligned to the standards above, with a dash where a standard has no such role:

| gridalyn role | USEF 2021 | OpenADR 3.1.0 |
| --- | --- | --- |
| `distribution_operator` | DSO | — |
| `aggregator` | AGR | VEN |
| `program_administrator` | — | BL |
| `active_customer` | Active Customer | VEN |

`flex_trading` uses UFTP 3.1.0 message names; its payloads are gridalyn's own
offer, dispatch and settlement records, not UFTP attributes. The acts follow
FIPA's contract-net shape. UFTP has no message that rejects an offer, so an
offer that is not ordered stays `offered`.

| Message | Act | From → to |
| --- | --- | --- |
| `FlexRequest` | `cfp` | DSO → AGR |
| `FlexOffer` | `propose` | AGR → DSO |
| `FlexOfferRevocation` | `cancel` | AGR → DSO |
| `FlexOrder` | `accept-proposal` | DSO → AGR |
| `FlexSettlement` | `inform` | DSO → AGR |

`dr_program` follows one OpenADR 3.1.0 `event` between the business logic and
one VEN. The payload fields are 3.1.0's, verbatim. What 3.1.0 lacks is an
extension with the `flexint:` prefix, and the protocol refuses to label it
otherwise:

| Message | Act | From → to | Origin |
| --- | --- | --- | --- |
| `event` | `inform` | BL → VEN | OpenADR 3.1.0 |
| `report` | `inform` | VEN → BL | OpenADR 3.1.0 |
| `flexint:EventCancellation` | `cancel` | BL → VEN | extension |
| `flexint:OptOut` | `refuse` | VEN → BL | extension |

The event payload's `flexint:activeFrom` and `flexint:activeUntil` carry the
event window in simulated time. The conversation becomes `active` and then
`completed` as its clock passes them, and the notice the event gave is
`flexint:activeFrom` minus the time the event was sent.

## Persistent IRIs for gridalyn's own namespaces

**Adopted 2026-09-11.** `dt:` and `cls:` sat on a `.local` host and could not
be dereferenced. gridalyn's own vocabularies now live under
`https://w3id.org/gridalyn/ontology/`: `dt:` at
`https://w3id.org/gridalyn/ontology/digital-twin#`, and `flexint:`, which
replaces `cls:`, at `https://w3id.org/gridalyn/ontology/flexint#`. Each is
generated from its declarations by `tools/export_ontology.py` into a reference
page — [Digital-Twin Vocabulary](./ontology/digital-twin.md),
[Flexint Vocabulary](./ontology/flexint.md) — and a Turtle file under
`docs/ontology/`; `tests/test_ontology_documents.py` fails when either is stale.
The Turtle marks every retired `cls:` term `owl:deprecated`, with
`dcterms:isReplacedBy` naming its replacement.

The [w3id.org](https://github.com/perma-id/w3id.org) process is a pull request
that adds a directory under the repository's ids directory with an `.htaccess`
(redirect rules) and a
`README.md` with contact information. Across its 59 most recently merged pull
requests the median time to merge was 3.2 hours (measured 2026-09-10). Because
the documentation site is served by GitHub Pages, which does no content
negotiation, HTML and Turtle requests are redirected to distinct files by the
w3id `.htaccess` itself: a 303 to the Turtle file when the `Accept` header asks
for Turtle, and to the reference page otherwise. gridalyn's rules and README
are kept in `tools/w3id/gridalyn/` and are submitted once the pages they point
at are published; until that pull request is merged, the IRIs are stable names
that do not yet resolve. [purl.archive.org](https://purl.archive.org/) is the
fallback.

## Not confirmed from a primary source

- A single USEF sentence stating that roles are distinct from parties (the
  principle is carried by the statements quoted above).
- That USEF moved to LF Energy in 2021; GOPACS's relation to UFTP.
- Which CIM release introduced `cim.ucaiug.io`.
- The universal absence of any official OpenADR or IEEE 2030.5 RDF vocabulary
  (checked only against the spec pages and download packages).
- EN 50491-12-2:2022 in CENELEC's own catalogue, and a formal expansion table
  for the S2 control-type acronyms.
- GitHub's own documentation of the Pages content-negotiation limit.

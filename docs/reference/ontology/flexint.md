# gridalyn flexibility and interaction vocabulary

Curtailment contracts, flexibility aggregators, portfolios, providers, offers and constraint zones, and the predicates of the network-impact surrogate graph.

- **Namespace:** `https://w3id.org/gridalyn/ontology/flexint#` (prefix `flexint:`)
- **Turtle:** [flexint.ttl](../../ontology/flexint.ttl)
- **Generated** from the declarations in `gridalyn/twin/semantic/` by `tools/export_ontology.py`, and held to them by `tests/test_ontology_documents.py`; edit the declarations, not this page.

## Classes

| Class | IRI |
| --- | --- |
| <a id="Agent"></a>`flexint:Agent` | `https://w3id.org/gridalyn/ontology/flexint#Agent` |
| <a id="ConstraintZone"></a>`flexint:ConstraintZone` | `https://w3id.org/gridalyn/ontology/flexint#ConstraintZone` |
| <a id="Conversation"></a>`flexint:Conversation` | `https://w3id.org/gridalyn/ontology/flexint#Conversation` |
| <a id="CurtailmentContract"></a>`flexint:CurtailmentContract` | `https://w3id.org/gridalyn/ontology/flexint#CurtailmentContract` |
| <a id="DemandResponseEvent"></a>`flexint:DemandResponseEvent` | `https://w3id.org/gridalyn/ontology/flexint#DemandResponseEvent` |
| <a id="DemandResponseProgram"></a>`flexint:DemandResponseProgram` | `https://w3id.org/gridalyn/ontology/flexint#DemandResponseProgram` |
| <a id="FlexibilityAggregator"></a>`flexint:FlexibilityAggregator` | `https://w3id.org/gridalyn/ontology/flexint#FlexibilityAggregator` |
| <a id="FlexibilityOffer"></a>`flexint:FlexibilityOffer` | `https://w3id.org/gridalyn/ontology/flexint#FlexibilityOffer` |
| <a id="FlexibilityPortfolio"></a>`flexint:FlexibilityPortfolio` | `https://w3id.org/gridalyn/ontology/flexint#FlexibilityPortfolio` |
| <a id="FlexibilityProvider"></a>`flexint:FlexibilityProvider` | `https://w3id.org/gridalyn/ontology/flexint#FlexibilityProvider` |
| <a id="Party"></a>`flexint:Party` | `https://w3id.org/gridalyn/ontology/flexint#Party` |
| <a id="Role"></a>`flexint:Role` | `https://w3id.org/gridalyn/ontology/flexint#Role` |

## Properties

| Property | Domain | Range | Relationship | Note |
| --- | --- | --- | --- | --- |
| <a id="actsFor"></a>`flexint:actsFor` | `flexint:Agent` | `flexint:Party` | `ACTS_FOR` | An agent acts for exactly one party; a party holds several agents, which is the Hydro-Quebec case the role model exists for. |
| <a id="aggregates"></a>`flexint:aggregates` | `flexint:FlexibilityAggregator` | `flexint:FlexibilityProvider` | `AGGREGATES` | — |
| <a id="constraintZoneFor"></a>`flexint:constraintZoneFor` | `flexint:ConstraintZone` | `cim:ACLineSegment` / `cim:ConnectivityNode` / `cim:PowerTransformer` | `CONSTRAINT_ZONE_FOR` | — |
| <a id="describesFlexibility"></a>`flexint:describesFlexibility` | `flexint:CurtailmentContract` | `efont:EnergyFlexibility` | `DESCRIBES_FLEXIBILITY` | — |
| <a id="enablesContract"></a>`flexint:enablesContract` | `brick:Electric_Vehicle_Charging_Station` | `flexint:CurtailmentContract` | `ENABLES_CONTRACT` | Until 2026-09-10 the EVSE-to-Hard-CLS edge shared the label ENABLES with EFOnt's operation-to-flexibility property while meaning something else, and carried cls:enables. |
| <a id="followsEvent"></a>`flexint:followsEvent` | `flexint:Conversation` | `flexint:DemandResponseEvent` | `FOLLOWS_EVENT` | — |
| <a id="hasNetworkImpact"></a>`flexint:hasNetworkImpact` | — | — | — | Declared for a graph other than the semantic graph: the network-impact surrogate's edges. |
| <a id="implementsContract"></a>`flexint:implementsContract` | `flexint:FlexibilityProvider` | `flexint:CurtailmentContract` | `IMPLEMENTS_CONTRACT` | — |
| <a id="includesProvider"></a>`flexint:includesProvider` | `flexint:FlexibilityPortfolio` | `flexint:FlexibilityProvider` | `INCLUDES_PROVIDER` | — |
| <a id="locatedInConstraintZone"></a>`flexint:locatedInConstraintZone` | `flexint:FlexibilityProvider` | `flexint:ConstraintZone` | `LOCATED_IN_CONSTRAINT_ZONE` | — |
| <a id="managesPortfolio"></a>`flexint:managesPortfolio` | `flexint:FlexibilityAggregator` | `flexint:FlexibilityPortfolio` | `MANAGES_PORTFOLIO` | — |
| <a id="offers"></a>`flexint:offers` | `flexint:FlexibilityProvider` | `flexint:FlexibilityOffer` | `OFFERS` | — |
| <a id="participatesIn"></a>`flexint:participatesIn` | `brick:Building` | `flexint:CurtailmentContract` | `PARTICIPATES_IN` | — |
| <a id="participatesInConversation"></a>`flexint:participatesInConversation` | `flexint:Agent` | `flexint:Conversation` | `PARTICIPATES_IN_CONVERSATION` | — |
| <a id="playsRole"></a>`flexint:playsRole` | `flexint:Agent` | `flexint:Role` | `PLAYS_ROLE` | Unconstrained on purpose: the log is the authority, and an agent observed sending under two roles is data to see, not a violation. |
| <a id="providesFlexibility"></a>`flexint:providesFlexibility` | — | — | — | Declared for a graph other than the semantic graph: the network-impact surrogate's edges. |
| <a id="schedulesEvent"></a>`flexint:schedulesEvent` | `flexint:DemandResponseProgram` | `flexint:DemandResponseEvent` | `SCHEDULES_EVENT` | — |
| <a id="targetsConstraint"></a>`flexint:targetsConstraint` | `flexint:FlexibilityOffer` | `flexint:ConstraintZone` | `TARGETS_CONSTRAINT` | — |

## Formerly written as

These terms were emitted before 2026-09-11. Each still resolves, for one release, through `resolve_deprecated_term` in `gridalyn/twin/semantic/profile.py`.

| Deprecated term | Replacement | Replacement carries | Why |
| --- | --- | --- | --- |
| `cls:ConstraintZone` | `flexint:ConstraintZone` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:FlexibilityAggregator` | `flexint:FlexibilityAggregator` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:FlexibilityOffer` | `flexint:FlexibilityOffer` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:FlexibilityPortfolio` | `flexint:FlexibilityPortfolio` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:FlexibilityProvider` | `flexint:FlexibilityProvider` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:HardCLSContract` | `flexint:CurtailmentContract` | `contract_mode` = `hard` | the Soft/Hard distinction is the contract_mode property, not a class; the acronym the class name encoded was defined nowhere |
| `cls:SoftCLSContract` | `flexint:CurtailmentContract` | `contract_mode` = `soft` | the Soft/Hard distinction is the contract_mode property, not a class; the acronym the class name encoded was defined nowhere |
| `cls:aggregates` | `flexint:aggregates` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:constraintZoneFor` | `flexint:constraintZoneFor` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:describesFlexibility` | `flexint:describesFlexibility` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:enablesContract` | `flexint:enablesContract` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:implementsContract` | `flexint:implementsContract` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:includesProvider` | `flexint:includesProvider` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:locatedInConstraintZone` | `flexint:locatedInConstraintZone` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:managesPortfolio` | `flexint:managesPortfolio` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:offers` | `flexint:offers` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:participatesIn` | `flexint:participatesIn` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `cls:targetsConstraint` | `flexint:targetsConstraint` | — | moved from the unresolvable gridalyn.local cls: namespace to the persistent flexint: namespace, unchanged otherwise |
| `efont:hasNetworkImpact` | `flexint:hasNetworkImpact` | — | EFOnt defines no hasNetworkImpact property |
| `efont:providesFlexibility` | `flexint:providesFlexibility` | — | EFOnt defines no providesFlexibility property |
| `ieee2030_5:EVSE` | `brick:Electric_Vehicle_Charging_Station` | — | IEEE 2030.5 defines no EVSE type and publishes no RDF namespace; Brick defines the class |

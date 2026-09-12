"""gridalyn's own vocabularies as published documents: a reference page and Turtle.

The IRIs gridalyn mints -- ``dt:`` and ``flexint:`` under
:data:`~gridalyn.twin.semantic.profile.GRIDALYN_ONTOLOGY_BASE` -- are only
persistent if something answers at them. w3id.org redirects each vocabulary
IRI to two files on the documentation site: an HTML page for a browser and a
Turtle file for an RDF client. Both are generated here from the declarations
themselves -- the model-first core and every registered capability -- and
``tests/test_ontology_documents.py`` holds the committed copies to this
generator, so the published vocabulary cannot drift from the one the graph
emits.

No RDF library: the Turtle is written as text, the way the graph itself is
written as parquet. ``rdflib`` is deliberately not a dependency.

Domain and range are published as ``schema:domainIncludes`` and
``schema:rangeIncludes``, not ``rdfs:domain``/``rdfs:range``: a relationship
here may start at several unrelated classes, and ``rdfs:domain`` would assert
that every subject belongs to *all* of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gridalyn.twin.semantic.profile import (
    DEPRECATED_NAMESPACES,
    GRIDALYN_ONTOLOGY_BASE,
    profile_with_capabilities,
)
from gridalyn.twin.semantic.registry import default_semantic_capability_registry

#: Where the documentation site publishes each vocabulary's page and Turtle file.
DOCUMENTATION_SITE = "https://lirei.ca/gridalyn/"

#: The source repository, linked from every vocabulary.
REPOSITORY_URL = "https://github.com/lirei-lab/gridalyn"

#: The date the persistent vocabularies replaced ``gridalyn.local``.
PERSISTENT_SINCE = "2026-09-11"

_STANDARD_PREFIXES: dict[str, str] = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "dcterms": "http://purl.org/dc/terms/",
    "schema": "https://schema.org/",
}

#: Retired prefixes whose namespace gridalyn itself owned, so a deprecation
#: triple about their terms is gridalyn's to publish.
_OWNED_RETIRED_PREFIXES: frozenset[str] = frozenset({"cls", "dt"})


@dataclass(frozen=True)
class OntologyDocument:
    """One vocabulary gridalyn defines, as a published document.

    Attributes:
        document_id: Path segment under the ontology base, e.g. ``flexint``.
        prefix: The qname prefix its terms carry.
        title: Human-readable name.
        description: What the vocabulary covers.
        alias_declarers: Capabilities whose deprecated aliases this document
            lists.
    """

    document_id: str
    prefix: str
    title: str
    description: str
    alias_declarers: tuple[str, ...] = ()

    @property
    def iri(self) -> str:
        """Return the vocabulary IRI, without its fragment separator."""
        return f"{GRIDALYN_ONTOLOGY_BASE}{self.document_id}"

    @property
    def namespace(self) -> str:
        """Return the hash namespace the vocabulary's terms are minted in."""
        return f"{self.iri}#"

    @property
    def page_url(self) -> str:
        """Return the documentation page w3id.org redirects a browser to."""
        return f"{DOCUMENTATION_SITE}reference/ontology/{self.document_id}/"

    @property
    def turtle_url(self) -> str:
        """Return the Turtle file w3id.org redirects an RDF client to."""
        return f"{DOCUMENTATION_SITE}ontology/{self.document_id}.ttl"


ONTOLOGY_DOCUMENTS: tuple[OntologyDocument, ...] = (
    OntologyDocument(
        document_id="digital-twin",
        prefix="dt",
        title="gridalyn digital-twin vocabulary",
        description=(
            "Scenarios, simulation runs, time-series datasets, scenario devices and "
            "the local topology shortcuts of gridalyn's model-first semantic graph."
        ),
    ),
    OntologyDocument(
        document_id="flexint",
        prefix="flexint",
        title="gridalyn flexibility and interaction vocabulary",
        description=(
            "Curtailment contracts, flexibility aggregators, portfolios, providers, "
            "offers and constraint zones, and the predicates of the network-impact "
            "surrogate graph."
        ),
        alias_declarers=("flexibility",),
    ),
)


@dataclass(frozen=True)
class _Property:
    qname: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    relationships: tuple[str, ...]
    notes: tuple[str, ...]


def list_ontology_documents() -> tuple[OntologyDocument, ...]:
    """Return every vocabulary gridalyn publishes."""
    return ONTOLOGY_DOCUMENTS


def _document(document_id: str) -> OntologyDocument:
    for document in ONTOLOGY_DOCUMENTS:
        if document.document_id == document_id:
            return document
    known = ", ".join(document.document_id for document in ONTOLOGY_DOCUMENTS)
    raise KeyError(f"unknown ontology document {document_id!r} (known: {known})")


def _full_profile(document: OntologyDocument) -> dict[str, Any]:
    registry = default_semantic_capability_registry()
    profile = profile_with_capabilities(set(registry.list_ids()))
    bound = profile["namespaces"].get(document.prefix)
    if bound != document.namespace:
        raise ValueError(
            f"ontology document {document.document_id!r} publishes "
            f"{document.namespace}, but the profile binds {document.prefix}: to "
            f"{bound}; the document IRI and the namespace must agree"
        )
    return profile


def _classes(document: OntologyDocument, profile: Mapping[str, Any]) -> list[str]:
    marker = f"{document.prefix}:"
    return sorted(
        qname for qname in profile["allowed_semantic_types"] if qname.startswith(marker)
    )


def _properties(
    document: OntologyDocument, profile: Mapping[str, Any]
) -> list[_Property]:
    marker = f"{document.prefix}:"
    collected: dict[str, dict[str, set[str]]] = {}
    for name, spec in profile["relationships"].items():
        if not spec["predicate"].startswith(marker):
            continue
        entry = collected.setdefault(
            spec["predicate"],
            {"domain": set(), "range": set(), "relationships": set(), "notes": set()},
        )
        entry["domain"].update(spec["domain"])
        entry["range"].update(spec["range"])
        entry["relationships"].add(name)
        if spec.get("note"):
            entry["notes"].add(spec["note"])
    for qname in profile.get("predicates", []):
        if qname.startswith(marker):
            collected.setdefault(
                qname,
                {
                    "domain": set(),
                    "range": set(),
                    "relationships": set(),
                    "notes": {
                        "Declared for a graph other than the semantic graph: the "
                        "network-impact surrogate's edges."
                    },
                },
            )
    return [
        _Property(
            qname=qname,
            domain=tuple(sorted(entry["domain"])),
            range=tuple(sorted(entry["range"])),
            relationships=tuple(sorted(entry["relationships"])),
            notes=tuple(sorted(entry["notes"])),
        )
        for qname, entry in sorted(collected.items())
    ]


def _aliases(
    document: OntologyDocument, profile: Mapping[str, Any]
) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (deprecated, alias)
        for deprecated, alias in sorted(profile["deprecated_aliases"].items())
        if alias["declared_by"] in document.alias_declarers
    ]


def _literal(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return '"' + escaped + '"'


def _statement_block(subject: str, statements: list[str]) -> list[str]:
    """Render one Turtle subject with its predicate-object pairs."""
    lines = [f"{subject} {statements[0]} ;"]
    lines.extend(f"    {statement} ;" for statement in statements[1:-1])
    lines.append(f"    {statements[-1]} .")
    return ["", *lines] if len(statements) > 1 else ["", f"{subject} {statements[0]} ."]


def _prefix_lines(
    document: OntologyDocument,
    properties: list[_Property],
    profile: Mapping[str, Any],
) -> list[str]:
    used = {document.prefix}
    for prop in properties:
        used.update(qname.partition(":")[0] for qname in (*prop.domain, *prop.range))
    prefixes = dict(_STANDARD_PREFIXES)
    for prefix in sorted(used):
        prefixes[prefix] = profile["namespaces"][prefix]
    return [f"@prefix {prefix}: <{iri}> ." for prefix, iri in prefixes.items()]


def _property_statements(prop: _Property, document: OntologyDocument) -> list[str]:
    statements = [
        "a owl:ObjectProperty",
        f"rdfs:label {_literal(prop.qname.partition(':')[2])}",
        f"rdfs:isDefinedBy <{document.iri}>",
    ]
    statements.extend(f"schema:domainIncludes {qname}" for qname in prop.domain)
    statements.extend(f"schema:rangeIncludes {qname}" for qname in prop.range)
    statements.extend(f"rdfs:comment {_literal(note)}" for note in prop.notes)
    return statements


def _alias_block(deprecated: str, alias: Mapping[str, Any]) -> list[str]:
    prefix, _, local_name = deprecated.partition(":")
    if prefix not in _OWNED_RETIRED_PREFIXES:
        return []
    statements = [
        "owl:deprecated true",
        f"dcterms:isReplacedBy {alias['replacement']}",
    ]
    statements.extend(
        f"rdfs:comment {_literal(f'The replacement carries {key} = {value}.')}"
        for key, value in sorted(alias["properties"].items())
    )
    if alias.get("note"):
        statements.append(f"rdfs:comment {_literal(alias['note'])}")
    iri = f"<{DEPRECATED_NAMESPACES[prefix]}{local_name}>"
    return _statement_block(iri, statements)


def build_ontology_turtle(document_id: str) -> str:
    """Build the Turtle file of one vocabulary from the declarations.

    Args:
        document_id: The vocabulary, e.g. ``flexint``.

    Returns:
        The Turtle text: the ontology header, every class and property the
        vocabulary defines, and a deprecation statement for every retired term
        of a namespace gridalyn owned.

    Raises:
        KeyError: ``document_id`` names no published vocabulary.
        ValueError: The document IRI and the profile's namespace disagree.
    """
    document = _document(document_id)
    profile = _full_profile(document)
    properties = _properties(document, profile)
    lines = _prefix_lines(document, properties, profile)
    lines.extend(
        _statement_block(
            f"<{document.iri}>",
            [
                "a owl:Ontology",
                f"rdfs:label {_literal(document.title)}",
                f"rdfs:comment {_literal(document.description)}",
                f"rdfs:seeAlso <{document.page_url}>, <{REPOSITORY_URL}>",
            ],
        )
    )
    for qname in _classes(document, profile):
        lines.extend(
            _statement_block(
                qname,
                [
                    "a owl:Class",
                    f"rdfs:label {_literal(qname.partition(':')[2])}",
                    f"rdfs:isDefinedBy <{document.iri}>",
                ],
            )
        )
    for prop in properties:
        lines.extend(_statement_block(prop.qname, _property_statements(prop, document)))
    for deprecated, alias in _aliases(document, profile):
        lines.extend(_alias_block(deprecated, alias))
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _anchor(local_name: str) -> str:
    """Return the HTML anchor a hash IRI's fragment lands on."""
    return '<a id="' + local_name + '"></a>'


def _codes(qnames: tuple[str, ...]) -> str:
    return " / ".join(f"`{qname}`" for qname in qnames) or "—"


def _class_section(document: OntologyDocument, classes: list[str]) -> list[str]:
    lines = ["", "## Classes", ""]
    if not classes:
        return [*lines, "This vocabulary defines no classes."]
    lines.extend(["| Class | IRI |", "| --- | --- |"])
    for qname in classes:
        local_name = qname.partition(":")[2]
        lines.append(
            f"| {_anchor(local_name)}`{qname}` | `{document.namespace}{local_name}` |"
        )
    return lines


def _property_section(properties: list[_Property]) -> list[str]:
    lines = ["", "## Properties", ""]
    if not properties:
        return [*lines, "This vocabulary defines no properties."]
    lines.extend(
        [
            "| Property | Domain | Range | Relationship | Note |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for prop in properties:
        local_name = prop.qname.partition(":")[2]
        relationships = _codes(prop.relationships)
        note = _cell(" ".join(prop.notes)) or "—"
        lines.append(
            f"| {_anchor(local_name)}`{prop.qname}` | {_codes(prop.domain)} | "
            f"{_codes(prop.range)} | {relationships} | {note} |"
        )
    return lines


def _alias_section(aliases: list[tuple[str, Mapping[str, Any]]]) -> list[str]:
    if not aliases:
        return []
    lines = [
        "",
        "## Formerly written as",
        "",
        f"These terms were emitted before {PERSISTENT_SINCE}. Each still resolves, "
        "for one release, through `resolve_deprecated_term` in "
        "`gridalyn/twin/semantic/profile.py`.",
        "",
        "| Deprecated term | Replacement | Replacement carries | Why |",
        "| --- | --- | --- | --- |",
    ]
    for deprecated, alias in aliases:
        carries = (
            ", ".join(
                f"`{key}` = `{value}`"
                for key, value in sorted(alias["properties"].items())
            )
            or "—"
        )
        lines.append(
            f"| `{deprecated}` | `{alias['replacement']}` | {carries} | "
            f"{_cell(alias.get('note') or '—')} |"
        )
    return lines


def build_ontology_page(document_id: str) -> str:
    """Build the reference page of one vocabulary from the declarations.

    Every term gets an HTML anchor named by its local name, so a hash IRI such
    as ``https://w3id.org/gridalyn/ontology/flexint#CurtailmentContract``
    lands on its own row once w3id.org redirects to this page.

    Args:
        document_id: The vocabulary, e.g. ``flexint``.

    Returns:
        The page as Markdown.

    Raises:
        KeyError: ``document_id`` names no published vocabulary.
        ValueError: The document IRI and the profile's namespace disagree.
    """
    document = _document(document_id)
    profile = _full_profile(document)
    lines = [
        f"# {document.title}",
        "",
        document.description,
        "",
        f"- **Namespace:** `{document.namespace}` (prefix `{document.prefix}:`)",
        f"- **Turtle:** [{document.document_id}.ttl]"
        f"(../../ontology/{document.document_id}.ttl)",
        "- **Generated** from the declarations in `gridalyn/twin/semantic/` by "
        "`tools/export_ontology.py`, and held to them by "
        "`tests/test_ontology_documents.py`; edit the declarations, not this page.",
    ]
    lines.extend(_class_section(document, _classes(document, profile)))
    lines.extend(_property_section(_properties(document, profile)))
    lines.extend(_alias_section(_aliases(document, profile)))
    return "\n".join(lines) + "\n"


__all__ = [
    "DOCUMENTATION_SITE",
    "ONTOLOGY_DOCUMENTS",
    "PERSISTENT_SINCE",
    "REPOSITORY_URL",
    "OntologyDocument",
    "build_ontology_page",
    "build_ontology_turtle",
    "list_ontology_documents",
]

#!/usr/bin/env python3
"""Write, or check, the published documents of gridalyn's own vocabularies.

Each vocabulary gridalyn defines (``dt:``, ``flexint:``) is published as a
reference page and a Turtle file, which w3id.org redirects its persistent IRI
to. Both are generated from the declarations in ``gridalyn/twin/semantic/`` by
:mod:`gridalyn.twin.semantic.ontology`; this tool writes them into ``docs/``.

Usage:
    python tools/export_ontology.py            # write the documents
    python tools/export_ontology.py --check    # fail when a committed one is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import this checkout's gridalyn, not whichever one the environment installed:
# a worktree's editable install can point at another checkout.
sys.path.insert(0, str(REPO_ROOT))

from gridalyn.twin.semantic.ontology import (  # noqa: E402
    build_ontology_page,
    build_ontology_turtle,
    list_ontology_documents,
)


def document_files(root: Path = REPO_ROOT) -> dict[Path, str]:
    """Return every published document's path and its generated content.

    Args:
        root: Repository root the ``docs/`` paths are resolved under.

    Returns:
        ``docs/ontology/<id>.ttl`` and ``docs/reference/ontology/<id>.md`` for
        every vocabulary, mapped to what they must contain.
    """
    files: dict[Path, str] = {}
    for document in list_ontology_documents():
        document_id = document.document_id
        files[root / "docs" / "ontology" / f"{document_id}.ttl"] = (
            build_ontology_turtle(document_id)
        )
        files[root / "docs" / "reference" / "ontology" / f"{document_id}.md"] = (
            build_ontology_page(document_id)
        )
    return files


def main(argv: list[str] | None = None) -> int:
    """Write the documents, or with ``--check`` report the stale ones.

    Args:
        argv: Command-line arguments; ``sys.argv`` when omitted.

    Returns:
        0 when every document is current (or was written), 1 when ``--check``
        finds one that is missing or differs.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when a committed document is stale",
    )
    args = parser.parse_args(argv)
    stale: list[str] = []
    for path, content in document_files().items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == content:
            continue
        relative = str(path.relative_to(REPO_ROOT))
        if args.check:
            stale.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {relative}")
    if stale:
        print(
            "stale ontology documents (run python tools/export_ontology.py):\n  "
            + "\n  ".join(stale),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Extension 'hello_world' (role: 'data_source'), scaffolded by gridalyn extension new.

A conformant extension module: the engine reads ``descriptor`` (an
:class:`gridalyn.foundation.platform.extensions.ExtensionDescriptor`) and
``factory`` (a callable returning the role's component) when this extension is
resolved through the ``gridalyn.extensions`` entry-point group.
"""

from __future__ import annotations

from gridalyn.foundation.platform.extensions import ExtensionDescriptor

descriptor = ExtensionDescriptor(
    extension_id="hello_world",
    role="data_source",
    name="hello_world",
    version="0.1.0",
    contract_version="1",
)


def factory():
    """Return the role component this extension provides.

    Returns:
        The component the role expects; the scaffold provides a placeholder
        the extension author replaces with a real implementation.
    """
    return None

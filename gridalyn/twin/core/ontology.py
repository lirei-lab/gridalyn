from typing import Literal, Optional, Any
from pydantic import BaseModel, Field

class GridNodeBase(BaseModel):
    """Base class for all topological grid elements."""
    id: str
    x: float
    y: float
    type: str # The human readable arbitrary type e.g. 'lv_feeder', 'building'
    cluster: Optional[int] = None
    child: Optional[int] = None

class ConnectivityNode(GridNodeBase):
    """A standard connectivity bus in the power system."""
    cimclass: Literal["cim.ConnectivityNode"] = "cim.ConnectivityNode"
    vn_kv: Optional[float] = None # Nominal voltage
    
class EnergyConsumer(GridNodeBase):
    """A building or load consuming power from the grid."""
    cimclass: Literal["cim.EnergyConsumer"] = "cim.EnergyConsumer"
    p_mw: float = 0.0
    q_mvar: float = 0.0
    
class PowerTransformer(GridNodeBase):
    """A transformer stepping voltage down/up."""
    cimclass: Literal["cim.PowerTransformer"] = "cim.PowerTransformer"
    sn_mva: Optional[float] = None
    
# You can have validation factories
def create_node_payload(node_id: str, x: float, y: float, node_type: str, **kwargs: Any) -> dict:
    """Instantiate and validate a Node based on its physical type."""
    if node_type == "building":
        # Extract load safely
        load_kw = kwargs.pop("load_kw", 0.0)
        load_kvar = kwargs.pop("load_kvar", 0.0)
        p_mw = load_kw / 1000.0
        q_mvar = load_kvar / 1000.0
        
        node = EnergyConsumer(
            id=node_id, x=x, y=y, type=node_type, 
            p_mw=p_mw, q_mvar=q_mvar, **kwargs
        )
    elif node_type in ["lv_bus", "mv_bus", "hv_bus"]:
        node = ConnectivityNode(
            id=node_id, x=x, y=y, type=node_type, **kwargs
        )
    else:
        # Default fallback for intermediate nodes (like feeders)
        node = GridNodeBase(
            id=node_id, x=x, y=y, type=node_type, **kwargs
        )
        
    return node.model_dump(exclude={"id"}) # We exclude ID because networkx uses it as the key

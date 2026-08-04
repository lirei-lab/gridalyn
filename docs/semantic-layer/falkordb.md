# Advanced Power Grid Use Cases with FalkorDB

Now that your grid topology is mathematically mapped into a Graph Database using **openCypher**, you unlock a massive suite of operations that were previously very difficult or extremely slow using pure Python/NetworkX architectures.

Because FalkorDB runs as a sub-process engine specifically tuned for linear algebra (*GraphBLAS*), it serves as the perfect "Brain" to parse graph hierarchies before forwarding results to physics solvers like `pandapower`.

Here are the most powerful capabilities FalkorDB gives your `gridalyn` Digital Twin:

---

## 1. Fault Isolation & Outage Tracing (Microsecond Propagation)
When a breaker opens or a line faults, you need to instantly know exactly which buildings lose power to update the API or UI.

**Scenario:** A tree falls on `Feeder_Line_X`. What drops offline?

```cypher
MATCH (switch:Breaker {name: "SW_22"})-[*1..15]->(b:Building)
RETURN b.name, b.load_kw
```

> **Note**: Because FalkorDB uses sparse adjacency matrices, it doesn't execute a slow "loop" searching through Python objects. It performs a matrix multiplication $\mathbf{A}^x$ and returns the exact column indices of the disconnected buildings in fractions of a millisecond.

---

## 2. Dynamic Rerouting (Shortest Path / Tie-Switches)
If a primary feeder fails, operators look for "Tie-Switches" (normally open switches) to backfeed power from a neighboring substation. You can ask FalkorDB to find the optimal path to reconnect a stranded transformer.

**Scenario:** Find the shortest backup path from `Substation_B` to the stranded `Transformer_MV1`.

```cypher
MATCH p = shortestPath((sub:Substation {name: 'Substation_B'})-[*]-(t:Transformer {name: 'Trafo_MV1'}))
RETURN p, length(p) AS hops
```

> **Tip**: You can easily restrict algorithmic paths! Tell FalkorDB to ONLY traverse relationships where `status = "CLOSED"` or `status = "TIE"` to validate real-time reconfiguration logic.

---

## 3. Network Criticality Analysis (Algorithmic Centrality)
FalkorDB supports built-in advanced Graph Algorithms. You can identify the most "vulnerable" or "critical" pieces of infrastructure in your grid (bottleneck nodes).

**Scenario:** Which transformer, if it fails, causes the most cascading damage across the network?

```cypher
// Using standard betweenness centrality algorithms
CALL algo.betweenness() YIELD nodeId, centrality
MATCH (n) WHERE id(n) = nodeId
RETURN n.name, n.type, centrality
ORDER BY centrality DESC LIMIT 5
```

---

## 4. Multi-Domain Queries (GIS + Load Telemetry)
Because FalkorDB represents properties natively, you can easily combine Spatial Data (clustering zones) with Electrical Data (Voltage, kW).

**Scenario:** Find all heavily loaded transformers ($> 500$ kW) within a specific geographic cluster that have more than 50 downstream buildings attached.

```cypher
MATCH (t:Transformer {cluster: "Zone_A"})
WHERE t.load_kw > 500
MATCH (t)-[*1..3]->(b:Building)
WITH t, count(b) AS building_count
WHERE building_count > 50
RETURN t.name, t.load_kw, building_count
```

---

## 5. Semantic AI Integration (GraphRAG)
FalkorDB is heavily optimized for modern AI applications by supporting **Vector Indexing**. 

If you build a Digital Twin Copilot, an operator could "talk" to the grid using natural language (e.g., *"Show me the status of the northern feeders"*). FalkorDB evaluates the vector embeddings and instantly retrieves the exact transformers and their downstream telemetry, passing it perfectly into your Large Language Model's prompt window.

/**
 * Turn the ontology the catalog declares into something the map can draw.
 *
 * Nothing here names a class, an artifact, a column or a scenario. Every one
 * of those comes off `catalog.semantic`, which is the whole point: a class
 * added to the twin -- a new `ontology_class` value, a different profile, a
 * user's own adapter -- reaches the map without a dashboard edit, the same
 * property the scenario list already had.
 *
 * The columns in particular are DECLARED, not assumed. `entry.coordinates`
 * names the two columns holding a row's position and `entry.scenarioColumn`
 * names the one it is scoped by, so this module never writes `lat`, `lon` or
 * `scenario_id` as a literal.
 */

/** DuckDB alias `useDuckDB` registers a declared artifact under. */
export function artifactAlias(artifact) {
  return `${artifact}.parquet`;
}

/** Quote a SQL string literal, so a class name with an apostrophe is safe. */
function quote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

/** Quote a SQL identifier, so a column named like a keyword still resolves. */
function identifier(name) {
  return `"${String(name).replace(/"/g, '""')}"`;
}

/**
 * The classes that can actually be drawn, for one scenario.
 *
 * Two filters, both from what the twin said rather than from a preference:
 * `located` is the twin's statement that the rows carry coordinates, and the
 * scenario scope keeps one scenario's counts from being shown as another's.
 * A class with no scenario scope belongs to every scenario.
 */
export function drawableClasses(semantic, scenarioId = null) {
  return (semantic?.classes || []).filter(
    entry =>
      entry.located &&
      entry.coordinates &&
      (entry.scenarioId === null || entry.scenarioId === scenarioId)
  );
}

/**
 * Group drawable classes into one query per artifact.
 *
 * Per artifact rather than per class: the classes of one artifact differ only
 * in a column value, so a query each would read the same parquet N times.
 */
export function ontologySources(semantic, scenarioId = null) {
  const byArtifact = new Map();
  for (const entry of drawableClasses(semantic, scenarioId)) {
    const existing = byArtifact.get(entry.artifact);
    if (existing) {
      if (!existing.classes.includes(entry.name)) existing.classes.push(entry.name);
      continue;
    }
    byArtifact.set(entry.artifact, {
      artifact: entry.artifact,
      alias: artifactAlias(entry.artifact),
      column: entry.column,
      coordinates: entry.coordinates,
      identity: entry.identity,
      scenarioColumn: entry.scenarioColumn,
      scenarioId: entry.scenarioId,
      classes: [entry.name],
    });
  }
  return mostSpecific([...byArtifact.values()]);
}

/**
 * Keep one artifact per entity namespace: the most specific reading of it.
 *
 * Measured against the shipped twin: `buildings` and `asset_registry` BOTH key
 * on `building_id` and both are drawable, so querying both drew all 3235
 * buildings twice -- and drew a scenario's EV charging assets a second time,
 * underneath, as plain buildings from the base table. Two readings of the same
 * entities, stacked.
 *
 * The rule: two artifacts of one twin that key on the same declared identity
 * column describe the same entities, and a SCENARIO-SCOPED artifact is the
 * more specific reading of them. That is an inference the client makes, so it
 * is stated rather than buried -- and it is made from what the catalog
 * declares (`identity`, `scenarioColumn`), not from any artifact's name.
 *
 * The superseded classes are NOT hidden: `describeOntologyClasses` still lists
 * every class the twin declares. Only the map draws one reading at a time.
 */
function mostSpecific(sources) {
  const winner = new Map();
  for (const source of sources) {
    // An artifact with no declared identity cannot be matched to another, so
    // it is its own namespace and always kept.
    const namespace = source.identity || `artifact:${source.artifact}`;
    const held = winner.get(namespace);
    if (!held || (!held.scenarioColumn && source.scenarioColumn)) {
      winner.set(namespace, source);
    }
  }
  return sources.filter(source => [...winner.values()].includes(source));
}

/**
 * SQL reading one artifact's located, class-typed rows.
 *
 * The projection is renamed to a fixed shape -- `ontology_class`, `lon`, `lat`,
 * `entity_id` -- so the feature builder below is independent of how any twin
 * spells its columns.
 */
export function ontologySql(source) {
  const { latitude, longitude } = source.coordinates;
  const columns = [
    `${identifier(source.column)} AS ontology_class`,
    `${identifier(longitude)} AS lon`,
    `${identifier(latitude)} AS lat`,
    source.identity
      ? `${identifier(source.identity)} AS entity_id`
      : 'NULL AS entity_id',
  ];
  const where = [
    `${identifier(source.column)} IN (${source.classes.map(quote).join(', ')})`,
    `${identifier(longitude)} IS NOT NULL`,
    `${identifier(latitude)} IS NOT NULL`,
  ];
  // Only when the twin says the rows ARE scoped. Filtering an unscoped
  // artifact by a scenario would return nothing and look like an empty class.
  if (source.scenarioColumn && source.scenarioId !== null) {
    where.push(`${identifier(source.scenarioColumn)} = ${quote(source.scenarioId)}`);
  }
  return (
    `SELECT ${columns.join(', ')} FROM '${source.alias}' ` +
    `WHERE ${where.join(' AND ')}`
  );
}

/** Turn queried rows into the feature shape the layer registry draws. */
export function toOntologyFeatures(rows) {
  return rows.map(row => ({
    geometry: { coordinates: [Number(row.lon), Number(row.lat)] },
    properties: {
      ontology_class: row.ontology_class,
      entity_id: row.entity_id ?? null,
    },
  }));
}

/**
 * What a legend should say about the twin's ontology, drawable or not.
 *
 * A class the twin declares but cannot draw -- the class on grid_lines, whose
 * geometry is the join of its endpoint buses, or a graph class that lives only
 * in the node table -- is reported with the reason rather than omitted.
 * Omitting it would tell the reader the twin does not know about it.
 */
export function describeOntologyClasses(semantic, scenarioId = null) {
  // Which artifact the MAP actually reads for each class, so a row can say it
  // is superseded rather than claiming a reading the map does not draw.
  const drawn = new Set(
    ontologySources(semantic, scenarioId).map(source => source.artifact)
  );
  const rows = (semantic?.classes || [])
    .filter(entry => entry.scenarioId === null || entry.scenarioId === scenarioId)
    .map(entry => {
      const locatable = Boolean(entry.located && entry.coordinates);
      const superseded = locatable && !drawn.has(entry.artifact);
      return {
        name: entry.name,
        count: entry.count,
        population: entry.population,
        artifact: entry.artifact,
        drawable: locatable && !superseded,
        superseded,
        undrawableReason: locatable
          ? superseded
            ? `superseded for the map by a more specific reading of the same ` +
              `entities; ${entry.artifact} is still what the twin declares`
            : null
          : `${entry.artifact} carries no coordinates of its own`,
      };
    });
  // Drawable first. The graph population is 21 of 34 rows in the shipped twin
  // and none of it is drawable, so catalog order pushed every class the map can
  // actually draw below the fold -- a legend the reader had to scroll past its
  // own subject. Order within each group is preserved.
  return [...rows.filter(row => row.drawable), ...rows.filter(row => !row.drawable)];
}

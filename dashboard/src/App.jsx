import React, { useEffect, useMemo, useState } from 'react';
import { ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ReferenceLine, ResponsiveContainer } from 'recharts';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';
import { useDuckDB } from './useDuckDB';
import { buildScenarioCatalog, loadTwin } from './scenarios';
import { loadClearingScorecard } from './clearingScorecard';
import { loadNetworkImpactReports } from './networkImpact';
import { loadOperationsCatalog } from './operationsCatalog';
import { deriveWorkspaces, loadProjectReports } from './projectCatalog';
import ProjectDashboard, { WorkspaceSelector } from './StudyWorkspace';

import TwinMap from './TwinMap';
import StudyExtensionPanels from './StudyExtensionPanels';
import OntologyPanel from './OntologyPanel';
import ProvenanceBadge from './ProvenanceBadge';
import OverlayPanel from './OverlayPanel';
import { drawableClasses } from './ontology';
import { useOntologyFeatures } from './useOntologyFeatures';
import { fmt, heatmapTitle } from './format';


function transformerKind(row) {
  const hv = Number(row.vn_hv_kv);
  const lv = Number(row.vn_lv_kv);
  if (hv >= 100 && lv >= 20) return 'HV/MV';
  if (hv >= 20 && lv < 1) return 'MV/LV';
  return `${fmt(hv, 1)}/${fmt(lv, 1)} kV`;
}

export default function App() {
  // The twin is the subject; studies are sources it draws on. Defaulting to a
  // study made one of them a peer of the twin, which is the framing this
  // dashboard exists to drop.
  const [activeWorkspace, setActiveWorkspace] = useState('digital_twin');
  const [twinProjects, setTwinProjects] = useState([]);
  const [projectReports, setProjectReports] = useState([]);
  const [projectReportsLoading, setProjectReportsLoading] = useState(false);
  const [scenarios, setScenarios] = useState(buildScenarioCatalog());
  const [twinGeography, setTwinGeography] = useState(null);
  const [twinNetworkModel, setTwinNetworkModel] = useState(null);
  // The twin's ontology, from the catalog. Null for a twin that declares none.
  const [twinSemantic, setTwinSemantic] = useState(null);
  // Whether this deployment is a shadow. Null for a catalog too old to say,
  // which is not the same as "no measured data".
  const [twinObservation, setTwinObservation] = useState(null);
  const [twinWarnings, setTwinWarnings] = useState([]);
  const [twinError, setTwinError] = useState(null);
  const { db, isInitializing, dbError } = useDuckDB(
    activeWorkspace === 'digital_twin' ? scenarios : [],
    activeWorkspace === 'digital_twin' ? twinGeography : null,
    activeWorkspace === 'digital_twin' ? twinSemantic : null
  );
  // No literal scenario id: the selection follows whatever the twin declares,
  // and stays null until it has answered.
  const [selectedScenario, setSelectedScenario] = useState(scenarios[0]?.id ?? null);
  const [timestamps, setTimestamps] = useState([]);
  const [timeIndex, setTimeIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  
  // Recharts target tracing state
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeHistory, setNodeHistory] = useState([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

  // Layer visibility state selectors
  const [showMV, setShowMV] = useState(true);
  const [showLV, setShowLV] = useState(true);
  const [showTransformers, setShowTransformers] = useState(false);
  const [showStudyExtensions, setShowStudyExtensions] = useState(false);
  // Off by default: the ontology layer is an extra reading of the same
  // entities, not a replacement for the electrical one.
  const [showOntology, setShowOntology] = useState(false);

  // Heatmap target dimension
  const [heatmapMode, setHeatmapMode] = useState('nodes'); // 'nodes', 'lines', or 'transformers'

  // Heatmap algorithms and runtime filtering require parsed feature arrays
  const [nodesFeatures, setNodesFeatures] = useState([]);
  const [linesFeatures, setLinesFeatures] = useState([]);
  const [transformerFeatures, setTransformerFeatures] = useState([]);
  const [networkImpact, setNetworkImpact] = useState(null);
  const [networkImpactError, setNetworkImpactError] = useState(null);
  const [clearingScorecard, setClearingScorecard] = useState(null);
  const [clearingScorecardError, setClearingScorecardError] = useState(null);
  const [operationsCatalog, setOperationsCatalog] = useState(null);
  const [operationsCatalogError, setOperationsCatalogError] = useState(null);

  // Entities typed by what the twin's ontology says they ARE, read from the
  // artifacts and columns the catalog declares.
  const ontologyFeatures = useOntologyFeatures(
    db,
    twinSemantic,
    selectedScenario,
    showOntology
  );

  const scenarioSummary = scenarios.find(item => item.id === selectedScenario);
  const networkImpactScenarios = networkImpact?.scenarios || {};
  const selectedNetworkImpact = networkImpactScenarios[selectedScenario] || null;
  const scenarioNetworkImpact = selectedNetworkImpact?.status === 'available' ? selectedNetworkImpact : null;
  const availableNetworkImpactLabels = Object.values(networkImpactScenarios)
    .filter(item => item?.status === 'available')
    .map(item => scenarios.find(scenario => scenario.id === item.scenarioId)?.label || item.scenarioId)
    .filter(Boolean);
  const scenarioClearingScorecard = clearingScorecard?.scenarioId === selectedScenario ? clearingScorecard : null;
  const operationScenarios = operationsCatalog?.scenarios || {};
  const selectedOperation = operationScenarios[selectedScenario] || null;
  const scenarioOperation = selectedOperation?.status === 'available' ? selectedOperation : null;
  const availableOperationLabels = Object.values(operationScenarios)
    .filter(item => item?.status === 'available')
    .map(item => scenarios.find(scenario => scenario.id === item.scenarioId)?.label || item.scenarioId)
    .filter(Boolean);
  const clearingRows = (scenarioClearingScorecard?.policies || [])
    .filter(policy => policy.policy_id !== 'unmanaged')
    .slice(0, 5);
  const gridMetrics = scenarioSummary?.gridMetrics || scenarioSummary || {};
  const scenarioExtensions = scenarioSummary?.extensions || {};
  const hasStudyExtensions = Boolean(
    scenarioExtensions.network_impact
    || scenarioExtensions.clearing_scorecard
    || scenarioExtensions.operations
  );

  const workspaces = deriveWorkspaces(twinProjects);
  const activeProject = workspaces.find(
    workspace => workspace.id === activeWorkspace && workspace.kind === 'project'
  );

  useEffect(() => {
    let cancelled = false;
    async function loadReports() {
      // Resolved inside the effect, from the two values it genuinely depends
      // on. `deriveWorkspaces` rebuilds its entries every render, so depending
      // on the derived object would refetch every report on every render.
      const project = twinProjects.find(entry => entry.project_id === activeWorkspace);
      if (!project) {
        setProjectReports([]);
        return;
      }
      setProjectReportsLoading(true);
      const loaded = await loadProjectReports(
        { artifacts: project.artifacts || [] },
        fetch
      );
      if (!cancelled) {
        setProjectReports(loaded);
        setProjectReportsLoading(false);
      }
    }
    loadReports();
    return () => {
      cancelled = true;
    };
  }, [activeWorkspace, twinProjects]);

  useEffect(() => {
    async function loadScenarios() {
      try {
        const twin = await loadTwin();
        setScenarios(twin.scenarios);
        setTwinGeography(twin.geography);
        setTwinNetworkModel(twin.networkModel);
        setTwinSemantic(twin.semantic);
        setTwinObservation(twin.observation);
        setTwinProjects(twin.projects);
        setTwinWarnings(twin.warnings);
        setTwinError(null);
      } catch (err) {
        // Surfaced, not only logged. An empty scenario list reaches the user
        // as a blank panel, with the reason and the URLs we tried confined to
        // the browser console.
        console.error('[App] Twin discovery error:', err.message || err);
        setScenarios([]);
        setTwinGeography(null);
        setTwinNetworkModel(null);
        setTwinSemantic(null);
        setTwinObservation(null);
        setTwinProjects([]);
        setTwinWarnings([]);
        setTwinError(err.message || String(err));
      }
    }
    loadScenarios();
  }, []);

  useEffect(() => {
    async function loadImpactReports() {
      if (!scenarioExtensions.network_impact) {
        setNetworkImpact(null);
        setNetworkImpactError(null);
        return;
      }
      try {
        const reports = await loadNetworkImpactReports(fetch, scenarioExtensions.network_impact);
        setNetworkImpact(reports);
        setNetworkImpactError(null);
      } catch (err) {
        console.error('[App] Network impact report load error:', err.message || err);
        setNetworkImpact(null);
        setNetworkImpactError(err.message || String(err));
      }
    }
    loadImpactReports();
  }, [scenarioExtensions.network_impact]);

  useEffect(() => {
    async function loadScorecard() {
      if (!scenarioExtensions.clearing_scorecard) {
        setClearingScorecard(null);
        setClearingScorecardError(null);
        return;
      }
      try {
        const report = await loadClearingScorecard(fetch, scenarioExtensions.clearing_scorecard);
        setClearingScorecard(report);
        setClearingScorecardError(null);
      } catch (err) {
        console.error('[App] Clearing scorecard load error:', err.message || err);
        setClearingScorecard(null);
        setClearingScorecardError(err.message || String(err));
      }
    }
    loadScorecard();
  }, [scenarioExtensions.clearing_scorecard]);

  useEffect(() => {
    async function loadOperations() {
      if (!scenarioExtensions.operations) {
        setOperationsCatalog(null);
        setOperationsCatalogError(null);
        return;
      }
      try {
        const catalog = await loadOperationsCatalog(fetch, scenarioExtensions.operations);
        setOperationsCatalog(catalog);
        setOperationsCatalogError(null);
      } catch (err) {
        console.error('[App] Operations catalog load error:', err.message || err);
        setOperationsCatalog(null);
        setOperationsCatalogError(err.message || String(err));
      }
    }
    loadOperations();
  }, [scenarioExtensions.operations]);

  useEffect(() => {
    if (!scenarios.some(scenario => scenario.id === selectedScenario)) {
      setSelectedScenario(scenarios[0]?.id ?? null);
    }
  }, [scenarios, selectedScenario]);

  useEffect(() => {
    setTimeIndex(0);
    setIsPlaying(false);
    setSelectedNode(null);
    setNodeHistory([]);
  }, [selectedScenario]);

  useEffect(() => {
    if (!showTransformers && heatmapMode === 'transformers') {
      setHeatmapMode('lines');
    }
  }, [showTransformers, heatmapMode]);

  // Load distinct timestamps once DuckDB engine is ready or scenario changes
  useEffect(() => {
    async function loadMetadata() {
      if (!db) return;
      try {
        console.log(`[App] Fetching temporal metadata from ${selectedScenario}_nodes.parquet...`);
        const conn = await db.connect();
        const res = await conn.query(`
          SELECT DISTINCT timestamp 
          FROM '${selectedScenario}_nodes.parquet'
          ORDER BY timestamp ASC
        `);
        const times = res.toArray().map(row => row.timestamp);
        console.log(`[App] Loaded ${times.length} timestamps`);
        setTimestamps(times);
        conn.close();
      } catch (err) {
        console.error('[App] Metadata load error:', err.message || err);
      }
    }
    loadMetadata();
  }, [db, selectedScenario]);

  // Query actual map features when timeIndex or filters change
  useEffect(() => {
    async function loadTimeSlice() {
      if (!db || timestamps.length === 0) return;

      const currentTime = timestamps[timeIndex];
      const cats = [];
      if (showMV) cats.push("'MV'");
      if (showLV) cats.push("'LV'");
      if (cats.length === 0 && !showTransformers) {
        setNodesFeatures([]);
        setLinesFeatures([]);
        setTransformerFeatures([]);
        return;
      }

      const catList = cats.join(",");
      const hasNetworkLayers = cats.length > 0;

      try {
        const conn = await db.connect();

        // Load Nodes
        if (hasNetworkLayers) {
          const nodesRes = await conn.query(`
            SELECT bus_idx, lon, lat, v_pu as vm_pu, category
            FROM '${selectedScenario}_nodes.parquet'
            WHERE timestamp = '${currentTime}' AND category IN (${catList})
          `);

          // Transform DuckDB Arrow rows into DeckGL Geometry objects
          const nodes = nodesRes.toArray().map(row => ({
            geometry: { coordinates: [row.lon, row.lat] },
            properties: { bus_idx: row.bus_idx, vm_pu: row.vm_pu, category: row.category }
          }));
          setNodesFeatures(nodes);
        } else {
          setNodesFeatures([]);
        }

        // Load Lines
        if (hasNetworkLayers) {
          const linesRes = await conn.query(`
            WITH n AS (
              SELECT bus_idx, lon, lat, category
              FROM '${selectedScenario}_nodes.parquet'
              WHERE timestamp = '${currentTime}'
            )
            SELECT
              l.line_idx,
              nf.lon AS lon_from,
              nf.lat AS lat_from,
              nt.lon AS lon_to,
              nt.lat AS lat_to,
              l.loading_percent,
              nf.category
            FROM '${selectedScenario}_lines.parquet' l
            JOIN n nf ON l.from_bus = nf.bus_idx
            JOIN n nt ON l.to_bus = nt.bus_idx
            WHERE l.timestamp = '${currentTime}' AND nf.category IN (${catList})
          `);

          const lines = linesRes.toArray().map(row => ({
            type: "Feature",
            geometry: { type: "LineString", coordinates: [[row.lon_from, row.lat_from], [row.lon_to, row.lat_to]] },
            properties: { line_idx: row.line_idx, loading_percent: row.loading_percent, category: row.category }
          }));
          setLinesFeatures(lines);
        } else {
          setLinesFeatures([]);
        }

        if (showTransformers) {
          const transformerLayerPredicate = hasNetworkLayers
            ? `AND (
                (t.vn_hv_kv >= 100 AND t.vn_lv_kv >= 20)
                OR nh.category IN (${catList})
                OR nl.category IN (${catList})
              )`
            : '';

          const transformerRes = await conn.query(`
            WITH n AS (
              SELECT bus_idx, lon, lat, category
              FROM '${selectedScenario}_nodes.parquet'
              WHERE timestamp = '${currentTime}'
            )
            SELECT
              t.trafo_idx,
              t.hv_bus,
              t.lv_bus,
              t.loading_percent,
              t.sn_mva,
              t.vn_hv_kv,
              t.vn_lv_kv,
              nh.lon AS lon_hv,
              nh.lat AS lat_hv,
              nl.lon AS lon_lv,
              nl.lat AS lat_lv,
              nh.category AS hv_category,
              nl.category AS lv_category
            FROM '${selectedScenario}_transformers.parquet' t
            JOIN n nh ON t.hv_bus = nh.bus_idx
            JOIN n nl ON t.lv_bus = nl.bus_idx
            WHERE t.timestamp = '${currentTime}'
            ${transformerLayerPredicate}
          `);

          const transformers = transformerRes.toArray().map(row => ({
            geometry: {
              coordinates: [
                (Number(row.lon_hv) + Number(row.lon_lv)) / 2,
                (Number(row.lat_hv) + Number(row.lat_lv)) / 2
              ]
            },
            properties: {
              trafo_idx: row.trafo_idx,
              hv_bus: row.hv_bus,
              lv_bus: row.lv_bus,
              loading_percent: row.loading_percent,
              sn_mva: row.sn_mva,
              vn_hv_kv: row.vn_hv_kv,
              vn_lv_kv: row.vn_lv_kv,
              transformer_kind: transformerKind(row),
              category: transformerKind(row)
            }
          }));
          setTransformerFeatures(transformers);
        } else {
          setTransformerFeatures([]);
        }

        conn.close();
      } catch (err) {
        console.error("DuckDB TimeSlice Query error:", err.message || err);
      }
    }

    loadTimeSlice();
  }, [db, timestamps, timeIndex, showMV, showLV, showTransformers, selectedScenario]);

  // Node Trajectory Fetcher (Fired upon User Click)
  useEffect(() => {
    async function loadNodeHistory() {
      if (!db || !selectedNode) return;
      
      setIsHistoryLoading(true);
      try {
        const conn = await db.connect();
        const bus_idx = selectedNode.properties.bus_idx;
        
        // Instantaneous 24-hr retrieval natively querying local analytics
        const historyRes = await conn.query(`
          SELECT 
            timestamp, 
            p_total_mw * 1000 AS p_kw,
            p_ev_mw * 1000 AS ev_kw,
            temperature_c 
          FROM '${selectedScenario}_power.parquet'
          WHERE pandapower_load = ${bus_idx}
          ORDER BY timestamp
        `);
        
        // Recharts prefers raw JSON dictionaries mapping numerical axes
        const history = historyRes.toArray().map(row => ({
           time: row.timestamp.split(" ")[1],
           Power: Number(row.p_kw.toFixed(2)),
           EV: Number(row.ev_kw.toFixed(2)),
           Temp: Number(row.temperature_c.toFixed(1))
        }));
        
        setNodeHistory(history);
        conn.close();
      } catch (err) {
        console.error("DuckDB History Fetch error:", err.message || err);
      } finally {
        setIsHistoryLoading(false);
      }
    }
    
    loadNodeHistory();
  }, [db, selectedNode, selectedScenario]);

  // Animation Loop Effect
  useEffect(() => {
    let interval;
    if (isPlaying && timestamps.length > 0) {
      interval = setInterval(() => {
        setTimeIndex(prev => (prev + 1) >= timestamps.length ? 0 : prev + 1);
      }, 500); // 500ms allows WebWorker to sync flawlessly rendering heatmaps
    }
    return () => clearInterval(interval);
  }, [isPlaying, timestamps]);

  // What the map draws comes from the registry in `mapLayers.js`. Adding a
  // layer touches that file; this component only supplies the context.
  // Grouped once rather than rebuilt inside the map on every render: a new
  // object identity there would defeat any memoisation downstream.
  const mapFeatures = useMemo(
    () => ({
      nodes: nodesFeatures,
      lines: linesFeatures,
      transformers: transformerFeatures,
      ontology: ontologyFeatures,
    }),
    [nodesFeatures, linesFeatures, transformerFeatures, ontologyFeatures]
  );

  // The classes the map may draw, narrowed to the selected scenario. Handed to
  // the registry, which derives one layer per class; no class name appears in
  // this component, and none needs to.
  const scenarioOntologyClasses = useMemo(
    () => drawableClasses(twinSemantic, selectedScenario),
    [twinSemantic, selectedScenario]
  );

  if (activeProject) {
    return (
      <ProjectDashboard
        workspace={activeProject}
        reports={projectReports}
        loading={projectReportsLoading}
        activeWorkspace={activeWorkspace}
        onWorkspaceChange={setActiveWorkspace}
        workspaces={workspaces}
      />
    );
  }

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'absolute', top: 0, left: 0 }}>
      <TwinMap
        features={mapFeatures}
        geography={twinGeography}
        heatmapMode={heatmapMode}
        ontologyClasses={scenarioOntologyClasses}
        showOntology={showOntology}
        onSelectNode={setSelectedNode}
      />

      {/* The overlay scrolls and collapses; see OverlayPanel for why it had
          to. The map is the subject of this view, so the panel must be able to
          get out of its way. */}
      <OverlayPanel title="Twin">
        <WorkspaceSelector activeWorkspace={activeWorkspace} onChange={setActiveWorkspace} workspaces={workspaces} />
        <h2 style={{ margin: '14px 0 5px 0', fontSize: '1.4rem' }}>Gridalyn Digital Twin</h2>
        {/* The twin identifies itself by its model version, not by a project
            name the dashboard guessed. */}
        <p style={{ margin: '0 0 4px 0', color: '#666666', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {twinNetworkModel?.modelVersionId || 'model unidentified'}
        </p>
        <p style={{ margin: '0 0 8px 0', color: '#aaaaaa', fontSize: '0.9rem' }}>Scenario {scenarioSummary?.label || selectedScenario} · Heatmap: {heatmapTitle(heatmapMode)}</p>
        {/* What is on screen, stated rather than assumed. A twin with no
            measured data says nothing further -- no empty panel, and no
            implication that anything here was measured. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '0 0 20px 0' }}>
          <ProvenanceBadge
            provenance={scenarioSummary?.provenance || twinObservation?.provenance}
            title={
              twinObservation?.measured.available
                ? 'this instance carries measured observations'
                : twinObservation?.measured.absentReason || undefined
            }
          />
          {twinObservation?.measured.available && (
            <span style={{ color: '#7dffb0', fontSize: '0.72rem' }}>
              shadow · {twinObservation.measured.sources.length} measured source
              {twinObservation.measured.sources.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', margin: '0 0 8px 0', color: '#aaaaaa', fontSize: '0.9rem', borderBottom: '1px solid #444', paddingBottom: '5px' }} htmlFor="scenario-select">Scenario</label>
          <select
            id="scenario-select"
            value={selectedScenario}
            onChange={event => setSelectedScenario(event.target.value)}
            style={{
              width: '100%',
              minHeight: '38px',
              border: '1px solid #444',
              background: 'rgba(255,255,255,0.08)',
              color: '#fff',
              borderRadius: '6px',
              padding: '6px 8px',
              fontSize: '0.9rem',
              cursor: 'pointer',
            }}
          >
            {scenarios.map(scenario => (
              <option key={scenario.id} value={scenario.id} style={{ background: '#111', color: '#fff' }}>
                {scenario.label}
              </option>
            ))}
          </select>
          {scenarioSummary?.description && (
            <p style={{ margin: '8px 0 0 0', color: '#b7dede', fontSize: '0.72rem', lineHeight: 1.35 }}>
              {scenarioSummary.description}
            </p>
          )}
          {scenarioSummary && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 8px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
                Grid Health
                <ProvenanceBadge provenance={scenarioSummary.provenance} />
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.82rem', color: '#e6e6e6' }}>
                <span>Grid peak: <strong>{fmt(gridMetrics.grid_peak_mw ?? gridMetrics.ext_grid_peak_mw)} MW</strong></span>
                <span>Load peak: <strong>{fmt(gridMetrics.load_peak_mw)} MW</strong></span>
                <span>Min voltage: <strong>{fmt(gridMetrics.v_min_pu, 4)} p.u.</strong></span>
                <span>Max line: <strong>{fmt(gridMetrics.line_max_loading_percent)}%</strong></span>
                <span>Max trafo: <strong>{fmt(gridMetrics.trafo_max_loading_percent)}%</strong></span>
                <span>Line ovl: <strong>{gridMetrics.n_line_overloads ?? 'n/a'}</strong></span>
                <span>Trafo ovl: <strong>{gridMetrics.n_trafo_overloads ?? 'n/a'}</strong></span>
              </div>
            </div>
          )}
          <OntologyPanel
            semantic={scenarioSummary?.semanticGraph || twinSemantic}
            scenarioId={selectedScenario}
            showOntology={showOntology}
            onToggleOntology={() => setShowOntology(!showOntology)}
          />
          <StudyExtensionPanels
            hasStudyExtensions={hasStudyExtensions}
            showStudyExtensions={showStudyExtensions}
            onToggle={() => setShowStudyExtensions(!showStudyExtensions)}
            scenarioNetworkImpact={scenarioNetworkImpact}
            networkImpact={networkImpact}
            networkImpactError={networkImpactError}
            scenarioOperation={scenarioOperation}
            operationsCatalog={operationsCatalog}
            operationsCatalogError={operationsCatalogError}
            scenarioClearingScorecard={scenarioClearingScorecard}
            clearingScorecard={clearingScorecard}
            clearingScorecardError={clearingScorecardError}
            selectedScenario={selectedScenario}
            selectedNetworkImpact={selectedNetworkImpact}
            availableNetworkImpactLabels={availableNetworkImpactLabels}
            selectedOperation={selectedOperation}
            availableOperationLabels={availableOperationLabels}
            clearingRows={clearingRows}
          />
        </div>

        {/* Color Gradient Legend */}
        <div style={{ width: '100%' }}>
          <div style={{
            height: '15px',
            width: '100%',
            borderRadius: '10px',
            background: 'linear-gradient(to right, rgb(25,100,255), rgb(0,200,200), rgb(150,255,50), rgb(255,200,0), rgb(255,100,0), rgb(255,0,40))'
          }} />

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginTop: '6px', color: '#e0e0e0' }}>
            {heatmapMode === 'nodes' ? (
              <><span>1.0 p.u.</span><span>0.98</span><span>0.96</span><span style={{ color: '#ff3232', fontWeight: 'bold' }}>&lt; 0.94</span></>
            ) : (
              <><span>0%</span><span>50%</span><span>80%</span><span style={{ color: '#ff3232', fontWeight: 'bold' }}>&gt; 100%</span></>
            )}
          </div>
        </div>

        {/* Dimension Selectors */}
        <div style={{ marginTop: '25px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <p style={{ margin: '0', color: '#aaaaaa', fontSize: '0.9rem', borderBottom: '1px solid #444', paddingBottom: '3px' }}>Heatmap Projection</p>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.9rem' }}>
            <input
              type="radio"
              name="heatmapMode"
              value="nodes"
              checked={heatmapMode === 'nodes'}
              onChange={() => setHeatmapMode('nodes')}
              style={{ marginRight: '8px', cursor: 'pointer' }}
            />
            Voltage Deficits (Nodes)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.9rem' }}>
            <input
              type="radio"
              name="heatmapMode"
              value="lines"
              checked={heatmapMode === 'lines'}
              onChange={() => setHeatmapMode('lines')}
              style={{ marginRight: '8px', cursor: 'pointer' }}
            />
            Thermal Loading (Cables)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.9rem' }}>
            <input
              type="radio"
              name="heatmapMode"
              value="transformers"
              checked={heatmapMode === 'transformers' && showTransformers}
              onChange={() => setHeatmapMode('transformers')}
              disabled={!showTransformers}
              style={{ marginRight: '8px', cursor: 'pointer' }}
            />
            Thermal Loading (Transformers)
          </label>
        </div>

        {/* Layer Selector */}
        <div style={{ marginTop: '25px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <p style={{ margin: '0', color: '#aaaaaa', fontSize: '0.9rem', borderBottom: '1px solid #444', paddingBottom: '5px' }}>Network Layers</p>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.95rem' }}>
            <input
              type="checkbox"
              checked={showMV}
              onChange={() => setShowMV(!showMV)}
              style={{ marginRight: '10px', width: '18px', height: '18px', cursor: 'pointer' }}
            />
            Medium Voltage (MV)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.95rem' }}>
            <input
              type="checkbox"
              checked={showLV}
              onChange={() => setShowLV(!showLV)}
              style={{ marginRight: '10px', width: '18px', height: '18px', cursor: 'pointer' }}
            />
            Low Voltage (LV)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '0.95rem' }}>
            <input
              type="checkbox"
              checked={showTransformers}
              onChange={() => setShowTransformers(!showTransformers)}
              style={{ marginRight: '10px', width: '18px', height: '18px', cursor: 'pointer' }}
            />
            Transformers
          </label>
        </div>

        {/* Time Slider Controls */}
        <div style={{ marginTop: '30px', borderTop: '1px solid #444', paddingTop: '15px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
            <p style={{ margin: '0', color: '#aaaaaa', fontSize: '0.9rem', fontWeight: 'bold' }}>
              Time: <span style={{ color: '#fff' }}>{timestamps.length > 0 ? timestamps[timeIndex].split(" ")[1] : "Loading Engine..."}</span>
            </p>
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              disabled={timestamps.length === 0 || isInitializing}
              style={{
                background: isPlaying ? '#ff3232' : 'rgb(0,200,200)',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '6px 14px',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: 'bold',
                boxShadow: '0 2px 5px rgba(0,0,0,0.3)',
                transition: 'background 0.2s'
              }}
            >
              {isPlaying ? "⏸ Pause" : "▶ Play"}
            </button>
          </div>

          <input
            type="range"
            min="0"
            max={timestamps.length > 0 ? timestamps.length - 1 : 0}
            value={timeIndex}
            onChange={(e) => {
              setTimeIndex(Number(e.target.value));
              setIsPlaying(false); // Stop playing if user manually slides
            }}
            disabled={timestamps.length === 0 || isInitializing}
            style={{ width: '100%', cursor: 'pointer' }}
          />
          {isInitializing && <p style={{ color: 'rgb(0,200,200)', fontSize: '0.8rem', marginTop: '10px', textShadow: '0 0 5px rgb(0,200,200)' }}>⚡ Booting WebAssembly Engine...</p>}
          {dbError && <p style={{ color: '#ff4444', fontSize: '0.75rem', marginTop: '8px', wordBreak: 'break-word' }}>⚠ Engine error: {dbError}</p>}
          {twinError && <p style={{ color: '#ff4444', fontSize: '0.75rem', marginTop: '8px', wordBreak: 'break-word' }}>⚠ Twin not found: {twinError}</p>}
          {twinNetworkModel && (
            <p style={{ color: '#888', fontSize: '0.7rem', marginTop: '8px', wordBreak: 'break-word' }}>
              {/* Which model this view is of. The dashboard renders a specific,
                  identified snapshot; without saying which, two runs of the
                  same page are indistinguishable. */}
              Model {twinNetworkModel.modelVersionId || 'unidentified'}
              {twinNetworkModel.counts?.buses != null && ` — ${twinNetworkModel.counts.buses} buses`}
              {twinNetworkModel.validation?.valid === false && ' — integrity check FAILED'}
            </p>
          )}
          {twinWarnings.map(warning => (
            <p key={warning} style={{ color: '#ffaa33', fontSize: '0.7rem', marginTop: '8px', wordBreak: 'break-word' }}>⚠ {warning}</p>
          ))}
          {twinGeography?.crsAssumed && (
            <p style={{ color: '#888', fontSize: '0.7rem', marginTop: '8px' }}>
              CRS {twinGeography.crs} assumed — the twin declares none.
            </p>
          )}
        </div>

      </OverlayPanel>

      {/* Floating Recharts Node Trajectory Analytics */}
      {selectedNode && (
        <div style={{
          position: 'absolute',
          bottom: 20,
          right: 20,
          background: 'rgba(5, 5, 10, 0.85)',
          backdropFilter: 'blur(8px)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: 'white',
          padding: '20px',
          borderRadius: '12px',
          fontFamily: 'Montserrat, sans-serif',
          width: '500px',
          height: '340px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          display: 'flex',
          flexDirection: 'column'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
            <h3 style={{ margin: '0', fontSize: '1.2rem', color: '#fff' }}>
              Building Node {selectedNode.properties.bus_idx} · {selectedScenario}
              <span style={{ fontSize: '0.8rem', marginLeft: '10px', color: '#ff3232' }}>{selectedNode.properties.category}</span>
              {/* This trace is a series of values, so it states where they
                  came from too -- the rule is per view, not per screen. */}
              <span style={{ marginLeft: '10px' }}>
                <ProvenanceBadge provenance={scenarioSummary?.provenance} />
              </span>
            </h3>
            <button 
              onClick={() => setSelectedNode(null)}
              style={{ background: 'transparent', color: '#aaa', border: 'none', cursor: 'pointer', fontSize: '1.2rem' }}
            >
              ✖
            </button>
          </div>
          
          {isHistoryLoading ? (
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
              <p style={{ color: '#00ccff', fontSize: '0.9rem' }}>DuckDB Analytic Extracting...</p>
            </div>
          ) : (
            <div style={{ flex: 1, width: '100%', minHeight: '250px', display: 'flex', justifyContent: 'center' }}>
              <ComposedChart width={460} height={260} data={nodeHistory} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="time" stroke="#aaa" fontSize={11} tick={{fill: '#888'}} />
                <YAxis yAxisId="left" stroke="#ff3232" fontSize={11} tick={{fill: '#ff3232'}} />
                <YAxis yAxisId="right" orientation="right" stroke="#00ccff" fontSize={11} tick={{fill: '#00ccff'}} />
                
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: 'rgba(0,0,0,0.8)', border: '1px solid #444', borderRadius: '5px' }}
                  labelStyle={{ color: '#aaa', marginBottom: '5px' }}
                  itemStyle={{ fontSize: '0.9rem' }}
                />
                <Legend wrapperStyle={{ fontSize: '0.8rem' }} />
                
                <Area yAxisId="left" type="monotone" dataKey="Power" fillOpacity={0.3} fill="#ff3232" stroke="#ff3232" name="Demand (kW)" />
                <Line yAxisId="left" type="monotone" dataKey="EV" stroke="#f5c542" strokeWidth={2} dot={false} name="EV (kW)" />
                <Line yAxisId="right" type="monotone" dataKey="Temp" stroke="#00ccff" strokeWidth={2} dot={false} name="Temp (°C)" />
                
                {/* Vertical Reference Line to sync with the Master Map Timeline */}
                {timestamps.length > 0 && nodeHistory.length > 0 && timeIndex < timestamps.length && (
                  <ReferenceLine yAxisId="left" x={timestamps[timeIndex].split(" ")[1]} stroke="white" strokeDasharray="3 3" />
                )}
              </ComposedChart>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import DeckGL from '@deck.gl/react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ReferenceLine, ResponsiveContainer } from 'recharts';
import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';
import { useDuckDB } from './useDuckDB';
import { buildScenarioCatalog, loadTwin } from './scenarios';
import { loadClearingScorecard } from './clearingScorecard';
import { loadNetworkImpactReports } from './networkImpact';
import { loadOperationsCatalog } from './operationsCatalog';
import { WORKSPACES, loadIeee33Dashboard } from './projectDashboards';
import { operatingProject } from './projectSource';

// Base map style (Carto Dark Matter equivalent in Open Standard)
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

// Exact spatial bounding box centroid for the synthetic grid network
const INITIAL_VIEW_STATE = {
  longitude: -72.604,
  latitude: 46.342,
  zoom: 14.5,
  pitch: 45,
  bearing: -10
};

function fmt(value, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return 'n/a';
  return Number(value).toFixed(digits);
}

function heatmapTitle(mode) {
  if (mode === 'nodes') return 'Nodal Voltage Drop';
  if (mode === 'lines') return 'Cable Thermal Overload';
  return 'Transformer Thermal Overload';
}

function signedFmt(value, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return 'n/a';
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
}

const IEEE_SCENARIO_COLORS = {
  baseline: '#72d6ff',
  load_growth_20: '#ffbf69',
  pv_midday: '#72e06a',
  ev_evening_peak: '#ff5c7a',
  pv_plus_ev: '#c9a7ff',
};

function compactScenarioLabel(id) {
  return String(id || '').replaceAll('_', ' ');
}

function WorkspaceSelector({ activeWorkspace, onChange }) {
  return (
    <div className="workspace-switcher">
      <label htmlFor="workspace-select">Workspace</label>
      <select
        id="workspace-select"
        value={activeWorkspace}
        onChange={event => onChange(event.target.value)}
      >
        {WORKSPACES.map(workspace => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function IeeeDemoDashboard({ data, error, selectedScenario, onScenarioChange, activeWorkspace, onWorkspaceChange }) {
  const selected = data?.scenarios?.find(item => item.scenarioId === selectedScenario) || data?.scenarios?.[0] || null;
  const chartScenarioIds = data?.scenarioSummary?.scenario_ids || data?.scenarios?.map(item => item.scenarioId) || [];

  return (
    <div className="project-dashboard">
      <div className="project-dashboard__panel">
        <div className="project-dashboard__header">
          <div>
            <p className="eyebrow">Gridalyn Project Dashboard</p>
            <h1>IEEE 33-Bus Demo</h1>
            <p>
              A compact distribution feeder demo with deterministic load growth, PV, EV peak,
              and mixed operating scenarios.
            </p>
          </div>
          <WorkspaceSelector activeWorkspace={activeWorkspace} onChange={onWorkspaceChange} />
        </div>

        {error && (
          <div className="project-dashboard__notice">
            IEEE demo artifacts are unavailable: {error}
          </div>
        )}

        {!data && !error && (
          <div className="project-dashboard__notice">Loading IEEE 33-bus project artifacts...</div>
        )}

        {data && (
          <>
            <section className="project-dashboard__cards">
              <div>
                <span>Base buses</span>
                <strong>{data.powerflow.bus_count ?? 'n/a'}</strong>
              </div>
              <div>
                <span>Base load</span>
                <strong>{fmt(data.powerflow.total_load_mw)} MW</strong>
              </div>
              <div>
                <span>Base min voltage</span>
                <strong>{fmt(data.powerflow.min_voltage_pu, 4)} p.u.</strong>
              </div>
              <div>
                <span>Scenarios</span>
                <strong>{data.scenarioSummary.scenario_count ?? data.scenarios.length}</strong>
              </div>
              <div>
                <span>Best voltage</span>
                <strong>{compactScenarioLabel(data.scenarioSummary.best_voltage_scenario)}</strong>
              </div>
              <div>
                <span>Worst voltage</span>
                <strong>{compactScenarioLabel(data.scenarioSummary.worst_voltage_scenario)}</strong>
              </div>
            </section>

            <section className="project-dashboard__content">
              <div className="project-dashboard__scenario">
                <label htmlFor="ieee-scenario-select">Scenario</label>
                <select
                  id="ieee-scenario-select"
                  value={selected?.scenarioId || ''}
                  onChange={event => onScenarioChange(event.target.value)}
                >
                  {data.scenarios.map(scenario => (
                    <option key={scenario.scenarioId} value={scenario.scenarioId}>
                      {compactScenarioLabel(scenario.scenarioId)}
                    </option>
                  ))}
                </select>
                {selected && (
                  <div className="project-dashboard__scenario-grid">
                    <span>Net demand <strong>{fmt(selected.netDemandMw)} MW</strong></span>
                    <span>PV gen. <strong>{fmt(selected.totalGenerationMw)} MW</strong></span>
                    <span>Losses <strong>{fmt(selected.lineLossMw)} MW</strong></span>
                    <span>Min V <strong>{fmt(selected.minVoltagePu, 4)} p.u.</strong></span>
                    <span>Max line <strong>{fmt(selected.maxLineLoadingPercent, 4)}%</strong></span>
                    <span>Violations <strong>{selected.voltageViolationCount ?? 'n/a'}</strong></span>
                  </div>
                )}
              </div>

              <div className="project-dashboard__chart">
                <div className="project-dashboard__chart-title">
                  <h2>Voltage Profile Comparison</h2>
                  <span>Per-unit voltage by bus</span>
                </div>
                <ResponsiveContainer width="100%" height={360}>
                  <ComposedChart data={data.voltageChartRows} margin={{ top: 12, right: 24, bottom: 8, left: 0 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.12)" />
                    <XAxis dataKey="busId" stroke="#b7c8d8" tick={{ fontSize: 12 }} />
                    <YAxis domain={[0.86, 1.01]} stroke="#b7c8d8" tick={{ fontSize: 12 }} />
                    <RechartsTooltip
                      contentStyle={{ background: '#151922', border: '1px solid #394452', borderRadius: 6 }}
                      labelStyle={{ color: '#fff' }}
                    />
                    <Legend />
                    <ReferenceLine y={0.95} stroke="#ff5c7a" strokeDasharray="4 4" />
                    {chartScenarioIds.map(scenarioId => (
                      <Line
                        key={scenarioId}
                        type="monotone"
                        dataKey={scenarioId}
                        stroke={IEEE_SCENARIO_COLORS[scenarioId] || '#ffffff'}
                        strokeWidth={scenarioId === selected?.scenarioId ? 3 : 1.7}
                        dot={false}
                        name={compactScenarioLabel(scenarioId)}
                      />
                    ))}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="project-dashboard__artifacts">
              <h2>Generated Artifacts</h2>
              <div>
                <a href={data.artifacts.powerflowReport}>Powerflow report</a>
                <a href={data.artifacts.scenarioReport}>Scenario report</a>
                <a href={data.artifacts.scenarioResults}>Scenario results CSV</a>
                <a href={data.artifacts.voltageProfiles}>Voltage profiles CSV</a>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function transformerKind(row) {
  const hv = Number(row.vn_hv_kv);
  const lv = Number(row.vn_lv_kv);
  if (hv >= 100 && lv >= 20) return 'HV/MV';
  if (hv >= 20 && lv < 1) return 'MV/LV';
  return `${fmt(hv, 1)}/${fmt(lv, 1)} kV`;
}

function loadingColor(load, alpha = 220) {
  if (load > 100) return [255, 0, 40, alpha];
  if (load > 90) return [255, 100, 0, alpha];
  if (load > 80) return [255, 200, 0, alpha];
  if (load > 50) return [120, 230, 70, alpha];
  return [0, 190, 210, alpha];
}

export default function App() {
  const [activeWorkspace, setActiveWorkspace] = useState('ieee_33_bus_demo');
  const [scenarios, setScenarios] = useState(buildScenarioCatalog());
  const [twinGeography, setTwinGeography] = useState(null);
  const [twinNetworkModel, setTwinNetworkModel] = useState(null);
  const [twinWarnings, setTwinWarnings] = useState([]);
  const [twinError, setTwinError] = useState(null);
  const { db, isInitializing, dbError } = useDuckDB(
    activeWorkspace === 'digital_twin' ? scenarios : [],
    activeWorkspace === 'digital_twin' ? twinGeography : null
  );
  // No literal scenario id: the selection follows whatever the twin declares,
  // and stays null until it has answered.
  const [selectedScenario, setSelectedScenario] = useState(scenarios[0]?.id ?? null);
  const [ieeeDemo, setIeeeDemo] = useState(null);
  const [ieeeDemoError, setIeeeDemoError] = useState(null);
  const [selectedIeeeScenario, setSelectedIeeeScenario] = useState('baseline');
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

  useEffect(() => {
    async function loadProjectDashboard() {
      if (activeWorkspace !== 'ieee_33_bus_demo') return;
      try {
        const dashboard = await loadIeee33Dashboard(fetch);
        setIeeeDemo(dashboard);
        setIeeeDemoError(null);
        if (!dashboard.scenarios.some(item => item.scenarioId === selectedIeeeScenario)) {
          setSelectedIeeeScenario(dashboard.scenarios[0]?.scenarioId || 'baseline');
        }
      } catch (err) {
        console.error('[App] IEEE 33 demo load error:', err.message || err);
        setIeeeDemo(null);
        setIeeeDemoError(err.message || String(err));
      }
    }
    loadProjectDashboard();
  }, [activeWorkspace, selectedIeeeScenario]);

  useEffect(() => {
    async function loadScenarios() {
      try {
        const twin = await loadTwin();
        setScenarios(twin.scenarios);
        setTwinGeography(twin.geography);
        setTwinNetworkModel(twin.networkModel);
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

  const layers = [
    // Renders the Grid Cables
    new GeoJsonLayer({
      id: 'grid-lines-layer',
      data: linesFeatures,
      pickable: true,
      stroked: false,
      filled: false,
      extruded: false,
      lineWidthScale: 1,
      lineWidthMinPixels: 2,
      getLineColor: d => {
        const load = d.properties.loading_percent || 0;
        // Thermal dynamic color mapping for Cables based on loading %
        if (load > 100) return [255, 0, 40, 255];       // Critical Red
        if (load > 80) return [255, 100, 0, 200];       // Danger Orange
        if (load > 50) return [255, 200, 0, 150];       // Warning Yellow
        return [25, 100, 255, 100];                     // Safe Blue
      },
      getLineWidth: d => {
        const load = d.properties.loading_percent || 0;
        return load > 100 ? 5 : (load > 50 ? 3 : 2);
      },
      onHover: info => {
        if (info.object) {
          // Debug hook (optional)
        }
      }
    }),
    
    // Renders physical click-box points of actual Nodes
    new ScatterplotLayer({
      id: 'scatter-nodes-layer',
      data: nodesFeatures,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 0, 200],
      onClick: info => {
        if (info.object && info.object.properties.bus_idx !== undefined) {
           setSelectedNode(info.object);
        } else {
           setSelectedNode(null);
        }
      },
      getPosition: d => d.geometry.coordinates,
      getFillColor: d => d.properties.category === 'MV' ? [255, 255, 255, 180] : [200, 200, 200, 90],
      getRadius: d => d.properties.category === 'MV' ? 12 : 5,
      radiusMinPixels: 2,
      radiusMaxPixels: 6
    }),

    // Multi-Dimensional Heatmap (Gaussian Interpolation of Network Stress)
    new HeatmapLayer({
      id: 'heatmap-nodes-layer',
      data: heatmapMode === 'nodes' ? nodesFeatures : (heatmapMode === 'lines' ? linesFeatures : []),
      pickable: false,
      getPosition: d => {
        if (heatmapMode === 'nodes') {
          return d.geometry.coordinates; // Exact physical Bus geometry
        } else if (heatmapMode === 'lines') {
          // Heat source emanates from the exact midpoint of the overloaded cable
          const p1 = d.geometry.coordinates[0];
          const p2 = d.geometry.coordinates[1];
          return [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
        }
        return [0, 0];
      },
      getWeight: d => {
        if (heatmapMode === 'nodes') {
           // We square the voltage deficit so extreme voltage drops exponentially dominate the heat blur
           const v = d.properties.vm_pu || 1.0;
           const drop = Math.max(0, 1.0 - v);
           return Math.pow(drop * 10, 2);
        } else if (heatmapMode === 'lines') {
           // We isolate physical congestion above warning levels (50%+)
           const load = d.properties.loading_percent || 0;
           return load > 50 ? Math.pow(load / 50, 2) : 0;
        }
        return 0;
      },
      radiusPixels: heatmapMode === 'nodes' ? 60 : 40,
      intensity: heatmapMode === 'nodes' ? 0.8 : 1.5,
      threshold: 0.03,
      // Standard 6-color thermal scale expected by Deck.gl for smooth interpolation
      colorRange: [
        [25, 100, 255, 60],     // 1. Safe Deep Blue
        [0, 200, 200, 120],     // 2. Cyan / Safe Margin
        [150, 255, 50, 180],    // 3. Green-Yellow Transition
        [255, 200, 0, 200],     // 4. Warning Yellow
        [255, 100, 0, 230],     // 5. Danger Orange
        [255, 0, 40, 255]       // 6. Critical Red Core
      ],
      aggregation: 'SUM'
    }),

    new HeatmapLayer({
      id: 'transformer-loading-heatmap-layer',
      data: heatmapMode === 'transformers' ? transformerFeatures : [],
      pickable: false,
      getPosition: d => d.geometry.coordinates,
      getWeight: d => {
        const load = d.properties.loading_percent || 0;
        return Math.pow(Math.max(load, 20) / 100, 2.2);
      },
      radiusPixels: 58,
      intensity: 1.25,
      threshold: 0.01,
      colorRange: [
        [25, 100, 255, 55],
        [0, 200, 200, 110],
        [150, 255, 50, 170],
        [255, 200, 0, 210],
        [255, 100, 0, 235],
        [255, 0, 40, 255]
      ],
      aggregation: 'SUM'
    }),

    new ScatterplotLayer({
      id: 'transformer-overload-halo-layer',
      data: heatmapMode === 'transformers' ? transformerFeatures.filter(d => (d.properties.loading_percent || 0) > 100) : [],
      pickable: false,
      stroked: true,
      filled: true,
      getPosition: d => d.geometry.coordinates,
      getFillColor: [255, 0, 40, 45],
      getLineColor: [255, 255, 255, 180],
      getLineWidth: 2,
      getRadius: d => d.properties.transformer_kind === 'HV/MV' ? 70 : 38,
      radiusMinPixels: 7,
      radiusMaxPixels: 18,
      lineWidthMinPixels: 1,
      lineWidthMaxPixels: 3
    }),

    new ScatterplotLayer({
      id: 'transformer-markers-layer',
      data: transformerFeatures,
      pickable: true,
      stroked: true,
      filled: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 220],
      getPosition: d => d.geometry.coordinates,
      getFillColor: d => {
        const load = d.properties.loading_percent || 0;
        return loadingColor(load, d.properties.transformer_kind === 'HV/MV' ? 245 : 210);
      },
      getLineColor: d => d.properties.transformer_kind === 'HV/MV' ? [255, 255, 255, 255] : [20, 20, 20, 230],
      getLineWidth: d => d.properties.transformer_kind === 'HV/MV' ? 3 : 1,
      getRadius: d => d.properties.transformer_kind === 'HV/MV' ? 45 : 18,
      radiusMinPixels: 3,
      radiusMaxPixels: 14,
      lineWidthMinPixels: 1,
      lineWidthMaxPixels: 3
    })
  ];

  if (activeWorkspace === 'ieee_33_bus_demo') {
    return (
      <IeeeDemoDashboard
        data={ieeeDemo}
        error={ieeeDemoError}
        selectedScenario={selectedIeeeScenario}
        onScenarioChange={setSelectedIeeeScenario}
        activeWorkspace={activeWorkspace}
        onWorkspaceChange={setActiveWorkspace}
      />
    );
  }

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'absolute', top: 0, left: 0 }}>
      {/* DeckGL acts as the primary webGL overlay Engine */}
      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        layers={layers}
        getTooltip={({ object }) => {
          if (!object) return null;
          if (object.properties.trafo_idx !== undefined) {
             return `Transformer: ${object.properties.trafo_idx} | ${object.properties.transformer_kind} | Load: ${object.properties.loading_percent.toFixed(1)}% | Rating: ${object.properties.sn_mva.toFixed(2)} MVA`;
          }
          if (object.properties.line_idx !== undefined) {
             return `Cable: ${object.properties.line_idx} | Load: ${object.properties.loading_percent.toFixed(1)}% | Cat: ${object.properties.category}`;
          }
          if (object.properties.bus_idx !== undefined) {
             return `Bus: ${object.properties.bus_idx} | Voltage: ${object.properties.vm_pu.toFixed(3)} p.u. | Cat: ${object.properties.category}`;
          }
          return null;
        }}
      >
        {/* Mapbox/MapLibre acts as the 2D background tile provider */}
        <Map reuseMaps mapStyle={MAP_STYLE} />
      </DeckGL>

      {/* UI overlay */}
      <div style={{
        position: 'absolute',
        top: 20,
        left: 20,
        background: 'rgba(0,0,0,0.85)',
        color: 'white',
        padding: '20px',
        borderRadius: '12px',
        fontFamily: 'Montserrat, sans-serif',
        minWidth: '320px',
        boxShadow: '0 4px 15px rgba(0,0,0,0.5)'
      }}>
        <WorkspaceSelector activeWorkspace={activeWorkspace} onChange={setActiveWorkspace} />
        <h2 style={{ margin: '14px 0 5px 0', fontSize: '1.4rem' }}>Gridalyn Digital Twin</h2>
        <p style={{ margin: '0 0 4px 0', color: '#666666', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Project: {operatingProject()}
        </p>
        <p style={{ margin: '0 0 20px 0', color: '#aaaaaa', fontSize: '0.9rem' }}>Scenario {scenarioSummary?.label || selectedScenario} · Heatmap: {heatmapTitle(heatmapMode)}</p>

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
              <p style={{ margin: '0 0 8px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Grid Health</p>
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
          {scenarioSummary?.semanticGraph && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333', fontSize: '0.78rem', color: '#d7eeee' }}>
              <span>Ontology: <strong>{scenarioSummary.semanticGraph.profile}</strong></span>
              <span>Valid: <strong>{scenarioSummary.semanticGraph.valid === null ? 'n/a' : String(scenarioSummary.semanticGraph.valid)}</strong></span>
              <span>Nodes: <strong>{scenarioSummary.semanticGraph.nodeCount ?? 'n/a'}</strong></span>
              <span>Edges: <strong>{scenarioSummary.semanticGraph.edgeCount ?? 'n/a'}</strong></span>
            </div>
          )}
          {hasStudyExtensions && <button
            type="button"
            onClick={() => setShowStudyExtensions(!showStudyExtensions)}
            style={{
              width: '100%',
              marginTop: '12px',
              padding: '8px 10px',
              border: '1px solid #333',
              background: 'rgba(255,255,255,0.06)',
              color: '#d7eeee',
              borderRadius: '6px',
              cursor: 'pointer',
              textAlign: 'left',
              fontSize: '0.78rem',
              fontWeight: 'bold',
            }}
          >
            {showStudyExtensions ? 'Hide' : 'Show'} Optional Study Extensions
          </button>}
          {showStudyExtensions && scenarioNetworkImpact && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 8px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Network Impact</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.76rem', color: '#e6f7f7' }}>
                <span>Samples: <strong>{scenarioNetworkImpact.labels?.n_samples ?? 'n/a'}</strong></span>
                <span>Providers: <strong>{scenarioNetworkImpact.labels?.provider_count ?? 'n/a'}</strong></span>
                <span>Pairs: <strong>{scenarioNetworkImpact.surrogate?.n_supervised_pairs ?? 'n/a'}</strong></span>
                <span>Predictions: <strong>{scenarioNetworkImpact.surrogate?.n_positive_predictions ?? 'n/a'}</strong></span>
                <span>Delivered: <strong>{fmt(scenarioNetworkImpact.physics?.total_delivered_mwh)} MWh</strong></span>
                <span>Shortfall: <strong>{fmt(scenarioNetworkImpact.physics?.total_shortfall_mwh)} MWh</strong></span>
                <span>Trafo relief: <strong>{fmt(scenarioNetworkImpact.physicsComparison?.trafo_max_loading_reduction_pctpt)} pct-pt</strong></span>
                <span>Overloads: <strong>{signedFmt(scenarioNetworkImpact.physicsComparison?.trafo_overload_delta, 0)}</strong></span>
              </div>
              {scenarioNetworkImpact.constraints?.length > 0 && (
                <p style={{ margin: '8px 0 0 0', color: '#b7dede', fontSize: '0.68rem', lineHeight: 1.35 }}>
                  Constraints: {scenarioNetworkImpact.constraints.slice(0, 3).join(', ')}
                  {scenarioNetworkImpact.constraints.length > 3 ? ` +${scenarioNetworkImpact.constraints.length - 3}` : ''}
                </p>
              )}
            </div>
          )}
          {showStudyExtensions && networkImpact && !scenarioNetworkImpact && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 6px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Network Impact</p>
              <p style={{ margin: 0, color: '#b7dede', fontSize: '0.72rem', lineHeight: 1.35 }}>
                {selectedNetworkImpact?.status === 'not_generated'
                  ? `Not generated for ${selectedScenario}.`
                  : `No report for ${selectedScenario}.`}
                {availableNetworkImpactLabels.length > 0 ? ` Available for ${availableNetworkImpactLabels.join(', ')}.` : ''}
              </p>
            </div>
          )}
          {showStudyExtensions && networkImpactError && (
            <p style={{ margin: '10px 0 0 0', color: '#ffb347', fontSize: '0.72rem' }}>
              Network impact unavailable
            </p>
          )}
          {showStudyExtensions && scenarioOperation && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 8px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Flexibility Operation</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.76rem', color: '#e6f7f7' }}>
                <span>Constraints: <strong>{scenarioOperation.summary?.active_constraint_count ?? 'n/a'}</strong></span>
                <span>Providers: <strong>{scenarioOperation.summary?.selected_provider_count ?? 'n/a'}</strong></span>
                <span>Delivered: <strong>{fmt(scenarioOperation.summary?.delivered_mwh)} MWh</strong></span>
                <span>Shortfall: <strong>{fmt(scenarioOperation.summary?.shortfall_mwh)} MWh</strong></span>
                <span>Settlement: <strong>${fmt(scenarioOperation.summary?.settlement_usd, 0)}</strong></span>
                <span>Delivery: <strong>{fmt((scenarioOperation.summary?.delivery_ratio ?? 0) * 100, 0)}%</strong></span>
                <span>Agg. conc.: <strong>{fmt((scenarioOperation.summary?.aggregator_concentration_top1_pct ?? 0) * 100, 0)}%</strong></span>
                <span>Topo conc.: <strong>{fmt((scenarioOperation.summary?.topological_concentration_top1_pct ?? 0) * 100, 0)}%</strong></span>
              </div>
              {scenarioOperation.clearingMethod && (
                <p style={{ margin: '8px 0 0 0', color: '#b7dede', fontSize: '0.68rem', lineHeight: 1.35 }}>
                  Status: {scenarioOperation.status} · Method: {scenarioOperation.clearingMethod}
                  {scenarioOperation.operationId ? ` · ${scenarioOperation.operationId}` : ''}
                </p>
              )}
            </div>
          )}
          {showStudyExtensions && operationsCatalog && !scenarioOperation && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 6px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Flexibility Operation</p>
              <p style={{ margin: 0, color: '#b7dede', fontSize: '0.72rem', lineHeight: 1.35 }}>
                {selectedOperation?.status === 'not_generated'
                  ? `Not generated for ${selectedScenario}.`
                  : `No operation for ${selectedScenario}.`}
                {availableOperationLabels.length > 0 ? ` Available for ${availableOperationLabels.join(', ')}.` : ''}
              </p>
            </div>
          )}
          {showStudyExtensions && operationsCatalogError && (
            <p style={{ margin: '10px 0 0 0', color: '#ffb347', fontSize: '0.72rem' }}>
              Flexibility operation unavailable
            </p>
          )}
          {showStudyExtensions && scenarioClearingScorecard && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 8px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Clearing Scorecard</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px', fontSize: '0.72rem', color: '#d7eeee' }}>
                <span>Best delivery: <strong>{scenarioClearingScorecard.summary?.best_delivery_policy_id || 'n/a'}</strong></span>
                <span>Best overload: <strong>{scenarioClearingScorecard.summary?.best_overload_policy_id || 'n/a'}</strong></span>
              </div>
              <div style={{ display: 'grid', gap: '5px', fontSize: '0.68rem', color: '#e6f7f7' }}>
                {clearingRows.map(policy => (
                  <div
                    key={policy.policy_id}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1.2fr 0.7fr 0.7fr 0.7fr',
                      gap: '6px',
                      alignItems: 'center',
                    }}
                    title={policy.intelligence_layer}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{policy.policy_label}</span>
                    <span>{fmt(policy.total_delivered_mwh)} MWh</span>
                    <span>{fmt(policy.total_shortfall_mwh)} sh</span>
                    <span>{signedFmt(policy.trafo_overload_delta, 0)} ovl</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {showStudyExtensions && clearingScorecard && !scenarioClearingScorecard && (
            <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #333' }}>
              <p style={{ margin: '0 0 6px 0', color: '#9de7ff', fontSize: '0.78rem', fontWeight: 'bold' }}>Clearing Scorecard</p>
              <p style={{ margin: 0, color: '#b7dede', fontSize: '0.72rem', lineHeight: 1.35 }}>
                Not generated for {selectedScenario}. Available for {clearingScorecard.scenarioId || 'another scenario'}.
              </p>
            </div>
          )}
          {showStudyExtensions && clearingScorecardError && (
            <p style={{ margin: '10px 0 0 0', color: '#ffb347', fontSize: '0.72rem' }}>
              Clearing scorecard unavailable
            </p>
          )}
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

      </div>

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

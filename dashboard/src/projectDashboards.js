import { projectOutputsPath } from './projectSource.js';
export const WORKSPACES = [
  {
    id: 'ieee_33_bus_demo',
    label: 'IEEE 33-Bus Demo',
    kind: 'project',
  },
  {
    id: 'digital_twin',
    label: 'Digital Twin',
    kind: 'digital_twin',
  },
];

export function parseCsv(text) {
  const lines = String(text || '').trim().split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) return [];
  const headers = lines[0].split(',').map(value => value.trim());
  return lines.slice(1).map(line => {
    const values = line.split(',');
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? '']));
  });
}

function numberOrNull(value) {
  if (value === undefined || value === null || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeScenarioRows(rows) {
  return rows.map(row => ({
    scenarioId: row.scenario_id,
    description: row.description || '',
    totalLoadMw: numberOrNull(row.total_load_mw),
    totalGenerationMw: numberOrNull(row.total_generation_mw),
    netDemandMw: numberOrNull(row.net_demand_mw),
    lineLossMw: numberOrNull(row.line_loss_mw),
    minVoltagePu: numberOrNull(row.min_voltage_pu),
    maxVoltagePu: numberOrNull(row.max_voltage_pu),
    maxLineLoadingPercent: numberOrNull(row.max_line_loading_percent),
    voltageViolationCount: numberOrNull(row.voltage_violation_count),
    converged: row.converged === 'True' || row.converged === 'true',
  }));
}

export function normalizeVoltageRows(rows) {
  return rows.map(row => ({
    scenarioId: row.scenario_id,
    busId: numberOrNull(row.bus_id),
    vmPu: numberOrNull(row.vm_pu),
  }));
}

export function buildIeeeVoltageChartRows(voltageRows) {
  const byBus = new Map();
  for (const row of voltageRows) {
    if (row.busId === null || !row.scenarioId) continue;
    const existing = byBus.get(row.busId) || { busId: row.busId };
    existing[row.scenarioId] = row.vmPu;
    byBus.set(row.busId, existing);
  }
  return Array.from(byBus.values()).sort((a, b) => a.busId - b.busId);
}

async function fetchJson(fetchImpl, path) {
  const response = await fetchImpl(path);
  if (!response.ok) throw new Error(`HTTP ${response.status} loading ${path}`);
  return response.json();
}

async function fetchText(fetchImpl, path) {
  const response = await fetchImpl(path);
  if (!response.ok) throw new Error(`HTTP ${response.status} loading ${path}`);
  return response.text();
}

export async function loadIeee33Dashboard(fetchImpl = fetch, basePath = projectOutputsPath([], 'ieee_33_bus_demo')) {
  const [powerflowReport, scenarioReport, scenarioCsv, voltageCsv] = await Promise.all([
    fetchJson(fetchImpl, `${basePath}/reports/ieee33_powerflow_report.json`),
    fetchJson(fetchImpl, `${basePath}/reports/ieee33_scenario_comparison_report.json`),
    fetchText(fetchImpl, `${basePath}/data/scenario_results.csv`),
    fetchText(fetchImpl, `${basePath}/data/scenario_voltage_profiles.csv`),
  ]);
  const scenarios = normalizeScenarioRows(parseCsv(scenarioCsv));
  const voltageProfiles = normalizeVoltageRows(parseCsv(voltageCsv));
  return {
    projectId: 'ieee_33_bus_demo',
    title: 'IEEE 33-Bus Demo',
    powerflow: powerflowReport.summary || {},
    scenarioSummary: scenarioReport.summary || {},
    scenarios,
    voltageProfiles,
    voltageChartRows: buildIeeeVoltageChartRows(voltageProfiles),
    artifacts: {
      powerflowReport: `${basePath}/reports/ieee33_powerflow_report.json`,
      scenarioReport: `${basePath}/reports/ieee33_scenario_comparison_report.json`,
      scenarioResults: `${basePath}/data/scenario_results.csv`,
      voltageProfiles: `${basePath}/data/scenario_voltage_profiles.csv`,
    },
  };
}

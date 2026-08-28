import {
  fmt,
  signedFmt,
} from './format';

/**
 * The study-derived panels a scenario's catalog extensions make available.
 *
 * Network impact, flexibility operations and the clearing scorecard are not
 * properties of the twin: each is a study's output that a scenario LINKS to
 * through `scenarios[].extensions`. They were 134 lines inside App.jsx's
 * render, interleaved with the map controls, which made the twin's own view
 * and a study's derived view look like the same thing.
 *
 * Kept as one component rather than three, because they share a single
 * disclosure toggle and are meaningless apart from it: a scenario either has
 * study extensions to show or it has none.
 */
export default function StudyExtensionPanels({
  hasStudyExtensions,
  showStudyExtensions,
  onToggle,
  scenarioNetworkImpact,
  networkImpact,
  networkImpactError,
  scenarioOperation,
  operationsCatalog,
  operationsCatalogError,
  scenarioClearingScorecard,
  clearingScorecard,
  clearingScorecardError,
  selectedScenario,
  selectedNetworkImpact,
  availableNetworkImpactLabels,
  selectedOperation,
  availableOperationLabels,
  clearingRows,
}) {
  return (
    <>
    {hasStudyExtensions && <button
      type="button"
      onClick={() => onToggle()}
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
    </>
  );
}

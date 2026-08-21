import type { CalculationData, GroundedCitationData } from '../types/chat'

const labels = {
  ebitda_margin: 'EBITDA margin',
  revenue_growth: 'Revenue growth',
  net_profit_margin: 'Net profit margin',
} as const

export function CalculationCard({
  calculation,
  citations,
  onOpenEvidence,
}: {
  calculation: CalculationData
  citations: GroundedCitationData[]
  onOpenEvidence: (citation: GroundedCitationData) => void
}) {
  const citationsById = new Map(
    citations.map((citation) => [citation.citation_id, citation]),
  )
  return (
    <article
      className="calculation-card"
      aria-label={`${labels[calculation.metric]} calculation`}
    >
      <header>
        <div>
          <p className="eyebrow">Deterministic calculation</p>
          <h3>{labels[calculation.metric]}</h3>
          <p>
            {calculation.company_slug} · {calculation.period}
          </p>
        </div>
        <strong>{calculation.result.toFixed(2)}%</strong>
      </header>
      <section aria-label="Formula">
        <h4>Formula</h4>
        <code>{calculation.formula}</code>
      </section>
      <section aria-label="Trusted calculation inputs">
        <h4>Trusted inputs</h4>
        <div className="calculation-inputs">
          {calculation.trusted_inputs.map((input) => {
            const citation = citationsById.get(input.citation_id)
            return (
              <div key={`${input.name}-${input.period}`}>
                <span>{input.name}</span>
                <strong>
                  {input.value} {input.unit}
                </strong>
                <small>{input.period}</small>
                {citation ? (
                  <button
                    type="button"
                    aria-label={input.citation_id}
                    onClick={() => onOpenEvidence(citation)}
                  >
                    [{input.citation_id}]
                  </button>
                ) : null}
              </div>
            )
          })}
        </div>
      </section>
      <p className="calculation-boundary">
        Inputs were reauthorized and arithmetic was performed by host code, not
        the model.
      </p>
    </article>
  )
}

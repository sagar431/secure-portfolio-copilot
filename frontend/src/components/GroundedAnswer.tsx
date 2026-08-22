import type { GroundedAnswerData, GroundedCitationData } from '../types/chat'

const ROUTE_LABELS: Record<string, string> = {
  USER_REQUESTED_DEEP: 'User explicitly requested Deep',
  FAST_MODE_ELIGIBLE: 'Simple high-confidence evidence',
  SIMPLE_LOW_RISK: 'Simple high-confidence evidence',
  MULTI_DOCUMENT: 'Multiple authorized documents',
  LOW_CONFIDENCE: 'Low-confidence retrieval',
  COMPLEX_REQUEST: 'Complex analysis requested',
  AGENTIC_REQUEST: 'Bounded agent request',
}

function modeLabel(mode: string) {
  return mode.charAt(0).toUpperCase() + mode.slice(1)
}

function RouteMetadata({ response }: { response: GroundedAnswerData }) {
  const totalTokens =
    response.input_tokens !== null && response.output_tokens !== null
      ? response.input_tokens + response.output_tokens
      : null
  return (
    <dl className="response-route-metadata" aria-label="Response route details">
      <div>
        <dt>Requested</dt>
        <dd>{modeLabel(response.requested_response_mode)}</dd>
      </div>
      {response.resolved_response_mode ? (
        <div>
          <dt>Selected</dt>
          <dd>{modeLabel(response.resolved_response_mode)}</dd>
        </div>
      ) : null}
      {response.model_name ? (
        <div>
          <dt>Model</dt>
          <dd>{response.model_name}</dd>
        </div>
      ) : null}
      {response.route_reason ? (
        <div>
          <dt>Reason</dt>
          <dd>
            {ROUTE_LABELS[response.route_reason] ?? response.route_reason}
          </dd>
        </div>
      ) : null}
      {response.latency_ms !== null ? (
        <div>
          <dt>Latency</dt>
          <dd>{(response.latency_ms / 1000).toFixed(2)} seconds</dd>
        </div>
      ) : null}
      {totalTokens !== null ? (
        <div>
          <dt>Tokens</dt>
          <dd>{totalTokens.toLocaleString()}</dd>
        </div>
      ) : null}
      {response.estimated_model_cost_usd ? (
        <div>
          <dt>Estimated model cost</dt>
          <dd>${response.estimated_model_cost_usd}</dd>
        </div>
      ) : null}
    </dl>
  )
}

function CitationButton({
  citation,
  onOpenEvidence,
}: {
  citation: GroundedCitationData
  onOpenEvidence: (citation: GroundedCitationData) => void
}) {
  return (
    <button
      type="button"
      className="inline-citation"
      aria-label={`View evidence ${citation.citation_id} from ${citation.document_title}`}
      onClick={() => onOpenEvidence(citation)}
    >
      [{citation.citation_id}]
    </button>
  )
}

export function GroundedAnswer({
  response,
  onOpenEvidence,
}: {
  response: GroundedAnswerData
  onOpenEvidence: (citation: GroundedCitationData) => void
}) {
  if (response.status === 'insufficient_evidence') {
    return (
      <article className="answer-card answer-card--insufficient">
        <p className="eyebrow">Insufficient evidence</p>
        <h3>I can’t support an answer from authorized documents</h3>
        <p className="answer-copy">{response.answer}</p>
        <RouteMetadata response={response} />
        {response.limitations.length > 0 ? (
          <ul className="limitation-list">
            {response.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        ) : null}
      </article>
    )
  }

  const citationsById = new Map(
    response.citations.map((citation) => [citation.citation_id, citation]),
  )
  return (
    <article className="answer-card">
      <p className="eyebrow">Grounded answer</p>
      <RouteMetadata response={response} />
      {response.fallback_used ? (
        <p className="model-route">Safe fallback used</p>
      ) : null}
      <p className="answer-copy">{response.answer}</p>
      <section className="supported-claims" aria-label="Supported claims">
        <h3>Claims and citations</h3>
        {response.claims.map((claim, index) => (
          <p key={`${response.assistant_message_id}-${index}`}>
            <span>{claim.text}</span>{' '}
            <span className="inline-citation-list">
              {claim.citation_ids.map((citationId) => {
                const citation = citationsById.get(citationId)
                return citation ? (
                  <CitationButton
                    key={citationId}
                    citation={citation}
                    onOpenEvidence={onOpenEvidence}
                  />
                ) : null
              })}
            </span>
          </p>
        ))}
      </section>
      {response.limitations.length > 0 ? (
        <section className="answer-limitations" aria-label="Answer limitations">
          <h3>Limitations</h3>
          <ul className="limitation-list">
            {response.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  )
}

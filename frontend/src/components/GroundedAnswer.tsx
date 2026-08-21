import type { GroundedAnswerData, GroundedCitationData } from '../types/chat'

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
        {response.model_name ? (
          <p className="model-route">Model route: {response.model_name}</p>
        ) : null}
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
      {response.model_name ? (
        <p className="model-route">
          Model route: {response.model_name}
          {response.fallback_used ? ' (safe fallback)' : ''}
        </p>
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

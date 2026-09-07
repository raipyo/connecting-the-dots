'use client';

interface ResultsDisplayProps {
  research: any;
}

export function ResultsDisplay({ research }: ResultsDisplayProps) {
  if (!research) return null;

  const { results } = research;
  const response = results?.response;

  return (
    <div className="space-y-6">
      {/* Answer */}
      {response?.answer && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-3">Answer</h3>
          <p className="whitespace-pre-wrap">{response.answer}</p>
        </div>
      )}

      {/* Entities */}
      {response?.entities && response.entities.length > 0 && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-3">
            Entities Found ({response.entities.length})
          </h3>
          <div className="space-y-2">
            {response.entities.map((entity: any, i: number) => (
              <div key={i} className="border-b border-gray-100 pb-2">
                <span className="font-medium">{entity.name}</span>
                <span className="ml-2 text-sm text-gray-600">({entity.type})</span>
                <span className="ml-2 text-sm text-gray-500">
                  Confidence: {(entity.confidence * 100).toFixed(0)}%
                </span>
                {entity.country && (
                  <span className="ml-2 text-sm text-gray-500">📍 {entity.country}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Relationships */}
      {response?.relationships && response.relationships.length > 0 && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-3">
            Relationships ({response.relationships.length})
          </h3>
          <div className="space-y-2">
            {response.relationships.map((rel: any, i: number) => (
              <div key={i} className="border-b border-gray-100 pb-2">
                <span className="font-medium">{rel.source}</span>
                <span className="mx-2 text-blue-600">→ {rel.relationship} →</span>
                <span className="font-medium">{rel.target}</span>
                <span className="ml-2 text-sm text-gray-500">
                  Confidence: {(rel.confidence * 100).toFixed(0)}%
                </span>
                <span className={`ml-2 text-sm ${rel.status === 'VERIFIED' ? 'text-green-600' : 'text-orange-500'}`}>
                  [{rel.status}]
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Opportunities */}
      {response?.opportunities && response.opportunities.length > 0 && (
        <div className="bg-white p-6 rounded-lg shadow border-l-4 border-green-500">
          <h3 className="text-lg font-semibold mb-3">
            💡 Opportunities ({response.opportunities.length})
          </h3>
          <div className="space-y-2">
            {response.opportunities.map((opp: any, i: number) => (
              <div key={i} className="border-b border-gray-100 pb-2">
                <p className="text-gray-800">{opp.description}</p>
                <div className="mt-1 text-sm text-gray-500">
                  Confidence: {(opp.confidence * 100).toFixed(0)}%
                  {opp.actionable && <span className="ml-2 text-green-600">✓ Actionable</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Metadata */}
      <div className="text-sm text-gray-500">
        Status: {research.status} | Research ID: {research.research_run_id}
      </div>
    </div>
  );
}
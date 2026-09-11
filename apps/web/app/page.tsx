'use client';

import { useEffect, useMemo, useState } from 'react';

interface Entity {
  name: string;
  type: string;
  normalized_name?: string;
  description?: string;
  country?: string;
  stage?: string;
  confidence: number;
  evidence: string;
  relevance?: number;
  source_quality?: number;
  url?: string;
}

interface Relationship {
  source: string;
  relationship: string;
  target: string;
  confidence: number;
  status: string;
  evidence: string;
}

interface Opportunity {
  description: string;
  confidence: number;
  entities: string[];
  actionable: boolean;
  potential_value?: string;
  evidence: string;
}

interface Citation {
  source: string;
  content: string;
  relevance: number;
}

interface ResearchResponse {
  answer: string;
  entities: Entity[];
  relationships: Relationship[];
  opportunities: Opportunity[];
  citations: Citation[];
}

interface ResearchResult {
  research_run_id: string;
  status: string;
  results: {
    query: string;
    response: ResearchResponse;
    sources?: Array<{
      type: string;
      content: string;
      relevance: number;
    }>;
  };
}

type Tab =
  | 'organizations'
  | 'relationships'
  | 'opportunities'
  | 'sources';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

const GENERIC_RESULT_PATTERNS = [
  /^top\s+/i,
  /^best\s+/i,
  /^list\s+of/i,
  /^ranking/i,
  /^guide\s+to/i,
  /^directory/i,
  /^how\s+to/i,
  /^where\s+to/i,
  /^who\s+/i,
  /^venture capital firms?$/i,
  /^venture capital investors?$/i,
  /^venture capital funds?$/i,
  /^seed investors?$/i,
  /^seed funds?$/i,
  /^angel investors?$/i,
  /^startup investors?$/i,
  /^investors? in /i,
  /^firms? investing /i,
  /^funds? investing /i,
  /^.*investing in india$/i,
];

function isLikelyGenericResult(name: string): boolean {
  const value = name.trim();

  if (!value) return true;

  if (GENERIC_RESULT_PATTERNS.some((pattern) => pattern.test(value))) {
    return true;
  }

  const words = value.split(/\s+/);

  const sentenceWords = [
    'the',
    'top',
    'best',
    'list',
    'investing',
    'investors',
    'firms',
    'funds',
    'companies',
    'startups',
    'india',
    'guide',
    'directory',
    'ranking',
  ];

  const sentenceWordCount = words.filter((word) =>
    sentenceWords.includes(word.toLowerCase())
  ).length;

  return sentenceWordCount >= 3 || words.length > 12;
}

function cleanOrganizationName(name: string): string {
  return name
    .replace(/^[•\-–—\d.)\s]+/, '')
    .replace(/\s+/g, ' ')
    .replace(/[|:;,]+$/, '')
    .trim();
}

function getConfidenceLabel(confidence: number): string {
  if (confidence >= 0.85) return 'High confidence';
  if (confidence >= 0.65) return 'Good confidence';
  return 'Needs verification';
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.85) return '#15803d';
  if (confidence >= 0.65) return '#b45309';
  return '#b91c1c';
}

function getEntityIcon(type: string): string {
  const icons: Record<string, string> = {
    COMPANY: '🏢',
    ORGANIZATION: '🏢',
    INVESTOR: '💰',
    VC: '💼',
    ANGEL: '👼',
    ACCELERATOR: '🚀',
    INCUBATOR: '🌱',
    FAMILY_OFFICE: '🏛️',
    FOUNDATION: '🎯',
    LP: '💰',
    MANUFACTURER: '🏭',
    DISTRIBUTOR: '🚚',
    RETAILER: '🏪',
    SUPPLIER: '📦',
    PRODUCT: '📦',
    PERSON: '👤',
    COUNTRY: '🌍',
    MARKET: '📊',
  };

  return icons[type?.toUpperCase()] || '🏢';
}

function getTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    VC: 'Venture Capital',
    ANGEL: 'Angel Investor',
    ACCELERATOR: 'Accelerator',
    INCUBATOR: 'Incubator',
    FAMILY_OFFICE: 'Family Office',
    FOUNDATION: 'Foundation',
    LP: 'Limited Partner',
    COMPANY: 'Company',
    ORGANIZATION: 'Organization',
    INVESTOR: 'Investor',
    MANUFACTURER: 'Manufacturer',
    DISTRIBUTOR: 'Distributor',
    RETAILER: 'Retailer',
    SUPPLIER: 'Supplier',
  };

  return labels[type?.toUpperCase()] || type || 'Organization';
}

function getStatusStyle(status: string) {
  const styles: Record<
    string,
    { background: string; color: string; icon: string }
  > = {
    VERIFIED: {
      background: '#dcfce7',
      color: '#166534',
      icon: '✓',
    },
    SUPPORTED: {
      background: '#dbeafe',
      color: '#1d4ed8',
      icon: '●',
    },
    INFERRED: {
      background: '#fef3c7',
      color: '#92400e',
      icon: '◇',
    },
    UNVERIFIED: {
      background: '#fee2e2',
      color: '#991b1b',
      icon: '?',
    },
    CONFLICTING: {
      background: '#fecaca',
      color: '#991b1b',
      icon: '!',
    },
  };

  return (
    styles[status?.toUpperCase()] || {
      background: '#f1f5f9',
      color: '#475569',
      icon: '•',
    }
  );
}

export default function Home() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('organizations');
  const [selectedOrganization, setSelectedOrganization] =
    useState<Entity | null>(null);

  useEffect(() => {
    let cancelled = false;

    const checkHealth = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/health`);

        if (!response.ok) {
          throw new Error('Backend unavailable');
        }

        const data = await response.json();

        if (!cancelled) {
          setMode(data.mode || 'unknown');
        }
      } catch {
        if (!cancelled) {
          setMode('offline');
        }
      }
    };

    checkHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  const organizations = useMemo(() => {
    const entities = result?.results?.response?.entities || [];

    const cleaned = entities
      .map((entity) => ({
        ...entity,
        name: cleanOrganizationName(entity.name),
      }))
      .filter((entity) => {
        if (!entity.name) return false;
        if (isLikelyGenericResult(entity.name)) return false;

        return true;
      });

    const unique = new Map<string, Entity>();

    for (const entity of cleaned) {
      const key =
        entity.normalized_name?.trim().toLowerCase() ||
        entity.name.trim().toLowerCase();

      const existing = unique.get(key);

      if (!existing || entity.confidence > existing.confidence) {
        unique.set(key, entity);
      }
    }

    return Array.from(unique.values()).sort(
      (a, b) => b.confidence - a.confidence
    );
  }, [result]);

  const relationships = result?.results?.response?.relationships || [];
  const opportunities = result?.results?.response?.opportunities || [];
  const citations = result?.results?.response?.citations || [];

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    const trimmedQuery = query.trim();

    if (!trimmedQuery || loading) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedOrganization(null);
    setActiveTab('organizations');

    try {
      const response = await fetch(`${API_BASE_URL}/api/research`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: trimmedQuery,
        }),
      });

      let data: any;

      try {
        data = await response.json();
      } catch {
        throw new Error(
          `Backend returned an invalid response (${response.status})`
        );
      }

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            data?.message ||
            `Research failed with status ${response.status}`
        );
      }

      setResult(data);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : 'Failed to perform research';

      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const exampleQueries = [
    'Find Indian manufacturers exporting biodegradable packaging to UAE',
    'Find early-stage VC investors backing startups in India',
    'Find UAE distributors for Indian food manufacturers',
  ];

  const [backendOnline, setBackendOnline] = useState(false);
  const [mode, setMode] = useState('unknown');

  useEffect(() => {
    let cancelled = false;

    const checkBackend = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/health`,
          {
            cache: 'no-store',
          }
        );

        if (!response.ok) {
          throw new Error(
            `HTTP ${response.status}`
          );
        }

        const data = await response.json();

        console.log('Health check:', data);

        if (!cancelled) {
          setBackendOnline(true);
          setMode(data.mode || 'unknown');
        }
      } catch (error) {
        console.error('Health check failed:', error);

        if (!cancelled) {
          setBackendOnline(false);
          setMode('unknown');
        }
      }
    };

    checkBackend();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main
      style={{
        minHeight: '100vh',
        background: '#f8fafc',
        color: '#0f172a',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif',
      }}
    >
      <style>{`
        * {
          box-sizing: border-box;
        }

        body {
          margin: 0;
        }

        button,
        input {
          font: inherit;
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .research-card {
          transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .research-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
        }

        .organization-button:hover {
          border-color: #818cf8 !important;
          background: #fafaff !important;
        }

        .tab-button:hover {
          color: #312e81 !important;
        }

        @media (max-width: 768px) {
          .search-container {
            flex-direction: column !important;
          }

          .search-button {
            width: 100%;
          }

          .stats-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }

          .tabs {
            overflow-x: auto;
          }

          .tab-button {
            min-width: 140px;
          }
        }
      `}</style>

      <div
        style={{
          maxWidth: 1180,
          margin: '0 auto',
          padding: '24px',
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: '36px 0 30px',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 12px',
              background: '#eef2ff',
              color: '#4338ca',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 700,
              marginBottom: 16,
            }}
          >
            🔗 CONNECTING THE DOTS AI
          </div>

          <h1
            style={{
              margin: 0,
              fontSize: 'clamp(32px, 5vw, 52px)',
              lineHeight: 1.05,
              letterSpacing: '-1.5px',
              fontWeight: 800,
            }}
          >
            Discover the{' '}
            <span
              style={{
                background:
                  'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              organizations
            </span>{' '}
            behind the data.
          </h1>

          <p
            style={{
              maxWidth: 720,
              margin: '16px auto 0',
              color: '#64748b',
              fontSize: 17,
              lineHeight: 1.7,
            }}
          >
            Find companies, investors, manufacturers, distributors and the
            relationships connecting them.
          </p>

          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              marginTop: 16,
              padding: '6px 12px',
              borderRadius: 999,
              background: backendOnline
                ? '#dcfce7'
                : '#fee2e2',
              color: backendOnline
                ? '#166534'
                : '#991b1b',
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            <span>
              {backendOnline ? '●' : '○'}
            </span>

            {backendOnline
              ? mode === 'mock'
                ? 'Mock mode'
                : 'Live research'
              : 'Backend offline'}
          </div>
        </header>

        {/* Search */}
        <section
          style={{
            marginBottom: 30,
          }}
        >
          <form onSubmit={handleSubmit}>
            <div
              className="search-container"
              style={{
                display: 'flex',
                gap: 10,
                padding: 8,
                background: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: 16,
                boxShadow: '0 10px 35px rgba(15, 23, 42, 0.07)',
              }}
            >
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                disabled={loading}
                placeholder="What organizations or connections are you looking for?"
                style={{
                  flex: 1,
                  minWidth: 0,
                  border: 'none',
                  outline: 'none',
                  padding: '15px 16px',
                  fontSize: 16,
                  color: '#0f172a',
                  background: 'transparent',
                }}
              />

              <button
                className="search-button"
                type="submit"
                disabled={loading || !query.trim()}
                style={{
                  border: 'none',
                  borderRadius: 11,
                  padding: '0 28px',
                  minHeight: 50,
                  background:
                    loading || !query.trim()
                      ? '#e2e8f0'
                      : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                  color:
                    loading || !query.trim()
                      ? '#94a3b8'
                      : '#ffffff',
                  fontWeight: 700,
                  cursor:
                    loading || !query.trim()
                      ? 'not-allowed'
                      : 'pointer',
                }}
              >
                {loading ? '⏳ Researching...' : '🔍 Research'}
              </button>
            </div>
          </form>

          {!result && !loading && (
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
                marginTop: 12,
                justifyContent: 'center',
              }}
            >
              {exampleQueries.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setQuery(example)}
                  style={{
                    border: '1px solid #e2e8f0',
                    background: '#ffffff',
                    color: '#64748b',
                    borderRadius: 999,
                    padding: '7px 12px',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  {example}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Error */}
        {error && (
          <div
            style={{
              marginBottom: 24,
              padding: 16,
              borderRadius: 12,
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#991b1b',
            }}
          >
            <strong>Research failed</strong>
            <div style={{ marginTop: 5, fontSize: 14 }}>
              {error}
            </div>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div
            style={{
              padding: '60px 20px',
              textAlign: 'center',
              background: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: 16,
            }}
          >
            <div
              style={{
                width: 42,
                height: 42,
                margin: '0 auto',
                border: '4px solid #e2e8f0',
                borderTopColor: '#4f46e5',
                borderRadius: '50%',
                animation: 'spin 0.8s linear infinite',
              }}
            />

            <h3 style={{ margin: '20px 0 6px' }}>
              Mapping your query
            </h3>

            <p
              style={{
                margin: 0,
                color: '#64748b',
                fontSize: 14,
              }}
            >
              Searching sources and identifying individual organizations...
            </p>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div
            style={{
              animation: 'fadeIn 0.35s ease',
            }}
          >
            {/* Query summary */}
            {/* <section
              style={{
                padding: 22,
                marginBottom: 18,
                background: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: 16,
              }}
            >
              <div
                style={{
                  color: '#64748b',
                  fontSize: 12,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: 0.7,
                }}
              >
                Research query
              </div>

              <div
                style={{
                  marginTop: 7,
                  fontSize: 19,
                  fontWeight: 700,
                  color: '#0f172a',
                  lineHeight: 1.35,
                }}
              >
                {result.results?.name || 'Unnamed organization'}
              </div>

              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  marginTop: 6,
                  padding: '3px 9px',
                  borderRadius: 999,
                  background: '#f1f5f9',
                  color: '#475569',
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                {result.results?.type || 'Organization'}
              </div>

              <p
                style={{
                  margin: '10px 0 0',
                  color: '#475569',
                  fontSize: 15,
                  lineHeight: 1.7,
                }}
              >
                {result.results?.description ||
                  result.results?.response?.answer ||
                  'Research completed.'}
              </p>
            </section> */}

            {/* Stats */}
            <div
              className="stats-grid"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: 12,
                marginBottom: 18,
              }}
            >
              {[
                {
                  label: 'Organizations',
                  value: organizations.length,
                  icon: '🏢',
                },
                {
                  label: 'Connections',
                  value: relationships.length,
                  icon: '🔗',
                },
                {
                  label: 'Opportunities',
                  value: opportunities.length,
                  icon: '💡',
                },
                {
                  label: 'Sources',
                  value: citations.length,
                  icon: '📚',
                },
              ].map((stat) => (
                <div
                  key={stat.label}
                  style={{
                    padding: 18,
                    background: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 14,
                  }}
                >
                  <div style={{ fontSize: 22 }}>{stat.icon}</div>
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 25,
                      fontWeight: 800,
                    }}
                  >
                    {stat.value}
                  </div>
                  <div
                    style={{
                      color: '#64748b',
                      fontSize: 12,
                      marginTop: 2,
                    }}
                  >
                    {stat.label}
                  </div>
                </div>
              ))}
            </div>

            {/* Tabs */}
            <div
              className="tabs"
              style={{
                display: 'flex',
                gap: 5,
                padding: 5,
                marginBottom: 18,
                background: '#eef2f7',
                borderRadius: 13,
              }}
            >
              {[
                {
                  id: 'organizations' as Tab,
                  label: '🏢 Organizations',
                  count: organizations.length,
                },
                {
                  id: 'relationships' as Tab,
                  label: '🔗 Connections',
                  count: relationships.length,
                },
                {
                  id: 'opportunities' as Tab,
                  label: '💡 Opportunities',
                  count: opportunities.length,
                },
                {
                  id: 'sources' as Tab,
                  label: '📚 Evidence',
                  count: citations.length,
                },
              ].map((tab) => (
                <button
                  key={tab.id}
                  className="tab-button"
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    flex: 1,
                    border: 'none',
                    borderRadius: 9,
                    padding: '11px 14px',
                    background:
                      activeTab === tab.id
                        ? '#ffffff'
                        : 'transparent',
                    color:
                      activeTab === tab.id
                        ? '#312e81'
                        : '#64748b',
                    fontWeight:
                      activeTab === tab.id ? 700 : 500,
                    cursor: 'pointer',
                    boxShadow:
                      activeTab === tab.id
                        ? '0 2px 8px rgba(15,23,42,0.07)'
                        : 'none',
                  }}
                >
                  {tab.label}

                  {tab.count > 0 && (
                    <span
                      style={{
                        marginLeft: 6,
                        padding: '2px 7px',
                        borderRadius: 999,
                        background:
                          activeTab === tab.id
                            ? '#eef2ff'
                            : '#e2e8f0',
                        fontSize: 11,
                      }}
                    >
                      {tab.count}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Main content */}
            <section
              style={{
                background: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: 16,
                padding: 24,
              }}
            >
              {/* Organizations */}
              {activeTab === 'organizations' && (
                <div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 15,
                      marginBottom: 20,
                      flexWrap: 'wrap',
                    }}
                  >
                    <div>
                      <h2
                        style={{
                          margin: 0,
                          fontSize: 22,
                        }}
                      >
                        Organizations identified
                      </h2>

                      <p
                        style={{
                          margin: '5px 0 0',
                          color: '#64748b',
                          fontSize: 13,
                        }}
                      >
                        Individual organizations extracted from the
                        research evidence.
                      </p>
                    </div>

                    <span
                      style={{
                        padding: '6px 10px',
                        background: '#ecfdf5',
                        color: '#047857',
                        borderRadius: 999,
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {organizations.length} identified
                    </span>
                  </div>

                  {organizations.length === 0 ? (
                    <div
                      style={{
                        padding: '50px 20px',
                        textAlign: 'center',
                        background: '#f8fafc',
                        borderRadius: 12,
                        color: '#64748b',
                      }}
                    >
                      <div style={{ fontSize: 38 }}>🔎</div>

                      <h3
                        style={{
                          color: '#334155',
                          margin: '12px 0 6px',
                        }}
                      >
                        No individual organizations identified
                      </h3>

                      <p style={{ margin: 0, fontSize: 14 }}>
                        The research found sources, but did not find
                        sufficiently strong evidence for specific
                        organizations.
                      </p>
                    </div>
                  ) : (
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns:
                          'repeat(auto-fit, minmax(310px, 1fr))',
                        gap: 14,
                      }}
                    >
                      {organizations.map((organization, index) => {
                        const confidence =
                          organization.confidence || 0;

                        return (
                          <button
                            key={
                              organization.normalized_name ||
                              `${organization.name}-${index}`
                            }
                            type="button"
                            className="research-card organization-button"
                            onClick={() =>
                              setSelectedOrganization(organization)
                            }
                            style={{
                              textAlign: 'left',
                              border: '1px solid #e2e8f0',
                              background: '#ffffff',
                              borderRadius: 14,
                              padding: 18,
                              cursor: 'pointer',
                            }}
                          >
                            <div
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'flex-start',
                                gap: 12,
                              }}
                            >
                              <div
                                style={{
                                  display: 'flex',
                                  gap: 11,
                                  minWidth: 0,
                                }}
                              >
                                <div
                                  style={{
                                    width: 42,
                                    height: 42,
                                    flexShrink: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    borderRadius: 11,
                                    background: '#eef2ff',
                                    fontSize: 21,
                                  }}
                                >
                                  {getEntityIcon(
                                    organization.type
                                  )}
                                </div>

                                <div style={{ minWidth: 0 }}>
                                  <div
                                    style={{
                                      fontWeight: 800,
                                      fontSize: 17,
                                      color: '#0f172a',
                                      wordBreak: 'break-word',
                                    }}
                                  >
                                    {organization.name}
                                  </div>

                                  <div
                                    style={{
                                      marginTop: 4,
                                      color: '#64748b',
                                      fontSize: 12,
                                    }}
                                  >
                                    {getTypeLabel(
                                      organization.type
                                    )}
                                  </div>
                                </div>
                              </div>

                              <div
                                style={{
                                  flexShrink: 0,
                                  padding: '4px 7px',
                                  borderRadius: 7,
                                  background: `${getConfidenceColor(
                                    confidence
                                  )}12`,
                                  color:
                                    getConfidenceColor(confidence),
                                  fontSize: 11,
                                  fontWeight: 700,
                                }}
                              >
                                {(confidence * 100).toFixed(0)}%
                              </div>
                            </div>

                            {organization.description && (
                              <p
                                style={{
                                  margin: '14px 0 12px',
                                  color: '#475569',
                                  fontSize: 13,
                                  lineHeight: 1.6,
                                }}
                              >
                                {organization.description}
                              </p>
                            )}

                            <div
                              style={{
                                display: 'flex',
                                gap: 6,
                                flexWrap: 'wrap',
                                marginTop: 13,
                              }}
                            >
                              {organization.country && (
                                <span
                                  style={{
                                    padding: '4px 8px',
                                    background: '#f1f5f9',
                                    color: '#475569',
                                    borderRadius: 6,
                                    fontSize: 11,
                                  }}
                                >
                                  🌍 {organization.country}
                                </span>
                              )}

                              {organization.stage && (
                                <span
                                  style={{
                                    padding: '4px 8px',
                                    background: '#f1f5f9',
                                    color: '#475569',
                                    borderRadius: 6,
                                    fontSize: 11,
                                  }}
                                >
                                  🎯 {organization.stage}
                                </span>
                              )}

                              <span
                                style={{
                                  padding: '4px 8px',
                                  background: '#f1f5f9',
                                  color: '#475569',
                                  borderRadius: 6,
                                  fontSize: 11,
                                }}
                              >
                                {getConfidenceLabel(confidence)}
                              </span>
                            </div>

                            <div
                              style={{
                                marginTop: 14,
                                paddingTop: 12,
                                borderTop:
                                  '1px solid #f1f5f9',
                                color: '#4f46e5',
                                fontSize: 12,
                                fontWeight: 700,
                              }}
                            >
                              View evidence →
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Relationships */}
              {activeTab === 'relationships' && (
                <div>
                  <h2
                    style={{
                      margin: 0,
                      fontSize: 22,
                    }}
                  >
                    Connections
                  </h2>

                  <p
                    style={{
                      margin: '5px 0 20px',
                      color: '#64748b',
                      fontSize: 13,
                    }}
                  >
                    Relationships discovered between individual
                    entities.
                  </p>

                  {relationships.length === 0 ? (
                    <EmptyState
                      icon="🔗"
                      title="No relationships found"
                      description="No sufficiently supported connections were identified."
                    />
                  ) : (
                    relationships.map((relationship, index) => {
                      const status = getStatusStyle(
                        relationship.status
                      );

                      return (
                        <div
                          key={`${relationship.source}-${relationship.target}-${index}`}
                          className="research-card"
                          style={{
                            padding: 18,
                            marginBottom: 12,
                            border: '1px solid #e2e8f0',
                            borderRadius: 13,
                          }}
                        >
                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 12,
                              flexWrap: 'wrap',
                            }}
                          >
                            <strong>
                              {relationship.source}
                            </strong>

                            <span
                              style={{
                                padding: '6px 10px',
                                borderRadius: 8,
                                background: '#eef2ff',
                                color: '#4338ca',
                                fontSize: 12,
                                fontWeight: 700,
                              }}
                            >
                              → {relationship.relationship} →
                            </span>

                            <strong>
                              {relationship.target}
                            </strong>
                          </div>

                          <div
                            style={{
                              display: 'flex',
                              gap: 7,
                              marginTop: 13,
                              flexWrap: 'wrap',
                            }}
                          >
                            <span
                              style={{
                                padding: '4px 8px',
                                borderRadius: 7,
                                background: status.background,
                                color: status.color,
                                fontSize: 11,
                                fontWeight: 700,
                              }}
                            >
                              {status.icon} {relationship.status}
                            </span>

                            <span
                              style={{
                                padding: '4px 8px',
                                borderRadius: 7,
                                background: '#f1f5f9',
                                color: '#475569',
                                fontSize: 11,
                              }}
                            >
                              Confidence:{' '}
                              {(
                                relationship.confidence * 100
                              ).toFixed(0)}
                              %
                            </span>
                          </div>

                          {relationship.evidence && (
                            <details
                              style={{
                                marginTop: 13,
                              }}
                            >
                              <summary
                                style={{
                                  cursor: 'pointer',
                                  color: '#4f46e5',
                                  fontSize: 12,
                                  fontWeight: 600,
                                }}
                              >
                                View evidence
                              </summary>

                              <p
                                style={{
                                  margin: '10px 0 0',
                                  padding: 12,
                                  background: '#f8fafc',
                                  borderRadius: 8,
                                  color: '#475569',
                                  fontSize: 13,
                                  lineHeight: 1.6,
                                }}
                              >
                                {relationship.evidence}
                              </p>
                            </details>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}

              {/* Opportunities */}
              {activeTab === 'opportunities' && (
                <div>
                  <h2
                    style={{
                      margin: 0,
                      fontSize: 22,
                    }}
                  >
                    Opportunities
                  </h2>

                  <p
                    style={{
                      margin: '5px 0 20px',
                      color: '#64748b',
                      fontSize: 13,
                    }}
                  >
                    Potentially actionable connections discovered
                    from the research.
                  </p>

                  {opportunities.length === 0 ? (
                    <EmptyState
                      icon="💡"
                      title="No opportunities found"
                      description="No actionable opportunities were identified from the available evidence."
                    />
                  ) : (
                    opportunities.map((opportunity, index) => (
                      <div
                        key={index}
                        className="research-card"
                        style={{
                          padding: 18,
                          marginBottom: 12,
                          border: '1px solid #e2e8f0',
                          borderLeft: `4px solid ${
                            opportunity.actionable
                              ? '#16a34a'
                              : '#f59e0b'
                          }`,
                          borderRadius: 12,
                          background: opportunity.actionable
                            ? '#f0fdf4'
                            : '#fffbeb',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: 12,
                            alignItems: 'flex-start',
                          }}
                        >
                          <p
                            style={{
                              margin: 0,
                              fontSize: 15,
                              lineHeight: 1.6,
                              fontWeight: 600,
                            }}
                          >
                            {opportunity.description}
                          </p>

                          {opportunity.actionable && (
                            <span
                              style={{
                                flexShrink: 0,
                                padding: '4px 8px',
                                background: '#dcfce7',
                                color: '#166534',
                                borderRadius: 7,
                                fontSize: 11,
                                fontWeight: 700,
                              }}
                            >
                              ACTIONABLE
                            </span>
                          )}
                        </div>

                        {opportunity.entities?.length > 0 && (
                          <div
                            style={{
                              marginTop: 12,
                              display: 'flex',
                              gap: 6,
                              flexWrap: 'wrap',
                            }}
                          >
                            {opportunity.entities.map(
                              (entity) => (
                                <span
                                  key={entity}
                                  style={{
                                    padding: '5px 8px',
                                    background: '#ffffff',
                                    border:
                                      '1px solid #e2e8f0',
                                    borderRadius: 7,
                                    fontSize: 11,
                                    color: '#475569',
                                  }}
                                >
                                  {entity}
                                </span>
                              )
                            )}
                          </div>
                        )}

                        <div
                          style={{
                            marginTop: 12,
                            fontSize: 12,
                            color: '#64748b',
                          }}
                        >
                          Confidence:{' '}
                          {(
                            opportunity.confidence * 100
                          ).toFixed(0)}
                          %
                        </div>

                        {opportunity.evidence && (
                          <details
                            style={{
                              marginTop: 12,
                            }}
                          >
                            <summary
                              style={{
                                cursor: 'pointer',
                                color: '#4f46e5',
                                fontSize: 12,
                                fontWeight: 600,
                              }}
                            >
                              View evidence
                            </summary>

                            <p
                              style={{
                                margin: '10px 0 0',
                                padding: 12,
                                background: '#ffffff',
                                borderRadius: 8,
                                color: '#475569',
                                fontSize: 13,
                                lineHeight: 1.6,
                              }}
                            >
                              {opportunity.evidence}
                            </p>
                          </details>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Sources */}
              {activeTab === 'sources' && (
                <div>
                  <h2
                    style={{
                      margin: 0,
                      fontSize: 22,
                    }}
                  >
                    Evidence & Sources
                  </h2>

                  <p
                    style={{
                      margin: '5px 0 20px',
                      color: '#64748b',
                      fontSize: 13,
                    }}
                  >
                    These sources support the organizations and
                    relationships shown above.
                  </p>

                  {citations.length === 0 ? (
                    <EmptyState
                      icon="📚"
                      title="No sources available"
                      description="No source evidence was returned by the research."
                    />
                  ) : (
                    citations.map((citation, index) => (
                      <div
                        key={`${citation.source}-${index}`}
                        style={{
                          padding: 17,
                          marginBottom: 12,
                          border: '1px solid #e2e8f0',
                          borderRadius: 12,
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: 12,
                            flexWrap: 'wrap',
                          }}
                        >
                          <div
                            style={{
                              minWidth: 0,
                              fontWeight: 700,
                              fontSize: 13,
                              wordBreak: 'break-all',
                            }}
                          >
                            📄 {citation.source ||
                              'Unknown source'}
                          </div>

                          <span
                            style={{
                              padding: '4px 8px',
                              background: '#eef2ff',
                              color: '#4338ca',
                              borderRadius: 7,
                              fontSize: 11,
                              fontWeight: 700,
                            }}
                          >
                            {(citation.relevance * 100).toFixed(
                              0
                            )}
                            % relevant
                          </span>
                        </div>

                        <p
                          style={{
                            margin: '11px 0 0',
                            color: '#475569',
                            fontSize: 13,
                            lineHeight: 1.65,
                          }}
                        >
                          {citation.content}
                        </p>

                        {citation.source?.startsWith('http') && (
                          <a
                            href={citation.source}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              display: 'inline-block',
                              marginTop: 10,
                              color: '#4f46e5',
                              fontSize: 12,
                              fontWeight: 700,
                              textDecoration: 'none',
                            }}
                          >
                            Open source →
                          </a>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </section>

            {/* Research metadata */}
            <footer
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 10,
                marginTop: 14,
                padding: '12px 4px',
                color: '#94a3b8',
                fontSize: 11,
              }}
            >
              <span>
                Research ID: {result.research_run_id}
              </span>

              <span>
                Status: {result.status}
              </span>
            </footer>
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && !error && (
          <div
            style={{
              padding: '70px 25px',
              textAlign: 'center',
              background: '#ffffff',
              border: '1px solid #e2e8f0',
              borderRadius: 18,
            }}
          >
            <div
              style={{
                width: 70,
                height: 70,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 18px',
                borderRadius: 20,
                background: '#eef2ff',
                fontSize: 34,
              }}
            >
              🔗
            </div>

            <h2
              style={{
                margin: 0,
                fontSize: 25,
              }}
            >
              Start connecting the dots
            </h2>

            <p
              style={{
                maxWidth: 600,
                margin: '10px auto 0',
                color: '#64748b',
                lineHeight: 1.7,
              }}
            >
              Ask a question about a market, company, investor,
              manufacturer or distributor. The system will search
              the web, identify individual organizations and map
              the relationships between them.
            </p>

            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                flexWrap: 'wrap',
                gap: 8,
                marginTop: 22,
              }}
            >
              {[
                '🏢 Organizations',
                '🔗 Relationships',
                '💡 Opportunities',
                '📚 Evidence',
              ].map((item) => (
                <span
                  key={item}
                  style={{
                    padding: '7px 11px',
                    background: '#f1f5f9',
                    color: '#475569',
                    borderRadius: 999,
                    fontSize: 12,
                  }}
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Organization evidence drawer */}
      {selectedOrganization && (
        <div
          onClick={() => setSelectedOrganization(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            background: 'rgba(15, 23, 42, 0.45)',
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <div
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(520px, 100%)',
              height: '100%',
              overflowY: 'auto',
              background: '#ffffff',
              padding: 28,
              boxShadow: '-10px 0 40px rgba(15,23,42,0.15)',
            }}
          >
            <button
              type="button"
              onClick={() => setSelectedOrganization(null)}
              style={{
                border: 'none',
                background: '#f1f5f9',
                color: '#475569',
                width: 36,
                height: 36,
                borderRadius: 9,
                cursor: 'pointer',
                fontSize: 18,
              }}
            >
              ×
            </button>

            <div
              style={{
                marginTop: 28,
                display: 'flex',
                alignItems: 'center',
                gap: 14,
              }}
            >
              <div
                style={{
                  width: 54,
                  height: 54,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: 14,
                  background: '#eef2ff',
                  fontSize: 27,
                }}
              >
                {getEntityIcon(selectedOrganization.type)}
              </div>

              <div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 800,
                  }}
                >
                  {selectedOrganization.name}
                </div>

                <div
                  style={{
                    marginTop: 4,
                    color: '#64748b',
                    fontSize: 13,
                  }}
                >
                  {getTypeLabel(selectedOrganization.type)}
                </div>
              </div>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 10,
                marginTop: 25,
              }}
            >
              <InfoBox
                label="Confidence"
                value={`${(
                  (selectedOrganization.confidence || 0) * 100
                ).toFixed(0)}%`}
              />

              <InfoBox
                label="Country"
                value={
                  selectedOrganization.country || 'Not specified'
                }
              />

              {selectedOrganization.stage && (
                <InfoBox
                  label="Stage"
                  value={selectedOrganization.stage}
                />
              )}

              {selectedOrganization.source_quality !==
                undefined && (
                <InfoBox
                  label="Source quality"
                  value={`${(
                    selectedOrganization.source_quality * 100
                  ).toFixed(0)}%`}
                />
              )}
            </div>

            {selectedOrganization.description && (
              <section style={{ marginTop: 28 }}>
                <SectionLabel>ABOUT</SectionLabel>

                <p
                  style={{
                    color: '#475569',
                    lineHeight: 1.7,
                    fontSize: 14,
                  }}
                >
                  {selectedOrganization.description}
                </p>
              </section>
            )}

            <section style={{ marginTop: 28 }}>
              <SectionLabel>EVIDENCE</SectionLabel>

              <div
                style={{
                  padding: 16,
                  background: '#f8fafc',
                  borderRadius: 12,
                  color: '#475569',
                  fontSize: 14,
                  lineHeight: 1.7,
                }}
              >
                {selectedOrganization.evidence ||
                  'No evidence provided.'}
              </div>
            </section>

            {selectedOrganization.url && (
              <a
                href={selectedOrganization.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'block',
                  marginTop: 20,
                  padding: 13,
                  textAlign: 'center',
                  borderRadius: 10,
                  background: '#4f46e5',
                  color: '#ffffff',
                  fontWeight: 700,
                  fontSize: 13,
                  textDecoration: 'none',
                }}
              >
                Open supporting source →
              </a>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: string;
  title: string;
  description: string;
}) {
  return (
    <div
      style={{
        padding: '50px 20px',
        textAlign: 'center',
        background: '#f8fafc',
        borderRadius: 12,
      }}
    >
      <div style={{ fontSize: 36 }}>{icon}</div>

      <h3
        style={{
          margin: '12px 0 6px',
          color: '#334155',
        }}
      >
        {title}
      </h3>

      <p
        style={{
          margin: 0,
          color: '#64748b',
          fontSize: 14,
        }}
      >
        {description}
      </p>
    </div>
  );
}

function InfoBox({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div
      style={{
        padding: 13,
        background: '#f8fafc',
        borderRadius: 10,
      }}
    >
      <div
        style={{
          color: '#94a3b8',
          fontSize: 10,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {label}
      </div>

      <div
        style={{
          marginTop: 5,
          fontSize: 14,
          fontWeight: 700,
          color: '#334155',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SectionLabel({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        color: '#94a3b8',
        fontSize: 10,
        fontWeight: 800,
        letterSpacing: 0.8,
      }}
    >
      {children}
    </div>
  );
}

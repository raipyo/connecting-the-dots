'use client';

import { useState, useEffect } from 'react';

interface ResearchResult {
  research_run_id: string;
  status: string;
  results: {
    query: string;
    response: {
      answer: string;
      entities: Array<{
        name: string;
        type: string;
        normalized_name: string;
        description?: string;
        country?: string;
        confidence: number;
        evidence: string;
      }>;
      relationships: Array<{
        source: string;
        relationship: string;
        target: string;
        confidence: number;
        status: string;
        evidence: string;
      }>;
      opportunities: Array<{
        description: string;
        confidence: number;
        entities: string[];
        actionable: boolean;
        potential_value?: string;
        evidence: string;
      }>;
      citations: Array<{
        source: string;
        content: string;
        relevance: number;
      }>;
    };
    sources: Array<{
      type: string;
      content: string;
      relevance: number;
    }>;
  };
}

export default function Home() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('answer');
  const [mode, setMode] = useState('Loading...');
  const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  console.log('API_BASE_URL', API_BASE_URL)
  // Check backend mode on load
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/health`)
      .then(res => res.json())
      .then(data => setMode(data.mode || 'unknown'))
      .catch(() => setMode('offline'));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setResult(data);
    } catch (err: any) {
      setError(err.message || 'Failed to perform research');
    } finally {
      setLoading(false);
    }
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return '#28a745';
    if (confidence >= 0.6) return '#ffc107';
    return '#dc3545';
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, { bg: string; color: string; icon: string }> = {
      VERIFIED: { bg: '#d4edda', color: '#155724', icon: '✅' },
      SUPPORTED: { bg: '#cce5ff', color: '#004085', icon: '📌' },
      INFERRED: { bg: '#fff3cd', color: '#856404', icon: '🔮' },
      UNVERIFIED: { bg: '#f8d7da', color: '#721c24', icon: '⚠️' },
      CONFLICTING: { bg: '#f5c6cb', color: '#721c24', icon: '❌' },
    };
    return styles[status] || { bg: '#e2e3e5', color: '#383d41', icon: '📄' };
  };

  const getEntityIcon = (type: string) => {
    const icons: Record<string, string> = {
      COMPANY: '🏢',
      PERSON: '👤',
      PRODUCT: '📦',
      DISTRIBUTOR: '🚚',
      RETAILER: '🏪',
      INVESTOR: '💰',
      MANUFACTURER: '🏭',
      SUPPLIER: '📦',
      COUNTRY: '🌍',
      MARKET: '📊',
    };
    return icons[type] || '📌';
  };

  return (
    <div style={{
      maxWidth: 1200,
      margin: '0 auto',
      padding: '20px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    }}>
      {/* Header */}
      <div style={{
        textAlign: 'center',
        padding: '30px 0',
        borderBottom: '1px solid #e9ecef',
        marginBottom: '30px'
      }}>
        <h1 style={{
          fontSize: '42px',
          fontWeight: '700',
          margin: '0',
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text'
        }}>
          🔗 Connecting the Dots AI
        </h1>
        <p style={{ color: '#6c757d', marginTop: '8px', fontSize: '18px' }}>
          Discover relationships between companies, markets, and opportunities
        </p>
        <div style={{
          display: 'inline-block',
          marginTop: '10px',
          padding: '4px 12px',
          borderRadius: '20px',
          fontSize: '12px',
          fontWeight: '600',
          background: mode === 'real' ? '#d4edda' : '#fff3cd',
          color: mode === 'real' ? '#155724' : '#856404'
        }}>
          {mode === 'real' ? '🚀 Real Search Mode' : mode === 'mock' ? '📝 Mock Mode' : '🔌 Offline'}
        </div>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSubmit} style={{ marginBottom: '30px' }}>
        <div style={{
          display: 'flex',
          gap: '12px',
          background: 'white',
          padding: '8px',
          borderRadius: '12px',
          boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
          border: '2px solid #e9ecef',
          transition: 'border-color 0.3s ease'
        }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter your research query... (e.g., 'Find Indian manufacturers exporting to UAE')"
            style={{
              flex: 1,
              padding: '12px 16px',
              fontSize: '16px',
              border: 'none',
              outline: 'none',
              borderRadius: '8px',
              background: 'transparent'
            }}
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: '12px 32px',
              fontSize: '16px',
              fontWeight: '600',
              background: loading ? '#e9ecef' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              color: loading ? '#6c757d' : 'white',
              border: 'none',
              borderRadius: '8px',
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease',
              boxShadow: loading ? 'none' : '0 4px 15px rgba(102, 126, 234, 0.4)'
            }}
            onMouseEnter={(e) => {
              if (!loading) {
                e.currentTarget.style.transform = 'translateY(-2px)';
                e.currentTarget.style.boxShadow = '0 6px 20px rgba(102, 126, 234, 0.5)';
              }
            }}
            onMouseLeave={(e) => {
              if (!loading) {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = '0 4px 15px rgba(102, 126, 234, 0.4)';
              }
            }}
          >
            {loading ? (
              <span>⏳ Searching...</span>
            ) : (
              <span>🔍 Search</span>
            )}
          </button>
        </div>
      </form>

      {/* Error Display */}
      {error && (
        <div style={{
          background: '#f8d7da',
          border: '1px solid #f5c6cb',
          borderRadius: '8px',
          padding: '16px',
          color: '#721c24',
          marginBottom: '20px'
        }}>
          <strong>❌ Error:</strong> {error}
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div style={{
          textAlign: 'center',
          padding: '40px',
          background: '#f8f9fa',
          borderRadius: '12px'
        }}>
          <div style={{
            display: 'inline-block',
            width: '40px',
            height: '40px',
            border: '4px solid #e9ecef',
            borderTop: '4px solid #667eea',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite'
          }} />
          <style>{`
            @keyframes spin {
              0% { transform: rotate(0deg); }
              100% { transform: rotate(360deg); }
            }
          `}</style>
          <p style={{ marginTop: '12px', color: '#6c757d' }}>Researching your query...</p>
        </div>
      )}

      {/* Results Display */}
      {result && !loading && (
        <div style={{ animation: 'fadeIn 0.5s ease' }}>
          <style>{`
            @keyframes fadeIn {
              from { opacity: 0; transform: translateY(20px); }
              to { opacity: 1; transform: translateY(0); }
            }
          `}</style>

          {/* Tabs */}
          <div style={{
            display: 'flex',
            gap: '4px',
            background: '#f8f9fa',
            padding: '4px',
            borderRadius: '12px',
            marginBottom: '20px',
            border: '1px solid #e9ecef'
          }}>
            {[
              { id: 'answer', label: '📝 Answer', count: null },
              { id: 'entities', label: '🏢 Entities', count: result.results?.response?.entities?.length },
              { id: 'relationships', label: '🔗 Relationships', count: result.results?.response?.relationships?.length },
              { id: 'opportunities', label: '💡 Opportunities', count: result.results?.response?.opportunities?.length },
              { id: 'citations', label: '📚 Sources', count: result.results?.response?.citations?.length },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  flex: 1,
                  padding: '10px 16px',
                  border: 'none',
                  borderRadius: '8px',
                  background: activeTab === tab.id ? 'white' : 'transparent',
                  color: activeTab === tab.id ? '#212529' : '#6c757d',
                  fontWeight: activeTab === tab.id ? '600' : '400',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  boxShadow: activeTab === tab.id ? '0 2px 8px rgba(0,0,0,0.08)' : 'none',
                  fontSize: '14px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px'
                }}
              >
                {tab.label}
                {tab.count !== null && tab.count > 0 && (
                  <span style={{
                    background: activeTab === tab.id ? '#667eea' : '#e9ecef',
                    color: activeTab === tab.id ? 'white' : '#6c757d',
                    padding: '1px 8px',
                    borderRadius: '12px',
                    fontSize: '11px',
                    fontWeight: '600'
                  }}>
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div style={{ background: 'white', borderRadius: '12px', padding: '24px', boxShadow: '0 2px 10px rgba(0,0,0,0.05)' }}>
            {/* Answer Tab */}
            {activeTab === 'answer' && (
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '12px' }}>
                  📝 Research Answer
                </h2>
                <div style={{
                  background: '#f8f9fa',
                  padding: '20px',
                  borderRadius: '8px',
                  lineHeight: '1.8',
                  whiteSpace: 'pre-wrap'
                }}>
                  {result.results?.response?.answer || 'No answer available.'}
                </div>
                {result.results?.response?.entities && result.results.response.entities.length > 0 && (
                  <div style={{
                    marginTop: '16px',
                    padding: '12px 16px',
                    background: '#e7f3ff',
                    borderRadius: '8px',
                    fontSize: '14px',
                    color: '#004085'
                  }}>
                    <strong>📊 Summary:</strong> Found {result.results.response.entities.length} entities,{' '}
                    {result.results.response.relationships?.length || 0} relationships, and{' '}
                    {result.results.response.opportunities?.length || 0} opportunities.
                  </div>
                )}
              </div>
            )}

            {/* Entities Tab */}
            {activeTab === 'entities' && (
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>
                  🏢 Entities Found ({result.results?.response?.entities?.length || 0})
                </h2>
                {result.results?.response?.entities?.map((entity, i) => (
                  <div key={i} style={{
                    padding: '16px',
                    marginBottom: '12px',
                    border: '1px solid #e9ecef',
                    borderRadius: '8px',
                    transition: 'box-shadow 0.2s ease'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span style={{ fontSize: '24px' }}>{getEntityIcon(entity.type)}</span>
                        <span style={{ fontSize: '18px', fontWeight: '600' }}>{entity.name}</span>
                        <span style={{
                          padding: '2px 10px',
                          borderRadius: '12px',
                          fontSize: '12px',
                          fontWeight: '500',
                          background: '#e9ecef',
                          color: '#495057'
                        }}>
                          {entity.type}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {entity.country && (
                          <span style={{ fontSize: '14px', color: '#6c757d' }}>
                            🌍 {entity.country}
                          </span>
                        )}
                        <span style={{
                          padding: '2px 10px',
                          borderRadius: '12px',
                          fontSize: '12px',
                          fontWeight: '500',
                          background: getConfidenceColor(entity.confidence) + '20',
                          color: getConfidenceColor(entity.confidence)
                        }}>
                          {(entity.confidence * 100).toFixed(0)}% confidence
                        </span>
                      </div>
                    </div>
                    {entity.description && (
                      <p style={{ color: '#6c757d', fontSize: '14px', margin: '4px 0 8px 0' }}>
                        {entity.description}
                      </p>
                    )}
                    {entity.evidence && (
                      <details style={{ marginTop: '8px' }}>
                        <summary style={{ cursor: 'pointer', fontSize: '13px', color: '#667eea' }}>
                          📖 View Evidence
                        </summary>
                        <p style={{
                          padding: '8px 12px',
                          background: '#f8f9fa',
                          borderRadius: '4px',
                          fontSize: '13px',
                          color: '#495057',
                          marginTop: '4px'
                        }}>
                          {entity.evidence}
                        </p>
                      </details>
                    )}
                  </div>
                ))}
                {(!result.results?.response?.entities || result.results.response.entities.length === 0) && (
                  <p style={{ color: '#6c757d', textAlign: 'center', padding: '20px' }}>
                    No entities found in this research.
                  </p>
                )}
              </div>
            )}

            {/* Relationships Tab */}
            {activeTab === 'relationships' && (
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>
                  🔗 Relationships Found ({result.results?.response?.relationships?.length || 0})
                </h2>
                {result.results?.response?.relationships?.map((rel, i) => {
                  const statusStyle = getStatusBadge(rel.status);
                  return (
                    <div key={i} style={{
                      padding: '16px',
                      marginBottom: '12px',
                      border: '1px solid #e9ecef',
                      borderRadius: '8px',
                      borderLeft: `4px solid ${getConfidenceColor(rel.confidence)}`
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: '500' }}>{rel.source}</span>
                          <span style={{
                            padding: '4px 12px',
                            background: '#e7f3ff',
                            borderRadius: '20px',
                            fontSize: '13px',
                            fontWeight: '500',
                            color: '#004085'
                          }}>
                            → {rel.relationship} →
                          </span>
                          <span style={{ fontWeight: '500' }}>{rel.target}</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                          <span style={{
                            padding: '2px 10px',
                            borderRadius: '12px',
                            fontSize: '12px',
                            fontWeight: '500',
                            background: statusStyle.bg,
                            color: statusStyle.color
                          }}>
                            {statusStyle.icon} {rel.status}
                          </span>
                          <span style={{
                            padding: '2px 10px',
                            borderRadius: '12px',
                            fontSize: '12px',
                            fontWeight: '500',
                            background: getConfidenceColor(rel.confidence) + '20',
                            color: getConfidenceColor(rel.confidence)
                          }}>
                            {(rel.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                      {rel.evidence && (
                        <details style={{ marginTop: '8px' }}>
                          <summary style={{ cursor: 'pointer', fontSize: '13px', color: '#667eea' }}>
                            📖 View Evidence
                          </summary>
                          <p style={{
                            padding: '8px 12px',
                            background: '#f8f9fa',
                            borderRadius: '4px',
                            fontSize: '13px',
                            color: '#495057',
                            marginTop: '4px'
                          }}>
                            {rel.evidence}
                          </p>
                        </details>
                      )}
                    </div>
                  );
                })}
                {(!result.results?.response?.relationships || result.results.response.relationships.length === 0) && (
                  <p style={{ color: '#6c757d', textAlign: 'center', padding: '20px' }}>
                    No relationships found in this research.
                  </p>
                )}
              </div>
            )}

            {/* Opportunities Tab */}
            {activeTab === 'opportunities' && (
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>
                  💡 Opportunities Found ({result.results?.response?.opportunities?.length || 0})
                </h2>
                {result.results?.response?.opportunities?.map((opp, i) => (
                  <div key={i} style={{
                    padding: '16px',
                    marginBottom: '12px',
                    border: '1px solid #e9ecef',
                    borderRadius: '8px',
                    background: opp.actionable ? '#f0f9ff' : '#f8f9fa',
                    borderLeft: `4px solid ${opp.actionable ? '#28a745' : '#ffc107'}`
                  }}>
                    <div style={{ display: 'flex', alignItems: 'start', justifyContent: 'space-between', gap: '12px' }}>
                      <div style={{ flex: 1 }}>
                        <p style={{ margin: '0 0 8px 0', fontSize: '16px' }}>{opp.description}</p>
                        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                          {opp.entities && opp.entities.length > 0 && (
                            <span style={{ fontSize: '13px', color: '#6c757d' }}>
                              📌 Entities: {opp.entities.join(', ')}
                            </span>
                          )}
                          <span style={{
                            fontSize: '13px',
                            padding: '2px 10px',
                            borderRadius: '12px',
                            background: getConfidenceColor(opp.confidence) + '20',
                            color: getConfidenceColor(opp.confidence)
                          }}>
                            {(opp.confidence * 100).toFixed(0)}% confidence
                          </span>
                          {opp.actionable && (
                            <span style={{
                              fontSize: '13px',
                              padding: '2px 10px',
                              borderRadius: '12px',
                              background: '#d4edda',
                              color: '#155724'
                            }}>
                              ✅ Actionable
                            </span>
                          )}
                          {opp.potential_value && (
                            <span style={{
                              fontSize: '13px',
                              padding: '2px 10px',
                              borderRadius: '12px',
                              background: '#cce5ff',
                              color: '#004085'
                            }}>
                              💰 {opp.potential_value}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    {opp.evidence && (
                      <details style={{ marginTop: '8px' }}>
                        <summary style={{ cursor: 'pointer', fontSize: '13px', color: '#667eea' }}>
                          📖 View Evidence
                        </summary>
                        <p style={{
                          padding: '8px 12px',
                          background: '#f8f9fa',
                          borderRadius: '4px',
                          fontSize: '13px',
                          color: '#495057',
                          marginTop: '4px'
                        }}>
                          {opp.evidence}
                        </p>
                      </details>
                    )}
                  </div>
                ))}
                {(!result.results?.response?.opportunities || result.results.response.opportunities.length === 0) && (
                  <p style={{ color: '#6c757d', textAlign: 'center', padding: '20px' }}>
                    No opportunities found in this research.
                  </p>
                )}
              </div>
            )}

            {/* Citations Tab */}
            {activeTab === 'citations' && (
              <div>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>
                  📚 Sources & Citations ({result.results?.response?.citations?.length || 0})
                </h2>
                {result.results?.response?.citations?.map((citation, i) => (
                  <div key={i} style={{
                    padding: '16px',
                    marginBottom: '12px',
                    border: '1px solid #e9ecef',
                    borderRadius: '8px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '18px' }}>📄</span>
                        <span style={{ fontWeight: '500', fontSize: '14px' }}>
                          {citation.source || 'Unknown Source'}
                        </span>
                      </div>
                      <span style={{
                        padding: '2px 10px',
                        borderRadius: '12px',
                        fontSize: '12px',
                        fontWeight: '500',
                        background: getConfidenceColor(citation.relevance) + '20',
                        color: getConfidenceColor(citation.relevance)
                      }}>
                        Relevance: {(citation.relevance * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p style={{
                      margin: '0',
                      fontSize: '14px',
                      color: '#495057',
                      lineHeight: '1.6'
                    }}>
                      {citation.content}
                    </p>
                    {citation.source && citation.source.startsWith('http') && (
                      <a
                        href={citation.source}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'inline-block',
                          marginTop: '8px',
                          fontSize: '13px',
                          color: '#667eea',
                          textDecoration: 'none'
                        }}
                      >
                        🔗 View Source
                      </a>
                    )}
                  </div>
                ))}
                {(!result.results?.response?.citations || result.results.response.citations.length === 0) && (
                  <p style={{ color: '#6c757d', textAlign: 'center', padding: '20px' }}>
                    No citations available for this research.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div style={{
            marginTop: '20px',
            padding: '16px',
            background: '#f8f9fa',
            borderRadius: '8px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '8px',
            fontSize: '13px',
            color: '#6c757d'
          }}>
            <span>🔍 Research ID: {result.research_run_id}</span>
            <span>📊 Status: {result.status}</span>
            {result.results?.response?.entities && (
              <span>
                📌 {result.results.response.entities.length} entities · 
                🔗 {result.results.response.relationships?.length || 0} relationships · 
                💡 {result.results.response.opportunities?.length || 0} opportunities
              </span>
            )}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!result && !loading && !error && (
        <div style={{
          textAlign: 'center',
          padding: '60px 20px',
          background: '#f8f9fa',
          borderRadius: '12px',
          border: '2px dashed #dee2e6'
        }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔍</div>
          <h2 style={{ fontSize: '24px', color: '#212529', marginBottom: '8px' }}>
            Start Your Research
          </h2>
          <p style={{ color: '#6c757d', fontSize: '16px', marginBottom: '4px' }}>
            Enter a query above to discover connections between companies, markets, and opportunities
          </p>
          <p style={{ color: '#adb5bd', fontSize: '14px' }}>
            Example: &quot;Find Indian manufacturers of biodegradable packaging exporting to UAE&quot;
          </p>
          <div style={{
            display: 'flex',
            gap: '8px',
            justifyContent: 'center',
            marginTop: '16px',
            flexWrap: 'wrap'
          }}>
            <span style={{
              padding: '4px 12px',
              background: '#e9ecef',
              borderRadius: '20px',
              fontSize: '12px',
              color: '#495057'
            }}>🏢 Companies</span>
            <span style={{
              padding: '4px 12px',
              background: '#e9ecef',
              borderRadius: '20px',
              fontSize: '12px',
              color: '#495057'
            }}>🔗 Relationships</span>
            <span style={{
              padding: '4px 12px',
              background: '#e9ecef',
              borderRadius: '20px',
              fontSize: '12px',
              color: '#495057'
            }}>💡 Opportunities</span>
            <span style={{
              padding: '4px 12px',
              background: '#e9ecef',
              borderRadius: '20px',
              fontSize: '12px',
              color: '#495057'
            }}>📚 Citations</span>
          </div>
        </div>
      )}
    </div>
  );
}
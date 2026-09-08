'use client';

import { useState } from 'react';
import { researchService } from '@/services/research';

interface ResearchResult {
  research_run_id: string;
  status: string;
  results: any;
}

export function useResearch() {
  const [research, setResearch] = useState<ResearchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const performResearch = async (query: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const result = await researchService.performResearch(query);
      setResearch(result as ResearchResult);
      return result;
    } catch (err: any) {
      const errorMessage = err.message || 'Failed to perform research';
      setError(errorMessage);
      console.error('Research error:', err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  return {
    research,
    isLoading,
    error,
    performResearch,
  };
}
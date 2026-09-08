import { api } from '../lib/api';

export const researchService = {
  async performResearch(query: string) {
    const response = await api.post('/api/research', { query });
    return response.data;
  },

  async getResearchStatus(id: string) {
    const response = await api.get(`/api/research/${id}`);
    return response.data;
  },

  async getResearchHistory() {
    const response = await api.get('/api/research/history');
    return response.data;
  }
};
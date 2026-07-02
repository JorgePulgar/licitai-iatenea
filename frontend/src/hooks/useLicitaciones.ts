import { useState, useEffect, useCallback } from 'react';
import type { LicitacionResponse } from '../types/licitacion';
import { fetchLicitaciones } from '../services/api';

export function useLicitaciones(pollInterval?: number) {
  const [licitaciones, setLicitaciones] = useState<LicitacionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchLicitaciones();
      setLicitaciones(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando licitaciones');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    if (!pollInterval) return;
    const id = setInterval(load, pollInterval);
    return () => clearInterval(id);
  }, [load, pollInterval]);

  return { licitaciones, loading, error, reload: load };
}

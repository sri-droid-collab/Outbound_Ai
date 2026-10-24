import { useCallback, useEffect, useState } from 'react';
import { getResearch, startResearch } from '../api';

const POLL_MS = 2000;
export const ACTIVE_STATUSES = ['queued', 'running'];

// One lead's research. Progress lives on the server, so this just polls while a
// run is active - closing the panel (or the whole tab) never stops the run.
// The caller remounts the hook per lead (key={contactId}) instead of resetting state.
export function useLeadResearch(contactId) {
  const [research, setResearch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retryTick, setRetryTick] = useState(0);
  const status = research?.status;

  useEffect(() => {
    let cancelled = false;
    getResearch(contactId)
      .then((data) => { if (!cancelled) setResearch(data); })
      .catch(() => { if (!cancelled) setError('Could not load research for this lead.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [contactId]);

  useEffect(() => {
    if (!ACTIVE_STATUSES.includes(status)) return undefined;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const data = await getResearch(contactId);
        if (!cancelled) setResearch(data);
      } catch {
        if (!cancelled) setRetryTick((t) => t + 1); // transient failure: try again next tick
      }
    }, POLL_MS);
    return () => { cancelled = true; clearTimeout(timer); };
    // `research` is a dependency on purpose: each new response schedules the next poll.
  }, [contactId, status, research, retryTick]);

  const start = useCallback(async (force = false) => {
    setError('');
    try {
      setResearch(await startResearch(contactId, { force }));
    } catch {
      setError('Could not start research. Please try again.');
    }
  }, [contactId]);

  return { research, loading, error, start };
}

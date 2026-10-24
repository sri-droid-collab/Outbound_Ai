import { useCallback, useEffect, useState } from 'react';
import { listResearchStatuses } from '../api';
import { ACTIVE_STATUSES } from './useLeadResearch';

const POLL_MS = 4000;

// contact_id -> research status for the leads table. Polls only while some run
// is active, so an idle page makes no background requests.
export function useResearchStatuses() {
  const [statusByContact, setStatusByContact] = useState({});
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const anyActive = Object.values(statusByContact).some((s) => ACTIVE_STATUSES.includes(s));

  useEffect(() => {
    let cancelled = false;
    listResearchStatuses()
      .then((items) => {
        if (!cancelled) setStatusByContact(Object.fromEntries(items.map((i) => [i.contact_id, i.status])));
      })
      .catch(() => { /* badges are a convenience; the next poll or refresh retries */ });
    return () => { cancelled = true; };
  }, [tick]);

  useEffect(() => {
    if (!anyActive) return undefined;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [anyActive, statusByContact, refresh]);

  return { statusByContact, refresh };
}

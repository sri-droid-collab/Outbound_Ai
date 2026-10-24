import { apiFetch } from '../../services/apiClient';

async function readJson(res, failureMessage) {
  if (!res.ok) throw new Error(failureMessage);
  return res.json();
}

export async function getResearch(contactId) {
  return readJson(await apiFetch(`/lead-research/${contactId}`), 'Could not load research');
}

export async function startResearch(contactId, { force = false } = {}) {
  const res = await apiFetch(`/lead-research/${contactId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }),
  });
  return readJson(res, 'Could not start research');
}

export async function listResearchStatuses() {
  return readJson(await apiFetch('/lead-research/'), 'Could not load research statuses');
}

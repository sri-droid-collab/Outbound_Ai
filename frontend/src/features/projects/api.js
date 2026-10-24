import { apiFetch } from '../../services/apiClient';

export async function getProjects() {
  const res = await apiFetch('/projects/');
  if (!res.ok) return null;
  return res.json();
}

export async function getProject(id) {
  const res = await apiFetch(`/projects/${id}`);
  if (!res.ok) throw new Error('Failed to load project');
  return res.json();
}

export async function getProjectsGraph() {
  const res = await apiFetch('/projects/graph');
  if (!res.ok) return null;
  return res.json();
}

export async function uploadProject(file) {
  const body = new FormData();
  body.append('file', file);
  const res = await apiFetch('/projects/upload', { method: 'POST', body });
  const data = await res.json();
  return { ok: res.ok, data };
}

export async function importProjectsExcel(file) {
  const body = new FormData();
  body.append('file', file);
  const res = await apiFetch('/projects/import-excel', { method: 'POST', body });
  const data = await res.json();
  return { ok: res.ok, data };
}

export async function deleteProject(id) {
  await apiFetch(`/projects/${id}`, { method: 'DELETE' });
}

export async function reprocessProject(id) {
  await apiFetch(`/projects/${id}/reprocess`, { method: 'POST' });
}

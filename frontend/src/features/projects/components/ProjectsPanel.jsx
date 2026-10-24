import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Upload, FolderKanban, FolderOpen, Search, Trash2, Loader2, CheckCircle2,
  AlertCircle, FileText, RotateCw, ChevronDown, Network, Cpu, Sparkles
} from 'lucide-react';
import KnowledgeGraph from './KnowledgeGraph';
import ProjectDetailFields from './ProjectDetailFields';
import { domainStyle } from '../../../shared/utils/domainColors';
import {
  getProjects,
  uploadProject,
  importProjectsExcel,
  deleteProject as deleteProjectRequest,
  reprocessProject as reprocessProjectRequest,
} from '../api';

const TABS = [
  { id: 'upload', label: 'Upload Project', icon: Upload },
  { id: 'available', label: 'Available Projects', icon: FolderOpen },
  { id: 'graph', label: 'Knowledge Map', icon: Network },
];

const STATUS_CHIP = {
  processing: { style: 'bg-blue-50 text-blue-600', label: 'Processing' },
  completed: { style: 'bg-emerald-50 text-emerald-600', label: 'Processed' },
  failed: { style: 'bg-red-50 text-red-600', label: 'Failed' },
};

const EXCEL_EXTENSIONS = ['xlsx', 'xlsm'];
const MAX_EXCEL_BYTES = 5 * 1024 * 1024;

// Excel-imported projects have no stored file, so show where they came from instead of a size.
const sourceLabel = (p) => (p.file_type === 'xlsx' ? `${p.file_name} · Excel import` : `${p.file_name} · ${formatSize(p.file_size)}`);

const formatSize = (bytes) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

function StatusChip({ project }) {
  const chip = STATUS_CHIP[project.processing_status] || STATUS_CHIP.processing;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[12px] font-semibold ${chip.style}`}>
      {project.processing_status === 'processing' && <Loader2 className="w-3 h-3 animate-spin" />}
      {project.processing_status === 'completed' && <CheckCircle2 className="w-3 h-3" />}
      {project.processing_status === 'failed' && <AlertCircle className="w-3 h-3" />}
      {chip.label}
    </span>
  );
}

function DomainBadge({ domain }) {
  if (!domain) return null;
  return (
    <span className={`px-2.5 py-0.5 rounded-md text-[12px] font-semibold border ${domainStyle(domain).chip}`}>
      {domain}
    </span>
  );
}

export default function ProjectsPanel() {
  const [tab, setTab] = useState('upload');
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [banner, setBanner] = useState(null); // {type: 'success'|'error', message}
  const fileInputRef = useRef(null);

  const fetchProjects = useCallback(async () => {
    try {
      const data = await getProjects();
      if (data) setProjects(data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchProjects(); }, [fetchProjects]);

  // While any document is still being processed by the AI agent, poll for
  // status updates so chips flip to Processed/Failed without a refresh.
  const anyProcessing = projects.some((p) => p.processing_status === 'processing');
  useEffect(() => {
    if (!anyProcessing) return;
    const interval = setInterval(fetchProjects, 3000);
    return () => clearInterval(interval);
  }, [anyProcessing, fetchProjects]);

  const showBanner = (type, message) => {
    setBanner({ type, message });
    setTimeout(() => setBanner(null), 6000);
  };

  const importExcel = async (file) => {
    if (file.size > MAX_EXCEL_BYTES) {
      showBanner('error', 'File is too large. Maximum size for an Excel sheet is 5 MB.');
      return;
    }
    setUploading(true);
    try {
      const { ok, data } = await importProjectsExcel(file);
      if (!ok) {
        showBanner('error', data.detail || 'Import failed. Please try again.');
        return;
      }
      const note = data.errors?.[0]?.message || data.warnings?.[0]?.message;
      showBanner(
        data.imported + data.updated > 0 ? 'success' : 'error',
        `${data.imported} imported, ${data.updated} updated, ${data.skipped} skipped.${note ? ` Row ${(data.errors?.[0] || data.warnings[0]).row}: ${note}` : ''}`,
      );
      fetchProjects();
    } catch (err) {
      console.error(err);
      showBanner('error', 'Import failed. Check your connection and try again.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const uploadFile = async (file) => {
    if (!file || uploading) return;
    const ext = file.name.toLowerCase().split('.').pop();
    if (EXCEL_EXTENSIONS.includes(ext)) {
      await importExcel(file);
      return;
    }
    if (!['pdf', 'doc', 'docx'].includes(ext)) {
      showBanner('error', 'Unsupported file type. Please upload a PDF or Word document, or an Excel sheet (.xlsx).');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      showBanner('error', 'File is too large. Maximum size is 20 MB.');
      return;
    }
    setUploading(true);
    try {
      const { ok, data } = await uploadProject(file);
      if (!ok) {
        showBanner('error', data.detail || 'Upload failed. Please try again.');
      } else {
        showBanner('success', `"${data.file_name}" uploaded — the AI agent is analyzing it now.`);
        fetchProjects();
      }
    } catch (err) {
      console.error(err);
      showBanner('error', 'Upload failed. Check your connection and try again.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const deleteProject = async (id) => {
    try { await deleteProjectRequest(id); fetchProjects(); }
    catch (err) { console.error(err); }
  };

  const reprocessProject = async (id) => {
    try { await reprocessProjectRequest(id); fetchProjects(); }
    catch (err) { console.error(err); }
  };

  const completed = projects.filter((p) => p.processing_status === 'completed');
  const stats = {
    total: projects.length,
    domains: new Set(completed.map((p) => p.metadata?.domain).filter(Boolean)).size,
    processed: completed.length,
    processing: projects.filter((p) => p.processing_status === 'processing').length,
  };

  const q = search.toLowerCase();
  const filtered = projects.filter((p) => {
    if (!q) return true;
    const meta = p.metadata || {};
    return (
      p.name.toLowerCase().includes(q) ||
      p.file_name.toLowerCase().includes(q) ||
      (meta.domain || '').toLowerCase().includes(q) ||
      (meta.summary || '').toLowerCase().includes(q) ||
      (meta.technologies || []).some((t) => t.toLowerCase().includes(q))
    );
  });

  return (
    <div className="py-8 anim-enter">
      {/* Stats Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8 anim-enter">
        {[
          { label: 'Total Projects', value: stats.total, icon: FolderKanban, iconStyle: 'bg-blue-50 text-blue-500' },
          { label: 'Domains', value: stats.domains, icon: Network, iconStyle: 'bg-violet-50 text-violet-500' },
          { label: 'AI Processed', value: stats.processed, icon: Sparkles, iconStyle: 'bg-emerald-50 text-emerald-500' },
          { label: 'Processing', value: stats.processing, icon: Loader2, iconStyle: 'bg-amber-50 text-amber-500' },
        ].map((stat, i) => (
          <div key={stat.label} className={`card hover-glow p-5 anim-enter delay-${i + 1}`}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[13px] font-semibold text-gray-400 uppercase tracking-wider">{stat.label}</span>
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${stat.iconStyle}`}>
                <stat.icon className={`w-4 h-4 ${stat.label === 'Processing' && stats.processing > 0 ? 'animate-spin' : ''}`} />
              </div>
            </div>
            <p className="text-[30px] font-extrabold text-gray-900 leading-none">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[14px] font-semibold transition-all duration-300 ${
                  active ? 'bg-white text-blue-600 shadow-sm shadow-blue-500/10' : 'text-gray-500 hover:text-gray-700 hover:bg-white/50'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        {tab === 'available' && (
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search projects, domains, technologies..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-11 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all"
            />
          </div>
        )}
      </div>

      {/* Banner */}
      {banner && (
        <div className={`flex items-center gap-2.5 mb-5 p-4 rounded-xl border anim-enter ${
          banner.type === 'success' ? 'bg-emerald-50 border-emerald-100' : 'bg-red-50 border-red-100'
        }`}>
          {banner.type === 'success'
            ? <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            : <AlertCircle className="w-4 h-4 text-red-500 shrink-0" />}
          <p className={`text-[14px] font-medium ${banner.type === 'success' ? 'text-emerald-700' : 'text-red-600'}`}>
            {banner.message}
          </p>
        </div>
      )}

      {/* ─── Upload tab ─── */}
      {tab === 'upload' && (
        <div className="anim-enter">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); uploadFile(e.dataTransfer.files?.[0]); }}
            onClick={() => fileInputRef.current?.click()}
            className={`card flex flex-col items-center justify-center py-16 cursor-pointer border-2 border-dashed transition-all ${
              dragOver ? 'border-blue-400 bg-blue-50/50' : 'border-gray-200 hover:border-blue-300'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx,.xlsx,.xlsm"
              className="hidden"
              style={{ display: 'none' }}
              onChange={(e) => uploadFile(e.target.files?.[0])}
            />
            <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mb-4 ${uploading ? 'bg-blue-50' : 'bg-blue-50'}`}>
              {uploading ? <Loader2 className="w-6 h-6 text-blue-500 animate-spin" /> : <Upload className="w-6 h-6 text-blue-500 anim-float" />}
            </div>
            <p className="text-[16px] font-bold text-gray-800 mb-1">
              {uploading ? 'Uploading...' : 'Drop a project document or Excel sheet here'}
            </p>
            <p className="text-[13px] text-gray-400">
              or click to browse — PDF, DOC, DOCX up to 20 MB, or an .xlsx sheet (one project per row) up to 5 MB
            </p>
            <p className="text-[12px] text-gray-400 mt-3 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-violet-400" />
              Documents are analyzed by the AI agent for domain, tech stack and summary; Excel rows are imported exactly as written.
            </p>
          </div>

          {/* Recent uploads */}
          {projects.length > 0 && (
            <div className="mt-8">
              <h3 className="text-[13px] font-bold text-gray-400 uppercase tracking-wider mb-3">Recent Uploads</h3>
              <div className="card divide-y divide-gray-100 overflow-hidden">
                {projects.slice(0, 8).map((p) => (
                  <div key={p.id} className="flex items-center gap-4 px-5 py-3.5 row-hover group">
                    <div className="w-9 h-9 rounded-xl bg-gray-50 flex items-center justify-center shrink-0">
                      <FileText className="w-4 h-4 text-gray-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[14px] font-semibold text-gray-800 truncate">{p.name}</p>
                      <p className="text-[12px] text-gray-400 truncate">
                        {sourceLabel(p)} · {new Date(p.created_at).toLocaleDateString()}
                      </p>
                      {p.processing_status === 'failed' && p.processing_error && (
                        <p className="text-[12px] text-red-500 mt-0.5">{p.processing_error}</p>
                      )}
                    </div>
                    {p.metadata?.domain && <DomainBadge domain={p.metadata.domain} />}
                    <StatusChip project={p} />
                    <div className="flex items-center gap-1">
                      {p.processing_status === 'failed' && (
                        <button onClick={() => reprocessProject(p.id)} title="Retry AI processing" className="p-2 text-gray-300 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-all">
                          <RotateCw className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button onClick={() => deleteProject(p.id)} className="p-2 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ─── Available projects tab ─── */}
      {tab === 'available' && (
        loading ? (
          <div className="card flex items-center justify-center py-24">
            <Loader2 className="w-6 h-6 animate-spin text-blue-500 mr-3" />
            <span className="text-[15px] text-gray-400 font-medium">Loading projects...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="card flex flex-col items-center justify-center py-24">
            <FolderOpen className="w-12 h-12 text-gray-200 mb-4" />
            <p className="text-[15px] text-gray-400 font-medium">
              {projects.length === 0 ? 'No projects yet. Upload your first project document!' : 'No results found.'}
            </p>
          </div>
        ) : (
          <div className="space-y-3 anim-enter">
            {filtered.map((p) => {
              const meta = p.metadata || {};
              const expanded = expandedId === p.id;
              return (
                <div key={p.id} className="card overflow-hidden">
                  <button
                    onClick={() => setExpandedId(expanded ? null : p.id)}
                    className="w-full flex items-center gap-4 px-6 py-4 text-left"
                  >
                    <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center shrink-0">
                      <FileText className="w-4.5 h-4.5 text-blue-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <p className="text-[15px] font-bold text-gray-900">{p.name}</p>
                        {meta.domain && <DomainBadge domain={meta.domain} />}
                        {meta.ai_ml_components?.length > 0 && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-violet-50 text-violet-600">
                            <Cpu className="w-3 h-3" />AI/ML
                          </span>
                        )}
                        <StatusChip project={p} />
                      </div>
                      {meta.summary && !expanded && (
                        <p className="text-[13px] text-gray-400 truncate mt-0.5">{meta.summary}</p>
                      )}
                    </div>
                    <ChevronDown className={`w-4 h-4 text-gray-300 shrink-0 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`} />
                  </button>

                  {expanded && (
                    <div className="px-6 pb-6 pt-1 border-t border-gray-100 anim-enter">
                      {p.processing_status === 'failed' ? (
                        <div className="flex items-center justify-between gap-3 mt-4 p-4 bg-red-50 border border-red-100 rounded-xl">
                          <p className="text-[13px] text-red-600">{p.processing_error || 'Processing failed.'}</p>
                          <button onClick={() => reprocessProject(p.id)} className="flex items-center gap-1.5 px-3 py-1.5 bg-white text-red-600 border border-red-200 rounded-lg text-[12px] font-semibold hover:bg-red-50 transition-all shrink-0">
                            <RotateCw className="w-3 h-3" />Retry
                          </button>
                        </div>
                      ) : p.processing_status === 'processing' ? (
                        <div className="flex items-center gap-2.5 mt-4 text-gray-400">
                          <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                          <p className="text-[13px]">The AI agent is analyzing this document...</p>
                        </div>
                      ) : (
                        <div className="mt-4">
                          <ProjectDetailFields meta={meta} />
                        </div>
                      )}

                      <div className="flex items-center justify-between mt-5 pt-4 border-t border-gray-100">
                        <p className="text-[12px] text-gray-400">
                          {sourceLabel(p)} · added {new Date(p.created_at).toLocaleDateString()}
                        </p>
                        <button onClick={() => deleteProject(p.id)} className="flex items-center gap-1.5 px-3 py-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg text-[12px] font-semibold transition-all">
                          <Trash2 className="w-3 h-3" />Delete
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )
      )}

      {/* ─── Knowledge map tab ─── */}
      {tab === 'graph' && <KnowledgeGraph />}
    </div>
  );
}

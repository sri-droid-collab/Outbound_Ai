import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Loader2, CheckCircle2, Circle, AlertCircle, RotateCw, Globe, FileSearch, Clock } from 'lucide-react';
import { useLeadResearch, ACTIVE_STATUSES } from '../hooks/useLeadResearch';
import BriefView from './BriefView';

const STEP_LABELS = {
  fetch_site: 'Reading their website',
  check_email_setup: 'Checking email setup',
  match_projects: 'Matching our past projects',
  write_brief: 'Writing the brief',
};

function StepIcon({ status }) {
  if (status === 'done') return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
  if (status === 'running') return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
  if (status === 'failed') return <AlertCircle className="w-4 h-4 text-red-500" />;
  return <Circle className="w-4 h-4 text-gray-300" />;
}

function Progress({ steps }) {
  return (
    <div className="p-5 rounded-2xl border border-blue-100 bg-blue-50/50">
      <p className="text-[14px] font-semibold text-gray-800 mb-3">Researching this lead…</p>
      <ul className="space-y-2.5">
        {steps.map((s) => (
          <li key={s.name} className="flex items-center gap-2.5 text-[13.5px] text-gray-700">
            <StepIcon status={s.status} />{STEP_LABELS[s.name] || s.name}
          </li>
        ))}
      </ul>
      <p className="text-[12.5px] text-gray-400 mt-4 leading-relaxed">
        This usually takes under a minute. You can close this panel — the research keeps running and the lead's
        button will show when the brief is ready.
      </p>
    </div>
  );
}

function WebsitePrompt({ onSave }) {
  const [website, setWebsite] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    if (!website.trim() || saving) return;
    setSaving(true);
    setError('');
    const ok = await onSave(website.trim());
    if (!ok) setError("Couldn't save that website. Please check it and try again.");
    setSaving(false);
  };

  return (
    <div className="p-5 rounded-2xl border border-amber-100 bg-amber-50/60">
      <div className="flex items-center gap-2 text-[14px] font-semibold text-gray-800 mb-1">
        <Globe className="w-4 h-4 text-amber-600" />Which website should we research?
      </div>
      <p className="text-[12.5px] text-gray-500 mb-3 leading-relaxed">
        This lead has no usable website yet. Enter the company's public website (a company site, not an internal address).
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
          placeholder="acme.com"
          className="flex-1 px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-[14px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100"
        />
        <button onClick={submit} disabled={!website.trim() || saving} className="btn-primary px-4 py-2.5 text-[14px] disabled:opacity-40">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Save & research'}
        </button>
      </div>
      {error && <p className="text-[12.5px] text-red-500 mt-2">{error}</p>}
    </div>
  );
}

const ageInDays = (iso) => (iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86400000) : 0);

// Slide-over opened from the leads table. Closing it never cancels the run -
// that is what makes "move to background" just "close the panel".
export default function ResearchPanel({ contact, onClose, onSaveWebsite, onStarted }) {
  const { research, loading, error, start } = useLeadResearch(contact.id);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const status = research?.status;
  const active = ACTIVE_STATUSES.includes(status);
  const hasBrief = Boolean(research?.brief);
  const website = research?.website || contact.website;

  const run = async (force = false) => {
    await start(force);
    onStarted?.();
  };
  const saveWebsiteAndRun = async (value) => {
    const ok = await onSaveWebsite(contact, value);
    if (ok) await run(true);
    return ok;
  };

  return createPortal(
    <div className="fixed inset-0 z-50 bg-gray-900/20 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        className="absolute right-0 top-0 h-full w-[580px] max-w-full bg-white shadow-2xl border-l border-gray-200 flex flex-col anim-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-6 py-5 border-b border-gray-100 shrink-0">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
              <FileSearch className="w-3.5 h-3.5" />Lead research
            </p>
            <h3 className="text-[17px] font-bold text-gray-900 truncate mt-0.5">{contact.company || contact.name}</h3>
            <p className="text-[12.5px] text-gray-400 truncate">
              {contact.name}{website ? ` · ${website.replace(/^https?:\/\//, '')}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {!active && (hasBrief || status === 'failed') && (
              <button
                onClick={() => run(true)}
                className="flex items-center gap-1.5 px-3 py-2 bg-gray-50 hover:bg-gray-100 text-gray-600 rounded-lg text-[13px] font-semibold transition-all"
              >
                <RotateCw className="w-3.5 h-3.5" />Re-run
              </button>
            )}
            <button
              onClick={onClose}
              title={active ? 'Close - research keeps running in the background' : 'Close'}
              className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all"
            >
              <X className="w-4.5 h-4.5" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-24">
              <Loader2 className="w-5 h-5 animate-spin text-blue-500 mr-3" />
              <span className="text-[14px] text-gray-400 font-medium">Loading…</span>
            </div>
          ) : (
            <>
              {error && (
                <div className="flex items-center gap-2.5 p-3.5 bg-red-50 border border-red-100 rounded-xl text-[13px] text-red-600">
                  <AlertCircle className="w-4 h-4 shrink-0" />{error}
                </div>
              )}

              {active && <Progress steps={research.steps || []} />}

              {status === 'needs_website' && <WebsitePrompt onSave={saveWebsiteAndRun} />}

              {status === 'failed' && (
                <div className="flex items-start gap-2.5 p-4 bg-red-50 border border-red-100 rounded-xl">
                  <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-[13.5px] font-semibold text-red-700">Research didn't complete</p>
                    <p className="text-[13px] text-red-600 mt-0.5 leading-relaxed">{research.error}</p>
                    {hasBrief && <p className="text-[12.5px] text-red-400 mt-1">Showing the previous brief below.</p>}
                  </div>
                </div>
              )}

              {(!status || status === 'none') && !error && (
                <div className="flex flex-col items-center text-center py-12 px-6">
                  <div className="w-12 h-12 rounded-2xl bg-blue-50 flex items-center justify-center mb-4">
                    <FileSearch className="w-5 h-5 text-blue-600" />
                  </div>
                  <p className="text-[15px] font-semibold text-gray-800">Research {contact.company || contact.name}</p>
                  <p className="text-[13px] text-gray-400 mt-1.5 mb-5 max-w-[360px] leading-relaxed">
                    Reads their public website and email setup, then prepares an opening line, likely pain points and
                    questions to ask — each tied to a source.
                  </p>
                  <button onClick={() => run(false)} className="btn-primary px-5 py-2.5 text-[14px]">Start research</button>
                </div>
              )}

              {hasBrief && (
                <>
                  {research.is_stale && !active && (
                    <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-100 rounded-xl text-[12.5px] text-amber-700">
                      <Clock className="w-3.5 h-3.5 shrink-0" />
                      This brief is {ageInDays(research.completed_at)} days old. Re-run it before an important call.
                    </div>
                  )}
                  <BriefView brief={research.brief} sources={research.sources} posture={research.posture} />
                  {research.completed_at && (
                    <p className="text-[11.5px] text-gray-300 text-right">
                      Generated {new Date(research.completed_at).toLocaleString()}
                    </p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </aside>
    </div>,
    document.body
  );
}

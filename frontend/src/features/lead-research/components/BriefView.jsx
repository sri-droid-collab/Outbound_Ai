import { Lightbulb, HelpCircle, ShieldAlert, Briefcase, Mail, ExternalLink, AlertCircle, Link2 } from 'lucide-react';

const CONFIDENCE_STYLES = {
  high: 'bg-emerald-50 text-emerald-600',
  medium: 'bg-amber-50 text-amber-600',
  low: 'bg-gray-100 text-gray-500',
};

// Scraped URLs only ever become links when they're plain http(s).
const safeHref = (url) => (/^https?:\/\//i.test(url || '') ? url : null);

function Section({ icon: Icon, title, children, tone = 'text-gray-400' }) {
  return (
    <section>
      <div className={`flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider mb-2 ${tone}`}>
        {Icon && <Icon className="w-3.5 h-3.5" />}{title}
      </div>
      {children}
    </section>
  );
}

function List({ items }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="text-[13.5px] text-gray-700 leading-relaxed pl-3 relative before:content-[''] before:absolute before:left-0 before:top-[9px] before:w-1 before:h-1 before:rounded-full before:bg-gray-300">
          {item}
        </li>
      ))}
    </ul>
  );
}

function EmailSetup({ posture }) {
  if (!posture || (!posture.mx?.length && !posture.spf && !posture.dmarc)) return null;
  const dmarc = !posture.dmarc ? 'missing' : posture.dmarc_policy === 'none' ? 'monitoring only (p=none)' : `p=${posture.dmarc_policy || 'set'}`;
  return (
    <div className="mt-2.5 flex items-start gap-2 p-3 rounded-xl bg-gray-50 border border-gray-100 text-[12.5px] text-gray-600">
      <Mail className="w-3.5 h-3.5 mt-0.5 text-gray-400 shrink-0" />
      <span>
        Email: <b>{posture.email_provider || 'provider not identified'}</b> · SPF <b>{posture.spf ? 'present' : 'missing'}</b> · DMARC <b>{dmarc}</b>
      </span>
    </div>
  );
}

export default function BriefView({ brief, sources = [], posture }) {
  const painPoints = brief.pain_points || [];
  return (
    <div className="space-y-6">
      <Section title="Company">
        <p className="text-[14px] text-gray-800 leading-relaxed">{brief.company_summary || 'No summary available.'}</p>
        {(brief.industry || brief.size_hint) && (
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            {brief.industry && <span className="px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 text-[12px] font-semibold">{brief.industry}</span>}
            {brief.size_hint && <span className="px-2 py-0.5 rounded-md bg-gray-100 text-gray-600 text-[12px] font-semibold">{brief.size_hint}</span>}
          </div>
        )}
      </Section>

      {brief.suggested_opening && (
        <div className="p-4 rounded-xl bg-blue-50 border border-blue-100">
          <Section icon={Lightbulb} title="Suggested opening" tone="text-blue-600">
            <p className="text-[14px] text-gray-800 leading-relaxed">{brief.suggested_opening}</p>
          </Section>
        </div>
      )}

      {painPoints.length > 0 && (
        <Section title="Likely pain points">
          <div className="space-y-2.5">
            {painPoints.map((p, i) => {
              const href = safeHref(p.source_url);
              return (
                <div key={i} className="p-3 rounded-xl border border-gray-200 bg-white">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[13.5px] font-semibold text-gray-800">{p.point}</p>
                    <span className={`shrink-0 px-2 py-0.5 rounded-md text-[11px] font-semibold ${CONFIDENCE_STYLES[p.confidence] || CONFIDENCE_STYLES.low}`}>
                      {p.confidence}
                    </span>
                  </div>
                  {p.evidence && <p className="text-[12.5px] text-gray-500 mt-1 leading-relaxed">{p.evidence}</p>}
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 mt-1.5 text-[12px] text-blue-500 hover:text-blue-700 font-medium">
                      <ExternalLink className="w-3 h-3" />Source
                    </a>
                  )}
                  {!href && p.source_url?.startsWith('dns:') && (
                    <span className="inline-block mt-1.5 text-[12px] text-gray-400">Source: public DNS records</span>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {(brief.it_posture || brief.technologies?.length > 0 || posture) && (
        <Section title="Technology & IT posture">
          {brief.it_posture && <p className="text-[13.5px] text-gray-700 leading-relaxed">{brief.it_posture}</p>}
          {brief.technologies?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              {brief.technologies.map((t) => <span key={t} className="px-2 py-0.5 rounded-md bg-gray-100 text-gray-600 text-[12px] font-medium">{t}</span>)}
            </div>
          )}
          <EmailSetup posture={posture} />
        </Section>
      )}

      {brief.discovery_questions?.length > 0 && (
        <Section icon={HelpCircle} title="Discovery questions" tone="text-teal-600"><List items={brief.discovery_questions} /></Section>
      )}
      {brief.objection_prep?.length > 0 && (
        <Section icon={ShieldAlert} title="Objection prep" tone="text-amber-600"><List items={brief.objection_prep} /></Section>
      )}
      {brief.relevant_projects?.length > 0 && (
        <Section icon={Briefcase} title="From our portfolio" tone="text-indigo-600"><List items={brief.relevant_projects} /></Section>
      )}
      {brief.do_not_say?.length > 0 && (
        <Section title="Avoid saying" tone="text-red-500"><List items={brief.do_not_say} /></Section>
      )}

      {brief.gaps?.length > 0 && (
        <Section icon={AlertCircle} title="Couldn't find">
          <ul className="space-y-1">
            {brief.gaps.map((g, i) => <li key={i} className="text-[12.5px] text-gray-400">{g}</li>)}
          </ul>
        </Section>
      )}

      {sources.length > 0 && (
        <Section icon={Link2} title={`Sources (${sources.length} pages read)`}>
          <ul className="space-y-1">
            {sources.map((s) => {
              const href = safeHref(s.url);
              return (
                <li key={s.url} className="text-[12.5px] truncate">
                  {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:text-blue-700">{s.title || s.url}</a> : s.url}
                </li>
              );
            })}
          </ul>
        </Section>
      )}
    </div>
  );
}

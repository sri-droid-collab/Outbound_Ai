import { LEAD_TEXT_FIELDS, PRIORITY_OPTIONS } from '../leadForm';

const INPUT_CLASS =
  'w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all';
const LABEL_CLASS = 'block text-[13px] font-semibold text-gray-500 mb-1.5';

export default function LeadFields({ website, lead, onWebsiteChange, onLeadChange }) {
  // The ERP can hold priorities beyond the three we offer - keep the stored one selectable.
  const priorities = lead.priority && !PRIORITY_OPTIONS.includes(lead.priority)
    ? [...PRIORITY_OPTIONS, lead.priority]
    : PRIORITY_OPTIONS;

  return (
    <div className="space-y-4 pt-1">
      <div>
        <label className={LABEL_CLASS}>Website</label>
        <input
          type="text"
          value={website}
          onChange={(e) => onWebsiteChange(e.target.value)}
          placeholder="acme.com (used by lead research)"
          className={INPUT_CLASS}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={LABEL_CLASS}>Priority</label>
          <select
            value={lead.priority}
            onChange={(e) => onLeadChange({ ...lead, priority: e.target.value })}
            className={INPUT_CLASS}
          >
            <option value="">—</option>
            {priorities.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        {LEAD_TEXT_FIELDS.map((f) => (
          <div key={f.key}>
            <label className={LABEL_CLASS}>{f.label}</label>
            <input
              type="text"
              value={lead[f.key]}
              onChange={(e) => onLeadChange({ ...lead, [f.key]: e.target.value })}
              placeholder={f.placeholder}
              className={INPUT_CLASS}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

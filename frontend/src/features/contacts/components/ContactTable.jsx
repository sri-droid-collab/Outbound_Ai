import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import {
  Plus, Search, Trash2, X, PhoneCall, Loader2, Phone, Users, Building2, TrendingUp,
  FileSpreadsheet, Upload, CheckCircle2, AlertCircle, Check, Rocket, Pencil
} from 'lucide-react';
import { useDialer } from '../../calls/hooks/useDialer';
import { getContacts, createContact, updateContact, deleteContact, uploadClientsExcel } from '../api';
import LeadFields from './LeadFields';
import { EMPTY_LEAD_FORM, PRIORITY_STYLES, leadFormFrom } from '../leadForm';
import ResearchButton from '../../lead-research/components/ResearchButton';
import ResearchPanel from '../../lead-research/components/ResearchPanel';
import { useResearchStatuses } from '../../lead-research/hooks/useResearchStatuses';

const STATUS_STYLES = {
  new: 'bg-blue-50 text-blue-600',
  called: 'bg-emerald-50 text-emerald-600',
  follow_up: 'bg-amber-50 text-amber-600',
  closed: 'bg-gray-100 text-gray-500',
};
const STATUS_LABELS = { new: 'New', called: 'Called', follow_up: 'Follow Up', closed: 'Closed' };

const EMPTY_FORM = { name: '', phone: '', secondary_phone: '', company: '', website: '', notes: '', lead: EMPTY_LEAD_FORM };

const COUNTRY_CODES = [
  { label: 'India (+91)', code: '+91' },
  { label: 'United States / Canada (+1)', code: '+1' },
  { label: 'United Kingdom (+44)', code: '+44' },
  { label: 'United Arab Emirates (+971)', code: '+971' },
  { label: 'Singapore (+65)', code: '+65' },
  { label: 'Australia (+61)', code: '+61' },
  { label: 'Numbers already include country code', code: '' },
];

function Checkbox({ checked, onChange, title }) {
  return (
    <button
      type="button"
      title={title}
      onClick={(e) => { e.stopPropagation(); onChange(); }}
      className={`w-[18px] h-[18px] rounded-md border-2 flex items-center justify-center transition-all shrink-0 ${
        checked ? 'bg-blue-600 border-blue-600' : 'border-gray-300 hover:border-blue-400'
      }`}
    >
      {checked && <Check className="w-3 h-3 text-white" strokeWidth={3} />}
    </button>
  );
}

export default function ContactTable({ onCallContact, makeCall, deviceReady, onStartPowerCall, sessionActive }) {
  const [contacts, setContacts] = useState([]);
  const [search, setSearch] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [loading, setLoading] = useState(true);
  const [callingId, setCallingId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [callTarget, setCallTarget] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
  const [editForm, setEditForm] = useState({ ...EMPTY_FORM, status: 'new' });
  const [saving, setSaving] = useState(false);
  const [viewMode, setViewMode] = useState('table');
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [importError, setImportError] = useState('');
  const [importCountryCode, setImportCountryCode] = useState('+91');
  const [selected, setSelected] = useState(new Set());
  const [showPowerCallConfirm, setShowPowerCallConfirm] = useState(false);
  const [researchTarget, setResearchTarget] = useState(null);
  const { placeCall } = useDialer(makeCall);
  const { statusByContact: researchStatus, refresh: refreshResearchStatuses } = useResearchStatuses();

  const fetchContacts = async () => {
    try { setContacts(await getContacts()); }
    catch (err) { console.error(err); }
    finally { setLoading(false); }
  };
  useEffect(() => { fetchContacts(); }, []);

  const addContact = async () => {
    if (!form.name || !form.phone) return;
    try {
      const ok = await createContact(form);
      if (ok) { setForm(EMPTY_FORM); setShowAdd(false); fetchContacts(); }
    } catch (err) { console.error(err); }
  };

  const removeContact = async (id) => {
    try { await deleteContact(id); fetchContacts(); }
    catch (err) { console.error(err); }
  };

  const openEdit = (contact) => {
    setEditTarget(contact);
    setEditForm({
      name: contact.name,
      phone: contact.phone,
      secondary_phone: contact.secondary_phone || '',
      company: contact.company || '',
      website: contact.website || '',
      notes: contact.notes || '',
      status: contact.status,
      lead: leadFormFrom(contact.lead),
    });
  };

  const saveEdit = async () => {
    if (!editTarget || !editForm.name || !editForm.phone || saving) return;
    setSaving(true);
    try {
      const ok = await updateContact(editTarget.id, editForm);
      if (ok) { setEditTarget(null); fetchContacts(); }
    } catch (err) { console.error(err); }
    finally { setSaving(false); }
  };

  const closeResearch = () => { setResearchTarget(null); refreshResearchStatuses(); };

  // Saves the website the research panel asked for, then refreshes the list so
  // the new value is on the contact. Resolves to whether the save worked.
  const saveResearchWebsite = async (contact, website) => {
    try {
      const ok = await updateContact(contact.id, { website });
      if (ok) fetchContacts();
      return ok;
    } catch (err) {
      console.error(err);
      return false;
    }
  };

  const confirmCall = async () => {
    if (!callTarget) return;
    const contact = callTarget;
    setCallTarget(null);
    setCallingId(contact.id);
    try {
      const { callId } = await placeCall(contact);
      onCallContact(contact, callId);
    } catch (err) { console.error(err); }
    finally { setCallingId(null); }
  };

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const pickImportFile = (file) => {
    setImportError('');
    setImportResult(null);
    if (!file) { setImportFile(null); return; }
    if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
      setImportFile(null);
      setImportError('Please choose an Excel file (.xlsx).');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setImportFile(null);
      setImportError('File is too large. Maximum size is 5 MB.');
      return;
    }
    setImportFile(file);
  };

  const uploadImport = async () => {
    if (!importFile || importing) return;
    setImporting(true);
    setImportError('');
    try {
      const { ok, data } = await uploadClientsExcel(importFile, importCountryCode);
      if (!ok) {
        setImportError(data.detail || 'Upload failed. Please try again.');
      } else {
        setImportResult(data);
        setImportFile(null);
        fetchContacts();
      }
    } catch (err) {
      console.error(err);
      setImportError('Upload failed. Check your connection and try again.');
    } finally {
      setImporting(false);
    }
  };

  const closeImport = () => {
    setShowImport(false);
    setImportFile(null);
    setImportResult(null);
    setImportError('');
  };

  const filtered = contacts.filter((c) =>
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    c.phone.includes(search) ||
    c.company.toLowerCase().includes(search.toLowerCase())
  );

  const allFilteredSelected = filtered.length > 0 && filtered.every((c) => selected.has(c.id));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      filtered.forEach((c) => (allFilteredSelected ? next.delete(c.id) : next.add(c.id)));
      return next;
    });
  };
  const selectedContacts = contacts.filter((c) => selected.has(c.id));
  const startPowerCallSession = () => {
    onStartPowerCall(selectedContacts);
    setSelected(new Set());
    setShowPowerCallConfirm(false);
  };

  const stats = {
    total: contacts.length,
    new: contacts.filter(c => c.status === 'new').length,
    called: contacts.filter(c => c.status === 'called').length,
    followUp: contacts.filter(c => c.status === 'follow_up').length,
  };

  return (
    <div className="py-8 anim-enter">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4 mb-8 anim-enter">
        {[
          { label: 'Total Contacts', value: stats.total, icon: Users, color: 'blue' },
          { label: 'New Leads', value: stats.new, icon: TrendingUp, color: 'blue' },
          { label: 'Called', value: stats.called, icon: Phone, color: 'emerald' },
          { label: 'Follow Up', value: stats.followUp, icon: Building2, color: 'amber' },
        ].map((stat, i) => (
          <div key={stat.label} className={`card hover-glow p-5 anim-enter delay-${i+1}`}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[13px] font-semibold text-gray-400 uppercase tracking-wider">{stat.label}</span>
              <div className={`w-8 h-8 rounded-lg bg-${stat.color}-50 flex items-center justify-center`}>
                <stat.icon className={`w-4 h-4 text-${stat.color}-500`} />
              </div>
            </div>
            <p className="text-[30px] font-extrabold text-gray-900 leading-none">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search contacts..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-11 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all"
          />
        </div>
        <div className="flex items-center gap-3">
          {/* View toggle */}
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            <button onClick={() => setViewMode('table')} className={`px-3 py-1.5 rounded-md text-[13px] font-semibold transition-all ${viewMode === 'table' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400'}`}>
              Table
            </button>
            <button onClick={() => setViewMode('cards')} className={`px-3 py-1.5 rounded-md text-[13px] font-semibold transition-all ${viewMode === 'cards' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400'}`}>
              Cards
            </button>
          </div>
          <button onClick={() => setShowImport(true)} className="flex items-center gap-2 px-5 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-xl text-[15px] font-semibold hover:bg-gray-50 hover:border-gray-300 transition-all">
            <FileSpreadsheet className="w-4 h-4 text-emerald-600" />Import Excel
          </button>
          <button onClick={() => setShowAdd(true)} className="btn-primary flex items-center gap-2 px-5 py-2.5 text-[15px]">
            <Plus className="w-4 h-4" />Add Contact
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="flex items-center justify-between mb-6 px-5 py-3 bg-blue-50 border border-blue-100 rounded-xl anim-enter">
          <div className="flex items-center gap-3">
            <span className="text-[14px] font-semibold text-blue-700">{selected.size} selected</span>
            <button onClick={() => setSelected(new Set())} className="text-[13px] text-blue-500 hover:text-blue-700 font-medium">
              Clear
            </button>
          </div>
          <button
            onClick={() => setShowPowerCallConfirm(true)}
            disabled={sessionActive || !deviceReady}
            title={sessionActive ? 'A power call session is already running' : !deviceReady ? 'Waiting for phone to connect' : ''}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-[13px] font-semibold transition-all disabled:opacity-40"
          >
            <Rocket className="w-4 h-4" />Start Power Call
          </button>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="card flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 animate-spin text-blue-500 mr-3" />
          <span className="text-[15px] text-gray-400 font-medium">Loading contacts...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-24">
          <Users className="w-12 h-12 text-gray-200 mb-4" />
          <p className="text-[15px] text-gray-400 font-medium">{contacts.length === 0 ? 'No contacts yet. Add your first!' : 'No results found.'}</p>
        </div>
      ) : viewMode === 'cards' ? (
        /* Card View */
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((contact, i) => (
            <div key={contact.id} className={`card card-hover hover-glow p-5 anim-enter delay-${Math.min(i % 6 + 1, 4)}`}>
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Checkbox checked={selected.has(contact.id)} onChange={() => toggleSelect(contact.id)} title="Select for power calling" />
                  <div className="w-11 h-11 rounded-xl bg-blue-50 flex items-center justify-center">
                    <span className="text-[15px] font-bold text-blue-600">{contact.name.charAt(0).toUpperCase()}</span>
                  </div>
                  <div>
                    <p className="text-[15px] font-bold text-gray-900">{contact.name}</p>
                    <p className="text-[13px] text-gray-400 font-mono">{contact.phone}</p>
                    {contact.secondary_phone && (
                      <p className="text-[11px] text-gray-300 font-mono">alt: {contact.secondary_phone}</p>
                    )}
                  </div>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[12px] font-semibold ${STATUS_STYLES[contact.status]}`}>
                  {STATUS_LABELS[contact.status]}
                </span>
              </div>
              {contact.company && (
                <p className="text-[13px] text-gray-500 mb-4 flex items-center gap-1.5">
                  <Building2 className="w-3 h-3" />{contact.company}
                  {contact.lead?.priority && (
                    <span className={`ml-auto px-2 py-0.5 rounded-md text-[11px] font-semibold ${PRIORITY_STYLES[contact.lead.priority] || PRIORITY_STYLES.Low}`}>
                      {contact.lead.priority}
                    </span>
                  )}
                </p>
              )}
              <div className="flex items-center gap-2 pt-3 border-t border-gray-100">
                <ResearchButton status={researchStatus[contact.id]} onClick={() => setResearchTarget(contact)} />
                <button
                  onClick={() => setCallTarget(contact)}
                  disabled={callingId === contact.id || !deviceReady || sessionActive}
                  className="flex-1 flex items-center justify-center gap-2 py-2 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg text-[13px] font-semibold transition-all disabled:opacity-40"
                >
                  {callingId === contact.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PhoneCall className="w-3.5 h-3.5" />}
                  Call
                </button>
                <button onClick={() => openEdit(contact)} className="p-2 text-gray-300 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-all">
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => removeContact(contact.id)} className="p-2 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Table View */
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="text-left pl-6 pr-2 py-3.5 w-[38px]">
                  <Checkbox checked={allFilteredSelected} onChange={toggleSelectAll} title="Select all" />
                </th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Name</th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Phone</th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Company</th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Priority</th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Status</th>
                <th className="text-left px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Last Called</th>
                <th className="text-right px-6 py-3.5 text-[12px] font-bold text-gray-400 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((contact) => (
                <tr key={contact.id} className="row-hover group cursor-default">
                  <td className="pl-6 pr-2 py-3.5">
                    <Checkbox checked={selected.has(contact.id)} onChange={() => toggleSelect(contact.id)} title="Select for power calling" />
                  </td>
                  <td className="px-6 py-3.5">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center">
                        <span className="text-[13px] font-bold text-blue-600">{contact.name.charAt(0).toUpperCase()}</span>
                      </div>
                      <span className="text-[15px] font-semibold text-gray-800">{contact.name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-3.5 text-[13px] text-gray-500 font-mono">
                    {contact.phone}
                    {contact.secondary_phone && <div className="text-[11px] text-gray-300">alt: {contact.secondary_phone}</div>}
                  </td>
                  <td className="px-6 py-3.5 text-[15px] text-gray-500">
                    {contact.company || '—'}
                    {contact.lead?.source && <div className="text-[11px] text-gray-300">{contact.lead.source}</div>}
                  </td>
                  <td className="px-6 py-3.5">
                    {contact.lead?.priority ? (
                      <span className={`px-2.5 py-0.5 rounded-md text-[12px] font-semibold ${PRIORITY_STYLES[contact.lead.priority] || PRIORITY_STYLES.Low}`}>
                        {contact.lead.priority}
                      </span>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-6 py-3.5">
                    <span className={`px-2.5 py-0.5 rounded-md text-[12px] font-semibold ${STATUS_STYLES[contact.status]}`}>
                      {STATUS_LABELS[contact.status]}
                    </span>
                  </td>
                  <td className="px-6 py-3.5 text-[13px] text-gray-400">
                    {contact.last_called ? new Date(contact.last_called).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-6 py-3.5">
                    <div className="flex items-center justify-end gap-1.5">
                      <ResearchButton status={researchStatus[contact.id]} onClick={() => setResearchTarget(contact)} />
                      <button
                        onClick={() => setCallTarget(contact)}
                        disabled={callingId === contact.id || !deviceReady || sessionActive}
                        className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg text-[13px] font-semibold transition-all disabled:opacity-40"
                      >
                        {callingId === contact.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PhoneCall className="w-3.5 h-3.5" />}
                        Call
                      </button>
                      <button onClick={() => openEdit(contact)} className="p-2 text-gray-300 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-all opacity-0 group-hover:opacity-100">
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => removeContact(contact.id)} className="p-2 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add Contact Modal */}
      {showAdd && createPortal(
        <div className="fixed inset-0 bg-gray-900/20 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-7 w-full max-w-md max-h-[90vh] overflow-y-auto shadow-xl border border-gray-200 anim-modal">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-[17px] font-bold text-gray-900">New Contact</h3>
              <button onClick={() => setShowAdd(false)} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all">
                <X className="w-4.5 h-4.5" />
              </button>
            </div>
            <div className="space-y-4">
              {[
                { label: 'Full Name', key: 'name', placeholder: 'John Doe', req: true },
                { label: 'Phone Number', key: 'phone', placeholder: '+1234567890', req: true },
                { label: 'Secondary Phone', key: 'secondary_phone', placeholder: '+1234567890 (optional)' },
                { label: 'Company', key: 'company', placeholder: 'Acme Corp' },
              ].map((f) => (
                <div key={f.key}>
                  <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">
                    {f.label}{f.req && <span className="text-blue-500 ml-0.5">*</span>}
                  </label>
                  <input
                    type="text"
                    value={form[f.key]}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    placeholder={f.placeholder}
                    className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all"
                  />
                </div>
              ))}
              <LeadFields
                website={form.website}
                lead={form.lead}
                onWebsiteChange={(website) => setForm({ ...form, website })}
                onLeadChange={(lead) => setForm({ ...form, lead })}
              />
              <div>
                <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">Notes</label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="Any notes..."
                  rows={2}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all resize-none"
                />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowAdd(false)} className="flex-1 py-2.5 border border-gray-200 text-gray-500 rounded-xl text-[15px] font-semibold hover:bg-gray-50 transition-all text-center">
                Cancel
              </button>
              <button onClick={addContact} className="flex-1 py-2.5 btn-primary text-[15px] text-center">
                Add Contact
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Edit Contact Modal */}
      {editTarget && createPortal(
        <div className="fixed inset-0 bg-gray-900/20 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-7 w-full max-w-md max-h-[90vh] overflow-y-auto shadow-xl border border-gray-200 anim-modal">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-[17px] font-bold text-gray-900">Edit Contact</h3>
              <button onClick={() => setEditTarget(null)} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all">
                <X className="w-4.5 h-4.5" />
              </button>
            </div>
            <div className="space-y-4">
              {[
                { label: 'Full Name', key: 'name', placeholder: 'John Doe', req: true },
                { label: 'Phone Number', key: 'phone', placeholder: '+1234567890', req: true },
                { label: 'Secondary Phone', key: 'secondary_phone', placeholder: '+1234567890 (optional)' },
                { label: 'Company', key: 'company', placeholder: 'Acme Corp' },
              ].map((f) => (
                <div key={f.key}>
                  <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">
                    {f.label}{f.req && <span className="text-blue-500 ml-0.5">*</span>}
                  </label>
                  <input
                    type="text"
                    value={editForm[f.key]}
                    onChange={(e) => setEditForm({ ...editForm, [f.key]: e.target.value })}
                    placeholder={f.placeholder}
                    className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all"
                  />
                </div>
              ))}
              <LeadFields
                website={editForm.website}
                lead={editForm.lead}
                onWebsiteChange={(website) => setEditForm({ ...editForm, website })}
                onLeadChange={(lead) => setEditForm({ ...editForm, lead })}
              />
              <div>
                <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">Status</label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(STATUS_LABELS).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setEditForm({ ...editForm, status: value })}
                      className={`px-3 py-1.5 rounded-lg text-[13px] font-semibold transition-all ${
                        editForm.status === value ? STATUS_STYLES[value] + ' ring-2 ring-offset-1 ring-blue-200' : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">Notes</label>
                <textarea
                  value={editForm.notes}
                  onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                  placeholder="Any notes..."
                  rows={2}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all resize-none"
                />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setEditTarget(null)} className="flex-1 py-2.5 border border-gray-200 text-gray-500 rounded-xl text-[15px] font-semibold hover:bg-gray-50 transition-all text-center">
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={!editForm.name || !editForm.phone || saving}
                className="flex-1 py-2.5 btn-primary text-[15px] text-center disabled:opacity-40"
              >
                <span className="flex items-center justify-center gap-2">
                  {saving ? <><Loader2 className="w-4 h-4 animate-spin" />Saving...</> : 'Save Changes'}
                </span>
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Import Clients Modal */}
      {showImport && createPortal(
        <div className="fixed inset-0 bg-gray-900/20 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-7 w-full max-w-md shadow-xl border border-gray-200 anim-modal">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[17px] font-bold text-gray-900">Import Clients from Excel</h3>
              <button onClick={closeImport} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all">
                <X className="w-4.5 h-4.5" />
              </button>
            </div>
            <p className="text-[13px] text-gray-400 mb-5">
              Required columns: <span className="font-semibold text-gray-500">Lead Name, Mobile No</span>.
              Optional: Company Name, Webpage, Secondary Phone, Industries, Employees Size, Country, Branch, Source, Priority, Project.
              Imported leads appear as contacts and are matched to relevant projects automatically.
            </p>

            {!importResult && (
              <div className="mb-5">
                <label className="block text-[13px] font-semibold text-gray-500 mb-1.5">
                  Phone numbers in this file are in
                </label>
                <select
                  value={importCountryCode}
                  onChange={(e) => setImportCountryCode(e.target.value)}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-[15px] text-gray-800 focus:outline-none focus:border-blue-300 focus:ring-3 focus:ring-blue-100 transition-all"
                >
                  {COUNTRY_CODES.map((c) => (
                    <option key={c.label} value={c.code}>{c.label}</option>
                  ))}
                </select>
                <p className="text-[12px] text-gray-400 mt-1.5">
                  Applied to any number in the sheet that doesn't already start with a country code.
                </p>
              </div>
            )}

            {importResult ? (
              <div className="anim-enter">
                <div className="flex items-center gap-3 p-4 bg-emerald-50 border border-emerald-100 rounded-xl mb-4">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                  <div>
                    <p className="text-[14px] font-bold text-emerald-700">Import complete</p>
                    <p className="text-[13px] text-emerald-600">
                      {importResult.imported} imported · {importResult.updated} updated · {importResult.skipped} skipped
                    </p>
                  </div>
                </div>
                {importResult.errors?.length > 0 && (
                  <div className="mb-4 p-4 bg-amber-50 border border-amber-100 rounded-xl max-h-40 overflow-y-auto">
                    <p className="text-[12px] font-bold text-amber-600 uppercase tracking-wider mb-2">Skipped rows</p>
                    {importResult.errors.map((e, i) => (
                      <p key={i} className="text-[13px] text-amber-700">Row {e.row}: {e.message}</p>
                    ))}
                  </div>
                )}
                <button onClick={closeImport} className="w-full py-2.5 btn-primary text-[15px] text-center">Done</button>
              </div>
            ) : (
              <>
                <label className={`flex flex-col items-center justify-center gap-3 py-10 border-2 border-dashed rounded-xl cursor-pointer transition-all ${
                  importFile ? 'border-emerald-300 bg-emerald-50/50' : 'border-gray-200 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/40'
                }`}>
                  <input
                    type="file"
                    accept=".xlsx,.xlsm"
                    className="hidden"
                    onChange={(e) => pickImportFile(e.target.files?.[0])}
                    style={{ display: 'none' }}
                  />
                  {importFile ? (
                    <>
                      <FileSpreadsheet className="w-8 h-8 text-emerald-500" />
                      <div className="text-center">
                        <p className="text-[14px] font-semibold text-gray-700">{importFile.name}</p>
                        <p className="text-[12px] text-gray-400">{(importFile.size / 1024).toFixed(0)} KB · click to change</p>
                      </div>
                    </>
                  ) : (
                    <>
                      <Upload className="w-8 h-8 text-gray-300" />
                      <div className="text-center">
                        <p className="text-[14px] font-semibold text-gray-500">Click to choose an Excel file</p>
                        <p className="text-[12px] text-gray-400">.xlsx up to 5 MB</p>
                      </div>
                    </>
                  )}
                </label>

                {importError && (
                  <div className="flex items-center gap-2.5 mt-4 p-3.5 bg-red-50 border border-red-100 rounded-xl anim-enter">
                    <AlertCircle className="w-4 h-4 text-red-500 shrink-0" />
                    <p className="text-[13px] text-red-600 font-medium">{importError}</p>
                  </div>
                )}

                <div className="flex gap-3 mt-6">
                  <button onClick={closeImport} className="flex-1 py-2.5 border border-gray-200 text-gray-500 rounded-xl text-[15px] font-semibold hover:bg-gray-50 transition-all text-center">
                    Cancel
                  </button>
                  <button
                    onClick={uploadImport}
                    disabled={!importFile || importing}
                    className="flex-1 py-2.5 btn-primary text-[15px] text-center disabled:opacity-40"
                  >
                    <span className="flex items-center justify-center gap-2">
                      {importing ? <><Loader2 className="w-4 h-4 animate-spin" />Importing...</> : <><Upload className="w-4 h-4" />Import</>}
                    </span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>,
        document.body
      )}

      {/* Call Confirmation */}
      {callTarget && createPortal(
        <div className="fixed inset-0 bg-gray-900/20 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-7 w-full max-w-sm shadow-xl border border-gray-200 anim-modal">
            <h3 className="text-[17px] font-bold text-gray-900 mb-5">Start Call</h3>
            <div className="mb-6 flex items-center gap-4 p-4 bg-blue-50 rounded-xl">
              <div className="w-12 h-12 rounded-xl bg-blue-100 flex items-center justify-center">
                <PhoneCall className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <p className="text-[15px] font-bold text-gray-900">{callTarget.name}</p>
                <p className="text-[15px] text-gray-500 font-mono">{callTarget.phone}</p>
              </div>
            </div>
            <p className="text-[13px] text-gray-400 mb-6">Call will use your browser mic and speakers.</p>
            <div className="flex gap-3">
              <button onClick={() => setCallTarget(null)} className="flex-1 py-2.5 border border-gray-200 text-gray-500 rounded-xl text-[15px] font-semibold hover:bg-gray-50 transition-all text-center">
                Cancel
              </button>
              <button onClick={confirmCall} className="flex-1 py-2.5 bg-emerald-500 hover:bg-emerald-400 text-white rounded-xl text-[15px] font-semibold transition-all text-center shadow-md shadow-emerald-500/20 hover:shadow-emerald-500/30">
                <span className="flex items-center justify-center gap-2"><PhoneCall className="w-4 h-4" />Call Now</span>
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Lead research panel - closing it leaves the run going in the background */}
      {researchTarget && (
        <ResearchPanel
          key={researchTarget.id}
          contact={contacts.find((c) => c.id === researchTarget.id) || researchTarget}
          onClose={closeResearch}
          onSaveWebsite={saveResearchWebsite}
          onStarted={refreshResearchStatuses}
        />
      )}

      {/* Start Power Call Confirmation */}
      {showPowerCallConfirm && createPortal(
        <div className="fixed inset-0 bg-gray-900/20 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-7 w-full max-w-sm shadow-xl border border-gray-200 anim-modal">
            <h3 className="text-[17px] font-bold text-gray-900 mb-2">Start Power Call?</h3>
            <p className="text-[13px] text-gray-400 mb-5">
              Dials these {selectedContacts.length} contacts one after another, automatically moving to the next when a call ends.
            </p>
            <div className="max-h-40 overflow-y-auto mb-6 space-y-1.5">
              {selectedContacts.slice(0, 6).map((c) => (
                <div key={c.id} className="flex items-center gap-2 text-[13px] text-gray-600">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />{c.name}
                </div>
              ))}
              {selectedContacts.length > 6 && (
                <p className="text-[12px] text-gray-400">+ {selectedContacts.length - 6} more</p>
              )}
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowPowerCallConfirm(false)} className="flex-1 py-2.5 border border-gray-200 text-gray-500 rounded-xl text-[15px] font-semibold hover:bg-gray-50 transition-all text-center">
                Cancel
              </button>
              <button onClick={startPowerCallSession} className="flex-1 py-2.5 btn-primary text-[15px] text-center">
                <span className="flex items-center justify-center gap-2"><Rocket className="w-4 h-4" />Start</span>
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

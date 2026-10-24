import { FileSearch, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { ACTIVE_STATUSES } from '../hooks/useLeadResearch';

const BASE = 'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-semibold transition-all';

// One control that doubles as the status indicator, so the leads table needs no extra column.
export default function ResearchButton({ status, onClick }) {
  if (ACTIVE_STATUSES.includes(status)) {
    return (
      <button onClick={onClick} title="Research is running - click to view progress" className={`${BASE} bg-blue-50 text-blue-600`}>
        <Loader2 className="w-3.5 h-3.5 animate-spin" />Researching
      </button>
    );
  }
  if (status === 'done') {
    return (
      <button onClick={onClick} title="Open the research brief" className={`${BASE} bg-emerald-50 hover:bg-emerald-100 text-emerald-600`}>
        <CheckCircle2 className="w-3.5 h-3.5" />Brief
      </button>
    );
  }
  if (status === 'failed') {
    return (
      <button onClick={onClick} title="The last run failed - open to retry" className={`${BASE} bg-red-50 hover:bg-red-100 text-red-600`}>
        <AlertCircle className="w-3.5 h-3.5" />Retry
      </button>
    );
  }
  return (
    <button onClick={onClick} title="Research this lead's company" className={`${BASE} bg-gray-50 hover:bg-gray-100 text-gray-600`}>
      <FileSearch className="w-3.5 h-3.5" />Research
    </button>
  );
}

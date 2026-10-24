export const EMPTY_LEAD_FORM = { industries: '', employees_size: '', country: '', branch: '', source: '', priority: '' };

export const PRIORITY_STYLES = {
  High: 'bg-red-50 text-red-600',
  Medium: 'bg-amber-50 text-amber-600',
  Low: 'bg-gray-100 text-gray-500',
};

export const PRIORITY_OPTIONS = ['Low', 'Medium', 'High'];

export const LEAD_TEXT_FIELDS = [
  { key: 'industries', label: 'Industries', placeholder: 'IT Services and IT Consulting' },
  { key: 'employees_size', label: 'Employees Size', placeholder: '51-200 employees' },
  { key: 'country', label: 'Country', placeholder: 'India' },
  { key: 'branch', label: 'Branch', placeholder: 'Chennai' },
  { key: 'source', label: 'Source', placeholder: 'Linkedin-Sales' },
];

// Pick the editable lead fields out of a contact's `lead` object. The backend
// only writes the keys it receives, so anything not listed here is never touched.
export function leadFormFrom(lead) {
  return Object.fromEntries(Object.keys(EMPTY_LEAD_FORM).map((k) => [k, lead?.[k] || '']));
}

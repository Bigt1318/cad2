// ============================================================================
// FORD-CAD — EVENT LOG CONTROLLER (Module)
// Handles Event Log Viewer modal interactions
// ============================================================================

const EL = {};

EL.toggleAdd = function(force) {
  const add = document.getElementById('el-add-panel');
  const filters = document.getElementById('el-filters-panel');
  if (!add) return;

  const show = (typeof force === 'boolean') ? force : add.hasAttribute('hidden');

  if (show) {
    add.removeAttribute('hidden');
    if (filters) filters.setAttribute('hidden', '');
    setTimeout(() => document.getElementById('el-add-details')?.focus(), 0);
  } else {
    add.setAttribute('hidden', '');
  }
};

EL.toggleFilters = function(force) {
  const filters = document.getElementById('el-filters-panel');
  const add = document.getElementById('el-add-panel');
  if (!filters) return;

  const show = (typeof force === 'boolean') ? force : filters.hasAttribute('hidden');

  if (show) {
    filters.removeAttribute('hidden');
    if (add) add.setAttribute('hidden', '');
    setTimeout(() => document.getElementById('el-filter-from')?.focus(), 0);
  } else {
    filters.setAttribute('hidden', '');
  }
};

EL.exportPdf = function() {
  try {
    const filters = EL.getFilters();
    filters.limit = '2000';

    const params = new URLSearchParams(filters).toString();
    const url = '/api/eventlog/export_pdf?' + params;

    // No popups. Force download in the current tab context.
    const a = document.createElement('a');
    a.href = url;
    a.download = 'FORDCAD_EventLog.pdf';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    console.error('[EL] Export PDF failed:', e);
    alert('Export failed');
  }
};

EL.emailResults = async function() {
  const f = EL.getFilters();

  const subject = (`FORD-CAD Event Log ${f.from_date || ''}${(f.from_date || f.to_date) ? ' - ' : ''}${f.to_date || ''}`.trim()) || 'FORD-CAD Event Log';

  try {
    const params = new URLSearchParams({ ...f, limit: '120' }).toString();
    const res = await fetch('/api/eventlog/export?' + params, { headers: { 'Accept': 'application/json' } });
    const data = await res.json();

    const rows = Array.isArray(data?.rows) ? data.rows : [];
    const lines = [
      'FORD-CAD Event Log (filtered)',
      '',
      `From: ${f.from_date || '(any)'}`,
      `To: ${f.to_date || '(any)'}`,
      `Category: ${f.category || 'All'}`,
      `Unit: ${f.unit_id || 'Any'}`,
      `Search: ${f.q || '(none)'}`,
      `Issues Only: ${f.issues_only ? 'Yes' : 'No'}`,
      '',
      '--- Results (top 120) ---'
    ];

    rows.forEach(r => {
      const ts = r.timestamp || '';
      const cat = r.category || '';
      const unit = r.unit_id || '';
      const inc = (r.incident_number || r.incident_id || '') || '';
      const issue = r.issue_found ? '⚠ ' : '';
      const details = (r.details || '').replace(/\s+/g, ' ').trim();
      const user = r.user || '';
      lines.push(`${ts} | ${cat} | ${unit} | ${inc} | ${issue}${details} (${user})`);
    });

    if (data?.truncated) {
      lines.push('');
      lines.push('Note: Results truncated. Use “Export PDF” for a full printout.');
    } else {
      lines.push('');
      lines.push('Tip: Use “Export PDF” to save/attach a full PDF.');
    }

    const mailto = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n'))}`;
    window.location.href = mailto;
  } catch (e) {
    const fallbackLines = [
      'FORD-CAD Event Log (filtered)',
      '',
      `From: ${f.from_date || '(any)'}`,
      `To: ${f.to_date || '(any)'}`,
      `Category: ${f.category || 'All'}`,
      `Unit: ${f.unit_id || 'Any'}`,
      `Search: ${f.q || '(none)'}`,
      `Issues Only: ${f.issues_only ? 'Yes' : 'No'}`,
      '',
      'Tip: Use “Export PDF” in the Event Log viewer to print/save a PDF, then attach it to this email.'
    ];
    const mailto = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(fallbackLines.join('\n'))}`;
    window.location.href = mailto;
  }
};


EL.getFilters = function() {
  return {
    from_date: document.getElementById('el-filter-from')?.value || '',
    to_date: document.getElementById('el-filter-to')?.value || '',
    category: document.getElementById('el-filter-category')?.value || '',
    unit_id: document.getElementById('el-filter-unit')?.value || '',
    q: document.getElementById('el-filter-search')?.value || '',
    issues_only: document.getElementById('el-filter-issues')?.checked ? '1' : ''
  };
};

EL.refresh = function() {
  const filters = EL.getFilters();
  const params = new URLSearchParams(filters).toString();
  htmx.ajax('GET', '/panel/eventlog_rows?' + params, {
    target: '#el-table-body',
    swap: 'innerHTML'
  });
};

EL.applyFilters = function() {
  EL.refresh();
};

EL.clearFilters = function() {
  const fromEl = document.getElementById('el-filter-from');
  const toEl = document.getElementById('el-filter-to');
  
  // Reset to today/last week
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);
  
  if (fromEl) fromEl.value = weekAgo.toISOString().split('T')[0];
  if (toEl) toEl.value = today.toISOString().split('T')[0];
  
  const catEl = document.getElementById('el-filter-category');
  const unitEl = document.getElementById('el-filter-unit');
  const searchEl = document.getElementById('el-filter-search');
  const issuesEl = document.getElementById('el-filter-issues');
  
  if (catEl) catEl.value = '';
  if (unitEl) unitEl.value = '';
  if (searchEl) searchEl.value = '';
  if (issuesEl) issuesEl.checked = false;
  
  EL.refresh();
};

// Enter-to-apply when focus is inside Filters panel
// (prevents “why did nothing happen” when users hit Enter)
if (!document.body.dataset.elFilterEnterBound) {
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;

    const fp = document.getElementById('el-filters-panel');
    if (!fp) return;
    if (fp.hasAttribute('hidden')) return;

    const t = e.target;
    if (!t || !fp.contains(t)) return;

    const tag = (t.tagName || '').toUpperCase();
    if (tag === 'TEXTAREA') return;

    e.preventDefault();
    EL.applyFilters();
  });

  document.body.dataset.elFilterEnterBound = '1';
}


EL.addEntry = async function(e) {
  if (e) e.preventDefault();
  
  const details = document.getElementById('el-add-details')?.value?.trim();
  if (!details) {
    document.getElementById('el-add-details')?.focus();
    return false;
  }
  
  const payload = {
    subtype: document.getElementById('el-add-category')?.value || 'OTHER',
    unit_id: document.getElementById('el-add-unit')?.value?.trim() || null,
    incident_id: document.getElementById('el-add-incident')?.value?.trim() || null,
    details: details,
    issue_found: document.getElementById('el-add-issue')?.checked ? 1 : 0,
    user: 'Dispatcher'
  };
  
  try {
    const res = await fetch('/api/eventlog/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const data = await res.json();
    if (data.ok) {
      // Clear form fields
      const detailsEl = document.getElementById('el-add-details');
      const unitEl = document.getElementById('el-add-unit');
      const incEl = document.getElementById('el-add-incident');
      const issueEl = document.getElementById('el-add-issue');
      
      if (detailsEl) detailsEl.value = '';
      if (unitEl) unitEl.value = '';
      if (incEl) incEl.value = '';
      if (issueEl) issueEl.checked = false;
      
      // Trigger refresh
      document.body.dispatchEvent(new CustomEvent('eventlog-updated', { bubbles: true }));
    } else {
      alert(data.error || 'Failed to add entry');
    }
  } catch (err) {
    console.error('[EL] Add failed:', err);
    alert('Network error');
  }
  
  return false;
};

EL.toggleIssue = async function(logId, currentState) {
  try {
    const res = await fetch('/api/eventlog/' + logId + '/toggle_issue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issue_found: currentState ? 0 : 1 })
    });
    
    if (res.ok) {
      document.body.dispatchEvent(new CustomEvent('eventlog-updated', { bubbles: true }));
    }
  } catch (err) {
    console.error('[EL] Toggle issue failed:', err);
  }
};

EL.openIncident = function(incidentId) {
  if (!incidentId) return;
  
  if (window.CAD_MODAL?.close) {
    window.CAD_MODAL.close();
  }
  
  setTimeout(() => {
    if (window.IAW?.open) {
      window.IAW.open(incidentId);
    }
  }, 150);
};

EL.updateStatus = function(count, issueCount) {
  const countEl = document.getElementById('el-status-count');
  const issueEl = document.getElementById('el-status-issues');
  
  if (countEl) countEl.textContent = count + ' entries';
  if (issueEl) {
    if (issueCount > 0) {
      issueEl.innerHTML = '<span class="el-issue-badge">' + issueCount + ' issues</span>';
    } else {
      issueEl.textContent = '';
    }
  }
};

// Expose globally
window.EL = EL;


export default EL;

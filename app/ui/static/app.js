async function syncGmail() {
    const btn = document.querySelector('button[onclick="syncGmail()"]');
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/gmail/sync', { method: 'POST' });
        const data = await resp.json();
        const el = document.getElementById('sync-result');
        if (el) {
            if (data.task_id) {
                el.innerHTML = `<div class="alert alert-success alert-dismissible">Sync queued (task: ${data.task_id}) <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
                showJobStatusBanner();
            } else {
                el.innerHTML = `<div class="alert alert-info alert-dismissible">Sync status: ${JSON.stringify(data)} <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
            }
        }
    } catch (e) {
        const el = document.getElementById('sync-result');
        if (el) el.innerHTML = `<div class="alert alert-danger">Error: ${e.message}</div>`;
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function reprocess(receiptId) {
    if (!confirm('Reprocess this receipt?')) return;
    try {
        const resp = await fetch(`/receipts/${receiptId}/reprocess`, { method: 'POST' });
        const data = await resp.json();
        const el = document.getElementById('action-result');
        if (el) el.innerHTML = `<div class="alert alert-info">Reprocess queued: task ${data.task_id || JSON.stringify(data)}</div>`;
    } catch (e) {
        const el = document.getElementById('action-result');
        if (el) el.innerHTML = `<div class="alert alert-danger">Error: ${e.message}</div>`;
    }
}

async function resolveCard(event, receiptId) {
    event.preventDefault();
    const form = event.target;
    const cardId = form.card_id.value;
    if (!cardId) { alert('Please select a card'); return; }
    try {
        const resp = await fetch(`/receipts/${receiptId}/resolve-card?card_id=${cardId}`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            location.reload();
        } else {
            alert('Failed: ' + JSON.stringify(data));
        }
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function saveExtraction(event, receiptId) {
    event.preventDefault();
    const form = event.target;
    const el = document.getElementById('edit-result');
    const payload = {};
    const merchant = form.merchant.value.trim();
    if (merchant) payload.merchant = merchant;
    const purchaseDate = form.purchase_date.value;
    if (purchaseDate) payload.purchase_date = purchaseDate;
    const amount = form.amount.value;
    if (amount) payload.amount = parseFloat(amount);
    const currency = form.currency.value.trim();
    if (currency) payload.currency = currency;
    const cardLast4 = form.card_last4_seen.value.trim();
    if (cardLast4) payload.card_last4_seen = cardLast4;
    try {
        const resp = await fetch(`/receipts/${receiptId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            const data = await resp.json();
            // Update view-mode fields inline without page reload
            _updateExtractionView(data);
            if (el) {
                el.className = 'mt-2 small text-success';
                el.textContent = '✓ Saved.';
            }
            // Collapse edit form
            const collapseEl = document.getElementById('editForm');
            if (collapseEl) bootstrap.Collapse.getInstance(collapseEl)?.hide();
        } else {
            const err = await resp.json();
            if (el) {
                el.className = 'mt-2 small text-danger';
                el.textContent = '✗ ' + (err.detail || 'Save failed.');
            }
        }
    } catch (e) {
        if (el) {
            el.className = 'mt-2 small text-danger';
            el.textContent = '✗ Error: ' + e.message;
        }
    }
}

function _updateExtractionView(data) {
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val || '—';
    };
    set('view-merchant', data.merchant);
    set('view-purchase-date', data.purchase_date);
    if (data.amount != null) {
        const currency = data.currency || '';
        set('view-amount', `${parseFloat(data.amount).toFixed(2)}${currency ? ' ' + currency : ''}`);
    } else {
        set('view-amount', null);
    }
    set('view-card-last4', data.card_last4_seen);
}

// ── Job Status Banner ─────────────────────────────────────────────────────

const JOB_STATUS_ICONS = {running: '⏳', pending: '🕐', completed: '✅', failed: '❌'};
const JOB_TYPE_LABELS = {gmail_sync: 'Gmail Sync', process_receipt: 'Process Receipt', reprocess_receipt: 'Reprocess Receipt'};
const MAX_RECENT_JOBS = 5;

let _jobPollTimer = null;

function showJobStatusBanner() {
    const banner = document.getElementById('job-status-banner');
    if (banner) {
        banner.style.display = '';
        loadJobStatus();
    }
}

async function loadJobStatus() {
    const body = document.getElementById('job-status-body');
    if (!body) return;
    try {
        const resp = await fetch(`/jobs/recent?limit=${MAX_RECENT_JOBS}`);
        if (!resp.ok) return;
        const jobs = await resp.json();
        if (!jobs.length) {
            body.innerHTML = '<div class="text-muted small">No recent jobs.</div>';
            _stopJobPolling();
            return;
        }
        body.innerHTML = jobs.map(j => {
            const icon = JOB_STATUS_ICONS[j.status] || '❓';
            const label = JOB_TYPE_LABELS[j.job_type] || j.job_type;
            const started = j.started_at ? new Date(j.started_at).toLocaleString() : '';
            const errHtml = j.error_message ? `<br><small class="text-danger">${j.error_message}</small>` : '';
            const detailHtml = j.details ? `<br><small class="text-muted">${j.details}</small>` : '';
            const progressHtml = j.status === 'running'
                ? `<div class="progress mt-1" style="height:4px;min-width:80px"><div class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width:100%"></div></div>`
                : '';
            return `<div class="mb-1">
                <div class="d-flex align-items-center gap-2">
                    <span>${icon}</span>
                    <span class="fw-semibold small">${label}</span>
                    <span class="badge bg-${j.status === 'completed' ? 'success' : j.status === 'failed' ? 'danger' : j.status === 'running' ? 'info' : 'secondary'} small">${j.status}</span>
                    <span class="text-muted small">${started}</span>
                </div>
                ${progressHtml}${errHtml}${detailHtml}
            </div>`;
        }).join('');

        // Auto-poll while any job is running or pending
        const hasActive = jobs.some(j => j.status === 'running' || j.status === 'pending');
        if (hasActive) {
            _scheduleJobPoll();
        } else {
            _stopJobPolling();
        }
    } catch (e) {
        if (body) body.innerHTML = '<div class="text-muted small">Could not load job status.</div>';
    }
}

function _scheduleJobPoll() {
    if (_jobPollTimer) return; // already scheduled
    _jobPollTimer = setTimeout(() => {
        _jobPollTimer = null;
        loadJobStatus();
    }, 3000);
}

function _stopJobPolling() {
    if (_jobPollTimer) {
        clearTimeout(_jobPollTimer);
        _jobPollTimer = null;
    }
}

/** On page load: show the banner if there are recent active jobs. */
async function autoInitJobStatus() {
    try {
        const resp = await fetch(`/jobs/recent?limit=${MAX_RECENT_JOBS}`);
        if (!resp.ok) return;
        const jobs = await resp.json();
        const hasActive = jobs.some(j => j.status === 'running' || j.status === 'pending');
        if (hasActive) {
            showJobStatusBanner();
        }
    } catch (_) { /* ignore */ }
}

document.addEventListener('DOMContentLoaded', autoInitJobStatus);


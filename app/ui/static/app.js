async function syncGmail() {
    const btn = document.querySelector('button[onclick="syncGmail()"]');
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/gmail/sync', { method: 'POST' });
        const data = await resp.json();
        const el = document.getElementById('sync-result');
        if (el) {
            if (data.task_id) {
                el.innerHTML = `<div class="alert alert-success">Sync queued (task: ${data.task_id})</div>`;
            } else {
                el.innerHTML = `<div class="alert alert-info">Sync status: ${JSON.stringify(data)}</div>`;
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
        if (el) el.innerHTML = `<div class="alert alert-info">Reprocess queued: ${JSON.stringify(data)}</div>`;
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

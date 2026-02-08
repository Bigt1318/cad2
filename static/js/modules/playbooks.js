/**
 * FORD-CAD Playbooks — Suggestion Accept/Dismiss UI
 * Listens for WebSocket playbook_suggestion messages and shows toast with actions.
 */
(function() {
    'use strict';

    const PB = window.CAD_PLAYBOOKS = {};

    /**
     * Show a playbook suggestion toast with Accept/Dismiss buttons.
     */
    PB.showSuggestion = function(data) {
        const container = document.getElementById('playbook-suggestions') || _createContainer();

        const div = document.createElement('div');
        div.className = 'pb-suggestion';
        div.style.cssText = 'background:#2d3748;border-left:3px solid #9f7aea;padding:10px 14px;margin-bottom:8px;border-radius:6px;display:flex;align-items:center;gap:10px;animation:pbSlideIn 0.3s;';

        const msg = data.message || data.playbook_name || 'Playbook suggestion';
        const pbId = data.playbook_id || '';
        const incId = data.incident_id || '';

        div.innerHTML =
            '<div style="flex:1;">' +
                '<div style="font-size:11px;color:#9f7aea;font-weight:600;margin-bottom:2px;">PLAYBOOK</div>' +
                '<div style="font-size:13px;color:#e2e8f0;">' + msg + '</div>' +
                (incId ? '<div style="font-size:11px;color:#64748b;">Incident #' + incId + '</div>' : '') +
            '</div>' +
            '<button onclick="CAD_PLAYBOOKS.accept(this,' + pbId + ')" style="background:#48bb78;color:#000;border:none;padding:5px 12px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;">Accept</button>' +
            '<button onclick="CAD_PLAYBOOKS.dismiss(this,' + pbId + ')" style="background:#4a5568;color:#a0aec0;border:none;padding:5px 12px;border-radius:4px;font-size:11px;cursor:pointer;">Dismiss</button>';

        container.appendChild(div);

        // Auto-dismiss after 60 seconds
        setTimeout(function() {
            if (div.parentNode) div.parentNode.removeChild(div);
        }, 60000);
    };

    PB.accept = function(btn, execId) {
        var row = btn.closest('.pb-suggestion');
        fetch('/api/playbooks/executions/' + execId + '/accept', { method: 'POST' })
            .then(function() { if (row) row.remove(); });
    };

    PB.dismiss = function(btn, execId) {
        var row = btn.closest('.pb-suggestion');
        fetch('/api/playbooks/executions/' + execId + '/dismiss', { method: 'POST' })
            .then(function() { if (row) row.remove(); });
    };

    function _createContainer() {
        var c = document.createElement('div');
        c.id = 'playbook-suggestions';
        c.style.cssText = 'position:fixed;top:60px;right:16px;width:380px;z-index:9999;';
        document.body.appendChild(c);
        return c;
    }

    // Hook into WS
    var origHandler = window._cadWSMessageHandler;
    window._cadWSMessageHandler = function(msg) {
        if (origHandler) origHandler(msg);
        if (msg && msg.type === 'playbook_suggestion' && msg.data) {
            PB.showSuggestion(msg.data);
        }
        if (msg && msg.type === 'playbook_notification' && msg.data) {
            // Show as toast notification
            if (window.CAD_TOAST) {
                CAD_TOAST.show(msg.data.message || 'Playbook action', 'info');
            }
        }
    };

    console.log('[Playbooks] Module loaded');
})();

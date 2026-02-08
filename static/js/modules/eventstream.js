/**
 * FORD-CAD Event Stream — Live Timeline JS Module
 * Listens for WebSocket event_stream messages and updates the timeline in real-time.
 */
(function() {
    'use strict';

    const ES = window.ES_TIMELINE = window.ES_TIMELINE || {};

    // Track if user has scrolled up (pause auto-scroll)
    ES._autoScroll = true;
    ES._activeFilter = '';

    const SEVERITY_COLORS = {
        info: '#4a5568',
        warning: '#d69e2e',
        alert: '#e53e3e',
        critical: '#e53e3e'
    };

    const CATEGORY_ICONS = {
        incident: '&#x1F6A8;',
        unit: '&#x1F692;',
        narrative: '&#x1F4DD;',
        system: '&#x2699;',
        dailylog: '&#x1F4CB;',
        chat: '&#x1F4AC;'
    };

    /**
     * Inject a new event row at the top of the timeline table.
     */
    ES.addEvent = function(ev) {
        const tbody = document.getElementById('es-timeline-body');
        if (!tbody) return;

        // Apply active filter
        if (ES._activeFilter && ev.category !== ES._activeFilter) return;

        const sev = ev.severity || 'info';
        const cat = ev.category || 'system';
        const color = SEVERITY_COLORS[sev] || '#4a5568';
        const icon = CATEGORY_ICONS[cat] || '&#x2022;';
        const ts = ev.timestamp || '';
        const timePart = ts.length >= 19 ? ts.substring(11, 19) : ts;
        const pulse = sev === 'critical' ? ' class="critical-pulse"' : '';

        const tr = document.createElement('tr');
        tr.setAttribute('style', 'border-left:3px solid ' + color + ';');
        if (sev === 'critical') tr.className = 'critical-pulse';

        tr.innerHTML =
            '<td style="padding:4px 8px;font-size:11px;color:#999;">' + timePart + '</td>' +
            '<td style="padding:4px 6px;font-size:12px;">' + icon + '</td>' +
            '<td style="padding:4px 8px;font-size:11px;"><span style="background:' + color + ';color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">' + (ev.event_type || '') + '</span></td>' +
            '<td style="padding:4px 8px;font-size:11px;">' + (ev.incident_id || '') + '</td>' +
            '<td style="padding:4px 8px;font-size:11px;">' + (ev.unit_id || '') + '</td>' +
            '<td style="padding:4px 8px;font-size:11px;">' + (ev.summary || ev.event_type || '') + '</td>' +
            '<td style="padding:4px 8px;font-size:11px;color:#888;">' + (ev.user || '') + '</td>';

        // Flash effect
        tr.style.transition = 'background 0.5s';
        tr.style.background = 'rgba(99,179,237,0.15)';
        setTimeout(function() { tr.style.background = ''; }, 1500);

        tbody.insertBefore(tr, tbody.firstChild);

        // Cap rows at 200
        while (tbody.children.length > 200) {
            tbody.removeChild(tbody.lastChild);
        }

        // Browser notification for high-priority events when tab is hidden
        if (document.hidden && window.LAYOUT && window.LAYOUT.browserNotify) {
            var evType = (ev.event_type || '').toUpperCase();
            if (evType === 'UNIT_DISPATCHED' || evType === 'INCIDENT_CREATED' || evType === 'EMERGENCY') {
                window.LAYOUT.browserNotify(
                    evType.replace(/_/g, ' '),
                    (ev.summary || ev.event_type || '') + (ev.unit_id ? ' — ' + ev.unit_id : ''),
                    { tag: 'cad-event-' + (ev.incident_id || Date.now()) }
                );
            }
        }
    };

    /**
     * Hook into existing WebSocket message handler.
     */
    ES.initWSListener = function() {
        // Listen on CAD's existing WS if available
        const origHandler = window._cadWSMessageHandler;
        window._cadWSMessageHandler = function(msg) {
            if (origHandler) origHandler(msg);
            if (msg && msg.type === 'event_stream' && msg.data) {
                ES.addEvent(msg.data);
            }
        };

        // Also listen on messaging WS if available
        if (window.CAD_MESSAGING && window.CAD_MESSAGING.onMessage) {
            const origMsg = window.CAD_MESSAGING.onMessage;
            window.CAD_MESSAGING.onMessage = function(data) {
                origMsg(data);
                if (data && data.type === 'event_stream' && data.data) {
                    ES.addEvent(data.data);
                }
            };
        }
    };

    /**
     * Filter category (called from modal buttons).
     */
    ES.filterCategory = function(btn, cat) {
        ES._activeFilter = cat;
        document.querySelectorAll('.es-filter-chip').forEach(function(b) {
            b.classList.remove('es-active');
        });
        btn.classList.add('es-active');
        const url = cat
            ? '/partials/event-stream/rows?limit=100&category=' + encodeURIComponent(cat)
            : '/partials/event-stream/rows?limit=100';
        fetch(url).then(function(r) { return r.text(); }).then(function(html) {
            var tbody = document.getElementById('es-timeline-body');
            if (tbody) tbody.innerHTML = html;
        });
    };

    // Auto-init WS listener when module loads
    try { ES.initWSListener(); } catch(e) { /* safe */ }

    console.log('[EventStream] Module loaded');
})();

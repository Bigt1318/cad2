// ============================================================================
// FORD-CAD Messaging v2 — Channel-Based Real-Time Chat
// WebSocket: presence, channels, typing, ACK, edit/delete, reactions
// ============================================================================

const MessagingUI = {
    ws: null,
    userId: null,
    currentChannelId: null,
    presenceMap: {},
    pendingAttachments: [],
    drawerOpen: false,
    drawerTab: 'inbox',
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,
    reconnectDelay: 1000,
    typingTimeout: null,
    searchDebounce: null,
    contextMenuMsgId: null,
    offlineQueue: [],
    _channelsCache: [],
    _composeRecipients: [],
    _groupMembers: [],
    _replyToId: null,
    _mentionUnitsCache: [],
    _mentionActive: false,
    _mentionQuery: '',
    _mentionStartPos: -1,

    // =========================================================================
    // INITIALIZATION
    // =========================================================================

    init(userId) {
        this.userId = userId;
        this.connectWebSocket();
        this.loadChannels();
        this.restoreOfflineQueue();
        console.log('[Chat] Initialized for user:', userId);
    },

    // =========================================================================
    // WEBSOCKET
    // =========================================================================

    connectWebSocket() {
        if (!this.userId) return;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/chat?user_id=${encodeURIComponent(this.userId)}`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('[Chat] WebSocket connected');
                this.reconnectAttempts = 0;
                this.startHeartbeat();
                this.flushOfflineQueue();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.error('[Chat] Parse error:', e);
                }
            };

            this.ws.onclose = () => {
                this.stopHeartbeat();
                this.attemptReconnect();
            };

            this.ws.onerror = (err) => {
                console.error('[Chat] WebSocket error:', err);
            };
        } catch (e) {
            console.error('[Chat] Failed to create WebSocket:', e);
        }
    },

    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[Chat] Max reconnects reached');
            return;
        }
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        console.log(`[Chat] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connectWebSocket(), delay);
    },

    startHeartbeat() {
        this.heartbeatInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    },

    stopHeartbeat() {
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
    },

    wsSend(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    },

    // =========================================================================
    // MESSAGE ROUTING
    // =========================================================================

    handleMessage(data) {
        switch (data.type) {
            case 'connected':
                if (data.presence) {
                    this.presenceMap = data.presence;
                    this.updateAllPresenceDots();
                }
                break;

            case 'channel_message':
                this.onChannelMessage(data);
                break;

            case 'message_edited':
                this.onMessageEdited(data);
                break;

            case 'message_deleted':
                this.onMessageDeleted(data);
                break;

            case 'presence':
                this.onPresenceUpdate(data);
                break;

            case 'typing':
                this.onTyping(data);
                break;

            case 'receipt_update':
                this.onReceiptUpdate(data);
                break;

            case 'channel_updated':
                this.loadChannels();
                break;

            case 'ping':
                break;

            default:
                console.log('[Chat] Unknown type:', data.type);
        }
    },

    onChannelMessage(data) {
        const msg = data.message;
        const channelId = data.channel_id;

        // Update unread counts
        this.loadChannels();

        // If viewing this channel, append message
        if (this.currentChannelId === channelId) {
            this.appendMessageToThread(msg);
            // Mark as read
            this.wsSend({ type: 'read', channel_id: channelId });
        } else {
            this.showNotification(msg);
        }

        // Play sound for priority messages
        if (msg.priority === 'urgent') {
            window.SOUNDS?.priorityDispatch?.() || window.SOUNDS?.play?.('priority');
        } else if (msg.priority === 'emergency') {
            window.SOUNDS?.priorityDispatch?.() || window.SOUNDS?.play?.('emergency');
            this.showEmergencyFlash(msg);
        }
    },

    onMessageEdited(data) {
        const el = document.querySelector(`[data-msg-id="${data.message_id}"] .chat-msg-body`);
        if (el) {
            el.textContent = data.body;
            // Add edited label
            const bubble = el.closest('.chat-bubble');
            if (bubble && !bubble.querySelector('.chat-edited-label')) {
                const label = document.createElement('span');
                label.className = 'chat-edited-label';
                label.textContent = '(edited)';
                bubble.appendChild(label);
            }
        }
    },

    onMessageDeleted(data) {
        const el = document.querySelector(`[data-msg-id="${data.message_id}"]`);
        if (el) {
            const body = el.querySelector('.chat-msg-body');
            if (body) body.textContent = 'This message was deleted';
            el.style.opacity = '0.5';
        }
    },

    onPresenceUpdate(data) {
        this.presenceMap[data.user_id] = { status: data.status, last_seen: data.last_seen };
        this.updateAllPresenceDots();
    },

    onTyping(data) {
        if (data.channel_id === this.currentChannelId) {
            const el = document.getElementById('chat-typing');
            const who = document.getElementById('chat-typing-who');
            if (el && who) {
                who.textContent = data.user_id;
                el.style.display = 'flex';
                clearTimeout(this._typingHideTimeout);
                this._typingHideTimeout = setTimeout(() => {
                    el.style.display = 'none';
                }, 3000);
            }
        }
    },

    onReceiptUpdate(data) {
        // Could update check marks on messages
    },

    // =========================================================================
    // DRAWER
    // =========================================================================

    toggleDrawer() {
        const drawer = document.getElementById('chat-drawer');
        if (!drawer) {
            // Load drawer HTML first
            fetch('/modal/messaging')
                .then(r => r.text())
                .then(html => {
                    let container = document.getElementById('chat-drawer-container');
                    if (!container) {
                        container = document.createElement('div');
                        container.id = 'chat-drawer-container';
                        document.body.appendChild(container);
                    }
                    container.innerHTML = html;
                    setTimeout(() => {
                        this.drawerOpen = true;
                        document.getElementById('chat-drawer')?.classList.add('open');
                        this.loadChannels();
                    }, 50);
                });
            return;
        }

        this.drawerOpen = !this.drawerOpen;
        drawer.classList.toggle('open', this.drawerOpen);
        if (this.drawerOpen) this.loadChannels();
    },

    switchTab(tab) {
        this.drawerTab = tab;
        document.querySelectorAll('.chat-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        document.querySelectorAll('.chat-tab-content').forEach(c => c.classList.remove('active'));
        const tabEl = document.getElementById(`chat-tab-${tab}`);
        if (tabEl) tabEl.classList.add('active');

        // Hide search results
        const sr = document.getElementById('chat-search-results');
        if (sr) sr.style.display = 'none';
    },

    // =========================================================================
    // CHANNELS
    // =========================================================================

    async loadChannels() {
        try {
            const res = await fetch('/api/chat/channels');
            const data = await res.json();
            if (!data.ok) return;

            this._channelsCache = data.channels || [];
            if (data.presence) {
                this.presenceMap = data.presence;
                this.updateAllPresenceDots();
            }

            this.renderChannelLists(data.channels);
            this.updateUnreadBadges(data.channels);
        } catch (e) {
            console.error('[Chat] Failed to load channels:', e);
        }
    },

    renderChannelLists(channels) {
        const inbox = [];
        const chans = [];
        const alerts = [];

        for (const ch of channels) {
            if (ch.type === 'dm') {
                inbox.push(ch);
            } else {
                chans.push(ch);
            }
            // Priority messages go to alerts
            if (ch.last_message && (ch.last_message.priority === 'urgent' || ch.last_message.priority === 'emergency')) {
                alerts.push(ch);
            }
        }

        this.renderList('chat-inbox-list', inbox, 'dm');
        this.renderList('chat-channels-list', chans, 'channel');
        this.renderList('chat-alerts-list', alerts, 'alert');
    },

    renderList(containerId, channels, listType) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!channels.length) {
            container.innerHTML = `<div class="chat-empty-state"><p>No ${listType === 'dm' ? 'conversations' : listType === 'alert' ? 'alerts' : 'channels'} yet</p></div>`;
            return;
        }

        let html = '';
        for (const ch of channels) {
            const displayName = this.getChannelDisplayName(ch);
            const initials = this.getInitials(displayName);
            const iconClass = ch.type === 'incident' ? 'incident' : ch.type === 'shift' ? 'shift' : ch.type === 'ops' ? 'ops' : '';
            const preview = ch.last_message ? this.truncate(ch.last_message.body, 40) : 'No messages yet';
            const time = ch.last_message ? this.formatTime(ch.last_message.created_at) : '';
            const hasUnread = ch.unread_count > 0;

            // Get presence for DMs
            let presenceDot = '';
            if (ch.type === 'dm') {
                const otherUser = this.getDmOtherUser(ch);
                const status = this.presenceMap[otherUser]?.status || 'offline';
                presenceDot = `<span class="chat-presence-dot" data-status="${status}" data-user="${this.escapeAttr(otherUser)}"></span>`;
            }

            html += `
                <div class="chat-channel-item ${hasUnread ? 'has-unread' : ''} ${this.currentChannelId === ch.id ? 'active' : ''}"
                     data-channel-id="${ch.id}" onclick="MessagingUI.openChannel(${ch.id})">
                    <div class="chat-channel-icon ${iconClass}">
                        ${initials}
                        ${presenceDot}
                    </div>
                    <div class="chat-channel-info">
                        <div class="chat-channel-name">${this.escapeHtml(displayName)}</div>
                        <div class="chat-channel-preview">${this.escapeHtml(preview)}</div>
                    </div>
                    <div class="chat-channel-meta">
                        <span class="chat-channel-time">${time}</span>
                        ${hasUnread ? `<span class="chat-unread-count">${ch.unread_count}</span>` : ''}
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    },

    getChannelDisplayName(ch) {
        if (ch.type === 'dm') {
            // Parse DM key to get other user
            return this.getDmOtherUser(ch);
        }
        return ch.title || ch.key;
    },

    getDmOtherUser(ch) {
        // Key format: "dm:USER1:USER2"
        const parts = (ch.key || '').split(':');
        if (parts.length >= 3) {
            return parts[1] === this.userId ? parts[2] : parts[1];
        }
        return ch.title || 'DM';
    },

    getInitials(name) {
        if (!name) return '?';
        const words = name.split(/[\s-]+/);
        if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
        return name.substring(0, 2).toUpperCase();
    },

    updateUnreadBadges(channels) {
        let totalUnread = 0;
        let inboxUnread = 0;
        let alertCount = 0;

        for (const ch of channels) {
            totalUnread += ch.unread_count || 0;
            if (ch.type === 'dm') inboxUnread += ch.unread_count || 0;
            if (ch.last_message && (ch.last_message.priority === 'urgent' || ch.last_message.priority === 'emergency')) {
                alertCount++;
            }
        }

        this.setBadge('msg-unread-badge', totalUnread);
        this.setBadge('chat-total-unread', totalUnread);
        this.setBadge('chat-inbox-badge', inboxUnread);
        this.setBadge('chat-alerts-badge', alertCount);
    },

    setBadge(id, count) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = count;
            el.style.display = count > 0 ? 'inline-flex' : 'none';
        }
    },

    // =========================================================================
    // OPEN CHANNEL / THREAD
    // =========================================================================

    async openChannel(channelId) {
        this.currentChannelId = channelId;

        // Highlight in list
        document.querySelectorAll('.chat-channel-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.channelId) === channelId);
        });

        // Load thread fragment
        const container = document.getElementById('chat-thread-container');
        if (!container) return;

        try {
            const res = await fetch(`/api/chat/channel/${channelId}/fragment`);
            const html = await res.text();
            container.innerHTML = html;
            container.style.display = 'flex';

            // Scroll to bottom
            const msgList = document.getElementById('chat-msg-list');
            if (msgList) msgList.scrollTop = msgList.scrollHeight;

            // Subscribe to channel updates
            this.wsSend({ type: 'subscribe', channel_id: channelId });

            // Mark as read
            this.wsSend({ type: 'read', channel_id: channelId });
            fetch(`/api/chat/channel/${channelId}/read`, { method: 'POST' });
        } catch (e) {
            console.error('[Chat] Failed to open channel:', e);
        }
    },

    closeThread() {
        if (this.currentChannelId) {
            this.wsSend({ type: 'unsubscribe', channel_id: this.currentChannelId });
        }
        this.currentChannelId = null;
        const container = document.getElementById('chat-thread-container');
        if (container) {
            container.innerHTML = '';
            container.style.display = 'none';
        }
    },

    async openDM(unitId) {
        try {
            const res = await fetch(`/api/chat/dm/${unitId}`, { method: 'POST' });
            const data = await res.json();
            if (data.ok) {
                if (!this.drawerOpen) this.toggleDrawer();
                setTimeout(() => this.openChannel(data.channel.id), 300);
            }
        } catch (e) {
            console.error('[Chat] Failed to open DM:', e);
        }
    },

    // =========================================================================
    // SEND MESSAGES
    // =========================================================================

    async sendFromComposer(channelId) {
        const input = document.getElementById('chat-input');
        const priorityEl = document.getElementById('chat-priority-select');
        if (!input) return;

        const body = input.value.trim();
        if (!body) return;

        const priority = priorityEl ? priorityEl.value : 'normal';
        const requireAck = priority !== 'normal';

        // Check offline
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.queueOffline({ channelId, body, priority, requireAck });
            input.value = '';
            return;
        }

        try {
            const payload = {
                body: body,
                sender_name: this.userId,
                priority: priority,
                require_ack: requireAck,
                metadata: this.pendingAttachments.length ? { attachments: this.pendingAttachments } : null
            };

            // Include reply_to_id if replying
            if (this._replyToId) {
                payload.reply_to_id = this._replyToId;
            }

            const res = await fetch(`/api/chat/channel/${channelId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.ok) {
                input.value = '';
                this.autoResize(input);
                this.pendingAttachments = [];
                const filesEl = document.getElementById('chat-pending-files');
                if (filesEl) { filesEl.innerHTML = ''; filesEl.style.display = 'none'; }

                // Clear reply state
                this.cancelReply();

                // Append own message immediately
                this.appendMessageToThread(data.message);

                // Reset priority
                if (priorityEl) priorityEl.value = 'normal';
            }
        } catch (e) {
            console.error('[Chat] Send failed:', e);
            window.TOAST?.error?.('Failed to send message');
        }
    },

    handleKeyDown(event, channelId) {
        this.handleComposerKeyDown(event, channelId);
    },

    sendTyping() {
        if (this.typingTimeout) return;
        if (this.currentChannelId) {
            this.wsSend({ type: 'typing', channel_id: this.currentChannelId });
        }
        this.typingTimeout = setTimeout(() => { this.typingTimeout = null; }, 2000);
    },

    insertQuickReply(text) {
        const input = document.getElementById('chat-input');
        if (input) {
            input.value = text;
            input.focus();
        }
    },

    // =========================================================================
    // APPEND MESSAGE TO THREAD
    // =========================================================================

    appendMessageToThread(msg) {
        const list = document.getElementById('chat-msg-list');
        if (!list) return;

        const isMine = msg.sender_id === this.userId;
        const isSystem = msg.sender_type === 'system';

        let html = '';
        if (isSystem) {
            if (msg.msg_type && msg.msg_type.startsWith('card:')) {
                html = `<div class="chat-msg chat-msg-system" data-msg-id="${msg.id}">
                    <div class="chat-card"><div class="chat-card-body">${this.escapeHtml(msg.body)}</div>
                    <div class="chat-card-time">${(msg.created_at || '').substring(11, 16)}</div></div></div>`;
            } else {
                html = `<div class="chat-msg chat-msg-system" data-msg-id="${msg.id}">
                    <div class="chat-system-text">${this.escapeHtml(msg.body)}</div></div>`;
            }
        } else {
            const priorityClass = msg.priority === 'urgent' ? ' chat-msg-urgent' : msg.priority === 'emergency' ? ' chat-msg-emergency' : '';
            const bubbleClass = isMine ? 'chat-bubble-mine' : 'chat-bubble-other';
            const time = (msg.created_at || '').substring(11, 16);

            // Reply reference
            let replyRef = '';
            if (msg.reply_to_id) {
                replyRef = `<div class="chat-reply-ref" onclick="MessagingUI.scrollToMessage(${msg.reply_to_id})">Reply to #${msg.reply_to_id}</div>`;
            }

            html = `<div class="chat-msg ${isMine ? 'chat-msg-mine' : 'chat-msg-other'}${priorityClass}" data-msg-id="${msg.id}">
                ${!isMine ? `<div class="chat-msg-sender">${this.escapeHtml(msg.sender_name || msg.sender_id)}</div>` : ''}
                <div class="chat-bubble ${bubbleClass}">
                    ${replyRef}
                    <div class="chat-msg-body">${this.formatMentions(this.escapeHtml(msg.body))}</div>
                    <div class="chat-msg-footer">
                        <span class="chat-msg-time">${time}</span>
                        ${msg.priority !== 'normal' ? `<span class="chat-priority-tag ${msg.priority}">${msg.priority.toUpperCase()}</span>` : ''}
                        ${msg.require_ack && !isMine ? `<button class="chat-ack-btn" onclick="MessagingUI.ackMessage(${msg.id})">ACK</button>` : ''}
                    </div>
                </div>
            </div>`;
        }

        list.insertAdjacentHTML('beforeend', html);
        list.scrollTop = list.scrollHeight;
    },

    // =========================================================================
    // EDIT / DELETE
    // =========================================================================

    showContextMenu(event, msgId, isMine) {
        event.preventDefault();
        this.contextMenuMsgId = msgId;
        const menu = document.getElementById('chat-context-menu');
        if (!menu) return;

        // Show/hide options based on ownership
        menu.querySelectorAll('[data-action="edit"], [data-action="delete"]').forEach(btn => {
            btn.style.display = isMine ? 'block' : 'none';
        });

        menu.style.left = event.clientX + 'px';
        menu.style.top = event.clientY + 'px';
        menu.style.display = 'block';

        const hide = (e) => {
            if (!menu.contains(e.target)) {
                menu.style.display = 'none';
                document.removeEventListener('click', hide);
            }
        };
        setTimeout(() => document.addEventListener('click', hide), 10);
    },

    async editMessage() {
        const msgId = this.contextMenuMsgId;
        if (!msgId) return;
        document.getElementById('chat-context-menu').style.display = 'none';

        const el = document.querySelector(`[data-msg-id="${msgId}"] .chat-msg-body`);
        if (!el) return;

        const oldText = el.textContent;
        const newText = prompt('Edit message:', oldText);
        if (!newText || newText === oldText) return;

        try {
            const res = await fetch(`/api/chat/messages/${msgId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ body: newText })
            });
            const data = await res.json();
            if (data.ok) {
                el.textContent = data.message.body;
            }
        } catch (e) {
            console.error('[Chat] Edit failed:', e);
        }
    },

    async deleteMessage() {
        const msgId = this.contextMenuMsgId;
        if (!msgId) return;
        document.getElementById('chat-context-menu').style.display = 'none';

        if (!confirm('Delete this message?')) return;

        try {
            const res = await fetch(`/api/chat/messages/${msgId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.ok) {
                const el = document.querySelector(`[data-msg-id="${msgId}"]`);
                if (el) {
                    const body = el.querySelector('.chat-msg-body');
                    if (body) body.textContent = 'This message was deleted';
                    el.style.opacity = '0.5';
                }
            }
        } catch (e) {
            console.error('[Chat] Delete failed:', e);
        }
    },

    replyToMessage() {
        const msgId = this.contextMenuMsgId;
        document.getElementById('chat-context-menu').style.display = 'none';
        if (!msgId) return;

        // Get the message text for preview
        const msgEl = document.querySelector(`[data-msg-id="${msgId}"] .chat-msg-body`);
        const msgText = msgEl ? msgEl.textContent : `Message #${msgId}`;
        const senderEl = document.querySelector(`[data-msg-id="${msgId}"] .chat-msg-sender`);
        const senderName = senderEl ? senderEl.textContent : '';

        // Store reply state
        this._replyToId = msgId;

        // Show reply preview bar
        const preview = document.getElementById('chat-reply-preview');
        const previewText = document.getElementById('chat-reply-text');
        if (preview && previewText) {
            const label = senderName ? `${senderName}: ` : '';
            previewText.textContent = label + (msgText.length > 80 ? msgText.substring(0, 80) + '...' : msgText);
            preview.style.display = 'flex';
        }

        // Focus input
        const input = document.getElementById('chat-input');
        if (input) input.focus();
    },

    cancelReply() {
        this._replyToId = null;
        const preview = document.getElementById('chat-reply-preview');
        if (preview) preview.style.display = 'none';
    },

    // =========================================================================
    // ACK
    // =========================================================================

    ackMessage(msgId) {
        this.wsSend({ type: 'ack', message_id: msgId });
        // Remove ACK button
        const el = document.querySelector(`[data-msg-id="${msgId}"] .chat-ack-btn`);
        if (el) {
            el.textContent = 'ACK\'d';
            el.disabled = true;
            el.style.opacity = '0.5';
        }
        window.TOAST?.success?.('Message acknowledged');
    },

    // =========================================================================
    // REACTIONS
    // =========================================================================

    async toggleReaction(msgId, reaction) {
        try {
            const res = await fetch(`/api/chat/messages/${msgId}/react`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reaction })
            });
            const data = await res.json();
            if (data.ok) {
                this.renderReactions(msgId, data.reactions);
            }
        } catch (e) {
            console.error('[Chat] Reaction failed:', e);
        }
    },

    renderReactions(msgId, reactions) {
        const msgEl = document.querySelector(`[data-msg-id="${msgId}"]`);
        if (!msgEl) return;

        let container = msgEl.querySelector('.chat-reactions');
        if (!container) {
            container = document.createElement('div');
            container.className = 'chat-reactions';
            const bubble = msgEl.querySelector('.chat-bubble');
            if (bubble) bubble.parentElement.appendChild(container);
            else return;
        }

        if (!reactions.length) {
            container.remove();
            return;
        }

        container.innerHTML = reactions.map(r => {
            const isMine = r.users.includes(this.userId);
            return `<button class="chat-reaction-pill ${isMine ? 'chat-reaction-mine' : ''}"
                            onclick="MessagingUI.toggleReaction(${msgId}, '${r.reaction}')">
                ${r.reaction} ${r.count}
            </button>`;
        }).join('');
    },

    // =========================================================================
    // SEARCH
    // =========================================================================

    onSearchInput(query) {
        clearTimeout(this.searchDebounce);
        const sr = document.getElementById('chat-search-results');

        if (query.length < 2) {
            if (sr) sr.style.display = 'none';
            document.querySelectorAll('.chat-tab-content').forEach(c => {
                if (c.id === `chat-tab-${this.drawerTab}`) c.classList.add('active');
            });
            return;
        }

        this.searchDebounce = setTimeout(async () => {
            try {
                const res = await fetch(`/api/chat/search/fragment?q=${encodeURIComponent(query)}`);
                const html = await res.text();
                if (sr) {
                    sr.innerHTML = html;
                    sr.style.display = 'block';
                    document.querySelectorAll('.chat-tab-content').forEach(c => c.classList.remove('active'));
                }
            } catch (e) {
                console.error('[Chat] Search failed:', e);
            }
        }, 300);
    },

    // =========================================================================
    // PRESENCE
    // =========================================================================

    setMyStatus(status) {
        this.wsSend({ type: 'presence', status: status });
        fetch('/api/chat/presence', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });
    },

    updateAllPresenceDots() {
        document.querySelectorAll('.chat-presence-dot[data-user]').forEach(dot => {
            const uid = dot.dataset.user;
            const p = this.presenceMap[uid];
            if (p) dot.dataset.status = p.status || 'offline';
        });
    },

    // =========================================================================
    // COMPOSE MODAL
    // =========================================================================

    openCompose() {
        this._composeRecipients = [];
        if (window.CAD_MODAL && window.CAD_MODAL.open) {
            window.CAD_MODAL.open('/api/chat/group/create');
        }
    },

    async searchUnits(query) {
        if (query.length < 1) {
            document.getElementById('compose-suggestions').style.display = 'none';
            return;
        }
        try {
            const res = await fetch(`/api/chat/units/available`);
            const data = await res.json();
            const filtered = (data.units || []).filter(u =>
                u.unit_id.toLowerCase().includes(query.toLowerCase()) ||
                (u.unit_name || '').toLowerCase().includes(query.toLowerCase())
            );

            const container = document.getElementById('compose-suggestions');
            if (!container) return;

            if (!filtered.length) {
                container.style.display = 'none';
                return;
            }

            container.innerHTML = filtered.slice(0, 10).map(u =>
                `<div class="chat-suggestion-item" onclick="MessagingUI.addComposeRecipient('${u.unit_id}')">${u.unit_id} ${u.unit_name ? '- ' + u.unit_name : ''}</div>`
            ).join('');
            container.style.display = 'block';
        } catch (e) {
            console.error('[Chat] Unit search failed:', e);
        }
    },

    addComposeRecipient(unitId) {
        if (this._composeRecipients.includes(unitId)) return;
        this._composeRecipients.push(unitId);
        this.renderSelectedRecipients('compose-selected', this._composeRecipients, 'compose');
        const input = document.getElementById('compose-to');
        if (input) input.value = '';
        document.getElementById('compose-suggestions').style.display = 'none';
    },

    removeComposeRecipient(unitId) {
        this._composeRecipients = this._composeRecipients.filter(u => u !== unitId);
        this.renderSelectedRecipients('compose-selected', this._composeRecipients, 'compose');
    },

    renderSelectedRecipients(containerId, list, prefix) {
        const el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = list.map(uid =>
            `<span class="chat-recipient-chip">${uid} <span class="remove" onclick="MessagingUI.remove${prefix === 'compose' ? 'Compose' : 'Group'}Recipient('${uid}')">&times;</span></span>`
        ).join('');
    },

    async sendCompose() {
        const body = document.getElementById('compose-body')?.value.trim();
        const priority = document.querySelector('input[name="compose-priority"]:checked')?.value || 'normal';
        const requireAck = document.getElementById('compose-ack-required')?.checked || false;

        if (!this._composeRecipients.length || !body) {
            window.TOAST?.error?.('Recipient and message required');
            return;
        }

        for (const unitId of this._composeRecipients) {
            await this.openDM(unitId);
        }

        // Send to last opened DM
        if (this.currentChannelId) {
            await fetch(`/api/chat/channel/${this.currentChannelId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ body, priority, require_ack: requireAck, sender_name: this.userId })
            });
        }

        window.CAD_MODAL?.close?.();
        window.TOAST?.success?.('Message sent');
    },

    // =========================================================================
    // GROUP CREATE
    // =========================================================================

    openGroupCreate() {
        this._groupMembers = [];
        if (window.CAD_MODAL && window.CAD_MODAL.open) {
            window.CAD_MODAL.open('/api/chat/group/create');
        }
    },

    async searchGroupMembers(query) {
        await this.searchUnitsForPicker(query, 'group-suggestions', (uid) => this.addGroupMember(uid));
    },

    addGroupMember(unitId) {
        if (this._groupMembers.includes(unitId)) return;
        this._groupMembers.push(unitId);
        this.renderSelectedRecipients('group-selected-members', this._groupMembers, 'Group');
        const input = document.getElementById('group-member-search');
        if (input) input.value = '';
        document.getElementById('group-suggestions').style.display = 'none';
    },

    removeGroupRecipient(unitId) {
        this._groupMembers = this._groupMembers.filter(u => u !== unitId);
        this.renderSelectedRecipients('group-selected-members', this._groupMembers, 'Group');
    },

    async createGroup() {
        const title = document.getElementById('group-title')?.value.trim();
        if (!title) {
            window.TOAST?.error?.('Channel name required');
            return;
        }

        try {
            const res = await fetch('/api/chat/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, members: this._groupMembers })
            });
            const data = await res.json();
            if (data.ok) {
                window.CAD_MODAL?.close?.();
                window.TOAST?.success?.('Channel created');
                this.loadChannels();
                this.openChannel(data.channel.id);
            }
        } catch (e) {
            console.error('[Chat] Group create failed:', e);
        }
    },

    async searchUnitsForPicker(query, suggestionsId, onSelect) {
        if (query.length < 1) {
            document.getElementById(suggestionsId).style.display = 'none';
            return;
        }
        try {
            const res = await fetch('/api/chat/units/available');
            const data = await res.json();
            const filtered = (data.units || []).filter(u =>
                u.unit_id.toLowerCase().includes(query.toLowerCase())
            );
            const container = document.getElementById(suggestionsId);
            if (!container || !filtered.length) {
                if (container) container.style.display = 'none';
                return;
            }
            container.innerHTML = filtered.slice(0, 10).map(u =>
                `<div class="chat-suggestion-item" onclick="MessagingUI.addGroupMember('${u.unit_id}')">${u.unit_id}</div>`
            ).join('');
            container.style.display = 'block';
        } catch (e) {
            console.error('[Chat] Search failed:', e);
        }
    },

    // =========================================================================
    // BROADCAST
    // =========================================================================

    openBroadcast() {
        if (window.CAD_MODAL && window.CAD_MODAL.open) {
            window.CAD_MODAL.open('/api/chat/broadcast/form');
        }
    },

    updateBroadcastTargets() {
        const type = document.getElementById('bcast-target-type')?.value;
        const picker = document.getElementById('bcast-custom-picker');
        const allUnits = window._bcastAllUnits || [];
        const commandPrefixes = window._bcastCommandPrefixes || [];

        if (picker) picker.style.display = type === 'custom' ? 'block' : 'none';

        // Count targets
        let count = 0;
        if (type === 'all') {
            count = allUnits.length;
        } else if (type.startsWith('shift_')) {
            const shift = type.replace('shift_', '').toUpperCase();
            count = allUnits.filter(u => (u.shift || '').toUpperCase() === shift).length;
        } else if (type === 'command') {
            count = allUnits.filter(u => commandPrefixes.some(p => u.unit_id.toUpperCase().startsWith(p))).length;
        } else if (type === 'custom') {
            count = document.querySelectorAll('input[name="bcast-unit"]:checked').length;
        }

        const countEl = document.getElementById('bcast-count');
        if (countEl) countEl.textContent = count;
    },

    async sendBroadcast() {
        const type = document.getElementById('bcast-target-type')?.value;
        const body = document.getElementById('bcast-body')?.value.trim();
        const priority = document.querySelector('input[name="bcast-priority"]:checked')?.value || 'normal';
        const requireAck = document.getElementById('bcast-ack-required')?.checked || false;

        if (!body) {
            window.TOAST?.error?.('Message required');
            return;
        }

        const allUnits = window._bcastAllUnits || [];
        const commandPrefixes = window._bcastCommandPrefixes || [];
        let targets = [];

        if (type === 'all') {
            targets = allUnits.map(u => u.unit_id);
        } else if (type.startsWith('shift_')) {
            const shift = type.replace('shift_', '').toUpperCase();
            targets = allUnits.filter(u => (u.shift || '').toUpperCase() === shift).map(u => u.unit_id);
        } else if (type === 'command') {
            targets = allUnits.filter(u => commandPrefixes.some(p => u.unit_id.toUpperCase().startsWith(p))).map(u => u.unit_id);
        } else if (type === 'custom') {
            targets = Array.from(document.querySelectorAll('input[name="bcast-unit"]:checked')).map(cb => cb.value);
        }

        if (!targets.length) {
            window.TOAST?.error?.('No targets selected');
            return;
        }

        try {
            const res = await fetch('/api/chat/broadcast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ targets, body, priority, require_ack: requireAck, sender_name: this.userId })
            });
            const data = await res.json();
            if (data.ok) {
                window.CAD_MODAL?.close?.();
                window.TOAST?.success?.(`Broadcast sent to ${data.count} units`);
            }
        } catch (e) {
            console.error('[Chat] Broadcast failed:', e);
        }
    },

    // =========================================================================
    // FILE UPLOAD
    // =========================================================================

    async handleFileSelect(input) {
        const file = input.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/chat/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.ok) {
                this.pendingAttachments.push(data.attachment);
                this.renderPendingFiles();
            } else {
                window.TOAST?.error?.('Upload failed');
            }
        } catch (e) {
            console.error('[Chat] Upload failed:', e);
        }

        input.value = '';
    },

    renderPendingFiles() {
        const container = document.getElementById('chat-pending-files');
        if (!container) return;
        if (!this.pendingAttachments.length) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'flex';
        container.innerHTML = this.pendingAttachments.map((a, i) =>
            `<div class="chat-pending-file">${this.escapeHtml(a.filename)} <span class="remove" onclick="MessagingUI.removePendingFile(${i})">&times;</span></div>`
        ).join('');
    },

    removePendingFile(index) {
        this.pendingAttachments.splice(index, 1);
        this.renderPendingFiles();
    },

    // =========================================================================
    // LOAD MORE
    // =========================================================================

    async loadMore(channelId, beforeId) {
        try {
            const res = await fetch(`/api/chat/channel/${channelId}/messages?before=${beforeId}&limit=50`);
            const data = await res.json();
            if (data.ok && data.messages.length) {
                const list = document.getElementById('chat-msg-list');
                if (!list) return;
                const loadBtn = list.querySelector('.chat-load-more');
                const oldScrollHeight = list.scrollHeight;

                for (const msg of data.messages) {
                    const isMine = msg.sender_id === this.userId;
                    const isSystem = msg.sender_type === 'system';
                    let html = '';

                    if (isSystem) {
                        html = `<div class="chat-msg chat-msg-system" data-msg-id="${msg.id}">
                            <div class="chat-card"><div class="chat-card-body">${this.escapeHtml(msg.body)}</div></div></div>`;
                    } else {
                        const bubbleClass = isMine ? 'chat-bubble-mine' : 'chat-bubble-other';
                        html = `<div class="chat-msg ${isMine ? 'chat-msg-mine' : 'chat-msg-other'}" data-msg-id="${msg.id}">
                            ${!isMine ? `<div class="chat-msg-sender">${this.escapeHtml(msg.sender_name || msg.sender_id)}</div>` : ''}
                            <div class="chat-bubble ${bubbleClass}">
                                <div class="chat-msg-body">${this.escapeHtml(msg.body)}</div>
                                <div class="chat-msg-footer"><span class="chat-msg-time">${(msg.created_at || '').substring(11, 16)}</span></div>
                            </div></div>`;
                    }

                    if (loadBtn) {
                        loadBtn.insertAdjacentHTML('afterend', html);
                    } else {
                        list.insertAdjacentHTML('afterbegin', html);
                    }
                }

                // Remove load more if less than 50
                if (data.messages.length < 50 && loadBtn) loadBtn.remove();
                else if (loadBtn && data.messages.length) {
                    loadBtn.querySelector('button').setAttribute('onclick',
                        `MessagingUI.loadMore(${channelId}, ${data.messages[0].id})`);
                }

                // Maintain scroll position
                list.scrollTop = list.scrollHeight - oldScrollHeight;
            }
        } catch (e) {
            console.error('[Chat] Load more failed:', e);
        }
    },

    // =========================================================================
    // CHANNEL INFO
    // =========================================================================

    showChannelInfo(channelId) {
        if (window.CAD_MODAL && window.CAD_MODAL.open) {
            window.CAD_MODAL.open(`/api/chat/channel/${channelId}/info`);
        }
    },

    // =========================================================================
    // OFFLINE QUEUE
    // =========================================================================

    queueOffline(data) {
        this.offlineQueue.push(data);
        try { sessionStorage.setItem('chat_offline_queue', JSON.stringify(this.offlineQueue)); } catch (e) {}
        window.TOAST?.info?.('Message queued (offline)');
    },

    restoreOfflineQueue() {
        try {
            const stored = sessionStorage.getItem('chat_offline_queue');
            if (stored) this.offlineQueue = JSON.parse(stored);
        } catch (e) {}
    },

    async flushOfflineQueue() {
        if (!this.offlineQueue.length) return;
        const queue = [...this.offlineQueue];
        this.offlineQueue = [];
        sessionStorage.removeItem('chat_offline_queue');

        for (const item of queue) {
            try {
                await fetch(`/api/chat/channel/${item.channelId}/send`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        body: item.body,
                        priority: item.priority,
                        require_ack: item.requireAck,
                        sender_name: this.userId
                    })
                });
            } catch (e) {
                this.offlineQueue.push(item);
            }
        }
    },

    // =========================================================================
    // EMERGENCY FLASH
    // =========================================================================

    showEmergencyFlash(msg) {
        const flash = document.createElement('div');
        flash.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(220,38,38,0.15);z-index:99999;pointer-events:none;animation:chat-flash 0.5s 3';
        document.body.appendChild(flash);
        setTimeout(() => flash.remove(), 1500);

        window.TOAST?.error?.(`EMERGENCY: ${msg.sender_name || msg.sender_id}: ${msg.body.substring(0, 60)}`);
    },

    // =========================================================================
    // INCIDENT CHAT EMBED (for IAW)
    // =========================================================================

    async loadIncidentChat(incidentId, containerId) {
        try {
            // Create or get incident channel
            const res = await fetch(`/api/chat/channel/0/messages`); // placeholder
            // Actually, we need to create the channel first
            // This is handled server-side by the IAW loader
        } catch (e) {
            console.error('[Chat] Incident chat load failed:', e);
        }
    },

    async sendIncidentMessage(incidentId, channelId) {
        const input = document.getElementById(`iaw-chat-input-${incidentId}`);
        if (!input) return;
        const body = input.value.trim();
        if (!body) return;

        try {
            await fetch(`/api/chat/channel/${channelId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ body, sender_name: this.userId })
            });
            input.value = '';
            // Reload incident chat
            this.refreshIncidentChat(incidentId, channelId);
        } catch (e) {
            console.error('[Chat] Incident send failed:', e);
        }
    },

    async refreshIncidentChat(incidentId, channelId) {
        try {
            const res = await fetch(`/api/chat/channel/${channelId}/messages?limit=20`);
            const data = await res.json();
            if (!data.ok) return;

            const container = document.getElementById(`iaw-chat-messages-${incidentId}`);
            if (!container) return;

            container.innerHTML = data.messages.map(msg => {
                const isSystem = msg.sender_type === 'system';
                const isMine = msg.sender_id === this.userId;
                if (isSystem) {
                    return `<div class="chat-msg chat-msg-system" data-msg-id="${msg.id}">
                        <div class="chat-card"><div class="chat-card-body">${this.escapeHtml(msg.body)}</div></div></div>`;
                }
                return `<div class="chat-msg ${isMine ? 'chat-msg-mine' : 'chat-msg-other'}" data-msg-id="${msg.id}">
                    ${!isMine ? `<div class="chat-msg-sender">${this.escapeHtml(msg.sender_name || msg.sender_id)}</div>` : ''}
                    <div class="chat-bubble ${isMine ? 'chat-bubble-mine' : 'chat-bubble-other'}">
                        <div class="chat-msg-body">${this.escapeHtml(msg.body)}</div>
                    </div></div>`;
            }).join('');

            container.scrollTop = container.scrollHeight;
        } catch (e) {
            console.error('[Chat] Refresh failed:', e);
        }
    },

    // =========================================================================
    // SCROLL
    // =========================================================================

    onScroll(el) {
        // Could implement infinite scroll here
    },

    scrollToMessage(msgId) {
        const el = document.querySelector(`[data-msg-id="${msgId}"]`);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.style.background = 'var(--bg-active)';
            setTimeout(() => el.style.background = '', 2000);
        }
    },

    // =========================================================================
    // @MENTION SUPPORT
    // =========================================================================

    formatMentions(html) {
        // Replace @WORD patterns with styled mention spans
        // Matches @followed by alphanumeric, dash, or underscore (unit IDs like E1, CAR1, BATT1-4, etc.)
        return html.replace(/@([A-Za-z0-9_-]+)/g, '<span class="chat-mention" data-mention="$1">@$1</span>');
    },

    async loadMentionUnits() {
        // Cache unit list for mention autocomplete
        if (this._mentionUnitsCache.length > 0) return;
        try {
            const res = await fetch('/api/chat/units/available');
            const data = await res.json();
            this._mentionUnitsCache = (data.units || []).map(u => u.unit_id);
        } catch (e) {
            console.error('[Chat] Failed to load units for mentions:', e);
        }
    },

    handleComposerInput(textarea) {
        this.autoResize(textarea);
        this.sendTyping();

        // Detect @ for mention autocomplete
        const val = textarea.value;
        const cursorPos = textarea.selectionStart;

        // Find the @ sign before cursor
        let atPos = -1;
        for (let i = cursorPos - 1; i >= 0; i--) {
            if (val[i] === '@') {
                atPos = i;
                break;
            }
            // Stop searching at whitespace or start (except if it's the very character)
            if (val[i] === ' ' || val[i] === '\n') break;
        }

        const dropdown = document.getElementById('chat-mention-dropdown');
        if (!dropdown) return;

        if (atPos >= 0 && (atPos === 0 || /\s/.test(val[atPos - 1]))) {
            const query = val.substring(atPos + 1, cursorPos).toUpperCase();
            this._mentionActive = true;
            this._mentionQuery = query;
            this._mentionStartPos = atPos;

            this.loadMentionUnits().then(() => {
                const filtered = this._mentionUnitsCache.filter(u =>
                    u.toUpperCase().startsWith(query) || u.toUpperCase().includes(query)
                ).slice(0, 8);

                if (filtered.length === 0) {
                    dropdown.style.display = 'none';
                    this._mentionActive = false;
                    return;
                }

                dropdown.innerHTML = filtered.map((u, i) =>
                    `<div class="chat-mention-item ${i === 0 ? 'active' : ''}" data-unit="${this.escapeAttr(u)}" onclick="MessagingUI.acceptMention('${this.escapeAttr(u)}')">${this.escapeHtml(u)}</div>`
                ).join('');
                dropdown.style.display = 'block';
            });
        } else {
            dropdown.style.display = 'none';
            this._mentionActive = false;
        }
    },

    handleComposerKeyDown(event, channelId) {
        const dropdown = document.getElementById('chat-mention-dropdown');

        // Handle mention dropdown navigation
        if (this._mentionActive && dropdown && dropdown.style.display !== 'none') {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                const items = dropdown.querySelectorAll('.chat-mention-item');
                let activeIdx = -1;
                items.forEach((el, i) => { if (el.classList.contains('active')) activeIdx = i; });

                items.forEach(el => el.classList.remove('active'));
                if (event.key === 'ArrowDown') {
                    activeIdx = (activeIdx + 1) % items.length;
                } else {
                    activeIdx = activeIdx <= 0 ? items.length - 1 : activeIdx - 1;
                }
                items[activeIdx].classList.add('active');
                items[activeIdx].scrollIntoView({ block: 'nearest' });
                return;
            }

            if (event.key === 'Tab' || (event.key === 'Enter' && this._mentionActive)) {
                const active = dropdown.querySelector('.chat-mention-item.active');
                if (active) {
                    event.preventDefault();
                    this.acceptMention(active.dataset.unit);
                    return;
                }
            }

            if (event.key === 'Escape') {
                dropdown.style.display = 'none';
                this._mentionActive = false;
                return;
            }
        }

        // Normal Enter to send
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.sendFromComposer(channelId);
        }
    },

    acceptMention(unitId) {
        const input = document.getElementById('chat-input');
        const dropdown = document.getElementById('chat-mention-dropdown');
        if (!input) return;

        const val = input.value;
        const before = val.substring(0, this._mentionStartPos);
        const after = val.substring(input.selectionStart);
        input.value = before + '@' + unitId + ' ' + after;
        input.focus();

        // Place cursor after the inserted mention
        const newPos = this._mentionStartPos + unitId.length + 2; // @+unitId+space
        input.selectionStart = newPos;
        input.selectionEnd = newPos;

        if (dropdown) dropdown.style.display = 'none';
        this._mentionActive = false;
    },

    // =========================================================================
    // HELPERS
    // =========================================================================

    autoResize(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    escapeAttr(text) {
        return (text || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    truncate(text, max) {
        if (!text) return '';
        return text.length > max ? text.substring(0, max) + '...' : text;
    },

    formatTime(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        if (isToday) {
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    },

    showNotification(msg) {
        if (Notification.permission === 'granted') {
            new Notification(msg.sender_name || msg.sender_id || 'New Message', {
                body: msg.body,
                icon: '/static/images/ford-logo.png'
            });
        }
        window.TOAST?.info?.(`${msg.sender_name || msg.sender_id}: ${(msg.body || '').substring(0, 50)}`);
        window.SOUNDS?.play?.('notification');
    }
};

// Auto-initialize
document.addEventListener('DOMContentLoaded', () => {
    const userId = window.CAD_USER || document.body.dataset.userId;
    if (userId) {
        MessagingUI.init(userId);
    }
    if (Notification.permission === 'default') {
        Notification.requestPermission();
    }
});

window.MessagingUI = MessagingUI;

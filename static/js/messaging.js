// ============================================================================
// FORD-CAD Messaging — Client-Side Module
// WebSocket real-time messaging with SSE fallback
// ============================================================================

const MessagingUI = {
    ws: null,
    userId: null,
    currentConversationId: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,
    reconnectDelay: 1000,
    typingTimeout: null,

    // =========================================================================
    // INITIALIZATION
    // =========================================================================

    init(userId) {
        this.userId = userId;
        this.connectWebSocket();
        this.bindEvents();
        this.loadUnreadCount();

        console.log('[Messaging] Initialized for user:', userId);
    },

    // =========================================================================
    // WEBSOCKET CONNECTION
    // =========================================================================

    connectWebSocket() {
        if (!this.userId) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/messaging?user_id=${encodeURIComponent(this.userId)}`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('[Messaging] WebSocket connected');
                this.reconnectAttempts = 0;
                this.startHeartbeat();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.error('[Messaging] Failed to parse message:', e);
                }
            };

            this.ws.onclose = (event) => {
                console.log('[Messaging] WebSocket closed:', event.code);
                this.stopHeartbeat();
                this.attemptReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('[Messaging] WebSocket error:', error);
            };

        } catch (e) {
            console.error('[Messaging] Failed to create WebSocket:', e);
            this.fallbackToSSE();
        }
    },

    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[Messaging] Max reconnect attempts reached, falling back to SSE');
            this.fallbackToSSE();
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        console.log(`[Messaging] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => {
            this.connectWebSocket();
        }, delay);
    },

    fallbackToSSE() {
        console.log('[Messaging] Using SSE fallback');

        const eventSource = new EventSource(`/api/messaging/events`);

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('[Messaging] SSE parse error:', e);
            }
        };

        eventSource.onerror = (error) => {
            console.error('[Messaging] SSE error:', error);
            eventSource.close();
        };
    },

    startHeartbeat() {
        this.heartbeatInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    },

    stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }
    },

    // =========================================================================
    // MESSAGE HANDLING
    // =========================================================================

    handleMessage(data) {
        switch (data.type) {
            case 'new_message':
                this.onNewMessage(data);
                break;

            case 'inbound_message':
                this.onInboundMessage(data);
                break;

            case 'typing':
                this.onTypingIndicator(data);
                break;

            case 'message_status':
                this.onMessageStatus(data);
                break;

            case 'connected':
                console.log('[Messaging] Connection confirmed');
                break;

            case 'pong':
                // Heartbeat response
                break;

            default:
                console.log('[Messaging] Unknown message type:', data.type);
        }
    },

    onNewMessage(data) {
        // Update unread count
        this.loadUnreadCount();

        // If viewing this conversation, append message
        if (this.currentConversationId === data.conversation_id) {
            this.appendMessage(data);
            this.markConversationRead(data.conversation_id);
        } else {
            // Show notification
            this.showNotification(data);
        }

        // Update conversation list
        this.refreshConversationList();
    },

    onInboundMessage(data) {
        // External message received (SMS, email, etc.)
        this.loadUnreadCount();
        this.refreshConversationList();

        // Show notification
        this.showNotification({
            from_name: data.from_name || data.from_address,
            body: data.body,
            channel: data.channel,
        });
    },

    onTypingIndicator(data) {
        if (this.currentConversationId === data.conversation_id) {
            const indicator = document.getElementById('typing-indicator');
            if (indicator) {
                indicator.style.display = 'flex';
                indicator.querySelector('.typing-text').textContent = `${data.user_name || 'Someone'} is typing...`;

                // Hide after 3 seconds
                setTimeout(() => {
                    indicator.style.display = 'none';
                }, 3000);
            }
        }
    },

    onMessageStatus(data) {
        const msgEl = document.querySelector(`[data-message-id="${data.message_id}"]`);
        if (msgEl) {
            const statusEl = msgEl.querySelector('.message-status');
            if (statusEl) {
                statusEl.className = `message-status status-${data.status}`;
            }
        }
    },

    // =========================================================================
    // UI ACTIONS
    // =========================================================================

    openConversation(conversationId) {
        this.currentConversationId = conversationId;

        // Mark active in list
        document.querySelectorAll('.conversation-item').forEach(el => {
            el.classList.toggle('active', el.dataset.conversationId == conversationId);
        });

        // Mark as read after small delay
        setTimeout(() => {
            this.markConversationRead(conversationId);
        }, 500);
    },

    closeConversation() {
        this.currentConversationId = null;
        document.getElementById('conversation-view').innerHTML = '';
    },

    openCompose(to = null, channel = null) {
        let url = '/api/messaging/compose';
        const params = [];
        if (to) params.push(`to=${encodeURIComponent(to)}`);
        if (channel) params.push(`channel=${encodeURIComponent(channel)}`);
        if (params.length) url += '?' + params.join('&');

        // Use CAD_MODAL if available, otherwise fetch and inject
        if (window.CAD_MODAL && window.CAD_MODAL.open) {
            window.CAD_MODAL.open(url);
        } else {
            fetch(url)
                .then(r => r.text())
                .then(html => {
                    const container = document.getElementById('fordcad-modal-container');
                    if (container) {
                        container.innerHTML = `<div class="cad-modal-overlay" onclick="this.parentElement.innerHTML=''"></div>${html}`;
                        container.style.display = 'flex';
                    }
                });
        }
    },

    // =========================================================================
    // SEND ACTIONS
    // =========================================================================

    afterSend(event) {
        if (event.detail.successful) {
            // Clear input
            const form = event.target;
            const textarea = form.querySelector('textarea[name="message"]');
            if (textarea) {
                textarea.value = '';
                this.autoResize(textarea);
            }

            // Refresh conversation
            if (this.currentConversationId) {
                htmx.ajax('GET', `/api/messaging/conversation/${this.currentConversationId}/fragment`, {
                    target: '#conversation-view',
                    swap: 'innerHTML'
                });
            }
        } else {
            window.TOAST?.error?.('Failed to send message');
        }
    },

    afterComposeSend(event) {
        if (event.detail.successful) {
            const response = JSON.parse(event.detail.xhr.responseText);
            if (response.ok) {
                window.CAD_MODAL?.close?.();
                window.TOAST?.success?.('Message sent');
                this.refreshConversationList();

                // Open the conversation
                if (response.conversation_id) {
                    this.openConversation(response.conversation_id);
                }
            } else {
                window.TOAST?.error?.(response.error || 'Failed to send');
            }
        }
    },

    sendTyping(conversationId) {
        if (this.typingTimeout) {
            clearTimeout(this.typingTimeout);
        }

        // Send typing indicator
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'typing',
                conversation_id: conversationId
            }));
        }

        // Debounce
        this.typingTimeout = setTimeout(() => {
            this.typingTimeout = null;
        }, 2000);
    },

    handleKeyDown(event, textarea) {
        // Send on Enter (without Shift)
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            const form = textarea.closest('form');
            if (form && textarea.value.trim()) {
                htmx.trigger(form, 'submit');
            }
        }
    },

    // =========================================================================
    // HELPERS
    // =========================================================================

    autoResize(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    },

    appendMessage(data) {
        const list = document.querySelector(`#message-list-${data.conversation_id}`);
        if (!list) return;

        const isOwn = data.from_id === this.userId;
        const html = `
            <div class="message ${isOwn ? 'outbound' : 'inbound'}" data-message-id="${data.message_id}">
                ${!isOwn ? `<div class="message-sender">${data.from_name}</div>` : ''}
                <div class="message-bubble">
                    <div class="message-body">${this.escapeHtml(data.body)}</div>
                    <div class="message-meta">
                        <span class="message-time">${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                        ${isOwn ? '<span class="message-status status-sent">✓</span>' : ''}
                    </div>
                </div>
            </div>
        `;

        list.insertAdjacentHTML('beforeend', html);
        list.scrollTop = list.scrollHeight;
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    async loadUnreadCount() {
        try {
            const response = await fetch('/api/messaging/unread');
            const data = await response.json();
            if (data.ok) {
                this.updateUnreadBadge(data.unread_count);
            }
        } catch (e) {
            console.error('[Messaging] Failed to load unread count:', e);
        }
    },

    updateUnreadBadge(count) {
        const badge = document.querySelector('.messaging-header .unread-badge');
        if (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }

        // Also update any global messaging badge
        const globalBadge = document.querySelector('#messaging-unread-badge');
        if (globalBadge) {
            globalBadge.textContent = count;
            globalBadge.style.display = count > 0 ? 'inline' : 'none';
        }
    },

    refreshConversationList() {
        const list = document.getElementById('conversation-list');
        if (list) {
            htmx.ajax('GET', '/api/messaging/panel', {
                target: '#messaging-panel',
                swap: 'outerHTML'
            });
        }
    },

    markConversationRead(conversationId) {
        fetch(`/api/messaging/conversations/${conversationId}/read`, {
            method: 'POST'
        }).then(() => {
            this.loadUnreadCount();
        });
    },

    searchConversations(query) {
        // Filter visible conversations
        const items = document.querySelectorAll('.conversation-item');
        const searchLower = query.toLowerCase();

        items.forEach(item => {
            const name = item.querySelector('.conv-name')?.textContent?.toLowerCase() || '';
            const preview = item.querySelector('.conv-preview')?.textContent?.toLowerCase() || '';

            const matches = name.includes(searchLower) || preview.includes(searchLower);
            item.style.display = matches ? '' : 'none';
        });
    },

    showNotification(data) {
        // Browser notification
        if (Notification.permission === 'granted') {
            new Notification(data.from_name || 'New Message', {
                body: data.body,
                icon: '/static/images/ford-logo.png'
            });
        }

        // In-app toast
        window.TOAST?.info?.(`New message from ${data.from_name || 'Unknown'}`);

        // Play sound
        window.SOUNDS?.play?.('notification');
    },

    showConversationInfo(conversationId) {
        // TODO: Show conversation info modal
        console.log('Show info for conversation:', conversationId);
    },

    attachFile() {
        document.getElementById('file-input')?.click();
    },

    handleFiles(files) {
        const list = document.getElementById('attachments-list');
        if (!list) return;

        Array.from(files).forEach(file => {
            const item = document.createElement('div');
            item.className = 'attachment-item';
            item.innerHTML = `
                <span>${file.name}</span>
                <span class="remove" onclick="this.parentElement.remove()">&times;</span>
            `;
            item.dataset.file = file.name;
            list.appendChild(item);
        });
    }
};

// Auto-initialize if user ID is available
document.addEventListener('DOMContentLoaded', () => {
    const userId = window.CAD_USER || document.body.dataset.userId;
    if (userId) {
        MessagingUI.init(userId);
    }

    // Request notification permission
    if (Notification.permission === 'default') {
        Notification.requestPermission();
    }
});

// Export for global access
window.MessagingUI = MessagingUI;

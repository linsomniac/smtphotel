/**
 * smtphotel - Web Interface JavaScript
 * AIDEV-NOTE: Vanilla JS implementation with no external dependencies.
 * Provides message list, detail view, and real-time updates.
 */

// API helper
const api = {
    async get(url) {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },

    async delete(url) {
        const response = await fetch(url, { method: 'DELETE' });
        if (!response.ok && response.status !== 204) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.status === 204 ? null : response.json();
    },

    async post(url, data = null) {
        const options = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        };
        if (data) {
            options.body = JSON.stringify(data);
        }
        const response = await fetch(url, options);
        if (!response.ok && response.status !== 204) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.status === 204 ? null : response.json();
    }
};

// Utility functions
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now - date;

    // If less than 24 hours, show relative time
    if (diff < 24 * 60 * 60 * 1000) {
        if (diff < 60 * 1000) return 'Just now';
        if (diff < 60 * 60 * 1000) return Math.floor(diff / 60000) + 'm ago';
        return Math.floor(diff / 3600000) + 'h ago';
    }

    // Otherwise show date
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatFullTime(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toast notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 200);
    }, 3000);
}

// App state
const state = {
    messages: [],
    currentMessage: null,
    sortBy: 'received_at',
    sortDesc: true,
    autoRefresh: true,
    refreshInterval: null
};

// DOM elements
const elements = {
    messageList: document.getElementById('messageList'),
    messageTable: document.getElementById('messageTable'),
    messageTableBody: document.getElementById('messageTableBody'),
    emptyState: document.getElementById('emptyState'),
    messageDetail: document.getElementById('messageDetail'),
    messageCount: document.getElementById('messageCount'),
    storageSize: document.getElementById('storageSize'),
    autoRefreshCheckbox: document.getElementById('autoRefresh'),
    refreshBtn: document.getElementById('refreshBtn'),
    deleteAllBtn: document.getElementById('deleteAllBtn'),
    closeDetailBtn: document.getElementById('closeDetailBtn'),
    viewRawBtn: document.getElementById('viewRawBtn'),
    deleteBtn: document.getElementById('deleteBtn'),
    detailFrom: document.getElementById('detailFrom'),
    detailTo: document.getElementById('detailTo'),
    detailSubject: document.getElementById('detailSubject'),
    detailTime: document.getElementById('detailTime'),
    detailHeaders: document.getElementById('detailHeaders'),
    detailBodyText: document.getElementById('detailBodyText'),
    htmlFrame: document.getElementById('htmlFrame'),
    attachmentsSection: document.getElementById('attachmentsSection'),
    attachmentList: document.getElementById('attachmentList'),
    tabBtns: document.querySelectorAll('.tab-btn'),
    textPanel: document.getElementById('textPanel'),
    htmlPanel: document.getElementById('htmlPanel')
};

// Load and render messages
async function loadMessages() {
    try {
        const data = await api.get(`/api/messages?sort_by=${state.sortBy}&sort_desc=${state.sortDesc}&limit=100`);
        state.messages = data.messages;
        renderMessageList();
        updateStats();
    } catch (error) {
        console.error('Failed to load messages:', error);
        showToast('Failed to load messages', 'error');
    }
}

async function updateStats() {
    try {
        const stats = await api.get('/api/stats');
        elements.messageCount.textContent = `${stats.message_count} message${stats.message_count !== 1 ? 's' : ''}`;
        elements.storageSize.textContent = formatBytes(stats.total_size_bytes);
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

function renderMessageList() {
    if (state.messages.length === 0) {
        elements.emptyState.style.display = 'block';
        elements.messageTable.style.display = 'none';
        return;
    }

    elements.emptyState.style.display = 'none';
    elements.messageTable.style.display = 'table';

    elements.messageTableBody.innerHTML = state.messages.map(msg => `
        <tr data-id="${escapeHtml(msg.id)}">
            <td class="col-time" title="${escapeHtml(formatFullTime(msg.received_at))}">${escapeHtml(formatTime(msg.received_at))}</td>
            <td class="col-from" title="${escapeHtml(msg.mail_from)}">${escapeHtml(msg.mail_from)}</td>
            <td class="col-to" title="${escapeHtml(msg.rcpt_to.join(', '))}">${escapeHtml(msg.rcpt_to.join(', '))}</td>
            <td class="col-subject" title="${escapeHtml(msg.subject)}">${escapeHtml(msg.subject || '(no subject)')}</td>
            <td class="col-size">${formatBytes(msg.size_bytes)}</td>
            <td class="col-actions">${msg.has_attachments ? '<span class="attachment-indicator" title="Has attachments">📎</span>' : ''}</td>
        </tr>
    `).join('');

    // Add click handlers
    elements.messageTableBody.querySelectorAll('tr').forEach(row => {
        row.addEventListener('click', () => {
            const id = row.dataset.id;
            showMessageDetail(id);
        });
    });

    // Update sort indicators
    document.querySelectorAll('.sortable').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (th.dataset.sort === state.sortBy) {
            th.classList.add(state.sortDesc ? 'sorted-desc' : 'sorted-asc');
        }
    });
}

async function showMessageDetail(id) {
    try {
        const message = await api.get(`/api/messages/${id}`);
        state.currentMessage = message;
        renderMessageDetail(message);
        elements.messageList.style.display = 'none';
        elements.messageDetail.style.display = 'block';
    } catch (error) {
        console.error('Failed to load message:', error);
        showToast('Failed to load message', 'error');
    }
}

function renderMessageDetail(message) {
    elements.detailFrom.textContent = message.mail_from;
    elements.detailTo.textContent = message.rcpt_to.join(', ');
    elements.detailSubject.textContent = message.subject || '(no subject)';
    elements.detailTime.textContent = formatFullTime(message.received_at);

    // Format headers
    const headersText = Object.entries(message.headers)
        .map(([key, values]) => values.map(v => `${key}: ${v}`).join('\n'))
        .join('\n');
    elements.detailHeaders.textContent = headersText;

    // Body text
    elements.detailBodyText.textContent = message.body_text || '(no text content)';

    // HTML body in sandboxed iframe
    if (message.body_html) {
        // Use srcdoc to safely render HTML in sandbox
        // AIDEV-NOTE: The iframe has strict sandbox - no scripts, no same-origin access
        elements.htmlFrame.srcdoc = message.body_html;
    } else {
        elements.htmlFrame.srcdoc = '<p style="color: #666; font-family: sans-serif;">No HTML content</p>';
    }

    // Attachments
    if (message.attachments && message.attachments.length > 0) {
        elements.attachmentsSection.style.display = 'block';
        elements.attachmentList.innerHTML = message.attachments.map(att => `
            <li class="attachment-item">
                <div class="attachment-info">
                    <span class="attachment-name">${escapeHtml(att.filename)}</span>
                    <span class="attachment-size">${formatBytes(att.size_bytes)}</span>
                </div>
                <a href="/api/messages/${message.id}/attachments/${att.id}" class="btn btn-secondary" download="${escapeHtml(att.filename)}">Download</a>
            </li>
        `).join('');
    } else {
        elements.attachmentsSection.style.display = 'none';
    }

    // Reset to text tab
    showTab('text');
}

function showTab(tabName) {
    elements.tabBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    elements.textPanel.classList.toggle('active', tabName === 'text');
    elements.htmlPanel.classList.toggle('active', tabName === 'html');
}

function closeDetail() {
    state.currentMessage = null;
    elements.messageDetail.style.display = 'none';
    elements.messageList.style.display = 'block';
}

async function deleteCurrentMessage() {
    if (!state.currentMessage) return;

    if (!confirm('Delete this message?')) return;

    try {
        await api.delete(`/api/messages/${state.currentMessage.id}`);
        showToast('Message deleted', 'success');
        closeDetail();
        loadMessages();
    } catch (error) {
        console.error('Failed to delete message:', error);
        showToast('Failed to delete message', 'error');
    }
}

async function deleteAllMessages() {
    if (!confirm('Delete ALL messages? This cannot be undone.')) return;

    try {
        const result = await api.delete('/api/messages?confirm=true');
        showToast(`Deleted ${result.deleted_count} messages`, 'success');
        loadMessages();
    } catch (error) {
        console.error('Failed to delete messages:', error);
        showToast('Failed to delete messages', 'error');
    }
}

function viewRawMessage() {
    if (!state.currentMessage) return;
    window.open(`/api/messages/${state.currentMessage.id}/raw`, '_blank');
}

function toggleAutoRefresh() {
    state.autoRefresh = elements.autoRefreshCheckbox.checked;
    if (state.autoRefresh) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
    }
}

function startAutoRefresh() {
    if (state.refreshInterval) return;
    state.refreshInterval = setInterval(() => {
        if (!state.currentMessage) {
            loadMessages();
        }
    }, 3000);
}

function stopAutoRefresh() {
    if (state.refreshInterval) {
        clearInterval(state.refreshInterval);
        state.refreshInterval = null;
    }
}

function handleSort(e) {
    const th = e.target.closest('.sortable');
    if (!th) return;

    const sortField = th.dataset.sort;
    if (state.sortBy === sortField) {
        state.sortDesc = !state.sortDesc;
    } else {
        state.sortBy = sortField;
        state.sortDesc = true;
    }
    loadMessages();
}

// Keyboard shortcuts
function handleKeyboard(e) {
    // Don't handle if typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    switch (e.key.toLowerCase()) {
        case 'r':
            e.preventDefault();
            loadMessages();
            break;
        case 'escape':
            if (state.currentMessage) {
                closeDetail();
            }
            break;
        case 'd':
            if (state.currentMessage) {
                deleteCurrentMessage();
            }
            break;
        case 'j':
            // Navigate to next message
            navigateMessage(1);
            break;
        case 'k':
            // Navigate to previous message
            navigateMessage(-1);
            break;
    }
}

function navigateMessage(direction) {
    if (state.messages.length === 0) return;

    if (!state.currentMessage) {
        // Open first/last message
        const index = direction > 0 ? 0 : state.messages.length - 1;
        showMessageDetail(state.messages[index].id);
        return;
    }

    const currentIndex = state.messages.findIndex(m => m.id === state.currentMessage.id);
    const newIndex = currentIndex + direction;

    if (newIndex >= 0 && newIndex < state.messages.length) {
        showMessageDetail(state.messages[newIndex].id);
    }
}

// Initialize
function init() {
    // Event listeners
    elements.refreshBtn.addEventListener('click', loadMessages);
    elements.deleteAllBtn.addEventListener('click', deleteAllMessages);
    elements.autoRefreshCheckbox.addEventListener('change', toggleAutoRefresh);
    elements.closeDetailBtn.addEventListener('click', closeDetail);
    elements.viewRawBtn.addEventListener('click', viewRawMessage);
    elements.deleteBtn.addEventListener('click', deleteCurrentMessage);

    // Tab buttons
    elements.tabBtns.forEach(btn => {
        btn.addEventListener('click', () => showTab(btn.dataset.tab));
    });

    // Sort headers
    document.querySelectorAll('.sortable').forEach(th => {
        th.addEventListener('click', handleSort);
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyboard);

    // Initial load
    loadMessages();

    // Start auto-refresh
    if (state.autoRefresh) {
        startAutoRefresh();
    }
}

// Start the app
document.addEventListener('DOMContentLoaded', init);

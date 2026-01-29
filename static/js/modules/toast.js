// ============================================================================
// FORD CAD — Toast Notification System
// Modern, non-intrusive notifications
// ============================================================================

const TOAST_CONTAINER_ID = "__fordcad_toast_container__";

let _container = null;

function _ensureContainer() {
    if (_container && _container.isConnected) return;

    _container = document.getElementById(TOAST_CONTAINER_ID);
    if (_container) return;

    _container = document.createElement("div");
    _container.id = TOAST_CONTAINER_ID;
    _container.style.cssText = `
        position: fixed;
        bottom: 60px;
        right: 20px;
        z-index: 10000;
        display: flex;
        flex-direction: column-reverse;
        gap: 8px;
        pointer-events: none;
    `;
    document.body.appendChild(_container);
}

function _createToast(message, type = "info", duration = 4000) {
    _ensureContainer();

    const toast = document.createElement("div");
    toast.className = `cad-toast cad-toast-${type}`;

    // Icon based on type
    const icons = {
        success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
        </svg>`,
        error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="15" y1="9" x2="9" y2="15"></line>
            <line x1="9" y1="9" x2="15" y2="15"></line>
        </svg>`,
        warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>`,
        info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="16" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12.01" y2="8"></line>
        </svg>`,
    };

    toast.innerHTML = `
        <span class="cad-toast-icon">${icons[type] || icons.info}</span>
        <span class="cad-toast-message">${message}</span>
        <button class="cad-toast-close" onclick="this.parentElement.remove()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
        </button>
    `;

    // Styles
    toast.style.cssText = `
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 16px;
        background: rgba(15, 23, 40, 0.95);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        color: #f0f4f8;
        font-size: 13px;
        font-weight: 500;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(12px);
        pointer-events: auto;
        animation: toastSlideIn 0.3s ease-out;
        max-width: 400px;
    `;

    // Type-specific border colors
    const borderColors = {
        success: "rgba(16, 185, 129, 0.5)",
        error: "rgba(239, 68, 68, 0.5)",
        warning: "rgba(245, 158, 11, 0.5)",
        info: "rgba(59, 130, 246, 0.5)",
    };
    toast.style.borderLeftWidth = "3px";
    toast.style.borderLeftColor = borderColors[type] || borderColors.info;

    // Icon colors
    const iconColors = {
        success: "#10b981",
        error: "#ef4444",
        warning: "#f59e0b",
        info: "#3b82f6",
    };
    const iconEl = toast.querySelector(".cad-toast-icon");
    if (iconEl) iconEl.style.color = iconColors[type] || iconColors.info;

    // Close button styles
    const closeBtn = toast.querySelector(".cad-toast-close");
    if (closeBtn) {
        closeBtn.style.cssText = `
            background: transparent;
            border: none;
            color: rgba(255, 255, 255, 0.5);
            cursor: pointer;
            padding: 4px;
            margin-left: auto;
            border-radius: 4px;
            transition: all 0.15s;
        `;
        closeBtn.addEventListener("mouseenter", () => {
            closeBtn.style.background = "rgba(255, 255, 255, 0.1)";
            closeBtn.style.color = "#fff";
        });
        closeBtn.addEventListener("mouseleave", () => {
            closeBtn.style.background = "transparent";
            closeBtn.style.color = "rgba(255, 255, 255, 0.5)";
        });
    }

    _container.appendChild(toast);

    // Auto-remove after duration
    if (duration > 0) {
        setTimeout(() => {
            toast.style.animation = "toastSlideOut 0.3s ease-in forwards";
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    return toast;
}

// Inject keyframe animations
const style = document.createElement("style");
style.textContent = `
    @keyframes toastSlideIn {
        from {
            opacity: 0;
            transform: translateX(100px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    @keyframes toastSlideOut {
        from {
            opacity: 1;
            transform: translateX(0);
        }
        to {
            opacity: 0;
            transform: translateX(100px);
        }
    }
`;
document.head.appendChild(style);

// Public API
const TOAST = {
    success(message, duration = 4000) {
        return _createToast(message, "success", duration);
    },

    error(message, duration = 6000) {
        return _createToast(message, "error", duration);
    },

    warning(message, duration = 5000) {
        return _createToast(message, "warning", duration);
    },

    info(message, duration = 4000) {
        return _createToast(message, "info", duration);
    },

    show(message, type = "info", duration = 4000) {
        return _createToast(message, type, duration);
    },
};

// Global exposure
window.TOAST = TOAST;

console.log("[TOAST] Notification system loaded");

export default TOAST;

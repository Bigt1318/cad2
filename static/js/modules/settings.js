// ============================================================================
// FORD-CAD — SETTINGS MODULE
// User preferences: theme, sounds, auto-refresh
// ============================================================================

const STORAGE_KEY = "fordcad_settings";

const DEFAULT_SETTINGS = {
    theme: "light",
    soundEnabled: true,
    autoRefresh: true,
    autoRefreshInterval: 30, // seconds
};

let _settings = { ...DEFAULT_SETTINGS };

export const SETTINGS = {
    // -------------------------------------------------------------------------
    // Load settings from localStorage
    // -------------------------------------------------------------------------
    load() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                const parsed = JSON.parse(stored);
                _settings = { ...DEFAULT_SETTINGS, ...parsed };
            }
        } catch (e) {
            console.warn("[SETTINGS] Failed to load settings:", e);
            _settings = { ...DEFAULT_SETTINGS };
        }
        return _settings;
    },

    // -------------------------------------------------------------------------
    // Save settings to localStorage
    // -------------------------------------------------------------------------
    save() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(_settings));
        } catch (e) {
            console.warn("[SETTINGS] Failed to save settings:", e);
        }
    },

    // -------------------------------------------------------------------------
    // Get a setting value
    // -------------------------------------------------------------------------
    get(key) {
        return _settings[key];
    },

    // -------------------------------------------------------------------------
    // Set a setting value
    // -------------------------------------------------------------------------
    set(key, value) {
        _settings[key] = value;
        this.save();

        // Apply immediately if it's theme
        if (key === "theme") {
            this.applyTheme(value);
        }
    },

    // -------------------------------------------------------------------------
    // Get all settings
    // -------------------------------------------------------------------------
    getAll() {
        return { ..._settings };
    },

    // -------------------------------------------------------------------------
    // Apply theme to document
    // -------------------------------------------------------------------------
    applyTheme(theme) {
        const validThemes = ["light", "dark", "high-contrast"];
        const t = validThemes.includes(theme) ? theme : "light";
        document.documentElement.setAttribute("data-theme", t);
        console.log(`[SETTINGS] Theme applied: ${t}`);
    },

    // -------------------------------------------------------------------------
    // Initialize: load settings and apply theme
    // -------------------------------------------------------------------------
    init() {
        this.load();
        this.applyTheme(_settings.theme);
        console.log("[SETTINGS] Initialized with:", _settings);
    },

    // -------------------------------------------------------------------------
    // Open settings modal (builds inline)
    // -------------------------------------------------------------------------
    openModal() {
        const current = this.getAll();

        const html = `
            <div class="cad-modal-overlay" onclick="SETTINGS.closeModal()"></div>
            <div class="cad-modal settings-modal" role="dialog" aria-modal="true" aria-label="Settings">
                <div class="cad-modal-header">
                    <div class="cad-modal-title">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="3"></circle>
                            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"></path>
                        </svg>
                        Settings
                    </div>
                    <button class="cad-modal-close" onclick="SETTINGS.closeModal()">×</button>
                </div>
                <div class="cad-modal-body settings-body">
                    <div class="settings-section">
                        <div class="settings-section-title">Appearance</div>
                        
                        <div class="settings-row">
                            <label for="setting-theme">Theme</label>
                            <select id="setting-theme" onchange="SETTINGS.setTheme(this.value)">
                                <option value="light" ${current.theme === "light" ? "selected" : ""}>Light (Ford Blue)</option>
                                <option value="dark" ${current.theme === "dark" ? "selected" : ""}>Dark</option>
                                <option value="high-contrast" ${current.theme === "high-contrast" ? "selected" : ""}>High Contrast</option>
                            </select>
                        </div>
                    </div>

                    <div class="settings-section">
                        <div class="settings-section-title">Notifications</div>
                        
                        <div class="settings-row">
                            <label for="setting-sound">
                                <input type="checkbox" id="setting-sound" 
                                    ${current.soundEnabled ? "checked" : ""} 
                                    onchange="SETTINGS.set('soundEnabled', this.checked)">
                                Enable sound alerts
                            </label>
                        </div>
                    </div>

                    <div class="settings-section">
                        <div class="settings-section-title">Auto-Refresh</div>
                        
                        <div class="settings-row">
                            <label for="setting-autorefresh">
                                <input type="checkbox" id="setting-autorefresh" 
                                    ${current.autoRefresh ? "checked" : ""} 
                                    onchange="SETTINGS.set('autoRefresh', this.checked)">
                                Auto-refresh panels
                            </label>
                        </div>

                        <div class="settings-row">
                            <label for="setting-interval">Refresh interval</label>
                            <select id="setting-interval" onchange="SETTINGS.set('autoRefreshInterval', parseInt(this.value))">
                                <option value="15" ${current.autoRefreshInterval === 15 ? "selected" : ""}>15 seconds</option>
                                <option value="30" ${current.autoRefreshInterval === 30 ? "selected" : ""}>30 seconds</option>
                                <option value="60" ${current.autoRefreshInterval === 60 ? "selected" : ""}>1 minute</option>
                                <option value="120" ${current.autoRefreshInterval === 120 ? "selected" : ""}>2 minutes</option>
                            </select>
                        </div>
                    </div>

                    <div class="settings-section">
                        <div class="settings-section-title">Keyboard Shortcuts</div>
                        <div class="settings-shortcuts">
                            <div class="shortcut-row"><kbd>F2</kbd> New Incident</div>
                            <div class="shortcut-row"><kbd>F5</kbd> Refresh Panels</div>
                            <div class="shortcut-row"><kbd>F9</kbd> Daily Log</div>
                            <div class="shortcut-row"><kbd>H</kbd> Held Calls</div>
                            <div class="shortcut-row"><kbd>ESC</kbd> Close Modal</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const container = document.getElementById("fordcad-modal-container");
        if (container) {
            container.innerHTML = html;
            container.style.display = "flex";
        }
    },

    closeModal() {
        const container = document.getElementById("fordcad-modal-container");
        if (container) {
            container.innerHTML = "";
            container.style.display = "none";
        }
    },

    setTheme(theme) {
        this.set("theme", theme);
    },
};

// Auto-initialize on load
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => SETTINGS.init());
} else {
    SETTINGS.init();
}

// Global exposure
window.SETTINGS = SETTINGS;

export default SETTINGS;

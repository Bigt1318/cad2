// ============================================================================
// FORD-CAD — SETTINGS MODULE
// User preferences: theme, sounds, auto-refresh, font size
// ============================================================================

const STORAGE_KEY = "fordcad_settings";

const DEFAULT_SETTINGS = {
    theme: "light",
    fontSize: "medium",      // small, medium, large, xlarge
    fontFamily: "system",    // system, segoe, arial, roboto, mono
    density: "normal",       // compact, normal, spacious
    soundEnabled: true,
    autoRefresh: true,
    autoRefreshInterval: 30, // seconds
    panelCalltakerWidth: "36%",
    panelUnitsWidth: "20%",
    panelIncidentsWidth: "44%",  // calculated: 100% - calltaker - units
    savedLayouts: [],        // array of {name, calltaker, units, incidents}
    // Notification settings
    highlightNew: true,
    highlightColor: "#fff3cd",
    flashTab: true,
    desktopNotify: false,
    volume: 70,
    statusColors: {          // customizable status colors
        dispatched: "#3b82f6",
        enroute: "#f59e0b",
        arrived: "#10b981",
        onscene: "#10b981",
        operating: "#8b5cf6",
        transporting: "#ec4899",
        available: "#22c55e",
        busy: "#ef4444"
    }
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
    // Save settings to localStorage and server
    // -------------------------------------------------------------------------
    save() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(_settings));
        } catch (e) {
            console.warn("[SETTINGS] Failed to save settings:", e);
        }

        // Also save to server (async, non-blocking)
        this.saveToServer();
    },

    // -------------------------------------------------------------------------
    // Save settings to server
    // -------------------------------------------------------------------------
    async saveToServer() {
        try {
            await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ settings: _settings }),
            });
        } catch (e) {
            console.warn("[SETTINGS] Failed to save to server:", e);
        }
    },

    // -------------------------------------------------------------------------
    // Load settings from server
    // -------------------------------------------------------------------------
    async loadFromServer() {
        try {
            const res = await fetch("/api/settings", {
                headers: { "Accept": "application/json" },
            });
            const data = await res.json();
            if (data.ok && data.settings) {
                // Only use server settings if they indicate user has saved preferences
                // (server returns fromUser: true when loading actual saved settings)
                if (data.fromUser) {
                    // User has saved settings on server - these take precedence
                    _settings = { ...DEFAULT_SETTINGS, ..._settings, ...data.settings };
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(_settings));
                    return true;
                } else {
                    // Server returned defaults - keep localStorage values, don't overwrite
                    return false;
                }
            }
        } catch (e) {
            console.warn("[SETTINGS] Failed to load from server:", e);
        }
        return false;
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

        // Apply immediately
        if (key === "theme") {
            this.applyTheme(value);
        } else if (key === "fontSize") {
            this.applyFontSize(value);
        } else if (key === "fontFamily") {
            this.applyFontFamily(value);
        } else if (key === "density") {
            this.applyDensity(value);
        } else if (key === "statusColors") {
            this.applyStatusColors();
        }
    },

    // -------------------------------------------------------------------------
    // Set a nested setting (e.g., statusColors.dispatched)
    // -------------------------------------------------------------------------
    setNested(path, value) {
        const keys = path.split(".");
        let obj = _settings;
        for (let i = 0; i < keys.length - 1; i++) {
            if (!obj[keys[i]]) obj[keys[i]] = {};
            obj = obj[keys[i]];
        }
        obj[keys[keys.length - 1]] = value;
        this.save();

        // Apply status colors if that's what changed
        if (keys[0] === "statusColors") {
            this.applyStatusColors();
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
    },

    // -------------------------------------------------------------------------
    // Apply font size to document
    // -------------------------------------------------------------------------
    applyFontSize(size) {
        const validSizes = ["small", "medium", "large", "xlarge"];
        const s = validSizes.includes(size) ? size : "medium";
        document.documentElement.setAttribute("data-font-size", s);
    },

    // -------------------------------------------------------------------------
    // Apply font family to document
    // -------------------------------------------------------------------------
    applyFontFamily(family) {
        const fontMap = {
            "system": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            "segoe": '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif',
            "arial": 'Arial, Helvetica, sans-serif',
            "roboto": 'Roboto, "Helvetica Neue", Arial, sans-serif',
            "inter": 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
            "mono": 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
            "verdana": 'Verdana, Geneva, sans-serif',
            "tahoma": 'Tahoma, Geneva, sans-serif',
            "narrow": '"Arial Narrow", "Helvetica Condensed", Arial, sans-serif',
            "georgia": 'Georgia, "Times New Roman", Times, serif',
            "bold": '"Arial Black", "Helvetica Bold", Impact, sans-serif',
            "emergency": '"Highway Gothic", "Interstate", "DIN", Arial, sans-serif'
        };
        const f = fontMap[family] || fontMap["system"];
        document.documentElement.style.setProperty("--font-sans", f);
    },

    // -------------------------------------------------------------------------
    // Apply display density to document
    // -------------------------------------------------------------------------
    applyDensity(density) {
        const validDensities = ["compact", "normal", "spacious"];
        const d = validDensities.includes(density) ? density : "normal";
        document.documentElement.setAttribute("data-density", d);
    },

    // -------------------------------------------------------------------------
    // Apply custom status colors
    // -------------------------------------------------------------------------
    applyStatusColors() {
        const root = document.documentElement;
        const colors = _settings.statusColors || {};
        Object.entries(colors).forEach(([status, color]) => {
            root.style.setProperty(`--status-${status}`, color);
        });
    },

    // -------------------------------------------------------------------------
    // Apply panel widths to CSS variables
    // -------------------------------------------------------------------------
    applyPanelWidths() {
        const root = document.documentElement;
        root.style.setProperty("--panel-calltaker-width", _settings.panelCalltakerWidth || "38%");
        root.style.setProperty("--panel-units-width", _settings.panelUnitsWidth || "22%");
    },

    // -------------------------------------------------------------------------
    // Apply highlight/notification settings
    // -------------------------------------------------------------------------
    applyHighlightSettings() {
        const root = document.documentElement;
        root.style.setProperty("--highlight-color", _settings.highlightColor || "#fff3cd");
        root.style.setProperty("--highlight-new", _settings.highlightNew ? "1" : "0");
    },

    // -------------------------------------------------------------------------
    // Initialize: load settings and apply all
    // -------------------------------------------------------------------------
    async init() {
        // First load from localStorage for immediate application
        this.load();
        this.applyTheme(_settings.theme);
        this.applyFontSize(_settings.fontSize);
        this.applyFontFamily(_settings.fontFamily);
        this.applyDensity(_settings.density);
        this.applyPanelWidths();
        this.applyStatusColors();
        this.applyHighlightSettings();
        this.initPanelResizers();

        // Then try to load from server (may update settings)
        const loaded = await this.loadFromServer();
        if (loaded) {
            // Re-apply settings from server
            this.applyTheme(_settings.theme);
            this.applyFontSize(_settings.fontSize);
            this.applyFontFamily(_settings.fontFamily);
            this.applyDensity(_settings.density);
            this.applyPanelWidths();
            this.applyStatusColors();
            this.applyHighlightSettings();
        }

    },

    // -------------------------------------------------------------------------
    // Initialize panel resize handles
    // -------------------------------------------------------------------------
    initPanelResizers() {
        const self = this;

        // Wait for DOM to be ready
        const setupResizers = () => {
            const calltakerPanel = document.querySelector(".panel-calltaker");
            const unitsPanel = document.querySelector(".panel-units");

            if (!calltakerPanel || !unitsPanel) {
                setTimeout(setupResizers, 100);
                return;
            }

            // Create resize handles if they don't exist
            if (!calltakerPanel.querySelector(".panel-resize-handle")) {
                self.createResizeHandle(calltakerPanel, "calltaker");
            }
            if (!unitsPanel.querySelector(".panel-resize-handle")) {
                self.createResizeHandle(unitsPanel, "units");
            }
        };

        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", setupResizers);
        } else {
            // Small delay to ensure panels are rendered
            setTimeout(setupResizers, 200);
        }
    },

    // -------------------------------------------------------------------------
    // Create a resize handle for a panel
    // -------------------------------------------------------------------------
    createResizeHandle(panel, panelName) {
        const self = this; // Capture context for nested functions
        const handle = document.createElement("div");
        handle.className = "panel-resize-handle";
        handle.setAttribute("data-panel", panelName);
        panel.appendChild(handle);

        let startX = 0;
        let startWidth = 0;
        let isDragging = false;

        const startDrag = (e) => {
            isDragging = true;
            startX = e.clientX || e.touches?.[0]?.clientX || 0;
            startWidth = panel.offsetWidth;
            handle.classList.add("dragging");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";

            document.addEventListener("mousemove", doDrag);
            document.addEventListener("mouseup", stopDrag);
            document.addEventListener("touchmove", doDrag);
            document.addEventListener("touchend", stopDrag);
        };

        const doDrag = (e) => {
            if (!isDragging) return;
            const clientX = e.clientX || e.touches?.[0]?.clientX || 0;
            const diff = clientX - startX;
            const newWidth = Math.max(180, Math.min(startWidth + diff, window.innerWidth * 0.6));
            panel.style.flex = `0 0 ${newWidth}px`;

            // Save the width as a percentage
            const pct = ((newWidth / window.innerWidth) * 100).toFixed(1) + "%";
            if (panelName === "calltaker") {
                _settings.panelCalltakerWidth = pct;
            } else if (panelName === "units") {
                _settings.panelUnitsWidth = pct;
            }
        };

        const stopDrag = () => {
            if (!isDragging) return;
            isDragging = false;
            handle.classList.remove("dragging");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";

            document.removeEventListener("mousemove", doDrag);
            document.removeEventListener("mouseup", stopDrag);
            document.removeEventListener("touchmove", doDrag);
            document.removeEventListener("touchend", stopDrag);

            // Save the new widths
            self.save();
        };

        handle.addEventListener("mousedown", startDrag);
        handle.addEventListener("touchstart", startDrag, { passive: true });
    },

    // -------------------------------------------------------------------------
    // Reset panel widths to defaults
    // -------------------------------------------------------------------------
    resetPanelWidths() {
        _settings.panelCalltakerWidth = "36%";
        _settings.panelUnitsWidth = "20%";
        this.save();
        this.applyPanelWidths();

        // Also reset inline styles
        const calltakerPanel = document.querySelector(".panel-calltaker");
        const unitsPanel = document.querySelector(".panel-units");
        if (calltakerPanel) calltakerPanel.style.flex = "";
        if (unitsPanel) unitsPanel.style.flex = "";

    },

    // -------------------------------------------------------------------------
    // Open settings modal (enhanced tabbed version)
    // -------------------------------------------------------------------------
    openModal(initialTab = "appearance") {
        const current = this.getAll();
        const savedLayouts = current.savedLayouts || [];
        const statusColors = current.statusColors || DEFAULT_SETTINGS.statusColors;

        const html = `
            <div class="cad-modal-overlay" onclick="SETTINGS.closeModal()"></div>
            <div class="cad-modal settings-modal-enhanced" role="dialog" aria-modal="true" aria-label="Preferences">
                <div class="cad-modal-header">
                    <div class="cad-modal-title">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="3"></circle>
                            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"></path>
                        </svg>
                        Preferences
                    </div>
                    <button class="cad-modal-close" onclick="SETTINGS.closeModal()" title="Close">&times;</button>
                </div>

                <div class="settings-tabs">
                    <button class="settings-tab ${initialTab === 'appearance' ? 'active' : ''}" data-tab="appearance" onclick="SETTINGS.switchTab('appearance')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                        Appearance
                    </button>
                    <button class="settings-tab ${initialTab === 'layout' ? 'active' : ''}" data-tab="layout" onclick="SETTINGS.switchTab('layout')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
                        Layout
                    </button>
                    <button class="settings-tab ${initialTab === 'notifications' ? 'active' : ''}" data-tab="notifications" onclick="SETTINGS.switchTab('notifications')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0"/></svg>
                        Notifications
                    </button>
                    <button class="settings-tab ${initialTab === 'colors' ? 'active' : ''}" data-tab="colors" onclick="SETTINGS.switchTab('colors')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="10.5" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="12.5" r="2.5"/><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12a10 10 0 0 0 10 10z"/></svg>
                        Colors
                    </button>
                    <button class="settings-tab ${initialTab === 'shortcuts' ? 'active' : ''}" data-tab="shortcuts" onclick="SETTINGS.switchTab('shortcuts')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h8M6 16h.01M18 16h.01M10 16h4"/></svg>
                        Shortcuts
                    </button>
                </div>

                <div class="cad-modal-body settings-body-enhanced">
                    <!-- APPEARANCE TAB -->
                    <div class="settings-panel ${initialTab === 'appearance' ? 'active' : ''}" id="settings-panel-appearance">
                        <div class="settings-group">
                            <div class="settings-group-title">Theme</div>
                            <div class="settings-theme-grid">
                                <button class="theme-option ${current.theme === 'light' ? 'selected' : ''}" onclick="SETTINGS.setTheme('light')">
                                    <div class="theme-preview theme-preview-light"></div>
                                    <span>Light</span>
                                </button>
                                <button class="theme-option ${current.theme === 'dark' ? 'selected' : ''}" onclick="SETTINGS.setTheme('dark')">
                                    <div class="theme-preview theme-preview-dark"></div>
                                    <span>Dark</span>
                                </button>
                                <button class="theme-option ${current.theme === 'high-contrast' ? 'selected' : ''}" onclick="SETTINGS.setTheme('high-contrast')">
                                    <div class="theme-preview theme-preview-hc"></div>
                                    <span>High Contrast</span>
                                </button>
                            </div>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Font Size</div>
                            <div class="settings-slider-row">
                                <span class="slider-label-left">A</span>
                                <input type="range" min="0" max="3" step="1"
                                    value="${['small','medium','large','xlarge'].indexOf(current.fontSize)}"
                                    oninput="SETTINGS.setFontSize(['small','medium','large','xlarge'][this.value]); document.getElementById('fontsize-label').textContent = ['Small','Medium','Large','Extra Large'][this.value]">
                                <span class="slider-label-right">A</span>
                                <span class="slider-value" id="fontsize-label">${{small:'Small',medium:'Medium',large:'Large',xlarge:'Extra Large'}[current.fontSize]}</span>
                            </div>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Font Family</div>
                            <select class="settings-select" onchange="SETTINGS.set('fontFamily', this.value)">
                                <option value="system" ${current.fontFamily === 'system' ? 'selected' : ''}>System Default</option>
                                <option value="segoe" ${current.fontFamily === 'segoe' ? 'selected' : ''}>Segoe UI</option>
                                <option value="arial" ${current.fontFamily === 'arial' ? 'selected' : ''}>Arial</option>
                                <option value="narrow" ${current.fontFamily === 'narrow' ? 'selected' : ''}>Arial Narrow</option>
                                <option value="verdana" ${current.fontFamily === 'verdana' ? 'selected' : ''}>Verdana</option>
                                <option value="tahoma" ${current.fontFamily === 'tahoma' ? 'selected' : ''}>Tahoma</option>
                                <option value="georgia" ${current.fontFamily === 'georgia' ? 'selected' : ''}>Georgia (Serif)</option>
                                <option value="roboto" ${current.fontFamily === 'roboto' ? 'selected' : ''}>Roboto</option>
                                <option value="inter" ${current.fontFamily === 'inter' ? 'selected' : ''}>Inter</option>
                                <option value="mono" ${current.fontFamily === 'mono' ? 'selected' : ''}>Monospace</option>
                                <option value="bold" ${current.fontFamily === 'bold' ? 'selected' : ''}>Bold (Arial Black)</option>
                                <option value="emergency" ${current.fontFamily === 'emergency' ? 'selected' : ''}>Emergency (Highway)</option>
                            </select>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Display Density</div>
                            <div class="settings-density-grid">
                                <button class="density-option ${current.density === 'compact' ? 'selected' : ''}" onclick="SETTINGS.setDensity('compact')">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="2"/><rect x="3" y="11" width="18" height="2"/><rect x="3" y="17" width="18" height="2"/></svg>
                                    <span>Compact</span>
                                </button>
                                <button class="density-option ${(current.density === 'normal' || !current.density) ? 'selected' : ''}" onclick="SETTINGS.setDensity('normal')">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="3"/><rect x="3" y="10.5" width="18" height="3"/><rect x="3" y="17" width="18" height="3"/></svg>
                                    <span>Normal</span>
                                </button>
                                <button class="density-option ${current.density === 'spacious' ? 'selected' : ''}" onclick="SETTINGS.setDensity('spacious')">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="4"/><rect x="3" y="10" width="18" height="4"/><rect x="3" y="17" width="18" height="4"/></svg>
                                    <span>Spacious</span>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- LAYOUT TAB -->
                    <div class="settings-panel ${initialTab === 'layout' ? 'active' : ''}" id="settings-panel-layout">
                        <div class="settings-group">
                            <div class="settings-group-title">Panel Widths</div>
                            <p class="settings-hint">Drag edges between panels to resize, or use sliders below.</p>

                            <div class="panel-width-control">
                                <label>Calltaker Panel</label>
                                <div class="slider-with-value">
                                    <input type="range" min="20" max="50" step="1"
                                        value="${parseInt(current.panelCalltakerWidth) || 36}"
                                        id="slider-calltaker"
                                        oninput="SETTINGS.setPanelWidth('calltaker', this.value)">
                                    <span class="slider-value" id="value-calltaker">${current.panelCalltakerWidth || '36%'}</span>
                                </div>
                            </div>

                            <div class="panel-width-control">
                                <label>Units Panel</label>
                                <div class="slider-with-value">
                                    <input type="range" min="15" max="35" step="1"
                                        value="${parseInt(current.panelUnitsWidth) || 20}"
                                        id="slider-units"
                                        oninput="SETTINGS.setPanelWidth('units', this.value)">
                                    <span class="slider-value" id="value-units">${current.panelUnitsWidth || '20%'}</span>
                                </div>
                            </div>

                            <div class="panel-preview">
                                <div class="preview-panel preview-calltaker" id="preview-calltaker" style="width: ${current.panelCalltakerWidth || '36%'}">CT</div>
                                <div class="preview-panel preview-incidents" id="preview-incidents">INC</div>
                                <div class="preview-panel preview-units" id="preview-units" style="width: ${current.panelUnitsWidth || '20%'}">UNITS</div>
                            </div>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Layout Presets</div>
                            <div class="layout-presets">
                                <div class="preset-buttons">
                                    <button class="preset-btn" onclick="SETTINGS.applyLayoutPreset('default')">Default</button>
                                    <button class="preset-btn" onclick="SETTINGS.applyLayoutPreset('wide-calltaker')">Wide Calltaker</button>
                                    <button class="preset-btn" onclick="SETTINGS.applyLayoutPreset('wide-incidents')">Wide Incidents</button>
                                    <button class="preset-btn" onclick="SETTINGS.applyLayoutPreset('balanced')">Balanced</button>
                                </div>
                            </div>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Saved Layouts</div>
                            <div class="saved-layouts-list" id="saved-layouts-list">
                                ${savedLayouts.length === 0 ? '<p class="settings-hint">No saved layouts yet.</p>' :
                                    savedLayouts.map((l, i) => `
                                        <div class="saved-layout-item">
                                            <span>${l.name}</span>
                                            <div class="saved-layout-actions">
                                                <button onclick="SETTINGS.loadSavedLayout(${i})">Load</button>
                                                <button onclick="SETTINGS.deleteSavedLayout(${i})">&times;</button>
                                            </div>
                                        </div>
                                    `).join('')}
                            </div>
                            <div class="save-layout-form">
                                <input type="text" id="new-layout-name" placeholder="Layout name..." maxlength="20">
                                <button onclick="SETTINGS.saveCurrentLayout()">Save Current</button>
                            </div>
                        </div>
                    </div>

                    <!-- NOTIFICATIONS TAB -->
                    <div class="settings-panel ${initialTab === 'notifications' ? 'active' : ''}" id="settings-panel-notifications">
                        <div class="settings-group">
                            <div class="settings-group-title">Sound Alerts</div>
                            <label class="settings-toggle">
                                <input type="checkbox" ${current.soundEnabled ? 'checked' : ''}
                                    onchange="SETTINGS.set('soundEnabled', this.checked)">
                                <span class="toggle-slider"></span>
                                <span class="toggle-label">Enable sound alerts</span>
                            </label>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Auto-Refresh</div>
                            <label class="settings-toggle">
                                <input type="checkbox" ${current.autoRefresh ? 'checked' : ''}
                                    onchange="SETTINGS.set('autoRefresh', this.checked)">
                                <span class="toggle-slider"></span>
                                <span class="toggle-label">Auto-refresh incident panels</span>
                            </label>

                            <div class="settings-row" style="margin-top: 12px;">
                                <label>Refresh Interval</label>
                                <select onchange="SETTINGS.set('autoRefreshInterval', parseInt(this.value))">
                                    <option value="15" ${current.autoRefreshInterval === 15 ? 'selected' : ''}>15 seconds</option>
                                    <option value="30" ${current.autoRefreshInterval === 30 ? 'selected' : ''}>30 seconds</option>
                                    <option value="60" ${current.autoRefreshInterval === 60 ? 'selected' : ''}>1 minute</option>
                                    <option value="120" ${current.autoRefreshInterval === 120 ? 'selected' : ''}>2 minutes</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- COLORS TAB -->
                    <div class="settings-panel ${initialTab === 'colors' ? 'active' : ''}" id="settings-panel-colors">
                        <div class="settings-group">
                            <div class="settings-group-title">Unit Status Colors</div>
                            <p class="settings-hint">Customize colors for unit status badges.</p>

                            <div class="color-grid">
                                ${Object.entries(statusColors).map(([status, color]) => `
                                    <div class="color-item">
                                        <label>${status.charAt(0).toUpperCase() + status.slice(1)}</label>
                                        <div class="color-input-wrap">
                                            <input type="color" value="${color}"
                                                onchange="SETTINGS.setNested('statusColors.${status}', this.value)">
                                            <span class="color-preview" style="background: ${color}"></span>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>

                            <button class="btn-reset-colors" onclick="SETTINGS.resetStatusColors()">Reset to Defaults</button>
                        </div>
                    </div>

                    <!-- SHORTCUTS TAB -->
                    <div class="settings-panel ${initialTab === 'shortcuts' ? 'active' : ''}" id="settings-panel-shortcuts">
                        <div class="settings-group">
                            <div class="settings-group-title">Keyboard Shortcuts</div>
                            <div class="shortcuts-grid">
                                <div class="shortcut-item"><kbd>F2</kbd><span>New Incident</span></div>
                                <div class="shortcut-item"><kbd>F5</kbd><span>Refresh Panels</span></div>
                                <div class="shortcut-item"><kbd>F9</kbd><span>Daily Log</span></div>
                                <div class="shortcut-item"><kbd>H</kbd><span>Held Calls</span></div>
                                <div class="shortcut-item"><kbd>Esc</kbd><span>Close Modal</span></div>
                                <div class="shortcut-item"><kbd>/</kbd><span>Focus Command Line</span></div>
                                <div class="shortcut-item"><kbd>Ctrl+S</kbd><span>Save Incident</span></div>
                                <div class="shortcut-item"><kbd>Ctrl+Enter</kbd><span>Submit & Close</span></div>
                            </div>
                        </div>

                        <div class="settings-group">
                            <div class="settings-group-title">Command Line Hints</div>
                            <div class="cli-hints">
                                <div class="cli-hint"><code>d [unit] [inc]</code> Dispatch unit to incident</div>
                                <div class="cli-hint"><code>e [unit]</code> Mark unit enroute</div>
                                <div class="cli-hint"><code>a [unit]</code> Mark unit arrived</div>
                                <div class="cli-hint"><code>c [unit]</code> Clear unit</div>
                                <div class="cli-hint"><code>h [inc]</code> Hold incident</div>
                                <div class="cli-hint"><code>r [inc]</code> Resume incident</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="cad-modal-footer settings-footer">
                    <button class="btn-secondary" onclick="SETTINGS.resetAllToDefaults()">Reset All</button>
                    <button class="btn-primary" onclick="SETTINGS.closeModal()">Done</button>
                </div>
            </div>
        `;

        const container = document.getElementById("fordcad-modal-container");
        if (container) {
            container.innerHTML = html;
            container.style.display = "flex";
        }
    },

    // -------------------------------------------------------------------------
    // Switch between settings tabs
    // -------------------------------------------------------------------------
    switchTab(tabId) {
        // Update tab buttons
        document.querySelectorAll(".settings-tab").forEach(tab => {
            tab.classList.toggle("active", tab.dataset.tab === tabId);
        });
        // Update panels
        document.querySelectorAll(".settings-panel").forEach(panel => {
            panel.classList.toggle("active", panel.id === `settings-panel-${tabId}`);
        });
    },

    // -------------------------------------------------------------------------
    // Set panel width from slider
    // -------------------------------------------------------------------------
    setPanelWidth(panel, value) {
        const pct = value + "%";
        if (panel === "calltaker") {
            _settings.panelCalltakerWidth = pct;
            document.getElementById("value-calltaker").textContent = pct;
            document.getElementById("preview-calltaker").style.width = pct;
        } else if (panel === "units") {
            _settings.panelUnitsWidth = pct;
            document.getElementById("value-units").textContent = pct;
            document.getElementById("preview-units").style.width = pct;
        }
        this.applyPanelWidths();
        this.save();
    },

    // -------------------------------------------------------------------------
    // Apply a layout preset
    // -------------------------------------------------------------------------
    applyLayoutPreset(preset) {
        const presets = {
            "default": { calltaker: "36%", units: "20%" },
            "wide-calltaker": { calltaker: "45%", units: "18%" },
            "wide-incidents": { calltaker: "28%", units: "18%" },
            "balanced": { calltaker: "33%", units: "22%" }
        };
        const p = presets[preset];
        if (p) {
            _settings.panelCalltakerWidth = p.calltaker;
            _settings.panelUnitsWidth = p.units;
            this.applyPanelWidths();
            this.save();
            // Update UI
            document.getElementById("slider-calltaker").value = parseInt(p.calltaker);
            document.getElementById("slider-units").value = parseInt(p.units);
            document.getElementById("value-calltaker").textContent = p.calltaker;
            document.getElementById("value-units").textContent = p.units;
            document.getElementById("preview-calltaker").style.width = p.calltaker;
            document.getElementById("preview-units").style.width = p.units;
        }
    },

    // -------------------------------------------------------------------------
    // Save current layout
    // -------------------------------------------------------------------------
    saveCurrentLayout() {
        const nameInput = document.getElementById("new-layout-name");
        const name = (nameInput?.value || "").trim();
        if (!name) {
            nameInput?.focus();
            return;
        }
        const layouts = _settings.savedLayouts || [];
        layouts.push({
            name: name,
            calltaker: _settings.panelCalltakerWidth,
            units: _settings.panelUnitsWidth
        });
        _settings.savedLayouts = layouts;
        this.save();
        // Refresh modal to show new layout
        this.openModal("layout");
    },

    // -------------------------------------------------------------------------
    // Load a saved layout
    // -------------------------------------------------------------------------
    loadSavedLayout(index) {
        const layouts = _settings.savedLayouts || [];
        const layout = layouts[index];
        if (layout) {
            _settings.panelCalltakerWidth = layout.calltaker;
            _settings.panelUnitsWidth = layout.units;
            this.applyPanelWidths();
            this.save();
            this.openModal("layout");
        }
    },

    // -------------------------------------------------------------------------
    // Delete a saved layout
    // -------------------------------------------------------------------------
    deleteSavedLayout(index) {
        const layouts = _settings.savedLayouts || [];
        layouts.splice(index, 1);
        _settings.savedLayouts = layouts;
        this.save();
        this.openModal("layout");
    },

    // -------------------------------------------------------------------------
    // Reset status colors to defaults
    // -------------------------------------------------------------------------
    resetStatusColors() {
        _settings.statusColors = { ...DEFAULT_SETTINGS.statusColors };
        this.applyStatusColors();
        this.save();
        this.openModal("colors");
    },

    // -------------------------------------------------------------------------
    // Reset all settings to defaults
    // -------------------------------------------------------------------------
    resetAllToDefaults() {
        if (confirm("Reset all settings to defaults? This cannot be undone.")) {
            _settings = { ...DEFAULT_SETTINGS };
            this.save();
            this.applyTheme(_settings.theme);
            this.applyFontSize(_settings.fontSize);
            this.applyDensity(_settings.density);
            this.applyPanelWidths();
            this.applyStatusColors();
            this.resetPanelWidths();
            this.openModal("appearance");
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
        // Update visual selection in modal
        document.querySelectorAll(".theme-option").forEach(btn => {
            btn.classList.toggle("selected", btn.textContent.trim().toLowerCase().replace(" ", "-") === theme);
        });
    },

    setFontSize(size) {
        this.set("fontSize", size);
    },

    setDensity(density) {
        this.set("density", density);
        // Update visual selection in modal
        document.querySelectorAll(".density-option").forEach(btn => {
            const btnDensity = btn.querySelector("span")?.textContent?.trim()?.toLowerCase();
            btn.classList.toggle("selected", btnDensity === density);
        });
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

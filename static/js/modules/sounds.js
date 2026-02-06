// ============================================================================
// FORD-CAD — SOUND ALERTS MODULE
// Audio notifications for dispatch events
// ============================================================================

const SOUNDS = {
    // Audio context (created on first user interaction)
    _ctx: null,
    _enabled: true,

    // -------------------------------------------------------------------------
    // Initialize audio context (must be called after user interaction)
    // -------------------------------------------------------------------------
    init() {
        // Check settings
        const settings = window.SETTINGS?.getAll?.() || {};
        this._enabled = settings.soundEnabled !== false;

        // Create audio context on first user click (browser requirement)
        document.addEventListener("click", () => this._ensureContext(), { once: true });
        document.addEventListener("keydown", () => this._ensureContext(), { once: true });

    },

    _ensureContext() {
        if (!this._ctx) {
            try {
                this._ctx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (e) {
                console.warn("[SOUNDS] AudioContext failed:", e);
            }
        }
        return this._ctx;
    },

    // -------------------------------------------------------------------------
    // Check if sounds are enabled
    // -------------------------------------------------------------------------
    isEnabled() {
        const settings = window.SETTINGS?.getAll?.() || {};
        return settings.soundEnabled !== false;
    },

    // -------------------------------------------------------------------------
    // Play a tone using Web Audio API (no external files needed)
    // -------------------------------------------------------------------------
    _playTone(frequency, duration, type = "sine", volume = 0.3) {
        if (!this.isEnabled()) return;

        const ctx = this._ensureContext();
        if (!ctx) return;

        try {
            const oscillator = ctx.createOscillator();
            const gainNode = ctx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(ctx.destination);

            oscillator.type = type;
            oscillator.frequency.setValueAtTime(frequency, ctx.currentTime);

            // Envelope: quick attack, sustain, quick release
            gainNode.gain.setValueAtTime(0, ctx.currentTime);
            gainNode.gain.linearRampToValueAtTime(volume, ctx.currentTime + 0.02);
            gainNode.gain.linearRampToValueAtTime(volume * 0.7, ctx.currentTime + duration - 0.05);
            gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + duration);

            oscillator.start(ctx.currentTime);
            oscillator.stop(ctx.currentTime + duration);
        } catch (e) {
            console.warn("[SOUNDS] Tone failed:", e);
        }
    },

    // -------------------------------------------------------------------------
    // Play a sequence of tones
    // -------------------------------------------------------------------------
    _playSequence(notes, gap = 0.05) {
        if (!this.isEnabled()) return;

        const ctx = this._ensureContext();
        if (!ctx) return;

        let time = ctx.currentTime;
        for (const [freq, dur, type, vol] of notes) {
            this._playToneAt(freq, dur, type || "sine", vol || 0.3, time);
            time += dur + gap;
        }
    },

    _playToneAt(frequency, duration, type, volume, startTime) {
        const ctx = this._ctx;
        if (!ctx) return;

        try {
            const oscillator = ctx.createOscillator();
            const gainNode = ctx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(ctx.destination);

            oscillator.type = type;
            oscillator.frequency.setValueAtTime(frequency, startTime);

            gainNode.gain.setValueAtTime(0, startTime);
            gainNode.gain.linearRampToValueAtTime(volume, startTime + 0.02);
            gainNode.gain.linearRampToValueAtTime(volume * 0.7, startTime + duration - 0.03);
            gainNode.gain.linearRampToValueAtTime(0, startTime + duration);

            oscillator.start(startTime);
            oscillator.stop(startTime + duration);
        } catch (e) {
            // Ignore
        }
    },

    // =========================================================================
    // ALERT SOUNDS
    // =========================================================================

    /**
     * New incident alert - attention-grabbing two-tone
     */
    newIncident() {
        // Classic two-tone alert (like emergency services)
        this._playSequence([
            [880, 0.15, "sine", 0.4],   // A5
            [660, 0.15, "sine", 0.4],   // E5
            [880, 0.15, "sine", 0.4],   // A5
            [660, 0.15, "sine", 0.4],   // E5
        ], 0.05);
    },

    /**
     * High priority dispatch - urgent triple beep
     */
    priorityDispatch() {
        this._playSequence([
            [1000, 0.1, "square", 0.3],
            [1000, 0.1, "square", 0.3],
            [1000, 0.1, "square", 0.3],
        ], 0.08);
    },

    /**
     * Unit dispatched - confirmation beep
     */
    unitDispatched() {
        this._playTone(800, 0.12, "sine", 0.25);
    },

    /**
     * Unit arrived - lower confirmation
     */
    unitArrived() {
        this._playTone(600, 0.15, "sine", 0.2);
    },

    /**
     * Unit cleared - double low beep
     */
    unitCleared() {
        this._playSequence([
            [400, 0.1, "sine", 0.2],
            [300, 0.15, "sine", 0.2],
        ], 0.05);
    },

    /**
     * Error / invalid action
     */
    error() {
        this._playTone(200, 0.2, "sawtooth", 0.2);
    },

    /**
     * Success / action completed
     */
    success() {
        this._playSequence([
            [523, 0.08, "sine", 0.2],   // C5
            [659, 0.08, "sine", 0.2],   // E5
            [784, 0.12, "sine", 0.25],  // G5
        ], 0.02);
    },

    /**
     * Notification / info
     */
    notify() {
        this._playTone(700, 0.1, "sine", 0.15);
    },

    /**
     * Held call reminder
     */
    heldReminder() {
        this._playSequence([
            [440, 0.2, "triangle", 0.2],
            [440, 0.2, "triangle", 0.2],
        ], 0.3);
    },

    /**
     * Timer alert - short siren sound (not excessive)
     */
    timerAlert() {
        // Short two-tone siren (about 1 second total)
        this._playSequence([
            [800, 0.15, "sine", 0.35],
            [600, 0.15, "sine", 0.35],
            [800, 0.15, "sine", 0.35],
            [600, 0.15, "sine", 0.35],
        ], 0.02);
    },
};

// Auto-initialize
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => SOUNDS.init());
} else {
    SOUNDS.init();
}

// Global exposure
window.SOUNDS = SOUNDS;
window.CAD = window.CAD || {};
window.CAD.sounds = SOUNDS;

export default SOUNDS;

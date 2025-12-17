// ============================================================================
// BOSK-CAD — DRAG ENGINE FOR MODALS
// Phase-3 Enterprise Edition
// ============================================================================
// Provides smooth, constrained, enterprise-grade dragging for all modals.
// Used by: IAW, UAW, IssueFound, Disposition, Picker, Remark.
// ============================================================================

export const BOSK_DRAG = {

    target: null,     // the modal being dragged
    offsetX: 0,       // pointer-to-modal offset
    offsetY: 0,
    active: false,    // true while dragging

    // ---------------------------------------------------------------------
    // START DRAG
    // Called by: onmousedown="IAW.startDrag(event)" etc.
    // ---------------------------------------------------------------------
    startDrag(event, modalSelector = ".bosk-modal") {
        const modal = event.target.closest(modalSelector);
        if (!modal) return;

        this.target = modal;

        // Calculate offset from modal top-left
        const rect = modal.getBoundingClientRect();
        this.offsetX = event.clientX - rect.left;
        this.offsetY = event.clientY - rect.top;

        this.active = true;

        // Raise modal above others
        modal.style.zIndex = 9999;

        // Bind listeners
        document.addEventListener("mousemove", this._move);
        document.addEventListener("mouseup", this._stop);
    },

    // ---------------------------------------------------------------------
    // MOVE MODAL
    // ---------------------------------------------------------------------
    _move: (e) => {
        if (!BOSK_DRAG.active || !BOSK_DRAG.target) return;

        const modal = BOSK_DRAG.target;

        let x = e.clientX - BOSK_DRAG.offsetX;
        let y = e.clientY - BOSK_DRAG.offsetY;

        // --------------------------------------------------------------
        // Constrain within viewport
        // --------------------------------------------------------------
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const rect = modal.getBoundingClientRect();

        // Keep modal within screen bounds
        if (x < 0) x = 0;
        if (y < 0) y = 0;
        if (x + rect.width > vw) x = vw - rect.width;
        if (y + rect.height > vh) y = vh - rect.height;

        modal.style.left = `${x}px`;
        modal.style.top = `${y}px`;
    },

    // ---------------------------------------------------------------------
    // STOP DRAGGING
    // ---------------------------------------------------------------------
    _stop: () => {
        BOSK_DRAG.active = false;

        document.removeEventListener("mousemove", BOSK_DRAG._move);
        document.removeEventListener("mouseup", BOSK_DRAG._stop);
    }
};


// ============================================================================
// SHORTCUT HOOKS FOR MODULES
// These wrapper functions allow modules to call DRAG without referencing
// BOSK_DRAG directly (keeps API clean and consistent).
// ============================================================================

export const IAW = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

export const UAW = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

export const DISP = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

export const ISSUE = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

export const PICKER = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

export const REMARK = {
    startDrag(event) { BOSK_DRAG.startDrag(event); }
};

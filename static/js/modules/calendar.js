// ============================================================================
// FORD-CAD — CALENDAR MODULE
// Calendar with 2-2-3 Shift Schedule display
// ============================================================================

window.CALENDAR = {
    currentDate: new Date(),

    async init() {
        await this.render();
    },

    async render() {
        const container = document.getElementById('calendar-days');
        if (!container) return;

        const year = this.currentDate.getFullYear();
        const month = this.currentDate.getMonth();

        // Fetch shift schedule
        let schedule = {};
        try {
            const res = await fetch(`/api/shift/schedule?days=42`);
            const data = await res.json();
            if (data.schedule) {
                data.schedule.forEach(s => {
                    schedule[s.date] = s;
                });
            }
        } catch (e) {
            console.warn('[CALENDAR] Failed to load shift schedule');
        }

        // Build calendar grid
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();

        let html = '';
        // Empty cells for days before first
        for (let i = 0; i < firstDay; i++) {
            html += '<div class="calendar-day empty"></div>';
        }

        // Days of month
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const shift = schedule[dateStr];
            const dayShift = shift?.day_shift || '';
            const nightShift = shift?.night_shift || '';
            const shiftClass = shift ? `shift-${dayShift.toLowerCase()}` : '';
            const isToday = this.isToday(year, month, day) ? 'today' : '';

            html += `<div class="calendar-day ${shiftClass} ${isToday}" data-date="${dateStr}">
                <span class="day-num">${day}</span>
                ${shift ? `
                    <div class="shift-labels">
                        <span class="shift-label shift-day" title="Day Shift">${dayShift}</span>
                        <span class="shift-label shift-night" title="Night Shift">${nightShift}</span>
                    </div>
                ` : ''}
            </div>`;
        }

        container.innerHTML = html;

        // Update title
        const title = document.querySelector('.calendar-month-title');
        if (title) {
            title.textContent = this.currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
        }
    },

    isToday(year, month, day) {
        const today = new Date();
        return today.getFullYear() === year &&
               today.getMonth() === month &&
               today.getDate() === day;
    },

    prevMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() - 1);
        this.render();
    },

    nextMonth() {
        this.currentDate.setMonth(this.currentDate.getMonth() + 1);
        this.render();
    },

    goToToday() {
        this.currentDate = new Date();
        this.render();
    }
};

// Auto-init when modal opens
document.addEventListener('DOMContentLoaded', () => {
    // Watch for calendar modal
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            m.addedNodes.forEach((node) => {
                if (node.querySelector && node.querySelector('.calendar-modal')) {
                    CALENDAR.init();
                }
            });
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
});

export default window.CALENDAR;

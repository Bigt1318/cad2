# FORD-CAD Fixes Round 3
## 2026-02-04 Evening Session

---

## IMMEDIATE: Start Server
The console errors are because the server isn't running. Start it:
```powershell
cd C:\cad2
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --port 8000
```

---

## 1. HELD CALLS - Auto-Clear Units

### Current Behavior
When incident is placed in HELD status, units remain assigned.

### Required Behavior
When incident goes to HELD:
1. Auto-clear all assigned units (disposition: "HELD")
2. Units return to AVAILABLE
3. Only the incident remains in HELD status

### Fix Location
`main.py` - Find the function that sets incident to HELD status

```python
def hold_incident(incident_id: int, reason: str, user: str):
    """Place incident on hold - auto-clears all units."""
    conn = get_conn()
    c = conn.cursor()
    ts = _ts()
    
    # Clear all assigned units first
    assigned_units = c.execute("""
        SELECT unit_id FROM UnitAssignments 
        WHERE incident_id = ? AND cleared IS NULL
    """, (incident_id,)).fetchall()
    
    for unit in assigned_units:
        # Clear unit with HELD disposition
        c.execute("""
            UPDATE UnitAssignments 
            SET cleared = ?, disposition = 'HELD'
            WHERE incident_id = ? AND unit_id = ? AND cleared IS NULL
        """, (ts, incident_id, unit['unit_id']))
        
        # Set unit back to AVAILABLE
        c.execute("""
            UPDATE Units SET status = 'AVAILABLE', updated = ?
            WHERE unit_id = ?
        """, (ts, unit['unit_id']))
    
    # Now set incident to HELD
    c.execute("""
        UPDATE Incidents 
        SET status = 'HELD', held_reason = ?, updated = ?
        WHERE incident_id = ?
    """, (reason, ts, incident_id))
    
    conn.commit()
    conn.close()
```

### Add held_reason Column
```sql
ALTER TABLE Incidents ADD COLUMN held_reason TEXT;
```

---

## 2. HELD CALLS LIST - Show Reason

### Current
Held calls list doesn't show why call was held.

### Fix
Update held incidents template to include reason column:

**File:** `templates/held_incidents.html`
```html
<table class="held-table">
    <thead>
        <tr>
            <th>Incident #</th>
            <th>Type</th>
            <th>Location</th>
            <th>Held Reason</th>  <!-- ADD THIS -->
            <th>Time Held</th>
        </tr>
    </thead>
    <tbody>
        {% for inc in held_incidents %}
        <tr onclick="openIAW({{ inc.incident_id }})">
            <td>{{ inc.incident_number }}</td>
            <td>{{ inc.type }}</td>
            <td>{{ inc.location }}</td>
            <td>{{ inc.held_reason or 'No reason given' }}</td>
            <td>{{ inc.updated }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

---

## 3. MESSAGING SYSTEM

### Requirements
- User-to-user messaging within CAD
- SMS messaging via carrier gateways
- Email messaging

### Database Schema
```sql
CREATE TABLE IF NOT EXISTS Messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id TEXT NOT NULL,
    recipient_id TEXT,           -- NULL for broadcast
    recipient_type TEXT,         -- 'USER', 'UNIT', 'SHIFT', 'ALL'
    subject TEXT,
    body TEXT NOT NULL,
    delivery_method TEXT,        -- 'CAD', 'SMS', 'EMAIL', 'ALL'
    status TEXT DEFAULT 'PENDING', -- 'PENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED'
    created TEXT,
    sent TEXT,
    read TEXT
);

CREATE TABLE IF NOT EXISTS MessageRecipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    recipient_id TEXT,
    delivery_method TEXT,
    status TEXT DEFAULT 'PENDING',
    sent TEXT,
    error TEXT,
    FOREIGN KEY (message_id) REFERENCES Messages(message_id)
);
```

### API Endpoints
```python
@app.post("/api/messages/send")
async def send_message(request: Request):
    """Send message to user(s) via CAD, SMS, or email."""
    data = await request.json()
    recipients = data.get("recipients", [])  # List of unit_ids or "ALL" or "SHIFT:A"
    subject = data.get("subject", "")
    body = data.get("body", "")
    method = data.get("method", "CAD")  # CAD, SMS, EMAIL, ALL
    
    # Implementation here...

@app.get("/api/messages/inbox")
async def get_inbox(request: Request):
    """Get messages for current user."""
    user = request.session.get("user")
    # Return unread and recent messages

@app.post("/api/messages/read/{message_id}")
async def mark_read(message_id: int, request: Request):
    """Mark message as read."""
```

### SMS Implementation (using carrier gateways)
```python
CARRIER_GATEWAYS = {
    'verizon': '@vtext.com',
    'att': '@txt.att.net', 
    'tmobile': '@tmomail.net',
    'sprint': '@messaging.sprintpcs.com',
}

def send_sms(phone: str, carrier: str, message: str):
    """Send SMS via email-to-SMS gateway."""
    gateway = CARRIER_GATEWAYS.get(carrier.lower())
    if not gateway:
        return False
    
    email_addr = phone.replace('-', '').replace(' ', '') + gateway
    # Use existing email sending infrastructure
    send_email(to=email_addr, subject="", body=message)
```

### Messaging UI
Add messaging button to header and create modal:
- Compose new message
- Select recipients (dropdown with units/shifts)
- Choose delivery method
- View inbox/sent messages
- Unread count badge

---

## 4. FIX DEPRECATED META TAG

**File:** `templates/index.html`

Change:
```html
<meta name="apple-mobile-web-app-capable" content="yes">
```
To:
```html
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
```

---

## 5. THEMES NOT APPLYING

Check these files for theme implementation:

1. **settings.js** - Is theme being saved and applied?
```javascript
apply() {
    const theme = this.get('theme');
    document.documentElement.setAttribute('data-theme', theme);
    // Also set class on body
    document.body.className = document.body.className.replace(/theme-\w+/g, '');
    document.body.classList.add(`theme-${theme}`);
}
```

2. **ford-cad-v4.css** - Are theme variables defined?
```css
[data-theme="dark"] {
    --bg-app: #0f172a;
    --bg-surface: #1e293b;
    --text-primary: #f1f5f9;
    /* etc */
}

[data-theme="light"] {
    --bg-app: #f1f5f9;
    --bg-surface: #ffffff;
    --text-primary: #0f172a;
    /* etc */
}
```

3. **On page load** - Is theme applied at startup?
```javascript
document.addEventListener('DOMContentLoaded', () => {
    CAD_SETTINGS.load();
    CAD_SETTINGS.apply();
});
```

---

## 6. VERIFICATION AFTER SERVER STARTS

Once server is running, these errors should stop:
- `/api/reports/pending` ✅ exists in reports.py
- `/api/held_count` ✅ exists in main.py  

If they still error, check:
1. Is reports.py being imported in main.py?
2. Are the routes registered?

---

## PRIORITY ORDER

1. **Start server** - fixes all connection errors
2. **Held calls auto-clear** - important workflow fix
3. **Held reason display** - usability
4. **Themes** - user preference
5. **Messaging** - new feature (bigger effort)

---

## TEST CHECKLIST

After fixes:
- [ ] Server runs without errors
- [ ] No console errors on page load
- [ ] Hold incident → units automatically cleared
- [ ] Held calls list shows reason
- [ ] Theme toggle works immediately
- [ ] Clock shows correct time with visible color

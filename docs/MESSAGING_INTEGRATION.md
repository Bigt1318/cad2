# FORD-CAD Messaging Integration Architecture

## Overview

This document outlines free/low-cost options for emergency notifications without expensive paging gateways like PageGate.

---

## Recommended Stack (Zero Cost)

### Primary: Signal (via signal-cli)
- **Free, encrypted, professional**
- Works on iOS, Android, Desktop
- Group messaging for crews/shifts
- No carrier fees

### Secondary: Web Push Notifications
- **Built into browsers**
- Works on mobile (add to home screen)
- No app store required

### Future: WebEx Integration
- Space notifications
- Emergency video calls
- API available

---

## Signal Integration

### Setup (One-Time)

1. **Install signal-cli** (on server):
   ```bash
   # Install Java runtime
   sudo apt install openjdk-17-jre
   
   # Download signal-cli
   wget https://github.com/AsamK/signal-cli/releases/latest/download/signal-cli-0.12.x.tar.gz
   tar xf signal-cli-*.tar.gz
   sudo mv signal-cli-*/bin/signal-cli /usr/local/bin/
   sudo mv signal-cli-*/lib /usr/local/lib/signal-cli
   ```

2. **Register a phone number** (for the CAD system):
   ```bash
   signal-cli -u +1YOURNUMBER register
   signal-cli -u +1YOURNUMBER verify CODE
   ```

3. **Create dispatch groups**:
   ```bash
   # Create A-Shift group
   signal-cli -u +1YOURNUMBER updateGroup -n "A-Shift Dispatch" -m +1MEMBER1 +1MEMBER2
   ```

### Python Integration

```python
# notifications/signal_notify.py

import subprocess
import json
from typing import List, Optional

SIGNAL_NUMBER = "+1YOURNUMBER"  # CAD system's Signal number

def send_signal_message(
    recipients: List[str],  # Phone numbers or group IDs
    message: str,
    group_id: Optional[str] = None
) -> bool:
    """Send a Signal message to individuals or a group."""
    try:
        cmd = ["signal-cli", "-u", SIGNAL_NUMBER, "send", "-m", message]
        
        if group_id:
            cmd.extend(["-g", group_id])
        else:
            cmd.extend(recipients)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"[SIGNAL] Send failed: {e}")
        return False

def send_dispatch_alert(
    incident_number: str,
    incident_type: str,
    location: str,
    units: List[str],
    group_id: str
) -> bool:
    """Send formatted dispatch alert."""
    message = f"""🚨 DISPATCH ALERT
━━━━━━━━━━━━━━━━
Incident: {incident_number}
Type: {incident_type}
Location: {location}
Units: {', '.join(units)}
━━━━━━━━━━━━━━━━
Respond immediately."""
    
    return send_signal_message([], message, group_id=group_id)

# Shift group IDs (set after creating groups)
SHIFT_GROUPS = {
    "A": "GROUP_ID_A",
    "B": "GROUP_ID_B", 
    "C": "GROUP_ID_C",
    "D": "GROUP_ID_D",
    "ALL": "GROUP_ID_ALL",
}
```

### FastAPI Integration

```python
# In main.py or notifications.py

from fastapi import BackgroundTasks

async def notify_dispatch(
    incident_id: int,
    units: List[str],
    background_tasks: BackgroundTasks
):
    """Queue dispatch notification."""
    # Get incident details
    inc = get_incident(incident_id)
    
    # Determine which shift to notify
    shift = get_current_shift_letter()
    group_id = SHIFT_GROUPS.get(shift, SHIFT_GROUPS["ALL"])
    
    # Send in background (don't block dispatch)
    background_tasks.add_task(
        send_dispatch_alert,
        inc["incident_number"],
        inc["type"],
        inc["location"],
        units,
        group_id
    )
```

---

## Web Push Notifications

### Setup

1. **Generate VAPID keys** (one-time):
   ```bash
   pip install pywebpush
   python -c "from pywebpush import webpush; import json; from cryptography.hazmat.primitives.asymmetric import ec; from cryptography.hazmat.backends import default_backend; key = ec.generate_private_key(ec.SECP256R1(), default_backend()); print(json.dumps({'private': key.private_bytes_raw().hex(), 'public': key.public_key().public_bytes_raw().hex()}))"
   ```

2. **Add service worker** to frontend:
   ```javascript
   // static/js/service-worker.js
   self.addEventListener('push', function(event) {
       const data = event.data.json();
       self.registration.showNotification(data.title, {
           body: data.body,
           icon: '/static/images/logo.png',
           badge: '/static/images/badge.png',
           tag: data.tag || 'cad-notification',
           requireInteraction: true,
           actions: [
               { action: 'view', title: 'View Incident' },
               { action: 'dismiss', title: 'Dismiss' }
           ]
       });
   });
   ```

3. **Subscribe users** on login:
   ```javascript
   // In layout.js or settings.js
   async function subscribeToPush() {
       const registration = await navigator.serviceWorker.ready;
       const subscription = await registration.pushManager.subscribe({
           userVisibleOnly: true,
           applicationServerKey: VAPID_PUBLIC_KEY
       });
       
       // Send subscription to server
       await fetch('/api/push/subscribe', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify(subscription)
       });
   }
   ```

---

## WebEx Integration (Future)

### Capabilities
- Post alerts to WebEx Spaces
- Trigger emergency meetings
- Send direct messages

### Setup
1. Create a WebEx Bot at developer.webex.com
2. Get Bot access token
3. Add bot to dispatch spaces

### Example
```python
import requests

WEBEX_TOKEN = "YOUR_BOT_TOKEN"
WEBEX_ROOM_ID = "DISPATCH_SPACE_ID"

def send_webex_alert(message: str):
    """Post message to WebEx Space."""
    requests.post(
        "https://webexapis.com/v1/messages",
        headers={
            "Authorization": f"Bearer {WEBEX_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "roomId": WEBEX_ROOM_ID,
            "markdown": message
        }
    )
```

---

## Free Email-to-SMS (Carrier Gateways)

For backup or carriers not on Signal:

| Carrier | Gateway |
|---------|---------|
| Verizon | @vtext.com |
| AT&T | @txt.att.net |
| T-Mobile | @tmomail.net |
| Sprint | @messaging.sprintpcs.com |

```python
import smtplib
from email.message import EmailMessage

def send_sms_via_email(phone: str, carrier: str, message: str):
    """Send SMS via carrier email gateway."""
    gateways = {
        "verizon": "vtext.com",
        "att": "txt.att.net",
        "tmobile": "tmomail.net",
    }
    
    if carrier not in gateways:
        return False
    
    msg = EmailMessage()
    msg.set_content(message)
    msg["To"] = f"{phone}@{gateways[carrier]}"
    msg["From"] = "cad@yourdomain.com"
    
    with smtplib.SMTP("localhost") as smtp:
        smtp.send_message(msg)
    
    return True
```

---

## Implementation Priority

1. **Phase 1**: Web Push (quick, works now)
2. **Phase 2**: Signal groups for shift crews
3. **Phase 3**: WebEx integration for command staff
4. **Phase 4**: Email-to-SMS fallback

---

## Configuration

Add to `config.env`:

```bash
# Signal
SIGNAL_ENABLED=true
SIGNAL_CLI_PATH=/usr/local/bin/signal-cli
SIGNAL_NUMBER=+1YOURNUMBER
SIGNAL_GROUP_A=GROUP_ID
SIGNAL_GROUP_B=GROUP_ID
SIGNAL_GROUP_C=GROUP_ID
SIGNAL_GROUP_D=GROUP_ID

# Web Push
WEBPUSH_ENABLED=true
VAPID_PUBLIC_KEY=your_public_key
VAPID_PRIVATE_KEY=your_private_key
VAPID_EMAIL=mailto:admin@yourdomain.com

# WebEx (optional)
WEBEX_ENABLED=false
WEBEX_BOT_TOKEN=
WEBEX_ROOM_ID=
```

---

## Next Steps

1. Test Signal setup with a phone number
2. Create shift groups
3. Add notification triggers to dispatch flow
4. Build settings UI for users to enable/disable notifications

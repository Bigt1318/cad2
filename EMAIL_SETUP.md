# FORD CAD Email Setup Guide

## Gmail SMTP Configuration

To send automated reports, you need to configure Gmail with an **App Password** (not your regular Gmail password).

### Step 1: Enable 2-Factor Authentication on Gmail

1. Go to https://myaccount.google.com/security
2. Under "Signing in to Google", click on **2-Step Verification**
3. Follow the prompts to enable 2FA

### Step 2: Create an App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select app: **Mail**
3. Select device: **Windows Computer** (or Other)
4. Click **Generate**
5. Copy the 16-character password (looks like: `abcd efgh ijkl mnop`)

### Step 3: Configure FORD CAD

**Option A: Edit the config file directly**

Edit `email_config.json` in the CAD folder:

```json
{
  "smtp_user": "bosksert@gmail.com",
  "smtp_pass": "your-16-char-app-password"
}
```

**Option B: Use the API**

```bash
curl -X POST http://localhost:8000/api/reports/config/email \
  -H "Content-Type: application/json" \
  -d '{"smtp_user": "bosksert@gmail.com", "smtp_pass": "your-app-password"}'
```

### Step 4: Test the Configuration

Send a test email:

```bash
curl -X POST "http://localhost:8000/api/reports/send/test?email=your-email@example.com"
```

Or view the report in browser:
- http://localhost:8000/api/reports/daily/html

## Battalion Chief Distribution List

Reports are automatically sent to:

| Battalion | Name | Email |
|-----------|------|-------|
| Battalion 1 | Bill Mullins | bill.mullins@blueovalsk.com |
| Battalion 2 | Daniel Highbaugh | daniel.highbaugh@blueovalsky.com |
| Battalion 3 | Kevin Jevning | kevin.jevning@blueovalsk.com |
| Battalion 4 | Shane Carpenter | shane.carpenter@blueovalsky.com |

## Automatic Report Schedule

Reports are sent automatically:

- **Every 30 minutes** during active shift hours
- **A Shift**: 0600-1730 (last report at 17:30)
- **B Shift**: 1800-0530 (last report at 05:30)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/daily` | GET | Get report as JSON |
| `/api/reports/daily/html` | GET | Get report as HTML |
| `/api/reports/daily/text` | GET | Get report as plain text |
| `/api/reports/send` | POST | Send report to all BCs |
| `/api/reports/send/test?email=X` | POST | Send test report |
| `/api/reports/config` | GET | View current config |
| `/api/reports/config/email` | POST | Update email settings |
| `/api/reports/scheduler/start` | POST | Start auto-reports |
| `/api/reports/scheduler/stop` | POST | Stop auto-reports |

## Troubleshooting

**"Email auth failed"**
- Make sure you're using an App Password, not your regular Gmail password
- Check that 2FA is enabled on the Gmail account

**"SMTP not configured"**
- The `smtp_pass` in `email_config.json` is empty
- Configure the password using the steps above

**Reports not sending automatically**
- Check if scheduler is running: `GET /api/reports/config`
- Start scheduler: `POST /api/reports/scheduler/start`

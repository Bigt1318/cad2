# FORD-CAD Logic Handoff

## Two-Lane Model

### Lane A: Emergency / Response Incidents
- Get units assigned, statuses, dispositions, closure rules
- Full incident lifecycle with audit trail

### Lane B: Daily Log Entries
- Non-emergency operational timeline items
- Notes/actions that don't become "incidents"
- Can be promoted to incident when needed

---

## Daily Log Rules

**Daily Log IS:**
- Running chronological timeline of non-emergency events
- Unit notes not tied to a call ("Unit 14 checked hydrant area")
- Admin operational notes ("Shift change completed", "Radio test ok")
- Minor events that don't warrant an incident number

**Daily Log is NOT:**
- A substitute for emergency incident lifecycle
- Something requiring full incident structure

**KEY RULE: Daily Log entries should NOT require a narrative.**

---

## Emergency Incident Rules

**Emergency Incident IS:**
- Tracked response event with:
  - Calltaker details
  - Unit assignments
  - Unit statuses
  - Remarks (timeline/audit log)
  - Disposition chain
  - Close rules

---

## AR (Add Remark) Routing Logic

Command: `<unit> AR <free text>`
Example: `14 AR patient walked in, minor cut, bandaged`

**Routing Decision:**
- **Case A:** Unit assigned to active/open incident → Incident Remark (goes into incident timeline)
- **Case B:** Unit NOT assigned to any incident → Daily Log entry

Same command, different destination based on unit assignment status.

---

## Held Calls

**"HELD" is an INCIDENT state, NOT a unit status.**

**What HELD means:**
- Incident exists but not actively being worked
- Paused / waiting / pending info / delayed response / standby
- Must remain visible and recoverable

**Non-negotiable:** Held incidents require a free-text reason.

**Use cases:**
- Waiting on Safety confirmation
- Equipment lockout/tagout delay
- Medical evaluation pending
- Area access restricted, escort required

---

## Incident Closure Chain (Strict)

**Emergency incident closure rules:**

1. **Unit Disposition** required when a unit clears
   - Capture disposition code/outcome for that unit

2. **Event Disposition** required before incident can be CLOSED
   - Even if all units cleared, incident cannot close without event disposition

3. **Last unit clears → triggers Event Disposition modal**

**Daily Log has NONE of this.** Daily Log entries don't "close" with dispositions.

---

## Incident Numbering

| Type | Has Incident Number | Has Internal ID |
|------|---------------------|-----------------|
| Normal Emergency | Yes | Yes |
| TRANSPORT | No | Yes |
| Daily Log Entry | No | dailylog_id |

---

## Promoting Daily Log to Incident

- Daily Log entry can be "promoted" to an incident
- After promotion:
  - Incident lives in incident system
  - Original log entry remains (marked "converted" but NOT deleted)
  - Daily log timeline must remain stable regardless of promotions

---

## Decision Trees

### When dispatcher enters a note/remark:
1. Is it tied to an existing incident?
   - Yes → Incident Remark
   - No → Daily Log Entry

### When dispatcher creates a "thing":
1. Does it require unit dispatch / response tracking?
   - Yes → Emergency Incident
   - No → Daily Log
2. Is it non-emergency transport?
   - Yes → TRANSPORT incident (no incident number)
   - No → Normal incident (with incident number)

### When pausing an incident:
1. Hold requested?
   - Require free-text reason
   - Move to Held state (incident-only)

### When closing an incident:
1. All units cleared? ✓
2. Unit dispositions captured? ✓
3. Event disposition captured? ✓
4. Then CLOSED allowed

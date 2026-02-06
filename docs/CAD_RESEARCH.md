# Commercial CAD Systems Research Report
## Guidance for Developing an Industrial Fire Brigade CAD

*Research compiled January 2026*

---

## Executive Summary

This report analyzes leading commercial Computer-Aided Dispatch (CAD) systems to identify patterns, features, and best practices that should guide the development of a CAD system for industrial fire brigades. The systems analyzed include Tyler Technologies New World CAD, Hexagon/Intergraph CAD, Mark43 CAD, CentralSquare CAD, and Motorola Spillman Flex.

**Key Takeaway:** Great CAD systems share common DNA: keyboard-first interaction, real-time situational awareness, unified data integration, and interfaces designed for high-stress, split-second decision-making.

---

## 1. Tyler Technologies New World CAD (Enterprise CAD)

### Overview
Tyler's Enterprise CAD is one of the most widely deployed CAD systems in North America, used in 44 states with 50%+ PSAP coverage in Pennsylvania. It's a cloud-hosted solution designed for multi-jurisdictional, multi-discipline dispatching.

### Core UI Layout Patterns
- **Multi-panel workspace**: Separate panels for active calls, unit status board, mapping, and pending queue
- **Call sheet design**: Optimized for rapid data entry with logical field progression
- **Predictive command line**: Auto-suggests next data fields for rapid input
- **Smart Dispatch Button**: Guides dispatchers through call sheets intuitively
- **Esri ArcGIS mapping integration**: Real-time geographic visualization

### Unit Status Model
- **Status states**: Available, Dispatched, Enroute, On Scene, Busy, Out of Service
- **AVL integration**: Automatic Vehicle Location tracking for proximity dispatching
- **Real-time ETA**: Continuously updated estimated time of arrival
- **Color coding**: Typically green (available), yellow (dispatched/enroute), red (busy/out of service)

### Dispatch Workflow
1. Call received → Call sheet populated via geo-verified address
2. System auto-recommends closest available units (proximity dispatching)
3. Dispatcher confirms or overrides recommendation
4. Silent dispatch option for sensitive operations
5. Real-time updates flow between dispatcher and field units
6. Call resolution and disposition logging

### Fire-Specific Features
- Unlimited fire response recommendations
- Building pre-plan integration
- Hydrant location mapping
- Hazmat information access
- Multi-agency mutual aid coordination

### Enterprise Grade Qualities
- 98% client retention rate
- Cloud-hosted architecture
- Cross-jurisdictional data sharing
- State/federal reporting compliance
- 24/7 mission-critical reliability

---

## 2. Hexagon Safety & Infrastructure (Intergraph CAD)

### Overview
Hexagon I/CAD is considered the "gold standard" in large-scale public safety deployments, particularly in major metropolitan areas and international markets. Powers many of the world's largest 911 centers.

### Core UI Layout Patterns
- **Command-line driven**: Heavily keyboard-centric interface for experienced dispatchers
- **Dockable windows**: Customizable workspace with detachable panels
- **Multi-monitor support**: Designed for 3-6 monitor workstations
- **Color-coded status boards**: Dense information displays
- **Tabbed incident views**: Multiple active incidents manageable simultaneously

### Unit Status Model
- **Sophisticated state machine**: 15+ configurable unit states
- **Automatic status transitions**: Time-based status changes (e.g., auto-available after X minutes)
- **Custom status codes**: Agency-configurable statuses
- **Hierarchical unit groupings**: Apparatus → Station → Battalion → Division

### Dispatch Workflow
1. ANI/ALI integration receives caller information automatically
2. Incident type drives recommended response (run cards)
3. Dispatcher uses function keys for rapid status updates
4. CAD-to-CAD interoperability for multi-jurisdiction incidents
5. Automated timestamping of all actions

### Key Features
- **ProQA integration**: Protocol-based call-taking (MPDS, FPDS)
- **Run cards**: Pre-configured response plans by incident type and location
- **Geofile management**: Sophisticated address verification and routing
- **Interfaces**: 200+ third-party integrations available
- **High availability**: Clustered architecture with automatic failover

### Enterprise Grade Qualities
- Handles 10,000+ calls/day in large deployments
- CJIS-compliant security
- Disaster recovery built-in
- Multi-language support
- Extensive audit trails

---

## 3. Mark43 CAD

### Overview
Mark43 represents the "next generation" of CAD systems—cloud-native, modern UX, and built on contemporary web technologies. Known for rapid deployment (2-5 weeks) and intuitive design.

### Core UI Layout Patterns
- **Modern web interface**: React-based, responsive design
- **Clean, minimal aesthetic**: Reduced visual clutter compared to legacy systems
- **Card-based layouts**: Incidents displayed as cards with key information surfaced
- **Real-time collaboration**: Multiple users see changes instantly
- **Mobile-first thinking**: Consistent experience across devices

### Unit Status Model
- **Simplified states**: Available, Dispatched, Enroute, Arrived, Busy, Off Duty
- **GPS-based tracking**: Esri mobile tracking shows real-time officer locations
- **Visual unit cards**: Rich information display per unit
- **Drag-and-drop assignment**: Modern interaction patterns

### Dispatch Workflow
1. Incident creation with predictive address lookup
2. Visual unit selection from map or status board
3. One-click dispatch with automatic notifications
4. Real-time field updates via OnScene mobile app
5. Seamless transition from dispatch to records management

### UX Innovations
- **50-80% reduction in report writing time**: Streamlined data entry
- **Dynamic reporting**: Auto-populated fields, error detection
- **Integrated platform**: CAD + RMS + Analytics + Mobile as unified system
- **Human-in-the-loop AI**: Automated recommendations with human override
- **Response plan execution**: Automated workflows with dispatcher control

### Fire/EMS Capabilities
- Multi-discipline coordination (Law, Fire, EMS)
- Breaks down silos between police and fire dispatch
- Unified incident view across disciplines

### Enterprise Grade Qualities
- **FedRAMP High Authorization**: Only CAD/RMS with this federal certification
- **GovRAMP High Authorization**
- **ISO 27001 certified**
- **UK Cyber Essentials Plus**
- Cloud-native architecture (not just cloud-hosted)

---

## 4. CentralSquare CAD (ONESolution)

### Overview
CentralSquare serves 8,000+ agencies with a focus on interoperability and cloud migration. Their platform emphasizes being "hero-grade" software for mission-critical environments.

### Core UI Layout Patterns
- **Traditional Windows-based interface**: Familiar to long-time CAD users
- **Customizable workspaces**: Role-based screen configurations
- **Status board prominence**: Large, visible unit status display
- **Multi-window architecture**: Popup windows for detailed information

### Unit Status Model
- **Standard emergency service statuses**: In Quarters, Responding, On Scene, Available, OOS
- **Apparatus-level tracking**: Individual unit status with crew information
- **Station status**: Aggregate view of station availability

### Dispatch Workflow
- Traditional call-taking → unit selection → dispatch workflow
- Emphasis on interoperability with other agencies
- Real-time data sharing across jurisdictions

### Key Features
- **Vertex NG911 Call Handling**: Next-generation 911 integration
- **Cloud-hosted options**: AWS-based infrastructure
- **Most interoperable**: Industry-leading cross-agency communication
- **Mobile situational awareness**: Field access to dispatch data

### Enterprise Grade Qualities
- 1,000+ cloud deployments
- Cybersecurity focus
- Disaster resilience (survived Alaska earthquake)
- Flexible pricing model

---

## 5. Motorola Spillman Flex

### Overview
Spillman Flex has 40+ years in public safety software (since 1982), now part of Motorola Solutions' connected ecosystem. Known for stability and customer-driven development.

### Core UI Layout Patterns
- **Traditional grid-based status boards**: Dense information display
- **Integrated mapping**: Built-in GIS visualization
- **Form-based data entry**: Structured input screens
- **Tabbed interfaces**: Multiple active views

### Unit Status Model
- **Configurable status codes**: Agency-defined statuses
- **Hierarchical organization**: Unit → Agency → Region
- **AVL integration**: Real-time vehicle tracking

### Key Capabilities
- **Single and multi-jurisdictional**: Scales from small to regional
- **CAD + Mobile + RMS + Jail**: Full public safety suite
- **Proven stability**: 1,600+ agencies rely on it
- **Legacy expertise**: Deep institutional knowledge

### Enterprise Grade Qualities
- Part of Motorola's broader safety ecosystem
- Integration with radio systems
- Long-term vendor stability
- Comprehensive training and support

---

## Common UI Patterns Across All Systems

### Primary Layout Structure
```
┌─────────────────────────────────────────────────────────────────┐
│  Menu Bar / Toolbar                                    │ Status │
├──────────────────┬──────────────────┬───────────────────────────┤
│                  │                  │                           │
│   Pending        │    Active        │        Map View           │
│   Calls          │    Incidents     │    (AVL/Units/Incidents)  │
│   Queue          │    Panel         │                           │
│                  │                  │                           │
├──────────────────┴──────────────────┼───────────────────────────┤
│                                     │                           │
│       Unit Status Board             │    Call/Incident          │
│    (All units, color-coded)         │    Detail Panel           │
│                                     │                           │
├─────────────────────────────────────┴───────────────────────────┤
│  Command Line / Quick Entry          │ Alerts / Notifications   │
└─────────────────────────────────────────────────────────────────┘
```

### Unit Status Color Coding (Industry Standard)
| Status | Color | Meaning |
|--------|-------|---------|
| Available | Green | Ready for dispatch |
| Dispatched | Yellow/Amber | Assigned, not yet enroute |
| Enroute | Blue | Responding to call |
| On Scene | Red/Orange | At incident location |
| Busy | Gray | On call, but interruptible |
| Out of Service | Dark Gray/Black | Not available |
| At Hospital | Purple | EMS-specific |

---

## Keyboard Shortcuts & Command Line Interfaces

### Common CAD Keyboard Patterns
Most enterprise CAD systems are heavily keyboard-driven for speed:

| Shortcut | Action |
|----------|--------|
| F1-F12 | Unit status changes (F1=Available, F2=Dispatched, etc.) |
| Ctrl+N | New incident/call |
| Ctrl+D | Dispatch selected unit |
| Tab | Move to next field |
| Enter | Confirm/Submit |
| Esc | Cancel/Clear |
| Ctrl+F | Find/Search |
| Space | Select/Toggle |
| Arrow keys | Navigate lists |
| Alt+# | Switch between panels |

### Command Line Conventions
Many CAD systems support type-ahead command entry:
```
/D 123 E41        → Dispatch Engine 41 to incident 123
/S E41 OS         → Set Engine 41 to On Scene
/L 123 Main St    → Look up address
/U E41            → Query unit status
/I 123            → Query incident details
```

### Best Practice: Minimal Mouse Usage
Experienced dispatchers measure efficiency in keystrokes. The best CAD systems allow:
- Full call creation without touching mouse
- Status updates via function keys
- Address lookup with type-ahead
- Unit selection via keyboard navigation

---

## Best Practices for Dispatcher UX

### 1. Information Hierarchy
- **Primary**: Active incident details, assigned units
- **Secondary**: Unit status board, pending calls
- **Tertiary**: Map view, historical data

### 2. Cognitive Load Management
- **Reduce clutter**: Show only what's needed for the current task
- **Color with purpose**: Use color sparingly but meaningfully
- **Consistent placement**: Same information in same location always
- **Progressive disclosure**: Details on demand, not always visible

### 3. Error Prevention
- **Address validation**: Geo-verify before accepting
- **Confirmation dialogs**: For destructive or irreversible actions only
- **Auto-save**: Never lose data
- **Undo capability**: Where possible

### 4. High-Stress Design Principles
- **Large click targets**: Bigger buttons for stressed users
- **High contrast**: Easy to read under any lighting
- **Audio feedback**: Sounds for alerts and confirmations
- **Visual alerts**: Flashing/pulsing for urgent items
- **No dead ends**: Always a path forward

### 5. Multi-Monitor Optimization
- **Dedicated map display**: One monitor for geographic awareness
- **Status board monitor**: Always-visible unit status
- **Incident detail monitor**: Active call management
- **Peripheral monitors**: Phones, CCTV, radio

---

## Industrial Fire Brigade vs Municipal 911: Key Differences

### Municipal 911 CAD Requirements
- Multiple agency coordination (Law, Fire, EMS)
- Public caller interface (ANI/ALI, text-to-911)
- Large geographic coverage
- High call volume (hundreds/thousands per day)
- NFIRS/NEMSIS reporting requirements
- Mutual aid coordination
- Public records compliance

### Industrial Fire Brigade Specific Needs

#### 1. Site-Specific Knowledge Integration
- **Building/facility pre-plans**: Detailed floor plans, hazard locations
- **Process information**: What chemicals/processes are where
- **Shutdown procedures**: Emergency isolation points
- **Personnel tracking**: Who's on site, where
- **Access control integration**: Gate/door control

#### 2. Simplified Call Sources
- Fewer call sources (plant phones, alarms, radio)
- Known caller population (employees vs random public)
- Integration with industrial alarm systems
- Fire panel/detection system integration

#### 3. Different Unit Types
- **Fire apparatus**: Pumpers, tankers, rescue
- **Specialized equipment**: Foam units, hazmat, confined space
- **Response teams**: Fire team, rescue team, hazmat team
- **External resources**: Mutual aid, ambulance, corporate response

#### 4. Incident Types
- Process fires (chemical, electrical)
- Confined space rescue
- Hazmat releases
- Medical emergencies
- Environmental incidents
- Security incidents

#### 5. Regulatory Compliance
- OSHA requirements (29 CFR 1910.156)
- EPA reporting
- NFPA 600 (Facility Fire Brigades)
- Insurance requirements
- Corporate policy compliance

#### 6. Smaller Scale, Higher Stakes
- Fewer incidents, but potentially catastrophic
- Every responder knows every other responder
- Local knowledge is critical
- Faster decision-making required
- Less bureaucracy, more flexibility

#### 7. Integration Points
- Plant alarm systems (DCS, fire panels)
- Access control systems
- CCTV systems
- Emergency notification systems
- HR systems (personnel, training records)
- Maintenance systems (equipment status)

---

## What Makes a Great CAD System

### 1. Speed
- Sub-second response times
- Minimal clicks/keystrokes to dispatch
- Real-time data synchronization
- No lag between action and confirmation

### 2. Reliability
- 99.99%+ uptime
- Graceful degradation (works offline)
- Automatic failover
- Data integrity guarantees

### 3. Situational Awareness
- Real-time unit location (AVL)
- Live incident status
- Resource availability at a glance
- Map-based visualization

### 4. Flexibility
- Configurable workflows
- Custom status codes
- Adaptable to agency needs
- API for integrations

### 5. Simplicity
- Learnable in days, not months
- Intuitive for new users
- Efficient for experts
- Consistent patterns throughout

### 6. Integration
- Single source of truth
- Connects to existing systems
- Eliminates double-entry
- Real-time data sharing

### 7. Auditability
- Complete action logging
- Timestamped events
- Who did what, when
- Defensible records

---

## Recommendations for Industrial Fire Brigade CAD

### Core Features (Must Have)
1. **Unit status board** with real-time updates and color coding
2. **Incident management** with lifecycle tracking
3. **Dispatch workflow** with quick keyboard-driven assignment
4. **Mapping** with facility-specific overlays
5. **Pre-plans** integration for buildings and processes
6. **Personnel tracking** (who's on duty, training status)
7. **Audit trail** for all actions

### High-Value Features
1. **Alarm system integration** (receive alarms directly)
2. **Mobile access** for responders (tablets, phones)
3. **Response recommendations** based on incident type
4. **Timer/countdown** for response benchmarks
5. **Radio integration** (if applicable)
6. **After-action reporting** with auto-populated data

### UX Priorities
1. **Keyboard-first design** with mouse as backup
2. **High-contrast themes** (light and dark options)
3. **Large, clear status indicators**
4. **Audible alerts** for new incidents
5. **Minimal training required** (intuitive)
6. **Works on single or multiple monitors**

### Differentiators from Municipal CAD
1. **Simpler**: Fewer agencies, fewer incident types
2. **Faster setup**: Less configuration, more convention
3. **Site-specific**: Built-in facility knowledge
4. **Process-aware**: Understands industrial operations
5. **Cost-effective**: Right-sized for industrial use

---

## Appendix: CAD Data Model Basics

### Incident
```
- Incident ID (unique)
- Type/Nature
- Priority
- Location (address, coordinates, facility area)
- Reported time
- Status (Open, Dispatched, In Progress, Closed)
- Units assigned
- Narrative/Notes
- Timestamps (all state changes)
```

### Unit
```
- Unit ID (e.g., "E41")
- Type (Engine, Rescue, Ambulance, Team)
- Home station/location
- Current status
- Current location (AVL)
- Personnel assigned
- Equipment/Capabilities
```

### Personnel
```
- ID
- Name
- Role/Certifications
- Current assignment
- Duty status
- Training records
```

### Status Timeline (per incident)
```
- Call received: timestamp
- Dispatched: timestamp
- Enroute: timestamp
- On scene: timestamp
- Under control: timestamp
- Cleared: timestamp
```

---

## References & Further Reading

1. Tyler Technologies - Enterprise CAD: https://www.tylertech.com/solutions/courts-public-safety/public-safety/computer-aided-dispatch
2. Mark43 Platform: https://mark43.com/platform/cad/
3. Motorola Spillman Flex: https://www.motorolasolutions.com/en_us/products/command-center-software/public-safety-software/flex.html
4. CentralSquare Public Safety: https://www.centralsquare.com/solutions/public-safety-software
5. NENA Standards: https://www.nena.org/
6. APCO Standards: https://www.apcointl.org/
7. NFPA 600 - Facility Fire Brigades: https://www.nfpa.org/
8. Wikipedia - Computer-aided dispatch: https://en.wikipedia.org/wiki/Computer-aided_dispatch

---

*Report generated for internal development guidance. Commercial CAD information compiled from public sources.*

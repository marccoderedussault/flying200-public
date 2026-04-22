# Flying 200 Mobile

A React Native app for analyzing and optimizing Flying 200-meter track cycling efforts. Integrates with Strava to retrieve ride data, detects 200m sprint efforts, and provides real-time simulation and optimization recommendations.

## Technology Stack

- **Framework:** React Native with Expo (v54.0.31)
- **Language:** TypeScript
- **State Management:** Zustand
- **Charts:** react-native-chart-kit
- **Routing:** Expo Router (tab-based navigation)
- **Build:** Expo EAS
- **Bundle ID:** `com.flying200.mobile`

## Features

### Home Tab
- Strava authentication and connection via OAuth 2.0
- Lists recent rides with power data
- Activity selection for analysis
- Server health check and API configuration

### Inputs Tab
- Define track segments (22 segments across 3+ laps)
- Select seated vs. standing position for each segment
- Configure kit options:
  - Wheel types (front disc, 3/4/5 spoke; rear disc vs. spokes)
  - Apparel (speed suit, aero helmet, shoe covers)
  - Aerodynamic modifiers (CdA adjustments: -0.0025 to +0.015 m²)

### Analysis Tab
- Auto-detection of Flying 200m efforts from activity data
- Environmental air density calculation (temperature, pressure, humidity)
- Quick simulation runs for each detected effort
- Power curve extraction from activities
- Manual effort selection fallback

### Simulation Tab
- Detailed parameter editing (mass, air density, rolling resistance, CP, W', CdA)
- Gearing configuration (chainring, cog, wheel circumference)
- Track geometry profile (895m with 22 elevation/CdA waypoints)
- Visualize speed profiles and splits
- Dual CdA solving (seated vs. standing optimization)

### Optimizer Tab
- Energy budget optimization using athlete power curve
- Position/power redistribution with zero-sum adjustments
- Athlete power curve management:
  - Import from Strava (last N activities)
  - Manual entry at standard durations (1-90 seconds)
  - Seated discount formula: `seated = standing × (1 - discount)`
- Optimization config: energy budget, minimum power floor, sampling count

---

## Physics Engine

The physics engine simulates a complete Flying 200m effort on a 250m velodrome track.

### Track Geometry

- **Total distance:** 895m (3+ lap buildup + timed 200m)
- **Banking angles:** 12° on straights, 42° on bends (with transitions)
- **Path scaling in bends:** `ds_arc = ds_black × (R_bend + y) / R_bend`
- **3D distance:** `ds_actual = √(ds_arc² + dy²)`

### Force Modeling

**Aerodynamic Drag:**
```
F_aero = 0.5 × ρ × CdA × v²
```

**Rolling Resistance:**
```
F_rr = C_rr × m × g × cos(θ)
```

**Gravitational Potential Energy:**
```
dE_pot = m × g × dh
```

### Power & W' (Anaerobic Capacity) Model

The engine implements the Critical Power model with W' depletion:

```
if P_target ≤ CP:
    P_eff = P_target
    dW' = -(CP - P_target) × dt          # Recovery when below CP
elif W'_remaining ≤ 0:
    P_eff = CP                            # Exhausted - capped at CP
else:
    max_above_CP = W'_remaining / dt
    P_above_CP = min(P_target - CP, max_above_CP)
    P_eff = CP + P_above_CP
    dW' = -P_above_CP × dt                # W' depletion
```

### Energy Integration

The simulation solves the energy equation at each time step:

```
W_rider = P_eff × drivetrain_eff × dt     # Work from rider
dE_kin = W_rider - W_resist - dE_pot       # Net kinetic energy change
v_next = √(2 × E_kin_next / m)             # Updated velocity
```

### Default Parameters

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| Mass | 92 kg | Rider + bike |
| Air density (ρ) | 1.1627 kg/m³ | Sea level standard |
| Rolling resistance (C_rr) | 0.002 | Tire coefficient |
| Critical Power (CP) | 250 W | Aerobic threshold |
| W' | 25,000 J | Anaerobic capacity |
| CdA (seated) | 0.24 m² | Drag area seated |
| CdA (standing) | 0.38 m² | Drag area standing |
| Drivetrain efficiency | 98% | Power transmission |

### Output Metrics

- `T_200`: Time for final timed 200m section
- `T_total`: Total effort time
- `v_200_entry`, `v_200_exit`: Entry/exit speeds at 200m mark
- `v_max`: Maximum speed reached
- `splits_200`: 50m splits (0-50, 50-100, 100-150, 150-200)
- `W'_remaining`: Anaerobic capacity left at finish

---

## Optimization Logic

### Energy Budget Optimizer

Maximizes 200m performance within physiological energy limits.

**Algorithm:**

1. **Segmentation:** Divide 895m effort into ~16 segments (50m each)
2. **Position allocation:** Each segment assigned seated or standing
3. **Power ceiling calculation:** At each segment, max power = minimum of:
   - Athlete power curve for that duration
   - Remaining W' / remaining time
4. **Constraint validation:**
   - Power curve ceilings (seated vs. standing)
   - Minimum power floors (e.g., ≥80% of baseline)
   - Position change penalties (smooth transitions)
5. **Random sampling:** Test 500+ random segment allocations
6. **Smoothing:** Apply 2-3% penalty to prevent unrealistic power spikes

**Output:**
- Optimal position sequence (seated/standing per segment)
- T_200 improvement (milliseconds saved)
- Per-segment energy allocation
- Speed profiles (baseline vs. optimized)

### Sprint Position Optimizer

Optimizes seated vs. standing transitions during the sprint phase.

**Constraints:**
- Minimum 3 seconds in each position (avoid rapid switching)
- Binary CdA: seated (0.24) or standing (0.38)
- Sprint phase only (last ~30 seconds before 200m finish)
- Must be seated for final 200m + buffer zone

**Power Curve Handling:**
- Converts average power curve to instantaneous power
- Cubic spline smoothing to avoid oscillations
- Validates running average ≤ curve limit at all times

### Power Redistribution Optimizer

Adjusts power within sections (zero-sum) to minimize time.

**Algorithm:**

1. **Section parsing:** Extract from profile CSV
2. **Power multipliers:** Apply per-section (0.8-1.2×)
3. **Constraint validation:**
   - Peak power: No point exceeds 1-second max
   - Running average: Average power from start to time t ≤ curve(t)
4. **Random search:** 500+ random multiplier combinations
5. **Feasibility filtering:** Only valid solutions considered

**Power Curve Constraint Class:**
```typescript
PowerCurveConstraint:
  - get_max_power_for_duration(duration_s)  // Interpolate curve
  - validate_power_sequence(power_array, dt_array)
      // Check 1: Peak power ≤ 1-second max
      // Check 2: Running average ≤ power curve at each time point
```

---

## Effort Detection Algorithm

The app uses a two-pass detection algorithm to identify Flying 200m efforts.

### Pass 1: Ramp Detection (Standard Profiles)

1. **Find drop-off points:** Identify transitions from high power/speed to low
   - Power drop: High threshold → Low threshold
   - Speed drop: 55 km/h → 25 km/h
2. **Work backwards to find ramp start:**
   - Speed range: 5-35 km/h (gradual buildup)
   - Ramp power: 50-450W (moderate buildup)
   - Duration: 60-130s total
3. **Validate effort:**
   - Sprint duration: 8-60 seconds
   - Total duration: 40-140 seconds
   - Speed increase during ramp: >2 km/h
   - Zero power before start: <8 seconds (rule out standing starts)
4. **Apply END - 90s override:** `startTime = endTime - 90 seconds`

### Pass 2: Fallback (END - 90s)

- Only triggered if Pass 1 finds nothing
- For each drop-off, create 90-second effort window
- Validate: Sprint avg power ≥ 50% of high threshold

### Sensitivity Presets

| Preset | Description |
|--------|-------------|
| Low | Relaxed thresholds, catches more efforts |
| Medium | Balanced (default) |
| High | Strict, fewer false positives |

**Medium Sensitivity Thresholds:**
- Power high: 30% of file max (capped at 500W)
- Power low: 15% of file max (capped at 200W)
- Ramp ceiling: 45% of file max (capped at 450W)
- Effort duration: 40-140 seconds
- Sprint duration: 8-60 seconds

---

## Project Structure

```
flying200-mobile/
├── app/                           # React Native screens
│   ├── index.tsx                  # Home (Strava login, activities)
│   ├── analysis.tsx               # Effort detection & quick sim
│   ├── simulation.tsx             # Manual simulation
│   ├── optimizer.tsx              # Energy budget & power optimization
│   ├── inputs.tsx                 # Track segments & kit config
│   ├── manual-select.tsx          # Manual effort selection
│   └── _layout.tsx                # Tab navigation
├── store/
│   └── simulationStore.ts         # Zustand state + detection logic
├── api/
│   └── client.ts                  # API client + types
├── package.json                   # Dependencies
└── app.json                       # Expo config
```

---

## Setup

### Prerequisites

- Node.js 18+
- Expo CLI
- iOS Simulator or physical device

### Installation

```bash
# Install dependencies
npm install

# Start development server
npx expo start

# Run on iOS
npx expo run:ios
```

### Environment Configuration

The app reads the backend URL from `EXPO_PUBLIC_BACKEND_URL`. Copy `.env.example` to `.env` and set the value to your deployed optimizer service (or `http://localhost:3001/api` for local dev).

Deep link scheme: `flying200://`

---

## API Integration

The app communicates with a Node.js/Express backend that bridges to the Python physics engine.

### Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `/simulation/run` | Execute physics simulation |
| `/simulation/breakeven-cda` | Solve for uniform CdA |
| `/simulation/dual-breakeven-cda` | Solve for seated/standing CdA |
| `/optimizer/energy-budget` | Run energy budget optimizer |
| `/optimizer/redistribution` | Run power redistribution optimizer |
| `/fit/quick-simulation-from-records` | Quick sim from activity stream |
| `/strava/activities` | Fetch Strava activities |
| `/strava/streams` | Get activity data streams |
| `/strava/auth-url` | OAuth flow initiation |
| `/strava/callback` | OAuth callback handler |

---

## License

Proprietary - All rights reserved.

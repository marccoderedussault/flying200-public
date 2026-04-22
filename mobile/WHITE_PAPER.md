# Flying 200: Physics-Based Sprint Optimization for Track Cycling

## White Paper

### Version 1.0 | 2026

---

## Abstract

Flying 200 is a mobile application that brings physics-based simulation and optimization to track cycling sprint events. By combining real activity data from Strava and FIT files with a validated aerodynamic model of a 250-meter velodrome, the app enables athletes and coaches to analyze recorded efforts, simulate performance under varying conditions, and discover optimal pacing strategies -- all from an iOS device trackside. This paper describes the problem domain, the physics engine underpinning the app, the optimization algorithms employed, and the practical workflow that connects raw ride data to actionable race strategy.

---

## 1. Introduction

### 1.1 The Problem

Track cycling sprint events -- the Flying 200m, Flying 150m, Flying 100m, and Flying 50m -- are decided by margins measured in thousandths of a second. An athlete's final time is determined by the interaction of human power output, aerodynamic drag, rolling resistance, gravitational forces on banked surfaces, drivetrain efficiency, and the strategic allocation of finite anaerobic energy across a multi-lap buildup and a timed section.

Despite the precision required, most athletes and coaches rely on stopwatch splits and intuition to evaluate performance and plan strategy. Key questions go unanswered:

- What CdA (drag area) does my recorded effort imply?
- Am I entering the timed section too fast or too slow?
- Where in the buildup should I stand versus sit?
- How should I distribute my energy budget across segments to minimize my timed section?

### 1.2 The Solution

Flying 200 answers these questions by placing a full physics simulation engine behind an intuitive mobile interface. The app ingests real power, cadence, and speed data; maps it onto an accurate 3D track model; runs a forward-integration simulation; and then applies constrained optimization to propose improved pacing strategies.

### 1.3 Target Users

- **Elite track sprint cyclists** preparing for competition at national and international levels
- **Coaches and performance staff** analyzing athlete efforts and planning race tactics
- **Sports scientists** validating aerodynamic measurements and calibrating models
- **Equipment specialists** comparing kit configurations and their impact on timed performance

---

## 2. Data Acquisition

### 2.1 Input Sources

The app supports two data import paths:

1. **Strava OAuth Integration** -- The athlete authenticates via Strava, and the app retrieves activity streams (power, cadence, speed, heart rate, distance) for any recorded ride with a power meter. Activities are filtered to show only rides with device-measured power.

2. **FIT File Upload** -- Athletes or coaches upload a .FIT file directly from a head unit (Garmin, Wahoo, Notio, etc.). The server parses the binary FIT format and returns second-by-second records along with metadata including environmental conditions (temperature, humidity) when available.

### 2.2 Effort Detection

Raw activity data typically contains an entire training session. The app automatically identifies sprint efforts within the session using a two-pass detection algorithm:

- **Pass 1 (Ramp Detection):** Scans for sustained high-power, high-speed ramp patterns characteristic of a flying start buildup. Evaluates power acceleration, peak speed, and duration against configurable thresholds.
- **Pass 2 (Fallback Override):** If Pass 1 yields ambiguous results, applies a time-based heuristic (end of activity minus 90 seconds) to capture the most likely effort window.

Detection sensitivity is user-adjustable (Low / Medium / High), and a peak-finder fallback locates all sustained high-power periods regardless of ramp shape. For edge cases, a full-screen manual selection chart allows the athlete to pinpoint the exact effort boundaries by scrubbing through the power trace.

Each detected effort is classified by estimated type (F200, F150, F100, F50) based on duration and distance, with manual override available.

### 2.3 Environmental Conditions

Air density directly affects aerodynamic drag and therefore timed performance. The app calculates air density from temperature, barometric pressure, and relative humidity using the Magnus formula for saturation vapor pressure and the ideal gas law for the dry-air/water-vapor mixture:

```
rho = (p_dry / (R_d * T)) + (p_vapor / (R_v * T))
```

When a FIT file contains embedded environmental metadata, these values auto-populate. Otherwise, the athlete enters conditions manually or overrides the computed density directly.

---

## 3. The Physics Engine

### 3.1 Track Model

The simulation models a standard 250-meter velodrome with accurate 3D geometry:

- **Straights:** 12-degree banking, approximately 45 meters each
- **Bends:** 42-degree banking, approximately 80 meters each (semi-circular)
- **Transitions:** Smooth banking angle interpolation between straights and bends
- **Elevation profile:** Height values (y_m) at every 10-meter increment from 0 to 895 meters, capturing the vertical displacement a rider experiences as they move between the measurement line, the sprinter's lane, and the upper track

The total simulated distance for a Flying 200 is 895 meters: approximately 2.75 laps of buildup (0-695m) followed by the 200-meter timed section (695-895m).

### 3.2 Force Model

At each simulation step, the net force on the rider is computed as:

**Aerodynamic Drag:**
```
F_drag = 0.5 * rho * CdA * v^2
```

Where CdA varies by position (seated vs. standing) and optionally by a bend factor that accounts for increased frontal area in turns.

**Rolling Resistance:**
```
F_roll = Crr * m * g * cos(theta)
```

Where theta is the effective slope derived from the track elevation profile.

**Gravitational Component:**
```
F_gravity = m * g * sin(theta)
```

Calculated from the elevation gradient between consecutive track points.

**Drivetrain Loss:**
Applied as an efficiency factor (typically 96-98%) to the rider's pedal power before it becomes propulsive force at the wheel.

### 3.3 Critical Power and W' Model

The athlete's ability to sustain power above threshold is governed by the Critical Power (CP) model. The anaerobic energy reservoir (W') depletes when power exceeds CP and recovers when power falls below it. This model constrains the total energy available for the sprint and prevents the optimizer from proposing physiologically impossible power profiles.

### 3.4 Integration Method

The simulation uses forward Euler integration at 0.25-0.5 meter spatial steps. At each step:

1. Interpolate power, CdA, and elevation from the input profile
2. Compute net force (propulsive - drag - rolling - gravity)
3. Update velocity: `v_new = sqrt(v^2 + 2 * a * ds)`
4. Update time: `dt = ds / v_avg`
5. Update W' balance
6. Record speed, time, and energy state

The simulation produces a complete distance-velocity-time profile, from which the timed-section time (T_200, T_150, etc.) and 50-meter splits are extracted.

---

## 4. Simulation Workflow

### 4.1 Gearing Configuration

The athlete specifies chainring teeth, cog teeth, and wheel circumference. These values are used to compute rollout distance, which converts cadence data into distance traveled -- critical for accurate effort-to-track mapping.

### 4.2 Kit Configuration

The app supports named kit configurations, each defining a seated CdA and standing CdA. Examples:

| Kit Name       | CdA Seated | CdA Standing |
|----------------|------------|--------------|
| Race Day       | 0.220      | 0.350        |
| Training       | 0.245      | 0.380        |
| Aero Helmet    | 0.215      | 0.340        |

Athletes can create, edit, and switch between configurations. CdA values can be further overridden per-simulation for one-off testing without modifying saved kits.

### 4.3 Position Profile

The buildup is divided into named segments corresponding to track geometry (e.g., "Lap 1 Home Straight 1st Half," "Lap 2 Turn 1"). For each segment, the athlete designates seated or standing position. The timed 200-meter section is locked to seated. This position map determines which CdA value applies at each distance in the simulation.

### 4.4 Breakeven CdA Solver

A key calibration tool. Given a known real-world entry speed and/or timed-section time, the solver iterates to find the CdA value that causes the simulation to reproduce those observed metrics. Two modes are available:

- **Single CdA:** Solves for a uniform CdA across the entire effort (or separately for the buildup and timed phases).
- **Dual CdA:** Simultaneously solves for distinct seated and standing CdA values using both entry speed and timed-section constraints.

This allows athletes to derive their actual aerodynamic properties from recorded performance, rather than relying on wind-tunnel estimates alone.

---

## 5. Optimization

### 5.1 Energy Budget Optimizer

The core optimization algorithm allocates a finite energy budget across track segments to minimize the timed-section time. It operates under the following constraints:

- **Athlete Power Curve:** Maximum sustainable power at each duration (1s through 90s), imported from Strava activity analysis or entered manually. Standing and seated curves are maintained separately, with seated values derived from standing values using a configurable discount factor.
- **Energy Conservation:** Total energy expended across optimized segments must not exceed the specified budget (typically derived from the recorded effort or W').
- **Power Bounds:** Each segment's allocated power must fall within the athlete's physiological capability at the corresponding duration, bounded by a configurable floor (default 80% of baseline) and ceiling (power curve maximum).
- **Position Constraints:** Standing segments use the standing power curve and CdA; seated segments use the seated equivalents.

The algorithm discretizes each segment's feasible power range into configurable energy levels and samples combinations (default: 100-500 samples) to find the allocation that produces the fastest timed section. Results include:

- Baseline vs. optimized timed-section time
- Time saved (in milliseconds)
- Entry and exit speed comparison
- Per-segment energy allocation (joules, percentage)
- Baseline vs. optimized speed and power profile graphs

### 5.2 Power Redistribution Optimizer

An alternative approach that redistributes power across segments while maintaining the same total energy. Rather than allocating from an energy budget, it applies incremental power adjustments (+/- watts) to each segment and evaluates thousands of zero-sum combinations to find improvements. This optimizer requires no athlete power curve -- it works directly from the recorded power data.

### 5.3 Optimization Start Point

Users can select which track segment the optimization begins from, allowing them to hold their actual power profile for early laps and only optimize the final approach into the timed section.

---

## 6. Sensitivity Analysis

The app includes a dedicated sensitivity analysis screen that evaluates how changes in individual parameters (CdA, mass, rolling resistance, air density) affect the timed-section time. This helps athletes and coaches prioritize which variables offer the greatest performance return -- for example, quantifying whether a 0.010 reduction in CdA or a 1 kg reduction in system mass yields a larger time improvement.

---

## 7. Technical Architecture

### 7.1 Mobile Client

- **Framework:** React Native with Expo (SDK 54)
- **Language:** TypeScript
- **State Management:** Zustand with AsyncStorage persistence
- **Navigation:** Expo Router with tab-based layout and hamburger menu for secondary screens
- **Charts:** react-native-chart-kit and react-native-svg for speed profiles, power traces, and bar charts
- **Platforms:** iOS (primary), Android (supported)

### 7.2 Backend Server

- **Runtime:** Node.js with Express
- **Physics Engine:** Python 3.12, invoked via a process bridge from the Node server
- **Libraries:** NumPy (numerical computing), SciPy (optimization), Pandas (data manipulation), fitparse (FIT file parsing)
- **Deployment:** Railway cloud platform with Docker (python-nodejs dual image), auto-deploys from master branch
- **API Surface:** RESTful endpoints for FIT upload, simulation execution, optimization, Strava OAuth, power curve computation, and track geometry

### 7.3 Data Flow

```
Strava / FIT File
       |
       v
  [Connect Data Tab] -- Import activity streams or upload file
       |
       v
  [Efforts Tab] -- Auto-detect sprint efforts, configure gearing & environment
       |
       v
  [Simulation Tab] -- Set physics params, kit, positions, run simulation
       |
       v
  [Optimizer Tab] -- Configure energy budget / redistribution, run optimization
       |
       v
  Results: Time saved, speed/power profiles, segment allocations
```

---

## 8. Validation Approach

The simulation is validated by calibrating against known real-world performances:

1. Record a flying 200 effort with a power meter on a known track
2. Import the data into Flying 200
3. Use the breakeven CdA solver to find the CdA that reproduces the actual timed section and entry speed
4. Compare the derived CdA against independent measurements (wind tunnel, Notio aerometer)
5. With a calibrated CdA, simulation predictions for other efforts on the same track should match observed times within measurement uncertainty

This closed-loop calibration process ensures the physics model is grounded in reality before optimization recommendations are acted upon.

---

## 9. Practical Applications

### 9.1 Race Preparation

An athlete records training efforts on the competition track. Flying 200 analyzes the data, calibrates the model, and proposes an optimized pacing strategy. The coach reviews the recommended segment-by-segment power allocation and position profile, adjusts for tactical considerations, and the athlete implements the strategy in subsequent attempts.

### 9.2 Equipment Testing

By running simulations with different kit configurations and comparing timed-section outputs, athletes can quantify the time impact of equipment choices: disc wheel vs. spoke wheel, speed suit vs. skinsuit, aero helmet vs. standard helmet.

### 9.3 Trackside Analysis

During a track session, between efforts, the athlete or coach opens the app, imports the latest FIT file, runs a quick simulation to assess the effort, and decides whether to adjust gearing, position strategy, or target speed for the next attempt.

### 9.4 Talent Development

Coaches working with developing athletes can use the sensitivity analysis to identify which physiological or equipment improvements would yield the greatest time returns, helping direct training priorities.

---

## 10. Conclusion

Flying 200 bridges the gap between raw ride data and optimized race performance for track cycling sprint events. By embedding a rigorous physics simulation into a mobile interface, it makes the kind of analysis previously confined to sports science labs accessible trackside, in real time, between efforts. The combination of automated effort detection, calibrated aerodynamic modeling, and constrained energy optimization provides athletes and coaches with a quantitative basis for strategic decisions that can shave critical milliseconds from timed results.

---

## References

- Morton, R.H. (2006). The critical power and related whole-body bioenergetic models. *European Journal of Applied Physiology*, 96(4), 339-354.
- Martin, J.C., Milliken, D.L., Cobb, J.E., McFadden, K.L., & Coggan, A.R. (1998). Validation of a mathematical model for road cycling power. *Journal of Applied Biomechanics*, 14(3), 276-291.
- Underwood, L., & Jermy, M. (2010). Mathematical model of track cycling: the individual pursuit. *Procedia Engineering*, 2(2), 3217-3222.
- Fitparse library documentation. https://github.com/dtcooper/python-fitparse

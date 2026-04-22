import axios from 'axios';

// Backend URL. Override via EXPO_PUBLIC_BACKEND_URL env var (see .env.example).
let BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || 'http://localhost:3001/api';

export const setBaseUrl = (url: string) => {
  BASE_URL = url;
  api.defaults.baseURL = url;
};

export const getBaseUrl = () => BASE_URL;

const api = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

// Breakeven CdA result interface (single uniform CdA)
export interface BreakevenCdAResult {
  success: boolean;
  breakeven_cda_entry: number | null;
  breakeven_cda_time: number | null;
  entry_speed_converged: boolean;
  time_converged: boolean;
  entry_speed_iterations?: number;
  entry_speed_achieved_kph?: number;
  time_iterations?: number;
  time_achieved_s?: number;
  error?: string;
}

// Dual breakeven CdA result interface (seated + standing OR buildup + timed)
export interface DualBreakevenCdAResult {
  success: boolean;
  solved_cda_seated: number | null;
  solved_cda_standing: number | null;
  solved_cda_buildup?: number | null;  // Present when mode is "buildup_vs_timed"
  solved_cda_timed?: number | null;    // Present when mode is "buildup_vs_timed"
  mode: 'seated_vs_standing' | 'buildup_vs_timed';
  seated_converged: boolean;
  standing_converged: boolean;
  seated_iterations?: number;
  standing_iterations?: number;
  seated_achieved_s?: number;
  standing_achieved_kph?: number;
  error?: string;
}

// FIT file metadata from parsing
export interface FitMetadata {
  activity_date?: string;
  activity_time?: string;
  device_manufacturer?: string;
  device_product?: string;
  device_serial?: string;
  software_version?: string;
  sport?: string;
  sub_sport?: string;
  total_elapsed_time?: number;
  total_distance?: number;
  avg_heart_rate?: number;
  max_heart_rate?: number;
  avg_cadence?: number;
  max_cadence?: number;
  avg_power?: number;
  max_power?: number;
  normalized_power?: number;
  threshold_power?: number;
  training_stress_score?: number;
  intensity_factor?: number;
  temperature_c?: number;
  humidity_pct?: number;
  sensors?: Array<{ name?: string; type?: string }>;
}

// FIT file upload response
export interface FitUploadResponse {
  success: boolean;
  fileId: string;
  originalName: string;
}

// FIT file data response (uses StravaStreamRecord for compatibility)
export interface FitDataResponse {
  success: boolean;
  records: StravaStreamRecord[];
  summary: {
    total_records: number;
    duration_s: number;
    avg_power: number;
    max_power: number;
    avg_speed: number;
    max_speed: number;
  };
  metadata?: FitMetadata;
  error?: string;
}

// FIT API (file upload + records-based endpoints)
export const fitApi = {
  // Upload a FIT file (native - uses uri)
  upload: async (fileUri: string, fileName: string): Promise<FitUploadResponse> => {
    const formData = new FormData();

    // React Native requires this specific format for file uploads
    formData.append('file', {
      uri: fileUri,
      type: 'application/octet-stream',
      name: fileName,
    } as unknown as Blob);

    const response = await api.post('/fit/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 60000, // 60 seconds for large files
    });
    return response.data;
  },

  // Upload a FIT file (web - uses File object)
  uploadWeb: async (file: File): Promise<FitUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file, file.name);

    const response = await api.post('/fit/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 60000,
    });
    return response.data;
  },

  // Get parsed FIT data for charting
  getData: async (fileId: string): Promise<FitDataResponse> => {
    const response = await api.get(`/fit/${fileId}/data`);
    return response.data;
  },

  // Run simulation from records data (for Strava imports)
  quickSimulationFromRecords: async (
    records: Array<{ elapsed_s: number; power_W: number; speed_kph?: number; cadence_rpm?: number }>,
    endTime: number,
    gearing: { chainring: number; cog: number; wheelCircMm: number },
    parameters?: unknown,
    effortType: 50 | 100 | 150 | 200 = 200,
    segmentPositions?: Record<string, 'seated' | 'standing'>
  ) => {
    const response = await api.post('/fit/quick-simulation-from-records', {
      records,
      endTime,
      chainring: gearing.chainring,
      cog: gearing.cog,
      wheelCircMm: gearing.wheelCircMm,
      parameters,
      effortType,
      segmentPositions,
    });
    return response.data;
  },
};

// Simulation API
export const simulationApi = {
  run: async (profile: unknown, parameters: unknown, powerCurve?: unknown) => {
    const response = await api.post('/simulation/run', { profile, parameters, powerCurve });
    return response.data;
  },
  // Compute breakeven CdA values for entry speed and/or timed section (single uniform CdA)
  computeBreakevenCdA: async (
    powerProfile: Array<{ s_m: number; P_W: number }>,
    parameters: unknown,
    targetEntrySpeedKph?: number,
    targetTimedSectionS?: number,
    effortType: 50 | 100 | 150 | 200 = 200
  ): Promise<BreakevenCdAResult> => {
    const response = await api.post('/simulation/breakeven-cda', {
      powerProfile,
      parameters,
      targetEntrySpeedKph,
      targetTimedSectionS,
      effortType,
    });
    return response.data;
  },
  // Compute BOTH seated and standing CdA values (requires both targets)
  computeDualBreakevenCdA: async (
    powerProfile: Array<{ s_m: number; P_W: number }>,
    parameters: unknown,
    targetEntrySpeedKph: number,
    targetTimedSectionS: number,
    segmentPositions: Record<string, 'seated' | 'standing'>,
    effortType: 50 | 100 | 150 | 200 = 200
  ): Promise<DualBreakevenCdAResult> => {
    const response = await api.post('/simulation/dual-breakeven-cda', {
      powerProfile,
      parameters,
      targetEntrySpeedKph,
      targetTimedSectionS,
      segmentPositions,
      effortType,
    });
    return response.data;
  },
};

// Strava API
export interface StravaAthlete {
  id: number;
  firstname: string;
  lastname: string;
}

export interface StravaActivity {
  id: number;
  name: string;
  type: string;
  sport_type: string;
  start_date: string;
  start_date_local: string;
  distance: number;
  moving_time: number;
  elapsed_time: number;
  average_speed: number;
  max_speed: number;
  average_watts?: number;
  max_watts?: number;
  weighted_average_watts?: number;
  device_watts?: boolean;
  average_cadence?: number;
}

export interface StravaStatus {
  connected: boolean;
  athlete: StravaAthlete | null;
}

export interface StravaStreamRecord {
  elapsed_s: number;
  power_W: number;
  cadence_rpm: number;
  speed_kph: number;
  distance_m: number;
  heartrate?: number;
}

export const stravaApi = {
  // Check if connected to Strava (uses session ID)
  getStatus: async (sessionId?: string): Promise<StravaStatus> => {
    const response = await api.get('/strava/status', {
      params: sessionId ? { sessionId } : undefined,
    });
    return response.data;
  },

  // Get OAuth URL to redirect user to Strava
  getAuthUrl: async (mobile = false, sessionId?: string): Promise<string> => {
    const response = await api.get('/strava/auth-url', {
      params: { mobile, sessionId },
    });
    return response.data.authUrl;
  },

  // Exchange OAuth code for token (called after redirect back)
  exchangeCode: async (code: string, state?: string) => {
    const response = await api.post('/strava/callback', { code, state });
    return response.data;
  },

  // Disconnect from Strava
  disconnect: async (sessionId?: string) => {
    const response = await api.post('/strava/disconnect', { sessionId });
    return response.data;
  },

  // List recent activities (after/before are epoch seconds for Strava date filtering)
  getActivities: async (sessionId?: string, page = 1, perPage = 30, after?: number, before?: number): Promise<StravaActivity[]> => {
    const params: Record<string, string | number> = { page, per_page: perPage };
    if (sessionId) params.sessionId = sessionId;
    if (after) params.after = after;
    if (before) params.before = before;

    const response = await api.get('/strava/activities', { params });
    return response.data.activities;
  },

  // Get activity streams (converted to FIT-like format)
  getActivityStreams: async (activityId: number, sessionId?: string): Promise<{
    success: boolean;
    summary: {
      total_records: number;
      duration_s: number;
      avg_power: number;
      max_power: number;
      avg_speed: number;
      max_speed: number;
    };
    metadata?: {
      activity_date?: string;
      activity_time?: string;
      sport?: string;
      avg_power?: number;
      max_power?: number;
    };
    records: StravaStreamRecord[];
    stravaActivityId: number;
    stravaActivityName?: string;
  }> => {
    const response = await api.get(`/strava/activities/${activityId}/streams`, {
      params: sessionId ? { sessionId } : undefined,
    });
    return response.data;
  },

  // Extract power curve (MMP) from activity
  extractPowerCurve: async (
    activityId: number,
    startTime?: number,
    endTime?: number,
    sessionId?: string
  ): Promise<{
    success: boolean;
    power_curve: Array<{ duration_s: number; seated_W: number; standing_W: number }>;
    summary: {
      segment_duration_s: number;
      avg_power_W: number;
      max_power_W: number;
      durations_available: number[];
    };
  }> => {
    const response = await api.post(`/strava/activities/${activityId}/power-curve`, {
      startTime,
      endTime,
      sessionId,
    });
    return response.data;
  },
};

// Health check
export const healthCheck = async () => {
  try {
    const response = await api.get('/health');
    return response.data;
  } catch (error) {
    return { status: 'error', error };
  }
};

// Athlete Power Curve - computed from multiple activities
export type PowerAggregationMethod = 'max' | 'avgOfMax';

export const athletePowerApi = {
  // Compute athlete's power curve from last N activities
  // aggregationMethod:
  //   'max' - Use the maximum power found at each duration across all activities (MMP)
  //   'avgOfMax' - Average the max power at each duration across all activities
  computeFromActivities: async (
    sessionId: string,
    numActivities: number = 10,
    aggregationMethod: PowerAggregationMethod = 'max'
  ): Promise<{
    success: boolean;
    power_curve: Array<{ duration_s: number; power_W: number }>;
    activities_used: number;
    method: PowerAggregationMethod;
    error?: string;
  }> => {
    console.log(`[PowerCurve] Computing from ${numActivities} activities using ${aggregationMethod} method`);

    // Fetch recent activities
    const activities = await stravaApi.getActivities(sessionId, 1, numActivities);

    if (!activities || activities.length === 0) {
      return { success: false, power_curve: [], activities_used: 0, method: aggregationMethod, error: 'No activities found' };
    }

    // Standard durations for power curve
    const durations = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 20, 25, 30, 45, 50, 60, 70, 80, 90];

    // For 'max' method: track best power at each duration
    // For 'avgOfMax' method: track all max powers per activity to average later
    const bestPowers: Record<number, number> = {};
    const allMaxPowers: Record<number, number[]> = {};

    durations.forEach(d => {
      bestPowers[d] = 0;
      allMaxPowers[d] = [];
    });

    let activitiesProcessed = 0;

    // Process each activity
    for (const activity of activities) {
      if (!activity.device_watts) continue; // Skip activities without power data

      try {
        console.log(`[PowerCurve] Processing activity ${activity.id}: ${activity.name}`);
        const streams = await stravaApi.getActivityStreams(activity.id, sessionId);
        if (!streams.success || !streams.records) continue;

        const powers = streams.records.map(r => r.power_W).filter(p => p > 0);
        if (powers.length === 0) continue;

        // Calculate MMP for each duration in this activity
        for (const duration of durations) {
          if (powers.length < duration) continue;

          // Rolling average to find max mean power for this duration
          let maxAvg = 0;
          for (let i = 0; i <= powers.length - duration; i++) {
            const window = powers.slice(i, i + duration);
            const avg = window.reduce((a, b) => a + b, 0) / duration;
            if (avg > maxAvg) maxAvg = avg;
          }

          if (maxAvg > 0) {
            // For 'max' method: keep the highest value
            if (maxAvg > bestPowers[duration]) {
              bestPowers[duration] = Math.round(maxAvg);
            }
            // For 'avgOfMax' method: collect all max values
            allMaxPowers[duration].push(maxAvg);
          }
        }

        activitiesProcessed++;
        console.log(`[PowerCurve] Activity ${activity.id} processed (${activitiesProcessed}/${activities.length})`);
      } catch (err) {
        console.log(`[PowerCurve] Failed to process activity ${activity.id}:`, err);
      }
    }

    // Compute final power curve based on aggregation method
    let finalPowers: Record<number, number>;

    if (aggregationMethod === 'avgOfMax') {
      // Average all the max powers collected from each activity
      finalPowers = {};
      for (const d of durations) {
        const values = allMaxPowers[d];
        if (values.length > 0) {
          const avg = values.reduce((a, b) => a + b, 0) / values.length;
          finalPowers[d] = Math.round(avg);
        } else {
          finalPowers[d] = 0;
        }
      }
      console.log(`[PowerCurve] Averaged max powers from ${activitiesProcessed} activities`);
    } else {
      // Use the max values directly
      finalPowers = bestPowers;
      console.log(`[PowerCurve] Using max powers from ${activitiesProcessed} activities`);
    }

    const powerCurve = durations
      .filter(d => finalPowers[d] > 0)
      .map(d => ({ duration_s: d, power_W: finalPowers[d] }));

    console.log(`[PowerCurve] Final curve has ${powerCurve.length} duration points`);

    return {
      success: powerCurve.length > 0,
      power_curve: powerCurve,
      activities_used: activitiesProcessed,
      method: aggregationMethod,
    };
  },
};

// Optimizer Types
export interface OptimizerSegment {
  start_m: number;
  end_m: number;
  name: string;
  section?: string;  // Track section name (e.g., "HomeStraight", "Turn1")
  energy_pct: number;
  energy_J: number;
  position: 'seated' | 'standing';
  power_W?: number;
}

export interface EnergyBudgetResult {
  success: boolean;
  optimizer_method?: 'legacy' | 'slsqp' | 'greedy';
  optimization?: {
    T_200_discrete: number;
    T_200_smoothed: number;
    smoothing_penalty_ms: number;
    best_allocation: number[];
    best_positions: ('seated' | 'standing')[];
    iterations_used: number;
  };
  comparison?: {
    baseline_T_200: number;
    optimized_T_200: number;
    time_saved_ms: number;
    improvement_pct: number;
    baseline_v_200_entry_kph?: number;
    baseline_v_200_exit_kph?: number;
    optimized_v_200_entry_kph?: number;
    optimized_v_200_exit_kph?: number;
  };
  statistics?: {
    samples_tested: number;
    valid_combinations: number;
    rejected_violations: number;
    was_stopped: boolean;
  };
  profiles?: {
    distance_m: number[];
    baseline_speed_kph: number[];
    optimized_speed_kph: number[];
    baseline_power_W: number[];
    P_discrete: number[];
    P_smooth: number[];
  };
  markers?: {
    timed_start_m: number;
    timed_end_m: number;
    opt_start_m: number;
  };
  segments?: OptimizerSegment[];
  summary_text?: string;
  error?: string;
}

export interface PowerRedistributionResult {
  success: boolean;
  optimization?: {
    T_200: number;
    best_adjustments: number[];
  };
  comparison?: {
    baseline_T_200: number;
    optimized_T_200: number;
    time_saved_ms: number;
    improvement_pct: number;
  };
  statistics?: {
    samples_tested: number;
    valid_solutions: number;
    rejected: number;
    was_stopped: boolean;
  };
  segments?: Array<{
    name: string;
    section?: string;  // Track section name (e.g., "HomeStraight", "Turn1")
    start_m: number;
    end_m: number;
    base_power_W: number;
    adjustment_W: number;
    new_power_W: number;
  }>;
  profiles?: {
    distance_m: number[];
    baseline_speed_kph: number[];
    optimized_speed_kph: number[];
    baseline_power_W: number[];
    optimized_power_W: number[];
  };
  error?: string;
}

// Optimizer API
export const optimizerApi = {
  // Run Energy Budget Optimizer (uses athlete power curve)
  runEnergyBudget: async (
    powerCurves: {
      durations: number[];
      seated: number[];
      standing: number[];
    },
    profile: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }>,
    riderParams: {
      mass_kg: number;
      rho: number;
      crr: number;
      cda_seated: number;
      cda_standing: number;
      cp_W?: number;
      wPrime_J?: number;
    },
    config?: {
      opt_start_m?: number;
      timed_start_m?: number;
      segment_length_m?: number;
      energy_budget_J?: number;
      n_samples?: number;
      min_power_pct?: number;  // Minimum power as fraction of baseline (0.3 = 30%)
      constraint_buffer_pct?: number;  // Buffer to relax constraints (0.02 = 2%)
      energy_levels?: number;  // Number of discrete energy levels per segment (default 10)
      optimizer_method?: 'legacy' | 'slsqp' | 'greedy';  // Optimization method: random search or gradient-based SLSQP
      gravity_aware_position?: boolean;  // Use gravity-aware position decision (Step 2 improvement)
    },
    baselineT200?: number,
    effortType?: 50 | 100 | 150 | 200,
    signal?: AbortSignal
  ): Promise<EnergyBudgetResult> => {
    console.log('[Optimizer] =====================================');
    console.log('[Optimizer] ENERGY BUDGET - Starting...');
    console.log('[Optimizer] Durations:', powerCurves.durations.length, 'points');
    console.log('[Optimizer] Standing power (first 5):', powerCurves.standing.slice(0, 5));
    console.log('[Optimizer] Seated power (first 5):', powerCurves.seated.slice(0, 5));
    console.log('[Optimizer] Durations (first 10):', powerCurves.durations.slice(0, 10));
    console.log('[Optimizer] Profile:', profile.length, 'points');
    console.log('[Optimizer] Profile power range:', Math.min(...profile.map(p => p.P_W)), '-', Math.max(...profile.map(p => p.P_W)), 'W');
    console.log('[Optimizer] Rider:', riderParams.mass_kg, 'kg, CdA:', riderParams.cda_seated, '/', riderParams.cda_standing);
    console.log('[Optimizer] Samples:', config?.n_samples ?? 500, ', Budget:', config?.energy_budget_J ?? 25000, 'J');
    console.log('[Optimizer] Min Power %:', ((config?.min_power_pct ?? 0.8) * 100).toFixed(0), '%');
    console.log('[Optimizer] Opt Start:', config?.opt_start_m ?? 480, 'm');
    console.log('[Optimizer] Baseline T_200:', baselineT200 ?? 'none');
    console.log('[Optimizer] Method:', config?.optimizer_method ?? 'legacy');
    console.log('[Optimizer] Gravity-aware position:', config?.gravity_aware_position ?? false);
    console.log('[Optimizer] -------------------------------------');
    console.log('[Optimizer] Sending POST to /optimizer/energy-budget...');

    const startTime = Date.now();

    // Heartbeat every 3 seconds
    const heartbeat = setInterval(() => {
      console.log(`[Optimizer] ...waiting for server (${Math.round((Date.now() - startTime) / 1000)}s)`);
    }, 3000);

    try {
      const response = await api.post('/optimizer/energy-budget', {
        power_curves: powerCurves,
        profile,
        rider_params: {
          mass: riderParams.mass_kg,
          rho: riderParams.rho,
          crr: riderParams.crr,
          cda_seated: riderParams.cda_seated,
          cda_standing: riderParams.cda_standing,
          cda_bend_factor: (riderParams as { cda_bend_factor?: number }).cda_bend_factor ?? 1.0,
          v0: (riderParams as { v0_mps?: number }).v0_mps ?? 5.0,
          drivetrain_eff: (riderParams as { drivetrain_eff?: number }).drivetrain_eff ?? 0.98,
          cp: riderParams.cp_W,
          w_prime: riderParams.wPrime_J,
        },
        config: {
          opt_start_m: config?.opt_start_m ?? 480,
          timed_start_m: config?.timed_start_m ?? 695,
          segment_length_m: config?.segment_length_m ?? 50,
          energy_budget_J: config?.energy_budget_J ?? 25000,
          energy_levels: config?.energy_levels ?? 10,
          min_power_pct: config?.min_power_pct ?? 0.8,
          constraint_buffer_pct: config?.constraint_buffer_pct ?? 0.02,
          s_total: 895,
        },
        options: {
          n_samples: config?.n_samples ?? 500,
          baseline_T_200: baselineT200,
          effort_type: effortType ?? 200,
          optimizer_method: config?.optimizer_method ?? 'legacy',
          gravity_aware_position: config?.gravity_aware_position ?? false,
        },
      }, { timeout: 300000, signal });

      clearInterval(heartbeat);
      const elapsed = Date.now() - startTime;
      console.log('[Optimizer] -------------------------------------');
      console.log('[Optimizer] RESPONSE after', elapsed, 'ms');
      console.log('[Optimizer] Method:', config?.optimizer_method ?? 'legacy');
      console.log('[Optimizer] Success:', response.data.success);
      if (response.data.success) {
        console.log('[Optimizer] T_200:', response.data.optimization?.T_200_smoothed?.toFixed(3), 's');
        console.log('[Optimizer] Saved:', response.data.comparison?.time_saved_ms, 'ms');
        console.log('[Optimizer] Tested:', response.data.statistics?.samples_tested, 'samples');
      } else {
        console.log('[Optimizer] ERROR:', response.data.error);
        // Log detailed diagnostics if available
        if (response.data.diagnostics) {
          const diag = response.data.diagnostics;
          console.log('[Optimizer] DIAGNOSTICS:');
          console.log('[Optimizer]   Samples tested:', diag.samples_tested);
          console.log('[Optimizer]   Valid:', diag.valid_samples);
          console.log('[Optimizer]   Rejected:', diag.rejected_samples);
          console.log('[Optimizer]   Power curve ceilings:', JSON.stringify(diag.power_curve_ceilings));
          console.log('[Optimizer]   Baseline powers at key points:', JSON.stringify(diag.baseline_powers));
          console.log('[Optimizer]   Segment floor/ceiling analysis:');
          if (diag.segments) {
            diag.segments.forEach((seg: {
              segment: string;
              elapsed_s: number;
              baseline_power_W: number;
              floor_W: number;
              ceiling_seated_W: number;
              headroom_W: number;
              floor_exceeds_ceiling: boolean;
            }) => {
              const issue = seg.floor_exceeds_ceiling ? ' *** FLOOR > CEILING ***' : '';
              console.log(`[Optimizer]     ${seg.segment}: baseline=${seg.baseline_power_W}W, floor=${seg.floor_W}W, ceiling=${seg.ceiling_seated_W}W, headroom=${seg.headroom_W}W${issue}`);
            });
          }
        }
      }
      console.log('[Optimizer] =====================================');
      return response.data;
    } catch (err: unknown) {
      clearInterval(heartbeat);
      const elapsed = Date.now() - startTime;
      console.log('[Optimizer] -------------------------------------');
      console.log('[Optimizer] FAILED after', elapsed, 'ms');
      if ((err as { name?: string })?.name === 'CanceledError' || (err as { code?: string })?.code === 'ERR_CANCELED') {
        console.log('[Optimizer] Reason: CANCELLED by user');
        return { success: false, error: 'Optimization cancelled by user' };
      }
      console.log('[Optimizer] Error name:', (err as { name?: string })?.name);
      console.log('[Optimizer] Error code:', (err as { code?: string })?.code);
      console.log('[Optimizer] Error msg:', (err as { message?: string })?.message);
      console.log('[Optimizer] =====================================');
      throw err;
    }
  },

  // Run Greedy Position + Power Optimizer
  // Phase 1: Deterministic position analysis (F_net, T_cutoff)
  // Phase 2: Systematic local search over position + power per segment
  runGreedy: async (
    powerCurves: {
      durations: number[];
      seated: number[];
      standing: number[];
    },
    profile: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }>,
    riderParams: {
      mass_kg: number;
      rho: number;
      crr: number;
      cda_seated: number;
      cda_standing: number;
      cp_W?: number;
      wPrime_J?: number;
    },
    config?: {
      opt_start_m?: number;
      timed_start_m?: number;
      segment_length_m?: number;
      min_power_pct?: number;
    },
    baselineT200?: number,
    effortType?: 50 | 100 | 150 | 200,
    signal?: AbortSignal
  ): Promise<EnergyBudgetResult> => {
    console.log('[Greedy Optimizer] =====================================');
    console.log('[Greedy Optimizer] Starting...');
    console.log('[Greedy Optimizer] Profile:', profile.length, 'points');
    console.log('[Greedy Optimizer] Rider:', riderParams.mass_kg, 'kg, CdA:', riderParams.cda_seated, '/', riderParams.cda_standing);
    console.log('[Greedy Optimizer] Baseline T_200:', baselineT200 ?? 'none');

    const startTime = Date.now();
    const heartbeat = setInterval(() => {
      console.log(`[Greedy Optimizer] ...waiting (${Math.round((Date.now() - startTime) / 1000)}s)`);
    }, 3000);

    try {
      const response = await api.post('/optimizer/greedy', {
        power_curves: powerCurves,
        profile,
        rider_params: {
          mass: riderParams.mass_kg,
          rho: riderParams.rho,
          crr: riderParams.crr,
          cda_seated: riderParams.cda_seated,
          cda_standing: riderParams.cda_standing,
          cda_bend_factor: (riderParams as { cda_bend_factor?: number }).cda_bend_factor ?? 1.0,
          v0: (riderParams as { v0_mps?: number }).v0_mps ?? 5.0,
          drivetrain_eff: (riderParams as { drivetrain_eff?: number }).drivetrain_eff ?? 0.98,
          cp: riderParams.cp_W,
          w_prime: riderParams.wPrime_J,
        },
        config: {
          opt_start_m: config?.opt_start_m ?? 480,
          timed_start_m: config?.timed_start_m ?? 695,
          segment_length_m: config?.segment_length_m ?? 50,
          min_power_pct: config?.min_power_pct ?? 0.8,
          s_total: 895,
        },
        options: {
          baseline_T_200: baselineT200,
          effort_type: effortType ?? 200,
        },
      }, { timeout: 300000, signal });

      clearInterval(heartbeat);
      const elapsed = Date.now() - startTime;
      console.log('[Greedy Optimizer] RESPONSE after', elapsed, 'ms');
      console.log('[Greedy Optimizer] Success:', response.data.success);
      if (response.data.success) {
        console.log('[Greedy Optimizer] T_200:', response.data.optimization?.T_200_smoothed?.toFixed(3), 's');
        console.log('[Greedy Optimizer] Saved:', response.data.comparison?.time_saved_ms, 'ms');
      } else {
        console.log('[Greedy Optimizer] ERROR:', response.data.error);
      }
      console.log('[Greedy Optimizer] =====================================');
      return response.data;
    } catch (err: unknown) {
      clearInterval(heartbeat);
      if ((err as { name?: string })?.name === 'CanceledError' || (err as { code?: string })?.code === 'ERR_CANCELED') {
        return { success: false, error: 'Optimization cancelled by user' };
      }
      throw err;
    }
  },

  // Run Power Redistribution Optimizer (zero-sum power adjustments)
  // Uses actual activity power profile - no power curves needed
  runPositionOptimizer: async (
    _powerCurves: {
      durations: number[];
      seated: number[];
      standing: number[];
    },
    profile: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }>,
    riderParams: {
      mass_kg: number;
      rho: number;
      crr: number;
      cda_seated: number;
      cda_standing: number;
    },
    options?: {
      n_samples?: number;
      opt_start_m?: number;
      segment_length_m?: number;
      max_adjustment_W?: number;
      power_increment_W?: number;
    },
    effortType?: 50 | 100 | 150 | 200,
    signal?: AbortSignal
  ): Promise<PowerRedistributionResult> => {
    console.log('[Optimizer] =====================================');
    console.log('[Optimizer] REDISTRIBUTION - Starting...');
    console.log('[Optimizer] Profile:', profile.length, 'points');
    const powers = profile.map(p => p.P_W).filter(p => p > 0);
    console.log('[Optimizer] Profile power range:', Math.min(...powers), '-', Math.max(...powers), 'W');
    console.log('[Optimizer] Power increment:', options?.power_increment_W ?? 10, 'W, Max adjustment:', options?.max_adjustment_W ?? 100, 'W');
    console.log('[Optimizer] Rider:', riderParams.mass_kg, 'kg, CdA:', riderParams.cda_seated);
    console.log('[Optimizer] -------------------------------------');
    console.log('[Optimizer] Sending POST to /optimizer/redistribution...');

    const startTime = Date.now();

    // Heartbeat every 3 seconds
    const heartbeat = setInterval(() => {
      console.log(`[Optimizer] ...waiting for server (${Math.round((Date.now() - startTime) / 1000)}s)`);
    }, 3000);

    try {
      const response = await api.post('/optimizer/redistribution', {
        profile,
        rider_params: {
          mass: riderParams.mass_kg,
          rho: riderParams.rho,
          crr: riderParams.crr,
          cda_seated: riderParams.cda_seated,
          cda_standing: (riderParams as { cda_standing?: number }).cda_standing,
          cda_bend_factor: (riderParams as { cda_bend_factor?: number }).cda_bend_factor ?? 1.0,
          v0: (riderParams as { v0_mps?: number }).v0_mps ?? 5.0,
          drivetrain_eff: (riderParams as { drivetrain_eff?: number }).drivetrain_eff ?? 0.98,
        },
        config: {
          opt_start_m: options?.opt_start_m ?? 430,
          segment_length_m: options?.segment_length_m ?? 50,
          max_adjustment_W: options?.max_adjustment_W ?? 100,
          power_increment_W: options?.power_increment_W ?? 10,
        },
        options: {
          n_samples: options?.n_samples ?? 500,
          effort_type: effortType ?? 200,
        },
      }, { timeout: 300000, signal });

      clearInterval(heartbeat);
      const elapsed = Date.now() - startTime;
      console.log('[Optimizer] -------------------------------------');
      console.log('[Optimizer] RESPONSE after', elapsed, 'ms');
      console.log('[Optimizer] Success:', response.data.success);
      if (response.data.success) {
        console.log('[Optimizer] T_200:', response.data.optimization?.T_200?.toFixed(3), 's');
        console.log('[Optimizer] Pattern:', response.data.optimization?.pattern_description);
      } else {
        console.log('[Optimizer] ERROR:', response.data.error);
      }
      console.log('[Optimizer] =====================================');
      return response.data;
    } catch (err: unknown) {
      clearInterval(heartbeat);
      const elapsed = Date.now() - startTime;
      console.log('[Optimizer] -------------------------------------');
      console.log('[Optimizer] FAILED after', elapsed, 'ms');
      if ((err as { name?: string })?.name === 'CanceledError' || (err as { code?: string })?.code === 'ERR_CANCELED') {
        console.log('[Optimizer] Reason: CANCELLED by user');
        return { success: false, error: 'Optimization cancelled by user' };
      }
      console.log('[Optimizer] Error name:', (err as { name?: string })?.name);
      console.log('[Optimizer] Error code:', (err as { code?: string })?.code);
      console.log('[Optimizer] Error msg:', (err as { message?: string })?.message);
      console.log('[Optimizer] =====================================');
      throw err;
    }
  },
};

export default api;

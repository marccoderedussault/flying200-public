/**
 * Optimizer API Routes
 * Handles position optimization for Flying 200m sprints
 */

import { Router, Request, Response } from 'express';
import { runPythonScript, runPythonScriptStreaming } from '../services/pythonBridge.js';

const router = Router();

// Note: Profile must be provided by the client from FIT analysis
// The optimizer requires a wind-up profile with power data from the user's actual effort

// Optimizer result interface
interface OptimizerResult {
  success: boolean;
  optimization?: {
    T_200: number;
    T_sprint: number;
    v_200_entry_kph: number;
    v_200_exit_kph: number;
    pattern_description: string;
    splits: Array<{ segment: string; time_s: number; avg_speed_kph: number }>;
    energy: { standing_kJ: number; seated_kJ: number };
  };
  comparison?: {
    baseline_T_200: number;
    optimized_T_200: number;
    time_saved_s: number;
    improvement_pct: number;
  };
  profiles?: {
    distance_m: number[];
    speed_kph: number[];
    power_W: number[];
    cda_m2: number[];
    is_standing: boolean[];
  };
  position_timeline?: Array<{
    position: 'standing' | 'seated';
    start_s: number;
    end_s: number;
    duration_s: number;
  }>;
  metadata?: {
    patterns_tested: number;
    elapsed_s: number;
  };
  error?: string;
}

/**
 * POST /api/optimizer/run
 * Run position optimization
 *
 * Request body:
 * {
 *   power_curves: {
 *     seated: [{duration_s: 1, power_W: 1000}, ...] or [1000, 950, 900, ...],
 *     standing: [{duration_s: 1, power_W: 1400}, ...] or [1400, 1350, 1300, ...]
 *   },
 *   profile: [{s_m, y_m, CdA_m2, P_W}, ...],  // REQUIRED - from FIT analysis
 *   rider_params?: {
 *     mass: 92,
 *     rho: 1.18,
 *     crr: 0.002,
 *     cda_seated: 0.24,
 *     cda_standing: 0.38
 *   },
 *   config?: {
 *     sprint_start: 460,
 *     s_total: 895,
 *     min_hold_s: 3,
 *     seated_zone: 230
 *   },
 *   options?: {
 *     use_smart_patterns: true,
 *     sprint_duration: 30,
 *     compare_baseline: true
 *   }
 * }
 */
router.post('/run', async (req: Request, res: Response) => {
  const { power_curves, profile, rider_params, config, options } = req.body;

  // Validate power curves
  if (!power_curves?.seated || !power_curves?.standing) {
    return res.status(400).json({
      success: false,
      error: 'Missing power curves. Both seated and standing curves are required.',
    });
  }

  // Extract durations (if provided)
  const durationsArray: number[] = power_curves.durations || [];

  // Normalize power curves to array format if needed
  const normalizeToArray = (curve: unknown[]): number[] => {
    if (!curve || curve.length === 0) return [];
    if (typeof curve[0] === 'object' && 'duration_s' in (curve[0] as Record<string, unknown>)) {
      // Already in {duration_s, power_W} format - convert to flat array
      return (curve as Array<{ duration_s: number; power_W?: number; seated_W?: number; standing_W?: number }>)
        .sort((a, b) => a.duration_s - b.duration_s)
        .map((p) => p.power_W ?? p.seated_W ?? p.standing_W ?? 0);
    }
    return curve as number[]; // Already flat array
  };

  const seatedArray = normalizeToArray(power_curves.seated);
  const standingArray = normalizeToArray(power_curves.standing);

  if (seatedArray.length === 0 || standingArray.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Power curves must have at least one data point each.',
    });
  }

  // Validate profile - REQUIRED from FIT analysis
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Missing wind-up profile. Please analyze a FIT file and run simulation first.',
    });
  }

  // Validate profile has power data
  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    return res.status(400).json({
      success: false,
      error: 'Profile has no power data. Please extract power profile from a FIT file.',
    });
  }

  const profileData = profile;

  // Determine action
  const compareBaseline = options?.compare_baseline ?? true;
  const action = compareBaseline ? 'compare' : 'optimize';

  // Build input for Python optimizer
  // IMPORTANT: Pass through explicit durations to Python
  const optimizerInput = {
    action,
    power_curves: {
      durations: durationsArray.length > 0 ? durationsArray : undefined,
      seated: seatedArray,
      standing: standingArray,
    },
    profile: profileData,
    rider_params: rider_params || {},
    config: config || {},
    options: {
      use_smart_patterns: options?.use_smart_patterns ?? true,
      sprint_duration: options?.sprint_duration ?? 30,
      sample_size: options?.sample_size,
    },
  };

  const result = await runPythonScript<OptimizerResult>('run_optimizer.py', optimizerInput);

  if (!result.success) {
    return res.status(500).json({
      success: false,
      error: result.error || 'Optimization failed',
    });
  }

  res.json(result.data);
});

// Note: The /quick endpoint has been removed as it required a profile from FIT analysis
// All optimization requests should use /run with a profile from the user's actual effort

/**
 * POST /api/optimizer/run-stream
 * Run position optimization with Server-Sent Events for progress updates
 */
router.post('/run-stream', async (req: Request, res: Response) => {
  const { power_curves, profile, rider_params, config, options } = req.body;

  // Set up SSE headers
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  // Validate power curves
  if (!power_curves?.seated || !power_curves?.standing) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Missing power curves' })}\n\n`);
    res.end();
    return;
  }

  // Extract durations (if provided)
  const durationsArray: number[] = power_curves.durations || [];

  // Normalize power curves
  const normalizeToArray = (curve: unknown[]): number[] => {
    if (!curve || curve.length === 0) return [];
    if (typeof curve[0] === 'object' && 'duration_s' in (curve[0] as Record<string, unknown>)) {
      return (curve as Array<{ duration_s: number; power_W?: number; seated_W?: number; standing_W?: number }>)
        .sort((a, b) => a.duration_s - b.duration_s)
        .map((p) => p.power_W ?? p.seated_W ?? p.standing_W ?? 0);
    }
    return curve as number[];
  };

  const seatedArray = normalizeToArray(power_curves.seated);
  const standingArray = normalizeToArray(power_curves.standing);

  if (seatedArray.length === 0 || standingArray.length === 0) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Power curves must have data' })}\n\n`);
    res.end();
    return;
  }

  // Validate profile
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Missing wind-up profile' })}\n\n`);
    res.end();
    return;
  }

  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Profile has no power data' })}\n\n`);
    res.end();
    return;
  }

  const compareBaseline = options?.compare_baseline ?? true;
  const action = compareBaseline ? 'compare' : 'optimize';

  // IMPORTANT: Pass through explicit durations to Python
  const optimizerInput = {
    action,
    power_curves: {
      durations: durationsArray.length > 0 ? durationsArray : undefined,
      seated: seatedArray,
      standing: standingArray,
    },
    profile: profile,
    rider_params: rider_params || {},
    config: config || {},
    options: {
      use_smart_patterns: options?.use_smart_patterns ?? true,
      sprint_duration: options?.sprint_duration ?? 30,
      sample_size: options?.sample_size,
      stream_progress: true,  // Enable streaming
    },
  };

  // Run with streaming
  const result = await runPythonScriptStreaming<OptimizerResult>(
    'run_optimizer.py',
    optimizerInput,
    (line) => {
      // Send each line as an SSE event
      try {
        const parsed = JSON.parse(line);
        res.write(`data: ${JSON.stringify(parsed)}\n\n`);
      } catch {
        // Not JSON, ignore
      }
    }
  );

  // Send final result
  if (result.success) {
    res.write(`data: ${JSON.stringify({ type: 'complete', ...result.data })}\n\n`);
  } else {
    res.write(`data: ${JSON.stringify({ type: 'error', error: result.error })}\n\n`);
  }

  res.end();
});

// =============================================================================
// Energy Budget Optimizer Routes
// =============================================================================

// Energy Budget Optimizer result interface
interface EnergyBudgetResult {
  success: boolean;
  optimization?: {
    T_200_discrete: number;
    T_200_smoothed: number;
    smoothing_penalty_ms: number;
    best_allocation: number[];
    best_positions: ('standing' | 'seated')[];
    iterations_used: number;
  };
  comparison?: {
    baseline_T_200: number;
    optimized_T_200: number;
    time_saved_ms: number;
    improvement_pct: number;
    baseline_v_200_entry_kph: number;
    baseline_v_200_exit_kph: number;
    optimized_v_200_entry_kph: number;
    optimized_v_200_exit_kph: number;
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
    CdA: number[];
    baseline_CdA: number[];
  };
  segments?: Array<{
    start_m: number;
    end_m: number;
    name: string;
    energy_pct: number;
    energy_J: number;
    position: string;
  }>;
  detail_table?: Array<{
    segment: string;
    section: string;
    v_base_kph: number;
    v_opt_kph: number;
    delta_v_kph: number;
    delta_t_s: number;
    P_base_W: number;
    P_opt_W: number;
    delta_P_W: number;
    position: string;
  }>;
  constraint_diagnostics?: Array<{
    s_m: number;
    elapsed_s: number;
    P_discrete: number;
    P_smooth: number | null;
    floor: number;
    ceiling: number;
    running_avg: number;
    status: string;
  }>;
  config_used?: {
    opt_start_m: number;
    timed_start_m: number;
    segment_length_m: number;
    min_standing_m: number;
    energy_budget_J: number;
    energy_levels: number;
    min_power_pct: number;
    timed_mode: string;
    n_samples: number;
    smoothing_method: string;
  };
  summary_text?: string;
  error?: string;
}

/**
 * POST /api/optimizer/energy-budget
 * Run Energy Budget Optimizer (matching Python GUI EnergyBudgetOptimizer)
 *
 * Request body:
 * {
 *   power_curves: {
 *     seated: [{duration_s: 1, power_W: 1000}, ...] or [1000, 950, 900, ...],
 *     standing: [{duration_s: 1, power_W: 1400}, ...] or [1400, 1350, 1300, ...]
 *   },
 *   profile: [{s_m, y_m, CdA_m2, P_W}, ...],  // REQUIRED - from FIT analysis
 *   rider_params?: {
 *     mass: 92,
 *     rho: 1.18,
 *     crr: 0.002,
 *     cda_seated: 0.24,
 *     cda_standing: 0.38,
 *     cp: 300,
 *     w_prime: 25000,
 *     v0: 1.0
 *   },
 *   config?: {
 *     opt_start_m: 480,
 *     timed_start_m: 695,
 *     segment_length_m: 50,
 *     min_standing_m: 50,
 *     energy_budget_J: 25000,
 *     energy_levels: 10,
 *     min_power_pct: 0.9,
 *     timed_mode: 'FLATOUT' | 'OPT',
 *     s_total: 895,
 *     ds: 0.25
 *   },
 *   options?: {
 *     n_samples: 1000,
 *     smoothing_method: 'cubic' | 'linear' | 'rolling',
 *     max_position_iterations: 3,
 *     stream_progress: false
 *   }
 * }
 */
router.post('/energy-budget', async (req: Request, res: Response) => {
  const { power_curves, profile, rider_params, config, options } = req.body;

  // Validate power curves
  if (!power_curves?.seated || !power_curves?.standing) {
    return res.status(400).json({
      success: false,
      error: 'Missing power curves. Both seated and standing curves are required.',
    });
  }

  // Extract durations (if provided) and power values
  const durationsArray: number[] = power_curves.durations || [];

  // Normalize power curves to array format if needed
  const normalizeToArray = (curve: unknown[]): number[] => {
    if (!curve || curve.length === 0) return [];
    if (typeof curve[0] === 'object' && 'duration_s' in (curve[0] as Record<string, unknown>)) {
      return (curve as Array<{ duration_s: number; power_W?: number; seated_W?: number; standing_W?: number }>)
        .sort((a, b) => a.duration_s - b.duration_s)
        .map((p) => p.power_W ?? p.seated_W ?? p.standing_W ?? 0);
    }
    return curve as number[];
  };

  const seatedArray = normalizeToArray(power_curves.seated);
  const standingArray = normalizeToArray(power_curves.standing);

  if (seatedArray.length === 0 || standingArray.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Power curves must have at least one data point each.',
    });
  }

  // Validate profile
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Missing wind-up profile. Please analyze a FIT file and run simulation first.',
    });
  }

  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    return res.status(400).json({
      success: false,
      error: 'Profile has no power data. Please extract power profile from a FIT file.',
    });
  }

  // Build input for Python energy budget optimizer
  // IMPORTANT: Pass through explicit durations to Python
  const optimizerInput = {
    power_curves: {
      durations: durationsArray.length > 0 ? durationsArray : undefined,
      seated: seatedArray,
      standing: standingArray,
    },
    profile: profile,
    rider_params: rider_params || {},
    config: {
      opt_start_m: config?.opt_start_m ?? 480,
      timed_start_m: config?.timed_start_m ?? 695,
      segment_length_m: config?.segment_length_m ?? 50,
      min_standing_m: config?.min_standing_m ?? 50,
      energy_budget_J: config?.energy_budget_J ?? 25000,
      energy_levels: config?.energy_levels ?? 10,
      min_power_pct: config?.min_power_pct ?? 0.9,
      timed_mode: config?.timed_mode ?? 'FLATOUT',
      s_total: config?.s_total ?? 895,
      ds: config?.ds ?? 0.25,
    },
    options: {
      n_samples: options?.n_samples ?? 1000,
      smoothing_method: options?.smoothing_method ?? 'cubic',
      max_position_iterations: options?.max_position_iterations ?? 3,
      stream_progress: false,
      baseline_T_200: options?.baseline_T_200,  // Pass through simulation baseline
      effort_type: options?.effort_type ?? 200,  // Pass effort type (50, 100, 150, or 200)
      optimizer_method: options?.optimizer_method ?? 'legacy',  // 'legacy' or 'slsqp'
      gravity_aware_position: options?.gravity_aware_position ?? false,  // gravity-aware position decision
    },
  };

  const result = await runPythonScript<EnergyBudgetResult>('run_energy_optimizer.py', optimizerInput);

  if (!result.success) {
    return res.status(500).json({
      success: false,
      error: result.error || 'Energy budget optimization failed',
    });
  }

  res.json(result.data);
});

/**
 * POST /api/optimizer/energy-budget-stream
 * Run Energy Budget Optimizer with Server-Sent Events for progress updates
 */
router.post('/energy-budget-stream', async (req: Request, res: Response) => {
  const { power_curves, profile, rider_params, config, options } = req.body;

  // Set up SSE headers
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  // Validate power curves
  if (!power_curves?.seated || !power_curves?.standing) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Missing power curves' })}\n\n`);
    res.end();
    return;
  }

  // Extract durations (if provided)
  const durationsArray: number[] = power_curves.durations || [];

  // Normalize power curves
  const normalizeToArray = (curve: unknown[]): number[] => {
    if (!curve || curve.length === 0) return [];
    if (typeof curve[0] === 'object' && 'duration_s' in (curve[0] as Record<string, unknown>)) {
      return (curve as Array<{ duration_s: number; power_W?: number; seated_W?: number; standing_W?: number }>)
        .sort((a, b) => a.duration_s - b.duration_s)
        .map((p) => p.power_W ?? p.seated_W ?? p.standing_W ?? 0);
    }
    return curve as number[];
  };

  const seatedArray = normalizeToArray(power_curves.seated);
  const standingArray = normalizeToArray(power_curves.standing);

  if (seatedArray.length === 0 || standingArray.length === 0) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Power curves must have data' })}\n\n`);
    res.end();
    return;
  }

  // Validate profile
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Missing wind-up profile' })}\n\n`);
    res.end();
    return;
  }

  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: 'Profile has no power data' })}\n\n`);
    res.end();
    return;
  }

  // Build input for Python energy budget optimizer
  // IMPORTANT: Pass through explicit durations to Python
  const optimizerInput = {
    power_curves: {
      durations: durationsArray.length > 0 ? durationsArray : undefined,
      seated: seatedArray,
      standing: standingArray,
    },
    profile: profile,
    rider_params: rider_params || {},
    config: {
      opt_start_m: config?.opt_start_m ?? 480,
      timed_start_m: config?.timed_start_m ?? 695,
      segment_length_m: config?.segment_length_m ?? 50,
      min_standing_m: config?.min_standing_m ?? 50,
      energy_budget_J: config?.energy_budget_J ?? 25000,
      energy_levels: config?.energy_levels ?? 10,
      min_power_pct: config?.min_power_pct ?? 0.9,
      timed_mode: config?.timed_mode ?? 'FLATOUT',
      s_total: config?.s_total ?? 895,
      ds: config?.ds ?? 0.25,
    },
    options: {
      n_samples: options?.n_samples ?? 1000,
      smoothing_method: options?.smoothing_method ?? 'cubic',
      max_position_iterations: options?.max_position_iterations ?? 3,
      stream_progress: true,  // Enable streaming
      baseline_T_200: options?.baseline_T_200,  // Pass through simulation baseline
      effort_type: options?.effort_type ?? 200,  // Pass effort type (50, 100, 150, or 200)
      optimizer_method: options?.optimizer_method ?? 'legacy',  // 'legacy' or 'slsqp'
      gravity_aware_position: options?.gravity_aware_position ?? false,  // gravity-aware position decision
    },
  };

  // Run with streaming
  const result = await runPythonScriptStreaming<EnergyBudgetResult>(
    'run_energy_optimizer.py',
    optimizerInput,
    (line) => {
      // Send each line as an SSE event
      try {
        const parsed = JSON.parse(line);
        res.write(`data: ${JSON.stringify(parsed)}\n\n`);
      } catch {
        // Not JSON, ignore
      }
    }
  );

  // Send final result
  if (result.success) {
    res.write(`data: ${JSON.stringify({ type: 'complete', ...result.data })}\n\n`);
  } else {
    res.write(`data: ${JSON.stringify({ type: 'error', error: result.error })}\n\n`);
  }

  res.end();
});

// =============================================================================
// Power Redistribution Optimizer Routes
// =============================================================================

// Power Redistribution result interface
interface PowerRedistributionResult {
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

/**
 * POST /api/optimizer/redistribution
 * Run Power Redistribution Optimizer (zero-sum power adjustments)
 *
 * This optimizer takes the actual activity power profile and redistributes
 * power across segments while maintaining constant total work.
 *
 * Request body:
 * {
 *   profile: [{s_m, y_m, CdA_m2, P_W}, ...],  // REQUIRED - from activity
 *   rider_params?: {
 *     mass: 92,
 *     rho: 1.18,
 *     crr: 0.002,
 *     cda_seated: 0.24,
 *   },
 *   config?: {
 *     opt_start_m: 430,
 *     segment_length_m: 50,
 *     max_adjustment_W: 100,
 *     power_increment_W: 10,
 *     s_total: 895
 *   },
 *   options?: {
 *     n_samples: 500
 *   }
 * }
 */
router.post('/redistribution', async (req: Request, res: Response) => {
  const { profile, rider_params, config, options } = req.body;

  // Validate profile
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Missing profile. Provide activity power profile from FIT analysis.',
    });
  }

  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    return res.status(400).json({
      success: false,
      error: 'Profile has no power data. Extract power profile from a FIT file.',
    });
  }

  // Build input for Python redistribution optimizer
  const optimizerInput = {
    profile: profile,
    rider_params: rider_params || {},
    config: {
      opt_start_m: config?.opt_start_m ?? 430,
      segment_length_m: config?.segment_length_m ?? 50,
      segment_mode: config?.segment_mode ?? 'fixed',
      max_adjustment_W: config?.max_adjustment_W ?? 100,
      power_increment_W: config?.power_increment_W ?? 10,
      s_total: config?.s_total ?? 895,
      ds: config?.ds ?? 0.25,
    },
    options: {
      n_samples: options?.n_samples ?? 500,
      stream_progress: false,
      effort_type: options?.effort_type ?? 200,  // Pass effort type (50, 100, 150, or 200)
    },
  };

  const result = await runPythonScript<PowerRedistributionResult>('run_redistribution_optimizer.py', optimizerInput);

  if (!result.success) {
    return res.status(500).json({
      success: false,
      error: result.error || 'Power redistribution optimization failed',
    });
  }

  res.json(result.data);
});

/**
 * POST /api/optimizer/greedy
 * Greedy Position + Power Optimizer
 * Phase 1: Deterministic position analysis (F_net, T_cutoff)
 * Phase 2: Systematic local search over position + power per segment
 */
router.post('/greedy', async (req: Request, res: Response) => {
  const { power_curves, profile, rider_params, config, options } = req.body;

  // Validate power curves
  if (!power_curves?.seated || !power_curves?.standing) {
    return res.status(400).json({
      success: false,
      error: 'Missing power curves. Both seated and standing curves are required.',
    });
  }

  // Normalize power curves to array format
  const durationsArray: number[] = power_curves.durations || [];
  const normalizeToArray = (curve: unknown[]): number[] => {
    if (!curve || curve.length === 0) return [];
    if (typeof curve[0] === 'object' && 'duration_s' in (curve[0] as Record<string, unknown>)) {
      return (curve as Array<{ duration_s: number; power_W?: number; seated_W?: number; standing_W?: number }>)
        .sort((a, b) => a.duration_s - b.duration_s)
        .map((p) => p.power_W ?? p.seated_W ?? p.standing_W ?? 0);
    }
    return curve as number[];
  };

  const seatedArray = normalizeToArray(power_curves.seated);
  const standingArray = normalizeToArray(power_curves.standing);

  if (seatedArray.length === 0 || standingArray.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Power curves must have at least one data point each.',
    });
  }

  // Validate profile
  if (!profile || !Array.isArray(profile) || profile.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Missing wind-up profile. Please analyze a FIT file and run simulation first.',
    });
  }

  const hasValidPower = profile.some((p: { P_W?: number }) => p.P_W && p.P_W > 0);
  if (!hasValidPower) {
    return res.status(400).json({
      success: false,
      error: 'Profile has no power data. Please extract power profile from a FIT file.',
    });
  }

  const optimizerInput = {
    power_curves: {
      durations: durationsArray.length > 0 ? durationsArray : undefined,
      seated: seatedArray,
      standing: standingArray,
    },
    profile: profile,
    rider_params: rider_params || {},
    config: {
      opt_start_m: config?.opt_start_m ?? 480,
      timed_start_m: config?.timed_start_m ?? 695,
      segment_length_m: config?.segment_length_m ?? 50,
      min_power_pct: config?.min_power_pct ?? 0.8,
      s_total: config?.s_total ?? 895,
      ds: config?.ds ?? 0.25,
    },
    options: {
      baseline_T_200: options?.baseline_T_200,
      effort_type: options?.effort_type ?? 200,
    },
  };

  const result = await runPythonScript<EnergyBudgetResult>('run_greedy_optimizer.py', optimizerInput);

  if (!result.success) {
    return res.status(500).json({
      success: false,
      error: result.error || 'Greedy optimization failed',
    });
  }

  res.json(result.data);
});

export default router;

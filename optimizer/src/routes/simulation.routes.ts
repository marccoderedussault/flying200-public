import { Router, Request, Response } from 'express';
import { runPythonScript } from '../services/pythonBridge.js';

const router = Router();

// Default track trajectory points (same as fit.routes.ts)
const DEFAULT_TRAJECTORY_POINTS = [
  { s_m: 0, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 10, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 20, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 30, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 40, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 50, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 60, y_m: 2.5, CdA_m2: 0.24 },
  { s_m: 70, y_m: 2.93, CdA_m2: 0.24 },
  { s_m: 80, y_m: 3.36, CdA_m2: 0.24 },
  { s_m: 90, y_m: 3.79, CdA_m2: 0.24 },
  { s_m: 100, y_m: 4.64, CdA_m2: 0.24 },
  { s_m: 110, y_m: 5.92, CdA_m2: 0.24 },
  { s_m: 120, y_m: 7.2, CdA_m2: 0.24 },
  { s_m: 130, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 140, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 150, y_m: 7.25, CdA_m2: 0.24 },
  { s_m: 160, y_m: 6.5, CdA_m2: 0.24 },
  { s_m: 170, y_m: 5.75, CdA_m2: 0.24 },
  { s_m: 180, y_m: 4.75, CdA_m2: 0.24 },
  { s_m: 190, y_m: 5.13, CdA_m2: 0.24 },
  { s_m: 200, y_m: 5.88, CdA_m2: 0.24 },
  { s_m: 210, y_m: 5.39, CdA_m2: 0.24 },
  { s_m: 220, y_m: 5.59, CdA_m2: 0.24 },
  { s_m: 230, y_m: 5.77, CdA_m2: 0.24 },
  { s_m: 240, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 250, y_m: 7.13, CdA_m2: 0.24 },
  { s_m: 260, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 270, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 280, y_m: 7.18, CdA_m2: 0.24 },
  { s_m: 290, y_m: 6.78, CdA_m2: 0.24 },
  { s_m: 300, y_m: 7.02, CdA_m2: 0.24 },
  { s_m: 310, y_m: 6.70, CdA_m2: 0.24 },
  { s_m: 320, y_m: 6.71, CdA_m2: 0.24 },
  { s_m: 330, y_m: 6.95, CdA_m2: 0.24 },
  { s_m: 340, y_m: 6.78, CdA_m2: 0.24 },
  { s_m: 350, y_m: 6.50, CdA_m2: 0.24 },
  { s_m: 360, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 370, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 380, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 390, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 400, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 410, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 420, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 430, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 440, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 450, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 460, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 470, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 480, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 490, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 500, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 510, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 520, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 530, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 540, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 550, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 560, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 570, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 580, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 590, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 600, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 610, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 620, y_m: 7.5, CdA_m2: 0.24 },
  { s_m: 630, y_m: 7.0, CdA_m2: 0.24 },
  { s_m: 640, y_m: 6.5, CdA_m2: 0.24 },
  { s_m: 650, y_m: 6.0, CdA_m2: 0.24 },
  { s_m: 660, y_m: 5.5, CdA_m2: 0.24 },
  { s_m: 670, y_m: 5.0, CdA_m2: 0.24 },
  { s_m: 680, y_m: 4.02, CdA_m2: 0.24 },
  { s_m: 690, y_m: 1.25, CdA_m2: 0.245 },
  { s_m: 695, y_m: 0.25, CdA_m2: 0.245 },  // 200m Start
  { s_m: 700, y_m: 0.15, CdA_m2: 0.245 },
  { s_m: 710, y_m: 0.2, CdA_m2: 0.245 },
  { s_m: 720, y_m: 0.7, CdA_m2: 0.245 },
  { s_m: 730, y_m: 0.0, CdA_m2: 0.245 },
  { s_m: 740, y_m: -0.3, CdA_m2: 0.245 },
  { s_m: 750, y_m: 0.05, CdA_m2: 0.245 },
  { s_m: 760, y_m: 0.0, CdA_m2: 0.245 },
  { s_m: 770, y_m: 0.2, CdA_m2: 0.245 },
  { s_m: 780, y_m: 0.15, CdA_m2: 0.245 },
  { s_m: 790, y_m: 0.6, CdA_m2: 0.245 },
  { s_m: 800, y_m: 0.6, CdA_m2: 0.245 },
  { s_m: 810, y_m: 0.2, CdA_m2: 0.245 },
  { s_m: 820, y_m: 0.5, CdA_m2: 0.245 },
  { s_m: 830, y_m: 0.7, CdA_m2: 0.245 },
  { s_m: 840, y_m: -0.1, CdA_m2: 0.245 },
  { s_m: 850, y_m: -0.1, CdA_m2: 0.245 },
  { s_m: 860, y_m: -0.1, CdA_m2: 0.245 },
  { s_m: 870, y_m: -0.1, CdA_m2: 0.245 },
  { s_m: 880, y_m: 0.0, CdA_m2: 0.245 },
  { s_m: 890, y_m: 0.0, CdA_m2: 0.245 },
  { s_m: 895, y_m: 0.0, CdA_m2: 0.245 },  // Finish
];

// POST /api/simulation/run - Run base vs modified simulation
router.post('/run', async (req: Request, res: Response) => {
  const { profile, parameters, powerCurve } = req.body;

  if (!profile || !parameters) {
    return res.status(400).json({ error: 'Profile and parameters are required' });
  }

  const result = await runPythonScript('run_simulation.py', {
    profile,
    parameters,
    power_curve: powerCurve,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// Breakeven CdA result interface
interface BreakevenCdAResult {
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

// POST /api/simulation/breakeven-cda - Compute breakeven CdA values
router.post('/breakeven-cda', async (req: Request, res: Response) => {
  const { powerProfile, parameters, targetEntrySpeedKph, targetTimedSectionS, effortType } = req.body;

  if (!powerProfile || !parameters) {
    return res.status(400).json({ error: 'Power profile and parameters are required' });
  }

  if (!targetEntrySpeedKph && !targetTimedSectionS) {
    return res.status(400).json({ error: 'At least one target (entry speed or timed section) is required' });
  }

  // Build complete profile by merging power data with default trajectory
  // This ensures the correct y_m (height) values are used for the simulation
  const profileRows = DEFAULT_TRAJECTORY_POINTS.map(traj => {
    // Find closest power value from the provided power profile
    let closestPower = 0;
    let closestDist = Infinity;
    for (const p of powerProfile) {
      const dist = Math.abs(p.s_m - traj.s_m);
      if (dist < closestDist) {
        closestDist = dist;
        closestPower = p.P_W;
      }
    }
    return {
      s_m: traj.s_m,
      y_m: traj.y_m,
      CdA_m2: traj.CdA_m2,
      P_W: closestPower,
    };
  });

  const result = await runPythonScript<BreakevenCdAResult>('run_simulation.py', {
    action: 'breakeven_cda',
    profile: { rows: profileRows },
    parameters,
    target_entry_speed_kph: targetEntrySpeedKph,
    target_timed_section_s: targetTimedSectionS,
    effort_type: effortType || 200,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// Dual breakeven CdA result interface (for seated vs standing)
interface DualBreakevenCdAResult {
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

// POST /api/simulation/dual-breakeven-cda - Compute BOTH seated and standing CdA values
router.post('/dual-breakeven-cda', async (req: Request, res: Response) => {
  const { powerProfile, parameters, targetEntrySpeedKph, targetTimedSectionS, segmentPositions, effortType } = req.body;

  if (!powerProfile || !parameters) {
    return res.status(400).json({ error: 'Power profile and parameters are required' });
  }

  if (!targetEntrySpeedKph || !targetTimedSectionS) {
    return res.status(400).json({ error: 'Dual breakeven requires BOTH entry speed AND timed section targets' });
  }

  // Build complete profile by merging power data with default trajectory
  const profileRows = DEFAULT_TRAJECTORY_POINTS.map(traj => {
    let closestPower = 0;
    let closestDist = Infinity;
    for (const p of powerProfile) {
      const dist = Math.abs(p.s_m - traj.s_m);
      if (dist < closestDist) {
        closestDist = dist;
        closestPower = p.P_W;
      }
    }
    return {
      s_m: traj.s_m,
      y_m: traj.y_m,
      CdA_m2: traj.CdA_m2,
      P_W: closestPower,
    };
  });

  const result = await runPythonScript<DualBreakevenCdAResult>('run_simulation.py', {
    action: 'dual_breakeven_cda',
    profile: { rows: profileRows },
    parameters,
    target_entry_speed_kph: targetEntrySpeedKph,
    target_timed_section_s: targetTimedSectionS,
    segment_positions: segmentPositions || {},
    effort_type: effortType || 200,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

export default router;

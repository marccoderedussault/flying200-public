import { Router, Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import { fileURLToPath } from 'url';
import { v4 as uuidv4 } from 'uuid';
import { runPythonScriptWithFile, runPythonScript } from '../services/pythonBridge.js';

// Types for Python script results
interface PowerByDistanceResult {
  success: boolean;
  power_profile: Array<{ s_m: number; P_W: number }>;
  summary: {
    total_distance_m: number;
    s_range_start: number;
    s_range_end: number;
    grid_points: number;
    avg_power_W: number;
    max_power_W: number;
  };
  error?: string;
}

interface SimulationResult {
  success: boolean;
  base?: {
    T_200: number;
    T_total: number;
    v_200_entry_kph: number;
    v_200_exit_kph: number;
    v_max_kph: number;
    P_avg_sprint: number;
    splits_200: number[];
    speed_profile?: Array<{ s_m: number; v_kph: number; t_s: number }>;
  };
  base_segments?: Array<{
    s_start: number;
    s_end: number;
    v_avg_kph: number;
    p_avg: number;
  }>;
  error?: string;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const router = Router();

// Configure multer for FIT file uploads
const storage = multer.diskStorage({
  destination: path.resolve(__dirname, '../../uploads'),
  filename: (req, file, cb) => {
    const id = uuidv4();
    cb(null, `${id}${path.extname(file.originalname)}`);
  },
});

const upload = multer({
  storage,
  fileFilter: (req, file, cb) => {
    if (file.originalname.toLowerCase().endsWith('.fit')) {
      cb(null, true);
    } else {
      cb(new Error('Only .fit files are allowed'));
    }
  },
  limits: { fileSize: 50 * 1024 * 1024 }, // 50MB max
});

// Store file metadata in memory (for MVP - use database in production)
const uploadedFiles = new Map<string, { path: string; originalName: string; uploadedAt: Date }>();

// POST /api/fit/upload - Upload a FIT file
router.post('/upload', upload.single('file'), (req: Request, res: Response) => {
  if (!req.file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }

  const fileId = path.basename(req.file.filename, path.extname(req.file.filename));
  uploadedFiles.set(fileId, {
    path: req.file.path,
    originalName: req.file.originalname,
    uploadedAt: new Date(),
  });

  res.json({
    success: true,
    fileId,
    originalName: req.file.originalname,
  });
});

// GET /api/fit/:id/data - Get parsed FIT data for charting
router.get('/:id/data', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const result = await runPythonScriptWithFile('analyze_fit.py', fileInfo.path, {
    action: 'parse',
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// POST /api/fit/:id/analyze - Analyze a section of the FIT file
router.post('/:id/analyze', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const { startTime, endTime, gearing } = req.body;

  const result = await runPythonScriptWithFile('analyze_fit.py', fileInfo.path, {
    action: 'analyze',
    start_time: startTime,
    end_time: endTime,
    gearing,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// POST /api/fit/:id/extract-power-curve - Extract power curve from section
router.post('/:id/extract-power-curve', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const { startTime, endTime } = req.body;

  const result = await runPythonScriptWithFile('analyze_fit.py', fileInfo.path, {
    action: 'extract_power_curve',
    start_time: startTime,
    end_time: endTime,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// POST /api/fit/:id/extract-power-by-distance - Extract power profile by distance
router.post('/:id/extract-power-by-distance', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const { startTime, endTime, chainring, cog, wheelCircMm, sTotal } = req.body;

  const result = await runPythonScriptWithFile('analyze_fit.py', fileInfo.path, {
    action: 'extract_power_by_distance',
    start_time: startTime || 0,
    end_time: endTime || 9999,
    chainring: chainring || 55,
    cog: cog || 14,
    wheel_circ_mm: wheelCircMm || 2096,
    s_total: sTotal || 895.0,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// POST /api/fit/:id/generate-power-curve - Generate best power curve (1-60s) from selection
router.post('/:id/generate-power-curve', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const { startTime, endTime } = req.body;

  const result = await runPythonScriptWithFile('analyze_fit.py', fileInfo.path, {
    action: 'generate_power_curve',
    start_time: startTime || 0,
    end_time: endTime || 9999,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// Default track trajectory points for quick simulation (full 10m grid matching client store)
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

// POST /api/fit/:id/quick-simulation - Extract power and run quick simulation for effort preview
router.post('/:id/quick-simulation', async (req: Request, res: Response) => {
  const fileInfo = uploadedFiles.get(req.params.id);
  if (!fileInfo) {
    return res.status(404).json({ error: 'File not found' });
  }

  const { endTime, chainring, cog, wheelCircMm, parameters, effortType = 200 } = req.body;

  // Calculate finish line based on effort type (F200=895m, F150=845m, F100=795m, F50=745m)
  const finishDistance = 695 + effortType;

  // First extract power by distance up to the effort's finish line
  const powerResult = await runPythonScriptWithFile<PowerByDistanceResult>('analyze_fit.py', fileInfo.path, {
    action: 'extract_power_by_distance',
    start_time: 0,
    end_time: endTime || 9999,
    chainring: chainring || 55,
    cog: cog || 14,
    wheel_circ_mm: wheelCircMm || 2096,
    s_total: finishDistance,
  });

  if (!powerResult.success || !powerResult.data?.success) {
    return res.status(500).json({
      error: powerResult.error || powerResult.data?.error || 'Failed to extract power profile'
    });
  }

  const powerProfile = powerResult.data.power_profile;
  const powerSummary = powerResult.data.summary;

  // Build a complete profile by merging power data with default trajectory
  // For shorter efforts, pad the remaining distance (after finish line) with 0W
  const profileRows = DEFAULT_TRAJECTORY_POINTS.map(traj => {
    // For distances beyond the effort's finish line, use 0W (doesn't affect timed section)
    if (traj.s_m > finishDistance) {
      return {
        s_m: traj.s_m,
        y_m: traj.y_m,
        CdA_m2: traj.CdA_m2,
        P_W: 0,
      };
    }

    // Find closest power value from extracted profile
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

  // Run quick simulation with the complete profile
  const simResult = await runPythonScript<SimulationResult>('run_simulation.py', {
    profile: { rows: profileRows },
    parameters: parameters || {},
    quick_mode: true, // Signal for simplified output
  });

  if (!simResult.success || !simResult.data?.success) {
    return res.status(500).json({
      error: simResult.error || simResult.data?.error || 'Simulation failed'
    });
  }

  // Calculate timed effort time based on effort type
  // splits_200 = [0-50, 50-100, 100-150, 150-200] from 695m start
  const splits = simResult.data.base?.splits_200 || [];
  const numSplits = effortType / 50; // F200=4, F150=3, F100=2, F50=1
  const timedEffortTime = splits.slice(0, numSplits).reduce((sum: number, t: number) => sum + t, 0);

  // Get exit speed at the correct finish line for this effort type
  // Speed profile has points at various distances, find closest to finish line
  const speedProfile = simResult.data.base?.speed_profile || [];
  let exitSpeed = simResult.data.base?.v_200_exit_kph || 0; // Default to full 200m exit
  if (speedProfile.length > 0) {
    // Find speed at the effort's finish line
    let closestPoint = speedProfile[0];
    let closestDiff = Math.abs(closestPoint.s_m - finishDistance);
    for (const p of speedProfile) {
      const diff = Math.abs(p.s_m - finishDistance);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestPoint = p;
      }
    }
    exitSpeed = closestPoint.v_kph;
  }

  // Calculate max speed only within the timed zone (695m to finishDistance)
  let maxSpeedInZone = 0;
  for (const p of speedProfile) {
    if (p.s_m >= 695 && p.s_m <= finishDistance) {
      maxSpeedInZone = Math.max(maxSpeedInZone, p.v_kph);
    }
  }
  if (maxSpeedInZone === 0) {
    maxSpeedInZone = simResult.data.base?.v_max_kph || 0;
  }

  // Calculate average sprint power only within the timed zone using segments
  const segments = simResult.data.base_segments || [];
  let totalPower = 0;
  let powerCount = 0;
  for (const seg of segments) {
    // Check if segment is within timed zone (695m to finishDistance)
    if (seg.s_start >= 695 && seg.s_end <= finishDistance) {
      totalPower += seg.p_avg;
      powerCount++;
    }
  }
  const avgSprintPower = powerCount > 0 ? totalPower / powerCount : (simResult.data.base?.P_avg_sprint || 0);

  // Return combined result with power summary and simulation stats
  res.json({
    success: true,
    power_summary: powerSummary,
    power_profile: powerProfile,
    effort_type: effortType,
    simulation: {
      T_200: timedEffortTime, // This is now the time for the actual effort type
      T_total: simResult.data.base?.T_total || 0,
      v_200_entry_kph: simResult.data.base?.v_200_entry_kph || 0,
      v_200_exit_kph: exitSpeed, // Speed at actual finish line
      v_max_kph: maxSpeedInZone, // Max speed within timed zone
      P_avg_sprint: avgSprintPower, // Avg power within timed zone
      splits_200: splits, // All 4 splits still available for display
    },
    segments: simResult.data.base_segments || [],
  });
});

// Track segment definitions (same as mobile app store)
// Each segment has: id, startM, endM
const TRACK_SEGMENTS = [
  { id: 'lap0_back_2', startM: 0, endM: 24 },
  { id: 'lap0_turn3', startM: 25, endM: 59 },
  { id: 'lap0_turn4', startM: 60, endM: 94 },
  { id: 'lap0_home_1', startM: 95, endM: 124 },
  { id: 'lap1_home_2', startM: 125, endM: 154 },
  { id: 'lap1_turn1', startM: 155, endM: 189 },
  { id: 'lap1_turn2', startM: 190, endM: 224 },
  { id: 'lap1_back_1', startM: 225, endM: 254 },
  { id: 'lap1_back_2', startM: 255, endM: 284 },
  { id: 'lap1_turn3', startM: 285, endM: 319 },
  { id: 'lap1_turn4', startM: 320, endM: 354 },
  { id: 'lap2_home_1', startM: 355, endM: 384 },
  { id: 'lap2_home_2', startM: 385, endM: 414 },
  { id: 'lap2_turn1', startM: 415, endM: 449 },
  { id: 'lap2_turn2', startM: 450, endM: 484 },
  { id: 'lap2_back_1', startM: 485, endM: 514 },
  { id: 'lap2_back_2', startM: 515, endM: 544 },
  { id: 'lap2_turn3', startM: 545, endM: 579 },
  { id: 'lap2_turn4', startM: 580, endM: 614 },
  { id: 'lap2_home2_1', startM: 615, endM: 644 },
  { id: 'lap2_home2_2', startM: 645, endM: 674 },
  { id: 'lap2_turn1_2', startM: 675, endM: 694 },
  { id: 'lap3_timed', startM: 695, endM: 895, locked: true }, // Timed section always seated
];

// Helper function to get CdA for a given distance based on segment positions
function getCdAForDistance(
  distanceM: number,
  segmentPositions: Record<string, 'seated' | 'standing'> | undefined,
  cdaSeated: number,
  cdaStanding: number
): number {
  // If no segment positions provided, default to seated CdA (user's setting)
  if (!segmentPositions || Object.keys(segmentPositions).length === 0) {
    return cdaSeated;
  }

  // Find which segment this distance falls into
  for (const segment of TRACK_SEGMENTS) {
    if (distanceM >= segment.startM && distanceM <= segment.endM) {
      // Locked segments (timed section) are always seated
      if ((segment as { locked?: boolean }).locked) {
        return cdaSeated;
      }
      const position = segmentPositions[segment.id] || 'seated';
      return position === 'standing' ? cdaStanding : cdaSeated;
    }
  }
  // Default to seated CdA if no segment found
  return cdaSeated;
}

// POST /api/fit/quick-simulation-from-records - Run simulation from provided records (for Strava imports)
router.post('/quick-simulation-from-records', async (req: Request, res: Response) => {
  const { records, endTime, chainring, cog, wheelCircMm, parameters, effortType = 200, segmentPositions } = req.body;

  // Debug logging for CdA and segment positions
  console.log('QuickSim received parameters:', {
    cda_seated: parameters?.cda_seated,
    cda_standing: parameters?.cda_standing,
    rho: parameters?.rho,
  });
  console.log('QuickSim received segmentPositions:', segmentPositions ? Object.keys(segmentPositions).length + ' segments' : 'none');
  // Log any segments that are 'standing'
  if (segmentPositions) {
    const standingSegments = Object.entries(segmentPositions).filter(([, v]) => v === 'standing');
    if (standingSegments.length > 0) {
      console.log('Standing segments:', standingSegments.map(([k]) => k));
    }
  }

  if (!records || !Array.isArray(records) || records.length === 0) {
    return res.status(400).json({ error: 'Records data is required' });
  }

  // Filter records up to endTime
  const filteredRecords = records.filter((r: { elapsed_s: number }) => r.elapsed_s <= endTime);

  if (filteredRecords.length < 10) {
    return res.status(400).json({ error: 'Not enough data points' });
  }

  // Calculate finish line based on effort type (F200=895m, F150=845m, F100=795m, F50=745m)
  const finishDistance = 695 + effortType;

  // Extract power by distance from the records
  // Calculate gear ratio and rollout
  const gearRatio = (chainring || 55) / (cog || 14);
  const wheelCircM = (wheelCircMm || 2096) / 1000;
  const rolloutM = gearRatio * wheelCircM;

  // Work backwards from end to calculate distance and power
  const sTotal = 895.0; // Always simulate full track, but only measure to finishDistance

  // Calculate cumulative distance from start (using cadence if available, otherwise speed)
  let cumulativeDistance = 0;
  const recordsWithDistance: Array<{ elapsed_s: number; power_W: number; distance_m: number }> = [];

  for (let i = 0; i < filteredRecords.length; i++) {
    const rec = filteredRecords[i];
    if (i > 0) {
      const prev = filteredRecords[i - 1];
      const dt = rec.elapsed_s - prev.elapsed_s;

      // Prefer cadence-based distance if available
      if (rec.cadence_rpm && rec.cadence_rpm > 0) {
        const rpm = rec.cadence_rpm;
        const distanceThisInterval = (rpm / 60) * dt * rolloutM;
        cumulativeDistance += distanceThisInterval;
      } else if (rec.speed_kph && rec.speed_kph > 0) {
        // Fallback to speed
        const speedMs = rec.speed_kph / 3.6;
        cumulativeDistance += speedMs * dt;
      }
    }
    recordsWithDistance.push({
      elapsed_s: rec.elapsed_s,
      power_W: rec.power_W || 0,
      distance_m: cumulativeDistance,
    });
  }

  // Calculate the distance offset to align finish with the effort's finish line
  const totalDistanceCovered = cumulativeDistance;
  const distanceOffset = finishDistance - totalDistanceCovered;

  // Build power profile on 10m grid from 0 to 895m
  // For distances beyond the effort's finish line, use 0W (doesn't affect timed section)
  const powerProfile: Array<{ s_m: number; P_W: number }> = [];
  for (let s = 0; s <= sTotal; s += 10) {
    // For distances beyond the effort's finish line, use 0W
    if (s > finishDistance) {
      powerProfile.push({ s_m: s, P_W: 0 });
      continue;
    }

    // Find records that fall near this distance
    const targetDist = s - distanceOffset; // Adjust for offset

    // Find closest record
    let closestRecord = recordsWithDistance[0];
    let closestDiff = Math.abs(closestRecord.distance_m - targetDist);

    for (const rec of recordsWithDistance) {
      const diff = Math.abs(rec.distance_m - targetDist);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestRecord = rec;
      }
    }

    powerProfile.push({
      s_m: s,
      P_W: Math.round(closestRecord.power_W),
    });
  }

  // Calculate power summary
  const powers = powerProfile.map(p => p.P_W).filter(p => p > 0);
  const avgPowerW = powers.length > 0 ? Math.round(powers.reduce((a, b) => a + b, 0) / powers.length) : 0;
  const maxPowerW = powers.length > 0 ? Math.max(...powers) : 0;

  const powerSummary = {
    total_distance_m: totalDistanceCovered,
    s_range_start: 0,
    s_range_end: sTotal,
    grid_points: powerProfile.length,
    avg_power_W: avgPowerW,
    max_power_W: maxPowerW,
  };

  // Get CdA values from parameters (with defaults)
  const cdaSeated = parameters?.cda_seated ?? 0.24;
  const cdaStanding = parameters?.cda_standing ?? 0.38;

  console.log('QuickSim using CdA values:', { cdaSeated, cdaStanding });

  // Build profile rows for simulation with segment-specific CdA
  const profileRows = DEFAULT_TRAJECTORY_POINTS.map(traj => {
    // Find closest power point (not exact match - grid may not align perfectly)
    let closestPower = 0;
    let closestDiff = Infinity;
    for (const p of powerProfile) {
      const diff = Math.abs(p.s_m - traj.s_m);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestPower = p.P_W;
      }
    }

    // Use segment positions to determine CdA (seated vs standing)
    const segmentCdA = getCdAForDistance(
      traj.s_m,
      segmentPositions,
      cdaSeated,
      cdaStanding
    );
    return {
      s_m: traj.s_m,
      y_m: traj.y_m,
      CdA_m2: segmentCdA,
      P_W: closestPower,
    };
  });

  // Log sample CdA values from the profile
  const cdaSamples = profileRows.filter((_, i) => i % 20 === 0).map(p => ({ s_m: p.s_m, CdA: p.CdA_m2 }));
  console.log('QuickSim profile CdA samples:', cdaSamples);

  // Run simulation
  const simResult = await runPythonScript<SimulationResult>('run_simulation.py', {
    profile: { rows: profileRows },
    parameters: parameters || {},
    quick_mode: true,
  });

  if (!simResult.success || !simResult.data?.success) {
    return res.status(500).json({
      error: simResult.error || simResult.data?.error || 'Simulation failed'
    });
  }

  // Calculate timed effort time based on effort type
  // splits_200 = [0-50, 50-100, 100-150, 150-200] from 695m start
  const splits = simResult.data.base?.splits_200 || [];
  const numSplits = effortType / 50; // F200=4, F150=3, F100=2, F50=1
  const timedEffortTime = splits.slice(0, numSplits).reduce((sum: number, t: number) => sum + t, 0);

  // Get exit speed at the correct finish line for this effort type
  const speedProfile = simResult.data.base?.speed_profile || [];
  let exitSpeed = simResult.data.base?.v_200_exit_kph || 0;
  if (speedProfile.length > 0) {
    let closestPoint = speedProfile[0];
    let closestDiff = Math.abs(closestPoint.s_m - finishDistance);
    for (const p of speedProfile) {
      const diff = Math.abs(p.s_m - finishDistance);
      if (diff < closestDiff) {
        closestDiff = diff;
        closestPoint = p;
      }
    }
    exitSpeed = closestPoint.v_kph;
  }

  // Calculate max speed only within the timed zone
  let maxSpeedInZone = 0;
  for (const p of speedProfile) {
    if (p.s_m >= 695 && p.s_m <= finishDistance) {
      maxSpeedInZone = Math.max(maxSpeedInZone, p.v_kph);
    }
  }
  if (maxSpeedInZone === 0) {
    maxSpeedInZone = simResult.data.base?.v_max_kph || 0;
  }

  // Calculate average sprint power only within the timed zone
  const segments = simResult.data.base_segments || [];
  let totalPower = 0;
  let powerCount = 0;
  for (const seg of segments) {
    if (seg.s_start >= 695 && seg.s_end <= finishDistance) {
      totalPower += seg.p_avg;
      powerCount++;
    }
  }
  const avgSprintPower = powerCount > 0 ? totalPower / powerCount : (simResult.data.base?.P_avg_sprint || 0);

  res.json({
    success: true,
    power_summary: powerSummary,
    power_profile: powerProfile,
    effort_type: effortType,
    simulation: {
      T_200: timedEffortTime,
      T_total: simResult.data.base?.T_total || 0,
      v_200_entry_kph: simResult.data.base?.v_200_entry_kph || 0,
      v_200_exit_kph: exitSpeed,
      v_max_kph: maxSpeedInZone,
      P_avg_sprint: avgSprintPower,
      splits_200: splits,
    },
    segments: simResult.data.base_segments || [],
  });
});

export default router;

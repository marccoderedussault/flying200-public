import { Router, Request, Response } from 'express';
import { runPythonScript } from '../services/pythonBridge.js';

const router = Router();

// GET /api/track/geometry - Get track geometry for rendering
// Query params: track_name (optional) - one of: Bromont, Milton, Konya
router.get('/geometry', async (req: Request, res: Response) => {
  const trackName = (req.query.track_name as string) || 'Bromont';

  const result = await runPythonScript('get_track_geometry.py', {
    action: 'get_geometry',
    track_name: trackName,
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

// GET /api/track/list - List available tracks
router.get('/list', async (req: Request, res: Response) => {
  const result = await runPythonScript('get_track_geometry.py', {
    action: 'list_tracks',
  });

  if (!result.success) {
    return res.status(500).json({ error: result.error });
  }

  res.json(result.data);
});

export default router;

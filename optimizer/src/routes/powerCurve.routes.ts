import { Router, Request, Response } from 'express';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const POWER_CURVES_DIR = path.resolve(__dirname, '../../python');

const router = Router();

// GET /api/power-curve - List available power curves
router.get('/', async (req: Request, res: Response) => {
  try {
    const files = await fs.readdir(POWER_CURVES_DIR);
    const curves = files
      .filter((f) => f.includes('power_curve') && f.endsWith('.csv'))
      .map((f) => f.replace('.csv', ''));
    res.json({ curves });
  } catch (error) {
    res.status(500).json({ error: 'Failed to list power curves' });
  }
});

// GET /api/power-curve/:name - Get power curve data
router.get('/:name', async (req: Request, res: Response) => {
  try {
    const filename = req.params.name.endsWith('.csv')
      ? req.params.name
      : `${req.params.name}.csv`;
    const filePath = path.join(POWER_CURVES_DIR, filename);

    const content = await fs.readFile(filePath, 'utf-8');
    const lines = content.trim().split('\n');
    const headers = lines[0].split(',').map((h) => h.trim());

    const data = lines.slice(1).map((line) => {
      const values = line.split(',');
      return {
        duration_s: parseInt(values[0]?.trim() || '0', 10),
        seated_W: parseInt(values[1]?.trim() || '0', 10),
        standing_W: parseInt(values[2]?.trim() || '0', 10),
      };
    });

    res.json({ name: req.params.name, data });
  } catch (error) {
    res.status(404).json({ error: 'Power curve not found' });
  }
});

// POST /api/power-curve - Save new power curve
router.post('/', async (req: Request, res: Response) => {
  try {
    const { name, data } = req.body;
    const filename = name.endsWith('.csv') ? name : `${name}.csv`;
    const filePath = path.join(POWER_CURVES_DIR, filename);

    // Convert to CSV
    const header = 'duration_s,seated_W,standing_W';
    const rows = data.map(
      (d: { duration_s: number; seated_W: number; standing_W: number }) =>
        `${d.duration_s},${d.seated_W},${d.standing_W}`
    );
    const csvContent = [header, ...rows].join('\n');

    await fs.writeFile(filePath, csvContent, 'utf-8');
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to save power curve' });
  }
});

// PUT /api/power-curve/:name - Update power curve
router.put('/:name', async (req: Request, res: Response) => {
  try {
    const { data } = req.body;
    const filename = req.params.name.endsWith('.csv')
      ? req.params.name
      : `${req.params.name}.csv`;
    const filePath = path.join(POWER_CURVES_DIR, filename);

    const header = 'duration_s,seated_W,standing_W';
    const rows = data.map(
      (d: { duration_s: number; seated_W: number; standing_W: number }) =>
        `${d.duration_s},${d.seated_W},${d.standing_W}`
    );
    const csvContent = [header, ...rows].join('\n');

    await fs.writeFile(filePath, csvContent, 'utf-8');
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to update power curve' });
  }
});

export default router;

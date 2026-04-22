import { Router, Request, Response } from 'express';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROFILES_DIR = path.resolve(__dirname, '../../python');

const router = Router();

// GET /api/profile - List available profiles
router.get('/', async (req: Request, res: Response) => {
  try {
    const files = await fs.readdir(PROFILES_DIR);
    const profiles = files
      .filter((f) => f.startsWith('profile_') && f.endsWith('.csv'))
      .map((f) => f.replace('.csv', ''));
    res.json({ profiles });
  } catch (error) {
    res.status(500).json({ error: 'Failed to list profiles' });
  }
});

// GET /api/profile/:name - Get profile data as JSON
router.get('/:name', async (req: Request, res: Response) => {
  try {
    const filename = req.params.name.endsWith('.csv')
      ? req.params.name
      : `${req.params.name}.csv`;
    const filePath = path.join(PROFILES_DIR, filename);

    const content = await fs.readFile(filePath, 'utf-8');
    const lines = content.trim().split('\n');
    const headers = lines[0].split(',').map((h) => h.trim());

    const rows = lines.slice(1).map((line) => {
      const values = line.split(',');
      const row: Record<string, string | number> = {};
      headers.forEach((header, i) => {
        const value = values[i]?.trim() || '';
        // Try to parse as number, keep as string if not
        const num = parseFloat(value);
        row[header] = isNaN(num) ? value : num;
      });
      return row;
    });

    res.json({ headers, rows });
  } catch (error) {
    res.status(404).json({ error: 'Profile not found' });
  }
});

// PUT /api/profile/:name - Update profile
router.put('/:name', async (req: Request, res: Response) => {
  try {
    const { headers, rows } = req.body;
    const filename = req.params.name.endsWith('.csv')
      ? req.params.name
      : `${req.params.name}.csv`;
    const filePath = path.join(PROFILES_DIR, filename);

    // Convert JSON back to CSV
    const headerLine = headers.join(',');
    const dataLines = rows.map((row: Record<string, unknown>) =>
      headers.map((h: string) => row[h] ?? '').join(',')
    );
    const csvContent = [headerLine, ...dataLines].join('\n');

    await fs.writeFile(filePath, csvContent, 'utf-8');
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to save profile' });
  }
});

export default router;

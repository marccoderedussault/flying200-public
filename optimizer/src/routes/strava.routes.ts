/**
 * Strava API Routes
 * Handles OAuth flow and activity data fetching
 */

import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import * as stravaService from '../services/stravaService.js';

const router = Router();

// Simple session management using cookies
// In production, use a proper session library like express-session
function getSessionId(req: Request, res: Response): string {
  let sessionId = req.cookies?.strava_session;

  if (!sessionId) {
    sessionId = uuidv4();
    res.cookie('strava_session', sessionId, {
      httpOnly: true,
      maxAge: 24 * 60 * 60 * 1000, // 24 hours
      sameSite: 'lax',
    });
  }

  return sessionId;
}

/**
 * GET /api/strava/status
 * Check if user is connected to Strava
 * Query params:
 *   - sessionId: string - optional session ID for mobile (since no cookies)
 */
router.get('/status', (req: Request, res: Response) => {
  // For mobile, use provided sessionId since we can't use cookies
  const sessionId = (req.query.sessionId as string) || getSessionId(req, res);
  const connected = stravaService.isConnected(sessionId);
  const athlete = connected ? stravaService.getAthlete(sessionId) : null;

  res.json({
    connected,
    athlete,
  });
});

/**
 * GET /api/strava/auth-url
 * Get OAuth authorization URL to redirect user to Strava
 * Query params:
 *   - mobile: boolean - if true, use mobile redirect URI
 *   - sessionId: string - optional session ID for mobile (since no cookies)
 */
router.get('/auth-url', (req: Request, res: Response) => {
  try {
    const isMobile = req.query.mobile === 'true';
    // For mobile, use provided sessionId since we can't use cookies
    const sessionId = (req.query.sessionId as string) || getSessionId(req, res);
    const authUrl = stravaService.getAuthUrl(sessionId, isMobile);
    res.json({ success: true, authUrl });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Failed to generate auth URL',
    });
  }
});

/**
 * POST /api/strava/callback
 * Handle OAuth callback - exchange code for token
 */
router.post('/callback', async (req: Request, res: Response) => {
  const { code, state } = req.body;

  if (!code) {
    return res.status(400).json({ success: false, error: 'Missing authorization code' });
  }

  // Use the state as session ID if provided, otherwise get from cookie
  const sessionId = state || getSessionId(req, res);

  try {
    const result = await stravaService.exchangeCodeForToken(code, sessionId);

    if (result.success) {
      // Set the session cookie to match the state
      res.cookie('strava_session', sessionId, {
        httpOnly: true,
        maxAge: 24 * 60 * 60 * 1000,
        sameSite: 'lax',
      });

      res.json({
        success: true,
        athlete: result.athlete,
      });
    } else {
      res.status(400).json({
        success: false,
        error: result.error || 'Authentication failed',
      });
    }
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Authentication failed',
    });
  }
});

/**
 * GET /api/strava/oauth-callback
 * Handle OAuth callback redirect from Strava (for mobile bounce)
 * Strava redirects here, we exchange the code and redirect to mobile app
 */
router.get('/oauth-callback', async (req: Request, res: Response) => {
  const code = req.query.code as string;
  const state = req.query.state as string;
  const error = req.query.error as string;

  // Check if this is a web callback (state contains webOrigin marker)
  const isWeb = state?.startsWith('web_');

  // Build redirect base: for web, send an HTML page that posts back to opener;
  // for mobile, use deep link
  function redirectWithParams(params: URLSearchParams) {
    if (isWeb) {
      // Return an HTML page that sends data back to the opener window and closes itself
      const data = JSON.stringify(Object.fromEntries(params));
      return res.send(`<!DOCTYPE html><html><body><script>
        if (window.opener) {
          window.opener.postMessage(${JSON.stringify(data)}, '*');
        }
        window.close();
      </script><p>Authenticated! You can close this window.</p></body></html>`);
    }
    return res.redirect(`flying200://strava-callback?${params.toString()}`);
  }

  if (error) {
    return redirectWithParams(new URLSearchParams({ error }));
  }

  if (!code) {
    return redirectWithParams(new URLSearchParams({ error: 'missing_code' }));
  }

  try {
    // Exchange code for token
    const result = await stravaService.exchangeCodeForToken(code, state);

    if (result.success && result.athlete) {
      redirectWithParams(new URLSearchParams({
        success: 'true',
        state: state,
        athlete_id: result.athlete.id.toString(),
        athlete_firstname: result.athlete.firstname,
        athlete_lastname: result.athlete.lastname,
      }));
    } else {
      redirectWithParams(new URLSearchParams({ error: result.error || 'auth_failed' }));
    }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'unknown_error';
    redirectWithParams(new URLSearchParams({ error: errorMsg }));
  }
});

/**
 * POST /api/strava/disconnect
 * Disconnect from Strava (clear tokens)
 */
router.post('/disconnect', (req: Request, res: Response) => {
  const sessionId = getSessionId(req, res);
  stravaService.disconnect(sessionId);
  res.json({ success: true });
});

/**
 * GET /api/strava/activities
 * List user's recent activities
 * Query params:
 *   - sessionId: string - optional session ID for mobile
 *   - page: number - page number (default 1)
 *   - per_page: number - items per page (default 30)
 */
router.get('/activities', async (req: Request, res: Response) => {
  const sessionId = (req.query.sessionId as string) || getSessionId(req, res);
  const page = parseInt(req.query.page as string) || 1;
  const perPage = parseInt(req.query.per_page as string) || 30;
  const after = req.query.after ? parseInt(req.query.after as string) : undefined;
  const before = req.query.before ? parseInt(req.query.before as string) : undefined;

  const result = await stravaService.listActivities(sessionId, page, perPage, after, before);

  if (result.success) {
    res.json({
      success: true,
      activities: result.activities,
    });
  } else {
    res.status(401).json({
      success: false,
      error: result.error,
    });
  }
});

/**
 * GET /api/strava/activities/:id
 * Get detailed activity info
 * Query params:
 *   - sessionId: string - optional session ID for mobile
 */
router.get('/activities/:id', async (req: Request, res: Response) => {
  const sessionId = (req.query.sessionId as string) || getSessionId(req, res);
  const activityId = parseInt(req.params.id);

  if (isNaN(activityId)) {
    return res.status(400).json({ success: false, error: 'Invalid activity ID' });
  }

  const result = await stravaService.getActivity(sessionId, activityId);

  if (result.success) {
    res.json({
      success: true,
      activity: result.activity,
    });
  } else {
    res.status(401).json({
      success: false,
      error: result.error,
    });
  }
});

/**
 * GET /api/strava/activities/:id/streams
 * Get activity streams and convert to FIT-like format
 * Query params:
 *   - sessionId: string - optional session ID for mobile
 */
router.get('/activities/:id/streams', async (req: Request, res: Response) => {
  const sessionId = (req.query.sessionId as string) || getSessionId(req, res);
  const activityId = parseInt(req.params.id);

  if (isNaN(activityId)) {
    return res.status(400).json({ success: false, error: 'Invalid activity ID' });
  }

  // Get both activity details and streams
  const [activityResult, streamsResult] = await Promise.all([
    stravaService.getActivity(sessionId, activityId),
    stravaService.getActivityStreams(sessionId, activityId),
  ]);

  if (!streamsResult.success || !streamsResult.streams) {
    return res.status(401).json({
      success: false,
      error: streamsResult.error || 'Failed to fetch streams',
    });
  }

  // Convert streams to FIT-like records
  const records = stravaService.convertStreamsToRecords(streamsResult.streams);
  const summary = stravaService.calculateSummary(records);

  // Build metadata from activity details
  const activity = activityResult.activity;
  const metadata = activity
    ? {
        activity_date: activity.start_date_local?.split('T')[0],
        activity_time: activity.start_date_local?.split('T')[1]?.replace('Z', ''),
        sport: activity.sport_type || activity.type,
        device_manufacturer: 'Strava',
        device_product: 'Import',
        normalized_power: activity.weighted_average_watts,
        avg_power: activity.average_watts,
        max_power: activity.max_watts,
      }
    : undefined;

  res.json({
    success: true,
    summary,
    metadata,
    records,
    stravaActivityId: activityId,
    stravaActivityName: activity?.name,
  });
});

/**
 * POST /api/strava/activities/:id/power-curve
 * Extract power curve (MMP) from Strava activity
 * Returns standing curve (raw MMP) and derived seated curve
 *
 * Seated curve converges to standing at ~40 seconds:
 * - At 1s: seated = standing * 0.71 (1/1.4)
 * - At 40s+: seated = standing (converged)
 *
 * Body params:
 *   - sessionId: string - optional session ID for mobile
 *   - startTime: number - optional start time filter
 *   - endTime: number - optional end time filter
 */
router.post('/activities/:id/power-curve', async (req: Request, res: Response) => {
  const sessionId = (req.body.sessionId as string) || getSessionId(req, res);
  const activityId = parseInt(req.params.id);
  const { startTime, endTime } = req.body;

  if (isNaN(activityId)) {
    return res.status(400).json({ success: false, error: 'Invalid activity ID' });
  }

  // Get activity streams
  const streamsResult = await stravaService.getActivityStreams(sessionId, activityId);

  if (!streamsResult.success || !streamsResult.streams) {
    return res.status(401).json({
      success: false,
      error: streamsResult.error || 'Failed to fetch streams',
    });
  }

  const streams = streamsResult.streams;
  const timeData = streams.time?.data ?? [];
  const wattsData = streams.watts?.data ?? [];

  if (wattsData.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'No power data in activity',
    });
  }

  // Filter to time range if specified
  let powerData = wattsData;
  if (startTime !== undefined || endTime !== undefined) {
    const start = startTime ?? 0;
    const end = endTime ?? Infinity;
    powerData = wattsData.filter((_, i) => {
      const t = timeData[i] ?? i;
      return t >= start && t <= end;
    });
  }

  if (powerData.length === 0) {
    return res.status(400).json({
      success: false,
      error: 'No power data in selected time range',
    });
  }

  // Standard power curve durations for track cycling (1-60s)
  const durations = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 60];
  const powerCurve: Array<{ duration_s: number; seated_W: number; standing_W: number }> = [];

  for (const duration of durations) {
    if (powerData.length >= duration) {
      // Rolling average to find best power for this duration
      let bestPower = 0;
      for (let i = 0; i <= powerData.length - duration; i++) {
        let sum = 0;
        for (let j = 0; j < duration; j++) {
          sum += powerData[i + j] ?? 0;
        }
        const avg = sum / duration;
        if (avg > bestPower) {
          bestPower = avg;
        }
      }

      // Standing = raw MMP (what was actually measured)
      const standingPower = Math.round(bestPower);

      // Seated = standing * factor, converging at 40s
      // Factor: 0.71 at 1s, 1.0 at 40s (linear interpolation)
      const convergenceSeconds = 40;
      const minFactor = 1 / 1.4; // ~0.714
      const factor = duration >= convergenceSeconds
        ? 1.0
        : minFactor + (1.0 - minFactor) * ((duration - 1) / (convergenceSeconds - 1));
      const seatedPower = Math.round(standingPower * factor);

      powerCurve.push({
        duration_s: duration,
        seated_W: seatedPower,
        standing_W: standingPower,
      });
    }
  }

  // Summary stats
  const segmentDuration = powerData.length;
  const avgPower = powerData.reduce((a, b) => a + b, 0) / powerData.length;
  const maxPower = Math.max(...powerData);

  res.json({
    success: true,
    power_curve: powerCurve,
    summary: {
      segment_duration_s: segmentDuration,
      avg_power_W: Math.round(avgPower),
      max_power_W: Math.round(maxPower),
      durations_available: powerCurve.map((p) => p.duration_s),
    },
  });
});

export default router;

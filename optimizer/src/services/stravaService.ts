/**
 * Strava API Service
 * Handles OAuth authentication and API calls to Strava
 * Each user authenticates with their own Strava account
 */

import axios from 'axios';

// Strava API endpoints
const STRAVA_AUTH_URL = 'https://www.strava.com/oauth/authorize';
const STRAVA_TOKEN_URL = 'https://www.strava.com/oauth/token';
const STRAVA_API_BASE = 'https://www.strava.com/api/v3';

// Token storage (in-memory, per-session)
// In production with multiple users, you'd want to store this per user session
interface TokenData {
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // Unix timestamp
  athlete: {
    id: number;
    firstname: string;
    lastname: string;
  };
}

// Simple in-memory token store keyed by a session ID
const tokenStore = new Map<string, TokenData>();

// Get Strava credentials from environment
function getCredentials(isMobile = false) {
  const clientId = process.env.STRAVA_CLIENT_ID;
  const clientSecret = process.env.STRAVA_CLIENT_SECRET;

  // For mobile: redirect to backend's oauth-callback endpoint (which then bounces to mobile app)
  // For web: redirect directly to frontend callback page
  const redirectUri = isMobile
    ? process.env.STRAVA_MOBILE_REDIRECT_URI || 'http://localhost:3001/api/strava/oauth-callback'
    : process.env.STRAVA_REDIRECT_URI || 'http://localhost:5173/strava/callback';

  if (!clientId || !clientSecret) {
    throw new Error('STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set in environment');
  }

  return { clientId, clientSecret, redirectUri };
}

/**
 * Generate OAuth authorization URL for user to authenticate
 */
export function getAuthUrl(sessionId: string, isMobile = false): string {
  const { clientId, redirectUri } = getCredentials(isMobile);

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'activity:read_all', // Read all activities including private ones
    state: sessionId, // Pass session ID to link the callback
  });

  return `${STRAVA_AUTH_URL}?${params.toString()}`;
}

/**
 * Exchange authorization code for access token
 */
export async function exchangeCodeForToken(
  code: string,
  sessionId: string
): Promise<{ success: boolean; athlete?: TokenData['athlete']; error?: string }> {
  const { clientId, clientSecret } = getCredentials();

  try {
    const response = await axios.post(STRAVA_TOKEN_URL, {
      client_id: clientId,
      client_secret: clientSecret,
      code,
      grant_type: 'authorization_code',
    });

    const { access_token, refresh_token, expires_at, athlete } = response.data;

    // Store token data
    tokenStore.set(sessionId, {
      accessToken: access_token,
      refreshToken: refresh_token,
      expiresAt: expires_at,
      athlete: {
        id: athlete.id,
        firstname: athlete.firstname,
        lastname: athlete.lastname,
      },
    });

    return {
      success: true,
      athlete: {
        id: athlete.id,
        firstname: athlete.firstname,
        lastname: athlete.lastname,
      },
    };
  } catch (error) {
    console.error('Strava token exchange failed:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Token exchange failed',
    };
  }
}

/**
 * Refresh access token if expired
 */
async function refreshAccessToken(sessionId: string): Promise<boolean> {
  const tokenData = tokenStore.get(sessionId);
  if (!tokenData) return false;

  const { clientId, clientSecret } = getCredentials();

  try {
    const response = await axios.post(STRAVA_TOKEN_URL, {
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: tokenData.refreshToken,
      grant_type: 'refresh_token',
    });

    const { access_token, refresh_token, expires_at } = response.data;

    tokenStore.set(sessionId, {
      ...tokenData,
      accessToken: access_token,
      refreshToken: refresh_token,
      expiresAt: expires_at,
    });

    return true;
  } catch (error) {
    console.error('Strava token refresh failed:', error);
    tokenStore.delete(sessionId);
    return false;
  }
}

/**
 * Get valid access token, refreshing if necessary
 */
async function getValidToken(sessionId: string): Promise<string | null> {
  const tokenData = tokenStore.get(sessionId);
  if (!tokenData) return null;

  // Check if token is expired (with 60s buffer)
  const now = Math.floor(Date.now() / 1000);
  if (tokenData.expiresAt <= now + 60) {
    const refreshed = await refreshAccessToken(sessionId);
    if (!refreshed) return null;
  }

  return tokenStore.get(sessionId)?.accessToken ?? null;
}

/**
 * Check if session has valid Strava connection
 */
export function isConnected(sessionId: string): boolean {
  return tokenStore.has(sessionId);
}

/**
 * Get connected athlete info
 */
export function getAthlete(sessionId: string): TokenData['athlete'] | null {
  return tokenStore.get(sessionId)?.athlete ?? null;
}

/**
 * Disconnect Strava (clear tokens)
 */
export function disconnect(sessionId: string): void {
  tokenStore.delete(sessionId);
}

// Strava API types
export interface StravaActivity {
  id: number;
  name: string;
  type: string;
  sport_type: string;
  start_date: string;
  start_date_local: string;
  distance: number; // meters
  moving_time: number; // seconds
  elapsed_time: number; // seconds
  total_elevation_gain: number;
  average_speed: number; // m/s
  max_speed: number; // m/s
  average_watts?: number;
  max_watts?: number;
  weighted_average_watts?: number;
  kilojoules?: number;
  device_watts?: boolean;
  has_heartrate?: boolean;
  average_heartrate?: number;
  max_heartrate?: number;
  average_cadence?: number;
}

export interface StravaStreams {
  time?: { data: number[] };
  distance?: { data: number[] };
  watts?: { data: number[] };
  cadence?: { data: number[] };
  velocity_smooth?: { data: number[] };
  heartrate?: { data: number[] };
  altitude?: { data: number[] };
}

/**
 * List recent activities for the authenticated user
 */
export async function listActivities(
  sessionId: string,
  page = 1,
  perPage = 30,
  after?: number,
  before?: number
): Promise<{ success: boolean; activities?: StravaActivity[]; error?: string }> {
  const token = await getValidToken(sessionId);
  if (!token) {
    return { success: false, error: 'Not authenticated with Strava' };
  }

  try {
    const params: Record<string, number> = { page, per_page: perPage };
    if (after) params.after = after;
    if (before) params.before = before;

    const response = await axios.get<StravaActivity[]>(`${STRAVA_API_BASE}/athlete/activities`, {
      headers: { Authorization: `Bearer ${token}` },
      params,
    });

    return { success: true, activities: response.data };
  } catch (error) {
    console.error('Failed to list Strava activities:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch activities',
    };
  }
}

/**
 * Get detailed activity info
 */
export async function getActivity(
  sessionId: string,
  activityId: number
): Promise<{ success: boolean; activity?: StravaActivity; error?: string }> {
  const token = await getValidToken(sessionId);
  if (!token) {
    return { success: false, error: 'Not authenticated with Strava' };
  }

  try {
    const response = await axios.get<StravaActivity>(
      `${STRAVA_API_BASE}/activities/${activityId}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );

    return { success: true, activity: response.data };
  } catch (error) {
    console.error('Failed to get Strava activity:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch activity',
    };
  }
}

/**
 * Get activity streams (power, cadence, speed, time, distance)
 */
export async function getActivityStreams(
  sessionId: string,
  activityId: number
): Promise<{ success: boolean; streams?: StravaStreams; error?: string }> {
  const token = await getValidToken(sessionId);
  if (!token) {
    return { success: false, error: 'Not authenticated with Strava' };
  }

  try {
    // Request all the streams we need
    const keys = ['time', 'distance', 'watts', 'cadence', 'velocity_smooth', 'heartrate', 'altitude'];

    const response = await axios.get(`${STRAVA_API_BASE}/activities/${activityId}/streams`, {
      headers: { Authorization: `Bearer ${token}` },
      params: {
        keys: keys.join(','),
        key_by_type: true,
      },
    });

    return { success: true, streams: response.data };
  } catch (error) {
    console.error('Failed to get Strava streams:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch activity streams',
    };
  }
}

/**
 * Convert Strava streams to FIT-like record format
 * This allows the rest of the app to use the same data structures
 */
export function convertStreamsToRecords(streams: StravaStreams): Array<{
  elapsed_s: number;
  power_W: number;
  cadence_rpm: number;
  speed_kph: number;
  distance_m: number;
  heartrate?: number;
}> {
  const timeData = streams.time?.data ?? [];
  const wattsData = streams.watts?.data ?? [];
  const cadenceData = streams.cadence?.data ?? [];
  const velocityData = streams.velocity_smooth?.data ?? [];
  const distanceData = streams.distance?.data ?? [];
  const heartrateData = streams.heartrate?.data ?? [];

  const records = [];

  for (let i = 0; i < timeData.length; i++) {
    records.push({
      elapsed_s: timeData[i] ?? 0,
      power_W: wattsData[i] ?? 0,
      cadence_rpm: cadenceData[i] ?? 0,
      speed_kph: (velocityData[i] ?? 0) * 3.6, // m/s to km/h
      distance_m: distanceData[i] ?? 0,
      heartrate: heartrateData[i],
    });
  }

  return records;
}

/**
 * Calculate summary stats from records (matches FIT file summary format)
 */
export function calculateSummary(records: ReturnType<typeof convertStreamsToRecords>) {
  if (records.length === 0) {
    return {
      total_records: 0,
      duration_s: 0,
      avg_power: 0,
      max_power: 0,
      avg_speed: 0,
      max_speed: 0,
    };
  }

  const powers = records.map((r) => r.power_W).filter((p) => p > 0);
  const speeds = records.map((r) => r.speed_kph);

  return {
    total_records: records.length,
    duration_s: records[records.length - 1].elapsed_s,
    avg_power: powers.length > 0 ? Math.round(powers.reduce((a, b) => a + b, 0) / powers.length) : 0,
    max_power: powers.length > 0 ? Math.max(...powers) : 0,
    avg_speed: speeds.length > 0 ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0,
    max_speed: speeds.length > 0 ? Math.max(...speeds) : 0,
  };
}

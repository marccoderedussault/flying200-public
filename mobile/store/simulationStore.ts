import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { StravaAthlete, StravaActivity, StravaStreamRecord, FitMetadata } from '../api/client';
import { migrate, STORE_VERSION } from './migrations';

// Track segment definitions
// Each segment has: id, label (display name), startM, endM, and optional locked flag
export interface TrackSegment {
  id: string;
  label: string;
  startM: number;
  endM: number;
  locked?: boolean;  // If true, cannot be changed (always seated for timed section)
}

// All track segments in order (based on profile_f200.csv)
// These define logical sections of the track for position (seated/standing) selection
// Structure follows a typical flying 200 buildup on a 250m track
export const TRACK_SEGMENTS: TrackSegment[] = [
  // Lap 0 - Initial approach (partial lap)
  { id: 'lap0_back_2', label: 'Lap 0 Back Straight (2nd half)', startM: 0, endM: 24 },
  { id: 'lap0_turn3', label: 'Lap 0 Turn 3', startM: 25, endM: 59 },
  { id: 'lap0_turn4', label: 'Lap 0 Turn 4', startM: 60, endM: 94 },
  { id: 'lap0_home_1', label: 'Lap 0 Home Straight (1st half)', startM: 95, endM: 124 },
  // Lap 1 - Full lap
  { id: 'lap1_home_2', label: 'Lap 1 Home Straight (2nd half)', startM: 125, endM: 154 },
  { id: 'lap1_turn1', label: 'Lap 1 Turn 1', startM: 155, endM: 189 },
  { id: 'lap1_turn2', label: 'Lap 1 Turn 2', startM: 190, endM: 224 },
  { id: 'lap1_back_1', label: 'Lap 1 Back Straight (1st half)', startM: 225, endM: 254 },
  { id: 'lap1_back_2', label: 'Lap 1 Back Straight (2nd half)', startM: 255, endM: 284 },
  { id: 'lap1_turn3', label: 'Lap 1 Turn 3', startM: 285, endM: 319 },
  { id: 'lap1_turn4', label: 'Lap 1 Turn 4', startM: 320, endM: 354 },
  // Lap 2 - Extended lap (extra long into start line)
  { id: 'lap2_home_1', label: 'Lap 2 Home Straight (1st half)', startM: 355, endM: 384 },
  { id: 'lap2_home_2', label: 'Lap 2 Home Straight (2nd half)', startM: 385, endM: 414 },
  { id: 'lap2_turn1', label: 'Lap 2 Turn 1', startM: 415, endM: 449 },
  { id: 'lap2_turn2', label: 'Lap 2 Turn 2', startM: 450, endM: 484 },
  { id: 'lap2_back_1', label: 'Lap 2 Back Straight (1st half)', startM: 485, endM: 514 },
  { id: 'lap2_back_2', label: 'Lap 2 Back Straight (2nd half)', startM: 515, endM: 544 },
  { id: 'lap2_turn3', label: 'Lap 2 Turn 3', startM: 545, endM: 579 },
  { id: 'lap2_turn4', label: 'Lap 2 Turn 4', startM: 580, endM: 614 },
  { id: 'lap2_home2_1', label: 'Lap 2+ Home Straight (1st half)', startM: 615, endM: 644 },
  { id: 'lap2_home2_2', label: 'Lap 2+ Home Straight (2nd half)', startM: 645, endM: 674 },
  { id: 'lap2_turn1_2', label: 'Lap 2+ Turn 1 (into start)', startM: 675, endM: 694 },
  // Lap 3 - Timed 200m section (LOCKED as seated)
  { id: 'lap3_timed', label: 'Lap 3 - Timed 200m (Seated)', startM: 695, endM: 895, locked: true },
];

// Segment position type
export type SegmentPosition = 'seated' | 'standing';

// Map of segment ID to position (seated/standing)
export type SegmentPositions = Record<string, SegmentPosition>;

// Kit configuration types
export type FrontWheelType = 'front_disc' | '345_spoke' | 'spokes';
export type RearWheelType = 'rear_disc' | 'spokes';

export interface KitConfig {
  frontWheel: FrontWheelType;
  rearWheel: RearWheelType;
  speedSuit: boolean;    // true = wearing
  aeroHelmet: boolean;   // true = wearing
  shoeCovers: boolean;   // true = wearing
}

// Default race kit configuration (user can customize this as their baseline)
export const DEFAULT_RACE_KIT: KitConfig = {
  frontWheel: '345_spoke',  // Typical race kit default
  rearWheel: 'rear_disc',   // Typical race kit default
  speedSuit: true,          // Race kit = wearing
  aeroHelmet: true,         // Race kit = wearing
  shoeCovers: true,         // Race kit = wearing
};

// Alias for backwards compatibility
export const DEFAULT_KIT_CONFIG = DEFAULT_RACE_KIT;

// Named kit configuration (up to 5 named configs with CdA values)
export interface NamedKitConfig {
  id: string;
  name: string;
  description: string;
  cdaSeated: number;
  cdaStanding: number;
  frontWheel: FrontWheelType;
  rearWheel: RearWheelType;
  speedSuit: boolean;
  aeroHelmet: boolean;
  shoeCovers: boolean;
  isDefault: boolean;
}

export const MAX_KIT_CONFIGS = 5;

export const DEFAULT_KIT_CONFIGS: NamedKitConfig[] = [{
  id: 'race-kit',
  name: 'Race Kit',
  description: 'Default race configuration',
  cdaSeated: 0.24,
  cdaStanding: 0.38,
  frontWheel: '345_spoke',
  rearWheel: 'rear_disc',
  speedSuit: true,
  aeroHelmet: true,
  shoeCovers: true,
  isDefault: true,
}];

// Get the default kit config from a list of configs
export function getDefaultKitConfig(configs: NamedKitConfig[]): NamedKitConfig {
  return configs.find(c => c.isDefault) || configs[0] || DEFAULT_KIT_CONFIGS[0];
}

// Get a kit config by ID
export function getKitConfigById(configs: NamedKitConfig[], id: string): NamedKitConfig | undefined {
  return configs.find(c => c.id === id);
}

// Absolute CDA values for each kit option (in m²)
// These are the CDA contributions, not relative modifiers
export const KIT_CDA_VALUES = {
  frontWheel: {
    'front_disc': 0.0000,   // Best aero (baseline reference)
    '345_spoke': 0.0025,    // +0.0025 vs front disc
    'spokes': 0.0125,       // +0.0125 vs front disc (+0.01 vs 3/4/5)
  },
  rearWheel: {
    'rear_disc': 0.0000,    // Best aero (baseline reference)
    'spokes': 0.01,         // +0.01 vs rear disc
  },
  // Apparel CDA penalty when NOT wearing
  speedSuitOff: 0.005,
  aeroHelmetOff: 0.005,
  shoeCoverOff: 0.005,
};

// Legacy modifiers (relative to typical race kit: 3/4/5 spoke front, disc rear, all apparel on)
export const KIT_CDA_MODIFIERS = {
  frontWheel: {
    'front_disc': -0.0025,  // Better aero than 3/4/5 spoke
    '345_spoke': 0,         // Typical race kit baseline
    'spokes': 0.01,         // Worse aero than 3/4/5 spoke
  },
  rearWheel: {
    'rear_disc': 0,         // Typical race kit baseline
    'spokes': 0.01,         // Worse aero than rear disc
  },
  speedSuit: 0.005,         // Added CDA when NOT wearing
  aeroHelmet: 0.005,        // Added CDA when NOT wearing
  shoeCovers: 0.005,        // Added CDA when NOT wearing
};

// Calculate CDA contribution for a kit configuration (absolute value)
function calculateKitCdaAbsolute(kit: KitConfig): number {
  let cda = 0;

  // Wheel contributions
  cda += KIT_CDA_VALUES.frontWheel[kit.frontWheel];
  cda += KIT_CDA_VALUES.rearWheel[kit.rearWheel];

  // Apparel penalties (only add if NOT wearing)
  if (!kit.speedSuit) cda += KIT_CDA_VALUES.speedSuitOff;
  if (!kit.aeroHelmet) cda += KIT_CDA_VALUES.aeroHelmetOff;
  if (!kit.shoeCovers) cda += KIT_CDA_VALUES.shoeCoverOff;

  return cda;
}

// Calculate CDA modifier relative to race kit (currentKit - raceKit)
export function calculateKitCdaModifier(currentKit: KitConfig, raceKit?: KitConfig): number {
  const baseRaceKit = raceKit || DEFAULT_RACE_KIT;
  const currentCda = calculateKitCdaAbsolute(currentKit);
  const raceKitCda = calculateKitCdaAbsolute(baseRaceKit);
  return currentCda - raceKitCda;
}

// Default all segments to seated
export const DEFAULT_SEGMENT_POSITIONS: SegmentPositions = TRACK_SEGMENTS.reduce(
  (acc, segment) => {
    acc[segment.id] = 'seated';
    return acc;
  },
  {} as SegmentPositions
);

// Simulation Parameters
export interface SimParameters {
  mass_kg: number;
  rho: number;
  crr: number;
  v0_mps: number;
  drivetrain_eff: number;
  cp_W: number;
  wPrime_J: number;
  sprint_delta_W: number;
  cda_standing: number;
  cda_seated: number;
  cda_bend_factor: number;
  s_total_m: number;
  ds_m: number;
  trans_len_m: number;
}

export const DEFAULT_PARAMS: SimParameters = {
  mass_kg: 92.0,
  rho: 1.1627,
  crr: 0.0020,
  v0_mps: 5.0,
  drivetrain_eff: 0.98,
  cp_W: 250.0,
  wPrime_J: 25000.0,
  sprint_delta_W: 250.0,
  cda_standing: 0.38,
  cda_seated: 0.24,
  cda_bend_factor: 1.00,
  s_total_m: 895.0,
  ds_m: 0.25,
  trans_len_m: 40.0,
};

// Gearing config
export interface GearingConfig {
  chainring: number;
  cog: number;
  wheelCircMm: number;
}

export const DEFAULT_GEARING: GearingConfig = {
  chainring: 55,
  cog: 12,
  wheelCircMm: 2096,
};

// Track geometry data
export interface TrackGeometry {
  straight_m: number;       // Straight length (m)
  banking_turn_deg: number; // Turn banking angle (degrees)
  banking_straight_deg: number; // Straight banking angle (degrees)
  width_m: number;          // Track width (m)
  altitude_m: number;       // Altitude (m) for air density
  lap_m: number;            // Lap length (m), always 250 for standard
}

export interface TrackOption {
  id: string;
  name: string;
  description: string;
  geometry: TrackGeometry;
}

// Derive turn radius from straight length for 250m lap
function _trackPreset(
  id: string, name: string, description: string,
  straight: number, bankT: number, bankS: number, width: number, alt: number,
): TrackOption {
  return {
    id, name, description,
    geometry: {
      straight_m: straight,
      banking_turn_deg: bankT,
      banking_straight_deg: bankS,
      width_m: width,
      altitude_m: alt,
      lap_m: 250,
    },
  };
}

// All tracks from track-builder presets
export const TRACK_OPTIONS: TrackOption[] = [
  // ── Canada
  _trackPreset('Bromont', 'Bromont 250m', 'Atlanta 1996 Olympic track, Quebec', 59, 42.0, 12, 7.5, 200),
  _trackPreset('Milton', 'Milton 250m', 'Mattamy National Cycling Centre, Ontario', 41, 42.0, 13, 7.0, 176),
  // ── Australia
  _trackPreset('Adelaide', 'Adelaide 250m', 'Super-Drome, Gepps Cross', 41, 43.0, 13, 7.0, 56),
  _trackPreset('Brisbane', 'Brisbane 250m', 'Anna Meares Velodrome, Chandler', 41, 43.9, 13, 7.0, 30),
  // ── Colombia
  _trackPreset('Cali', 'Cali 250m', 'Alcides Nieto Patiño (high altitude)', 45, 46.0, 11, 7.0, 997),
  // ── Denmark
  _trackPreset('Ballerup', 'Ballerup 250m', 'Ballerup Super Arena', 40, 45.0, 14, 8.15, 30),
  // ── France
  _trackPreset('Roubaix', 'Roubaix 250m', 'Vélodrome Jean Stablinski', 42, 44.3, 13, 7.0, 25),
  _trackPreset('Saint-Quentin', 'Saint-Quentin 250m', 'Vélodrome National', 53, 43.0, 13, 8.0, 160),
  // ── Germany
  _trackPreset('Berlin', 'Berlin 250m', 'Velodrom Berlin', 38, 45.0, 13, 7.5, 35),
  // ── Hong Kong
  _trackPreset('Hong Kong', 'Hong Kong 250m', 'Tseung Kwan O', 43, 41.9, 12.4, 7.0, 10),
  // ── Italy
  _trackPreset('Montichiari', 'Montichiari 250m', 'Velodrome Fassa Bortolo', 42, 44.0, 13, 7.0, 100),
  // ── Japan
  _trackPreset('Izu', 'Izu 250m', 'Izu Olympic Velodrome', 38, 45.0, 13, 7.5, 30),
  // ── Netherlands
  _trackPreset('Apeldoorn', 'Apeldoorn 250m', 'Omnisport Apeldoorn', 40, 44.0, 13, 7.0, 15),
  // ── New Zealand
  _trackPreset('Cambridge', 'Cambridge 250m', 'Avantidrome', 41, 43.5, 13, 7.0, 50),
  // ── Poland
  _trackPreset('Pruszków', 'Pruszków 250m', 'BGŻ Arena', 41, 43.0, 13, 7.0, 100),
  // ── Switzerland
  _trackPreset('Grenchen', 'Grenchen 250m', 'Tissot Velodrome (high altitude)', 36, 46.0, 13, 7.0, 450),
  // ── Turkey
  _trackPreset('Konya', 'Konya 250m', 'Konya Velodrome - Fastest geometry', 38, 45.5, 12.7, 8.0, 1020),
  // ── United Kingdom
  _trackPreset('Derby', 'Derby 250m', 'Derby Arena', 41, 42.0, 13, 7.0, 50),
  _trackPreset('Glasgow', 'Glasgow 250m', 'Sir Chris Hoy Velodrome', 38, 44.0, 13, 7.0, 40),
  _trackPreset('London', 'London 250m', 'Lee Valley VeloPark (Olympic)', 41, 42.0, 13, 7.0, 10),
  _trackPreset('Manchester', 'Manchester 250m', 'National Cycling Centre', 41, 42.0, 13, 7.0, 40),
  // ── USA
  _trackPreset('Los Angeles', 'Los Angeles 250m', 'VELO Sports Center, Carson', 40, 45.5, 13, 7.0, 5),
  // ── Wales
  _trackPreset('Newport', 'Newport 250m', 'Geraint Thomas National Velodrome', 42, 42.0, 13, 7.0, 15),
];

export type TrackName = string;
export const DEFAULT_TRACK: TrackName = 'Bromont';

// Get track geometry for the selected track
export function getTrackGeometry(trackName: string): TrackGeometry {
  const track = TRACK_OPTIONS.find(t => t.id === trackName);
  if (!track) return TRACK_OPTIONS[0].geometry; // Bromont fallback
  return track.geometry;
}

// Compute the banking angle (in radians) at a given global distance along the black line.
// Banking transitions linearly from straight angle at bend entry/exit to turn angle at apex.
export function computeBankingAngle(s_global: number, geometry: TrackGeometry): number {
  const L = geometry.straight_m;
  const lapLen = geometry.lap_m;
  const R = (lapLen - 2 * L) / (2 * Math.PI);
  const arcLen = Math.PI * R;
  const transLen = arcLen / 2; // banking transition = half the bend

  const thetaStraight = geometry.banking_straight_deg * Math.PI / 180;
  const thetaBend = geometry.banking_turn_deg * Math.PI / 180;

  const sMod = ((s_global % lapLen) + lapLen) % lapLen;

  // [0, L): straight
  if (sMod < L) return thetaStraight;

  // [L, L+arcLen): bend 1
  if (sMod < L + arcLen) {
    const sInBend = sMod - L;
    if (transLen > 0) {
      if (sInBend < transLen) {
        const f = sInBend / transLen;
        return thetaStraight + f * (thetaBend - thetaStraight);
      } else if (sInBend > arcLen - transLen) {
        const f = (arcLen - sInBend) / transLen;
        return thetaStraight + f * (thetaBend - thetaStraight);
      }
    }
    return thetaBend;
  }

  // [L+arcLen, 2L+arcLen): straight
  if (sMod < 2 * L + arcLen) return thetaStraight;

  // [2L+arcLen, 250): bend 2
  const sInBend = sMod - (2 * L + arcLen);
  if (transLen > 0) {
    if (sInBend < transLen) {
      const f = sInBend / transLen;
      return thetaStraight + f * (thetaBend - thetaStraight);
    } else if (sInBend > arcLen - transLen) {
      const f = (arcLen - sInBend) / transLen;
      return thetaStraight + f * (thetaBend - thetaStraight);
    }
  }
  return thetaBend;
}

// Check if a distance is in a bend region
export function isInBend(s_global: number, geometry: TrackGeometry): boolean {
  const L = geometry.straight_m;
  const lapLen = geometry.lap_m;
  const R = (lapLen - 2 * L) / (2 * Math.PI);
  const arcLen = Math.PI * R;

  const sMod = ((s_global % lapLen) + lapLen) % lapLen;
  if (sMod < L) return false;
  if (sMod < L + arcLen) return true;
  if (sMod < 2 * L + arcLen) return false;
  return true;
}

// Compute the turn radius for a track
export function getTurnRadius(geometry: TrackGeometry): number {
  return (geometry.lap_m - 2 * geometry.straight_m) / (2 * Math.PI);
}

// Power profile point
export interface PowerProfilePoint {
  s_m: number;
  P_W: number;
}

// Power curve point
export interface PowerCurvePoint {
  duration_s: number;
  seated_W: number;
  standing_W: number;
}

// Athlete power curve durations (for Energy Budget optimizer)
// 1-15 individual, then 20, 25, 30, 45, 50, 60, 70, 80, 90
export const ATHLETE_CURVE_DURATIONS = [
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
  20, 25, 30, 45, 50, 60, 70, 80, 90
];

// Calculate seated power from standing power with linear convergence at 45s
// At 1s: seated = standing * (1 - discount)
// At 45s+: seated = standing (curves converge)
export function calculateSeatedFromStanding(
  standingPower: number,
  durationS: number,
  discountAt1s: number = 0.15 // 15% discount at 1 second
): number {
  const convergenceTimeS = 45;
  if (durationS >= convergenceTimeS) {
    return standingPower; // No discount at or beyond 45s
  }
  const t = Math.max(1, durationS);
  const discount = discountAt1s * (convergenceTimeS - t) / (convergenceTimeS - 1);
  return Math.round(standingPower * (1 - discount));
}

// Generate default athlete power curve (empty - user must import or enter)
export function createEmptyAthleteCurve(): PowerCurvePoint[] {
  return ATHLETE_CURVE_DURATIONS.map(d => ({
    duration_s: d,
    standing_W: 0,
    seated_W: 0,
  }));
}

// Optimizer method type
export type OptimizerMethod = 'legacy' | 'slsqp' | 'greedy';

// Effort types
export type EffortType = 50 | 100 | 150 | 200;

// Detection sensitivity levels
export type DetectionSensitivity = 'low' | 'medium' | 'high';

// Detected effort from activity
export interface DetectedEffort {
  startIndex: number;
  endIndex: number;
  startTime: number;
  endTime: number;
  duration: number;
  maxPower: number;
  avgPower: number;
  endPower: number;
  confidence: number;
  estimatedEffortType: EffortType;
}

// Quick simulation result
export interface QuickSimResult {
  T_200: number;
  T_total: number;
  v_200_entry_kph: number;
  v_200_exit_kph: number;
  v_max_kph: number;
  P_avg_sprint: number;
  splits_200: number[];
}

// Data source type (Strava or FIT file)
export type DataSource = 'strava' | 'fit';

// Activity data with records
export interface ActivityData {
  activityId?: number;     // Strava activity ID (optional for FIT files)
  activityName: string;
  records: StravaStreamRecord[];
  summary: {
    total_records: number;
    duration_s: number;
    avg_power: number;
    max_power: number;
    avg_speed: number;
    max_speed: number;
  };
  source: DataSource;      // Where the data came from
  fitFileId?: string;      // FIT file ID if source is 'fit'
  fitMetadata?: FitMetadata; // FIT file metadata (date, device, etc.)
  stravaStartDateLocal?: string; // Strava activity date for saved efforts
}

// Saved effort for progression tracking
export interface SavedEffort {
  id: string;
  activityDate: string;           // YYYY-MM-DD from FIT metadata or Strava
  savedAt: string;                // ISO timestamp
  activityName: string;
  source: DataSource;

  // Dedup key: source + (activityId|fitFileId) + startIndex + endIndex
  activityId?: number;
  fitFileId?: string;
  effortStartIndex: number;
  effortEndIndex: number;

  effortType: EffortType;

  // Official/real time (user-entered, optional)
  realTime?: number;              // seconds, e.g. 10.456

  // User notes / tag (optional free-text)
  notes?: string;

  // Raw result (what user simulated with their current params)
  rawT200: number;
  rawParams: {
    rho: number;
    crr: number;
    drivetrain_eff: number;
    mass_kg: number;
    cda_seated: number;
    cda_standing: number;
  };

  // Standardized result (race kit CdA, all-seated positions, same physics)
  standardizedT200: number;
  standardParams: {
    rho: number;
    crr: number;
    drivetrain_eff: number;
    mass_kg: number;
    cda_seated: number;
    cda_standing: number;
  };

  // Segment positions used for the raw simulation
  rawSegmentPositions?: SegmentPositions;

  // Stored for potential future re-standardization
  powerProfile: PowerProfilePoint[];

  // Activity metadata (optional, for display in detail view)
  activityMeta?: {
    fileName?: string;              // Original FIT filename
    rideDuration?: number;          // Total elapsed time in seconds
    device?: string;                // e.g. "Garmin Edge 540"
    hasPower?: boolean;
    hasCadence?: boolean;
    hasSpeed?: boolean;
    hasHeartRate?: boolean;
    sensors?: Array<{ name?: string; type?: string }>;  // Individual sensor names from FIT
  };
}

// Check if an effort is already saved (dedup by source + activity + effort indices)
export function isEffortAlreadySaved(
  savedEfforts: SavedEffort[],
  source: DataSource,
  activityId: number | undefined,
  fitFileId: string | undefined,
  startIndex: number,
  endIndex: number,
): boolean {
  return savedEfforts.some((e) => {
    if (source === 'strava' && e.source === 'strava') {
      return e.activityId === activityId && e.effortStartIndex === startIndex && e.effortEndIndex === endIndex;
    }
    if (source === 'fit' && e.source === 'fit') {
      return e.fitFileId === fitFileId && e.effortStartIndex === startIndex && e.effortEndIndex === endIndex;
    }
    return false;
  });
}

interface AppStore {
  // API configuration
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;

  // Strava auth
  stravaSessionId: string | null;
  stravaAthlete: StravaAthlete | null;
  setStravaSession: (sessionId: string, athlete: StravaAthlete) => void;
  clearStravaSession: () => void;

  // Current activity
  currentActivity: ActivityData | null;
  setCurrentActivity: (activity: ActivityData | null) => void;

  // Detected efforts
  detectedEfforts: DetectedEffort[];
  setDetectedEfforts: (efforts: DetectedEffort[]) => void;
  selectedEffortIndex: number | null;
  setSelectedEffortIndex: (index: number | null) => void;

  // Power profile (distance-based, from selected effort)
  powerProfile: PowerProfilePoint[] | null;
  powerProfileSummary: {
    totalDistanceM: number;
    sRangeStart: number;
    sRangeEnd: number;
    gridPoints: number;
    avgPowerW: number;
    maxPowerW: number;
  } | null;
  setPowerProfile: (profile: PowerProfilePoint[], summary: {
    totalDistanceM: number;
    sRangeStart: number;
    sRangeEnd: number;
    gridPoints: number;
    avgPowerW: number;
    maxPowerW: number;
  }) => void;
  clearPowerProfile: () => void;

  // Simulation parameters
  params: SimParameters;
  setParams: (params: Partial<SimParameters>) => void;
  resetParams: () => void;

  // Gearing
  gearing: GearingConfig;
  setGearing: (gearing: Partial<GearingConfig>) => void;

  // Track selection
  selectedTrack: TrackName;
  setSelectedTrack: (track: TrackName) => void;

  // Effort type for current analysis
  effortType: EffortType;
  setEffortType: (type: EffortType) => void;

  // Detection sensitivity
  detectionSensitivity: DetectionSensitivity;
  setDetectionSensitivity: (sensitivity: DetectionSensitivity) => void;

  // Segment positions (seated/standing for each track segment)
  segmentPositions: SegmentPositions;
  setSegmentPosition: (segmentId: string, position: SegmentPosition) => void;
  resetSegmentPositions: () => void;

  // Kit configuration (wheels, apparel affecting CDA)
  kitConfig: KitConfig;
  setKitConfig: (config: Partial<KitConfig>) => void;
  resetKitConfig: () => void;

  // Race kit defaults (configurable baseline for CDA calculations)
  raceKitConfig: KitConfig;
  setRaceKitConfig: (config: Partial<KitConfig>) => void;
  resetRaceKitConfig: () => void;

  // Named kit configurations (up to 5)
  kitConfigs: NamedKitConfig[];
  addKitConfig: (config: NamedKitConfig) => void;
  updateKitConfig: (id: string, updates: Partial<NamedKitConfig>) => void;
  removeKitConfig: (id: string) => void;
  setDefaultKitConfig: (id: string) => void;

  // Selected kit for current simulation (null = use default)
  selectedSimKitId: string | null;
  setSelectedSimKitId: (id: string | null) => void;

  // Last simulation kit config (for optimizer/sensitivity context)
  lastSimulationKitConfig: NamedKitConfig | null;

  // Athlete power curve (for Energy Budget optimizer)
  // Standing values from Strava, seated calculated with discount
  athletePowerCurve: PowerCurvePoint[];
  stravaPowerCurve: PowerCurvePoint[] | null; // Original Strava values for reset
  seatedDiscount: number; // Discount at 1s (e.g., 0.15 = 15%)
  setAthletePowerCurve: (curve: PowerCurvePoint[]) => void;
  setAthletePowerValue: (durationS: number, standingW: number) => void;
  setSeatedDiscount: (discount: number) => void;
  importAthleteCurveFromStrava: (stravaPowers: Array<{ duration_s: number; power_W: number }>) => void;
  resetAthleteCurveToStrava: () => void;
  clearAthleteCurve: () => void;

  // Optimizer method preference (legacy random search vs gradient-based SLSQP)
  optimizerMethod: OptimizerMethod;
  setOptimizerMethod: (method: OptimizerMethod) => void;

  // Gravity-aware position decision (accounts for track slope in standing/seated choice)
  gravityAwarePosition: boolean;
  setGravityAwarePosition: (enabled: boolean) => void;

  // Last simulation T_200 (for optimizer baseline)
  lastSimulationT200: number | null;
  setLastSimulationT200: (t200: number | null) => void;

  // Last simulation params and profile (for optimizer to use exact same inputs)
  lastSimulationParams: SimParameters | null;
  lastSimulationProfile: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }> | null;
  lastSimulationEffortType: EffortType | null;
  setLastSimulationInputs: (params: SimParameters, profile: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }>, effortType: EffortType, kitConfig?: NamedKitConfig) => void;

  // Saved efforts (persisted)
  savedEfforts: SavedEffort[];
  addSavedEffort: (effort: SavedEffort) => void;
  removeSavedEffort: (id: string) => void;
  updateSavedEffortRealTime: (id: string, realTime: number | undefined) => void;
  updateSavedEffortNotes: (id: string, notes: string | undefined) => void;
  clearSavedEfforts: () => void;
}

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      // API configuration - set EXPO_PUBLIC_BACKEND_URL in .env (see .env.example)
      apiBaseUrl: process.env.EXPO_PUBLIC_BACKEND_URL || 'http://localhost:3001/api',
      setApiBaseUrl: (url) => set({ apiBaseUrl: url }),

      // Strava auth
      stravaSessionId: null,
      stravaAthlete: null,
      setStravaSession: (sessionId, athlete) => set({ stravaSessionId: sessionId, stravaAthlete: athlete }),
      clearStravaSession: () => set({ stravaSessionId: null, stravaAthlete: null }),

      // Current activity
      currentActivity: null,
      setCurrentActivity: (activity) => set({ currentActivity: activity }),

      // Detected efforts
      detectedEfforts: [],
      setDetectedEfforts: (efforts) => set({ detectedEfforts: efforts }),
      selectedEffortIndex: null,
      setSelectedEffortIndex: (index) => set({ selectedEffortIndex: index }),

      // Power profile
      powerProfile: null,
      powerProfileSummary: null,
      setPowerProfile: (profile, summary) => set({ powerProfile: profile, powerProfileSummary: summary }),
      clearPowerProfile: () => set({ powerProfile: null, powerProfileSummary: null }),

      // Simulation parameters
      params: { ...DEFAULT_PARAMS },
      setParams: (newParams) => set((state) => ({
        params: { ...state.params, ...newParams },
      })),
      resetParams: () => set({ params: { ...DEFAULT_PARAMS } }),

      // Gearing
      gearing: { ...DEFAULT_GEARING },
      setGearing: (newGearing) => set((state) => ({
        gearing: { ...state.gearing, ...newGearing },
      })),

      // Track selection
      selectedTrack: DEFAULT_TRACK,
      setSelectedTrack: (track) => set({ selectedTrack: track }),

      // Effort type
      effortType: 200,
      setEffortType: (type) => set({ effortType: type }),

      // Detection sensitivity
      detectionSensitivity: 'medium',
      setDetectionSensitivity: (sensitivity) => set({ detectionSensitivity: sensitivity }),

      // Segment positions
      segmentPositions: { ...DEFAULT_SEGMENT_POSITIONS },
      setSegmentPosition: (segmentId, position) => set((state) => ({
        segmentPositions: { ...state.segmentPositions, [segmentId]: position },
      })),
      resetSegmentPositions: () => set({ segmentPositions: { ...DEFAULT_SEGMENT_POSITIONS } }),

      // Kit configuration (current selection)
      kitConfig: { ...DEFAULT_KIT_CONFIG },
      setKitConfig: (config) => set((state) => ({
        kitConfig: { ...state.kitConfig, ...config },
      })),
      resetKitConfig: () => set((state) => ({ kitConfig: { ...state.raceKitConfig } })),

      // Race kit defaults (configurable baseline)
      raceKitConfig: { ...DEFAULT_RACE_KIT },
      setRaceKitConfig: (config) => set((state) => ({
        raceKitConfig: { ...state.raceKitConfig, ...config },
      })),
      resetRaceKitConfig: () => set({ raceKitConfig: { ...DEFAULT_RACE_KIT } }),

      // Named kit configurations (up to 5)
      kitConfigs: [...DEFAULT_KIT_CONFIGS],
      addKitConfig: (config) => set((state) => {
        if (state.kitConfigs.length >= MAX_KIT_CONFIGS) return {};
        return { kitConfigs: [...state.kitConfigs, config] };
      }),
      updateKitConfig: (id, updates) => set((state) => ({
        kitConfigs: state.kitConfigs.map(c => c.id === id ? { ...c, ...updates } : c),
      })),
      removeKitConfig: (id) => set((state) => {
        const filtered = state.kitConfigs.filter(c => c.id !== id);
        // If we removed the default, make the first one default
        if (filtered.length > 0 && !filtered.some(c => c.isDefault)) {
          filtered[0].isDefault = true;
        }
        return { kitConfigs: filtered };
      }),
      setDefaultKitConfig: (id) => set((state) => ({
        kitConfigs: state.kitConfigs.map(c => ({
          ...c,
          isDefault: c.id === id,
        })),
      })),

      // Selected kit for simulation
      selectedSimKitId: null,
      setSelectedSimKitId: (id) => set({ selectedSimKitId: id }),

      // Last simulation kit config
      lastSimulationKitConfig: null,

      // Athlete power curve (for Energy Budget optimizer)
      athletePowerCurve: createEmptyAthleteCurve(),
      stravaPowerCurve: null,
      seatedDiscount: 0.15, // 15% at 1s
      setAthletePowerCurve: (curve) => set({ athletePowerCurve: curve }),
      setAthletePowerValue: (durationS, standingW) => set((state) => {
        const updated = state.athletePowerCurve.map(p => {
          if (p.duration_s === durationS) {
            return {
              ...p,
              standing_W: standingW,
              seated_W: calculateSeatedFromStanding(standingW, durationS, state.seatedDiscount),
            };
          }
          return p;
        });
        return { athletePowerCurve: updated };
      }),
      setSeatedDiscount: (discount) => set((state) => {
        // Recalculate all seated values with new discount
        const updated = state.athletePowerCurve.map(p => ({
          ...p,
          seated_W: calculateSeatedFromStanding(p.standing_W, p.duration_s, discount),
        }));
        return { seatedDiscount: discount, athletePowerCurve: updated };
      }),
      importAthleteCurveFromStrava: (stravaPowers) => set((state) => {
        // Map Strava powers to our durations (find closest match)
        const curve = ATHLETE_CURVE_DURATIONS.map(d => {
          // Find closest duration in Strava data
          let closest = stravaPowers[0];
          let minDiff = Math.abs(stravaPowers[0]?.duration_s - d);
          for (const sp of stravaPowers) {
            const diff = Math.abs(sp.duration_s - d);
            if (diff < minDiff) {
              minDiff = diff;
              closest = sp;
            }
          }
          // Only use if within 5s of target duration, otherwise 0
          const standingW = closest && minDiff <= 5 ? closest.power_W : 0;
          return {
            duration_s: d,
            standing_W: standingW,
            seated_W: calculateSeatedFromStanding(standingW, d, state.seatedDiscount),
          };
        });
        return {
          athletePowerCurve: curve,
          stravaPowerCurve: curve.map(p => ({ ...p })), // Save original for reset
        };
      }),
      resetAthleteCurveToStrava: () => set((state) => {
        if (state.stravaPowerCurve) {
          // Recalculate seated with current discount
          const curve = state.stravaPowerCurve.map(p => ({
            ...p,
            seated_W: calculateSeatedFromStanding(p.standing_W, p.duration_s, state.seatedDiscount),
          }));
          return { athletePowerCurve: curve };
        }
        return {};
      }),
      clearAthleteCurve: () => set({
        athletePowerCurve: createEmptyAthleteCurve(),
        stravaPowerCurve: null,
      }),

      // Optimizer method preference
      optimizerMethod: 'legacy' as OptimizerMethod,
      setOptimizerMethod: (method) => set({ optimizerMethod: method }),

      // Gravity-aware position decision
      gravityAwarePosition: false,
      setGravityAwarePosition: (enabled) => set({ gravityAwarePosition: enabled }),

      // Last simulation T_200
      lastSimulationT200: null,
      setLastSimulationT200: (t200) => set({ lastSimulationT200: t200 }),

      // Last simulation params and profile (for optimizer to use exact same inputs)
      lastSimulationParams: null,
      lastSimulationProfile: null,
      lastSimulationEffortType: null,
      setLastSimulationInputs: (params, profile, effortType, kitConfig) => set({
        lastSimulationParams: params,
        lastSimulationProfile: profile,
        lastSimulationEffortType: effortType,
        lastSimulationKitConfig: kitConfig || null,
      }),

      // Saved efforts
      savedEfforts: [],
      addSavedEffort: (effort) => set((state) => ({
        savedEfforts: [...state.savedEfforts, effort],
      })),
      removeSavedEffort: (id) => set((state) => ({
        savedEfforts: state.savedEfforts.filter((e) => e.id !== id),
      })),
      updateSavedEffortRealTime: (id, realTime) => set((state) => ({
        savedEfforts: state.savedEfforts.map((e) =>
          e.id === id ? { ...e, realTime } : e
        ),
      })),
      updateSavedEffortNotes: (id, notes) => set((state) => ({
        savedEfforts: state.savedEfforts.map((e) =>
          e.id === id ? { ...e, notes: notes || undefined } : e
        ),
      })),
      clearSavedEfforts: () => set({ savedEfforts: [] }),
    }),
    {
      name: 'flying200-storage',
      storage: createJSONStorage(() => AsyncStorage),
      version: STORE_VERSION,
      migrate,
      partialize: (state) => ({
        // Only persist these fields
        apiBaseUrl: state.apiBaseUrl,
        stravaSessionId: state.stravaSessionId,
        stravaAthlete: state.stravaAthlete,
        params: state.params,
        gearing: state.gearing,
        selectedTrack: state.selectedTrack,
        segmentPositions: state.segmentPositions,
        kitConfig: state.kitConfig,
        raceKitConfig: state.raceKitConfig,
        kitConfigs: state.kitConfigs,
        athletePowerCurve: state.athletePowerCurve,
        stravaPowerCurve: state.stravaPowerCurve,
        seatedDiscount: state.seatedDiscount,
        detectionSensitivity: state.detectionSensitivity,
        optimizerMethod: state.optimizerMethod,
        gravityAwarePosition: state.gravityAwarePosition,
        savedEfforts: state.savedEfforts,
      }),
    }
  )
);

// Sensitivity presets for detection algorithm
const SENSITIVITY_PRESETS = {
  low: {
    // Relaxed thresholds - catches more efforts but may have false positives
    powerHighPercent: 0.25,    // Lower threshold to detect sprints
    powerLowPercent: 0.12,     // Lower post-drop threshold
    powerRampCeilingPercent: 0.50,
    powerHighCap: 400,
    powerLowCap: 150,
    powerRampCeilingCap: 400,
    rampPowerFloor: 30,
    highSpeedThreshold: 50,
    lowSpeedThreshold: 20,
    minSprintDuration: 5,
    maxSprintDuration: 70,
    minTotalDuration: 30,
    maxTotalDuration: 160,
    minSpeedIncrease: 1,
    maxZeroPowerBefore: 12,
  },
  medium: {
    // Balanced thresholds - default behavior
    powerHighPercent: 0.30,
    powerLowPercent: 0.15,
    powerRampCeilingPercent: 0.45,
    powerHighCap: 500,
    powerLowCap: 200,
    powerRampCeilingCap: 450,
    rampPowerFloor: 50,
    highSpeedThreshold: 55,
    lowSpeedThreshold: 25,
    minSprintDuration: 8,
    maxSprintDuration: 60,
    minTotalDuration: 40,
    maxTotalDuration: 140,
    minSpeedIncrease: 2,
    maxZeroPowerBefore: 8,
  },
  high: {
    // Strict thresholds - fewer false positives but may miss some efforts
    powerHighPercent: 0.35,
    powerLowPercent: 0.18,
    powerRampCeilingPercent: 0.40,
    powerHighCap: 600,
    powerLowCap: 250,
    powerRampCeilingCap: 500,
    rampPowerFloor: 80,
    highSpeedThreshold: 58,
    lowSpeedThreshold: 28,
    minSprintDuration: 12,
    maxSprintDuration: 50,
    minTotalDuration: 60,
    maxTotalDuration: 120,
    minSpeedIncrease: 5,
    maxZeroPowerBefore: 5,
  },
};

// Auto-detect flying efforts (50m, 100m, 150m, 200m)
// Pattern: gradual ramp up from low speed (~15-25km/h), then sprint at high power, then sharp drop
// Key difference from STANDING STARTS:
// - Flying efforts: start at 10-25 km/h, gradual 50-70s buildup, progressive power increase
// - Standing starts: start at 0 km/h, 0W period before, explosive 0→max power in <5s
// Two-pass approach:
// 1. FIRST PASS: Original ramp-detection algorithm (works well for standard profiles)
// 2. SECOND PASS (fallback): Simplified END - 90s approach (only if first pass finds nothing)
export function detectFlying200Efforts(
  records: StravaStreamRecord[],
  _effortType: EffortType = 200,
  _sensitivity: DetectionSensitivity = 'medium'
): DetectedEffort[] {
  if (records.length < 50) return [];

  const EFFORT_DURATION = 90; // All flying efforts are 90 seconds

  // Calculate file max power for dynamic thresholds
  let fileMaxPower = 0;
  for (const r of records) {
    if (r.power_W > fileMaxPower) fileMaxPower = r.power_W;
  }

  // Thresholds based on athlete's max power - CAPPED to handle files with high-power match sprints
  const HIGH_POWER_THRESHOLD = Math.min(fileMaxPower * 0.30, 500);  // Sprint power threshold (capped at 500W)
  const LOW_POWER_THRESHOLD = Math.min(fileMaxPower * 0.15, 200);   // Post-effort drop threshold (capped at 200W)
  const RAMP_POWER_CEILING = Math.min(fileMaxPower * 0.45, 450);    // Ramp phase should be below this (capped)
  const RAMP_POWER_FLOOR = 50;  // Ramp phase must have SOME power (not 0W standing start)

  // Speed-based thresholds for alternative detection
  const HIGH_SPEED_THRESHOLD = 55;  // km/h - sprint speed
  const LOW_SPEED_THRESHOLD = 25;   // km/h - post-effort drop

  console.log(`Auto-detect: fileMaxPower=${fileMaxPower}W, highThreshold=${HIGH_POWER_THRESHOLD.toFixed(0)}W, rampCeiling=${RAMP_POWER_CEILING.toFixed(0)}W`);

  // Helper to get average power over a range
  const avgPower = (start: number, end: number) => {
    let sum = 0, count = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      sum += records[i].power_W;
      count++;
    }
    return count > 0 ? sum / count : 0;
  };

  // Helper to get average speed over a range
  const avgSpeed = (start: number, end: number) => {
    let sum = 0, count = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      sum += records[i].speed_kph || 0;
      count++;
    }
    return count > 0 ? sum / count : 0;
  };

  // Helper to get max power over a range
  const maxPowerInRange = (start: number, end: number) => {
    let max = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      max = Math.max(max, records[i].power_W);
    }
    return max;
  };

  // Helper to count zero-power seconds in a range
  const countZeroPowerSeconds = (start: number, end: number) => {
    let count = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      if (records[i].power_W < 10) count++;
    }
    return count;
  };

  // STEP 1: Find all sharp drop-offs using BOTH power and speed
  const dropOffPoints: number[] = [];
  for (let i = 10; i < records.length - 5; i++) {
    const beforeAvgPower = avgPower(i - 5, i);
    const afterAvgPower = avgPower(i + 1, i + 5);
    const beforeAvgSpeed = avgSpeed(i - 5, i);
    const afterAvgSpeed = avgSpeed(i + 1, i + 5);

    // Sharp drop detected by EITHER power OR speed pattern
    const powerDrop = beforeAvgPower >= HIGH_POWER_THRESHOLD && afterAvgPower < LOW_POWER_THRESHOLD;
    const speedDrop = beforeAvgSpeed >= HIGH_SPEED_THRESHOLD && afterAvgSpeed < LOW_SPEED_THRESHOLD;

    if (powerDrop || speedDrop) {
      // Avoid duplicates within 30s
      if (dropOffPoints.length === 0 || records[i].elapsed_s - records[dropOffPoints[dropOffPoints.length - 1]].elapsed_s > 30) {
        dropOffPoints.push(i);
        console.log(`  Drop-off at ${records[i].elapsed_s.toFixed(0)}s: power ${powerDrop ? 'YES' : 'no'}, speed ${speedDrop ? 'YES' : 'no'}`);
      }
    }
  }

  console.log(`Found ${dropOffPoints.length} potential drop-off points`);

  // ============================================================
  // FIRST PASS: Original ramp-detection algorithm (standard profiles)
  // ============================================================
  console.log('--- FIRST PASS: Ramp detection ---');
  const firstPassEfforts: DetectedEffort[] = [];

  for (const endIndex of dropOffPoints) {
    console.log(`Analyzing drop-off at ${records[endIndex].elapsed_s.toFixed(0)}s`);

    // Find actual end of high power
    let actualEndIndex = endIndex;
    for (let j = endIndex; j < Math.min(records.length, endIndex + 15); j++) {
      if (records[j].power_W < HIGH_POWER_THRESHOLD) {
        actualEndIndex = Math.max(endIndex, j - 1);
        break;
      }
    }
    while (actualEndIndex > 0 && records[actualEndIndex].power_W < HIGH_POWER_THRESHOLD) {
      actualEndIndex--;
    }
    const actualEndTime = records[actualEndIndex].elapsed_s;
    console.log(`  Actual sprint end: ${actualEndTime.toFixed(0)}s (${records[actualEndIndex].power_W}W)`);

    // Find sprint start (where power first exceeded threshold)
    let sprintStartIndex = actualEndIndex;
    for (let j = actualEndIndex - 1; j >= Math.max(0, actualEndIndex - 60); j--) {
      if (records[j].power_W < HIGH_POWER_THRESHOLD) {
        sprintStartIndex = j + 1;
        break;
      }
    }

    const sprintStartTime = records[sprintStartIndex].elapsed_s;
    const sprintDuration = actualEndTime - sprintStartTime;
    console.log(`  Sprint: ${sprintStartTime.toFixed(0)}s to ${actualEndTime.toFixed(0)}s (${sprintDuration.toFixed(1)}s)`);

    // Validate sprint phase: should be 8-60s of high power
    if (sprintDuration < 8 || sprintDuration > 60) {
      console.log(`  REJECTED: sprint ${sprintDuration.toFixed(1)}s outside 8-60s range`);
      continue;
    }

    // Work backwards to find ramp start
    const RAMP_MIN_SPEED_KPH = 5;
    const RAMP_MAX_SPEED_KPH = 35;

    let effortStartIndex = actualEndIndex;
    let foundRampStart = false;

    // Look back 60-130s from actual end for the ramp beginning
    for (let totalLen = 60; totalLen <= 130 && !foundRampStart; totalLen += 5) {
      const candidateIndex = actualEndIndex - totalLen;
      if (candidateIndex < 0) break;

      const candidateSpeed = records[candidateIndex].speed_kph || 0;
      const candidatePower = avgPower(candidateIndex, candidateIndex + 5);

      if (candidateSpeed >= RAMP_MIN_SPEED_KPH &&
          candidateSpeed <= RAMP_MAX_SPEED_KPH &&
          candidatePower >= RAMP_POWER_FLOOR &&
          candidatePower < RAMP_POWER_CEILING) {

        const midPoint = Math.floor((candidateIndex + sprintStartIndex) / 2);
        const startSpeed = avgSpeed(candidateIndex, candidateIndex + 5);
        const midSpeed = avgSpeed(midPoint, midPoint + 5);
        const endSpeed = avgSpeed(sprintStartIndex - 5, sprintStartIndex);

        if (midSpeed > startSpeed && endSpeed > midSpeed) {
          effortStartIndex = candidateIndex;
          foundRampStart = true;
          console.log(`  Found ramp start at ${records[candidateIndex].elapsed_s.toFixed(0)}s: ${candidateSpeed.toFixed(1)} km/h, ${candidatePower.toFixed(0)}W`);
        }
      }
    }

    if (!foundRampStart) {
      console.log(`  No valid ramp start found (will try fallback pass)`);
      continue;
    }

    const startTime = records[effortStartIndex].elapsed_s;
    const totalDuration = actualEndTime - startTime;
    const rampDuration = sprintStartTime - startTime;

    console.log(`  Total: ${totalDuration.toFixed(1)}s, Ramp: ${rampDuration.toFixed(1)}s, Sprint: ${sprintDuration.toFixed(1)}s`);

    // Validate total duration (should be 40-140s)
    if (totalDuration < 40 || totalDuration > 140) {
      console.log(`  REJECTED: duration ${totalDuration.toFixed(1)}s outside 40-140s range`);
      continue;
    }

    // Check for standing start indicator
    const preStartCheckIndex = Math.max(0, effortStartIndex - 15);
    const zeroPowerBeforeStart = countZeroPowerSeconds(preStartCheckIndex, effortStartIndex);
    if (zeroPowerBeforeStart >= 8) {
      console.log(`  REJECTED: ${zeroPowerBeforeStart}s of 0W before start - likely standing start`);
      continue;
    }

    // Check ramp speed increase
    const rampStartSpeed = avgSpeed(effortStartIndex, effortStartIndex + 5);
    const rampEndSpeed = avgSpeed(sprintStartIndex - 5, sprintStartIndex);
    const speedIncrease = rampEndSpeed - rampStartSpeed;
    console.log(`  Ramp speed: ${rampStartSpeed.toFixed(1)} → ${rampEndSpeed.toFixed(1)} km/h (+${speedIncrease.toFixed(1)})`);

    if (speedIncrease < 2) {
      console.log(`  REJECTED: speed increase ${speedIncrease.toFixed(1)} km/h < 2 km/h during ramp`);
      continue;
    }

    // Check ramp avg power
    const rampAvgPower = avgPower(effortStartIndex, sprintStartIndex - 1);
    if (rampAvgPower < RAMP_POWER_FLOOR) {
      console.log(`  REJECTED: ramp avg power ${rampAvgPower.toFixed(0)}W below floor`);
      continue;
    }

    // *** OVERRIDE: Use END - 90s for final effort start ***
    const targetStartTime = Math.max(0, actualEndTime - EFFORT_DURATION);
    let finalStartIndex = 0;
    let closestDiff = Infinity;
    for (let i = 0; i < records.length; i++) {
      const diff = Math.abs(records[i].elapsed_s - targetStartTime);
      if (diff < closestDiff) {
        closestDiff = diff;
        finalStartIndex = i;
      }
      if (records[i].elapsed_s > targetStartTime) break;
    }

    const finalStartTime = records[finalStartIndex].elapsed_s;
    const finalDuration = actualEndTime - finalStartTime;

    // Calculate stats
    const maxPower = maxPowerInRange(finalStartIndex, actualEndIndex);
    const totalAvgPower = Math.round(avgPower(finalStartIndex, actualEndIndex));
    const sprintAvgPower = avgPower(sprintStartIndex, actualEndIndex);

    // Calculate confidence score
    let confidence = 50;
    if (finalDuration >= 85 && finalDuration <= 95) confidence += 15;
    else if (finalDuration >= 75 && finalDuration <= 105) confidence += 10;
    if (sprintDuration >= 25 && sprintDuration <= 35) confidence += 15;
    else if (sprintDuration >= 20 && sprintDuration <= 40) confidence += 10;
    if (maxPower >= 1000) confidence += 10;
    else if (maxPower >= 800) confidence += 5;
    const powerRatio = sprintAvgPower / (rampAvgPower || 1);
    if (powerRatio >= 3) confidence += 10;
    else if (powerRatio >= 2) confidence += 5;

    console.log(`ACCEPTED (first pass): ${finalStartTime.toFixed(0)}s to ${actualEndTime.toFixed(0)}s (${finalDuration.toFixed(1)}s), confidence=${confidence}%`);

    const overlaps = firstPassEfforts.some(e => Math.abs(e.endTime - actualEndTime) < 60);
    if (!overlaps) {
      firstPassEfforts.push({
        startIndex: finalStartIndex,
        endIndex: actualEndIndex,
        startTime: finalStartTime,
        endTime: actualEndTime,
        duration: finalDuration,
        maxPower,
        avgPower: totalAvgPower,
        endPower: records[actualEndIndex].power_W,
        confidence: Math.min(100, confidence),
        estimatedEffortType: 200,
      });
    }
  }

  // If first pass found efforts, return them
  if (firstPassEfforts.length > 0) {
    console.log(`First pass found ${firstPassEfforts.length} efforts - returning`);
    firstPassEfforts.sort((a, b) => a.startTime - b.startTime);
    return firstPassEfforts.slice(0, 10);
  }

  // ============================================================
  // SECOND PASS (FALLBACK): Simple END - 90s approach
  // ============================================================
  console.log('--- SECOND PASS: Fallback (END - 90s) ---');
  const secondPassEfforts: DetectedEffort[] = [];

  for (const dropOffIndex of dropOffPoints) {
    console.log(`Fallback analyzing drop-off at ${records[dropOffIndex].elapsed_s.toFixed(0)}s`);

    let actualEndIndex = dropOffIndex;
    for (let j = dropOffIndex; j < Math.min(records.length, dropOffIndex + 15); j++) {
      if (records[j].power_W < HIGH_POWER_THRESHOLD) {
        actualEndIndex = Math.max(dropOffIndex, j - 1);
        break;
      }
    }
    while (actualEndIndex > 0 && records[actualEndIndex].power_W < HIGH_POWER_THRESHOLD) {
      actualEndIndex--;
    }
    const actualEndTime = records[actualEndIndex].elapsed_s;

    // Verify meaningful sprint phase
    const sprintCheckStart = Math.max(0, actualEndIndex - 30);
    const sprintCheckEnd = Math.max(0, actualEndIndex - 5);
    const sprintAvgPower = avgPower(sprintCheckStart, sprintCheckEnd);

    if (sprintAvgPower < HIGH_POWER_THRESHOLD * 0.5) {
      console.log(`  REJECTED: sprint avg ${sprintAvgPower.toFixed(0)}W too low`);
      continue;
    }

    // Calculate START = END - 90 seconds
    const targetStartTime = Math.max(0, actualEndTime - EFFORT_DURATION);
    let effortStartIndex = 0;
    let closestDiff = Infinity;
    for (let i = 0; i < records.length; i++) {
      const diff = Math.abs(records[i].elapsed_s - targetStartTime);
      if (diff < closestDiff) {
        closestDiff = diff;
        effortStartIndex = i;
      }
      if (records[i].elapsed_s > targetStartTime) break;
    }

    const startTime = records[effortStartIndex].elapsed_s;
    const totalDuration = actualEndTime - startTime;

    // Check for standing start
    const preStartCheckIndex = Math.max(0, effortStartIndex - 15);
    const zeroPowerBeforeStart = countZeroPowerSeconds(preStartCheckIndex, effortStartIndex);
    if (zeroPowerBeforeStart >= 8) {
      console.log(`  REJECTED: ${zeroPowerBeforeStart}s of 0W before start`);
      continue;
    }

    const maxPower = maxPowerInRange(effortStartIndex, actualEndIndex);
    const totalAvgPower = Math.round(avgPower(effortStartIndex, actualEndIndex));

    let confidence = 50;
    if (maxPower >= 1000) confidence += 15;
    else if (maxPower >= 800) confidence += 10;

    console.log(`ACCEPTED (fallback): ${startTime.toFixed(0)}s to ${actualEndTime.toFixed(0)}s (${totalDuration.toFixed(1)}s), confidence=${confidence}%`);

    const overlaps = secondPassEfforts.some(e => Math.abs(e.endTime - actualEndTime) < 60);
    if (!overlaps) {
      secondPassEfforts.push({
        startIndex: effortStartIndex,
        endIndex: actualEndIndex,
        startTime,
        endTime: actualEndTime,
        duration: totalDuration,
        maxPower,
        avgPower: totalAvgPower,
        endPower: records[actualEndIndex].power_W,
        confidence: Math.min(100, confidence),
        estimatedEffortType: 200,
      });
    }
  }

  secondPassEfforts.sort((a, b) => a.startTime - b.startTime);
  return secondPassEfforts.slice(0, 10);
}

// Peak finder - finds power dropoffs and creates 90-second efforts
// Logic: Find peak -> Find dropoff (END) -> Back up 90s (START)
// All flying efforts are exactly 90 seconds
export function findAllPowerPeaks(
  records: StravaStreamRecord[],
  _minDurationS: number = 15,
  minPowerW: number = 300
): DetectedEffort[] {
  if (records.length < 50) return [];

  const EFFORT_DURATION = 90; // All flying efforts are 90 seconds
  const efforts: DetectedEffort[] = [];

  // Calculate file stats for adaptive threshold
  let fileMaxPower = 0;
  for (const r of records) {
    if (r.power_W > fileMaxPower) fileMaxPower = r.power_W;
  }

  // Thresholds for detecting dropoffs
  const highThreshold = Math.max(minPowerW, fileMaxPower * 0.30);
  const lowThreshold = Math.max(minPowerW * 0.5, fileMaxPower * 0.15);

  console.log(`Peak finder: fileMax=${fileMaxPower}W, highThreshold=${highThreshold.toFixed(0)}W, lowThreshold=${lowThreshold.toFixed(0)}W`);

  // Helper to get average power over a range
  const avgPower = (start: number, end: number) => {
    let sum = 0, count = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      sum += records[i].power_W;
      count++;
    }
    return count > 0 ? sum / count : 0;
  };

  // Helper to get max power over a range
  const maxPowerInRange = (start: number, end: number) => {
    let max = 0;
    for (let i = start; i <= end && i < records.length; i++) {
      max = Math.max(max, records[i].power_W);
    }
    return max;
  };

  // Find all sharp dropoffs (high power -> low power transitions)
  const dropOffPoints: number[] = [];
  for (let i = 10; i < records.length - 5; i++) {
    const beforeAvg = avgPower(i - 5, i);
    const afterAvg = avgPower(i + 1, i + 5);

    // Sharp drop detected
    if (beforeAvg >= highThreshold && afterAvg < lowThreshold) {
      // Avoid duplicates within 60s
      if (dropOffPoints.length === 0 || records[i].elapsed_s - records[dropOffPoints[dropOffPoints.length - 1]].elapsed_s > 60) {
        dropOffPoints.push(i);
        console.log(`  Dropoff at ${records[i].elapsed_s.toFixed(0)}s: ${beforeAvg.toFixed(0)}W -> ${afterAvg.toFixed(0)}W`);
      }
    }
  }

  console.log(`Peak finder: found ${dropOffPoints.length} dropoff points`);

  // For each dropoff, create a 90-second effort ending at that point
  for (const dropOffIndex of dropOffPoints) {
    const endTime = records[dropOffIndex].elapsed_s;
    const endIndex = dropOffIndex;

    // Calculate START = END - 90 seconds
    const targetStartTime = Math.max(0, endTime - EFFORT_DURATION);

    // Find the index closest to target start time
    let startIndex = 0;
    let closestDiff = Infinity;
    for (let i = 0; i < records.length; i++) {
      const diff = Math.abs(records[i].elapsed_s - targetStartTime);
      if (diff < closestDiff) {
        closestDiff = diff;
        startIndex = i;
      }
      if (records[i].elapsed_s > targetStartTime) break;
    }

    const startTime = records[startIndex].elapsed_s;
    const duration = endTime - startTime;

    // Calculate stats
    const maxPower = maxPowerInRange(startIndex, endIndex);
    const totalAvgPower = Math.round(avgPower(startIndex, endIndex));

    efforts.push({
      startIndex,
      endIndex,
      startTime,
      endTime,
      duration,
      maxPower,
      avgPower: totalAvgPower,
      endPower: records[endIndex].power_W,
      confidence: 40, // Medium-low confidence - peak finder results
      estimatedEffortType: 200,
    });

    console.log(`  Effort: ${startTime.toFixed(0)}s to ${endTime.toFixed(0)}s (${duration.toFixed(1)}s), maxPower=${maxPower}W`);
  }

  // Sort by max power (highest first) and return top 15
  efforts.sort((a, b) => b.maxPower - a.maxPower);

  return efforts.slice(0, 15);
}

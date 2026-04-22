import axios from 'axios';
import { getBaseUrl } from './client';

// Available track info
export interface TrackInfo {
  id: string;
  name: string;
  description: string;
}

// Track geometry interface matching Python TrackModel
export interface TrackGeometry {
  track_name: string;
  track: {
    name: string;
    description: string;
    black_line: { x: number[]; y: number[] };
    inner_edge: { x: number[]; y: number[] };
    normals: { nx: number[]; ny: number[] };
    start: { x: number; y: number; nx: number; ny: number };
    finish: { x: number; y: number; idx: number };
    pursuit_lines: {
      top: { distance_m: number; x: number; y: number } | null;
      bottom: { distance_m: number; x: number; y: number } | null;
    };
    config: {
      W: number;
      BLACK_LINE_POSITION: number;
      RED_LINE_POSITION: number;
      BLUE_LINE_POSITION: number;
      banking_turn_deg?: number;
      banking_straight_deg?: number;
    };
    segments: { name: string; start_distance: number; end_distance: number; length: number }[];
  };
}

// Available tracks
export const AVAILABLE_TRACKS: TrackInfo[] = [
  { id: 'Bromont', name: 'Bromont 250m', description: '59m straights, 21m turns, 42° banking' },
  { id: 'Milton', name: 'Milton 250m', description: '41m straights, 27m turns, 42° banking' },
  { id: 'Konya', name: 'Konya 250m', description: '38m straights, 28m turns, 45.5° banking' },
];

// Fetch track geometry from backend
export async function getTrackGeometry(trackName: string = 'Bromont'): Promise<TrackGeometry> {
  const response = await axios.get(`${getBaseUrl()}/track/geometry`, {
    params: { track_name: trackName }
  });
  return response.data;
}

// Fetch list of available tracks
export async function getAvailableTracks(): Promise<TrackInfo[]> {
  try {
    const response = await axios.get(`${getBaseUrl()}/track/list`);
    return response.data.tracks || AVAILABLE_TRACKS;
  } catch {
    return AVAILABLE_TRACKS;
  }
}

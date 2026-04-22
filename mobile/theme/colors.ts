export const colors = {
  // Background layers
  bg0: '#080C12',
  bg1: '#0E1420',
  bg2: '#151D2B',
  bg3: '#1C2636',

  // Borders
  border: '#1E2A3A',
  borderAccent: '#2A3A4E',

  // Text
  textPrimary: '#E8ECF0',
  textSecondary: '#7A8BA0',
  textMuted: '#4A5568',

  // Accent
  accent: '#00D4FF',
  accentDim: '#0091B3',
  accentGlow: 'rgba(0, 212, 255, 0.15)',
  accentSubtle: 'rgba(0, 212, 255, 0.08)',

  // Semantic
  success: '#00E676',
  successDim: 'rgba(0, 230, 118, 0.15)',
  warning: '#FFB300',
  warningDim: 'rgba(255, 179, 0, 0.15)',
  danger: '#FF3D51',
  dangerDim: 'rgba(255, 61, 81, 0.15)',

  // Position coding
  seated: '#2979FF',
  seatedDim: 'rgba(41, 121, 255, 0.15)',
  standing: '#FF6D00',
  standingDim: 'rgba(255, 109, 0, 0.15)',

  // Special
  strava: '#FC4C02',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.7)',
} as const;

export type ColorKey = keyof typeof colors;

import { colors, fonts, spacing } from '../../theme';
import React, { useState, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  TextInput,
  Share,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LineChart } from 'react-native-chart-kit';
import { Dimensions } from 'react-native';
import { useAppStore, TRACK_SEGMENTS, TRACK_OPTIONS, getDefaultKitConfig, isEffortAlreadySaved, DEFAULT_SEGMENT_POSITIONS, getTrackGeometry, computeBankingAngle, isInBend, getTurnRadius } from '../../store/simulationStore';
import type { SegmentPosition, NamedKitConfig, SavedEffort, TrackGeometry } from '../../store/simulationStore';
import { simulationApi, BreakevenCdAResult, DualBreakevenCdAResult } from '../../api/client';
import Svg, { Path, Line, Text as SvgText } from 'react-native-svg';

// Helper function to get CdA for a given distance based on segment positions and kit CdA values
function getCdAForDistance(
  distanceM: number,
  segmentPositions: Record<string, 'seated' | 'standing'>,
  cdaSeated: number,
  cdaStanding: number,
): number {
  // Find which segment this distance falls into
  for (const segment of TRACK_SEGMENTS) {
    if (distanceM >= segment.startM && distanceM <= segment.endM) {
      // Locked segments (timed 200m) are always seated
      if (segment.locked) {
        return cdaSeated;
      }
      const position = segmentPositions[segment.id] || 'seated';
      return position === 'standing' ? cdaStanding : cdaSeated;
    }
  }
  // Default to seated CdA if no segment found
  return cdaSeated;
}

// Default track trajectory with correct y_m (height) values for each distance point
// These are the typical track positions for a flying 200m buildup (same as web)
const DEFAULT_TRACK_TRAJECTORY = [
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

const screenWidth = Dimensions.get('window').width;

// The DEFAULT_TRACK_TRAJECTORY was authored for Bromont (width = 7.5m).
// When using a different track, y_m must be scaled proportionally to track width,
// but ONLY for positions above the red line (0.9m from black line, UCI standard).
// Positions at or below the red line are identical on all 250m tracks — a rider
// sprinting near the black line doesn't change position just because the track is wider.
const REFERENCE_TRACK_WIDTH = 7.5; // Bromont width (m)
const RED_LINE_POSITION = 0.9;     // UCI standard red line distance from black line (m)

function scaleTrajectoryForTrack(
  trajectory: Array<{ s_m: number; y_m: number; CdA_m2: number }>,
  trackWidth: number,
): Array<{ s_m: number; y_m: number; CdA_m2: number }> {
  if (trackWidth === REFERENCE_TRACK_WIDTH) return trajectory;
  // Scale the portion above the red line proportionally to available width above it
  const refAboveRed = REFERENCE_TRACK_WIDTH - RED_LINE_POSITION;
  const newAboveRed = trackWidth - RED_LINE_POSITION;
  const scale = newAboveRed / refAboveRed;
  return trajectory.map((p) => {
    if (p.y_m <= RED_LINE_POSITION) return p; // below red line: no change
    const aboveRed = p.y_m - RED_LINE_POSITION;
    const scaledY = RED_LINE_POSITION + aboveRed * scale;
    return {
      s_m: p.s_m,
      y_m: Math.min(scaledY, trackWidth), // clamp to track width
      CdA_m2: p.CdA_m2,
    };
  });
}

interface SimulationResult {
  T_total: number;
  T_200: number;
  T_sprint: number;
  v_200_entry_kph: number;
  v_200_exit_kph: number;
  v_max_kph: number;
  P_avg_sprint: number;
  splits_200: number[];
  speed_profile?: Array<{ s_m: number; v_kph: number }>;
}

interface CollapsibleSectionProps {
  title: string;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({ title, defaultExpanded = false, children }: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <View style={styles.section}>
      <TouchableOpacity style={styles.sectionHeader} onPress={() => setExpanded(!expanded)}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.expandIcon}>{expanded ? '−' : '+'}</Text>
      </TouchableOpacity>
      {expanded && <View style={styles.sectionContent}>{children}</View>}
    </View>
  );
}

interface ParamRowProps {
  label: string;
  value: number;
  unit: string;
  onChangeText: (value: string) => void;
  step?: number;
}

function ParamRow({ label, value, unit, onChangeText }: ParamRowProps) {
  // Use local state to allow typing intermediate values like "1." or ""
  const [localValue, setLocalValue] = useState(value.toString());
  const [isFocused, setIsFocused] = useState(false);

  // Sync local value with prop value when not focused (e.g., when params change externally)
  React.useEffect(() => {
    if (!isFocused) {
      setLocalValue(value.toString());
    }
  }, [value, isFocused]);

  const handleBlur = () => {
    setIsFocused(false);
    const num = parseFloat(localValue);
    if (!isNaN(num)) {
      onChangeText(num.toString());
      setLocalValue(num.toString());
    } else {
      // Revert to the current value if invalid
      setLocalValue(value.toString());
    }
  };

  return (
    <View style={styles.paramRow}>
      <Text style={styles.paramLabel}>{label}</Text>
      <View style={styles.paramInputWrapper}>
        <TextInput
          style={styles.paramInput}
          value={localValue}
          onChangeText={setLocalValue}
          onFocus={() => setIsFocused(true)}
          onBlur={handleBlur}
          keyboardType="decimal-pad"
        />
        <Text style={styles.paramUnit}>{unit}</Text>
      </View>
    </View>
  );
}

// Overridable parameter row (shows reset button when value differs from source)
interface OverridableParamRowProps {
  label: string;
  value: number;
  sourceValue: number;
  unit: string;
  isOverridden: boolean;
  onChangeValue: (num: number) => void;
  onReset: () => void;
}

function OverridableParamRow({ label, value, sourceValue, unit, isOverridden, onChangeValue, onReset }: OverridableParamRowProps) {
  const [localValue, setLocalValue] = useState(value.toString());
  const [isFocused, setIsFocused] = useState(false);

  React.useEffect(() => {
    if (!isFocused) {
      setLocalValue(value.toString());
    }
  }, [value, isFocused]);

  const handleBlur = () => {
    setIsFocused(false);
    const num = parseFloat(localValue);
    if (!isNaN(num)) {
      onChangeValue(num);
      setLocalValue(num.toString());
    } else {
      setLocalValue(value.toString());
    }
  };

  return (
    <View style={styles.paramRow}>
      <View style={styles.paramLabelRow}>
        <Text style={[styles.paramLabel, isOverridden && styles.paramLabelOverridden]}>
          {label}
        </Text>
        {isOverridden && (
          <TouchableOpacity style={styles.resetOverrideButton} onPress={onReset}>
            <Text style={styles.resetOverrideText}>Reset ({sourceValue})</Text>
          </TouchableOpacity>
        )}
      </View>
      <View style={styles.paramInputWrapper}>
        <TextInput
          style={[styles.paramInput, isOverridden && styles.paramInputOverridden]}
          value={localValue}
          onChangeText={setLocalValue}
          onFocus={() => setIsFocused(true)}
          onBlur={handleBlur}
          keyboardType="decimal-pad"
        />
        <Text style={styles.paramUnit}>{unit}</Text>
      </View>
    </View>
  );
}

// Kit config selector for simulation page
interface KitSelectorProps {
  configs: NamedKitConfig[];
  selectedId: string;
  onSelect: (id: string) => void;
}

function KitSelector({ configs, selectedId, onSelect }: KitSelectorProps) {
  return (
    <View style={styles.kitSelectorContainer}>
      {configs.map((config) => (
        <TouchableOpacity
          key={config.id}
          style={[styles.kitSelectorItem, selectedId === config.id && styles.kitSelectorItemSelected]}
          onPress={() => onSelect(config.id)}
          activeOpacity={1}
        >
          <View style={styles.kitSelectorItemLeft}>
            <View style={styles.kitSelectorNameRow}>
              <Text style={[styles.kitSelectorName, selectedId === config.id && styles.kitSelectorNameSelected]}>
                {config.name}
              </Text>
              {config.isDefault && (
                <Text style={styles.kitSelectorDefault}> (default)</Text>
              )}
            </View>
            {config.description ? (
              <Text style={styles.kitSelectorDesc} numberOfLines={1}>{config.description}</Text>
            ) : null}
          </View>
          <Text style={[styles.kitSelectorCda, selectedId === config.id && styles.kitSelectorCdaSelected]}>
            {config.cdaSeated.toFixed(3)} / {config.cdaStanding.toFixed(3)}
          </Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

// Compact position toggle for simulation page
function SimSegmentRow({ label, position, onToggle, locked, isTimed }: {
  label: string;
  position: SegmentPosition;
  onToggle: () => void;
  locked?: boolean;
  isTimed?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[
        styles.simSegmentRow,
        isTimed && styles.simSegmentRowTimed,
        locked && styles.simSegmentRowLocked,
      ]}
      onPress={locked ? undefined : onToggle}
      disabled={locked}
    >
      <Text style={[
        styles.simSegmentLabel,
        isTimed && styles.simSegmentLabelTimed,
        locked && styles.simSegmentLabelLocked,
      ]} numberOfLines={1}>
        {label}
      </Text>
      <View style={[
        styles.simSegmentToggle,
        locked ? styles.simSegmentToggleLocked :
          (position === 'standing' ? styles.simSegmentToggleStanding : styles.simSegmentToggleSeated)
      ]}>
        <Text style={[styles.simSegmentToggleText, locked && styles.simSegmentToggleTextLocked]}>
          {locked ? 'Locked' : (position === 'standing' ? 'Standing' : 'Seated')}
        </Text>
      </View>
    </TouchableOpacity>
  );
}

export default function SimulationScreen() {
  const router = useRouter();
  const { params, setParams, gearing, setGearing, selectedTrack, setSelectedTrack, powerProfile, powerProfileSummary, effortType, segmentPositions: storedSegmentPositions, kitConfigs, selectedSimKitId, setSelectedSimKitId, setLastSimulationT200, setLastSimulationInputs, currentActivity, selectedEffortIndex, detectedEfforts, savedEfforts, addSavedEffort } = useAppStore();

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [simProfileRows, setSimProfileRows] = useState<Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }>>([]);

  // Local sim-specific overrides for positions
  const [simSegmentPositions, setSimSegmentPositions] = useState<Record<string, SegmentPosition>>({ ...storedSegmentPositions });

  React.useEffect(() => {
    setSimSegmentPositions({ ...storedSegmentPositions });
  }, [Object.keys(storedSegmentPositions).length]);

  // Get selected kit config (or default)
  const defaultKit = getDefaultKitConfig(kitConfigs);
  const activeKitId = selectedSimKitId || defaultKit.id;
  const activeKit = kitConfigs.find(c => c.id === activeKitId) || defaultKit;

  // CdA overrides (null = use kit value, number = user override)
  const [cdaSeatedOverride, setCdaSeatedOverride] = useState<number | null>(null);
  const [cdaStandingOverride, setCdaStandingOverride] = useState<number | null>(null);

  // Reset overrides when kit selection changes
  React.useEffect(() => {
    setCdaSeatedOverride(null);
    setCdaStandingOverride(null);
  }, [activeKitId]);

  // Effective CdA values used for simulation
  const effectiveCdaSeated = cdaSeatedOverride ?? activeKit.cdaSeated;
  const effectiveCdaStanding = cdaStandingOverride ?? activeKit.cdaStanding;
  const hasCdaOverride = cdaSeatedOverride !== null || cdaStandingOverride !== null;

  // Track-scaled trajectory: scale y_m from Bromont reference to selected track width
  const trackGeometry = getTrackGeometry(selectedTrack);
  const scaledTrajectory = useMemo(
    () => scaleTrajectoryForTrack(DEFAULT_TRACK_TRAJECTORY, trackGeometry.width_m),
    [trackGeometry.width_m],
  );

  // Params with track geometry included (sent to backend)
  const paramsWithTrack = useMemo(() => ({
    ...params,
    track_geometry: {
      straight_m: trackGeometry.straight_m,
      banking_turn_deg: trackGeometry.banking_turn_deg,
      banking_straight_deg: trackGeometry.banking_straight_deg,
      lap_m: trackGeometry.lap_m,
    },
  }), [params, trackGeometry]);

  // Breakeven CdA state
  const [targetEntrySpeedKph, setTargetEntrySpeedKph] = useState<string>('');
  const [targetTimedSectionS, setTargetTimedSectionS] = useState<string>('');
  const [breakevenResult, setBreakevenResult] = useState<BreakevenCdAResult | null>(null);
  const [breakevenLoading, setBreakevenLoading] = useState(false);

  // Dual breakeven CdA state (for solving both seated and standing CdAs)
  const [dualMode, setDualMode] = useState(false);
  const [dualBreakevenResult, setDualBreakevenResult] = useState<DualBreakevenCdAResult | null>(null);

  // Save effort state
  const [saving, setSaving] = useState(false);
  const [showRealTimeInput, setShowRealTimeInput] = useState(false);
  const [realTimeInput, setRealTimeInput] = useState('');

  const currentEffort = selectedEffortIndex !== null ? detectedEfforts[selectedEffortIndex] : null;
  const alreadySaved = currentEffort && currentActivity
    ? isEffortAlreadySaved(
        savedEfforts,
        currentActivity.source,
        currentActivity.activityId,
        currentActivity.fitFileId,
        currentEffort.startIndex,
        currentEffort.endIndex,
      )
    : false;

  const getActivityDate = (): string => {
    if (!currentActivity) return new Date().toISOString().slice(0, 10);
    if (currentActivity.source === 'strava' && currentActivity.stravaStartDateLocal) {
      return currentActivity.stravaStartDateLocal.slice(0, 10);
    }
    if (currentActivity.source === 'fit' && currentActivity.fitMetadata?.activity_date) {
      return currentActivity.fitMetadata.activity_date;
    }
    return new Date().toISOString().slice(0, 10);
  };

  const saveEffort = async (realTime?: number) => {
    if (!powerProfile || !result || !currentActivity || !currentEffort) {
      Alert.alert('Error', 'Run a simulation first, then save.');
      return;
    }

    try {
      setSaving(true);

      // Standard params: race kit CdA, all-seated positions
      const raceKit = getDefaultKitConfig(kitConfigs);

      // Build standardized profile (race kit CdA + all-seated)
      const sortedPower = [...powerProfile].sort((a, b) => a.s_m - b.s_m);
      const standardProfileRows = scaledTrajectory.map((traj) => {
        let closestPower = 0;
        let closestDist = Infinity;
        for (const p of sortedPower) {
          const dist = Math.abs(p.s_m - traj.s_m);
          if (dist < closestDist) {
            closestDist = dist;
            closestPower = p.P_W;
          }
        }
        const segmentCdA = getCdAForDistance(
          traj.s_m,
          DEFAULT_SEGMENT_POSITIONS,
          raceKit.cdaSeated,
          raceKit.cdaStanding,
        );
        return {
          s_m: traj.s_m,
          y_m: traj.y_m,
          CdA_m2: parseFloat(segmentCdA.toFixed(4)),
          P_W: closestPower,
        };
      });

      // Re-simulate with standard settings
      const standardResponse = await simulationApi.run(
        { rows: standardProfileRows },
        paramsWithTrack,
      );

      if (!standardResponse.success) {
        Alert.alert('Error', 'Standardized simulation failed.');
        return;
      }

      const standardT200 = standardResponse.base.splits_200
        ?.slice(0, effortType / 50)
        .reduce((a: number, b: number) => a + b, 0);

      const rawT200 = result.splits_200
        .slice(0, effortType / 50)
        .reduce((a, b) => a + b, 0);

      // Build activity metadata for detail view
      const fitMeta = currentActivity.fitMetadata;
      const records = currentActivity.records;
      const hasPower = records.some(r => r.power_W > 0);
      const hasCadence = records.some(r => r.cadence_rpm > 0);
      const hasSpeed = records.some(r => r.speed_kph > 0);
      const hasHeartRate = records.some(r => r.heartrate != null && r.heartrate > 0);

      const activityMeta: SavedEffort['activityMeta'] = {
        rideDuration: currentActivity.summary.duration_s,
        hasPower,
        hasCadence,
        hasSpeed,
        hasHeartRate,
        sensors: fitMeta?.sensors || undefined,
      };

      if (currentActivity.source === 'fit') {
        activityMeta.fileName = currentActivity.fitFileId;
        if (fitMeta?.device_manufacturer || fitMeta?.device_product) {
          activityMeta.device = [fitMeta.device_manufacturer, fitMeta.device_product].filter(Boolean).join(' ');
        }
      }

      const saved: SavedEffort = {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2),
        activityDate: getActivityDate(),
        savedAt: new Date().toISOString(),
        activityName: currentActivity.activityName,
        source: currentActivity.source,
        activityId: currentActivity.activityId,
        fitFileId: currentActivity.fitFileId,
        effortStartIndex: currentEffort.startIndex,
        effortEndIndex: currentEffort.endIndex,
        effortType,
        realTime: realTime,
        rawT200,
        rawParams: {
          rho: params.rho,
          crr: params.crr,
          drivetrain_eff: params.drivetrain_eff,
          mass_kg: params.mass_kg,
          cda_seated: effectiveCdaSeated,
          cda_standing: effectiveCdaStanding,
        },
        standardizedT200: standardT200,
        standardParams: {
          rho: params.rho,
          crr: params.crr,
          drivetrain_eff: params.drivetrain_eff,
          mass_kg: params.mass_kg,
          cda_seated: raceKit.cdaSeated,
          cda_standing: raceKit.cdaStanding,
        },
        rawSegmentPositions: { ...simSegmentPositions },
        powerProfile: [...powerProfile],
        activityMeta,
      };

      addSavedEffort(saved);
      Alert.alert('Saved', `Effort saved.\nStandard F${effortType}: ${standardT200.toFixed(3)}s${realTime ? `\nReal: ${realTime.toFixed(3)}s` : ''}`);
    } catch (err) {
      console.error('Save effort error:', err);
      Alert.alert('Error', 'Failed to save effort.');
    } finally {
      setSaving(false);
    }
  };

  const handleSavePress = () => {
    setRealTimeInput('');
    setShowRealTimeInput(true);
  };

  const handleSaveConfirm = () => {
    setShowRealTimeInput(false);
    const realTime = parseFloat(realTimeInput);
    saveEffort(isNaN(realTime) || realTime <= 0 ? undefined : realTime);
  };

  const handleSaveSkip = () => {
    setShowRealTimeInput(false);
    saveEffort(undefined);
  };

  // Export simulation inputs for debugging/development
  const exportToDev = async () => {
    // Build the complete profile rows (same as runSimulation) - this is what Python ingests
    const sortedPower = powerProfile ? [...powerProfile].sort((a, b) => a.s_m - b.s_m) : [];
    const profileRows = scaledTrajectory.map((traj) => {
      // Find closest power value
      let closestPower = 0;
      let closestDist = Infinity;
      for (const p of sortedPower) {
        const dist = Math.abs(p.s_m - traj.s_m);
        if (dist < closestDist) {
          closestDist = dist;
          closestPower = p.P_W;
        }
      }
      // Get CdA based on segment position using effective CdA values (kit or override)
      const segmentCdA = getCdAForDistance(
        traj.s_m,
        simSegmentPositions,
        effectiveCdaSeated,
        effectiveCdaStanding,
      );
      return {
        s_m: traj.s_m,
        y_m: traj.y_m,
        CdA_m2: parseFloat(segmentCdA.toFixed(4)),
        P_W: closestPower,
      };
    });

    // Gather all simulation inputs
    const exportData = {
      timestamp: new Date().toISOString(),
      effortType: `F${effortType}`,
      track: selectedTrack,
      track_geometry: trackGeometry,

      // Physics parameters (what Python simulation uses)
      parameters: {
        mass_kg: params.mass_kg,
        rho: params.rho,
        crr: params.crr,
        drivetrain_eff: params.drivetrain_eff,
        cda_seated: effectiveCdaSeated,
        cda_standing: effectiveCdaStanding,
      },

      // Gearing
      gearing: {
        chainring: gearing.chainring,
        cog: gearing.cog,
        wheel_circ_mm: gearing.wheelCircMm,
      },

      // Kit configuration used
      kit_config: {
        name: activeKit.name,
        cda_seated: effectiveCdaSeated,
        cda_standing: effectiveCdaStanding,
        overridden: hasCdaOverride,
      },

      // Standing segments
      standing_segments: Object.entries(simSegmentPositions)
        .filter(([_, pos]) => pos === 'standing')
        .map(([id]) => id),

      // THE MAIN DATA: Complete profile rows for Python simulation
      // Format: { s_m, y_m, CdA_m2, P_W } for each 10m point
      profile_rows: profileRows,

      // Last simulation result (if any)
      last_result: result ? {
        T_200: result.T_200,
        v_entry_kph: result.v_200_entry_kph,
        v_exit_kph: result.v_200_exit_kph,
        v_max_kph: result.v_max_kph,
      } : null,
    };

    const jsonString = JSON.stringify(exportData, null, 2);

    try {
      await Share.share({
        message: jsonString,
        title: `Flying ${effortType} Simulation Data`,
      });
    } catch (err) {
      console.error('Share failed:', err);
    }
  };

  const runSimulation = async () => {
    if (!powerProfile || powerProfile.length === 0) {
      Alert.alert('Error', 'No power profile loaded. Select an effort from Analysis first.');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Sort power profile by distance for interpolation
      const sortedPower = [...powerProfile].sort((a, b) => a.s_m - b.s_m);

      // Build complete track profile by merging power data with default trajectory
      // This ensures correct y_m (height) values are used for the simulation
      // CdA is determined by segment position (seated/standing) + kit modifier
      const profileRows = scaledTrajectory.map((traj) => {
        // Find closest power value from the provided power profile
        let closestPower = 0;
        let closestDist = Infinity;
        for (const p of sortedPower) {
          const dist = Math.abs(p.s_m - traj.s_m);
          if (dist < closestDist) {
            closestDist = dist;
            closestPower = p.P_W;
          }
        }

        // Get CdA based on segment position using effective CdA values (kit or override)
        const segmentCdA = getCdAForDistance(
          traj.s_m,
          simSegmentPositions,
          effectiveCdaSeated,
          effectiveCdaStanding,
        );

        return {
          s_m: traj.s_m,
          y_m: traj.y_m,  // Use correct track height from trajectory
          CdA_m2: segmentCdA,  // Use CdA based on segment position + kit
          P_W: closestPower,
        };
      });

      console.log(`Running simulation with ${profileRows.length} profile points`);
      console.log(`Power range: ${Math.min(...profileRows.map(p => p.P_W))}W - ${Math.max(...profileRows.map(p => p.P_W))}W`);
      console.log(`Effort type: ${effortType}`);

      const response = await simulationApi.run({ rows: profileRows }, paramsWithTrack);

      if (response.success) {
        setResult(response.base);
        setSimProfileRows(profileRows);
        // Save T_200 for optimizer baseline
        const t200 = response.base.splits_200?.slice(0, effortType / 50).reduce((a: number, b: number) => a + b, 0);
        if (t200) {
          setLastSimulationT200(t200);
        }
        // Save params and profile for optimizer to use exact same inputs
        // This ensures optimizer baseline matches simulation exactly
        setLastSimulationInputs({ ...params }, profileRows, effortType, activeKit);
        console.log('Saved simulation inputs for optimizer with effort type:', effortType, 'kit:', activeKit.name);
      } else {
        setError(response.error || 'Simulation failed');
      }
    } catch (err) {
      console.error('Simulation error:', err);
      setError('Failed to run simulation');
    } finally {
      setLoading(false);
    }
  };

  const updateParam = (key: string, value: string) => {
    const num = parseFloat(value);
    if (!isNaN(num)) {
      setParams({ [key]: num });
    }
  };

  // Compute breakeven CdA values
  const computeBreakevenCdA = async () => {
    if (!powerProfile || powerProfile.length === 0) {
      Alert.alert('Error', 'No power profile loaded. Select an effort from Analysis first.');
      return;
    }

    const entrySpeed = targetEntrySpeedKph ? parseFloat(targetEntrySpeedKph) : undefined;
    const timedSection = targetTimedSectionS ? parseFloat(targetTimedSectionS) : undefined;

    if (!entrySpeed && !timedSection) {
      Alert.alert('Error', 'Enter at least one target value (entry speed or timed section).');
      return;
    }

    try {
      setBreakevenLoading(true);
      setBreakevenResult(null);

      const response = await simulationApi.computeBreakevenCdA(
        powerProfile,
        paramsWithTrack,
        entrySpeed,
        timedSection,
        effortType
      );

      if (response.success) {
        setBreakevenResult(response);
      } else {
        Alert.alert('Error', response.error || 'Failed to compute breakeven CdA');
      }
    } catch (err) {
      console.error('Breakeven CdA error:', err);
      Alert.alert('Error', 'Failed to compute breakeven CdA');
    } finally {
      setBreakevenLoading(false);
    }
  };

  // Compute DUAL breakeven CdA values (seated + standing)
  const computeDualBreakevenCdA = async () => {
    if (!powerProfile || powerProfile.length === 0) {
      Alert.alert('Error', 'No power profile loaded. Select an effort from Analysis first.');
      return;
    }

    const entrySpeed = targetEntrySpeedKph ? parseFloat(targetEntrySpeedKph) : undefined;
    const timedSection = targetTimedSectionS ? parseFloat(targetTimedSectionS) : undefined;

    if (!entrySpeed || !timedSection) {
      Alert.alert('Error', 'Dual mode requires BOTH entry speed AND timed section.');
      return;
    }

    try {
      setBreakevenLoading(true);
      setDualBreakevenResult(null);
      setBreakevenResult(null);

      const response = await simulationApi.computeDualBreakevenCdA(
        powerProfile,
        paramsWithTrack,
        entrySpeed,
        timedSection,
        simSegmentPositions,
        effortType
      );

      if (response.success) {
        setDualBreakevenResult(response);
      } else {
        Alert.alert('Error', response.error || 'Failed to compute dual breakeven CdA');
      }
    } catch (err: unknown) {
      console.error('Dual breakeven CdA error:', err);
      // Extract axios error message if available
      const errorMessage = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { error?: string } } }).response?.data?.error || 'Server error'
        : err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message
        : 'Failed to compute dual breakeven CdA';
      Alert.alert('Error', errorMessage);
    } finally {
      setBreakevenLoading(false);
    }
  };

  // Speed chart data
  const getSpeedChartData = () => {
    if (!result?.speed_profile || result.speed_profile.length === 0) return null;

    const sampled = result.speed_profile.filter((_, i) => i % 10 === 0);
    return {
      labels: [],
      datasets: [{ data: sampled.map((p) => p.v_kph) }],
    };
  };

  // Net Watts & CdA data for the custom SVG chart
  // Net Watts = P_rider * drivetrain_eff - P_aero - P_rr - P_gravity
  const netWattsData = useMemo(() => {
    if (simProfileRows.length === 0 || !result?.speed_profile || result.speed_profile.length === 0) return null;

    const speedProfile = result.speed_profile;
    const netWatts: number[] = [];
    const distances: number[] = [];
    const cdaValues: number[] = [];

    for (let i = 0; i < simProfileRows.length; i++) {
      const p = simProfileRows[i];
      distances.push(p.s_m);
      cdaValues.push(p.CdA_m2);

      // Find speed at this distance from speed_profile (interpolate)
      let v_kph = 0;
      for (let j = 0; j < speedProfile.length - 1; j++) {
        if (speedProfile[j].s_m <= p.s_m && speedProfile[j + 1].s_m >= p.s_m) {
          const frac = (p.s_m - speedProfile[j].s_m) / (speedProfile[j + 1].s_m - speedProfile[j].s_m || 1);
          v_kph = speedProfile[j].v_kph + frac * (speedProfile[j + 1].v_kph - speedProfile[j].v_kph);
          break;
        }
      }
      if (v_kph === 0 && speedProfile.length > 0) {
        const closest = speedProfile.reduce((best, sp) =>
          Math.abs(sp.s_m - p.s_m) < Math.abs(best.s_m - p.s_m) ? sp : best
        );
        v_kph = closest.v_kph;
      }

      const v_ms = v_kph / 3.6;
      const P_aero = 0.5 * params.rho * p.CdA_m2 * v_ms * v_ms * v_ms;
      const P_rr = params.crr * params.mass_kg * 9.81 * v_ms;

      let P_grav = 0;
      if (i < simProfileRows.length - 1) {
        const ds = simProfileRows[i + 1].s_m - p.s_m;
        const dh = simProfileRows[i + 1].y_m - p.y_m;
        if (ds > 0) {
          P_grav = params.mass_kg * 9.81 * (dh / ds) * v_ms;
        }
      }

      const P_net = p.P_W * params.drivetrain_eff - P_aero - P_rr - P_grav;
      netWatts.push(P_net);
    }

    return { netWatts, distances, cdaValues };
  }, [simProfileRows, result?.speed_profile, params]);

  // W/CdA vs Breakeven W/CdA data (using raw powermeter watts)
  // Actual W/CdA = P_W / CdA (raw watts per drag area)
  // Breakeven W/CdA = 0.5 * rho * v^3  (aero drag power per CdA)
  // When actual > breakeven → accelerating, below → decelerating
  const wCdaData = useMemo(() => {
    if (simProfileRows.length === 0 || !result?.speed_profile || result.speed_profile.length === 0) return null;

    const speedProfile = result.speed_profile;
    const actualWCdA: number[] = [];
    const breakevenWCdA: number[] = [];
    const distances: number[] = [];

    for (let i = 0; i < simProfileRows.length; i++) {
      const p = simProfileRows[i];
      distances.push(p.s_m);

      // Interpolate speed
      let v_kph = 0;
      for (let j = 0; j < speedProfile.length - 1; j++) {
        if (speedProfile[j].s_m <= p.s_m && speedProfile[j + 1].s_m >= p.s_m) {
          const frac = (p.s_m - speedProfile[j].s_m) / (speedProfile[j + 1].s_m - speedProfile[j].s_m || 1);
          v_kph = speedProfile[j].v_kph + frac * (speedProfile[j + 1].v_kph - speedProfile[j].v_kph);
          break;
        }
      }
      if (v_kph === 0 && speedProfile.length > 0) {
        const closest = speedProfile.reduce((best, sp) =>
          Math.abs(sp.s_m - p.s_m) < Math.abs(best.s_m - p.s_m) ? sp : best
        );
        v_kph = closest.v_kph;
      }

      const v_ms = v_kph / 3.6;

      // Actual W/CdA = raw powermeter watts / CdA
      const wcda = p.CdA_m2 > 0 ? p.P_W / p.CdA_m2 : 0;
      actualWCdA.push(wcda);

      // Breakeven W/CdA = aero drag power per CdA at current speed
      breakevenWCdA.push(0.5 * params.rho * v_ms * v_ms * v_ms);
    }

    return { actualWCdA, breakevenWCdA, distances };
  }, [simProfileRows, result?.speed_profile, params]);

  return (
    <ScrollView style={styles.container}>
      {/* Return to Efforts */}
      <TouchableOpacity style={styles.returnButton} onPress={() => router.push('/(data)/analysis')}>
        <Text style={styles.returnButtonText}>← Efforts</Text>
      </TouchableOpacity>

      {/* Status Banner */}
      <View style={styles.statusBanner}>
        {powerProfile ? (
          <Text style={styles.statusText}>
            Power profile loaded: {powerProfileSummary?.gridPoints} points, {powerProfileSummary?.avgPowerW}W avg
          </Text>
        ) : (
          <Text style={styles.statusTextWarn}>
            No power profile. Select an effort from Analysis tab.
          </Text>
        )}
      </View>

      {/* Track Selector */}
      <CollapsibleSection title="Track" defaultExpanded={false}>
        <View style={styles.trackOptionsRow}>
          {TRACK_OPTIONS.map((track) => (
            <TouchableOpacity
              key={track.id}
              style={[
                styles.trackOption,
                selectedTrack === track.id && styles.trackOptionSelected,
              ]}
              onPress={() => setSelectedTrack(track.id)}
              activeOpacity={1}
            >
              <Text style={[
                styles.trackOptionName,
                selectedTrack === track.id && styles.trackOptionNameSelected,
              ]}>
                {track.id}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </CollapsibleSection>

      {/* Gearing */}
      <CollapsibleSection title={`Gearing  ${gearing.chainring}/${gearing.cog}`} defaultExpanded={false}>
        <View style={styles.gearingRow}>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Chainring</Text>
            <View style={styles.paramInputWrapper}>
              <TextInput
                style={styles.paramInput}
                value={gearing.chainring.toString()}
                onChangeText={(v) => { const n = parseInt(v); if (!isNaN(n)) setGearing({ chainring: n }); }}
                keyboardType="number-pad"
              />
            </View>
          </View>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Cog</Text>
            <View style={styles.paramInputWrapper}>
              <TextInput
                style={styles.paramInput}
                value={gearing.cog.toString()}
                onChangeText={(v) => { const n = parseInt(v); if (!isNaN(n)) setGearing({ cog: n }); }}
                keyboardType="number-pad"
              />
            </View>
          </View>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Wheel (mm)</Text>
            <View style={styles.paramInputWrapper}>
              <TextInput
                style={styles.paramInput}
                value={gearing.wheelCircMm.toString()}
                onChangeText={(v) => { const n = parseInt(v); if (!isNaN(n)) setGearing({ wheelCircMm: n }); }}
                keyboardType="number-pad"
              />
            </View>
          </View>
        </View>
        <Text style={styles.gearingRollout}>
          Rollout: {((gearing.chainring / gearing.cog) * (gearing.wheelCircMm / 1000)).toFixed(2)}m | Ratio: {(gearing.chainring / gearing.cog).toFixed(2)}
        </Text>
      </CollapsibleSection>

      {/* Rider Parameters */}
      <CollapsibleSection title="Rider Parameters" defaultExpanded={true}>
        <ParamRow
          label="Mass"
          value={params.mass_kg}
          unit="kg"
          onChangeText={(v) => updateParam('mass_kg', v)}
        />
        <ParamRow
          label="Critical Power"
          value={params.cp_W}
          unit="W"
          onChangeText={(v) => updateParam('cp_W', v)}
        />
        <ParamRow
          label="W'"
          value={params.wPrime_J}
          unit="J"
          onChangeText={(v) => updateParam('wPrime_J', v)}
        />
      </CollapsibleSection>

      {/* Kit Configuration */}
      <CollapsibleSection title="Kit Configuration" defaultExpanded={true}>
        <KitSelector
          configs={kitConfigs}
          selectedId={activeKitId}
          onSelect={(id) => setSelectedSimKitId(id)}
        />
      </CollapsibleSection>

      {/* Aero Parameters */}
      <CollapsibleSection title="Aero Parameters" defaultExpanded={true}>
        <OverridableParamRow
          label="CdA Seated"
          value={effectiveCdaSeated}
          sourceValue={activeKit.cdaSeated}
          unit="m²"
          isOverridden={cdaSeatedOverride !== null}
          onChangeValue={(num) => setCdaSeatedOverride(num)}
          onReset={() => setCdaSeatedOverride(null)}
        />
        <OverridableParamRow
          label="CdA Standing"
          value={effectiveCdaStanding}
          sourceValue={activeKit.cdaStanding}
          unit="m²"
          isOverridden={cdaStandingOverride !== null}
          onChangeValue={(num) => setCdaStandingOverride(num)}
          onReset={() => setCdaStandingOverride(null)}
        />

        {/* Override warning banner */}
        {hasCdaOverride && (
          <View style={styles.overrideWarning}>
            <Text style={styles.overrideWarningText}>
              CdA overridden from kit "{activeKit.name}"
            </Text>
            <TouchableOpacity
              onPress={() => { setCdaSeatedOverride(null); setCdaStandingOverride(null); }}
            >
              <Text style={styles.overrideWarningReset}>Reset All</Text>
            </TouchableOpacity>
          </View>
        )}

        <ParamRow
          label="Bend Factor"
          value={params.cda_bend_factor}
          unit=""
          onChangeText={(v) => updateParam('cda_bend_factor', v)}
        />
      </CollapsibleSection>

      {/* Position Profile */}
      <CollapsibleSection title="Position Profile">
        <Text style={styles.simPositionHint}>
          Override seated/standing per segment. Tap to toggle.
        </Text>
        <View style={styles.simSegmentList}>
          {TRACK_SEGMENTS.map((segment) => (
            <SimSegmentRow
              key={segment.id}
              label={segment.label}
              position={segment.locked ? 'seated' : (simSegmentPositions[segment.id] || 'seated')}
              onToggle={() => {
                const current = simSegmentPositions[segment.id] || 'seated';
                setSimSegmentPositions({
                  ...simSegmentPositions,
                  [segment.id]: current === 'seated' ? 'standing' : 'seated'
                });
              }}
              locked={segment.locked}
              isTimed={segment.startM >= 695}
            />
          ))}
        </View>
        <TouchableOpacity
          style={styles.resetPositionsButton}
          onPress={() => setSimSegmentPositions(
            TRACK_SEGMENTS.reduce((acc, seg) => ({ ...acc, [seg.id]: 'seated' }), {})
          )}
        >
          <Text style={styles.resetPositionsText}>Reset All to Seated</Text>
        </TouchableOpacity>
      </CollapsibleSection>

      {/* Environment Parameters */}
      <CollapsibleSection title="Environment">
        <ParamRow
          label="Air Density"
          value={params.rho}
          unit="kg/m³"
          onChangeText={(v) => updateParam('rho', v)}
        />
        <ParamRow
          label="Rolling Resistance"
          value={params.crr}
          unit=""
          onChangeText={(v) => updateParam('crr', v)}
        />
        <ParamRow
          label="Drivetrain Eff"
          value={params.drivetrain_eff}
          unit=""
          onChangeText={(v) => updateParam('drivetrain_eff', v)}
        />
      </CollapsibleSection>

      {/* Run Button */}
      <TouchableOpacity
        style={[styles.runButton, loading && styles.buttonDisabled]}
        onPress={runSimulation}
        disabled={loading || !powerProfile}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.runButtonText}>Run Simulation</Text>
        )}
      </TouchableOpacity>

      {/* Export to Dev button */}
      <TouchableOpacity
        style={styles.exportButton}
        onPress={exportToDev}
      >
        <Text style={styles.exportButtonText}>Export to Dev</Text>
      </TouchableOpacity>

      {/* Save Effort button */}
      {result && (
        <>
          {showRealTimeInput ? (
            <View style={styles.realTimePrompt}>
              <Text style={styles.realTimeLabel}>Official time (optional):</Text>
              <View style={styles.realTimeRow}>
                <TextInput
                  style={styles.realTimeInput}
                  value={realTimeInput}
                  onChangeText={setRealTimeInput}
                  placeholder="e.g. 10.456"
                  placeholderTextColor="#556b82"
                  keyboardType="decimal-pad"
                  autoFocus
                />
                <Text style={styles.realTimeUnit}>s</Text>
              </View>
              <View style={styles.realTimeActions}>
                <TouchableOpacity style={styles.realTimeSaveBtn} onPress={handleSaveConfirm}>
                  <Text style={styles.realTimeSaveBtnText}>Save</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.realTimeSkipBtn} onPress={handleSaveSkip}>
                  <Text style={styles.realTimeSkipBtnText}>Skip</Text>
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <TouchableOpacity
              style={[styles.saveButton, (saving || alreadySaved) && styles.buttonDisabled]}
              onPress={handleSavePress}
              disabled={saving || alreadySaved || !currentEffort}
            >
              {saving ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.saveButtonText}>
                  {alreadySaved ? 'Already Saved' : 'Save Effort'}
                </Text>
              )}
            </TouchableOpacity>
          )}
        </>
      )}

      {/* Error */}
      {error && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Key Metrics */}
          <View style={styles.resultsCard}>
            <Text style={styles.resultsTitle}>Results</Text>
            <View style={styles.metricsGrid}>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>
                  {result.splits_200.slice(0, effortType / 50).reduce((a, b) => a + b, 0).toFixed(3)}s
                </Text>
                <Text style={styles.metricLabel}>T_{effortType}</Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>{result.v_200_entry_kph.toFixed(1)}</Text>
                <Text style={styles.metricLabel}>Entry kph</Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>{result.v_200_exit_kph.toFixed(1)}</Text>
                <Text style={styles.metricLabel}>Exit kph</Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>{result.v_max_kph.toFixed(1)}</Text>
                <Text style={styles.metricLabel}>Max kph</Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>{Math.round(result.P_avg_sprint)}W</Text>
                <Text style={styles.metricLabel}>Avg Power</Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricValue}>{result.T_total.toFixed(2)}s</Text>
                <Text style={styles.metricLabel}>Total Time</Text>
              </View>
            </View>
          </View>

          {/* Speed Chart */}
          {getSpeedChartData() && (
            <View style={styles.chartCard}>
              <Text style={styles.chartTitle}>Speed Profile</Text>
              <LineChart
                data={getSpeedChartData()!}
                width={screenWidth - 32}
                height={180}
                chartConfig={{
                  backgroundColor: colors.bg1,
                  backgroundGradientFrom: colors.bg1,
                  backgroundGradientTo: colors.bg1,
                  color: (opacity = 1) => `rgba(77, 166, 255, ${opacity})`,
                  strokeWidth: 2,
                  propsForDots: { r: '0' },
                }}
                bezier
                withVerticalLabels={false}
                withHorizontalLabels={true}
                withDots={false}
                style={styles.chart}
              />
            </View>
          )}

          {/* Net Watts & CdA Chart - custom SVG with green/red AUC fill */}
          {netWattsData && (() => {
            const { netWatts, distances, cdaValues } = netWattsData;
            const chartW = screenWidth - 64;
            const chartH = 220;
            const padLeft = 40;
            const padRight = 8;
            const padTop = 10;
            const padBottom = 30;
            const plotW = chartW - padLeft - padRight;
            const plotH = chartH - padTop - padBottom;

            const minDist = distances[0];
            const maxDist = distances[distances.length - 1];
            const distRange = maxDist - minDist || 1;

            const maxVal = Math.max(...netWatts);
            const minVal = Math.min(...netWatts);
            const absMax = Math.max(Math.abs(maxVal), Math.abs(minVal), 1);
            // Symmetric Y range around zero
            const yMax = absMax * 1.1;
            const yMin = -absMax * 1.1;
            const yRange = yMax - yMin;

            const toX = (d: number) => padLeft + ((d - minDist) / distRange) * plotW;
            const toY = (w: number) => padTop + ((yMax - w) / yRange) * plotH;
            const zeroY = toY(0);

            // CdA line (scaled to chart)
            const minCda = Math.min(...cdaValues);
            const maxCda = Math.max(...cdaValues);
            const cdaRange = maxCda - minCda || 0.001;
            const cdaToY = (c: number) => padTop + plotH * 0.1 + ((maxCda - c) / cdaRange) * plotH * 0.8;

            // Build net watts line path
            let linePath = '';
            for (let i = 0; i < distances.length; i++) {
              const x = toX(distances[i]);
              const y = toY(netWatts[i]);
              linePath += i === 0 ? `M${x},${y}` : `L${x},${y}`;
            }

            // Build filled areas: green above zero, red below zero
            // Walk through points and create filled polygons between the line and the zero axis
            let greenPath = '';
            let redPath = '';

            for (let i = 0; i < distances.length - 1; i++) {
              const x1 = toX(distances[i]);
              const x2 = toX(distances[i + 1]);
              const y1 = netWatts[i];
              const y2 = netWatts[i + 1];
              const py1 = toY(y1);
              const py2 = toY(y2);

              if (y1 >= 0 && y2 >= 0) {
                // Both positive - green fill
                greenPath += `M${x1},${zeroY}L${x1},${py1}L${x2},${py2}L${x2},${zeroY}Z`;
              } else if (y1 <= 0 && y2 <= 0) {
                // Both negative - red fill
                redPath += `M${x1},${zeroY}L${x1},${py1}L${x2},${py2}L${x2},${zeroY}Z`;
              } else {
                // Crosses zero - split at crossing point
                const frac = Math.abs(y1) / (Math.abs(y1) + Math.abs(y2));
                const xCross = x1 + frac * (x2 - x1);
                if (y1 > 0) {
                  // Positive then negative
                  greenPath += `M${x1},${zeroY}L${x1},${py1}L${xCross},${zeroY}Z`;
                  redPath += `M${xCross},${zeroY}L${x2},${py2}L${x2},${zeroY}Z`;
                } else {
                  // Negative then positive
                  redPath += `M${x1},${zeroY}L${x1},${py1}L${xCross},${zeroY}Z`;
                  greenPath += `M${xCross},${zeroY}L${x2},${py2}L${x2},${zeroY}Z`;
                }
              }
            }

            // CdA line path
            let cdaPath = '';
            for (let i = 0; i < distances.length; i++) {
              const x = toX(distances[i]);
              const y = cdaToY(cdaValues[i]);
              cdaPath += i === 0 ? `M${x},${y}` : `L${x},${y}`;
            }

            // Y-axis tick values
            const yTicks = [];
            const tickStep = Math.ceil(absMax / 3 / 50) * 50;
            for (let v = -tickStep * 3; v <= tickStep * 3; v += tickStep) {
              if (v >= yMin && v <= yMax) yTicks.push(v);
            }

            // X-axis tick values
            const xTicks = [];
            const xStep = maxDist > 500 ? 200 : 100;
            for (let d = 0; d <= maxDist; d += xStep) {
              if (d >= minDist) xTicks.push(d);
            }

            return (
              <View style={styles.chartCard}>
                <Text style={styles.chartTitle}>Net Watts & CdA vs Distance</Text>
                <Text style={styles.chartSubtitle}>
                  Accelerative potential after aero, gravity, CRR, drivetrain
                </Text>
                <View style={styles.chartLegend}>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.success }]} />
                    <Text style={styles.legendText}>Accel (+W)</Text>
                  </View>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.danger }]} />
                    <Text style={styles.legendText}>Decel (-W)</Text>
                  </View>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.warning }]} />
                    <Text style={styles.legendText}>CdA ({minCda.toFixed(3)}–{maxCda.toFixed(3)})</Text>
                  </View>
                </View>
                <Svg width={chartW} height={chartH}>
                  {/* Green fill (acceleration) */}
                  {greenPath ? <Path d={greenPath} fill="rgba(74, 222, 128, 0.35)" /> : null}
                  {/* Red fill (deceleration) */}
                  {redPath ? <Path d={redPath} fill="rgba(239, 68, 68, 0.35)" /> : null}
                  {/* Zero line */}
                  <Line x1={padLeft} y1={zeroY} x2={padLeft + plotW} y2={zeroY} stroke="#5a7a96" strokeWidth={1} strokeDasharray="4,4" />
                  {/* Y-axis grid lines and labels */}
                  {yTicks.map((v) => (
                    <React.Fragment key={`y${v}`}>
                      {v !== 0 && (
                        <Line x1={padLeft} y1={toY(v)} x2={padLeft + plotW} y2={toY(v)} stroke="#1a3a5c" strokeWidth={0.5} />
                      )}
                      <SvgText x={padLeft - 4} y={toY(v) + 3} fontSize={9} fill="#5a7a96" textAnchor="end">
                        {v}
                      </SvgText>
                    </React.Fragment>
                  ))}
                  {/* X-axis labels */}
                  {xTicks.map((d) => (
                    <SvgText key={`x${d}`} x={toX(d)} y={chartH - 4} fontSize={9} fill="#5a7a96" textAnchor="middle">
                      {d}m
                    </SvgText>
                  ))}
                  {/* Timed section start vertical line at 695m */}
                  {695 >= minDist && 695 <= maxDist && (
                    <>
                      <Line x1={toX(695)} y1={padTop} x2={toX(695)} y2={padTop + plotH} stroke="#fbbf24" strokeWidth={1} strokeDasharray="4,3" opacity={0.8} />
                      <SvgText x={toX(695) + 3} y={padTop + 10} fontSize={8} fill="#fbbf24" opacity={0.8}>
                        200m
                      </SvgText>
                    </>
                  )}
                  {/* CdA line */}
                  <Path d={cdaPath} fill="none" stroke="#fbbf24" strokeWidth={1.5} opacity={0.7} />
                  {/* Net watts line */}
                  <Path d={linePath} fill="none" stroke="#8aa4c0" strokeWidth={1.5} />
                </Svg>
              </View>
            );
          })()}

          {/* W/CdA vs Breakeven chart - custom SVG with green/red AUC fill */}
          {wCdaData && (() => {
            const { actualWCdA, breakevenWCdA, distances: wDists } = wCdaData;
            const chartW = screenWidth - 64;
            const chartH = 220;
            const padLeft = 48;
            const padRight = 8;
            const padTop = 10;
            const padBottom = 30;
            const plotW = chartW - padLeft - padRight;
            const plotH = chartH - padTop - padBottom;

            const minDist = wDists[0];
            const maxDist = wDists[wDists.length - 1];
            const distRange = maxDist - minDist || 1;

            const allVals = [...actualWCdA, ...breakevenWCdA];
            const yMax = Math.max(...allVals) * 1.1;
            const yMin = 0;
            const yRange = yMax - yMin || 1;

            const toX = (d: number) => padLeft + ((d - minDist) / distRange) * plotW;
            const toY = (w: number) => padTop + ((yMax - w) / yRange) * plotH;

            // Build actual W/CdA line path
            let actualPath = '';
            for (let i = 0; i < wDists.length; i++) {
              const x = toX(wDists[i]);
              const y = toY(actualWCdA[i]);
              actualPath += i === 0 ? `M${x},${y}` : `L${x},${y}`;
            }

            // Build breakeven W/CdA line path
            let breakevenPath = '';
            for (let i = 0; i < wDists.length; i++) {
              const x = toX(wDists[i]);
              const y = toY(breakevenWCdA[i]);
              breakevenPath += i === 0 ? `M${x},${y}` : `L${x},${y}`;
            }

            // Build green/red fill between actual and breakeven
            let greenFill = '';
            let redFill = '';
            for (let i = 0; i < wDists.length - 1; i++) {
              const x1 = toX(wDists[i]);
              const x2 = toX(wDists[i + 1]);
              const a1 = actualWCdA[i], a2 = actualWCdA[i + 1];
              const b1 = breakevenWCdA[i], b2 = breakevenWCdA[i + 1];
              const pa1 = toY(a1), pa2 = toY(a2);
              const pb1 = toY(b1), pb2 = toY(b2);

              const diff1 = a1 - b1;
              const diff2 = a2 - b2;

              if (diff1 >= 0 && diff2 >= 0) {
                greenFill += `M${x1},${pb1}L${x1},${pa1}L${x2},${pa2}L${x2},${pb2}Z`;
              } else if (diff1 <= 0 && diff2 <= 0) {
                redFill += `M${x1},${pa1}L${x1},${pb1}L${x2},${pb2}L${x2},${pa2}Z`;
              } else {
                // Crosses — split at intersection
                const frac = Math.abs(diff1) / (Math.abs(diff1) + Math.abs(diff2));
                const xC = x1 + frac * (x2 - x1);
                const yC = toY(a1 + frac * (a2 - a1));
                if (diff1 > 0) {
                  greenFill += `M${x1},${pb1}L${x1},${pa1}L${xC},${yC}Z`;
                  redFill += `M${xC},${yC}L${x2},${pa2}L${x2},${pb2}Z`;
                } else {
                  redFill += `M${x1},${pa1}L${x1},${pb1}L${xC},${yC}Z`;
                  greenFill += `M${xC},${yC}L${x2},${pb2}L${x2},${pa2}Z`;
                }
              }
            }

            // Y-axis ticks
            const yTicks: number[] = [];
            const tickStep = Math.ceil(yMax / 5 / 500) * 500 || 500;
            for (let v = 0; v <= yMax; v += tickStep) {
              yTicks.push(v);
            }

            // X-axis ticks
            const xTicks: number[] = [];
            const xStep = maxDist > 500 ? 200 : 100;
            for (let d = 0; d <= maxDist; d += xStep) {
              if (d >= minDist) xTicks.push(d);
            }

            // 200m timed section start at 695m
            const timedStartX = toX(695);
            const timedStartVisible = 695 >= minDist && 695 <= maxDist;

            return (
              <View style={styles.chartCard}>
                <Text style={styles.chartTitle}>W/CdA Analysis | Best Time: {result.T_200.toFixed(3)}s</Text>
                <Text style={styles.chartSubtitle}>
                  Net watts (after CRR, gravity, drivetrain) per CdA vs aero breakeven
                </Text>
                <View style={styles.chartLegend}>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.success }]} />
                    <Text style={styles.legendText}>Above (accel)</Text>
                  </View>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.danger }]} />
                    <Text style={styles.legendText}>Below (decel)</Text>
                  </View>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.textSecondary }]} />
                    <Text style={styles.legendText}>Actual W/CdA</Text>
                  </View>
                  <View style={styles.legendItem}>
                    <View style={[styles.legendDot, { backgroundColor: colors.warning }]} />
                    <Text style={styles.legendText}>Breakeven</Text>
                  </View>
                </View>
                <Svg width={chartW} height={chartH}>
                  {/* Green fill (above breakeven = accelerating) */}
                  {greenFill ? <Path d={greenFill} fill="rgba(74, 222, 128, 0.35)" /> : null}
                  {/* Red fill (below breakeven = decelerating) */}
                  {redFill ? <Path d={redFill} fill="rgba(239, 68, 68, 0.35)" /> : null}
                  {/* Y-axis grid lines and labels */}
                  {yTicks.map((v) => (
                    <React.Fragment key={`wcda-y${v}`}>
                      <Line x1={padLeft} y1={toY(v)} x2={padLeft + plotW} y2={toY(v)} stroke="#1a3a5c" strokeWidth={0.5} />
                      <SvgText x={padLeft - 4} y={toY(v) + 3} fontSize={9} fill="#5a7a96" textAnchor="end">
                        {v}
                      </SvgText>
                    </React.Fragment>
                  ))}
                  {/* X-axis labels */}
                  {xTicks.map((d) => (
                    <SvgText key={`wcda-x${d}`} x={toX(d)} y={chartH - 4} fontSize={9} fill="#5a7a96" textAnchor="middle">
                      {d}m
                    </SvgText>
                  ))}
                  {/* Timed section start vertical line at 695m */}
                  {timedStartVisible && (
                    <>
                      <Line x1={timedStartX} y1={padTop} x2={timedStartX} y2={padTop + plotH} stroke="#fbbf24" strokeWidth={1} strokeDasharray="4,3" opacity={0.8} />
                      <SvgText x={timedStartX + 3} y={padTop + 10} fontSize={8} fill="#fbbf24" opacity={0.8}>
                        200m
                      </SvgText>
                    </>
                  )}
                  {/* Breakeven W/CdA line (dashed) */}
                  <Path d={breakevenPath} fill="none" stroke="#fbbf24" strokeWidth={1.5} strokeDasharray="6,3" />
                  {/* Actual W/CdA line */}
                  <Path d={actualPath} fill="none" stroke="#8aa4c0" strokeWidth={1.5} />
                </Svg>
              </View>
            );
          })()}

          {/* Splits Table (Collapsible, default collapsed) */}
          <CollapsibleSection title={`F${effortType} Splits (50m)`} defaultExpanded={false}>
            <View style={styles.splitsTable}>
              <View style={styles.splitsHeader}>
                <Text style={styles.splitHeaderText}>Segment</Text>
                <Text style={styles.splitHeaderText}>Time</Text>
              </View>
              {/* Only show splits relevant to the effort type */}
              {result.splits_200.slice(0, effortType / 50).map((split, index) => (
                <View key={index} style={styles.splitRow}>
                  <Text style={styles.splitSegment}>{index * 50}m - {(index + 1) * 50}m</Text>
                  <Text style={styles.splitTime}>{split.toFixed(3)}s</Text>
                </View>
              ))}
              <View style={[styles.splitRow, styles.splitTotal]}>
                <Text style={styles.splitSegment}>T_{effortType}</Text>
                <Text style={styles.splitTime}>
                  {result.splits_200.slice(0, effortType / 50).reduce((a, b) => a + b, 0).toFixed(3)}s
                </Text>
              </View>
            </View>
          </CollapsibleSection>

          {/* Breakeven CdA (Collapsible, default collapsed) */}
          <CollapsibleSection title="Breakeven CdA" defaultExpanded={false}>
            <Text style={styles.breakevenInfo}>
              Enter your real entry speed and/or timed section time to compute the implied CdA values.
            </Text>

            {/* Mode Toggle */}
            <View style={styles.modeToggleRow}>
              <TouchableOpacity
                style={[styles.modeToggleButton, !dualMode && styles.modeToggleButtonActive]}
                onPress={() => { setDualMode(false); setDualBreakevenResult(null); }}
              >
                <Text style={[styles.modeToggleText, !dualMode && styles.modeToggleTextActive]}>
                  Single CdA
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modeToggleButton, dualMode && styles.modeToggleButtonActive]}
                onPress={() => { setDualMode(true); setBreakevenResult(null); }}
              >
                <Text style={[styles.modeToggleText, dualMode && styles.modeToggleTextActive]}>
                  Dual CdA
                </Text>
              </TouchableOpacity>
            </View>

            {dualMode && (
              <Text style={styles.dualModeInfo}>
                Dual mode solves for BOTH seated and standing CdA using timed section (seated) and entry speed (with position profile).
              </Text>
            )}

            {/* Target Entry Speed Input */}
            <View style={styles.breakevenInputRow}>
              <Text style={styles.breakevenInputLabel}>Target Entry Speed</Text>
              <View style={styles.breakevenInputWrapper}>
                <TextInput
                  style={styles.breakevenInput}
                  value={targetEntrySpeedKph}
                  onChangeText={setTargetEntrySpeedKph}
                  placeholder="e.g. 65.5"
                  placeholderTextColor="#5a7a9a"
                  keyboardType="decimal-pad"
                />
                <Text style={styles.breakevenInputUnit}>kph</Text>
              </View>
            </View>

            {/* Target Timed Section Input */}
            <View style={styles.breakevenInputRow}>
              <Text style={styles.breakevenInputLabel}>Target T_{effortType}</Text>
              <View style={styles.breakevenInputWrapper}>
                <TextInput
                  style={styles.breakevenInput}
                  value={targetTimedSectionS}
                  onChangeText={setTargetTimedSectionS}
                  placeholder="e.g. 10.5"
                  placeholderTextColor="#5a7a9a"
                  keyboardType="decimal-pad"
                />
                <Text style={styles.breakevenInputUnit}>s</Text>
              </View>
            </View>

            {/* Compute Button */}
            <TouchableOpacity
              style={[styles.breakevenButton, breakevenLoading && styles.buttonDisabled]}
              onPress={dualMode ? computeDualBreakevenCdA : computeBreakevenCdA}
              disabled={breakevenLoading || (dualMode ? (!targetEntrySpeedKph || !targetTimedSectionS) : (!targetEntrySpeedKph && !targetTimedSectionS))}
            >
              {breakevenLoading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.breakevenButtonText}>
                  {dualMode ? 'Compute Dual CdA' : 'Compute Breakeven CdA'}
                </Text>
              )}
            </TouchableOpacity>

            {/* Single Mode Results */}
            {!dualMode && breakevenResult && (
              <View style={styles.breakevenResults}>
                {/* Entry Speed Result (Buildup Phase) */}
                {breakevenResult.breakeven_cda_entry !== null && (
                  <View style={[
                    styles.breakevenResultCard,
                    breakevenResult.entry_speed_converged ? styles.breakevenResultConverged : styles.breakevenResultNotConverged
                  ]}>
                    <Text style={styles.breakevenResultLabel}>Implied CdA (Buildup 0-695m)</Text>
                    <Text style={styles.breakevenResultValue}>
                      {breakevenResult.breakeven_cda_entry.toFixed(4)} m²
                    </Text>
                    <Text style={styles.breakevenResultStatus}>
                      {breakevenResult.entry_speed_converged ? '✓ Converged' : '⚠ Not converged'}
                    </Text>
                    <Text style={styles.breakevenResultDelta}>
                      {((breakevenResult.breakeven_cda_entry - effectiveCdaSeated) * 10000).toFixed(0)} cm² vs base ({effectiveCdaSeated.toFixed(3)})
                    </Text>
                  </View>
                )}

                {/* Timed Section Result */}
                {breakevenResult.breakeven_cda_time !== null && (
                  <View style={[
                    styles.breakevenResultCard,
                    breakevenResult.time_converged ? styles.breakevenResultConvergedPurple : styles.breakevenResultNotConvergedPurple
                  ]}>
                    <Text style={styles.breakevenResultLabelPurple}>Implied CdA (Timed 695m+)</Text>
                    <Text style={styles.breakevenResultValuePurple}>
                      {breakevenResult.breakeven_cda_time.toFixed(4)} m²
                    </Text>
                    <Text style={styles.breakevenResultStatusPurple}>
                      {breakevenResult.time_converged ? '✓ Converged' : '⚠ Not converged'}
                    </Text>
                    <Text style={styles.breakevenResultDeltaPurple}>
                      {((breakevenResult.breakeven_cda_time - effectiveCdaSeated) * 10000).toFixed(0)} cm² vs base ({effectiveCdaSeated.toFixed(3)})
                    </Text>
                  </View>
                )}
              </View>
            )}

            {/* Dual Mode Results */}
            {dualMode && dualBreakevenResult && (
              <View style={styles.breakevenResults}>
                <Text style={styles.dualModeLabel}>
                  Mode: {dualBreakevenResult.mode === 'seated_vs_standing' ? 'Seated vs Standing' : 'Buildup vs Timed'}
                </Text>

                {/* Seated / Timed CdA Result */}
                <View style={[
                  styles.breakevenResultCard,
                  dualBreakevenResult.seated_converged ? styles.breakevenResultConvergedPurple : styles.breakevenResultNotConvergedPurple
                ]}>
                  <Text style={styles.breakevenResultLabelPurple}>
                    {dualBreakevenResult.mode === 'buildup_vs_timed' ? 'Timed Section CdA' : 'Seated CdA'}
                  </Text>
                  <Text style={styles.breakevenResultValuePurple}>
                    {(dualBreakevenResult.solved_cda_seated ?? 0).toFixed(4)} m²
                  </Text>
                  <Text style={styles.breakevenResultStatusPurple}>
                    {dualBreakevenResult.seated_converged ? '✓ Converged' : '⚠ Not converged'}
                  </Text>
                  <Text style={styles.breakevenResultDeltaPurple}>
                    {(((dualBreakevenResult.solved_cda_seated ?? 0) - effectiveCdaSeated) * 10000).toFixed(0)} cm² vs base ({effectiveCdaSeated.toFixed(3)})
                  </Text>
                </View>

                {/* Standing / Buildup CdA Result */}
                <View style={[
                  styles.breakevenResultCard,
                  dualBreakevenResult.standing_converged ? styles.breakevenResultConverged : styles.breakevenResultNotConverged
                ]}>
                  <Text style={styles.breakevenResultLabel}>
                    {dualBreakevenResult.mode === 'buildup_vs_timed' ? 'Buildup CdA' : 'Standing CdA'}
                  </Text>
                  <Text style={styles.breakevenResultValue}>
                    {(dualBreakevenResult.solved_cda_standing ?? 0).toFixed(4)} m²
                  </Text>
                  <Text style={styles.breakevenResultStatus}>
                    {dualBreakevenResult.standing_converged ? '✓ Converged' : '⚠ Not converged'}
                  </Text>
                  <Text style={styles.breakevenResultDelta}>
                    {(((dualBreakevenResult.solved_cda_standing ?? 0) - effectiveCdaStanding) * 10000).toFixed(0)} cm² vs base ({effectiveCdaStanding.toFixed(3)})
                  </Text>
                </View>
              </View>
            )}
          </CollapsibleSection>
        </>
      )}

      {/* Action Buttons */}
      <View style={styles.actionButtonRow}>
        <TouchableOpacity
          style={styles.sensitivityButton}
          onPress={() => router.push('/(simulate)/sensitivity')}
        >
          <Text style={styles.sensitivityButtonText}>Sensitivity</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.optimizeButton}
          onPress={() => router.push('/(simulate)/optimizer')}
        >
          <Text style={styles.optimizeButtonText}>Optimize</Text>
        </TouchableOpacity>
      </View>

      {/* Bottom padding */}
      <View style={styles.bottomPadding} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
  },
  returnButton: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  returnButtonText: {
    color: colors.accent,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  statusBanner: {
    padding: 12,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  statusText: {
    color: colors.success,
    fontSize: 13,
    textAlign: 'center',
  },
  statusTextWarn: {
    color: colors.warning,
    fontSize: 13,
    textAlign: 'center',
  },
  trackOptionsRow: {
    flexDirection: 'row',
    gap: 8,
  },
  trackOption: {
    flex: 1,
    padding: 10,
    borderRadius: 8,
    backgroundColor: colors.bg0,
    alignItems: 'center',
  },
  trackOptionSelected: {
    backgroundColor: colors.accent,
  },
  trackOptionName: {
    color: colors.textSecondary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  trackOptionNameSelected: {
    color: colors.textPrimary,
  },
  gearingRow: {
    flexDirection: 'row',
    gap: 8,
  },
  gearingInput: {
    flex: 1,
  },
  gearingLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 4,
  },
  gearingRollout: {
    color: colors.textSecondary,
    fontSize: 12,
    marginTop: 8,
    textAlign: 'center',
  },
  section: {
    backgroundColor: colors.bg1,
    marginTop: 8,
    marginHorizontal: 8,
    borderRadius: 12,
    overflow: 'hidden',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  expandIcon: {
    color: colors.textSecondary,
    fontSize: 20,
    fontFamily: fonts.sansBold,
  },
  sectionContent: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  paramRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  paramLabel: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  paramInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  paramInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    fontSize: 14,
    minWidth: 80,
    textAlign: 'right',
  },
  paramUnit: {
    color: colors.textSecondary,
    fontSize: 12,
    marginLeft: 8,
    minWidth: 40,
  },
  runButton: {
    backgroundColor: colors.success,
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  runButtonText: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  exportButton: {
    backgroundColor: colors.bg1,
    marginHorizontal: 16,
    marginTop: 8,
    padding: 12,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  exportButtonText: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  errorBanner: {
    backgroundColor: '#7f1d1d',
    marginHorizontal: 16,
    marginTop: 12,
    padding: 12,
    borderRadius: 8,
  },
  errorText: {
    color: '#fca5a5',
    fontSize: 14,
    textAlign: 'center',
  },
  resultsCard: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 16,
    borderRadius: 12,
    padding: 16,
  },
  resultsTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    marginBottom: 16,
  },
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },
  metricItem: {
    width: '30%',
    alignItems: 'center',
    marginBottom: 16,
  },
  metricValue: {
    color: colors.success,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  metricLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginTop: 4,
  },
  chartCard: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 8,
    borderRadius: 12,
    padding: 16,
  },
  chartTitle: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 12,
  },
  chart: {
    borderRadius: 8,
    marginLeft: -16,
  },
  chartSubtitle: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 8,
  },
  chartLegend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 8,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  splitsTable: {
    backgroundColor: colors.bg0,
    borderRadius: 8,
    overflow: 'hidden',
  },
  splitsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 12,
    backgroundColor: colors.border,
  },
  splitHeaderText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  splitRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.bg1,
  },
  splitTotal: {
    backgroundColor: colors.bg1,
    borderBottomWidth: 0,
  },
  splitSegment: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  splitTime: {
    color: colors.warning,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  breakevenInfo: {
    color: colors.textSecondary,
    fontSize: 13,
    marginBottom: 16,
  },
  breakevenInputRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  breakevenInputLabel: {
    color: colors.textSecondary,
    fontSize: 14,
    flex: 1,
  },
  breakevenInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  breakevenInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    fontSize: 14,
    minWidth: 80,
    textAlign: 'right',
  },
  breakevenInputUnit: {
    color: colors.textSecondary,
    fontSize: 12,
    marginLeft: 8,
    minWidth: 30,
  },
  breakevenButton: {
    backgroundColor: '#6366f1',
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 16,
  },
  breakevenButtonText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  breakevenResults: {
    gap: 12,
  },
  breakevenResultCard: {
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
  },
  breakevenResultConverged: {
    backgroundColor: '#422006',
  },
  breakevenResultNotConverged: {
    backgroundColor: '#2d1f06',
    borderWidth: 1,
    borderColor: '#854d0e',
  },
  breakevenResultConvergedPurple: {
    backgroundColor: '#2e1065',
  },
  breakevenResultNotConvergedPurple: {
    backgroundColor: '#1e0a3e',
    borderWidth: 1,
    borderColor: '#7c3aed',
  },
  breakevenResultLabel: {
    color: colors.warning,
    fontSize: 11,
    marginBottom: 4,
  },
  breakevenResultValue: {
    color: '#fcd34d',
    fontSize: 20,
    fontFamily: fonts.sansBold,
    marginBottom: 4,
  },
  breakevenResultStatus: {
    color: '#d97706',
    fontSize: 11,
    marginBottom: 4,
  },
  breakevenResultDelta: {
    color: '#b45309',
    fontSize: 11,
  },
  breakevenResultLabelPurple: {
    color: '#a78bfa',
    fontSize: 11,
    marginBottom: 4,
  },
  breakevenResultValuePurple: {
    color: '#c4b5fd',
    fontSize: 20,
    fontFamily: fonts.sansBold,
    marginBottom: 4,
  },
  breakevenResultStatusPurple: {
    color: '#8b5cf6',
    fontSize: 11,
    marginBottom: 4,
  },
  breakevenResultDeltaPurple: {
    color: '#7c3aed',
    fontSize: 11,
  },
  modeToggleRow: {
    flexDirection: 'row',
    marginBottom: 16,
    borderRadius: 8,
    overflow: 'hidden',
  },
  modeToggleButton: {
    flex: 1,
    paddingVertical: 10,
    backgroundColor: colors.bg0,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  modeToggleButtonActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  modeToggleText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  modeToggleTextActive: {
    color: colors.textPrimary,
  },
  dualModeInfo: {
    color: '#6366f1',
    fontSize: 12,
    marginBottom: 16,
    fontStyle: 'italic',
  },
  dualModeLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 12,
    textAlign: 'center',
  },
  actionButtonRow: {
    flexDirection: 'row' as const,
    marginHorizontal: 16,
    marginTop: 16,
    gap: 10,
  },
  sensitivityButton: {
    flex: 1,
    backgroundColor: colors.bg1,
    borderWidth: 1,
    borderColor: colors.borderAccent,
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center' as const,
  },
  sensitivityButtonText: {
    color: colors.textSecondary,
    fontSize: 15,
    fontFamily: fonts.sansSemiBold as const,
    letterSpacing: 0.5,
  },
  optimizeButton: {
    flex: 1,
    backgroundColor: colors.accent,
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center' as const,
  },
  optimizeButtonText: {
    color: colors.bg0,
    fontSize: 15,
    fontFamily: fonts.sansBold as const,
    letterSpacing: 0.5,
  },
  bottomPadding: {
    height: 40,
  },
  // Kit selector styles for simulation page
  kitSelectorContainer: {
    gap: 6,
    marginBottom: 12,
  },
  kitSelectorItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.bg0,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  kitSelectorItemSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.bg2,
  },
  kitSelectorItemLeft: {
    flex: 1,
    marginRight: 12,
  },
  kitSelectorNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  kitSelectorName: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  kitSelectorNameSelected: {
    color: colors.textPrimary,
  },
  kitSelectorDefault: {
    color: colors.accent,
    fontSize: 11,
  },
  kitSelectorDesc: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: 2,
  },
  kitSelectorCda: {
    color: colors.textMuted,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
    fontVariant: ['tabular-nums'],
  },
  kitSelectorCdaSelected: {
    color: colors.success,
  },
  activeKitSummary: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.bg0,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
  },
  activeKitLabel: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  activeKitCda: {
    color: colors.success,
    fontSize: 14,
    fontFamily: fonts.sansBold,
    fontVariant: ['tabular-nums'],
  },
  // CdA override styles
  paramLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flex: 1,
  },
  paramLabelOverridden: {
    color: colors.warning,
  },
  paramInputOverridden: {
    borderWidth: 1,
    borderColor: colors.warning,
  },
  resetOverrideButton: {
    backgroundColor: '#422006',
    paddingVertical: 2,
    paddingHorizontal: 8,
    borderRadius: 4,
  },
  resetOverrideText: {
    color: colors.warning,
    fontSize: 10,
    fontFamily: fonts.sansSemiBold,
  },
  overrideWarning: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#422006',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    marginBottom: 12,
  },
  overrideWarningText: {
    color: colors.warning,
    fontSize: 11,
    flex: 1,
  },
  overrideWarningReset: {
    color: '#fcd34d',
    fontSize: 11,
    fontFamily: fonts.sansBold,
    marginLeft: 8,
  },
  // Position section styles for simulation page
  simPositionHint: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 12,
    fontStyle: 'italic',
  },
  simSegmentList: {
    marginBottom: 12,
  },
  simSegmentRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: colors.bg0,
    borderRadius: 8,
    marginBottom: 8,
  },
  simSegmentRowTimed: {
    backgroundColor: '#1a3a2e',
    borderLeftWidth: 3,
    borderLeftColor: colors.success,
  },
  simSegmentRowLocked: {
    opacity: 0.7,
  },
  simSegmentLabel: {
    color: colors.textPrimary,
    fontSize: 13,
    flex: 1,
  },
  simSegmentLabelTimed: {
    color: colors.success,
  },
  simSegmentLabelLocked: {
    color: colors.textMuted,
  },
  simSegmentToggle: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    minWidth: 80,
    alignItems: 'center',
  },
  simSegmentToggleSeated: {
    backgroundColor: colors.seated,
  },
  simSegmentToggleStanding: {
    backgroundColor: colors.standing,
  },
  simSegmentToggleLocked: {
    backgroundColor: colors.bg3,
  },
  simSegmentToggleText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  simSegmentToggleTextLocked: {
    color: colors.textMuted,
  },
  resetPositionsButton: {
    backgroundColor: colors.bg3,
    paddingVertical: 10,
    borderRadius: 6,
    alignItems: 'center',
  },
  resetPositionsText: {
    color: colors.textMuted,
    fontSize: 12,
  },
  saveButton: {
    backgroundColor: colors.accentDim,
    paddingVertical: 14,
    borderRadius: 8,
    marginHorizontal: 16,
    marginTop: 8,
    alignItems: 'center',
  },
  saveButtonText: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansBold,
  },
  realTimePrompt: {
    marginHorizontal: 16,
    marginTop: 8,
    backgroundColor: colors.bg1,
    borderRadius: 8,
    padding: 14,
  },
  realTimeLabel: {
    color: colors.textSecondary,
    fontSize: 13,
    marginBottom: 8,
  },
  realTimeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  realTimeInput: {
    flex: 1,
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    padding: 10,
    borderRadius: 6,
    fontSize: 16,
  },
  realTimeUnit: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  realTimeActions: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 10,
  },
  realTimeSaveBtn: {
    flex: 1,
    backgroundColor: colors.accentDim,
    paddingVertical: 10,
    borderRadius: 6,
    alignItems: 'center',
  },
  realTimeSaveBtnText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  realTimeSkipBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 6,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.textMuted,
  },
  realTimeSkipBtnText: {
    color: colors.textSecondary,
    fontSize: 14,
  },
});

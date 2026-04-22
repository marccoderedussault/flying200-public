import { colors, fonts, spacing } from '../../theme';
import React, { useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  TextInput,
  Dimensions,
} from 'react-native';
import { useRouter } from 'expo-router';
import Slider from '@react-native-community/slider';
import { LineChart, BarChart } from 'react-native-chart-kit';
import {
  useAppStore,
  TRACK_SEGMENTS,
  ATHLETE_CURVE_DURATIONS,
  calculateSeatedFromStanding,
} from '../../store/simulationStore';
import type { PowerCurvePoint, OptimizerMethod } from '../../store/simulationStore';
import {
  athletePowerApi,
  optimizerApi,
  type EnergyBudgetResult,
  type PowerRedistributionResult,
  type OptimizerSegment,
  type PowerAggregationMethod,
} from '../../api/client';
import type { StravaStreamRecord } from '../../api/client';

// Compute mean maximal power (MMP) curve from power records
// For each target duration, finds the max rolling average power over that window
function computePowerCurve(records: StravaStreamRecord[]): { duration_s: number; power_W: number }[] {
  const powers = records.map(r => r.power_W ?? 0);
  const n = powers.length;
  if (n === 0) return [];

  const result: { duration_s: number; power_W: number }[] = [];
  for (const dur of ATHLETE_CURVE_DURATIONS) {
    if (dur > n) break; // not enough data for this duration
    let maxAvg = 0;
    // Sliding window of size dur
    let windowSum = 0;
    for (let i = 0; i < dur; i++) windowSum += powers[i];
    maxAvg = windowSum / dur;
    for (let i = dur; i < n; i++) {
      windowSum += powers[i] - powers[i - dur];
      const avg = windowSum / dur;
      if (avg > maxAvg) maxAvg = avg;
    }
    if (maxAvg > 0) {
      result.push({ duration_s: dur, power_W: Math.round(maxAvg) });
    }
  }
  return result;
}

// Helper function to get CdA for a given distance based on segment positions
function getCdAForDistance(
  distanceM: number,
  segmentPositions: Record<string, 'seated' | 'standing'>,
  cdaSeated: number,
  cdaStanding: number
): number {
  for (const segment of TRACK_SEGMENTS) {
    if (distanceM >= segment.startM && distanceM <= segment.endM) {
      if (segment.locked) {
        return cdaSeated;
      }
      const position = segmentPositions[segment.id] || 'seated';
      return position === 'standing' ? cdaStanding : cdaSeated;
    }
  }
  return cdaSeated;
}

// Default track trajectory (simplified)
const DEFAULT_TRACK_TRAJECTORY = [
  { s_m: 0, y_m: 2.5 }, { s_m: 50, y_m: 2.5 }, { s_m: 100, y_m: 4.64 },
  { s_m: 150, y_m: 7.25 }, { s_m: 200, y_m: 5.88 }, { s_m: 250, y_m: 7.13 },
  { s_m: 300, y_m: 7.02 }, { s_m: 350, y_m: 6.5 }, { s_m: 400, y_m: 7.5 },
  { s_m: 450, y_m: 7.5 }, { s_m: 500, y_m: 7.5 }, { s_m: 550, y_m: 7.5 },
  { s_m: 600, y_m: 7.5 }, { s_m: 650, y_m: 6.0 }, { s_m: 695, y_m: 0.25 },
  { s_m: 750, y_m: 0.05 }, { s_m: 800, y_m: 0.6 }, { s_m: 850, y_m: -0.1 },
  { s_m: 895, y_m: 0.0 },
];

interface CollapsibleSectionProps {
  title: string;
  defaultExpanded?: boolean;
  children: React.ReactNode;
  badge?: string;
}

function CollapsibleSection({ title, defaultExpanded = false, children, badge }: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <View style={styles.section}>
      <TouchableOpacity style={styles.sectionHeader} onPress={() => setExpanded(!expanded)}>
        <View style={styles.sectionTitleRow}>
          <Text style={styles.sectionTitle}>{title}</Text>
          {badge && <View style={styles.badge}><Text style={styles.badgeText}>{badge}</Text></View>}
        </View>
        <Text style={styles.expandIcon}>{expanded ? '−' : '+'}</Text>
      </TouchableOpacity>
      {expanded && <View style={styles.sectionContent}>{children}</View>}
    </View>
  );
}

// Editable power value row
interface PowerValueRowProps {
  duration: number;
  standingW: number;
  seatedW: number;
  onChangeStanding: (value: number) => void;
}

function PowerValueRow({ duration, standingW, seatedW, onChangeStanding }: PowerValueRowProps) {
  const [localValue, setLocalValue] = useState(standingW > 0 ? standingW.toString() : '');

  const handleBlur = () => {
    const num = parseInt(localValue);
    if (!isNaN(num) && num >= 0) {
      onChangeStanding(num);
    } else {
      setLocalValue(standingW > 0 ? standingW.toString() : '');
    }
  };

  // Sync with external changes
  React.useEffect(() => {
    setLocalValue(standingW > 0 ? standingW.toString() : '');
  }, [standingW]);

  return (
    <View style={styles.powerValueRow}>
      <Text style={styles.powerDuration}>{duration}s</Text>
      <TextInput
        style={styles.powerInput}
        value={localValue}
        onChangeText={setLocalValue}
        onBlur={handleBlur}
        keyboardType="number-pad"
        placeholder="W"
        placeholderTextColor="#5a7a9a"
      />
      <Text style={styles.powerSeated}>{seatedW > 0 ? `${seatedW}W` : '-'}</Text>
    </View>
  );
}

export default function OptimizerScreen() {
  const router = useRouter();
  const {
    params,
    powerProfile,
    powerProfileSummary,
    segmentPositions,
    stravaSessionId,
    clearStravaSession,
    athletePowerCurve,
    stravaPowerCurve,
    seatedDiscount,
    setAthletePowerValue,
    setSeatedDiscount,
    importAthleteCurveFromStrava,
    resetAthleteCurveToStrava,
    clearAthleteCurve,
    lastSimulationT200,
    lastSimulationParams,
    lastSimulationProfile,
    lastSimulationEffortType,
    lastSimulationKitConfig,
    currentActivity,
    detectedEfforts,
    selectedEffortIndex,
    optimizerMethod,
    setOptimizerMethod,
    gravityAwarePosition,
    setGravityAwarePosition,
  } = useAppStore();

  // Loading states
  const [loadingAthleteCurve, setLoadingAthleteCurve] = useState(false);

  // Optimizer state
  const [optimizerType, setOptimizerType] = useState<'energy' | 'redistribution'>('energy');
  const [optimizing, setOptimizing] = useState(false);
  const [energyResult, setEnergyResult] = useState<EnergyBudgetResult | null>(null);
  const [redistributionResult, setRedistributionResult] = useState<PowerRedistributionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedTime, setElapsedTime] = useState(0);

  // Abort controller for cancelling optimization
  const abortControllerRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Stop optimization
  const stopOptimization = () => {
    console.log('[Optimizer UI] Stop button pressed');
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  // Energy budget config - use optional chaining for hydration safety
  const [energyBudget, setEnergyBudget] = useState(params?.wPrime_J?.toString() ?? '25000');
  const [nSamples, setNSamples] = useState('100');
  const [minPowerPct, setMinPowerPct] = useState('80');  // Min power as % of baseline (80% default)
  const [showMinPowerHelp, setShowMinPowerHelp] = useState(false);
  const [constraintBufferPct, setConstraintBufferPct] = useState('2');  // 2% buffer for floor/ceiling
  const [showBufferHelp, setShowBufferHelp] = useState(false);
  const [energyLevels, setEnergyLevels] = useState('10');  // Number of discrete energy levels per segment
  const [showEnergyLevelsHelp, setShowEnergyLevelsHelp] = useState(false);
  const [useStandingForSeated, setUseStandingForSeated] = useState(false);  // If true, seated = standing (no discount)

  // Optimization start segment - segments from Lap 2 Home (1st half) to Lap 2+ Turn 1
  // These are the segments where optimization can reasonably start (before timed section at 695m)
  const OPT_START_SEGMENTS = TRACK_SEGMENTS.filter(
    seg => seg.startM >= 355 && seg.startM < 695
  );
  const [optStartSegmentId, setOptStartSegmentId] = useState('lap2_back_1');  // Default: 485m (Lap 2 Back Straight 1st half)
  const selectedOptStartSegment = OPT_START_SEGMENTS.find(s => s.id === optStartSegmentId) || OPT_START_SEGMENTS[0];

  // Number of activities to analyze for athlete curve
  const [numActivities, setNumActivities] = useState('10');
  const [importProgress, setImportProgress] = useState<string | null>(null);
  const [aggregationMethod, setAggregationMethod] = useState<PowerAggregationMethod>('max');

  // Redistribution optimizer config
  const [powerIncrement, setPowerIncrement] = useState('10');  // Step size in watts
  const [maxAdjustment, setMaxAdjustment] = useState('100');   // Max +/- watts per segment

  // Load athlete power curve from last N Strava activities
  const loadAthleteCurveFromStrava = async () => {
    if (!stravaSessionId) {
      Alert.alert('Error', 'Not connected to Strava. Go to Home tab to connect.');
      return;
    }

    const n = parseInt(numActivities) || 10;
    if (n < 1 || n > 50) {
      Alert.alert('Error', 'Number of activities must be between 1 and 50');
      return;
    }

    try {
      setLoadingAthleteCurve(true);
      const methodLabel = aggregationMethod === 'max' ? 'Max' : 'Avg of Max';
      setImportProgress(`Analyzing ${n} activities (${methodLabel})...`);

      const result = await athletePowerApi.computeFromActivities(stravaSessionId, n, aggregationMethod);

      if (result.success && result.power_curve.length > 0) {
        importAthleteCurveFromStrava(result.power_curve);
        const methodDesc = result.method === 'max' ? 'best power' : 'average of bests';
        Alert.alert(
          'Success',
          `Imported ${methodDesc} from ${result.activities_used} activities (${result.power_curve.length} durations)`
        );
      } else {
        Alert.alert('Error', result.error || 'Could not compute power curve from activities');
      }
    } catch (err: unknown) {
      const axiosError = err as { response?: { status?: number }; message?: string };
      // Handle 401 silently - session expired
      if (axiosError.response?.status === 401) {
        console.log('Session expired (401) - clearing session');
        clearStravaSession();
      } else {
        console.error('Power curve import error:', axiosError.message || err);
        Alert.alert('Error', 'Failed to import power curve from Strava');
      }
    } finally {
      setLoadingAthleteCurve(false);
      setImportProgress(null);
    }
  };

  // Build profile for optimizer - use optional chaining for hydration safety
  const cdaSeated = params?.cda_seated ?? 0.24;
  const cdaStanding = params?.cda_standing ?? 0.38;

  const buildProfile = useCallback(() => {
    if (!powerProfile || powerProfile.length === 0) return null;

    const sortedPower = [...powerProfile].sort((a, b) => a.s_m - b.s_m);

    return DEFAULT_TRACK_TRAJECTORY.map((traj) => {
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
        segmentPositions || {},
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
  }, [powerProfile, segmentPositions, cdaSeated, cdaStanding]);

  // Calculate energy from Strava effort using actual time data
  // Energy = integral(Power × dt), using trapezoid rule with actual elapsed_s
  const calculateEnergyFromProfile = useCallback((startM: number, endM: number = 895): number | null => {
    // Need activity records with time data, and a selected effort
    if (!currentActivity?.records || currentActivity.records.length === 0) return null;
    if (selectedEffortIndex === null || !detectedEfforts[selectedEffortIndex]) return null;

    const effort = detectedEfforts[selectedEffortIndex];
    const records = currentActivity.records;

    // Get records within the selected effort
    const effortRecords = records.slice(effort.startIndex, effort.endIndex + 1);
    if (effortRecords.length < 2) return null;

    // Effort start distance (to map to track distance 0)
    const effortStartDist = effortRecords[0].distance_m;
    const effortEndDist = effortRecords[effortRecords.length - 1].distance_m;

    console.log('[Energy Calc] Effort records:', effortRecords.length);
    console.log('[Energy Calc] Effort distance range:', effortStartDist.toFixed(1), 'to', effortEndDist.toFixed(1), 'm');
    console.log('[Energy Calc] Effort total distance:', (effortEndDist - effortStartDist).toFixed(1), 'm');
    console.log('[Energy Calc] Requested range:', startM, 'to', endM, 'm');

    let totalEnergy = 0;
    let intervalsUsed = 0;

    // Integrate using trapezoid rule with actual time intervals
    for (let i = 1; i < effortRecords.length; i++) {
      const prev = effortRecords[i - 1];
      const curr = effortRecords[i];

      // Map to track distance (relative to effort start)
      const prevTrackDist = prev.distance_m - effortStartDist;
      const currTrackDist = curr.distance_m - effortStartDist;

      // Check if this interval overlaps with our range [startM, endM]
      if (currTrackDist >= startM && prevTrackDist <= endM) {
        // Calculate actual time interval from elapsed_s
        const dt = curr.elapsed_s - prev.elapsed_s;

        // Trapezoid rule: average power × time
        const avgPower = (prev.power_W + curr.power_W) / 2;

        totalEnergy += avgPower * dt;
        intervalsUsed++;
      }
    }

    console.log('[Energy Calc] Intervals used:', intervalsUsed);
    console.log('[Energy Calc] Total energy:', totalEnergy.toFixed(0), 'J');

    // If we didn't accumulate any energy, return null
    if (totalEnergy < 100) return null;

    return Math.round(totalEnergy);
  }, [currentActivity, detectedEfforts, selectedEffortIndex]);

  // Get calculated energy for current segment selection
  const calculatedEnergy = calculateEnergyFromProfile(selectedOptStartSegment.startM, 895);

  // Check if athlete curve has enough data - defensive check for hydration safety
  const athleteCurveValid = (athletePowerCurve || []).filter(p => p.standing_W > 0).length >= 3;

  // Run Energy Budget optimization
  const runEnergyBudgetOptimization = async () => {
    console.log('[Optimizer UI] Starting Energy Budget optimization...');

    // CRITICAL: Must use exact same inputs as last simulation for valid comparison
    if (!lastSimulationParams || !lastSimulationProfile) {
      Alert.alert(
        'Run Simulation First',
        'Please run a simulation first. The optimizer must use the exact same parameters and profile to ensure the baseline matches.',
        [{ text: 'OK' }]
      );
      return;
    }

    if (!athleteCurveValid) {
      Alert.alert('Error', 'Athlete power curve needs at least 3 values. Import from Strava or enter manually.');
      return;
    }

    // Setup abort controller and timer
    abortControllerRef.current = new AbortController();
    setElapsedTime(0);
    timerRef.current = setInterval(() => {
      setElapsedTime(t => t + 1);
    }, 1000);

    setOptimizing(true);
    setError(null);
    setEnergyResult(null);

    try {
      // Use athlete power curve for Energy Budget
      const validPoints = athletePowerCurve.filter(p => p.standing_W > 0);
      const powerCurves = {
        durations: validPoints.map(p => p.duration_s),
        // If useStandingForSeated is true, use standing values for seated (no discount)
        // This matches Python GUI behavior where users often enter same values for both
        seated: validPoints.map(p => useStandingForSeated ? p.standing_W : p.seated_W),
        standing: validPoints.map(p => p.standing_W),
      };
      console.log('[Optimizer UI] Power curve points:', validPoints.length);
      console.log('[Optimizer UI] Using standing for seated:', useStandingForSeated);

      // Use EXACT params from last simulation - no modifications
      const simParams = lastSimulationParams;
      const riderParams = {
        mass_kg: simParams.mass_kg,
        rho: simParams.rho,
        crr: simParams.crr,
        cda_seated: simParams.cda_seated,
        cda_standing: simParams.cda_standing,
        cda_bend_factor: simParams.cda_bend_factor,
        cp_W: simParams.cp_W,
        wPrime_J: simParams.wPrime_J,
        v0_mps: simParams.v0_mps,
        drivetrain_eff: simParams.drivetrain_eff,
      };

      console.log('[Optimizer UI] Using simulation params:', riderParams);
      console.log('[Optimizer UI] Using simulation profile:', lastSimulationProfile.length, 'points');

      // Build config with debug logging
      const minPowerPctDecimal = (parseInt(minPowerPct) || 80) / 100;
      const constraintBufferDecimal = (parseFloat(constraintBufferPct) || 2) / 100;
      const config = {
        energy_budget_J: parseInt(energyBudget) || simParams.wPrime_J,
        n_samples: parseInt(nSamples) || 500,
        min_power_pct: minPowerPctDecimal,
        constraint_buffer_pct: constraintBufferDecimal,
        energy_levels: parseInt(energyLevels) || 10,
        opt_start_m: selectedOptStartSegment.startM,
        optimizer_method: optimizerMethod,
        gravity_aware_position: gravityAwarePosition,
      };
      console.log('[Optimizer UI] Config:', config);
      console.log('[Optimizer UI] Method:', optimizerMethod);
      console.log('[Optimizer UI] Gravity-aware position:', gravityAwarePosition);
      console.log('[Optimizer UI] Min Power %:', minPowerPct, '% → decimal:', minPowerPctDecimal);
      console.log('[Optimizer UI] Constraint Buffer %:', constraintBufferPct, '% → decimal:', constraintBufferDecimal);
      console.log('[Optimizer UI] Opt Start:', selectedOptStartSegment.label, '(', selectedOptStartSegment.startM, 'm)');

      const result = optimizerMethod === 'greedy'
        ? await optimizerApi.runGreedy(
            powerCurves,
            lastSimulationProfile,
            riderParams,
            config,
            lastSimulationT200 ?? undefined,
            lastSimulationEffortType ?? 200,
            abortControllerRef.current.signal
          )
        : await optimizerApi.runEnergyBudget(
            powerCurves,
            lastSimulationProfile,  // Use exact profile from simulation
            riderParams,
            config,
            lastSimulationT200 ?? undefined,
            lastSimulationEffortType ?? 200,
            abortControllerRef.current.signal
          );

      console.log('[Optimizer UI] Energy Budget result received:', result.success);
      setEnergyResult(result);
      if (!result.success) {
        setError(result.error || 'Optimization failed');
      }
    } catch (err: unknown) {
      console.error('[Optimizer UI] Energy Budget error:', err);
      const message = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
        : err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message
        : 'Optimization failed';
      setError(message || 'Optimization failed');
    } finally {
      setOptimizing(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      abortControllerRef.current = null;
      console.log('[Optimizer UI] Energy Budget optimization finished');
    }
  };

  // Run Power Redistribution optimization
  const runRedistributionOptimization = async () => {
    console.log('[Optimizer UI] Starting Redistribution optimization...');

    // CRITICAL: Must use exact same inputs as last simulation for valid comparison
    if (!lastSimulationParams || !lastSimulationProfile) {
      Alert.alert(
        'Run Simulation First',
        'Please run a simulation first. The optimizer must use the exact same parameters and profile to ensure the baseline matches.',
        [{ text: 'OK' }]
      );
      return;
    }

    // Setup abort controller and timer
    abortControllerRef.current = new AbortController();
    setElapsedTime(0);
    timerRef.current = setInterval(() => {
      setElapsedTime(t => t + 1);
    }, 1000);

    setOptimizing(true);
    setError(null);
    setRedistributionResult(null);

    try {
      // For redistribution, we use activity power directly from simulation profile
      const profilePowers = lastSimulationProfile.filter(p => p.P_W > 0).map(p => p.P_W);

      if (profilePowers.length === 0) {
        console.log('[Optimizer UI] Profile has no valid power data');
        Alert.alert('Error', 'Profile has no valid power data');
        return;
      }

      const maxPower = Math.max(...profilePowers);
      const avgPower = profilePowers.reduce((a, b) => a + b, 0) / profilePowers.length;
      console.log('[Optimizer UI] Profile power - max:', maxPower, 'avg:', avgPower);

      // Validate we have usable values
      if (!isFinite(maxPower) || !isFinite(avgPower) || maxPower <= 0) {
        console.log('[Optimizer UI] Invalid power values');
        Alert.alert('Error', `Invalid power values: max=${maxPower}, avg=${avgPower}`);
        return;
      }

      // Create more detailed power curve from activity
      const durations = [1, 2, 3, 5, 10, 15, 20, 30, 45, 60];
      const seated: number[] = [];
      const standing: number[] = [];

      for (const d of durations) {
        const decay = Math.exp(-d / 30);
        const power = avgPower + (maxPower - avgPower) * decay;
        standing.push(Math.round(power));
        seated.push(Math.round(power * 0.85));
      }

      const powerCurves = { durations, seated, standing };
      console.log('[Optimizer UI] Generated power curve:', powerCurves);

      // Use EXACT params from last simulation - no modifications
      const simParams = lastSimulationParams;
      const riderParams = {
        mass_kg: simParams.mass_kg,
        rho: simParams.rho,
        crr: simParams.crr,
        cda_seated: simParams.cda_seated,
        cda_standing: simParams.cda_standing,
        cda_bend_factor: simParams.cda_bend_factor,
        v0_mps: simParams.v0_mps,
        drivetrain_eff: simParams.drivetrain_eff,
      };

      console.log('[Optimizer UI] Using simulation params:', riderParams);
      console.log('[Optimizer UI] Using simulation profile:', lastSimulationProfile.length, 'points');

      const result = await optimizerApi.runPositionOptimizer(
        powerCurves,
        lastSimulationProfile,  // Use exact profile from simulation
        riderParams,
        {
          n_samples: parseInt(nSamples) || 500,
          power_increment_W: parseInt(powerIncrement) || 10,
          max_adjustment_W: parseInt(maxAdjustment) || 100,
        },
        lastSimulationEffortType ?? 200,
        abortControllerRef.current.signal
      );

      console.log('[Optimizer UI] Redistribution result received:', result.success);
      setRedistributionResult(result);
      if (!result.success) {
        setError(result.error || 'Optimization failed');
      }
    } catch (err: unknown) {
      console.error('[Optimizer UI] Redistribution error:', err);
      const message = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
        : err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message
        : 'Optimization failed';
      setError(message || 'Optimization failed');
    } finally {
      setOptimizing(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      abortControllerRef.current = null;
      console.log('[Optimizer UI] Redistribution optimization finished');
    }
  };

  const hasPowerProfile = powerProfile && powerProfile.length > 0;
  const validAthletePowerCount = (athletePowerCurve || []).filter(p => p.standing_W > 0).length;

  return (
    <ScrollView style={styles.container}>
      {/* Return to Simulation */}
      <TouchableOpacity style={styles.returnButton} onPress={() => router.push('/(simulate)/')}>
        <Text style={styles.returnButtonText}>← Simulation</Text>
      </TouchableOpacity>

      {/* Status Banner */}
      <View style={styles.statusBanner}>
        {hasPowerProfile ? (
          <Text style={styles.statusText}>
            Activity: {powerProfileSummary?.gridPoints} pts, {powerProfileSummary?.avgPowerW}W avg
          </Text>
        ) : (
          <Text style={styles.statusTextWarn}>
            No power profile. Select an effort from Analysis.
          </Text>
        )}
      </View>

      {/* Optimizer Type Selection */}
      <View style={styles.typeSelector}>
        <TouchableOpacity
          style={[styles.typeButton, optimizerType === 'energy' && styles.typeButtonActive]}
          onPress={() => setOptimizerType('energy')}
          activeOpacity={1}
        >
          <Text style={[styles.typeButtonText, optimizerType === 'energy' && styles.typeButtonTextActive]}>
            Energy Budget
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.typeButton, optimizerType === 'redistribution' && styles.typeButtonActive]}
          onPress={() => setOptimizerType('redistribution')}
          activeOpacity={1}
        >
          <Text style={[styles.typeButtonText, optimizerType === 'redistribution' && styles.typeButtonTextActive]}>
            Redistribution
          </Text>
        </TouchableOpacity>
      </View>

      {/* Energy Budget Optimizer */}
      {optimizerType === 'energy' && (
        <>
          {/* Athlete Power Curve Section */}
          <CollapsibleSection
            title="Athlete Power Curve"
            defaultExpanded={true}
            badge={validAthletePowerCount > 0 ? `${validAthletePowerCount} values` : undefined}
          >
            <Text style={styles.helpText}>
              Enter your best power values (standing). Seated is auto-calculated with {Math.round(seatedDiscount * 100)}% discount at 1s, converging at 45s.
            </Text>

            {/* Seated Discount Slider */}
            <View style={styles.sliderRow}>
              <Text style={styles.sliderLabel}>Seated Discount: {Math.round(seatedDiscount * 100)}%</Text>
              <Slider
                style={styles.slider}
                minimumValue={0}
                maximumValue={0.30}
                step={0.01}
                value={seatedDiscount}
                onValueChange={setSeatedDiscount}
                minimumTrackTintColor="#4da6ff"
                maximumTrackTintColor="#2d4a6f"
                thumbTintColor="#4da6ff"
              />
            </View>

            {/* Import from Strava - Number of Activities */}
            <View style={styles.importSection}>
              <View style={styles.activitiesRow}>
                <Text style={styles.activitiesLabel}>Activities to analyze:</Text>
                <TextInput
                  style={styles.activitiesInput}
                  value={numActivities}
                  onChangeText={setNumActivities}
                  keyboardType="number-pad"
                  placeholder="10"
                  placeholderTextColor="#5a7a9a"
                />
              </View>

              {/* Aggregation Method Selector */}
              <View style={styles.methodSelector}>
                <TouchableOpacity
                  style={[styles.methodButton, aggregationMethod === 'max' && styles.methodButtonActive]}
                  onPress={() => setAggregationMethod('max')}
                  activeOpacity={1}
                >
                  <Text style={[styles.methodButtonText, aggregationMethod === 'max' && styles.methodButtonTextActive]}>
                    Max Power
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.methodButton, aggregationMethod === 'avgOfMax' && styles.methodButtonActive]}
                  onPress={() => setAggregationMethod('avgOfMax')}
                  activeOpacity={1}
                >
                  <Text style={[styles.methodButtonText, aggregationMethod === 'avgOfMax' && styles.methodButtonTextActive]}>
                    Avg of Max
                  </Text>
                </TouchableOpacity>
              </View>
              <Text style={styles.methodHelpText}>
                {aggregationMethod === 'max'
                  ? 'Uses highest power found at each duration across all activities'
                  : 'Averages the best power at each duration from each activity'}
              </Text>

              <TouchableOpacity
                style={[styles.importButton, (loadingAthleteCurve || !stravaSessionId) && styles.buttonDisabled]}
                onPress={loadAthleteCurveFromStrava}
                disabled={loadingAthleteCurve || !stravaSessionId}
              >
                {loadingAthleteCurve ? (
                  <View style={styles.importLoadingRow}>
                    <ActivityIndicator color="#fff" size="small" />
                    <Text style={styles.importButtonText}>  {importProgress || 'Loading...'}</Text>
                  </View>
                ) : (
                  <Text style={styles.importButtonText}>
                    {stravaSessionId ? 'Import Power Curve from Strava' : 'Connect Strava First'}
                  </Text>
                )}
              </TouchableOpacity>
              <Text style={styles.importHelpText}>
                Computes your best power at each duration from recent activities (Mean Maximal Power).
              </Text>

              {/* Generate from Activity / Effort */}
              <View style={styles.buttonRow}>
                <TouchableOpacity
                  style={[styles.secondaryButton, !currentActivity && styles.buttonDisabled]}
                  onPress={() => {
                    if (!currentActivity) return;
                    const curve = computePowerCurve(currentActivity.records);
                    if (curve.length > 0) {
                      importAthleteCurveFromStrava(curve);
                      Alert.alert('Success', `Generated power curve from activity (${curve.length} durations)`);
                    } else {
                      Alert.alert('Error', 'No power data found in current activity');
                    }
                  }}
                  disabled={!currentActivity}
                >
                  <Text style={[styles.secondaryButtonText, { color: colors.textPrimary }]}>Get Power from Activity</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.secondaryButton, (!currentActivity || selectedEffortIndex === null) && styles.buttonDisabled]}
                  onPress={() => {
                    if (!currentActivity || selectedEffortIndex === null) return;
                    const effort = detectedEfforts[selectedEffortIndex];
                    if (!effort) return;
                    const effortRecords = currentActivity.records.slice(effort.startIndex, effort.endIndex + 1);
                    const curve = computePowerCurve(effortRecords);
                    if (curve.length > 0) {
                      importAthleteCurveFromStrava(curve);
                      Alert.alert('Success', `Generated power curve from effort (${curve.length} durations, ${effortRecords.length} records)`);
                    } else {
                      Alert.alert('Error', 'No power data found in selected effort');
                    }
                  }}
                  disabled={!currentActivity || selectedEffortIndex === null}
                >
                  <Text style={[styles.secondaryButtonText, { color: colors.textPrimary }]}>Get Power from Effort</Text>
                </TouchableOpacity>
              </View>
              <Text style={styles.importHelpText}>
                Generate MMP curve from current activity or selected effort's power data.
              </Text>
            </View>

            {/* Reset / Clear buttons */}
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={[styles.secondaryButton, !stravaPowerCurve && styles.buttonDisabled]}
                onPress={resetAthleteCurveToStrava}
                disabled={!stravaPowerCurve}
              >
                <Text style={styles.secondaryButtonText}>Reset to Strava</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.clearButton}
                onPress={clearAthleteCurve}
              >
                <Text style={styles.clearButtonText}>Clear All</Text>
              </TouchableOpacity>
            </View>

            {/* Power Values Header */}
            <View style={styles.powerHeader}>
              <Text style={styles.powerHeaderText}>Duration</Text>
              <Text style={styles.powerHeaderText}>Standing</Text>
              <Text style={styles.powerHeaderText}>Seated</Text>
            </View>

            {/* Power Values - 1-15s */}
            <Text style={styles.sectionSubtitle}>Short Duration (1-15s)</Text>
            {ATHLETE_CURVE_DURATIONS.filter(d => d <= 15).map(d => {
              const point = (athletePowerCurve || []).find(p => p.duration_s === d);
              return (
                <PowerValueRow
                  key={d}
                  duration={d}
                  standingW={point?.standing_W ?? 0}
                  seatedW={point?.seated_W ?? 0}
                  onChangeStanding={(val) => setAthletePowerValue(d, val)}
                />
              );
            })}

            {/* Power Values - 20-90s */}
            <Text style={styles.sectionSubtitle}>Medium Duration (20-90s)</Text>
            {ATHLETE_CURVE_DURATIONS.filter(d => d > 15).map(d => {
              const point = (athletePowerCurve || []).find(p => p.duration_s === d);
              return (
                <PowerValueRow
                  key={d}
                  duration={d}
                  standingW={point?.standing_W ?? 0}
                  seatedW={point?.seated_W ?? 0}
                  onChangeStanding={(val) => setAthletePowerValue(d, val)}
                />
              );
            })}
          </CollapsibleSection>

          {/* Energy Budget Config */}
          <CollapsibleSection title="Optimization Config" defaultExpanded={true}>
            {/* Optimization Start Segment Selector */}
            <View style={styles.configSection}>
              <Text style={styles.configSectionLabel}>Optimize From Segment</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.segmentSelector}>
                {OPT_START_SEGMENTS.map(seg => (
                  <TouchableOpacity
                    key={seg.id}
                    style={[
                      styles.segmentOption,
                      optStartSegmentId === seg.id && styles.segmentOptionSelected
                    ]}
                    onPress={() => setOptStartSegmentId(seg.id)}
                  >
                    <Text style={[
                      styles.segmentOptionText,
                      optStartSegmentId === seg.id && styles.segmentOptionTextSelected
                    ]}>
                      {seg.label.replace('Lap ', 'L').replace(' Straight', '').replace('(1st half)', '1').replace('(2nd half)', '2').replace('Turn ', 'T').replace(' (into start)', '')}
                    </Text>
                    <Text style={styles.segmentOptionDistance}>{seg.startM}m</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <Text style={styles.configHint}>
                Selected: {selectedOptStartSegment.label} ({selectedOptStartSegment.startM}m)
              </Text>
            </View>

            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Energy Budget (J)</Text>
              <View style={styles.energyInputRow}>
                <TextInput
                  style={styles.energyInput}
                  value={energyBudget}
                  onChangeText={setEnergyBudget}
                  keyboardType="number-pad"
                />
                {calculatedEnergy && (
                  <TouchableOpacity
                    style={styles.useEffortButton}
                    onPress={() => setEnergyBudget(calculatedEnergy.toString())}
                  >
                    <Text style={styles.useEffortButtonText}>Use Effort</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
            {calculatedEnergy && (
              <Text style={styles.calculatedEnergyHint}>
                Effort energy ({selectedOptStartSegment.startM}m → 895m): {calculatedEnergy.toLocaleString()}J
              </Text>
            )}
            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Samples</Text>
              <TextInput
                style={styles.configInput}
                value={nSamples}
                onChangeText={setNSamples}
                keyboardType="number-pad"
              />
            </View>
            <View style={styles.configRow}>
              <View style={styles.labelWithHelp}>
                <Text style={styles.configLabel}>Min Power %</Text>
                <TouchableOpacity onPress={() => setShowMinPowerHelp(!showMinPowerHelp)}>
                  <Text style={styles.helpIcon}>?</Text>
                </TouchableOpacity>
              </View>
              <TextInput
                style={styles.configInput}
                value={minPowerPct}
                onChangeText={setMinPowerPct}
                keyboardType="number-pad"
              />
            </View>
            {showMinPowerHelp && (
              <View style={styles.helpBox}>
                <Text style={styles.helpBoxText}>
                  Floor power as % of baseline. Lower values give more optimization freedom
                  but may be less realistic. Higher values (e.g., 90%) constrain power closer
                  to your actual effort. Default 80% works well for most cases.
                </Text>
              </View>
            )}
            <View style={styles.configRow}>
              <View style={styles.labelWithHelp}>
                <Text style={styles.configLabel}>Constraint Buffer %</Text>
                <TouchableOpacity onPress={() => setShowBufferHelp(!showBufferHelp)}>
                  <Text style={styles.helpIcon}>?</Text>
                </TouchableOpacity>
              </View>
              <TextInput
                style={styles.configInput}
                value={constraintBufferPct}
                onChangeText={setConstraintBufferPct}
                keyboardType="decimal-pad"
              />
            </View>
            {showBufferHelp && (
              <View style={styles.helpBox}>
                <Text style={styles.helpBoxText}>
                  Buffer to relax floor/ceiling constraints. 2% makes floor 2% lower and ceiling
                  2% higher, helping find solutions when constraints are tight. Increase if optimizer
                  can't find improvements. Default 2%.
                </Text>
              </View>
            )}
            <View style={styles.configRow}>
              <View style={styles.labelWithHelp}>
                <Text style={styles.configLabel}>Energy Levels</Text>
                <TouchableOpacity onPress={() => setShowEnergyLevelsHelp(!showEnergyLevelsHelp)}>
                  <Text style={styles.helpIcon}>?</Text>
                </TouchableOpacity>
              </View>
              <TextInput
                style={styles.configInput}
                value={energyLevels}
                onChangeText={setEnergyLevels}
                keyboardType="number-pad"
              />
            </View>
            {showEnergyLevelsHelp && (
              <View style={styles.helpBox}>
                <Text style={styles.helpBoxText}>
                  Number of discrete power levels to allocate per segment. Higher values (20-30)
                  give finer granularity and better optimization results, but take longer to compute.
                  Lower values (5-10) are faster but coarser. Default 10.
                </Text>
              </View>
            )}
            <View style={styles.configRow}>
              <Text style={styles.configLabel}>No Seated Discount</Text>
              <TouchableOpacity
                style={[styles.toggleButton, useStandingForSeated && styles.toggleButtonActive]}
                onPress={() => setUseStandingForSeated(!useStandingForSeated)}
                activeOpacity={1}
              >
                <Text style={styles.toggleText}>{useStandingForSeated ? 'ON' : 'OFF'}</Text>
              </TouchableOpacity>
            </View>
            <Text style={styles.configHint}>
              {useStandingForSeated ? 'Seated curve = Standing curve (higher ceiling)' : 'Seated curve = 85% of standing at 1s'}
            </Text>

            {/* Optimizer Method Selector */}
            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Optimizer Method</Text>
            </View>
            <View style={styles.methodSelector}>
              <TouchableOpacity
                style={[styles.methodButton, optimizerMethod === 'greedy' && styles.methodButtonActive]}
                onPress={() => setOptimizerMethod('greedy')}
                activeOpacity={1}
              >
                <Text style={[styles.methodButtonText, optimizerMethod === 'greedy' && styles.methodButtonTextActive]}>
                  Greedy
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.methodButton, optimizerMethod === 'legacy' && styles.methodButtonActive]}
                onPress={() => setOptimizerMethod('legacy')}
                activeOpacity={1}
              >
                <Text style={[styles.methodButtonText, optimizerMethod === 'legacy' && styles.methodButtonTextActive]}>
                  Legacy
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.methodButton, optimizerMethod === 'slsqp' && styles.methodButtonActive]}
                onPress={() => setOptimizerMethod('slsqp')}
                activeOpacity={1}
              >
                <Text style={[styles.methodButtonText, optimizerMethod === 'slsqp' && styles.methodButtonTextActive]}>
                  SLSQP
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={styles.configHint}>
              {optimizerMethod === 'greedy'
                ? 'Position + power local search: F_net analysis seed, then systematic perturbation'
                : optimizerMethod === 'legacy'
                ? 'Random search: tests N random energy allocations (proven, stochastic)'
                : 'Gradient-based NLP: SLSQP solver with restarts (faster, deterministic)'}
            </Text>

            {/* Gravity-Aware Position Toggle */}
            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Gravity-Aware Position</Text>
              <TouchableOpacity
                style={[styles.toggleButton, gravityAwarePosition && styles.toggleButtonActive]}
                onPress={() => setGravityAwarePosition(!gravityAwarePosition)}
                activeOpacity={1}
              >
                <Text style={styles.toggleText}>{gravityAwarePosition ? 'ON' : 'OFF'}</Text>
              </TouchableOpacity>
            </View>
            <Text style={styles.configHint}>
              {gravityAwarePosition
                ? 'Accounts for track slope: gravity inflates speed during dive, narrowing standing window'
                : 'Legacy: compares power gain vs drag penalty without gravity effects'}
            </Text>

            {lastSimulationT200 && (
              <Text style={styles.baselineInfo}>
                Baseline T_200 from simulation: {lastSimulationT200.toFixed(3)}s
                {lastSimulationKitConfig ? ` | Kit: ${lastSimulationKitConfig.name}` : ''}
              </Text>
            )}
          </CollapsibleSection>

          {/* Run/Stop Energy Budget Button */}
          {optimizing ? (
            <View style={styles.optimizingContainer}>
              <View style={styles.optimizingStatus}>
                <ActivityIndicator color="#4da6ff" />
                <Text style={styles.optimizingText}>
                  Optimizing... {elapsedTime}s
                </Text>
              </View>
              <TouchableOpacity
                style={styles.stopButton}
                onPress={stopOptimization}
              >
                <Text style={styles.stopButtonText}>Stop</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity
              style={[styles.runButton, (!hasPowerProfile || !athleteCurveValid) && styles.buttonDisabled]}
              onPress={runEnergyBudgetOptimization}
              disabled={!hasPowerProfile || !athleteCurveValid}
            >
              <Text style={styles.runButtonText}>
                Run {optimizerMethod === 'greedy' ? 'Greedy' : optimizerMethod === 'slsqp' ? 'SLSQP' : 'Energy Budget'} Optimizer
              </Text>
            </TouchableOpacity>
          )}
        </>
      )}

      {/* Power Redistribution Optimizer */}
      {optimizerType === 'redistribution' && (
        <>
          <View style={styles.infoBox}>
            <Text style={styles.infoText}>
              Power Redistribution uses your actual activity power to find optimal power distribution across the effort.
              No athlete power curve needed - it works with the power you actually produced.
            </Text>
          </View>

          {/* Redistribution Config */}
          <View style={styles.configSection}>
            <Text style={styles.configSectionTitle}>Power Adjustment Settings</Text>

            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Power Increment (W)</Text>
              <TextInput
                style={styles.configInput}
                value={powerIncrement}
                onChangeText={setPowerIncrement}
                keyboardType="numeric"
                placeholder="10"
                placeholderTextColor="#5a7a9a"
              />
            </View>
            <Text style={styles.configHelp}>Step size for power adjustments (e.g., 10W, 20W, 50W)</Text>

            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Max Adjustment (W)</Text>
              <TextInput
                style={styles.configInput}
                value={maxAdjustment}
                onChangeText={setMaxAdjustment}
                keyboardType="numeric"
                placeholder="100"
                placeholderTextColor="#5a7a9a"
              />
            </View>
            <Text style={styles.configHelp}>Maximum +/- watts per segment (e.g., ±100W)</Text>

            <View style={styles.configRow}>
              <Text style={styles.configLabel}>Samples</Text>
              <TextInput
                style={styles.configInput}
                value={nSamples}
                onChangeText={setNSamples}
                keyboardType="numeric"
                placeholder="500"
                placeholderTextColor="#5a7a9a"
              />
            </View>
            <Text style={styles.configHelp}>Number of random combinations to test</Text>
          </View>

          {/* Run/Stop Redistribution Button */}
          {optimizing ? (
            <View style={styles.optimizingContainer}>
              <View style={styles.optimizingStatus}>
                <ActivityIndicator color="#4da6ff" />
                <Text style={styles.optimizingText}>
                  Optimizing... {elapsedTime}s
                </Text>
              </View>
              <TouchableOpacity
                style={styles.stopButton}
                onPress={stopOptimization}
              >
                <Text style={styles.stopButtonText}>Stop</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity
              style={[styles.runButton, !hasPowerProfile && styles.buttonDisabled]}
              onPress={runRedistributionOptimization}
              disabled={!hasPowerProfile}
            >
              <Text style={styles.runButtonText}>Run Redistribution Optimizer</Text>
            </TouchableOpacity>
          )}
        </>
      )}

      {/* Error Display */}
      {error && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      {/* Energy Budget Results */}
      {energyResult?.success && optimizerType === 'energy' && (
        <View style={styles.resultsCard}>
          <Text style={styles.resultsTitle}>
            {energyResult.optimizer_method === 'greedy' ? 'Greedy' : energyResult.optimizer_method === 'slsqp' ? 'SLSQP' : 'Energy Budget'} Results
          </Text>

          {/* Key Metrics */}
          <View style={styles.metricsGrid}>
            <View style={styles.metricItem}>
              <Text style={styles.metricValue}>
                {energyResult.comparison?.baseline_T_200.toFixed(3)}s
              </Text>
              <Text style={styles.metricLabel}>Baseline</Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricValueGreen}>
                {energyResult.optimization?.T_200_smoothed.toFixed(3)}s
              </Text>
              <Text style={styles.metricLabel}>Optimized</Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricValueYellow}>
                +{energyResult.comparison?.time_saved_ms.toFixed(0)}ms
              </Text>
              <Text style={styles.metricLabel}>Saved</Text>
            </View>
          </View>

          {/* Entry/Exit Speed Comparison */}
          {energyResult.comparison?.baseline_v_200_entry_kph && (
            <View style={styles.speedComparisonSection}>
              <Text style={styles.speedComparisonTitle}>200m Speed Comparison</Text>
              <View style={styles.speedComparisonRow}>
                <Text style={styles.speedComparisonLabel}>Entry Speed:</Text>
                <Text style={styles.speedComparisonValue}>
                  {energyResult.comparison.baseline_v_200_entry_kph?.toFixed(1)} kph
                </Text>
                <Text style={styles.speedComparisonArrow}>→</Text>
                <Text style={styles.speedComparisonValueGreen}>
                  {energyResult.comparison.optimized_v_200_entry_kph?.toFixed(1)} kph
                </Text>
              </View>
              <View style={styles.speedComparisonRow}>
                <Text style={styles.speedComparisonLabel}>Exit Speed:</Text>
                <Text style={styles.speedComparisonValue}>
                  {energyResult.comparison.baseline_v_200_exit_kph?.toFixed(1)} kph
                </Text>
                <Text style={styles.speedComparisonArrow}>→</Text>
                <Text style={styles.speedComparisonValueGreen}>
                  {energyResult.comparison.optimized_v_200_exit_kph?.toFixed(1)} kph
                </Text>
              </View>
            </View>
          )}

          {/* Speed Profile Graph */}
          {energyResult.profiles?.distance_m && energyResult.profiles?.baseline_speed_kph && (
            <View style={styles.graphSection}>
              <Text style={styles.graphTitle}>Speed Profile (Baseline vs Optimized)</Text>
              <LineChart
                data={{
                  labels: energyResult.profiles.distance_m
                    .filter((_, i) => i % Math.ceil(energyResult.profiles!.distance_m.length / 6) === 0)
                    .map(d => `${Math.round(d)}m`),
                  datasets: [
                    {
                      data: energyResult.profiles.baseline_speed_kph
                        .filter((_, i) => i % Math.ceil(energyResult.profiles!.baseline_speed_kph.length / 50) === 0),
                      color: () => colors.textMuted,
                      strokeWidth: 2,
                    },
                    {
                      data: energyResult.profiles.optimized_speed_kph
                        .filter((_, i) => i % Math.ceil(energyResult.profiles!.optimized_speed_kph.length / 50) === 0),
                      color: () => colors.success,
                      strokeWidth: 2,
                    },
                  ],
                  legend: ['Baseline', 'Optimized'],
                }}
                width={Dimensions.get('window').width - 48}
                height={180}
                chartConfig={{
                  backgroundColor: colors.bg2,
                  backgroundGradientFrom: colors.bg2,
                  backgroundGradientTo: colors.bg2,
                  decimalPlaces: 0,
                  color: (opacity = 1) => `rgba(255, 255, 255, ${opacity})`,
                  labelColor: () => colors.textSecondary,
                  style: { borderRadius: 8 },
                  propsForDots: { r: '0' },
                }}
                bezier
                style={styles.chart}
              />
            </View>
          )}

          {/* Power Profile Graph */}
          {energyResult.profiles?.distance_m && energyResult.profiles?.baseline_power_W && (
            <View style={styles.graphSection}>
              <Text style={styles.graphTitle}>Power Profile (Baseline vs Optimized)</Text>

              {/* Standing Zones Indicator */}
              {energyResult.segments && energyResult.segments.some((s: OptimizerSegment) => s.position === 'standing') && (
                <View style={styles.standingIndicator}>
                  <View style={styles.standingLegendItem}>
                    <View style={styles.standingLegendColor} />
                    <Text style={styles.standingLegendText}>
                      Standing: {energyResult.segments
                        .filter((s: OptimizerSegment) => s.position === 'standing')
                        .map((s: OptimizerSegment) => `${s.start_m}-${s.end_m}m`)
                        .join(', ')}
                    </Text>
                  </View>
                </View>
              )}

              <LineChart
                data={{
                  labels: energyResult.profiles.distance_m
                    .filter((_: number, i: number) => i % Math.ceil(energyResult.profiles!.distance_m.length / 6) === 0)
                    .map((d: number) => `${Math.round(d)}m`),
                  datasets: [
                    {
                      data: energyResult.profiles.baseline_power_W
                        .filter((_: number, i: number) => i % Math.ceil(energyResult.profiles!.baseline_power_W.length / 50) === 0),
                      color: () => colors.textMuted,
                      strokeWidth: 2,
                    },
                    {
                      data: (energyResult.profiles.P_smooth || energyResult.profiles.P_discrete)
                        .filter((_: number, i: number) => i % Math.ceil((energyResult.profiles!.P_smooth || energyResult.profiles!.P_discrete).length / 50) === 0),
                      color: () => colors.success,
                      strokeWidth: 2,
                    },
                  ],
                  legend: ['Baseline', 'Optimized'],
                }}
                width={Dimensions.get('window').width - 48}
                height={180}
                yAxisSuffix="W"
                chartConfig={{
                  backgroundColor: colors.bg2,
                  backgroundGradientFrom: colors.bg2,
                  backgroundGradientTo: colors.bg2,
                  decimalPlaces: 0,
                  color: (opacity = 1) => `rgba(255, 255, 255, ${opacity})`,
                  labelColor: () => colors.textSecondary,
                  style: { borderRadius: 8 },
                  propsForDots: { r: '0' },
                }}
                bezier
                style={styles.chart}
              />
            </View>
          )}

          {/* Segment Allocation Summary */}
          {energyResult.segments && energyResult.segments.length > 0 && (
            <View style={styles.segmentsSection}>
              <Text style={styles.segmentsTitle}>Segment Allocation Summary</Text>
              {energyResult.segments.map((seg: OptimizerSegment, i: number) => (
                <View
                  key={i}
                  style={[
                    styles.segmentRow,
                    seg.position === 'standing' && styles.segmentRowStanding
                  ]}
                >
                  <View style={styles.segmentInfo}>
                    <Text style={styles.segmentRange}>{seg.start_m}-{seg.end_m}m</Text>
                    {seg.section && (
                      <Text style={styles.segmentSection}>{seg.section}</Text>
                    )}
                  </View>
                  <View style={[
                    styles.positionBadge,
                    seg.position === 'standing' ? styles.positionStanding : styles.positionSeated
                  ]}>
                    <Text style={styles.positionText}>
                      {seg.position === 'standing' ? 'Stand' : 'Sit'}
                    </Text>
                  </View>
                  <Text style={styles.segmentEnergy}>{seg.energy_pct.toFixed(1)}%</Text>
                  <Text style={styles.segmentJoules}>{Math.round(seg.energy_J)}J</Text>
                </View>
              ))}
            </View>
          )}

          {/* Segment Power Detail */}
          {energyResult.segments && energyResult.segments.length > 0 && (
            <View style={styles.timelineSection}>
              <Text style={styles.segmentsTitle}>Segment Power Detail</Text>
              {energyResult.segments.map((seg: OptimizerSegment, i: number) => {
                const avgPower = seg.power_W != null ? Math.round(seg.power_W) : null;

                return (
                  <View
                    key={i}
                    style={[
                      styles.timelineRow,
                      seg.position === 'standing' && styles.segmentRowPositive
                    ]}
                  >
                    <View style={styles.segmentInfo}>
                      <Text style={styles.segmentName}>{seg.start_m}-{seg.end_m}m</Text>
                      {seg.section && (
                        <Text style={styles.segmentSection}>{seg.section}</Text>
                      )}
                    </View>
                    <View style={[
                      styles.positionBadge,
                      seg.position === 'standing' ? styles.positionStanding : styles.positionSeated
                    ]}>
                      <Text style={styles.positionText}>
                        {seg.position === 'standing' ? 'Stand' : 'Sit'}
                      </Text>
                    </View>
                    {avgPower != null && (
                    <Text style={styles.segmentPower}>
                      ~{avgPower}W
                    </Text>
                    )}
                    <Text style={styles.segmentEnergy}>
                      {seg.energy_pct.toFixed(1)}%
                    </Text>
                    <Text style={styles.segmentJoules}>
                      {Math.round(seg.energy_J)}J
                    </Text>
                  </View>
                );
              })}
              <Text style={styles.graphHint}>
                Power from optimizer segment allocation
              </Text>
            </View>
          )}

          {/* Statistics */}
          <View style={styles.statsRow}>
            <Text style={styles.statsText}>
              Tested: {energyResult.statistics?.samples_tested} |
              Valid: {energyResult.statistics?.valid_combinations} |
              Rejected: {energyResult.statistics?.rejected_violations}
            </Text>
          </View>
        </View>
      )}

      {/* Redistribution Results */}
      {redistributionResult?.success && optimizerType === 'redistribution' && (
        <View style={styles.resultsCard}>
          <Text style={styles.resultsTitle}>Redistribution Results</Text>

          {/* Key Metrics */}
          <View style={styles.metricsGrid}>
            <View style={styles.metricItem}>
              <Text style={styles.metricValue}>
                {redistributionResult.comparison?.baseline_T_200.toFixed(3)}s
              </Text>
              <Text style={styles.metricLabel}>Baseline</Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricValueGreen}>
                {redistributionResult.optimization?.T_200.toFixed(3)}s
              </Text>
              <Text style={styles.metricLabel}>Optimized</Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricValueYellow}>
                +{(redistributionResult.comparison?.time_saved_ms ?? 0).toFixed(0)}ms
              </Text>
              <Text style={styles.metricLabel}>Saved</Text>
            </View>
          </View>

          {/* Statistics */}
          {redistributionResult.statistics && (
            <View style={styles.statsBox}>
              <Text style={styles.statsText}>
                {redistributionResult.statistics.samples_tested} samples tested,{' '}
                {redistributionResult.statistics.valid_solutions} valid
              </Text>
            </View>
          )}

          {/* Speed Profile Graph */}
          {redistributionResult.profiles?.distance_m && redistributionResult.profiles?.baseline_speed_kph && (
            <View style={styles.graphSection}>
              <Text style={styles.graphTitle}>Speed Profile (Baseline vs Optimized)</Text>
              <LineChart
                data={{
                  labels: redistributionResult.profiles.distance_m
                    .filter((_, i) => i % Math.ceil(redistributionResult.profiles!.distance_m.length / 6) === 0)
                    .map(d => `${Math.round(d)}m`),
                  datasets: [
                    {
                      data: redistributionResult.profiles.baseline_speed_kph
                        .filter((_, i) => i % Math.ceil(redistributionResult.profiles!.baseline_speed_kph.length / 50) === 0),
                      color: () => colors.textMuted,
                      strokeWidth: 2,
                    },
                    {
                      data: redistributionResult.profiles.optimized_speed_kph
                        .filter((_, i) => i % Math.ceil(redistributionResult.profiles!.optimized_speed_kph.length / 50) === 0),
                      color: () => colors.success,
                      strokeWidth: 2,
                    },
                  ],
                  legend: ['Baseline', 'Optimized'],
                }}
                width={Dimensions.get('window').width - 48}
                height={180}
                chartConfig={{
                  backgroundColor: colors.bg2,
                  backgroundGradientFrom: colors.bg2,
                  backgroundGradientTo: colors.bg2,
                  decimalPlaces: 0,
                  color: (opacity = 1) => `rgba(255, 255, 255, ${opacity})`,
                  labelColor: () => colors.textSecondary,
                  style: { borderRadius: 8 },
                  propsForDots: { r: '0' },
                }}
                bezier
                style={styles.chart}
              />
            </View>
          )}

          {/* Power Adjustment Bar Chart */}
          {redistributionResult.segments && redistributionResult.segments.length > 0 && (
            <View style={styles.graphSection}>
              <Text style={styles.graphTitle}>Power Adjustments (W) by Segment</Text>
              <BarChart
                data={{
                  labels: redistributionResult.segments.map((seg) => {
                    // Extract distance range, e.g., "430-480" from "430-480m"
                    const match = seg.name.match(/(\d+)-(\d+)/);
                    if (match) {
                      return `${match[1]}`;
                    }
                    return seg.section || seg.name.slice(0, 4);
                  }),
                  datasets: [
                    {
                      data: redistributionResult.segments.map((seg) => seg.adjustment_W),
                    },
                  ],
                }}
                width={Dimensions.get('window').width - 48}
                height={200}
                yAxisSuffix="W"
                chartConfig={{
                  backgroundColor: colors.bg2,
                  backgroundGradientFrom: colors.bg2,
                  backgroundGradientTo: colors.bg2,
                  decimalPlaces: 0,
                  color: (opacity = 1) => `rgba(74, 222, 128, ${opacity})`,
                  labelColor: () => colors.textSecondary,
                  style: { borderRadius: 8 },
                  barPercentage: 0.7,
                  propsForBackgroundLines: {
                    strokeDasharray: '3,3',
                    stroke: colors.border,
                  },
                }}
                style={styles.chart}
                showBarTops={true}
                showValuesOnTopOfBars={true}
                fromZero={true}
              />
              <Text style={styles.graphHint}>
                Positive = add power (push harder), Negative = reduce power (recover)
              </Text>
            </View>
          )}

          {/* Segment Power Adjustments Detail */}
          {redistributionResult.segments && redistributionResult.segments.length > 0 && (
            <View style={styles.timelineSection}>
              <Text style={styles.segmentsTitle}>Power Adjustments Detail</Text>
              {redistributionResult.segments.map((seg, i) => (
                <View
                  key={i}
                  style={[
                    styles.timelineRow,
                    seg.adjustment_W > 0 && styles.segmentRowPositive,
                    seg.adjustment_W < 0 && styles.segmentRowNegative
                  ]}
                >
                  <View style={styles.segmentInfo}>
                    <Text style={styles.segmentName}>{seg.name}</Text>
                    {seg.section && (
                      <Text style={styles.segmentSection}>{seg.section}</Text>
                    )}
                  </View>
                  <Text style={styles.segmentPower}>
                    {seg.base_power_W}W
                  </Text>
                  <Text style={[
                    styles.segmentAdjustment,
                    seg.adjustment_W > 0 && styles.adjustmentPositive,
                    seg.adjustment_W < 0 && styles.adjustmentNegative
                  ]}>
                    {seg.adjustment_W >= 0 ? '+' : ''}{seg.adjustment_W}W
                  </Text>
                  <Text style={styles.segmentNewPower}>
                    = {seg.new_power_W}W
                  </Text>
                </View>
              ))}
            </View>
          )}
        </View>
      )}

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
  typeSelector: {
    flexDirection: 'row',
    marginHorizontal: 8,
    marginTop: 8,
    borderRadius: 8,
    overflow: 'hidden',
  },
  typeButton: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: colors.bg1,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  typeButtonActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  typeButtonText: {
    color: colors.textSecondary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  typeButtonTextActive: {
    color: colors.textPrimary,
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
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  badge: {
    backgroundColor: colors.success,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  badgeText: {
    color: colors.textPrimary,
    fontSize: 11,
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
  sectionSubtitle: {
    color: colors.accent,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
    marginTop: 12,
    marginBottom: 8,
  },
  helpText: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 12,
    lineHeight: 18,
  },
  sliderRow: {
    marginBottom: 12,
  },
  sliderLabel: {
    color: colors.textPrimary,
    fontSize: 13,
    marginBottom: 4,
  },
  slider: {
    width: '100%',
    height: 40,
  },
  importSection: {
    marginBottom: 8,
  },
  activitiesRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  activitiesLabel: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  activitiesInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    fontSize: 14,
    width: 70,
    textAlign: 'center',
  },
  methodSelector: {
    flexDirection: 'row',
    marginBottom: 4,
    borderRadius: 8,
    overflow: 'hidden',
  },
  methodButton: {
    flex: 1,
    paddingVertical: 10,
    backgroundColor: colors.bg0,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  methodButtonActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  methodButtonText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  methodButtonTextActive: {
    color: colors.textPrimary,
  },
  methodHelpText: {
    color: colors.textSecondary,
    fontSize: 11,
    textAlign: 'center',
    marginBottom: 12,
  },
  importButton: {
    backgroundColor: '#f97316',
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 4,
  },
  importLoadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  importButtonText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  importHelpText: {
    color: colors.textSecondary,
    fontSize: 11,
    textAlign: 'center',
    marginTop: 4,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  secondaryButton: {
    flex: 1,
    backgroundColor: colors.border,
    padding: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  clearButton: {
    flex: 1,
    backgroundColor: '#7f1d1d',
    padding: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  clearButtonText: {
    color: '#fca5a5',
    fontSize: 13,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  powerHeader: {
    flexDirection: 'row',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  powerHeaderText: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  powerValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.bg0,
  },
  powerDuration: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: 13,
  },
  powerInput: {
    flex: 1,
    backgroundColor: colors.bg0,
    color: '#f97316',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
    fontSize: 14,
    textAlign: 'right',
    fontFamily: fonts.sansSemiBold,
  },
  powerSeated: {
    flex: 1,
    color: colors.accent,
    fontSize: 13,
    textAlign: 'right',
  },
  configSection: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 8,
    borderRadius: 8,
    padding: 12,
  },
  configSectionTitle: {
    color: colors.accent,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 12,
  },
  configRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  configLabel: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  labelWithHelp: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  helpIcon: {
    color: colors.accent,
    fontSize: 14,
    fontFamily: fonts.sansBold,
    backgroundColor: colors.bg2,
    borderRadius: 10,
    width: 18,
    height: 18,
    textAlign: 'center',
    lineHeight: 18,
    overflow: 'hidden',
  },
  helpBox: {
    backgroundColor: colors.bg2,
    padding: 10,
    borderRadius: 6,
    marginTop: 4,
    marginBottom: 8,
  },
  helpBoxText: {
    color: colors.textSecondary,
    fontSize: 12,
    lineHeight: 18,
  },
  toggleButton: {
    backgroundColor: colors.bg2,
    paddingVertical: 6,
    paddingHorizontal: 16,
    borderRadius: 6,
    minWidth: 60,
    alignItems: 'center',
  },
  toggleButtonActive: {
    backgroundColor: '#2d6a4f',
  },
  toggleText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  configHint: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 8,
    marginTop: 2,
  },
  configSection: {
    marginBottom: 12,
  },
  configSectionLabel: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansMedium,
    marginBottom: 8,
  },
  segmentSelector: {
    flexDirection: 'row',
    marginBottom: 4,
  },
  segmentOption: {
    backgroundColor: colors.bg2,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    marginRight: 8,
    alignItems: 'center',
    minWidth: 70,
  },
  segmentOptionSelected: {
    backgroundColor: colors.seated,
  },
  segmentOptionText: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fonts.sansMedium,
  },
  segmentOptionTextSelected: {
    color: colors.textPrimary,
  },
  segmentOptionDistance: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 2,
  },
  configInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    fontSize: 14,
    minWidth: 100,
    textAlign: 'right',
  },
  energyInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  energyInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    fontSize: 14,
    minWidth: 80,
    textAlign: 'right',
  },
  useEffortButton: {
    backgroundColor: colors.accentDim,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
  },
  useEffortButtonText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  calculatedEnergyHint: {
    color: colors.success,
    fontSize: 11,
    marginBottom: 8,
    marginTop: -4,
  },
  configHelp: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 12,
  },
  baselineInfo: {
    color: colors.success,
    fontSize: 12,
    fontStyle: 'italic',
  },
  infoBox: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 8,
    borderRadius: 8,
    padding: 12,
  },
  infoText: {
    color: colors.textSecondary,
    fontSize: 12,
    lineHeight: 18,
  },
  runButton: {
    backgroundColor: colors.success,
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  optimizingContainer: {
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    backgroundColor: colors.bg1,
    borderRadius: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  optimizingStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  optimizingText: {
    color: colors.accent,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
    marginLeft: 12,
  },
  stopButton: {
    backgroundColor: colors.standing,
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
  },
  stopButtonText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansBold,
  },
  runningRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  runButtonText: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
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
    justifyContent: 'space-around',
    marginBottom: 16,
  },
  metricItem: {
    alignItems: 'center',
  },
  metricValue: {
    color: colors.textSecondary,
    fontSize: 20,
    fontFamily: fonts.sansBold,
  },
  metricValueGreen: {
    color: colors.success,
    fontSize: 20,
    fontFamily: fonts.sansBold,
  },
  metricValueYellow: {
    color: colors.warning,
    fontSize: 20,
    fontFamily: fonts.sansBold,
  },
  metricLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginTop: 4,
  },
  segmentsSection: {
    marginTop: 8,
  },
  segmentsTitle: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 8,
  },
  segmentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 8,
    backgroundColor: colors.bg0,
    borderRadius: 6,
    marginBottom: 4,
  },
  segmentRowStanding: {
    backgroundColor: '#422006',
  },
  segmentRange: {
    color: colors.textSecondary,
    fontSize: 12,
    width: 80,
  },
  segmentInfo: {
    flex: 1,
    minWidth: 100,
  },
  segmentSection: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 2,
  },
  graphSection: {
    marginTop: 16,
    marginBottom: 8,
  },
  graphTitle: {
    color: '#22d3ee',
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 8,
  },
  standingIndicator: {
    backgroundColor: 'rgba(249, 115, 22, 0.15)',
    borderRadius: 6,
    padding: 8,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#f97316',
  },
  standingLegendItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  standingLegendColor: {
    width: 12,
    height: 12,
    backgroundColor: '#f97316',
    borderRadius: 2,
    marginRight: 8,
  },
  standingLegendText: {
    color: '#f97316',
    fontSize: 12,
    fontFamily: fonts.sansMedium,
  },
  chart: {
    borderRadius: 8,
  },
  graphHint: {
    color: colors.textMuted,
    fontSize: 11,
    fontStyle: 'italic',
    marginTop: 6,
    textAlign: 'center',
  },
  positionBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    marginRight: 8,
  },
  positionStanding: {
    backgroundColor: colors.standing,
  },
  positionSeated: {
    backgroundColor: colors.seated,
  },
  positionText: {
    color: colors.textPrimary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  segmentEnergy: {
    color: colors.warning,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
    width: 50,
    textAlign: 'right',
  },
  segmentJoules: {
    color: colors.textSecondary,
    fontSize: 12,
    width: 50,
    textAlign: 'right',
  },
  statsRow: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  statsText: {
    color: colors.textSecondary,
    fontSize: 11,
    textAlign: 'center',
  },
  patternBox: {
    backgroundColor: colors.bg0,
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  patternText: {
    color: colors.accent,
    fontSize: 13,
    textAlign: 'center',
  },
  timelineSection: {
    marginTop: 8,
  },
  timelineRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 8,
    backgroundColor: colors.bg0,
    borderRadius: 6,
    marginBottom: 4,
  },
  timelineTime: {
    color: colors.textSecondary,
    fontSize: 12,
    flex: 1,
    marginLeft: 8,
  },
  timelineDuration: {
    color: colors.textSecondary,
    fontSize: 12,
  },
  statsBox: {
    backgroundColor: colors.bg0,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 6,
    marginBottom: 12,
  },
  statsText: {
    color: colors.textSecondary,
    fontSize: 12,
    textAlign: 'center',
  },
  speedComparisonSection: {
    backgroundColor: colors.bg0,
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
  },
  speedComparisonTitle: {
    color: colors.accent,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 8,
  },
  speedComparisonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  speedComparisonLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    width: 80,
  },
  speedComparisonValue: {
    color: colors.textPrimary,
    fontSize: 12,
    width: 65,
    textAlign: 'right',
  },
  speedComparisonArrow: {
    color: colors.textSecondary,
    fontSize: 12,
    marginHorizontal: 8,
  },
  speedComparisonValueGreen: {
    color: colors.success,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  segmentRowPositive: {
    borderLeftWidth: 3,
    borderLeftColor: colors.success,
  },
  segmentRowNegative: {
    borderLeftWidth: 3,
    borderLeftColor: colors.warning,
  },
  segmentName: {
    color: colors.textPrimary,
    fontSize: 12,
    flex: 1,
    fontFamily: fonts.sansMedium,
  },
  segmentPower: {
    color: colors.textSecondary,
    fontSize: 12,
    width: 55,
    textAlign: 'right',
  },
  segmentAdjustment: {
    fontSize: 12,
    width: 50,
    textAlign: 'right',
    fontFamily: fonts.sansSemiBold,
  },
  adjustmentPositive: {
    color: colors.success,
  },
  adjustmentNegative: {
    color: colors.warning,
  },
  segmentNewPower: {
    color: colors.accent,
    fontSize: 12,
    width: 60,
    textAlign: 'right',
    fontFamily: fonts.sansMedium,
  },
  bottomPadding: {
    height: 40,
  },
});

import { colors, fonts, spacing } from '../../theme';
import { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Dimensions,
  TextInput,
  Share,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { LineChart } from 'react-native-chart-kit';
import { useAppStore, detectFlying200Efforts, findAllPowerPeaks, isEffortAlreadySaved, TRACK_SEGMENTS, type DetectedEffort, type EffortType, type QuickSimResult, type DetectionSensitivity } from '../../store/simulationStore';
import { fitApi } from '../../api/client';

const screenWidth = Dimensions.get('window').width;
const CHART_HEIGHT = 120; // For effort power charts

function promptValue(title: string, message: string, defaultValue: string, onSubmit: (value: string) => void) {
  if (Platform.OS === 'web') {
    const result = window.prompt(message, defaultValue);
    if (result != null) onSubmit(result);
  } else {
    Alert.prompt(title, message, (value) => onSubmit(value), 'plain-text', defaultValue);
  }
}

export default function AnalysisScreen() {
  const router = useRouter();
  const {
    currentActivity,
    detectedEfforts,
    setDetectedEfforts,
    selectedEffortIndex,
    setSelectedEffortIndex,
    gearing,
    setGearing,
    params,
    effortType,
    setEffortType,
    setPowerProfile,
    segmentPositions,
    detectionSensitivity,
    setDetectionSensitivity,
    savedEfforts,
  } = useAppStore();

  const [quickSimResults, setQuickSimResults] = useState<Map<number, QuickSimResult>>(new Map());
  const [loadingEffort, setLoadingEffort] = useState<number | null>(null);
  const [expandedEffort, setExpandedEffort] = useState<number | null>(null);
  // Per-effort type overrides (user can change the auto-detected type)
  const [effortTypeOverrides, setEffortTypeOverrides] = useState<Map<number, EffortType>>(new Map());

  // Air density override for QuickSim (defaults to params.rho from settings)
  const [airDensity, setAirDensity] = useState(params.rho);
  const [rhoOverrideMode, setRhoOverrideMode] = useState(false); // false = calculate from environment

  // Environment inputs for air density calculation
  const [temperature, setTemperature] = useState(20); // °C
  const [pressure, setPressure] = useState(101.0); // kPa
  const [humidity, setHumidity] = useState(33); // % relative humidity

  // Local text state for inputs (allows free typing, updates actual value on blur)
  const [tempText, setTempText] = useState(temperature.toFixed(1));
  const [pressText, setPressText] = useState(pressure.toFixed(2));
  const [humidText, setHumidText] = useState(humidity.toFixed(0));
  const [rhoText, setRhoText] = useState(airDensity.toFixed(4));

  // Calculate air density from temperature, pressure, and humidity
  // Using the formula: ρ = (p_d + p_v) / (R_specific * T)
  const calculateAirDensity = (tempC: number, pressureKPa: number, humidityPct: number): number => {
    const T = tempC + 273.15; // Convert to Kelvin
    const P = pressureKPa * 1000; // Convert kPa to Pa
    const RH = humidityPct / 100; // Convert % to decimal

    // Saturation vapor pressure (Magnus formula)
    const pSat = 610.94 * Math.exp((17.625 * tempC) / (tempC + 243.04)); // Pa

    // Partial pressure of water vapor
    const pV = RH * pSat;

    // Partial pressure of dry air
    const pD = P - pV;

    // Specific gas constants
    const Rd = 287.058; // J/(kg·K) for dry air
    const Rv = 461.495; // J/(kg·K) for water vapor

    // Air density
    const rho = (pD / (Rd * T)) + (pV / (Rv * T));

    return rho;
  };

  // Update air density when environment values change (if not in override mode)
  useEffect(() => {
    if (!rhoOverrideMode) {
      const calculatedRho = calculateAirDensity(temperature, pressure, humidity);
      setAirDensity(calculatedRho);
      setRhoText(calculatedRho.toFixed(4));
    }
  }, [temperature, pressure, humidity, rhoOverrideMode]);

  // Sync text fields when numeric values change externally
  useEffect(() => { setTempText(temperature.toFixed(1)); }, [temperature]);
  useEffect(() => { setPressText(pressure.toFixed(2)); }, [pressure]);
  useEffect(() => { setHumidText(humidity.toFixed(0)); }, [humidity]);

  // Auto-populate environment from FIT metadata if available
  useEffect(() => {
    if (currentActivity?.source === 'fit' && currentActivity.fitMetadata) {
      const meta = currentActivity.fitMetadata;
      if (meta.temperature_c !== undefined && meta.temperature_c !== null) {
        setTemperature(meta.temperature_c);
      }
      if (meta.humidity_pct !== undefined && meta.humidity_pct !== null) {
        setHumidity(meta.humidity_pct);
      }
    }
  }, [currentActivity]);


  // Get the effective effort type for an effort (override or auto-detected)
  const getEffectiveEffortType = (effort: DetectedEffort, index: number): EffortType => {
    return effortTypeOverrides.get(index) ?? effort.estimatedEffortType;
  };

  // Set effort type override for a specific effort
  const setEffortTypeOverride = (index: number, type: EffortType) => {
    setEffortTypeOverrides((prev) => new Map(prev).set(index, type));
    // Clear any existing QuickSim result since type changed
    setQuickSimResults((prev) => {
      const newMap = new Map(prev);
      newMap.delete(index);
      return newMap;
    });
  };

  // Detect efforts when activity or sensitivity changes
  useEffect(() => {
    if (currentActivity?.records) {
      const efforts = detectFlying200Efforts(currentActivity.records, effortType, detectionSensitivity);
      setDetectedEfforts(efforts);
      setSelectedEffortIndex(null);
      setQuickSimResults(new Map());
    }
  }, [currentActivity, effortType, detectionSensitivity]);

  // Run peak finder as fallback
  const runPeakFinder = () => {
    if (!currentActivity?.records) {
      Alert.alert('No Activity', 'Load an activity first');
      return;
    }
    const peaks = findAllPowerPeaks(currentActivity.records);
    if (peaks.length === 0) {
      Alert.alert('No Peaks Found', 'No sustained high-power periods found. Try Manual Selection instead.');
      return;
    }
    setDetectedEfforts(peaks);
    setSelectedEffortIndex(null);
    setQuickSimResults(new Map());
    Alert.alert('Peaks Found', `Found ${peaks.length} power peaks. These have low confidence - use Manual Selection to refine the exact end point.`);
  };

  const runQuickSim = async (effort: DetectedEffort, index: number) => {
    if (!currentActivity) return;

    try {
      setLoadingEffort(index);

      // Get records for this effort
      const effortRecords = currentActivity.records.slice(effort.startIndex, effort.endIndex + 1);

      // Use the effective effort type (override or auto-detected)
      const effectiveType = getEffectiveEffortType(effort, index);

      console.log(`QuickSim: Running for effort ${index}, type=${effectiveType}, records=${effortRecords.length}`);
      console.log(`QuickSim: Gearing ${gearing.chainring}/${gearing.cog}, wheel=${gearing.wheelCircMm}mm`);
      console.log(`QuickSim: CdA seated=${params.cda_seated}, standing=${params.cda_standing}`);
      // Log any standing segments
      const standingSegments = Object.entries(segmentPositions).filter(([, v]) => v === 'standing');
      console.log(`QuickSim: Standing segments (${standingSegments.length}):`, standingSegments.map(([k]) => k));

      // Run quick simulation with air density override and segment positions
      const result = await fitApi.quickSimulationFromRecords(
        effortRecords,
        effort.endTime,
        gearing,
        { ...params, rho: airDensity },
        effectiveType,
        segmentPositions
      );

      console.log('QuickSim result:', JSON.stringify(result, null, 2));

      if (result.success && result.simulation) {
        // Store the simulation object directly (API returns it nested)
        setQuickSimResults((prev) => new Map(prev).set(index, result.simulation));
      } else {
        console.error('QuickSim failed:', result.error || 'Unknown error');
        Alert.alert('Error', result.error || 'QuickSim failed');
      }
    } catch (error) {
      console.error('QuickSim error:', error);
      Alert.alert('Error', 'Failed to run simulation. Check server connection.');
    } finally {
      setLoadingEffort(null);
    }
  };

  const selectEffortForSimulation = (effort: DetectedEffort, index: number) => {
    if (!currentActivity) return;

    setSelectedEffortIndex(index);
    // Use the effective effort type (override or auto-detected)
    const effectiveType = getEffectiveEffortType(effort, index);
    setEffortType(effectiveType);

    // Get records for this effort
    const effortRecords = currentActivity.records.slice(effort.startIndex, effort.endIndex + 1);
    if (effortRecords.length < 10) {
      console.error('Not enough records for power profile');
      return;
    }

    // Calculate finish distance based on effort type (695 + effortType)
    // F200 finishes at 895m, F150 at 845m, F100 at 795m, F50 at 745m
    const finishDistance = 695 + effectiveType;

    // Calculate gear ratio and rollout (same as web app)
    const gearRatio = gearing.chainring / gearing.cog;
    const wheelCircM = gearing.wheelCircMm / 1000;
    const rolloutM = gearRatio * wheelCircM;

    // Calculate cumulative distance from start (using cadence if available, otherwise speed)
    let cumulativeDistance = 0;
    const recordsWithDistance: Array<{ elapsed_s: number; power_W: number; distance_m: number }> = [];

    for (let i = 0; i < effortRecords.length; i++) {
      const rec = effortRecords[i];
      if (i > 0) {
        const prev = effortRecords[i - 1];
        const dt = rec.elapsed_s - prev.elapsed_s;

        if (rec.cadence_rpm && rec.cadence_rpm > 0) {
          // Use cadence + gearing for accurate distance
          const rpm = rec.cadence_rpm;
          cumulativeDistance += (rpm / 60) * dt * rolloutM;
        } else if (rec.speed_kph && rec.speed_kph > 0) {
          // Fallback to speed
          const speedMs = rec.speed_kph / 3.6;
          cumulativeDistance += speedMs * dt;
        }
      }
      recordsWithDistance.push({
        elapsed_s: rec.elapsed_s,
        power_W: rec.power_W || 0,
        distance_m: cumulativeDistance,
      });
    }

    // Calculate the distance offset to align finish with the effort's finish line
    const totalDistanceCovered = cumulativeDistance;
    const distanceOffset = finishDistance - totalDistanceCovered;

    console.log(`Building power profile: finishDist=${finishDistance}m, covered=${totalDistanceCovered.toFixed(1)}m, offset=${distanceOffset.toFixed(1)}m`);

    // Build power profile on 10m grid from 0 to finishDistance
    const powerProfile: Array<{ s_m: number; P_W: number }> = [];
    for (let s = 0; s <= finishDistance; s += 10) {
      const targetDist = s - distanceOffset;

      // Find closest record to this target distance
      let closestRecord = recordsWithDistance[0];
      let closestDiff = Math.abs(closestRecord.distance_m - targetDist);

      for (const rec of recordsWithDistance) {
        const diff = Math.abs(rec.distance_m - targetDist);
        if (diff < closestDiff) {
          closestDiff = diff;
          closestRecord = rec;
        }
      }

      powerProfile.push({
        s_m: s,
        P_W: Math.round(closestRecord.power_W),
      });
    }

    // Calculate power summary
    const powers = powerProfile.map((p) => p.P_W).filter((p) => p > 0);
    const avgPower = powers.length > 0 ? Math.round(powers.reduce((a, b) => a + b, 0) / powers.length) : 0;
    const maxPower = powers.length > 0 ? Math.max(...powers) : 0;

    console.log(`Power profile: ${powerProfile.length} points, avg=${avgPower}W, max=${maxPower}W`);

    setPowerProfile(powerProfile, {
      totalDistanceM: totalDistanceCovered,
      sRangeStart: 0,
      sRangeEnd: finishDistance,
      gridPoints: powerProfile.length,
      avgPowerW: avgPower,
      maxPowerW: maxPower,
    });

    router.push('/(simulate)/');
  };

  const toggleEffortExpand = (index: number) => {
    if (expandedEffort === index) {
      setExpandedEffort(null);
    } else {
      setExpandedEffort(index);
      // Don't auto-run QuickSim - let user select effort type first since all default to F200
    }
  };

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return mins > 0 ? `${mins}:${secs.padStart(5, '0')}` : `${secs}s`;
  };

  // Format elapsed seconds as Xm:XXs timestamp (e.g. 39m:42s)
  const formatTimestamp = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m${secs.toString().padStart(2, '0')}s`;
  };

  // Sort efforts chronologically for display
  const sortedEfforts = [...detectedEfforts]
    .map((effort, originalIndex) => ({ effort, originalIndex }))
    .sort((a, b) => a.effort.startTime - b.effort.startTime);

  const getEffortTypeLabel = (type: EffortType): string => {
    return `F${type}`;
  };

  const getConfidenceColor = (confidence: number): string => {
    if (confidence >= 70) return colors.success;
    if (confidence >= 50) return colors.warning;
    return colors.danger;
  };

  // Power chart data for selected effort
  const getChartData = (effort: DetectedEffort) => {
    if (!currentActivity) return null;

    const effortRecords = currentActivity.records.slice(effort.startIndex, effort.endIndex + 1);
    // Sample every nth point for performance
    const sampleRate = Math.max(1, Math.floor(effortRecords.length / 50));
    const sampledPower = effortRecords
      .filter((_, i) => i % sampleRate === 0)
      .map((r) => r.power_W);

    return {
      labels: [],
      datasets: [{ data: sampledPower }],
    };
  };

  // Share raw activity/FIT data with dev
  const shareDataWithDev = async () => {
    if (!currentActivity) return;

    const exportData = {
      timestamp: new Date().toISOString(),
      source: currentActivity.source,
      activityName: currentActivity.activityName,

      // Source-specific identifiers
      ...(currentActivity.source === 'strava' && { stravaActivityId: currentActivity.activityId }),
      ...(currentActivity.source === 'fit' && { fitFileId: currentActivity.fitFileId }),

      // FIT metadata if available
      ...(currentActivity.fitMetadata && { fitMetadata: currentActivity.fitMetadata }),

      // Summary stats
      summary: currentActivity.summary,

      // All records (the raw data)
      records: currentActivity.records,
    };

    const jsonString = JSON.stringify(exportData, null, 2);

    try {
      await Share.share({
        message: jsonString,
        title: `${currentActivity.source === 'fit' ? 'FIT' : 'Strava'} Data: ${currentActivity.activityName}`,
      });
    } catch (err) {
      console.error('Share failed:', err);
    }
  };

  if (!currentActivity) {
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>No activity selected</Text>
        <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
          <Text style={styles.backButtonText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container}>
      {/* Return to Connect Data */}
      <TouchableOpacity style={styles.returnButton} onPress={() => router.push('/(data)/')}>
        <Text style={styles.returnButtonText}>← Connect Data</Text>
      </TouchableOpacity>

      {/* Activity Header */}
      <View style={styles.header}>
        <Text style={styles.activityName}>{currentActivity.activityName}</Text>
        <Text style={styles.activityStats}>
          {currentActivity.summary.avg_power}W avg | {currentActivity.summary.max_power}W max
        </Text>
        {/* FIT File Metadata - basic info only */}
        {currentActivity.source === 'fit' && currentActivity.fitMetadata && (
          <Text style={styles.fitMetadataText}>
            {currentActivity.fitMetadata.activity_date && currentActivity.fitMetadata.activity_date}
            {currentActivity.fitMetadata.activity_time && ` ${currentActivity.fitMetadata.activity_time}`}
            {currentActivity.fitMetadata.max_power && ` | ${currentActivity.fitMetadata.max_power}W max`}
          </Text>
        )}
        {/* Share Data with Dev button */}
        <TouchableOpacity style={styles.shareDataButton} onPress={shareDataWithDev}>
          <Text style={styles.shareDataButtonText}>Share Data with Dev</Text>
        </TouchableOpacity>
      </View>

      {/* Effort Type Filter */}
      <View style={styles.filterSection}>
        <Text style={styles.filterLabel}>Detect:</Text>
        {([50, 100, 150, 200] as EffortType[]).map((type) => (
          <TouchableOpacity
            key={type}
            style={[styles.filterButton, effortType === type && styles.filterButtonActive]}
            onPress={() => setEffortType(type)}
            activeOpacity={1}
          >
            <Text style={[styles.filterButtonText, effortType === type && styles.filterButtonTextActive]}>
              F{type}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Gearing Config */}
      <View style={styles.gearingSection}>
        <Text style={styles.sectionTitle}>Gearing</Text>
        <View style={styles.gearingRow}>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Chainring</Text>
            <TouchableOpacity
              style={styles.gearingValue}
              onPress={() => {
                promptValue('Chainring', 'Enter chainring teeth', gearing.chainring.toString(), (value) => {
                  const num = parseInt(value);
                  if (!isNaN(num)) setGearing({ chainring: num });
                });
              }}
            >
              <Text style={styles.gearingValueText}>{gearing.chainring}</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Cog</Text>
            <TouchableOpacity
              style={styles.gearingValue}
              onPress={() => {
                promptValue('Cog', 'Enter cog teeth', gearing.cog.toString(), (value) => {
                  const num = parseInt(value);
                  if (!isNaN(num)) setGearing({ cog: num });
                });
              }}
            >
              <Text style={styles.gearingValueText}>{gearing.cog}</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.gearingInput}>
            <Text style={styles.gearingLabel}>Wheel (mm)</Text>
            <TouchableOpacity
              style={styles.gearingValue}
              onPress={() => {
                promptValue('Wheel Circumference', 'Enter wheel circ in mm', gearing.wheelCircMm.toString(), (value) => {
                  const num = parseInt(value);
                  if (!isNaN(num)) setGearing({ wheelCircMm: num });
                });
              }}
            >
              <Text style={styles.gearingValueText}>{gearing.wheelCircMm}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>

      {/* Environment */}
      <View style={styles.airDensitySection}>
        <Text style={styles.sectionTitle}>Environment</Text>

        {/* Environment inputs row */}
        <View style={styles.envInputsRow}>
          <View style={styles.envInputItem}>
            <Text style={styles.envInputLabel}>Temp (°C)</Text>
            <TextInput
              style={[styles.envTextInput, rhoOverrideMode && styles.envInputDisabled]}
              value={tempText}
              keyboardType="numeric"
              selectTextOnFocus
              editable={!rhoOverrideMode}
              onChangeText={setTempText}
              onBlur={() => {
                const num = parseFloat(tempText);
                if (!isNaN(num) && num > -50 && num < 60) {
                  setTemperature(num);
                } else {
                  setTempText(temperature.toFixed(1));
                }
              }}
            />
          </View>

          <View style={styles.envInputItem}>
            <Text style={styles.envInputLabel}>Press (kPa)</Text>
            <TextInput
              style={[styles.envTextInput, rhoOverrideMode && styles.envInputDisabled]}
              value={pressText}
              keyboardType="numeric"
              selectTextOnFocus
              editable={!rhoOverrideMode}
              onChangeText={setPressText}
              onBlur={() => {
                const num = parseFloat(pressText);
                if (!isNaN(num) && num > 80 && num < 110) {
                  setPressure(num);
                } else {
                  setPressText(pressure.toFixed(2));
                }
              }}
            />
          </View>

          <View style={styles.envInputItem}>
            <Text style={styles.envInputLabel}>Humid (%)</Text>
            <TextInput
              style={[styles.envTextInput, rhoOverrideMode && styles.envInputDisabled]}
              value={humidText}
              keyboardType="numeric"
              selectTextOnFocus
              editable={!rhoOverrideMode}
              onChangeText={setHumidText}
              onBlur={() => {
                const num = parseFloat(humidText);
                if (!isNaN(num) && num >= 0 && num <= 100) {
                  setHumidity(num);
                } else {
                  setHumidText(humidity.toFixed(0));
                }
              }}
            />
          </View>
        </View>

        {/* Calculated/Override rho display */}
        <View style={styles.rhoDisplayRow}>
          <View style={styles.rhoDisplayLeft}>
            <Text style={styles.rhoLabel}>ρ (kg/m³)</Text>
            <TextInput
              style={[styles.rhoTextInput, rhoOverrideMode && styles.rhoTextInputOverride]}
              value={rhoText}
              keyboardType="numeric"
              selectTextOnFocus
              onFocus={() => {
                // Auto-enable override mode when rho input is focused
                if (!rhoOverrideMode) {
                  setRhoOverrideMode(true);
                }
              }}
              onChangeText={setRhoText}
              onBlur={() => {
                const num = parseFloat(rhoText);
                if (!isNaN(num) && num > 0 && num < 2) {
                  setAirDensity(num);
                  setRhoText(num.toFixed(4));
                } else {
                  setRhoText(airDensity.toFixed(4));
                }
              }}
            />
          </View>

          <TouchableOpacity
            style={[styles.rhoModeToggle, rhoOverrideMode && styles.rhoModeToggleOverride]}
            onPress={() => {
              if (rhoOverrideMode) {
                // Switching back to calculated mode - recalculate from environment
                setRhoOverrideMode(false);
              }
            }}
          >
            <Text style={[styles.rhoModeToggleText, rhoOverrideMode && styles.rhoModeToggleTextOverride]}>
              {rhoOverrideMode ? 'Override' : 'Calculated'}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.rhoResetButton}
            onPress={() => {
              setTemperature(20);
              setPressure(101.0);
              setHumidity(33);
              setRhoOverrideMode(false);
            }}
          >
            <Text style={styles.rhoResetButtonText}>Reset</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Detection Settings */}
      <View style={styles.detectionSection}>
        <Text style={styles.sectionTitle}>Detection Settings</Text>

        {/* Sensitivity Selector */}
        <View style={styles.sensitivityRow}>
          <Text style={styles.sensitivityLabel}>Sensitivity:</Text>
          <View style={styles.sensitivityButtons}>
            {(['low', 'medium', 'high'] as DetectionSensitivity[]).map((level) => (
              <TouchableOpacity
                key={level}
                style={[
                  styles.sensitivityButton,
                  detectionSensitivity === level && styles.sensitivityButtonActive,
                ]}
                onPress={() => setDetectionSensitivity(level)}
              >
                <Text
                  style={[
                    styles.sensitivityButtonText,
                    detectionSensitivity === level && styles.sensitivityButtonTextActive,
                  ]}
                >
                  {level.charAt(0).toUpperCase() + level.slice(1)}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Peak Finder Button */}
        <TouchableOpacity style={styles.peakFinderButton} onPress={runPeakFinder}>
          <Text style={styles.peakFinderButtonText}>Find All Power Peaks</Text>
          <Text style={styles.peakFinderButtonHint}>Use if auto-detect misses efforts</Text>
        </TouchableOpacity>
      </View>

      {/* Detected Efforts */}
      <View style={styles.effortsSection}>
        <Text style={styles.sectionTitle}>
          Detected Efforts ({detectedEfforts.length})
        </Text>

        {detectedEfforts.length === 0 ? (
          <Text style={styles.noEffortsText}>No flying 200 efforts detected</Text>
        ) : (
          sortedEfforts.map(({ effort, originalIndex: index }) => (
            <TouchableOpacity
              key={index}
              style={[
                styles.effortCard,
                selectedEffortIndex === index && styles.effortCardSelected,
              ]}
              onPress={() => toggleEffortExpand(index)}
            >
              {/* Effort Header */}
              <View style={styles.effortHeader}>
                <View style={styles.effortHeaderLeft}>
                  <View style={[styles.confidenceBadge, { backgroundColor: getConfidenceColor(effort.confidence) }]}>
                    <Text style={styles.confidenceText}>{effort.confidence}%</Text>
                  </View>
                  <Text style={styles.effortTypeBadge}>
                    {getEffortTypeLabel(getEffectiveEffortType(effort, index))}
                    {effortTypeOverrides.has(index) ? '' : '*'}
                  </Text>
                  {currentActivity && isEffortAlreadySaved(
                    savedEfforts,
                    currentActivity.source,
                    currentActivity.activityId,
                    currentActivity.fitFileId,
                    effort.startIndex,
                    effort.endIndex,
                  ) && (
                    <View style={styles.savedBadge}>
                      <Text style={styles.savedBadgeText}>Saved</Text>
                    </View>
                  )}
                </View>
                <View style={styles.effortHeaderRight}>
                  <Text style={styles.effortTimestamp}>
                    {formatTimestamp(effort.startTime)} to {formatTimestamp(effort.endTime)}
                  </Text>
                  <Text style={styles.effortTimestamp}>
                    Rows {effort.startIndex}–{effort.endIndex}
                  </Text>
                  <Text style={styles.effortDuration}>{formatTime(effort.duration)}</Text>
                </View>
              </View>

              {/* Effort Stats */}
              <View style={styles.effortStats}>
                <View style={styles.statItem}>
                  <Text style={styles.statValue}>{effort.avgPower}W</Text>
                  <Text style={styles.statLabel}>Avg</Text>
                </View>
                <View style={styles.statItem}>
                  <Text style={styles.statValue}>{effort.maxPower}W</Text>
                  <Text style={styles.statLabel}>Max</Text>
                </View>
                <View style={styles.statItem}>
                  <Text style={styles.statValue}>{effort.endPower}W</Text>
                  <Text style={styles.statLabel}>End</Text>
                </View>
              </View>

              {/* Expanded Section */}
              {expandedEffort === index && (
                <View style={styles.expandedSection}>
                  {/* Effort Type Selector - manually override auto-detected type */}
                  <View style={styles.effortTypeSelector}>
                    <Text style={styles.effortTypeSelectorLabel}>Effort Type:</Text>
                    <View style={styles.effortTypeButtons}>
                      {([50, 100, 150, 200] as EffortType[]).map((type) => {
                        const isSelected = getEffectiveEffortType(effort, index) === type;
                        const isAutoDetected = effort.estimatedEffortType === type && !effortTypeOverrides.has(index);
                        return (
                          <TouchableOpacity
                            key={type}
                            style={[
                              styles.effortTypeButton,
                              isSelected && styles.effortTypeButtonSelected,
                            ]}
                            onPress={() => setEffortTypeOverride(index, type)}
                          >
                            <Text
                              style={[
                                styles.effortTypeButtonText,
                                isSelected && styles.effortTypeButtonTextSelected,
                              ]}
                            >
                              F{type}{isAutoDetected ? '*' : ''}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  </View>

                  {/* Power Chart */}
                  {getChartData(effort) && (
                    <LineChart
                      data={getChartData(effort)!}
                      width={screenWidth - 64}
                      height={120}
                      chartConfig={{
                        backgroundColor: colors.bg1,
                        backgroundGradientFrom: colors.bg1,
                        backgroundGradientTo: colors.bg1,
                        color: (opacity = 1) => `rgba(74, 222, 128, ${opacity})`,
                        strokeWidth: 2,
                        propsForDots: { r: '0' },
                      }}
                      bezier
                      withVerticalLabels={false}
                      withHorizontalLabels={false}
                      withDots={false}
                      style={styles.chart}
                    />
                  )}

                  {/* QuickSim Results */}
                  {loadingEffort === index ? (
                    <ActivityIndicator color="#4da6ff" style={styles.loader} />
                  ) : (
                    <>
                      {quickSimResults.has(index) && quickSimResults.get(index)?.T_200 != null && (
                        <View style={styles.quickSimResults}>
                          <Text style={styles.quickSimTitle}>Quick Simulation</Text>
                          <View style={styles.quickSimRow}>
                            <View style={styles.quickSimItem}>
                              <Text style={styles.quickSimValue}>
                                {(quickSimResults.get(index)?.T_200 ?? 0).toFixed(3)}s
                              </Text>
                              <Text style={styles.quickSimLabel}>T_{getEffectiveEffortType(effort, index)}</Text>
                            </View>
                            <View style={styles.quickSimItem}>
                              <Text style={styles.quickSimValue}>
                                {(quickSimResults.get(index)?.v_200_entry_kph ?? 0).toFixed(1)}
                              </Text>
                              <Text style={styles.quickSimLabel}>Entry kph</Text>
                            </View>
                            <View style={styles.quickSimItem}>
                              <Text style={styles.quickSimValue}>
                                {(quickSimResults.get(index)?.v_200_exit_kph ?? 0).toFixed(1)}
                              </Text>
                              <Text style={styles.quickSimLabel}>Exit kph</Text>
                            </View>
                          </View>
                          {/* Splits - truncate to effort type (e.g., F100 = 2 splits, F200 = 4 splits) */}
                          {quickSimResults.get(index)?.splits_200 && (
                            <View style={styles.splitsRow}>
                              {(quickSimResults.get(index)?.splits_200 ?? [])
                                .slice(0, getEffectiveEffortType(effort, index) / 50)
                                .map((split, i) => (
                                <View key={i} style={styles.splitItem}>
                                  <Text style={styles.splitValue}>{(split ?? 0).toFixed(3)}</Text>
                                  <Text style={styles.splitLabel}>{(i + 1) * 50}m</Text>
                                </View>
                              ))}
                            </View>
                          )}
                        </View>
                      )}
                      {/* Run/Refresh QuickSim Button */}
                      <TouchableOpacity
                        style={[
                          styles.runSimButton,
                          quickSimResults.has(index) && styles.refreshSimButton,
                        ]}
                        onPress={() => runQuickSim(effort, index)}
                      >
                        <Text style={styles.runSimButtonText}>
                          {quickSimResults.has(index) ? 'Refresh QuickSim' : 'Run QuickSim'}
                        </Text>
                      </TouchableOpacity>
                    </>
                  )}

                  {/* Use in Simulation Button */}
                  <TouchableOpacity
                    style={styles.useInSimButton}
                    onPress={() => selectEffortForSimulation(effort, index)}
                  >
                    <Text style={styles.useInSimButtonText}>Use in Simulation</Text>
                  </TouchableOpacity>
                </View>
              )}
            </TouchableOpacity>
          ))
        )}
      </View>
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
  emptyContainer: {
    flex: 1,
    backgroundColor: colors.bg0,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textSecondary,
    fontSize: 18,
    marginBottom: 20,
  },
  backButton: {
    backgroundColor: colors.accent,
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 8,
  },
  backButtonText: {
    color: colors.textPrimary,
    fontFamily: fonts.sansSemiBold,
  },
  header: {
    padding: 16,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  activityName: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    marginBottom: 4,
  },
  activityStats: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  fitMetadataText: {
    color: '#6b8cb3',
    fontSize: 12,
    marginTop: 4,
  },
  shareDataButton: {
    marginTop: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
    backgroundColor: colors.bg0,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
    alignSelf: 'flex-start',
  },
  shareDataButtonText: {
    color: colors.textSecondary,
    fontSize: 12,
  },
  filterSection: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  filterLabel: {
    color: colors.textSecondary,
    fontSize: 14,
    marginRight: 12,
  },
  filterButton: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 16,
    backgroundColor: colors.bg0,
    marginRight: 8,
  },
  filterButtonActive: {
    backgroundColor: colors.accent,
  },
  filterButtonText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  filterButtonTextActive: {
    color: colors.textPrimary,
  },
  gearingSection: {
    padding: 16,
    backgroundColor: colors.bg1,
    marginTop: 8,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
    textTransform: 'uppercase',
    marginBottom: 12,
  },
  gearingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  gearingInput: {
    flex: 1,
    marginHorizontal: 4,
  },
  gearingLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 4,
  },
  gearingValue: {
    backgroundColor: colors.bg0,
    padding: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  gearingValueText: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  // Environment section
  airDensitySection: {
    padding: 16,
    backgroundColor: colors.bg1,
    marginTop: 8,
  },
  envInputsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 8,
    marginBottom: 12,
  },
  envInputItem: {
    flex: 1,
  },
  envInputLabel: {
    color: colors.textSecondary,
    fontSize: 10,
    marginBottom: 4,
    textAlign: 'center',
  },
  envTextInput: {
    backgroundColor: colors.bg0,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.textPrimary,
    fontSize: 15,
    fontFamily: fonts.sansSemiBold,
    textAlign: 'center',
  },
  envInputDisabled: {
    opacity: 0.4,
  },
  rhoDisplayRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rhoDisplayLeft: {
    flex: 1,
  },
  rhoLabel: {
    color: colors.textSecondary,
    fontSize: 10,
    marginBottom: 4,
  },
  rhoTextInput: {
    backgroundColor: colors.bg0,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  rhoTextInputOverride: {
    borderColor: colors.danger,
    backgroundColor: '#f59e0b20',
  },
  rhoValueText: {
    color: colors.success,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    fontVariant: ['tabular-nums'],
  },
  rhoModeToggle: {
    backgroundColor: colors.bg0,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rhoModeToggleOverride: {
    backgroundColor: '#ef444420',
    borderColor: colors.danger,
  },
  rhoModeToggleText: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  rhoModeToggleTextOverride: {
    color: colors.danger,
  },
  rhoResetButton: {
    backgroundColor: colors.bg0,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rhoResetButtonText: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansMedium,
  },
  effortsSection: {
    padding: 16,
  },
  noEffortsText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: 'center',
    marginTop: 20,
  },
  effortCard: {
    backgroundColor: colors.bg1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  effortCardSelected: {
    borderWidth: 2,
    borderColor: colors.accent,
  },
  effortHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  effortHeaderLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  confidenceBadge: {
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: 12,
    marginRight: 8,
  },
  confidenceText: {
    color: '#000',
    fontSize: 12,
    fontFamily: fonts.sansBold,
  },
  effortTypeBadge: {
    color: colors.accent,
    fontSize: 14,
    fontFamily: fonts.sansBold,
  },
  effortHeaderRight: {
    alignItems: 'flex-end',
  },
  effortTimestamp: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 2,
  },
  effortDuration: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  effortStats: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  statItem: {
    alignItems: 'center',
  },
  statValue: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  statLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginTop: 2,
  },
  expandedSection: {
    marginTop: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  effortTypeSelector: {
    marginBottom: 12,
  },
  effortTypeSelectorLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: 6,
  },
  effortTypeButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  effortTypeButton: {
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: colors.bg0,
    borderWidth: 1,
    borderColor: colors.border,
  },
  effortTypeButtonSelected: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  effortTypeButtonText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  effortTypeButtonTextSelected: {
    color: colors.textPrimary,
  },
  chart: {
    marginVertical: 8,
    borderRadius: 8,
  },
  loader: {
    marginVertical: 20,
  },
  quickSimResults: {
    marginTop: 12,
  },
  quickSimTitle: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 8,
  },
  quickSimRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 12,
  },
  quickSimItem: {
    alignItems: 'center',
  },
  quickSimValue: {
    color: colors.success,
    fontSize: 16,
    fontFamily: fonts.sansBold,
  },
  quickSimLabel: {
    color: colors.textSecondary,
    fontSize: 10,
    marginTop: 2,
  },
  splitsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    backgroundColor: colors.bg0,
    padding: 12,
    borderRadius: 8,
  },
  splitItem: {
    alignItems: 'center',
  },
  splitValue: {
    color: colors.warning,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  splitLabel: {
    color: colors.textSecondary,
    fontSize: 10,
  },
  runSimButton: {
    backgroundColor: colors.accent,
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 12,
  },
  refreshSimButton: {
    backgroundColor: '#6366f1',
  },
  runSimButtonText: {
    color: colors.textPrimary,
    fontFamily: fonts.sansSemiBold,
  },
  useInSimButton: {
    backgroundColor: colors.success,
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 12,
  },
  useInSimButtonText: {
    color: colors.textPrimary,
    fontFamily: fonts.sansBold,
    fontSize: 16,
  },
  // Detection settings section
  detectionSection: {
    padding: 16,
    backgroundColor: colors.bg1,
    marginTop: 8,
  },
  sensitivityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  sensitivityLabel: {
    color: colors.textSecondary,
    fontSize: 14,
    marginRight: 12,
  },
  sensitivityButtons: {
    flexDirection: 'row',
    flex: 1,
    gap: 8,
  },
  sensitivityButton: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: colors.bg0,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  sensitivityButtonActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  sensitivityButtonText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  sensitivityButtonTextActive: {
    color: colors.textPrimary,
  },
  peakFinderButton: {
    backgroundColor: '#6366f1',
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  peakFinderButtonText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  peakFinderButtonHint: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 11,
    marginTop: 2,
  },
  savedBadge: {
    backgroundColor: colors.accentDim,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    marginLeft: 6,
  },
  savedBadgeText: {
    color: colors.textPrimary,
    fontSize: 10,
    fontFamily: fonts.sansBold,
  },
});

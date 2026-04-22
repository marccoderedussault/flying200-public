import { colors, fonts, spacing } from '../../theme';
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useAppStore, TRACK_SEGMENTS } from '../../store/simulationStore';
import { simulationApi } from '../../api/client';

// Power and CdA variations for sensitivity matrix
const POWER_DELTAS = [-50, -25, 0, 25, 50]; // Watts
const CDA_DELTAS = [0.02, 0.01, 0, -0.01, -0.02]; // CdA adjustments

export default function SensitivityScreen() {
  const {
    lastSimulationT200,
    lastSimulationParams,
    lastSimulationProfile,
    lastSimulationEffortType,
    lastSimulationKitConfig,
  } = useAppStore();

  // Segment selector for where power deltas start
  const POWER_START_SEGMENTS = TRACK_SEGMENTS.filter(
    seg => seg.startM >= 0 && seg.startM < 895
  );
  const [powerStartSegmentId, setPowerStartSegmentId] = useState('lap2_back_1'); // Default: 485m
  const selectedPowerStartSegment = POWER_START_SEGMENTS.find(s => s.id === powerStartSegmentId) || POWER_START_SEGMENTS[0];

  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<(number | null)[][]>([]);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [showAbsoluteTime, setShowAbsoluteTime] = useState(false); // Toggle between delta and absolute time
  const [retrying, setRetrying] = useState(false);

  // Run sensitivity analysis
  const runSensitivityAnalysis = async () => {
    if (!lastSimulationParams || !lastSimulationProfile || lastSimulationProfile.length === 0) {
      Alert.alert('Error', 'Please run a simulation first to establish a baseline.');
      return;
    }

    if (!lastSimulationT200) {
      Alert.alert('Error', 'No baseline time found. Please run a simulation first.');
      return;
    }

    setRunning(true);
    setProgress({ current: 0, total: POWER_DELTAS.length * CDA_DELTAS.length });

    const matrixResults: (number | null)[][] = [];

    try {
      // Loop through CdA deltas (rows)
      for (let rowIdx = 0; rowIdx < CDA_DELTAS.length; rowIdx++) {
        const cdaDelta = CDA_DELTAS[rowIdx];
        const row: (number | null)[] = [];

        // Loop through power deltas (columns)
        for (let colIdx = 0; colIdx < POWER_DELTAS.length; colIdx++) {
          const powerDelta = POWER_DELTAS[colIdx];

          // Update progress
          const currentCell = rowIdx * POWER_DELTAS.length + colIdx + 1;
          setProgress({ current: currentCell, total: POWER_DELTAS.length * CDA_DELTAS.length });

          // Skip baseline - we already have this value
          if (powerDelta === 0 && cdaDelta === 0) {
            row.push(0); // Time improvement is 0 for baseline
            continue;
          }

          try {
            // Apply power delta to profile from selected segment onward
            // AND apply CdA delta to the profile (simulation reads CdA from profile, not params)
            const modifiedProfile = lastSimulationProfile.map(point => {
              let newPower = point.P_W;

              // Only apply power delta if we're at or past the selected start segment
              if (point.s_m >= selectedPowerStartSegment.startM) {
                newPower += powerDelta;
              }

              return {
                ...point,
                P_W: Math.max(0, newPower), // Ensure power doesn't go negative
                CdA_m2: point.CdA_m2 + cdaDelta, // Apply CdA delta to profile
              };
            });

            // Run simulation with modified parameters - use EXACT params from last simulation
            const result = await simulationApi.run(
              { rows: modifiedProfile },
              {
                mass_kg: lastSimulationParams.mass_kg,
                rho: lastSimulationParams.rho,
                crr: lastSimulationParams.crr,
                cda_seated: lastSimulationParams.cda_seated + cdaDelta,
                cda_standing: lastSimulationParams.cda_standing + cdaDelta,
                cda_bend_factor: lastSimulationParams.cda_bend_factor,
                v0_mps: lastSimulationParams.v0_mps,
                drivetrain_eff: lastSimulationParams.drivetrain_eff,
                cp_W: lastSimulationParams.cp_W,
                wPrime_J: lastSimulationParams.wPrime_J,
              }
            );

            if (result.success && result.base?.splits_200) {
              // Calculate time from splits based on effort type
              // F200=4 splits, F150=3 splits, F100=2 splits, F50=1 split
              const effortType = lastSimulationEffortType || 200;
              const numSplits = effortType / 50;
              const time = result.base.splits_200.slice(0, numSplits).reduce((a: number, b: number) => a + b, 0);
              // Calculate time improvement (negative = faster)
              const timeImprovement = time - lastSimulationT200;
              row.push(timeImprovement);
            } else {
              row.push(null);
            }
          } catch (err) {
            console.error(`Simulation error [Power:${powerDelta}W, CdA:${cdaDelta}]:`, err);
            // Log additional details if available
            if (err instanceof Error) {
              console.error('Error message:', err.message);
              console.error('Error stack:', err.stack);
            }
            row.push(null);
          }
        }

        matrixResults.push(row);
      }

      setResults(matrixResults);

      // Check for failed cells and retry them
      const failedCells: Array<{ rowIdx: number; colIdx: number; cdaDelta: number; powerDelta: number }> = [];
      for (let rowIdx = 0; rowIdx < CDA_DELTAS.length; rowIdx++) {
        for (let colIdx = 0; colIdx < POWER_DELTAS.length; colIdx++) {
          if (matrixResults[rowIdx][colIdx] === null) {
            failedCells.push({
              rowIdx,
              colIdx,
              cdaDelta: CDA_DELTAS[rowIdx],
              powerDelta: POWER_DELTAS[colIdx],
            });
          }
        }
      }

      // Retry failed cells if any
      if (failedCells.length > 0) {
        console.log(`Retrying ${failedCells.length} failed simulations...`);
        setRetrying(true);
        setProgress({ current: 0, total: failedCells.length });

        for (let i = 0; i < failedCells.length; i++) {
          const { rowIdx, colIdx, cdaDelta, powerDelta } = failedCells[i];
          setProgress({ current: i + 1, total: failedCells.length });

          try {
            // Apply power delta to profile from selected segment onward
            const modifiedProfile = lastSimulationProfile.map(point => {
              let newPower = point.P_W;
              if (point.s_m >= selectedPowerStartSegment.startM) {
                newPower += powerDelta;
              }
              return {
                ...point,
                P_W: Math.max(0, newPower),
                CdA_m2: point.CdA_m2 + cdaDelta,
              };
            });

            // Run simulation with modified parameters
            const result = await simulationApi.run(
              { rows: modifiedProfile },
              {
                mass_kg: lastSimulationParams.mass_kg,
                rho: lastSimulationParams.rho,
                crr: lastSimulationParams.crr,
                cda_seated: lastSimulationParams.cda_seated + cdaDelta,
                cda_standing: lastSimulationParams.cda_standing + cdaDelta,
                cda_bend_factor: lastSimulationParams.cda_bend_factor,
                v0_mps: lastSimulationParams.v0_mps,
                drivetrain_eff: lastSimulationParams.drivetrain_eff,
                cp_W: lastSimulationParams.cp_W,
                wPrime_J: lastSimulationParams.wPrime_J,
              }
            );

            if (result.success && result.base?.splits_200) {
              const effortType = lastSimulationEffortType || 200;
              const numSplits = effortType / 50;
              const time = result.base.splits_200.slice(0, numSplits).reduce((a: number, b: number) => a + b, 0);
              const timeImprovement = time - lastSimulationT200;
              matrixResults[rowIdx][colIdx] = timeImprovement;
            }
          } catch (err) {
            console.error(`Retry failed [Power:${powerDelta}W, CdA:${cdaDelta}]:`, err);
          }
        }

        // Update results with retried values
        setResults([...matrixResults]);
        setRetrying(false);
      }
    } catch (error) {
      console.error('Sensitivity analysis error:', error);
      Alert.alert('Error', 'Failed to complete sensitivity analysis');
    } finally {
      setRunning(false);
      setRetrying(false);
    }
  };

  const hasResults = results.length > 0;
  const baselineTime = lastSimulationT200 || 0;

  return (
    <ScrollView style={styles.container}>
      {/* Status Banner */}
      <View style={styles.statusBanner}>
        {lastSimulationT200 ? (
          <>
            <Text style={styles.statusText}>
              Baseline T_200: {lastSimulationT200.toFixed(3)}s
            </Text>
            {lastSimulationKitConfig && (
              <Text style={styles.statusTextKit}>
                Kit: {lastSimulationKitConfig.name} ({lastSimulationKitConfig.cdaSeated.toFixed(2)} / {lastSimulationKitConfig.cdaStanding.toFixed(2)})
              </Text>
            )}
          </>
        ) : (
          <Text style={styles.statusTextWarn}>
            No baseline. Run a simulation first.
          </Text>
        )}
      </View>

      {/* Info Box */}
      <View style={styles.infoBox}>
        <Text style={styles.infoTitle}>Sensitivity Analysis</Text>
        <Text style={styles.infoText}>
          Explore how changes in power and aerodynamics (CdA) affect your Flying 200 time.
          Power deltas apply from the selected segment onward. Runs 24 scenarios (baseline skipped).
        </Text>
        {running && (
          <View style={styles.warningBox}>
            <Text style={styles.warningText}>
              ⚠️ Stay in this app while analysis runs. Switching apps may cause simulations to fail.
            </Text>
          </View>
        )}
      </View>

      {/* Power Start Segment Selector */}
      <View style={styles.configSection}>
        <Text style={styles.configSectionLabel}>Power Delta Start Point</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.segmentSelector}>
          {POWER_START_SEGMENTS.map(seg => (
            <TouchableOpacity
              key={seg.id}
              style={[
                styles.segmentOption,
                powerStartSegmentId === seg.id && styles.segmentOptionSelected
              ]}
              onPress={() => setPowerStartSegmentId(seg.id)}
            >
              <Text style={[
                styles.segmentOptionText,
                powerStartSegmentId === seg.id && styles.segmentOptionTextSelected
              ]}>
                {seg.label.replace('Lap ', 'L').replace(' Straight', '').replace('(1st half)', '1').replace('(2nd half)', '2').replace('Turn ', 'T').replace(' (into start)', '')}
              </Text>
              <Text style={styles.segmentOptionDistance}>{seg.startM}m</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <Text style={styles.configHint}>
          Power changes apply from: {selectedPowerStartSegment.label} ({selectedPowerStartSegment.startM}m)
        </Text>
      </View>

      {/* Run Button */}
      {running ? (
        <View style={styles.runningContainer}>
          <ActivityIndicator color="#4da6ff" size="large" />
          <Text style={styles.runningText}>
            {retrying
              ? `Retrying failed simulations... ${progress.current}/${progress.total}`
              : `Running analysis... ${progress.current}/${progress.total}`
            }
          </Text>
        </View>
      ) : (
        <TouchableOpacity
          style={[styles.runButton, (!lastSimulationProfile || !lastSimulationT200) && styles.buttonDisabled]}
          onPress={runSensitivityAnalysis}
          disabled={!lastSimulationProfile || !lastSimulationT200}
        >
          <Text style={styles.runButtonText}>Run Sensitivity Analysis</Text>
        </TouchableOpacity>
      )}

      {/* Results Matrix */}
      {hasResults && (
        <View style={styles.resultsCard}>
          <View style={styles.resultsHeader}>
            <View>
              <Text style={styles.resultsTitle}>Sensitivity Matrix</Text>
              <Text style={styles.resultsSubtitle}>
                {showAbsoluteTime
                  ? `Final T_200 times (baseline: ${baselineTime.toFixed(3)}s)`
                  : `Time change vs baseline ${baselineTime.toFixed(3)}s`
                }
              </Text>
            </View>
            <TouchableOpacity
              style={styles.toggleButton}
              onPress={() => setShowAbsoluteTime(!showAbsoluteTime)}
            >
              <Text style={styles.toggleButtonText}>
                {showAbsoluteTime ? 'Show Δ' : 'Show Time'}
              </Text>
            </TouchableOpacity>
          </View>

          {/* Matrix Container */}
          <ScrollView horizontal showsHorizontalScrollIndicator={true}>
            <View style={styles.matrixContainer}>
              {/* Header Row - Power Deltas */}
              <View style={styles.matrixRow}>
                <View style={styles.matrixCornerCell}>
                  <Text style={styles.matrixHeaderTextSmall}>Power Δ</Text>
                  <Text style={styles.matrixHeaderTextSmall}>CdA Δ</Text>
                </View>
                {POWER_DELTAS.map(delta => (
                  <View key={`header-${delta}`} style={styles.matrixHeaderCell}>
                    <Text style={styles.matrixHeaderText}>
                      {delta >= 0 ? '+' : ''}{delta}W
                    </Text>
                  </View>
                ))}
              </View>

              {/* Data Rows */}
              {CDA_DELTAS.map((cdaDelta, rowIdx) => (
                <View key={`row-${rowIdx}`} style={styles.matrixRow}>
                  {/* Row Header - CdA Delta */}
                  <View style={styles.matrixRowHeaderCell}>
                    <Text style={styles.matrixRowHeaderText}>
                      {cdaDelta >= 0 ? '+' : ''}{cdaDelta.toFixed(2)}
                    </Text>
                  </View>

                  {/* Data Cells */}
                  {POWER_DELTAS.map((powerDelta, colIdx) => {
                    const delta = results[rowIdx]?.[colIdx];
                    const isBaseline = cdaDelta === 0 && powerDelta === 0;

                    // Calculate display value (either delta or absolute time)
                    const displayValue = showAbsoluteTime && delta !== null
                      ? baselineTime + delta  // Absolute time
                      : delta;                 // Delta

                    // Color coding based on delta (not display value)
                    const cellStyle = isBaseline
                      ? styles.matrixCellBaseline
                      : delta !== null && delta < 0
                      ? styles.matrixCellImproved
                      : delta !== null && delta > 0
                      ? styles.matrixCellSlower
                      : styles.matrixCell;

                    const textStyle = isBaseline
                      ? styles.matrixCellTextBaseline
                      : delta !== null && delta < 0
                      ? styles.matrixCellTextImproved
                      : delta !== null && delta > 0
                      ? styles.matrixCellTextSlower
                      : styles.matrixCellText;

                    return (
                      <View key={`cell-${rowIdx}-${colIdx}`} style={[styles.matrixCell, cellStyle]}>
                        <Text style={textStyle}>
                          {displayValue !== null
                            ? showAbsoluteTime
                              ? `${displayValue.toFixed(3)}`       // Absolute: show seconds with 3 decimals
                              : `${displayValue >= 0 ? '+' : ''}${(displayValue * 1000).toFixed(0)}`  // Delta: show ms
                            : 'ERR'}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              ))}
            </View>
          </ScrollView>

          <Text style={styles.matrixLegend}>
            {showAbsoluteTime
              ? 'Final T_200 times in seconds. Green = faster than baseline, Red = slower'
              : 'Time changes in milliseconds. Green = faster, Red = slower'
            }
          </Text>
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
  statusTextKit: {
    color: colors.accent,
    fontSize: 12,
    textAlign: 'center',
    marginTop: 4,
  },
  infoBox: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 8,
    borderRadius: 8,
    padding: 12,
  },
  infoTitle: {
    color: colors.accent,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 8,
  },
  infoText: {
    color: colors.textSecondary,
    fontSize: 12,
    lineHeight: 18,
  },
  warningBox: {
    backgroundColor: '#7f1d1d',
    marginTop: 12,
    padding: 10,
    borderRadius: 6,
    borderLeftWidth: 3,
    borderLeftColor: '#fca5a5',
  },
  warningText: {
    color: '#fca5a5',
    fontSize: 11,
    lineHeight: 16,
  },
  configSection: {
    marginHorizontal: 8,
    marginTop: 12,
    marginBottom: 8,
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
  configHint: {
    color: colors.textSecondary,
    fontSize: 11,
    marginTop: 4,
  },
  runButton: {
    backgroundColor: colors.success,
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  runButtonText: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  runningContainer: {
    marginHorizontal: 16,
    marginTop: 16,
    padding: 16,
    backgroundColor: colors.bg1,
    borderRadius: 12,
    alignItems: 'center',
  },
  runningText: {
    color: colors.accent,
    fontSize: 14,
    marginTop: 8,
  },
  resultsCard: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginTop: 16,
    borderRadius: 12,
    padding: 16,
  },
  resultsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 16,
  },
  resultsTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    marginBottom: 4,
  },
  resultsSubtitle: {
    color: colors.textSecondary,
    fontSize: 12,
  },
  toggleButton: {
    backgroundColor: colors.seated,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 6,
  },
  toggleButtonText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  matrixContainer: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    overflow: 'hidden',
  },
  matrixRow: {
    flexDirection: 'row',
  },
  matrixCornerCell: {
    width: 50,
    padding: 3,
    backgroundColor: colors.bg0,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  matrixHeaderCell: {
    width: 50,
    padding: 3,
    backgroundColor: colors.bg0,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  matrixRowHeaderCell: {
    width: 50,
    padding: 3,
    backgroundColor: colors.bg0,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  matrixHeaderText: {
    color: colors.accent,
    fontSize: 10,
    fontFamily: fonts.sansSemiBold,
  },
  matrixHeaderTextSmall: {
    color: colors.accent,
    fontSize: 8,
    fontFamily: fonts.sansSemiBold,
  },
  matrixRowHeaderText: {
    color: colors.accent,
    fontSize: 10,
    fontFamily: fonts.sansSemiBold,
  },
  matrixCell: {
    width: 50,
    padding: 3,
    backgroundColor: colors.bg1,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  matrixCellBaseline: {
    backgroundColor: colors.border,
  },
  matrixCellImproved: {
    backgroundColor: '#064e3b',
  },
  matrixCellSlower: {
    backgroundColor: '#7f1d1d',
  },
  matrixCellText: {
    color: colors.textPrimary,
    fontSize: 11,
    fontFamily: fonts.sansMedium,
  },
  matrixCellTextBaseline: {
    color: colors.warning,
    fontSize: 11,
    fontFamily: fonts.sansBold,
  },
  matrixCellTextImproved: {
    color: colors.success,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  matrixCellTextSlower: {
    color: '#fca5a5',
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  matrixLegend: {
    color: colors.textSecondary,
    fontSize: 11,
    marginTop: 8,
    textAlign: 'center',
    fontStyle: 'italic',
  },
  bottomPadding: {
    height: 40,
  },
});

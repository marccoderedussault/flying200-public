import { colors, fonts, spacing } from '../../theme';
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useAppStore, DEFAULT_PARAMS, DEFAULT_GEARING, TRACK_SEGMENTS, DEFAULT_SEGMENT_POSITIONS, TRACK_OPTIONS } from '../../store/simulationStore';
import type { SegmentPosition } from '../../store/simulationStore';

// Collapsible section wrapper
interface CollapsibleSectionProps {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}

function CollapsibleSection({ title, children, defaultExpanded = false }: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <View style={styles.section}>
      <TouchableOpacity style={styles.sectionHeader} onPress={() => setExpanded(!expanded)}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.sectionToggle}>{expanded ? '\u2212' : '+'}</Text>
      </TouchableOpacity>
      {expanded && <View style={styles.sectionContent}>{children}</View>}
    </View>
  );
}

interface SettingRowProps {
  label: string;
  value: string | number;
  unit?: string;
  onChangeText: (value: string) => void;
  isInteger?: boolean;
  helpText?: string;
}

function SettingRow({ label, value, unit, onChangeText, isInteger = false, helpText }: SettingRowProps) {
  const [localValue, setLocalValue] = useState(value.toString());
  const [isFocused, setIsFocused] = useState(false);

  React.useEffect(() => {
    if (!isFocused) {
      setLocalValue(value.toString());
    }
  }, [value, isFocused]);

  const handleBlur = () => {
    setIsFocused(false);
    const num = isInteger ? parseInt(localValue) : parseFloat(localValue);
    if (!isNaN(num)) {
      onChangeText(num.toString());
      setLocalValue(num.toString());
    } else {
      setLocalValue(value.toString());
    }
  };
  return (
    <View style={styles.settingRow}>
      <View style={styles.settingLabelWrapper}>
        <View style={styles.labelWithHelp}>
          <Text style={styles.settingLabel}>{label}</Text>
          {helpText && (
            <TouchableOpacity
              style={styles.helpButton}
              onPress={() => Alert.alert(label, helpText)}
            >
              <Text style={styles.helpButtonText}>?</Text>
            </TouchableOpacity>
          )}
        </View>
        {unit && <Text style={styles.settingUnit}>{unit}</Text>}
      </View>
      <TextInput
        style={styles.settingInput}
        value={localValue}
        onChangeText={setLocalValue}
        onFocus={() => setIsFocused(true)}
        onBlur={handleBlur}
        keyboardType="decimal-pad"
      />
    </View>
  );
}

// Segment position toggle row
interface SegmentRowProps {
  label: string;
  position: SegmentPosition;
  onToggle: () => void;
  isTimedSection?: boolean;
  locked?: boolean;
}

function SegmentRow({ label, position, onToggle, isTimedSection, locked }: SegmentRowProps) {
  return (
    <TouchableOpacity
      style={[
        styles.segmentRow,
        isTimedSection && styles.segmentRowTimed,
        locked && styles.segmentRowLocked
      ]}
      onPress={locked ? undefined : onToggle}
      disabled={locked}
    >
      <Text style={[
        styles.segmentLabel,
        isTimedSection && styles.segmentLabelTimed,
        locked && styles.segmentLabelLocked
      ]}>
        {label}
      </Text>
      <View style={[
        styles.segmentToggle,
        locked ? styles.segmentToggleLocked :
          (position === 'standing' ? styles.segmentToggleStanding : styles.segmentToggleSeated)
      ]}>
        <Text style={[styles.segmentToggleText, locked && styles.segmentToggleTextLocked]}>
          {locked ? 'Locked' : (position === 'standing' ? 'Standing' : 'Seated')}
        </Text>
      </View>
    </TouchableOpacity>
  );
}


export default function SettingsScreen() {
  const router = useRouter();
  const {
    params,
    setParams,
    resetParams,
    gearing,
    setGearing,
    selectedTrack,
    setSelectedTrack,
    clearStravaSession,
    segmentPositions,
    setSegmentPosition,
    resetSegmentPositions,
  } = useAppStore();

  const updateParam = (key: string, value: string) => {
    const num = parseFloat(value);
    if (!isNaN(num)) {
      setParams({ [key]: num });
    }
  };

  const updateGearing = (key: string, value: string) => {
    const num = parseInt(value);
    if (!isNaN(num)) {
      setGearing({ [key]: num });
    }
  };

  const handleResetParams = () => {
    Alert.alert(
      'Reset Parameters',
      'Reset all parameters to defaults?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: () => {
            resetParams();
            setGearing(DEFAULT_GEARING);
          },
        },
      ]
    );
  };

  const handleClearSession = () => {
    Alert.alert(
      'Clear Session',
      'This will log you out of Strava.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear',
          style: 'destructive',
          onPress: clearStravaSession,
        },
      ]
    );
  };

  const handleResetPositions = () => {
    Alert.alert(
      'Reset Position Profile',
      'Reset all segments to seated?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: resetSegmentPositions,
        },
      ]
    );
  };

  const toggleSegmentPosition = (segmentId: string) => {
    const current = segmentPositions[segmentId] || 'seated';
    setSegmentPosition(segmentId, current === 'seated' ? 'standing' : 'seated');
  };

  const isTimedSection = (startM: number) => startM >= 695;

  const selectedTrackInfo = TRACK_OPTIONS.find(t => t.id === selectedTrack);

  return (
    <ScrollView style={styles.container}>
      {/* Track Selection */}
      <CollapsibleSection title="Track">
        <Text style={styles.trackSelectorLabel}>Velodrome</Text>
        <View style={styles.trackOptionsRow}>
          {TRACK_OPTIONS.map((track) => (
            <TouchableOpacity
              key={track.id}
              style={[
                styles.trackOption,
                selectedTrack === track.id && styles.trackOptionSelected
              ]}
              onPress={() => setSelectedTrack(track.id)}
              activeOpacity={1}
            >
              <Text style={[
                styles.trackOptionName,
                selectedTrack === track.id && styles.trackOptionNameSelected
              ]}>
                {track.id}
              </Text>
              <Text style={styles.trackOptionInfo}>
                {track.geometry.straight_m}m / {track.geometry.banking_turn_deg}°
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        {selectedTrackInfo && (
          <View style={styles.trackDetails}>
            <Text style={styles.trackDetailsName}>{selectedTrackInfo.name}</Text>
            <Text style={styles.trackDetailsDesc}>{selectedTrackInfo.description}</Text>
            <View style={styles.trackDetailsStats}>
              <Text style={styles.trackDetailsStat}>Straights: {selectedTrackInfo.geometry.straight_m}m</Text>
              <Text style={styles.trackDetailsStat}>Turns: {((selectedTrackInfo.geometry.lap_m - 2 * selectedTrackInfo.geometry.straight_m) / (2 * Math.PI)).toFixed(1)}m</Text>
              <Text style={styles.trackDetailsStat}>Banking: {selectedTrackInfo.geometry.banking_turn_deg}°</Text>
              <Text style={styles.trackDetailsStat}>Width: {selectedTrackInfo.geometry.width_m}m</Text>
            </View>
          </View>
        )}
      </CollapsibleSection>

      {/* Gearing */}
      <CollapsibleSection title="Gearing">
        <View style={styles.importantBanner}>
          <Text style={styles.importantIcon}>⚠️</Text>
          <Text style={styles.importantText}>
            Required to calculate the power over distance profile from activity data.
          </Text>
        </View>
        <SettingRow
          label="Chainring"
          value={gearing.chainring}
          unit="teeth"
          onChangeText={(v) => updateGearing('chainring', v)}
          isInteger={true}
          helpText="Front gear teeth. Used with cog and wheel to calculate rollout: (chainring/cog) × wheel circ = distance per pedal revolution. Rollout affects cadence-to-speed conversion in analysis. Bigger chainring = more distance per rev = lower cadence at same speed."
        />
        <SettingRow
          label="Cog"
          value={gearing.cog}
          unit="teeth"
          onChangeText={(v) => updateGearing('cog', v)}
          isInteger={true}
          helpText="Rear sprocket teeth. Gear ratio = chainring ÷ cog. Smaller cog = higher ratio = more distance per pedal rev. Used in analysis to calculate distance from cadence data: distance = (cadence/60) × rollout × time."
        />
        <SettingRow
          label="Wheel Circumference"
          value={gearing.wheelCircMm}
          unit="mm"
          onChangeText={(v) => updateGearing('wheelCircMm', v)}
          isInteger={true}
          helpText="Wheel circumference in mm. Rollout = gear ratio × wheel circ. Used to convert cadence to distance in analysis. Calculate: (rim diam + 2 × tire width) × π. Example: (622 + 2×23) × 3.14 = 2098mm. Wrong value = incorrect distance/speed calculations."
        />
        <Text style={styles.gearRatio}>
          Gear Ratio: {(gearing.chainring / gearing.cog).toFixed(2)}
        </Text>
      </CollapsibleSection>

      {/* Rider Parameters */}
      <CollapsibleSection title="Rider">
        <SettingRow
          label="Mass"
          value={params.mass_kg}
          unit="kg"
          onChangeText={(v) => updateParam('mass_kg', v)}
          helpText="Combined rider + bike mass used in physics calculations. Affects: (1) Rolling resistance force = Crr × mass × g, (2) Kinetic energy for acceleration = ½mv², (3) Potential energy on banking = m×g×h. Higher mass = more energy needed to accelerate and climb banking, slower times."
        />
        <SettingRow
          label="Critical Power"
          value={params.cp_W}
          unit="W"
          onChangeText={(v) => updateParam('cp_W', v)}
          helpText="Threshold power for the fatigue model. Power above CP depletes your W' battery at rate (P-CP) watts. Power below CP recovers W' at rate (CP-P). When W' hits zero, simulation limits you to CP output only. Higher CP = more sustainable power before tapping into W'."
        />
        <SettingRow
          label="W' (Anaerobic Capacity)"
          value={params.wPrime_J}
          unit="J"
          onChangeText={(v) => updateParam('wPrime_J', v)}
          helpText="Total anaerobic energy reservoir in Joules. Depletes when power > CP, recovers when power < CP. Example: 20,000J at 500W above CP lasts 40 seconds. Higher W' = can sustain high power longer before hitting CP limit. Directly affects how long you can sprint."
        />
        <SettingRow
          label="Sprint Delta"
          value={params.sprint_delta_W}
          unit="W"
          onChangeText={(v) => updateParam('sprint_delta_W', v)}
          helpText="Power threshold above Critical Power used to detect when the sprint phase begins in analysis. When your power exceeds CP + Sprint Delta, the model considers you to be sprinting. Used for calculating sprint duration and average sprint power. Typical: 200-300W above CP."
        />
      </CollapsibleSection>

      {/* Environment */}
      <CollapsibleSection title="Environment">
        <SettingRow
          label="Air Density"
          value={params.rho}
          unit="kg/m³"
          onChangeText={(v) => updateParam('rho', v)}
          helpText="Air density in the aero drag equation: F_aero = ½ × ρ × CdA × v². Lower ρ = less drag = faster times. Hot/humid/high altitude = lower ρ. Example: ρ=1.05 vs 1.20 saves ~0.3-0.5s on F200. Calculate from temperature, pressure, humidity on Analysis page."
        />
        <SettingRow
          label="Rolling Resistance"
          value={params.crr}
          unit="Crr"
          onChangeText={(v) => updateParam('crr', v)}
          helpText="Coefficient in rolling resistance: F_rr = Crr × mass × g × cos(θ). Accounts for tire deformation losses. At F200 speeds, rolling resistance is ~5-10% of total drag. Crr of 0.002 vs 0.004 = ~0.1s difference. Good tires + high pressure = lower Crr."
        />
        <SettingRow
          label="Drivetrain Efficiency"
          value={params.drivetrain_eff}
          unit=""
          onChangeText={(v) => updateParam('drivetrain_eff', v)}
          helpText="Multiplier on power output: W_effective = Power × Efficiency. Value of 0.97 means 3% of your watts lost to chain/bearing friction. At 1000W sprint, 0.97 vs 1.0 efficiency = 30W lost. Clean chain and good bearings maximize this value."
        />
        <SettingRow
          label="Initial Velocity"
          value={params.v0_mps}
          unit="m/s"
          onChangeText={(v) => updateParam('v0_mps', v)}
          helpText="Speed at s=0 (start of simulation). Sets initial kinetic energy: E = ½mv². For flying efforts, represents the slow roll before dive. Higher v0 = less time/energy needed to reach sprint speed. Default 5.0 m/s (~18 km/h). Set lower for standing start simulations."
        />
        <SettingRow
          label="Bend CdA Factor"
          value={params.cda_bend_factor}
          unit=""
          onChangeText={(v) => updateParam('cda_bend_factor', v)}
          helpText="Multiplier applied to CdA in bends. Factor < 1.0 reduces drag in turns due to yaw angle reducing effective frontal area. Example: 0.97 means CdA × 0.97 in bends (3% less drag). Straights use full CdA. Set to 1.0 for no difference. Typical: 0.95-0.98."
        />
      </CollapsibleSection>

      {/* Position Profile */}
      <CollapsibleSection title="Position Profile">
        <Text style={styles.positionHint}>
          Set seated or standing for each track segment. Tap to toggle. Standing uses CdA Standing value.
        </Text>
        <View style={styles.segmentList}>
          {TRACK_SEGMENTS.map((segment) => (
            <SegmentRow
              key={segment.id}
              label={segment.label}
              position={segment.locked ? 'seated' : (segmentPositions[segment.id] || 'seated')}
              onToggle={() => toggleSegmentPosition(segment.id)}
              isTimedSection={isTimedSection(segment.startM)}
              locked={segment.locked}
            />
          ))}
        </View>
        <TouchableOpacity style={styles.resetPositionsButton} onPress={handleResetPositions}>
          <Text style={styles.resetPositionsText}>Reset All to Seated</Text>
        </TouchableOpacity>
      </CollapsibleSection>

      {/* Kit Configuration */}
      <CollapsibleSection title="Kit Configuration">
        <TouchableOpacity
          style={styles.kitNavButton}
          onPress={() => router.push('/(settings)/kit')}
          activeOpacity={0.7}
        >
          <Text style={styles.kitNavButtonText}>Manage Kit Configurations</Text>
          <Text style={styles.kitNavArrow}>›</Text>
        </TouchableOpacity>
      </CollapsibleSection>

      {/* Actions - last section */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Actions</Text>
        </View>
        <View style={styles.sectionContent}>
          <TouchableOpacity style={styles.actionButton} onPress={handleResetParams}>
            <Text style={styles.actionButtonText}>Reset to Defaults</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionButton, styles.dangerButton]} onPress={handleClearSession}>
            <Text style={styles.actionButtonText}>Clear Strava Session</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* App Info */}
      <View style={styles.footer}>
        <Text style={styles.footerText}>Flying 200 Mobile v1.0.0</Text>
        <Text style={styles.footerText}>Track Cycling Simulation & Analysis</Text>
      </View>

      <View style={styles.bottomPadding} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
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
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 14,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
    textTransform: 'uppercase',
  },
  sectionToggle: {
    color: colors.textSecondary,
    fontSize: 16,
    fontFamily: fonts.sansBold,
  },
  sectionContent: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  settingLabelWrapper: {
    flex: 1,
  },
  labelWithHelp: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  settingLabel: {
    color: colors.textPrimary,
    fontSize: 14,
  },
  helpButton: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  helpButtonText: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansBold,
  },
  settingUnit: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  settingInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    fontSize: 14,
    minWidth: 100,
    textAlign: 'right',
  },
  gearRatio: {
    color: colors.accent,
    fontSize: 14,
    textAlign: 'center',
    marginTop: 8,
  },
  trackSelectorLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 8,
  },
  trackOptionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 12,
  },
  trackOption: {
    backgroundColor: colors.bg0,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: 'transparent',
    alignItems: 'center',
  },
  trackOptionSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.bg2,
  },
  trackOptionName: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  trackOptionNameSelected: {
    color: colors.textPrimary,
  },
  trackOptionInfo: {
    color: colors.textSecondary,
    fontSize: 10,
    marginTop: 2,
  },
  trackDetails: {
    backgroundColor: colors.bg0,
    padding: 12,
    borderRadius: 8,
  },
  trackDetailsName: {
    color: colors.textPrimary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    marginBottom: 2,
  },
  trackDetailsDesc: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 8,
  },
  trackDetailsStats: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  trackDetailsStat: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  actionButton: {
    backgroundColor: colors.border,
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 12,
  },
  dangerButton: {
    backgroundColor: '#7f1d1d',
  },
  actionButtonText: {
    color: colors.textPrimary,
    fontFamily: fonts.sansSemiBold,
  },
  footer: {
    padding: 24,
    alignItems: 'center',
  },
  footerText: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 4,
  },
  importantBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#332b00',
    borderRadius: 8,
    padding: 10,
    marginBottom: 16,
    gap: 8,
  },
  importantIcon: {
    fontSize: 14,
  },
  importantText: {
    color: colors.warning,
    fontSize: 12,
    flex: 1,
  },
  sectionHint: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 16,
    fontStyle: 'italic',
  },
  positionHint: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 16,
    fontStyle: 'italic',
  },
  segmentList: {
    marginBottom: 12,
  },
  segmentRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: colors.bg0,
    borderRadius: 8,
    marginBottom: 8,
  },
  segmentRowTimed: {
    backgroundColor: '#1a3a2e',
    borderLeftWidth: 3,
    borderLeftColor: colors.success,
  },
  segmentLabel: {
    color: colors.textPrimary,
    fontSize: 13,
    flex: 1,
  },
  segmentLabelTimed: {
    color: colors.success,
  },
  segmentToggle: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    minWidth: 80,
    alignItems: 'center',
  },
  segmentToggleSeated: {
    backgroundColor: colors.seated,
  },
  segmentToggleStanding: {
    backgroundColor: colors.standing,
  },
  segmentToggleLocked: {
    backgroundColor: colors.bg3,
  },
  segmentToggleText: {
    color: colors.textPrimary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  segmentToggleTextLocked: {
    color: colors.textMuted,
  },
  segmentRowLocked: {
    opacity: 0.7,
  },
  segmentLabelLocked: {
    color: colors.textMuted,
  },
  resetPositionsButton: {
    backgroundColor: colors.bg3,
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  resetPositionsText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  bottomPadding: {
    height: 40,
  },
  kitNavButton: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderWidth: 1,
    borderColor: colors.borderAccent,
    paddingHorizontal: spacing.lg,
  },
  kitNavButtonText: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    fontSize: 13,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  kitNavArrow: {
    color: colors.accent,
    fontSize: 20,
    fontFamily: fonts.mono,
  },
});

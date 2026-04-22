import { colors, fonts, spacing } from '../../theme';
import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, useWindowDimensions, Modal, Pressable, Platform } from 'react-native';
import { useNavigation } from 'expo-router';
import * as ScreenOrientation from 'expo-screen-orientation';
import TrackVisual from '../../components/TrackVisual';
import { AVAILABLE_TRACKS } from '../../api/trackApi';
import { useAppStore, TRACK_OPTIONS, getTrackGeometry } from '../../store/simulationStore';
import type { TrackName } from '../../store/simulationStore';

// Lap definitions for UI
const LAP_DEFINITIONS = [
  { id: 0, name: 'L0', color: '#1f77b4' },
  { id: 1, name: 'L1', color: '#2ca02c' },
  { id: 2, name: 'L2', color: '#ff7f0e' },
  { id: 3, name: 'Timed', color: '#d62728' },
];

// Default trajectory from profile_f200.csv - the standard flying 200 racing line
const DEFAULT_TRAJECTORY: Array<{ s_m: number; y_m: number; CdA_m2: number; P_W: number }> = [
  { s_m: 0, y_m: 2.5, CdA_m2: 0.24, P_W: 134 },
  { s_m: 10, y_m: 2.5, CdA_m2: 0.24, P_W: 134 },
  { s_m: 20, y_m: 2.5, CdA_m2: 0.24, P_W: 165 },
  { s_m: 30, y_m: 2.5, CdA_m2: 0.24, P_W: 204 },
  { s_m: 40, y_m: 2.5, CdA_m2: 0.24, P_W: 153 },
  { s_m: 50, y_m: 2.5, CdA_m2: 0.24, P_W: 138 },
  { s_m: 60, y_m: 2.5, CdA_m2: 0.24, P_W: 125 },
  { s_m: 70, y_m: 2.93, CdA_m2: 0.24, P_W: 162 },
  { s_m: 80, y_m: 3.36, CdA_m2: 0.24, P_W: 160 },
  { s_m: 90, y_m: 3.79, CdA_m2: 0.24, P_W: 145 },
  { s_m: 100, y_m: 4.64, CdA_m2: 0.24, P_W: 123 },
  { s_m: 110, y_m: 5.92, CdA_m2: 0.24, P_W: 134 },
  { s_m: 120, y_m: 7.2, CdA_m2: 0.24, P_W: 113 },
  { s_m: 130, y_m: 7.5, CdA_m2: 0.24, P_W: 130 },
  { s_m: 140, y_m: 7.5, CdA_m2: 0.24, P_W: 137 },
  { s_m: 150, y_m: 7.25, CdA_m2: 0.24, P_W: 141 },
  { s_m: 160, y_m: 6.5, CdA_m2: 0.24, P_W: 144 },
  { s_m: 170, y_m: 5.75, CdA_m2: 0.24, P_W: 131 },
  { s_m: 180, y_m: 4.75, CdA_m2: 0.24, P_W: 127 },
  { s_m: 190, y_m: 5.13, CdA_m2: 0.24, P_W: 148 },
  { s_m: 200, y_m: 5.88, CdA_m2: 0.24, P_W: 161 },
  { s_m: 210, y_m: 5.39, CdA_m2: 0.24, P_W: 122 },
  { s_m: 220, y_m: 5.59, CdA_m2: 0.24, P_W: 157 },
  { s_m: 230, y_m: 5.77, CdA_m2: 0.24, P_W: 109 },
  { s_m: 240, y_m: 7.5, CdA_m2: 0.24, P_W: 115 },
  { s_m: 250, y_m: 7.13, CdA_m2: 0.24, P_W: 120 },
  { s_m: 260, y_m: 7.5, CdA_m2: 0.24, P_W: 130 },
  { s_m: 270, y_m: 7.5, CdA_m2: 0.24, P_W: 161 },
  { s_m: 280, y_m: 7.18, CdA_m2: 0.24, P_W: 194 },
  { s_m: 290, y_m: 6.78, CdA_m2: 0.24, P_W: 184 },
  { s_m: 300, y_m: 7.02, CdA_m2: 0.24, P_W: 192 },
  { s_m: 310, y_m: 6.7, CdA_m2: 0.24, P_W: 222 },
  { s_m: 320, y_m: 6.71, CdA_m2: 0.24, P_W: 206 },
  { s_m: 330, y_m: 6.95, CdA_m2: 0.24, P_W: 201 },
  { s_m: 340, y_m: 6.78, CdA_m2: 0.24, P_W: 172 },
  { s_m: 350, y_m: 6.5, CdA_m2: 0.24, P_W: 171 },
  { s_m: 360, y_m: 7.5, CdA_m2: 0.24, P_W: 186 },
  { s_m: 370, y_m: 7.5, CdA_m2: 0.24, P_W: 240 },
  { s_m: 380, y_m: 7.5, CdA_m2: 0.24, P_W: 268 },
  { s_m: 390, y_m: 7.5, CdA_m2: 0.24, P_W: 272 },
  { s_m: 400, y_m: 7.5, CdA_m2: 0.24, P_W: 308 },
  { s_m: 410, y_m: 7.5, CdA_m2: 0.24, P_W: 394 },
  { s_m: 420, y_m: 7.5, CdA_m2: 0.24, P_W: 432 },
  { s_m: 430, y_m: 7.5, CdA_m2: 0.24, P_W: 478 },
  { s_m: 440, y_m: 7.5, CdA_m2: 0.24, P_W: 536 },
  { s_m: 450, y_m: 7.5, CdA_m2: 0.24, P_W: 502 },
  { s_m: 460, y_m: 7.5, CdA_m2: 0.24, P_W: 519 },
  { s_m: 470, y_m: 7.5, CdA_m2: 0.24, P_W: 468 },
  { s_m: 480, y_m: 7.5, CdA_m2: 0.24, P_W: 500 },
  { s_m: 490, y_m: 7.5, CdA_m2: 0.24, P_W: 596 },
  { s_m: 500, y_m: 7.5, CdA_m2: 0.24, P_W: 775 },
  { s_m: 510, y_m: 7.5, CdA_m2: 0.24, P_W: 847 },
  { s_m: 520, y_m: 7.5, CdA_m2: 0.24, P_W: 847 },
  { s_m: 530, y_m: 7.5, CdA_m2: 0.24, P_W: 827 },
  { s_m: 540, y_m: 7.5, CdA_m2: 0.24, P_W: 813 },
  { s_m: 550, y_m: 7.5, CdA_m2: 0.24, P_W: 813 },
  { s_m: 560, y_m: 7.5, CdA_m2: 0.24, P_W: 881 },
  { s_m: 570, y_m: 7.5, CdA_m2: 0.24, P_W: 888 },
  { s_m: 580, y_m: 7.5, CdA_m2: 0.24, P_W: 863 },
  { s_m: 590, y_m: 7.5, CdA_m2: 0.24, P_W: 889 },
  { s_m: 600, y_m: 7.5, CdA_m2: 0.24, P_W: 870 },
  { s_m: 610, y_m: 7.5, CdA_m2: 0.24, P_W: 842 },
  { s_m: 620, y_m: 7.5, CdA_m2: 0.24, P_W: 876 },
  { s_m: 630, y_m: 7.0, CdA_m2: 0.24, P_W: 931 },
  { s_m: 640, y_m: 6.5, CdA_m2: 0.24, P_W: 997 },
  { s_m: 650, y_m: 6.0, CdA_m2: 0.24, P_W: 1041 },
  { s_m: 660, y_m: 5.5, CdA_m2: 0.24, P_W: 1075 },
  { s_m: 670, y_m: 5.0, CdA_m2: 0.24, P_W: 1085 },
  { s_m: 680, y_m: 5.0, CdA_m2: 0.24, P_W: 919 },
  { s_m: 690, y_m: 1.25, CdA_m2: 0.245, P_W: 834 },
  { s_m: 695, y_m: 0, CdA_m2: 0.245, P_W: 827 },
  { s_m: 700, y_m: 0, CdA_m2: 0.245, P_W: 820 },
  { s_m: 710, y_m: 0, CdA_m2: 0.245, P_W: 803 },
  { s_m: 720, y_m: 0, CdA_m2: 0.245, P_W: 785 },
  { s_m: 730, y_m: 0, CdA_m2: 0.245, P_W: 795 },
  { s_m: 740, y_m: 0, CdA_m2: 0.245, P_W: 804 },
  { s_m: 750, y_m: 0, CdA_m2: 0.245, P_W: 804 },
  { s_m: 760, y_m: 0, CdA_m2: 0.245, P_W: 789 },
  { s_m: 770, y_m: 0, CdA_m2: 0.245, P_W: 748 },
  { s_m: 780, y_m: 0, CdA_m2: 0.245, P_W: 703 },
  { s_m: 790, y_m: 0, CdA_m2: 0.245, P_W: 656 },
  { s_m: 800, y_m: 0, CdA_m2: 0.245, P_W: 651 },
  { s_m: 810, y_m: 0, CdA_m2: 0.245, P_W: 655 },
  { s_m: 820, y_m: 0, CdA_m2: 0.245, P_W: 682 },
  { s_m: 830, y_m: 0, CdA_m2: 0.245, P_W: 687 },
  { s_m: 840, y_m: 0, CdA_m2: 0.245, P_W: 662 },
  { s_m: 850, y_m: 0, CdA_m2: 0.245, P_W: 637 },
  { s_m: 860, y_m: 0, CdA_m2: 0.245, P_W: 613 },
  { s_m: 870, y_m: 0, CdA_m2: 0.245, P_W: 576 },
  { s_m: 880, y_m: 0, CdA_m2: 0.245, P_W: 543 },
  { s_m: 890, y_m: 0, CdA_m2: 0.245, P_W: 543 },
  { s_m: 895, y_m: 0, CdA_m2: 0.245, P_W: 543 },
];

export default function TrackScreen() {
  const [showLap0, setShowLap0] = useState(true);
  const [showLap1, setShowLap1] = useState(true);
  const [showLap2, setShowLap2] = useState(true);
  const [showTimed, setShowTimed] = useState(true);
  const [showTrackSelector, setShowTrackSelector] = useState(false);

  // Get track selection from store (synced with Inputs screen)
  const { selectedTrack, setSelectedTrack } = useAppStore();

  // Use window dimensions hook for responsive layout
  const { width, height } = useWindowDimensions();
  const isLandscape = width > height;

  // Navigation refs for hiding tab bar and header in landscape
  const navigation = useNavigation();
  const parentNavigation = navigation.getParent();

  // Hide tab bar and header when landscape, restore when portrait
  useEffect(() => {
    if (isLandscape) {
      // Hide bottom tab bar
      parentNavigation?.setOptions({
        tabBarStyle: { display: 'none' as const },
      });
      // Hide stack header
      navigation.setOptions({ headerShown: false });
    } else {
      // Restore bottom tab bar
      parentNavigation?.setOptions({
        tabBarStyle: {
          backgroundColor: '#0E1420',
          borderTopWidth: 1,
          borderTopColor: '#1E2A3A',
          height: Platform.OS === 'ios' ? 85 : 65,
          paddingBottom: Platform.OS === 'ios' ? 25 : 10,
          paddingTop: 8,
        },
      });
      // Restore stack header
      navigation.setOptions({ headerShown: true });
    }
  }, [isLandscape]);

  // Always use the default trajectory (simulation uses the same path)
  const trackProfile = DEFAULT_TRAJECTORY;

  // Get current track geometry
  const currentTrackGeo = getTrackGeometry(selectedTrack);

  // Enable landscape orientation when screen mounts, restore on unmount
  useEffect(() => {
    const enableLandscape = async () => {
      await ScreenOrientation.unlockAsync();
    };

    const lockPortrait = async () => {
      await ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.PORTRAIT_UP);
    };

    enableLandscape();

    return () => {
      lockPortrait();
      // Restore tab bar when leaving the screen (in case we leave while landscape)
      parentNavigation?.setOptions({
        tabBarStyle: {
          backgroundColor: '#0E1420',
          borderTopWidth: 1,
          borderTopColor: '#1E2A3A',
          height: Platform.OS === 'ios' ? 85 : 65,
          paddingBottom: Platform.OS === 'ios' ? 25 : 10,
          paddingTop: 8,
        },
      });
      navigation.setOptions({ headerShown: true });
    };
  }, []);

  // Calculate track dimensions based on orientation
  const getTrackDimensions = () => {
    if (isLandscape) {
      // Landscape: track takes most of the width, leave space for controls
      // Tab bar and header are hidden, so use full height minus minimal status bar padding
      const controlsWidth = 100;
      const trackWidth = width - controlsWidth - 16;
      const trackHeight = height - 16;
      return { trackWidth, trackHeight };
    } else {
      // Portrait: full width, horizontal aspect ratio
      const trackWidth = width - 8;
      const trackHeight = Math.round(trackWidth * 0.55);
      return { trackWidth, trackHeight };
    }
  };

  const { trackWidth, trackHeight } = getTrackDimensions();

  const toggleVisibility = (lapId: number) => {
    switch (lapId) {
      case 0: setShowLap0(!showLap0); break;
      case 1: setShowLap1(!showLap1); break;
      case 2: setShowLap2(!showLap2); break;
      case 3: setShowTimed(!showTimed); break;
    }
  };

  const isVisible = (lapId: number) => {
    switch (lapId) {
      case 0: return showLap0;
      case 1: return showLap1;
      case 2: return showLap2;
      case 3: return showTimed;
      default: return true;
    }
  };

  // Track selector modal - uses TRACK_OPTIONS from store (synced with Inputs)
  const TrackSelectorModal = () => (
    <Modal
      visible={showTrackSelector}
      transparent
      animationType="fade"
      onRequestClose={() => setShowTrackSelector(false)}
    >
      <Pressable style={styles.modalOverlay} onPress={() => setShowTrackSelector(false)}>
        <View style={styles.modalContent}>
          <Text style={styles.modalTitle}>Select Track</Text>
          {TRACK_OPTIONS.map((track) => (
            <TouchableOpacity
              key={track.id}
              style={[
                styles.trackOption,
                selectedTrack === track.id && styles.trackOptionSelected,
              ]}
              onPress={() => {
                setSelectedTrack(track.id);
                setShowTrackSelector(false);
              }}
            >
              <Text style={[
                styles.trackOptionName,
                selectedTrack === track.id && styles.trackOptionNameSelected,
              ]}>
                {track.name}
              </Text>
              <Text style={styles.trackOptionDesc}>{track.geometry.straight_m}m straights, {track.geometry.banking_turn_deg}° banking, {track.geometry.width_m}m wide</Text>
            </TouchableOpacity>
          ))}
        </View>
      </Pressable>
    </Modal>
  );

  // Landscape layout: track on left, controls on right
  if (isLandscape) {
    return (
      <View style={styles.landscapeContainer}>
        <TrackSelectorModal />

        {/* Track Visual - fills left side */}
        <View style={styles.landscapeTrack}>
          <TrackVisual
            trackProfile={trackProfile}
            showLap0={showLap0}
            showLap1={showLap1}
            showLap2={showLap2}
            showTimed={showTimed}
            width={trackWidth}
            height={trackHeight}
            trackName={selectedTrack}
          />
        </View>

        {/* Controls on right side */}
        <View style={styles.landscapeControls}>
          {/* Track selector button */}
          <TouchableOpacity
            style={styles.trackSelectorButton}
            onPress={() => setShowTrackSelector(true)}
          >
            <Text style={styles.trackSelectorText}>{selectedTrack}</Text>
            <Text style={styles.trackSelectorArrow}>▼</Text>
          </TouchableOpacity>

          {/* Lap toggles - vertical stack */}
          {LAP_DEFINITIONS.map((lap) => (
            <TouchableOpacity
              key={lap.id}
              style={[
                styles.landscapeToggle,
                { borderColor: lap.color },
                isVisible(lap.id) && { backgroundColor: lap.color },
              ]}
              onPress={() => toggleVisibility(lap.id)}
              activeOpacity={0.7}
            >
              <Text style={[
                styles.landscapeToggleText,
                isVisible(lap.id) && styles.toggleTextActive,
              ]}>
                {lap.name}
              </Text>
            </TouchableOpacity>
          ))}

          {/* Legend */}
          <View style={styles.landscapeLegend}>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: colors.seated }]} />
              <Text style={styles.legendTextSmall}>Start</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: colors.danger }]} />
              <Text style={styles.legendTextSmall}>Finish</Text>
            </View>
            <View style={styles.legendItem}>
              <View style={[styles.legendDot, { backgroundColor: colors.success }]} />
              <Text style={styles.legendTextSmall}>Path</Text>
            </View>
          </View>
        </View>
      </View>
    );
  }

  // Portrait layout: track on top, controls below
  return (
    <ScrollView style={styles.container}>
      <TrackSelectorModal />

      {/* Track selector row */}
      <View style={styles.trackSelectorRow}>
        <TouchableOpacity
          style={styles.trackSelectorButtonPortrait}
          onPress={() => setShowTrackSelector(true)}
        >
          <Text style={styles.trackSelectorTextPortrait}>{selectedTrack} 250m</Text>
          <Text style={styles.trackSelectorArrowPortrait}>▼</Text>
        </TouchableOpacity>
      </View>

      {/* Track Visual - full width, horizontal aspect */}
      <View style={styles.trackContainer}>
        <TrackVisual
          trackProfile={trackProfile}
          showLap0={showLap0}
          showLap1={showLap1}
          showLap2={showLap2}
          showTimed={showTimed}
          width={trackWidth}
          height={trackHeight}
          trackName={selectedTrack}
        />
      </View>

      {/* Compact legend row */}
      <View style={styles.legendRow}>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: colors.seated }]} />
          <Text style={styles.legendText}>Start</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: colors.danger }]} />
          <Text style={styles.legendText}>Finish</Text>
        </View>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: colors.success }]} />
          <Text style={styles.legendText}>Trajectory</Text>
        </View>
      </View>

      {/* Compact lap toggles - horizontal row */}
      <View style={styles.togglesRow}>
        {LAP_DEFINITIONS.map((lap) => (
          <TouchableOpacity
            key={lap.id}
            style={[
              styles.toggleChip,
              { borderColor: lap.color },
              isVisible(lap.id) && { backgroundColor: lap.color },
            ]}
            onPress={() => toggleVisibility(lap.id)}
            activeOpacity={0.7}
          >
            <Text style={[
              styles.toggleChipText,
              isVisible(lap.id) && styles.toggleChipTextActive,
            ]}>
              {lap.name}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Compact track info row - dynamic based on selected track */}
      <View style={styles.infoRow}>
        <Text style={styles.infoText}>{currentTrackGeo.straight_m}m straights</Text>
        <Text style={styles.infoDivider}>|</Text>
        <Text style={styles.infoText}>{((currentTrackGeo.lap_m - 2 * currentTrackGeo.straight_m) / (2 * Math.PI)).toFixed(0)}m turns</Text>
        <Text style={styles.infoDivider}>|</Text>
        <Text style={styles.infoText}>{currentTrackGeo.banking_turn_deg}° banking</Text>
      </View>

    </ScrollView>
  );
}

const styles = StyleSheet.create({
  // Portrait styles
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
  },
  trackContainer: {
    paddingHorizontal: 4,
    paddingTop: 4,
  },
  trackSelectorRow: {
    paddingHorizontal: 16,
    paddingTop: 8,
    alignItems: 'center',
  },
  trackSelectorButtonPortrait: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.bg2,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  trackSelectorTextPortrait: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  trackSelectorArrowPortrait: {
    color: colors.textMuted,
    fontSize: 10,
  },
  legendRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 16,
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  legendDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  legendText: {
    color: colors.textSecondary,
    fontSize: 12,
  },
  legendTextSmall: {
    color: colors.textSecondary,
    fontSize: 10,
  },
  togglesRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  toggleChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 2,
    backgroundColor: 'transparent',
  },
  toggleChipText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  toggleChipTextActive: {
    color: colors.textPrimary,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
  },
  infoText: {
    color: colors.textMuted,
    fontSize: 12,
  },
  infoDivider: {
    color: colors.border,
    fontSize: 12,
  },
  // Landscape styles
  landscapeContainer: {
    flex: 1,
    flexDirection: 'row',
    backgroundColor: colors.bg0,
  },
  landscapeTrack: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingLeft: 4,
  },
  landscapeControls: {
    width: 90,
    paddingVertical: 8,
    paddingRight: 8,
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
  },
  landscapeToggle: {
    width: 70,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 2,
    backgroundColor: 'transparent',
    alignItems: 'center',
  },
  landscapeToggleText: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  toggleTextActive: {
    color: colors.textPrimary,
  },
  landscapeLegend: {
    marginTop: 16,
    gap: 6,
  },
  trackSelectorButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.bg2,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 4,
    marginBottom: 8,
  },
  trackSelectorText: {
    color: colors.textPrimary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  trackSelectorArrow: {
    color: colors.textMuted,
    fontSize: 8,
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.bg2,
    borderRadius: 12,
    padding: 16,
    width: '80%',
    maxWidth: 320,
  },
  modalTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    marginBottom: 12,
    textAlign: 'center',
  },
  trackOption: {
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 8,
    marginBottom: 8,
    backgroundColor: colors.bg0,
  },
  trackOptionSelected: {
    backgroundColor: colors.seated,
  },
  trackOptionName: {
    color: colors.textPrimary,
    fontSize: 15,
    fontFamily: fonts.sansSemiBold,
  },
  trackOptionNameSelected: {
    color: colors.textPrimary,
  },
  trackOptionDesc: {
    color: colors.textSecondary,
    fontSize: 12,
    marginTop: 2,
  },
});

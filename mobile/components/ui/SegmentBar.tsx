import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, fonts, spacing } from '../../theme';

interface Segment {
  id: string;
  label: string;
  position: 'seated' | 'standing';
  power?: number;
}

interface SegmentBarProps {
  segments: Segment[];
}

export function SegmentBar({ segments }: SegmentBarProps) {
  return (
    <View style={styles.container}>
      {segments.map((seg) => (
        <View
          key={seg.id}
          style={[
            styles.segment,
            { backgroundColor: seg.position === 'seated' ? colors.seatedDim : colors.standingDim },
            { borderBottomColor: seg.position === 'seated' ? colors.seated : colors.standing },
          ]}
        >
          {seg.power !== undefined && (
            <Text style={styles.power}>{Math.round(seg.power)}</Text>
          )}
          <Text style={styles.label} numberOfLines={1}>{seg.label}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    borderRadius: 4,
    overflow: 'hidden',
  },
  segment: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.xs,
    borderBottomWidth: 2,
  },
  power: {
    fontFamily: fonts.mono,
    fontSize: 11,
    color: colors.textPrimary,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: 8,
    color: colors.textMuted,
    marginTop: 1,
  },
});

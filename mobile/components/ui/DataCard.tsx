import React from 'react';
import { View, ViewStyle, StyleSheet } from 'react-native';
import { colors, spacing, radii } from '../../theme';

interface DataCardProps {
  children: React.ReactNode;
  active?: boolean;
  style?: ViewStyle;
}

export function DataCard({ children, active = false, style }: DataCardProps) {
  return (
    <View style={[styles.card, active && styles.active, style]}>
      {active && <View style={styles.accentStripe} />}
      <View style={styles.content}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.bg1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    overflow: 'hidden',
  },
  active: {
    borderColor: colors.borderAccent,
  },
  accentStripe: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 2,
    backgroundColor: colors.accent,
  },
  content: {
    padding: spacing.lg,
  },
});

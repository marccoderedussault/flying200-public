import React from 'react';
import { View, Text, StyleSheet, ViewStyle } from 'react-native';
import { colors, typography, fonts, spacing } from '../../theme';

interface MetricDisplayProps {
  value: string;
  unit?: string;
  label?: string;
  glow?: boolean;
  delta?: { value: string; positive: boolean };
  size?: 'normal' | 'large';
  style?: ViewStyle;
}

export function MetricDisplay({ value, unit, label, glow = false, delta, size = 'normal', style }: MetricDisplayProps) {
  return (
    <View style={[styles.container, glow && styles.glow, style]}>
      {label && <Text style={styles.label}>{label}</Text>}
      <View style={styles.valueRow}>
        <Text style={[styles.value, size === 'large' && styles.valueLarge]}>{value}</Text>
        {unit && <Text style={styles.unit}>{unit}</Text>}
      </View>
      {delta && (
        <View style={styles.deltaRow}>
          <Text style={[styles.deltaText, { color: delta.positive ? colors.success : colors.danger }]}>
            {delta.positive ? '▲' : '▼'} {delta.value}
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  glow: {
    backgroundColor: colors.accentGlow,
    borderRadius: 8,
  },
  label: {
    ...typography.label,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  value: {
    ...typography.keyNumber,
    color: colors.textPrimary,
  },
  valueLarge: {
    fontSize: 40,
  },
  unit: {
    ...typography.unit,
    color: colors.textMuted,
    marginLeft: spacing.xs,
  },
  deltaRow: {
    marginTop: spacing.xs,
  },
  deltaText: {
    fontFamily: fonts.mono,
    fontSize: 12,
  },
});

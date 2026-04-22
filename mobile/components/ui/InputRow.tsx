import React from 'react';
import { View, Text, TextInput, StyleSheet, ViewStyle } from 'react-native';
import { colors, fonts, typography, spacing } from '../../theme';

interface InputRowProps {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  unit?: string;
  help?: string;
  keyboardType?: 'default' | 'numeric' | 'decimal-pad';
  style?: ViewStyle;
}

export function InputRow({ label, value, onChangeText, unit, help, keyboardType = 'default', style }: InputRowProps) {
  return (
    <View style={[styles.container, style]}>
      <View style={styles.row}>
        <View style={styles.labelContainer}>
          <Text style={styles.label}>{label}</Text>
          {unit && <Text style={styles.unitLabel}>{unit}</Text>}
        </View>
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChangeText}
          keyboardType={keyboardType}
          placeholderTextColor={colors.textMuted}
          selectionColor={colors.accent}
        />
      </View>
      {help && <Text style={styles.help}>{help}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingVertical: spacing.md,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  labelContainer: {
    flexDirection: 'row',
    alignItems: 'baseline',
    flex: 1,
  },
  label: {
    ...typography.body,
    color: colors.textPrimary,
  },
  unitLabel: {
    ...typography.unit,
    color: colors.textMuted,
    marginLeft: spacing.xs,
  },
  input: {
    fontFamily: fonts.mono,
    fontSize: 15,
    color: colors.textPrimary,
    backgroundColor: colors.bg2,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    minWidth: 100,
    textAlign: 'right',
    borderRadius: 4,
  },
  help: {
    ...typography.unit,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
});

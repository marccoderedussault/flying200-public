import React from 'react';
import { TouchableOpacity, Text, ActivityIndicator, StyleSheet, ViewStyle } from 'react-native';
import { colors, typography, spacing } from '../../theme';

interface ActionButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'destructive';
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
}

export function ActionButton({ label, onPress, variant = 'primary', disabled = false, loading = false, style }: ActionButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.7}
      style={[
        styles.base,
        variant === 'primary' && styles.primary,
        variant === 'secondary' && styles.secondary,
        variant === 'destructive' && styles.destructive,
        isDisabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={variant === 'primary' ? colors.bg0 : colors.accent} />
      ) : (
        <Text style={[
          styles.label,
          variant === 'primary' && styles.primaryLabel,
          variant === 'secondary' && styles.secondaryLabel,
          variant === 'destructive' && styles.destructiveLabel,
        ]}>
          {label}
        </Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
  },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 0,
  },
  secondary: {
    backgroundColor: colors.transparent,
    borderWidth: 1,
    borderColor: colors.accent,
    borderRadius: 0,
  },
  destructive: {
    backgroundColor: colors.transparent,
    borderWidth: 1,
    borderColor: colors.danger,
    borderRadius: 0,
  },
  disabled: {
    opacity: 0.5,
  },
  label: {
    ...typography.buttonLabel,
  },
  primaryLabel: {
    color: colors.bg0,
  },
  secondaryLabel: {
    color: colors.accent,
  },
  destructiveLabel: {
    color: colors.danger,
  },
});

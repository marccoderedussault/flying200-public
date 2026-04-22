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
import { useAppStore, MAX_KIT_CONFIGS, DEFAULT_KIT_CONFIGS } from '../../store/simulationStore';
import type { NamedKitConfig, FrontWheelType, RearWheelType } from '../../store/simulationStore';

function generateId(): string {
  return 'kit-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6);
}

interface KitCardProps {
  config: NamedKitConfig;
  expanded: boolean;
  onToggleExpand: () => void;
  onUpdate: (updates: Partial<NamedKitConfig>) => void;
  onSetDefault: () => void;
  onDelete: () => void;
  canDelete: boolean;
}

function KitCard({ config, expanded, onToggleExpand, onUpdate, onSetDefault, onDelete, canDelete }: KitCardProps) {
  const [localName, setLocalName] = useState(config.name);
  const [localDesc, setLocalDesc] = useState(config.description);
  const [localCdaSeated, setLocalCdaSeated] = useState(config.cdaSeated.toString());
  const [localCdaStanding, setLocalCdaStanding] = useState(config.cdaStanding.toString());

  // Sync local state when config changes externally
  React.useEffect(() => {
    setLocalName(config.name);
    setLocalDesc(config.description);
    setLocalCdaSeated(config.cdaSeated.toString());
    setLocalCdaStanding(config.cdaStanding.toString());
  }, [config.name, config.description, config.cdaSeated, config.cdaStanding]);

  const handleNameBlur = () => {
    if (localName.trim() && localName !== config.name) {
      onUpdate({ name: localName.trim() });
    } else {
      setLocalName(config.name);
    }
  };

  const handleDescBlur = () => {
    if (localDesc !== config.description) {
      onUpdate({ description: localDesc });
    }
  };

  const handleCdaSeatedBlur = () => {
    const num = parseFloat(localCdaSeated);
    if (!isNaN(num) && num > 0 && num < 1) {
      onUpdate({ cdaSeated: num });
    } else {
      setLocalCdaSeated(config.cdaSeated.toString());
    }
  };

  const handleCdaStandingBlur = () => {
    const num = parseFloat(localCdaStanding);
    if (!isNaN(num) && num > 0 && num < 1) {
      onUpdate({ cdaStanding: num });
    } else {
      setLocalCdaStanding(config.cdaStanding.toString());
    }
  };

  return (
    <View style={[styles.kitCard, config.isDefault && styles.kitCardDefault]}>
      {/* Card Header - always visible */}
      <TouchableOpacity style={styles.kitCardHeader} onPress={onToggleExpand}>
        <View style={styles.kitCardHeaderLeft}>
          {config.isDefault && (
            <Text style={styles.defaultBadge}>DEFAULT</Text>
          )}
          <Text style={styles.kitCardName}>{config.name}</Text>
          {config.description ? (
            <Text style={styles.kitCardDesc} numberOfLines={1}>{config.description}</Text>
          ) : null}
        </View>
        <View style={styles.kitCardHeaderRight}>
          <Text style={styles.kitCardCda}>
            {config.cdaSeated.toFixed(3)} / {config.cdaStanding.toFixed(3)}
          </Text>
          <Text style={styles.expandIcon}>{expanded ? '\u2212' : '+'}</Text>
        </View>
      </TouchableOpacity>

      {/* Expanded Content */}
      {expanded && (
        <View style={styles.kitCardContent}>
          {/* Name */}
          <View style={styles.fieldRow}>
            <Text style={styles.fieldLabel}>Name</Text>
            <TextInput
              style={styles.fieldInput}
              value={localName}
              onChangeText={setLocalName}
              onBlur={handleNameBlur}
              maxLength={30}
            />
          </View>

          {/* Description */}
          <View style={styles.fieldRow}>
            <Text style={styles.fieldLabel}>Description</Text>
            <TextInput
              style={styles.fieldInput}
              value={localDesc}
              onChangeText={setLocalDesc}
              onBlur={handleDescBlur}
              placeholder="Optional description"
              placeholderTextColor="#5a7a9a"
              maxLength={60}
            />
          </View>

          {/* CdA Values */}
          <View style={styles.cdaRow}>
            <View style={styles.cdaField}>
              <Text style={styles.fieldLabel}>CdA Seated</Text>
              <View style={styles.cdaInputWrapper}>
                <TextInput
                  style={styles.cdaInput}
                  value={localCdaSeated}
                  onChangeText={setLocalCdaSeated}
                  onBlur={handleCdaSeatedBlur}
                  keyboardType="decimal-pad"
                />
                <Text style={styles.cdaUnit}>m²</Text>
              </View>
            </View>
            <View style={styles.cdaField}>
              <Text style={styles.fieldLabel}>CdA Standing</Text>
              <View style={styles.cdaInputWrapper}>
                <TextInput
                  style={styles.cdaInput}
                  value={localCdaStanding}
                  onChangeText={setLocalCdaStanding}
                  onBlur={handleCdaStandingBlur}
                  keyboardType="decimal-pad"
                />
                <Text style={styles.cdaUnit}>m²</Text>
              </View>
            </View>
          </View>

          {/* Divider */}
          <View style={styles.divider} />

          {/* Equipment Selectors (informative only) */}
          <Text style={styles.equipmentTitle}>Equipment (informative)</Text>

          {/* Front Wheel */}
          <View style={styles.equipmentRow}>
            <Text style={styles.equipmentLabel}>Front Wheel</Text>
            <View style={styles.equipmentOptions}>
              {([
                { value: 'front_disc' as FrontWheelType, label: 'Disc' },
                { value: '345_spoke' as FrontWheelType, label: '3/4/5' },
                { value: 'spokes' as FrontWheelType, label: 'Spokes' },
              ]).map((opt) => (
                <TouchableOpacity
                  key={opt.value}
                  style={[styles.equipOption, config.frontWheel === opt.value && styles.equipOptionSelected]}
                  onPress={() => onUpdate({ frontWheel: opt.value })}
                  activeOpacity={1}
                >
                  <Text style={[styles.equipOptionText, config.frontWheel === opt.value && styles.equipOptionTextSelected]}>
                    {opt.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* Rear Wheel */}
          <View style={styles.equipmentRow}>
            <Text style={styles.equipmentLabel}>Rear Wheel</Text>
            <View style={styles.equipmentOptions}>
              {([
                { value: 'rear_disc' as RearWheelType, label: 'Disc' },
                { value: 'spokes' as RearWheelType, label: 'Spokes' },
              ]).map((opt) => (
                <TouchableOpacity
                  key={opt.value}
                  style={[styles.equipOption, config.rearWheel === opt.value && styles.equipOptionSelected]}
                  onPress={() => onUpdate({ rearWheel: opt.value })}
                  activeOpacity={1}
                >
                  <Text style={[styles.equipOptionText, config.rearWheel === opt.value && styles.equipOptionTextSelected]}>
                    {opt.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* Apparel Toggles */}
          <View style={styles.apparelRow}>
            {([
              { key: 'speedSuit' as const, label: 'Suit', value: config.speedSuit },
              { key: 'aeroHelmet' as const, label: 'Helmet', value: config.aeroHelmet },
              { key: 'shoeCovers' as const, label: 'Shoes', value: config.shoeCovers },
            ]).map((item) => (
              <TouchableOpacity
                key={item.key}
                style={styles.apparelToggleCol}
                onPress={() => onUpdate({ [item.key]: !item.value })}
              >
                <Text style={styles.apparelLabel}>{item.label}</Text>
                <View style={[styles.apparelToggle, item.value ? styles.apparelOn : styles.apparelOff]}>
                  <Text style={styles.apparelToggleText}>{item.value ? 'On' : 'Off'}</Text>
                </View>
              </TouchableOpacity>
            ))}
          </View>

          {/* Actions */}
          <View style={styles.cardActions}>
            {!config.isDefault && (
              <TouchableOpacity style={styles.setDefaultButton} onPress={onSetDefault}>
                <Text style={styles.setDefaultText}>Set as Default</Text>
              </TouchableOpacity>
            )}
            {canDelete && (
              <TouchableOpacity style={styles.deleteButton} onPress={() => {
                Alert.alert(
                  'Delete Configuration',
                  `Delete "${config.name}"?`,
                  [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Delete', style: 'destructive', onPress: onDelete },
                  ]
                );
              }}>
                <Text style={styles.deleteText}>Delete</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      )}
    </View>
  );
}

export default function KitScreen() {
  const {
    kitConfigs,
    addKitConfig,
    updateKitConfig,
    removeKitConfig,
    setDefaultKitConfig,
  } = useAppStore();

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleAddConfig = () => {
    if (kitConfigs.length >= MAX_KIT_CONFIGS) {
      Alert.alert('Limit Reached', `Maximum of ${MAX_KIT_CONFIGS} configurations allowed.`);
      return;
    }

    const newConfig: NamedKitConfig = {
      id: generateId(),
      name: `Config ${kitConfigs.length + 1}`,
      description: '',
      cdaSeated: 0.24,
      cdaStanding: 0.38,
      frontWheel: '345_spoke',
      rearWheel: 'rear_disc',
      speedSuit: true,
      aeroHelmet: true,
      shoeCovers: true,
      isDefault: false,
    };

    addKitConfig(newConfig);
    setExpandedId(newConfig.id);
  };

  const handleResetAll = () => {
    Alert.alert(
      'Reset All Configurations',
      'This will remove all kit configurations and restore the default.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: () => {
            // Remove all and add back defaults
            const store = useAppStore.getState();
            // We need to set kitConfigs directly - use the raw set
            useAppStore.setState({ kitConfigs: [...DEFAULT_KIT_CONFIGS] });
            setExpandedId(null);
          },
        },
      ]
    );
  };

  return (
    <ScrollView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Kit Configurations</Text>
        <Text style={styles.headerSubtitle}>
          Manage up to {MAX_KIT_CONFIGS} named equipment configurations.
          Each has its own CdA values. The default is used in simulations.
        </Text>
      </View>

      {/* Kit Cards */}
      {kitConfigs.map((config) => (
        <KitCard
          key={config.id}
          config={config}
          expanded={expandedId === config.id}
          onToggleExpand={() => setExpandedId(expandedId === config.id ? null : config.id)}
          onUpdate={(updates) => updateKitConfig(config.id, updates)}
          onSetDefault={() => setDefaultKitConfig(config.id)}
          onDelete={() => {
            removeKitConfig(config.id);
            if (expandedId === config.id) setExpandedId(null);
          }}
          canDelete={kitConfigs.length > 1}
        />
      ))}

      {/* Add Button */}
      {kitConfigs.length < MAX_KIT_CONFIGS && (
        <TouchableOpacity style={styles.addButton} onPress={handleAddConfig}>
          <Text style={styles.addButtonText}>+ Add Configuration</Text>
        </TouchableOpacity>
      )}

      {/* Reset Button */}
      <TouchableOpacity style={styles.resetButton} onPress={handleResetAll}>
        <Text style={styles.resetText}>Reset to Defaults</Text>
      </TouchableOpacity>

      <View style={styles.bottomPadding} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
  },
  header: {
    padding: 16,
    backgroundColor: colors.bg1,
    marginBottom: 8,
  },
  headerTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
    marginBottom: 8,
  },
  headerSubtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
  },
  kitCard: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginBottom: 8,
    borderRadius: 12,
    overflow: 'hidden',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  kitCardDefault: {
    borderColor: colors.accent,
  },
  kitCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
  },
  kitCardHeaderLeft: {
    flex: 1,
    marginRight: 12,
  },
  kitCardHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  defaultBadge: {
    color: colors.accent,
    fontSize: 10,
    fontFamily: fonts.sansBold,
    letterSpacing: 1,
    marginBottom: 4,
  },
  kitCardName: {
    color: colors.textPrimary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  kitCardDesc: {
    color: colors.textSecondary,
    fontSize: 12,
    marginTop: 2,
  },
  kitCardCda: {
    color: colors.success,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    fontVariant: ['tabular-nums'],
  },
  expandIcon: {
    color: colors.textSecondary,
    fontSize: 20,
    fontFamily: fonts.sansBold,
  },
  kitCardContent: {
    paddingHorizontal: 16,
    paddingBottom: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  fieldRow: {
    marginTop: 12,
  },
  fieldLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 6,
  },
  fieldInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    fontSize: 14,
  },
  cdaRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 12,
  },
  cdaField: {
    flex: 1,
  },
  cdaInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  cdaInput: {
    flex: 1,
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    fontSize: 14,
    textAlign: 'right',
  },
  cdaUnit: {
    color: colors.textSecondary,
    fontSize: 12,
    marginLeft: 8,
    minWidth: 24,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginTop: 16,
    marginBottom: 12,
  },
  equipmentTitle: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
    textTransform: 'uppercase',
    marginBottom: 12,
  },
  equipmentRow: {
    marginBottom: 12,
  },
  equipmentLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: 6,
  },
  equipmentOptions: {
    flexDirection: 'row',
    gap: 6,
  },
  equipOption: {
    flex: 1,
    backgroundColor: colors.bg0,
    paddingVertical: 8,
    paddingHorizontal: 6,
    borderRadius: 6,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  equipOptionSelected: {
    borderColor: colors.accent,
    backgroundColor: colors.bg2,
  },
  equipOptionText: {
    color: colors.textMuted,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  equipOptionTextSelected: {
    color: colors.textPrimary,
  },
  apparelRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  apparelToggleCol: {
    flex: 1,
    alignItems: 'center',
    gap: 4,
  },
  apparelLabel: {
    color: colors.textSecondary,
    fontSize: 11,
  },
  apparelToggle: {
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 6,
    minWidth: 50,
    alignItems: 'center',
  },
  apparelOn: {
    backgroundColor: colors.success,
  },
  apparelOff: {
    backgroundColor: colors.textMuted,
  },
  apparelToggleText: {
    color: colors.textPrimary,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  cardActions: {
    flexDirection: 'row',
    gap: 8,
  },
  setDefaultButton: {
    flex: 1,
    backgroundColor: colors.seated,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  setDefaultText: {
    color: colors.textPrimary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  deleteButton: {
    backgroundColor: '#7f1d1d',
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    alignItems: 'center',
  },
  deleteText: {
    color: '#fca5a5',
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  addButton: {
    backgroundColor: colors.bg1,
    marginHorizontal: 8,
    marginBottom: 8,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: 'dashed',
  },
  addButtonText: {
    color: colors.accent,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
  },
  resetButton: {
    backgroundColor: colors.bg3,
    marginHorizontal: 8,
    marginBottom: 8,
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  resetText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  bottomPadding: {
    height: 40,
  },
});

import { colors, fonts, spacing } from '../../theme';
import React, { useState, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Alert,
  Dimensions,
  TextInput,
  Platform,
} from 'react-native';
import Svg, { Path, Line, Circle, Text as SvgText, Rect, Polyline } from 'react-native-svg';
import { useAppStore, type SavedEffort, type EffortType, TRACK_SEGMENTS } from '../../store/simulationStore';

const isWeb = Platform.OS === 'web';
const screenWidth = Dimensions.get('window').width;

type DatePreset = '30d' | '90d' | '6mo' | 'all';
type EffortFilter = EffortType | 'all';

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function SavedScreen() {
  const { savedEfforts, removeSavedEffort, updateSavedEffortRealTime, updateSavedEffortNotes, clearSavedEfforts } = useAppStore();

  const [effortFilter, setEffortFilter] = useState<EffortFilter>('all');
  const [datePreset, setDatePreset] = useState<DatePreset>('all');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editRealTime, setEditRealTime] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const dateStart = useMemo(() => {
    switch (datePreset) {
      case '30d': return daysAgo(30);
      case '90d': return daysAgo(90);
      case '6mo': return daysAgo(183);
      default: return null;
    }
  }, [datePreset]);

  const filteredEfforts = useMemo(() => {
    let efforts = [...savedEfforts];
    if (effortFilter !== 'all') {
      efforts = efforts.filter(e => e.effortType === effortFilter);
    }
    if (dateStart) {
      efforts = efforts.filter(e => e.activityDate >= dateStart);
    }
    efforts.sort((a, b) => a.activityDate.localeCompare(b.activityDate));
    return efforts;
  }, [savedEfforts, effortFilter, dateStart]);

  // For list display (newest first)
  const effortsDescending = useMemo(() => [...filteredEfforts].reverse(), [filteredEfforts]);

  const confirmDelete = (id: string, name: string) => {
    const doDelete = () => removeSavedEffort(id);
    if (isWeb) {
      if (window.confirm(`Delete saved effort "${name}"?`)) doDelete();
    } else {
      Alert.alert('Delete Effort', `Delete saved effort "${name}"?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: doDelete },
      ]);
    }
  };

  const confirmClearAll = () => {
    const doClear = () => clearSavedEfforts();
    if (isWeb) {
      if (window.confirm(`Delete ALL ${savedEfforts.length} saved efforts?`)) doClear();
    } else {
      Alert.alert('Clear All', `Delete ALL ${savedEfforts.length} saved efforts?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete All', style: 'destructive', onPress: doClear },
      ]);
    }
  };

  const startEditRealTime = (effort: SavedEffort) => {
    setEditingId(effort.id);
    setEditRealTime(effort.realTime?.toFixed(3) ?? '');
  };

  const saveRealTimeEdit = () => {
    if (!editingId) return;
    const val = parseFloat(editRealTime);
    updateSavedEffortRealTime(editingId, isNaN(val) || val <= 0 ? undefined : val);
    setEditingId(null);
  };

  return (
    <ScrollView style={styles.container}>
      {/* Effort type filter */}
      <View style={styles.filterRow}>
        {(['all', 50, 100, 150, 200] as EffortFilter[]).map((f) => (
          <TouchableOpacity
            key={String(f)}
            style={[styles.filterChip, effortFilter === f && styles.filterChipActive]}
            onPress={() => setEffortFilter(f)}
          >
            <Text style={[styles.filterChipText, effortFilter === f && styles.filterChipTextActive]}>
              {f === 'all' ? 'All' : `F${f}`}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Date range presets */}
      <View style={styles.filterRow}>
        {(['30d', '90d', '6mo', 'all'] as DatePreset[]).map((p) => (
          <TouchableOpacity
            key={p}
            style={[styles.filterChip, datePreset === p && styles.filterChipActive]}
            onPress={() => setDatePreset(p)}
          >
            <Text style={[styles.filterChipText, datePreset === p && styles.filterChipTextActive]}>
              {p === 'all' ? 'All Time' : p}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Chart */}
      {filteredEfforts.length >= 2 ? (
        <ProgressionChart efforts={filteredEfforts} />
      ) : filteredEfforts.length === 1 ? (
        <View style={styles.chartPlaceholder}>
          <Text style={styles.placeholderText}>Need at least 2 efforts to show chart</Text>
        </View>
      ) : (
        <View style={styles.chartPlaceholder}>
          <Text style={styles.placeholderText}>No saved efforts yet</Text>
          <Text style={styles.placeholderSubtext}>Run a simulation and tap "Save Effort"</Text>
        </View>
      )}

      {/* Effort list */}
      {effortsDescending.length > 0 && (
        <View style={styles.listSection}>
          <View style={styles.listHeader}>
            <Text style={styles.listTitle}>
              {filteredEfforts.length} effort{filteredEfforts.length !== 1 ? 's' : ''}
            </Text>
            {savedEfforts.length > 0 && (
              <TouchableOpacity onPress={confirmClearAll}>
                <Text style={styles.clearAllText}>Clear All</Text>
              </TouchableOpacity>
            )}
          </View>

          {effortsDescending.map((effort) => {
            const isExpanded = expandedId === effort.id;
            return (
              <View key={effort.id} style={styles.effortCard}>
                <TouchableOpacity
                  activeOpacity={0.8}
                  onPress={() => setExpandedId(isExpanded ? null : effort.id)}
                >
                  <View style={styles.effortHeader}>
                    <View style={styles.effortMeta}>
                      <Text style={styles.effortDate}>{effort.activityDate}</Text>
                      <View style={styles.effortTypeBadge}>
                        <Text style={styles.effortTypeText}>F{effort.effortType}</Text>
                      </View>
                    </View>
                    <View style={styles.effortHeaderRight}>
                      <Text style={styles.expandIcon}>{isExpanded ? '−' : '+'}</Text>
                      <TouchableOpacity onPress={() => confirmDelete(effort.id, effort.activityName)}>
                        <Text style={styles.deleteText}>Delete</Text>
                      </TouchableOpacity>
                    </View>
                  </View>

                  <Text style={styles.effortName} numberOfLines={1}>{effort.activityName}</Text>

                  <View style={styles.timesRow}>
                    <View style={styles.timeBlock}>
                      <Text style={styles.timeLabel}>Standard</Text>
                      <Text style={styles.timeValue}>{effort.standardizedT200.toFixed(3)}s</Text>
                    </View>
                    <View style={styles.timeBlock}>
                      <Text style={styles.timeLabel}>Raw Sim</Text>
                      <Text style={styles.timeValueSecondary}>{effort.rawT200.toFixed(3)}s</Text>
                    </View>
                    <View style={styles.timeBlock}>
                      <Text style={styles.timeLabel}>Real</Text>
                      {editingId === effort.id ? (
                        <View style={styles.editRealTimeRow}>
                          <TextInput
                            style={styles.editRealTimeInput}
                            value={editRealTime}
                            onChangeText={setEditRealTime}
                            keyboardType="decimal-pad"
                            autoFocus
                            onBlur={saveRealTimeEdit}
                            onSubmitEditing={saveRealTimeEdit}
                          />
                        </View>
                      ) : (
                        <TouchableOpacity onPress={() => startEditRealTime(effort)}>
                          <Text style={[styles.timeValueReal, !effort.realTime && styles.timeValuePlaceholder]}>
                            {effort.realTime ? `${effort.realTime.toFixed(3)}s` : 'tap to add'}
                          </Text>
                        </TouchableOpacity>
                      )}
                    </View>
                  </View>
                </TouchableOpacity>

                {isExpanded && <EffortDetails effort={effort} onUpdateNotes={updateSavedEffortNotes} />}
              </View>
            );
          })}
        </View>
      )}

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

// Effort detail panel (shown when card is expanded)
function EffortDetails({ effort, onUpdateNotes }: { effort: SavedEffort; onUpdateNotes: (id: string, notes: string | undefined) => void }) {
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesInput, setNotesInput] = useState(effort.notes ?? '');
  const chartW = screenWidth - 64;
  const chartH = 140;
  const padL = 45;
  const padR = 12;
  const padT = 10;
  const padB = 24;
  const plotW = chartW - padL - padR;
  const plotH = chartH - padT - padB;

  const profile = effort.powerProfile;
  const hasProfile = profile && profile.length >= 2;

  // Power profile chart data
  let powerPoints = '';
  let maxP = 0;
  let minP = Infinity;
  let avgP = 0;
  let maxS = 0;
  if (hasProfile) {
    maxP = Math.max(...profile.map(p => p.P_W));
    minP = Math.min(...profile.map(p => p.P_W));
    avgP = profile.reduce((sum, p) => sum + p.P_W, 0) / profile.length;
    maxS = profile[profile.length - 1].s_m;
    const pRange = maxP - minP || 1;

    powerPoints = profile.map((p, i) => {
      const x = padL + (p.s_m / maxS) * plotW;
      const y = padT + plotH - ((p.P_W - minP) / pRange) * plotH;
      return `${x},${y}`;
    }).join(' ');
  }

  // Y-axis ticks for power chart
  const pRange = maxP - minP || 1;
  const yTicks = hasProfile ? [minP, minP + pRange * 0.5, maxP] : [];

  const sp = effort.standardParams;
  const rp = effort.rawParams;

  return (
    <View style={detailStyles.container}>
      <View style={detailStyles.divider} />

      {/* Standardized Parameters */}
      <Text style={detailStyles.sectionLabel}>Standardized Parameters</Text>
      <View style={detailStyles.paramsGrid}>
        <ParamCell label="CdA (seated)" value={sp.cda_seated.toFixed(4)} unit="m²" />
        <ParamCell label="CdA (standing)" value={sp.cda_standing.toFixed(4)} unit="m²" />
        <ParamCell label="Rho" value={sp.rho.toFixed(4)} unit="kg/m³" />
        <ParamCell label="Crr" value={sp.crr.toFixed(4)} />
        <ParamCell label="Mass" value={sp.mass_kg.toFixed(1)} unit="kg" />
        <ParamCell label="Drivetrain" value={`${(sp.drivetrain_eff * 100).toFixed(1)}%`} />
      </View>

      {/* Raw Sim Parameters (only show if different from standard) */}
      {(rp.cda_seated !== sp.cda_seated || rp.rho !== sp.rho || rp.crr !== sp.crr || rp.mass_kg !== sp.mass_kg) && (
        <>
          <Text style={detailStyles.sectionLabel}>Raw Sim Parameters</Text>
          <View style={detailStyles.paramsGrid}>
            <ParamCell label="CdA (seated)" value={rp.cda_seated.toFixed(4)} unit="m²" />
            <ParamCell label="CdA (standing)" value={rp.cda_standing.toFixed(4)} unit="m²" />
            <ParamCell label="Rho" value={rp.rho.toFixed(4)} unit="kg/m³" />
            <ParamCell label="Crr" value={rp.crr.toFixed(4)} />
            <ParamCell label="Mass" value={rp.mass_kg.toFixed(1)} unit="kg" />
            <ParamCell label="Drivetrain" value={`${(rp.drivetrain_eff * 100).toFixed(1)}%`} />
          </View>
        </>
      )}

      {/* Power Profile Chart */}
      {hasProfile && (
        <>
          <Text style={detailStyles.sectionLabel}>Power Profile</Text>
          <View style={detailStyles.chartWrap}>
            <Svg width={chartW} height={chartH}>
              <Rect x={padL} y={padT} width={plotW} height={plotH} fill="#0f1f33" rx={4} />

              {/* Position profile bands (seated=blue tint, standing=red tint) */}
              {effort.rawSegmentPositions && TRACK_SEGMENTS.filter(seg => seg.startM < maxS).map((seg) => {
                const pos = seg.locked ? 'seated' : (effort.rawSegmentPositions![seg.id] || 'seated');
                if (pos === 'seated') return null; // Only highlight standing segments
                const x1 = padL + (Math.max(seg.startM, 0) / maxS) * plotW;
                const x2 = padL + (Math.min(seg.endM, maxS) / maxS) * plotW;
                return (
                  <Rect
                    key={seg.id}
                    x={x1}
                    y={padT}
                    width={x2 - x1}
                    height={plotH}
                    fill="#ef4444"
                    opacity={0.15}
                  />
                );
              })}

              {/* Y-axis gridlines + labels */}
              {yTicks.map((t, i) => {
                const y = padT + plotH - ((t - minP) / pRange) * plotH;
                return (
                  <React.Fragment key={i}>
                    <Line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="#1e3a5f" strokeWidth={1} />
                    <SvgText x={padL - 4} y={y + 4} fill="#8aa4c0" fontSize={9} textAnchor="end">
                      {Math.round(t)}W
                    </SvgText>
                  </React.Fragment>
                );
              })}

              {/* Power line */}
              <Polyline points={powerPoints} fill="none" stroke="#f59e0b" strokeWidth={1.5} />

              {/* X-axis labels */}
              <SvgText x={padL} y={chartH - 4} fill="#8aa4c0" fontSize={9} textAnchor="start">0m</SvgText>
              <SvgText x={padL + plotW} y={chartH - 4} fill="#8aa4c0" fontSize={9} textAnchor="end">{Math.round(maxS)}m</SvgText>
            </Svg>

            <View style={detailStyles.powerStats}>
              <Text style={detailStyles.powerStatText}>Avg: {Math.round(avgP)}W</Text>
              <Text style={detailStyles.powerStatText}>Max: {Math.round(maxP)}W</Text>
              {effort.rawSegmentPositions && Object.values(effort.rawSegmentPositions).some(p => p === 'standing') && (
                <Text style={detailStyles.powerStatStanding}>Red = Standing</Text>
              )}
            </View>
          </View>
        </>
      )}

      {/* Notes */}
      <View style={detailStyles.notesSection}>
        <View style={detailStyles.notesSectionHeader}>
          <Text style={detailStyles.sectionLabel}>Notes</Text>
          {!editingNotes && (
            <TouchableOpacity onPress={() => { setNotesInput(effort.notes ?? ''); setEditingNotes(true); }}>
              <Text style={detailStyles.notesEditBtn}>{effort.notes ? 'Edit' : 'Add'}</Text>
            </TouchableOpacity>
          )}
        </View>
        {editingNotes ? (
          <View>
            <TextInput
              style={detailStyles.notesInput}
              value={notesInput}
              onChangeText={setNotesInput}
              placeholder="Add a note..."
              placeholderTextColor="#556b82"
              multiline
              autoFocus
            />
            <View style={detailStyles.notesActions}>
              <TouchableOpacity onPress={() => setEditingNotes(false)}>
                <Text style={detailStyles.notesCancelBtn}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => {
                onUpdateNotes(effort.id, notesInput.trim() || undefined);
                setEditingNotes(false);
              }}>
                <Text style={detailStyles.notesSaveBtn}>Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : effort.notes ? (
          <Text style={detailStyles.notesText}>{effort.notes}</Text>
        ) : (
          <Text style={detailStyles.notesPlaceholder}>No notes</Text>
        )}
      </View>

      {/* Meta info */}
      <View style={detailStyles.metaSection}>
        <Text style={detailStyles.metaText}>
          Source: {effort.source === 'strava' ? 'Strava' : 'FIT File'}
          {effort.activityMeta?.fileName ? ` — ${effort.activityMeta.fileName}` : ''}
        </Text>
        {effort.activityMeta?.device && (
          <Text style={detailStyles.metaText}>Device: {effort.activityMeta.device}</Text>
        )}
        {effort.activityMeta?.rideDuration != null && (
          <Text style={detailStyles.metaText}>
            Ride duration: {Math.floor(effort.activityMeta.rideDuration / 60)}m {Math.round(effort.activityMeta.rideDuration % 60)}s
          </Text>
        )}
        {effort.activityMeta?.sensors && effort.activityMeta.sensors.length > 0 ? (
          effort.activityMeta.sensors.map((s, i) => (
            <Text key={i} style={detailStyles.metaText}>
              {s.type || 'Sensor'}: {s.name || 'Unknown'}
            </Text>
          ))
        ) : (
          <Text style={detailStyles.metaText}>
            Sensors:{' '}
            {[
              effort.activityMeta?.hasPower && 'Power',
              effort.activityMeta?.hasCadence && 'Cadence',
              effort.activityMeta?.hasSpeed && 'Speed',
              effort.activityMeta?.hasHeartRate && 'HR',
            ].filter(Boolean).join(', ') || 'N/A'}
          </Text>
        )}
        <Text style={detailStyles.metaText}>
          Effort rows: {effort.effortStartIndex} – {effort.effortEndIndex}
        </Text>
        <Text style={detailStyles.metaText}>
          Date: {effort.activityDate} · Saved: {effort.savedAt.slice(0, 10)}
        </Text>
      </View>
    </View>
  );
}

function ParamCell({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <View style={detailStyles.paramCell}>
      <Text style={detailStyles.paramLabel}>{label}</Text>
      <Text style={detailStyles.paramValue}>
        {value}{unit ? <Text style={detailStyles.paramUnit}> {unit}</Text> : null}
      </Text>
    </View>
  );
}

const detailStyles = StyleSheet.create({
  container: {
    marginTop: 10,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginBottom: 10,
  },
  sectionLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fonts.sansBold,
    textTransform: 'uppercase',
    marginBottom: 6,
    marginTop: 8,
  },
  paramsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
  },
  paramCell: {
    width: '31%' as unknown as number,
    backgroundColor: colors.bg0,
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 8,
  },
  paramLabel: {
    color: colors.textMuted,
    fontSize: 9,
    marginBottom: 2,
  },
  paramValue: {
    color: colors.textPrimary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  paramUnit: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: '400',
  },
  chartWrap: {
    marginTop: 4,
  },
  powerStats: {
    flexDirection: 'row',
    gap: 16,
    marginTop: 4,
    paddingLeft: 4,
  },
  powerStatText: {
    color: colors.warning,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
  },
  powerStatStanding: {
    color: colors.danger,
    fontSize: 11,
    fontFamily: fonts.sansSemiBold,
    opacity: 0.8,
  },
  notesSection: {
    marginTop: 10,
  },
  notesSectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  notesEditBtn: {
    color: colors.accent,
    fontSize: 12,
    fontFamily: fonts.sansSemiBold,
  },
  notesInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    fontSize: 13,
    padding: 10,
    borderRadius: 6,
    minHeight: 60,
    textAlignVertical: 'top',
  },
  notesActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 16,
    marginTop: 8,
  },
  notesCancelBtn: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  notesSaveBtn: {
    color: colors.accent,
    fontSize: 13,
    fontFamily: fonts.sansBold,
  },
  notesText: {
    color: '#c0d0e0',
    fontSize: 13,
    lineHeight: 18,
  },
  notesPlaceholder: {
    color: colors.textMuted,
    fontSize: 12,
    fontStyle: 'italic',
  },
  metaSection: {
    marginTop: 12,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: colors.bg1,
    gap: 3,
  },
  metaText: {
    color: colors.textMuted,
    fontSize: 11,
  },
});

// Progression chart component
function ProgressionChart({ efforts }: { efforts: SavedEffort[] }) {
  const chartW = screenWidth - 32;
  const chartH = 220;
  const padL = 55;
  const padR = 16;
  const padT = 16;
  const padB = 40;
  const plotW = chartW - padL - padR;
  const plotH = chartH - padT - padB;

  // Data points
  const standardTimes = efforts.map(e => e.standardizedT200);
  const realTimes = efforts.filter(e => e.realTime != null).map(e => e.realTime!);
  const allTimes = [...standardTimes, ...realTimes];

  const minTime = Math.min(...allTimes) - 0.1;
  const maxTime = Math.max(...allTimes) + 0.1;
  const timeRange = maxTime - minTime || 1;

  // Map date string to x position
  const dateToX = (i: number) => padL + (i / Math.max(efforts.length - 1, 1)) * plotW;
  // Lower time = higher on chart (better)
  const timeToY = (t: number) => padT + ((t - minTime) / timeRange) * plotH;

  // Build standard line path
  const standardPath = efforts.map((e, i) => {
    const x = dateToX(i);
    const y = timeToY(e.standardizedT200);
    return `${i === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');

  // Build real time path (only for efforts that have it)
  const realEffortIndices = efforts
    .map((e, i) => e.realTime != null ? i : -1)
    .filter(i => i >= 0);
  const realPath = realEffortIndices.map((idx, j) => {
    const x = dateToX(idx);
    const y = timeToY(efforts[idx].realTime!);
    return `${j === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');

  // Y-axis ticks
  const numTicks = 5;
  const yTicks = Array.from({ length: numTicks }, (_, i) => {
    const t = minTime + (timeRange * i) / (numTicks - 1);
    return t;
  });

  // X-axis labels (show first, middle, last dates)
  const xLabels: { i: number; label: string }[] = [];
  if (efforts.length > 0) {
    xLabels.push({ i: 0, label: efforts[0].activityDate.slice(5) });
    if (efforts.length > 2) {
      const mid = Math.floor(efforts.length / 2);
      xLabels.push({ i: mid, label: efforts[mid].activityDate.slice(5) });
    }
    if (efforts.length > 1) {
      xLabels.push({ i: efforts.length - 1, label: efforts[efforts.length - 1].activityDate.slice(5) });
    }
  }

  return (
    <View style={styles.chartContainer}>
      <Svg width={chartW} height={chartH}>
        {/* Background */}
        <Rect x={padL} y={padT} width={plotW} height={plotH} fill="#1a2f47" rx={4} />

        {/* Y-axis gridlines + labels */}
        {yTicks.map((t, i) => {
          const y = timeToY(t);
          return (
            <React.Fragment key={i}>
              <Line x1={padL} y1={y} x2={padL + plotW} y2={y} stroke="#2d4a6f" strokeWidth={1} />
              <SvgText x={padL - 6} y={y + 4} fill="#8aa4c0" fontSize={10} textAnchor="end">
                {t.toFixed(2)}s
              </SvgText>
            </React.Fragment>
          );
        })}

        {/* Standard line */}
        <Path d={standardPath} stroke="#4da6ff" strokeWidth={2} fill="none" />
        {efforts.map((e, i) => (
          <Circle key={`s${i}`} cx={dateToX(i)} cy={timeToY(e.standardizedT200)} r={4} fill="#4da6ff" />
        ))}

        {/* Real time line */}
        {realPath && realEffortIndices.length >= 2 && (
          <Path d={realPath} stroke="#4ade80" strokeWidth={2} fill="none" strokeDasharray="4,4" />
        )}
        {realEffortIndices.map((idx) => (
          <Circle key={`r${idx}`} cx={dateToX(idx)} cy={timeToY(efforts[idx].realTime!)} r={4} fill="#4ade80" />
        ))}

        {/* X-axis labels */}
        {xLabels.map(({ i, label }) => (
          <SvgText
            key={`xl${i}`}
            x={dateToX(i)}
            y={chartH - 6}
            fill="#8aa4c0"
            fontSize={10}
            textAnchor="middle"
          >
            {label}
          </SvgText>
        ))}
      </Svg>

      {/* Legend */}
      <View style={styles.legend}>
        <View style={styles.legendItem}>
          <View style={[styles.legendDot, { backgroundColor: colors.accent }]} />
          <Text style={styles.legendText}>Standard Sim</Text>
        </View>
        {realEffortIndices.length > 0 && (
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: colors.success }]} />
            <Text style={styles.legendText}>Real Time</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
  },
  filterRow: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingTop: 12,
    gap: 8,
  },
  filterChip: {
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: colors.bg1,
    borderWidth: 1,
    borderColor: colors.border,
  },
  filterChipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  filterChipText: {
    color: colors.textSecondary,
    fontSize: 13,
    fontFamily: fonts.sansSemiBold,
  },
  filterChipTextActive: {
    color: colors.textPrimary,
  },
  chartContainer: {
    margin: 16,
  },
  chartPlaceholder: {
    margin: 16,
    backgroundColor: colors.bg1,
    borderRadius: 8,
    padding: 40,
    alignItems: 'center',
  },
  placeholderText: {
    color: colors.textSecondary,
    fontSize: 16,
  },
  placeholderSubtext: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 8,
  },
  legend: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 20,
    marginTop: 8,
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
  listSection: {
    paddingHorizontal: 16,
  },
  listHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  listTitle: {
    color: colors.textSecondary,
    fontSize: 14,
    fontFamily: fonts.sansSemiBold,
    textTransform: 'uppercase',
  },
  clearAllText: {
    color: colors.danger,
    fontSize: 13,
  },
  effortCard: {
    backgroundColor: colors.bg1,
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
  },
  effortHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  effortHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  expandIcon: {
    color: colors.textSecondary,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  effortMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  effortDate: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  effortTypeBadge: {
    backgroundColor: colors.border,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  effortTypeText: {
    color: colors.accent,
    fontSize: 11,
    fontFamily: fonts.sansBold,
  },
  deleteText: {
    color: colors.danger,
    fontSize: 12,
  },
  effortName: {
    color: colors.textPrimary,
    fontSize: 15,
    fontFamily: fonts.sansSemiBold,
    marginTop: 6,
    marginBottom: 10,
  },
  timesRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  timeBlock: {
    flex: 1,
  },
  timeLabel: {
    color: colors.textMuted,
    fontSize: 11,
    marginBottom: 2,
  },
  timeValue: {
    color: colors.accent,
    fontSize: 18,
    fontFamily: fonts.sansBold,
  },
  timeValueSecondary: {
    color: colors.textSecondary,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  timeValueReal: {
    color: colors.success,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
  },
  timeValuePlaceholder: {
    color: colors.textMuted,
    fontWeight: '400',
    fontSize: 13,
    fontStyle: 'italic',
  },
  editRealTimeRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  editRealTimeInput: {
    backgroundColor: colors.bg0,
    color: colors.success,
    fontSize: 16,
    fontFamily: fonts.sansSemiBold,
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: 4,
    width: 80,
  },
});

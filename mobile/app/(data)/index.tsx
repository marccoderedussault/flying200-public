import { useState, useEffect, useCallback } from 'react';
import { colors, fonts, spacing } from '../../theme';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  RefreshControl,
  Alert,
  TextInput,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import * as DocumentPicker from 'expo-document-picker';
import { useAppStore } from '../../store/simulationStore';
import { stravaApi, fitApi, setBaseUrl, healthCheck, type StravaActivity } from '../../api/client';

const isWeb = Platform.OS === 'web';

if (!isWeb) {
  WebBrowser.maybeCompleteAuthSession();
}

export default function HomeScreen() {
  const router = useRouter();
  const {
    apiBaseUrl,
    setApiBaseUrl,
    stravaSessionId,
    stravaAthlete,
    setStravaSession,
    clearStravaSession,
    setCurrentActivity,
  } = useAppStore();

  const [activities, setActivities] = useState<StravaActivity[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [serverConnected, setServerConnected] = useState<boolean | null>(null);
  const [showApiConfig, setShowApiConfig] = useState(false);
  const [tempApiUrl, setTempApiUrl] = useState(apiBaseUrl);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [dateAfter, setDateAfter] = useState('');   // YYYY-MM-DD
  const [dateBefore, setDateBefore] = useState('');  // YYYY-MM-DD
  const [showDateFilter, setShowDateFilter] = useState(false);

  // Check server connection on mount
  useEffect(() => {
    checkServerConnection();
  }, [apiBaseUrl]);

  // Load activities when we have a session
  useEffect(() => {
    if (stravaSessionId && stravaAthlete) {
      loadActivities();
    }
  }, [stravaSessionId, stravaAthlete]);

  const checkServerConnection = async () => {
    try {
      setBaseUrl(apiBaseUrl);
      const result = await healthCheck();
      setServerConnected(result.status === 'ok');
    } catch (error) {
      setServerConnected(false);
    }
  };

  const saveApiUrl = () => {
    setApiBaseUrl(tempApiUrl);
    setBaseUrl(tempApiUrl);
    setShowApiConfig(false);
    checkServerConnection();
  };

  const connectToStrava = async () => {
    try {
      setConnecting(true);

      if (isWeb) {
        // Web: open popup window, listen for postMessage from backend oauth-callback
        const sessionId = `web_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const authUrl = await stravaApi.getAuthUrl(true, sessionId);

        const popup = window.open(authUrl, 'strava-auth', 'width=600,height=700');

        // Listen for the postMessage from the popup
        const onMessage = (event: MessageEvent) => {
          try {
            const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
            if (data.success === 'true' && data.athlete_id) {
              setStravaSession(data.state || sessionId, {
                id: parseInt(data.athlete_id),
                firstname: data.athlete_firstname,
                lastname: data.athlete_lastname,
              });
            } else if (data.error) {
              alert(`Strava authentication failed: ${data.error}`);
            }
          } catch {
            // Ignore non-JSON messages
          } finally {
            window.removeEventListener('message', onMessage);
            setConnecting(false);
          }
        };
        window.addEventListener('message', onMessage);

        // Also handle popup being closed without completing auth
        const checkClosed = setInterval(() => {
          if (popup?.closed) {
            clearInterval(checkClosed);
            window.removeEventListener('message', onMessage);
            setConnecting(false);
          }
        }, 500);
      } else {
        // Native: use expo-web-browser + deep link
        const sessionId = `mobile_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const authUrl = await stravaApi.getAuthUrl(true, sessionId);

        const result = await WebBrowser.openAuthSessionAsync(
          authUrl,
          'flying200://strava-callback'
        );

        if (result.type === 'success' && result.url) {
          const url = new URL(result.url);
          const success = url.searchParams.get('success');
          const error = url.searchParams.get('error');
          const state = url.searchParams.get('state');
          const athleteId = url.searchParams.get('athlete_id');
          const athleteFirstname = url.searchParams.get('athlete_firstname');
          const athleteLastname = url.searchParams.get('athlete_lastname');

          if (success === 'true' && athleteId && athleteFirstname && athleteLastname) {
            setStravaSession(state || sessionId, {
              id: parseInt(athleteId),
              firstname: athleteFirstname,
              lastname: athleteLastname,
            });
          } else if (error) {
            Alert.alert('Error', `Strava authentication failed: ${error}`);
          } else {
            Alert.alert('Error', 'Failed to authenticate with Strava');
          }
        }
        setConnecting(false);
      }
    } catch (error) {
      console.error('Strava connect error:', error);
      if (isWeb) {
        alert('Failed to connect to Strava');
      } else {
        Alert.alert('Error', 'Failed to connect to Strava');
      }
      setConnecting(false);
    }
  };

  const disconnectStrava = () => {
    const doDisconnect = async () => {
      await stravaApi.disconnect(stravaSessionId || undefined);
      clearStravaSession();
      setActivities([]);
    };

    if (isWeb) {
      if (window.confirm('Are you sure you want to disconnect from Strava?')) {
        doDisconnect();
      }
    } else {
      Alert.alert(
        'Disconnect Strava',
        'Are you sure you want to disconnect from Strava?',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Disconnect', style: 'destructive', onPress: doDisconnect },
        ]
      );
    }
  };

  const getDateFilters = () => {
    const after = dateAfter ? Math.floor(new Date(dateAfter).getTime() / 1000) : undefined;
    const before = dateBefore ? Math.floor(new Date(dateBefore + 'T23:59:59').getTime() / 1000) : undefined;
    return { after, before };
  };

  const loadActivities = async () => {
    if (!stravaSessionId) return;

    try {
      setLoading(true);
      setPage(1);
      const { after, before } = getDateFilters();
      const result = await stravaApi.getActivities(stravaSessionId, 1, 30, after, before);
      // Filter to only Ride activities with power
      const rides = result.filter(
        (a) => (a.type === 'Ride' || a.sport_type === 'Ride') && a.device_watts
      );
      setActivities(rides);
      setHasMore(result.length === 30);
    } catch (error: unknown) {
      const axiosError = error as { response?: { status?: number }; code?: string; message?: string };

      if (axiosError.response?.status === 401) {
        console.log('Session expired (401) - clearing session');
        clearStravaSession();
        setActivities([]);
      } else if (axiosError.code === 'ERR_NETWORK' || axiosError.message?.includes('Network')) {
        console.log('Network error - clearing stale session');
        clearStravaSession();
        setActivities([]);
      } else {
        console.error('Unexpected activity load error:', axiosError.message || error);
        Alert.alert('Error', 'Failed to load activities. Please try reconnecting.');
        clearStravaSession();
        setActivities([]);
      }
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    if (!stravaSessionId || loadingMore || !hasMore) return;
    try {
      setLoadingMore(true);
      const nextPage = page + 1;
      const { after, before } = getDateFilters();
      const result = await stravaApi.getActivities(stravaSessionId, nextPage, 30, after, before);
      const rides = result.filter(
        (a) => (a.type === 'Ride' || a.sport_type === 'Ride') && a.device_watts
      );
      setActivities((prev) => [...prev, ...rides]);
      setPage(nextPage);
      setHasMore(result.length === 30);
    } catch (error) {
      console.error('Load more error:', error);
    } finally {
      setLoadingMore(false);
    }
  };

  const applyDateFilter = () => {
    loadActivities();
  };

  const clearDateFilter = () => {
    setDateAfter('');
    setDateBefore('');
    // Reload will happen via the effect below
  };

  // Reload when date filters are cleared
  useEffect(() => {
    if (stravaSessionId && stravaAthlete && !dateAfter && !dateBefore) {
      loadActivities();
    }
  }, [dateAfter, dateBefore]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadActivities();
    setRefreshing(false);
  }, [stravaSessionId]);

  const selectActivity = async (activity: StravaActivity) => {
    try {
      setLoading(true);
      // Fetch activity streams
      const streams = await stravaApi.getActivityStreams(activity.id, stravaSessionId || undefined);
      if (streams.success) {
        setCurrentActivity({
          activityId: activity.id,
          activityName: activity.name,
          records: streams.records,
          summary: streams.summary,
          source: 'strava',
          stravaStartDateLocal: activity.start_date_local,
        });
        router.push('/(data)/analysis');
      } else {
        Alert.alert('Error', 'Failed to load activity data');
      }
    } catch (error: unknown) {
      const axiosError = error as { response?: { status?: number }; message?: string };
      // Handle 401 silently - session expired
      if (axiosError.response?.status === 401) {
        console.log('Session expired (401) - clearing session');
        clearStravaSession();
        setActivities([]);
      } else {
        console.error('Select activity error:', axiosError.message || error);
        Alert.alert('Error', 'Failed to load activity data');
      }
    } finally {
      setLoading(false);
    }
  };

  const uploadFitFile = async () => {
    try {
      let fileName: string;
      let fileUri: string;
      let webFile: File | undefined;

      if (isWeb) {
        // Web: use a hidden file input
        const file = await new Promise<File | null>((resolve) => {
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = '.fit,.FIT';
          input.onchange = () => resolve(input.files?.[0] ?? null);
          // Handle cancel (input won't fire change if cancelled)
          input.addEventListener('cancel', () => resolve(null));
          input.click();
        });

        if (!file) return; // User cancelled

        if (!file.name.toLowerCase().endsWith('.fit')) {
          alert('Please select a .fit file');
          return;
        }

        fileName = file.name;
        fileUri = '';  // Not used on web
        webFile = file;
      } else {
        // Native: use expo-document-picker
        const result = await DocumentPicker.getDocumentAsync({
          type: '*/*',
          copyToCacheDirectory: true,
        });

        if (result.canceled || !result.assets || result.assets.length === 0) {
          return;
        }

        const asset = result.assets[0];
        if (!asset.name.toLowerCase().endsWith('.fit')) {
          Alert.alert('Invalid File', 'Please select a .fit file');
          return;
        }

        fileName = asset.name;
        fileUri = asset.uri;
      }

      setUploading(true);

      // Upload the file
      const uploadResponse = webFile
        ? await fitApi.uploadWeb(webFile)
        : await fitApi.upload(fileUri, fileName);

      if (!uploadResponse.success) {
        if (isWeb) alert('Failed to upload the FIT file');
        else Alert.alert('Upload Failed', 'Failed to upload the FIT file');
        return;
      }

      // Get the parsed data
      const dataResponse = await fitApi.getData(uploadResponse.fileId);

      if (!dataResponse.success || !dataResponse.records) {
        const msg = dataResponse.error || 'Failed to parse the FIT file';
        if (isWeb) alert(msg);
        else Alert.alert('Parse Failed', msg);
        return;
      }

      // Set the activity data and navigate to analysis
      setCurrentActivity({
        activityName: fileName.replace('.fit', '').replace('.FIT', ''),
        records: dataResponse.records,
        summary: dataResponse.summary,
        source: 'fit',
        fitFileId: uploadResponse.fileId,
        fitMetadata: dataResponse.metadata,
      });

      router.push('/(data)/analysis');
    } catch (error: unknown) {
      console.error('FIT upload error:', error);
      const axiosError = error as { message?: string };
      const msg = axiosError.message || 'Failed to upload FIT file';
      if (isWeb) alert(msg);
      else Alert.alert('Error', msg);
    } finally {
      setUploading(false);
    }
  };

  const renderActivity = ({ item }: { item: StravaActivity }) => {
    const date = new Date(item.start_date_local);
    const dateStr = date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
    const timeStr = date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
    const distanceKm = (item.distance / 1000).toFixed(1);
    const duration = Math.floor(item.moving_time / 60);

    return (
      <TouchableOpacity style={styles.activityCard} onPress={() => selectActivity(item)}>
        <View style={styles.activityHeader}>
          <Text style={styles.activityName} numberOfLines={1}>{item.name}</Text>
          {item.max_watts && (
            <Text style={styles.activityPower}>{item.max_watts}W max</Text>
          )}
        </View>
        <View style={styles.activityDetails}>
          <Text style={styles.activityMeta}>{dateStr} at {timeStr}</Text>
          <Text style={styles.activityMeta}>{distanceKm} km  |  {duration} min</Text>
        </View>
        {item.max_watts && (
          <Text style={styles.activityMax}>Max: {item.max_watts}W</Text>
        )}
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.container}>
      {/* Server Status */}
      <TouchableOpacity
        style={styles.serverStatus}
        onPress={() => setShowApiConfig(!showApiConfig)}
      >
        <View style={[styles.statusDot, serverConnected ? styles.statusConnected : styles.statusDisconnected]} />
        <Text style={styles.serverText}>
          {serverConnected === null ? 'Checking...' : serverConnected ? 'Server Connected' : 'Server Offline'}
        </Text>
      </TouchableOpacity>

      {/* API Config (collapsible) */}
      {showApiConfig && (
        <View style={styles.apiConfig}>
          <Text style={styles.configLabel}>API Base URL:</Text>
          <TextInput
            style={styles.configInput}
            value={tempApiUrl}
            onChangeText={setTempApiUrl}
            placeholder="http://localhost:3001/api"
            autoCapitalize="none"
            autoCorrect={false}
          />
          <TouchableOpacity style={styles.saveButton} onPress={saveApiUrl}>
            <Text style={styles.saveButtonText}>Save & Test</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Strava Connect */}
      {!stravaAthlete ? (
        <View style={styles.connectSection}>
          <Text style={styles.welcomeText}>Flying 200 Analyzer</Text>
          <Text style={styles.descriptionText}>
            Connect to Strava or upload a FIT file to analyze your track cycling efforts
          </Text>
          <TouchableOpacity
            style={[styles.stravaButton, connecting && styles.buttonDisabled]}
            onPress={connectToStrava}
            disabled={connecting || !serverConnected}
          >
            {connecting ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.stravaButtonText}>Connect to Strava</Text>
            )}
          </TouchableOpacity>
          <Text style={styles.orText}>or</Text>
          <TouchableOpacity
            style={[styles.fitButton, uploading && styles.buttonDisabled]}
            onPress={uploadFitFile}
            disabled={uploading || !serverConnected}
          >
            {uploading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.fitButtonText}>Upload FIT File</Text>
            )}
          </TouchableOpacity>
          {!serverConnected && (
            <Text style={styles.warningText}>
              Connect to server first (tap status bar to configure)
            </Text>
          )}
        </View>
      ) : (
        <>
          {/* Athlete Info */}
          <View style={styles.athleteSection}>
            <View style={styles.athleteInfo}>
              <Text style={styles.athleteName}>
                {stravaAthlete.firstname} {stravaAthlete.lastname}
              </Text>
              <TouchableOpacity onPress={disconnectStrava}>
                <Text style={styles.disconnectText}>Disconnect</Text>
              </TouchableOpacity>
            </View>
            {/* FIT Upload Button */}
            <TouchableOpacity
              style={[styles.fitUploadSmall, uploading && styles.buttonDisabled]}
              onPress={uploadFitFile}
              disabled={uploading}
            >
              {uploading ? (
                <ActivityIndicator color={colors.accent} size="small" />
              ) : (
                <Text style={styles.fitUploadSmallText}>Upload FIT File</Text>
              )}
            </TouchableOpacity>
          </View>

          {/* Activities List */}
          <View style={styles.activitiesSection}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Recent Rides with Power</Text>
              <TouchableOpacity onPress={() => setShowDateFilter(!showDateFilter)}>
                <Text style={styles.filterToggle}>
                  {showDateFilter ? 'Hide Filter' : (dateAfter || dateBefore) ? 'Filtered' : 'Filter'}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Date Filter */}
            {showDateFilter && (
              <View style={styles.dateFilter}>
                <View style={styles.dateRow}>
                  <View style={styles.dateField}>
                    <Text style={styles.dateLabel}>From</Text>
                    <TextInput
                      style={styles.dateInput}
                      value={dateAfter}
                      onChangeText={setDateAfter}
                      placeholder="YYYY-MM-DD"
                      placeholderTextColor="#556b82"
                      autoCapitalize="none"
                    />
                  </View>
                  <View style={styles.dateField}>
                    <Text style={styles.dateLabel}>To</Text>
                    <TextInput
                      style={styles.dateInput}
                      value={dateBefore}
                      onChangeText={setDateBefore}
                      placeholder="YYYY-MM-DD"
                      placeholderTextColor="#556b82"
                      autoCapitalize="none"
                    />
                  </View>
                </View>
                <View style={styles.dateActions}>
                  <TouchableOpacity style={styles.dateApplyButton} onPress={applyDateFilter}>
                    <Text style={styles.dateApplyText}>Apply</Text>
                  </TouchableOpacity>
                  {(dateAfter || dateBefore) ? (
                    <TouchableOpacity style={styles.dateClearButton} onPress={clearDateFilter}>
                      <Text style={styles.dateClearText}>Clear</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              </View>
            )}

            {loading && !refreshing ? (
              <ActivityIndicator style={styles.loader} color={colors.accent} />
            ) : activities.length === 0 ? (
              <Text style={styles.emptyText}>No rides with power data found</Text>
            ) : (
              <FlatList
                data={activities}
                renderItem={renderActivity}
                keyExtractor={(item) => item.id.toString()}
                refreshControl={
                  <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
                }
                showsVerticalScrollIndicator={false}
                ListFooterComponent={
                  hasMore ? (
                    <TouchableOpacity
                      style={styles.loadMoreButton}
                      onPress={loadMore}
                      disabled={loadingMore}
                    >
                      {loadingMore ? (
                        <ActivityIndicator color={colors.accent} size="small" />
                      ) : (
                        <Text style={styles.loadMoreText}>Load More</Text>
                      )}
                    </TouchableOpacity>
                  ) : null
                }
              />
            )}
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg0,
  },
  serverStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: spacing.sm,
  },
  statusConnected: {
    backgroundColor: colors.success,
  },
  statusDisconnected: {
    backgroundColor: colors.danger,
  },
  serverText: {
    fontFamily: fonts.sans,
    color: colors.textSecondary,
    fontSize: 12,
    letterSpacing: 0.5,
  },
  apiConfig: {
    padding: spacing.lg,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  configLabel: {
    fontFamily: fonts.sansSemiBold,
    color: colors.textSecondary,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
  },
  configInput: {
    backgroundColor: colors.bg2,
    color: colors.textPrimary,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    fontFamily: fonts.mono,
    fontSize: 13,
    marginBottom: spacing.md,
  },
  saveButton: {
    backgroundColor: colors.accent,
    padding: spacing.md,
    alignItems: 'center',
  },
  saveButtonText: {
    fontFamily: fonts.sansSemiBold,
    color: colors.bg0,
    fontSize: 13,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  connectSection: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xxxl,
  },
  welcomeText: {
    fontFamily: fonts.sansBold,
    color: colors.textPrimary,
    fontSize: 26,
    letterSpacing: 2,
    textTransform: 'uppercase',
    marginBottom: spacing.md,
  },
  descriptionText: {
    fontFamily: fonts.sans,
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: spacing.xxxl,
  },
  stravaButton: {
    backgroundColor: colors.strava,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.xxxl,
    minWidth: 220,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  stravaButtonText: {
    fontFamily: fonts.sansSemiBold,
    color: colors.textPrimary,
    fontSize: 14,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  orText: {
    fontFamily: fonts.sans,
    color: colors.textMuted,
    fontSize: 12,
    marginVertical: spacing.lg,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  fitButton: {
    backgroundColor: colors.transparent,
    borderWidth: 1,
    borderColor: colors.accent,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.xxxl,
    minWidth: 220,
    alignItems: 'center',
  },
  fitButtonText: {
    fontFamily: fonts.sansSemiBold,
    color: colors.accent,
    fontSize: 14,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  warningText: {
    fontFamily: fonts.sans,
    color: colors.danger,
    fontSize: 12,
    marginTop: spacing.lg,
    textAlign: 'center',
  },
  athleteSection: {
    padding: spacing.lg,
    backgroundColor: colors.bg1,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  athleteInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  athleteName: {
    fontFamily: fonts.sansSemiBold,
    color: colors.textPrimary,
    fontSize: 16,
    letterSpacing: 0.5,
  },
  disconnectText: {
    fontFamily: fonts.sans,
    color: colors.danger,
    fontSize: 12,
  },
  fitUploadSmall: {
    marginTop: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderWidth: 1,
    borderColor: colors.borderAccent,
    alignItems: 'center',
  },
  fitUploadSmallText: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    fontSize: 12,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  activitiesSection: {
    flex: 1,
    padding: spacing.lg,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontFamily: fonts.sansSemiBold,
    color: colors.textSecondary,
    fontSize: 11,
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  filterToggle: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    fontSize: 11,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  dateFilter: {
    backgroundColor: colors.bg2,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  dateRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  dateField: {
    flex: 1,
  },
  dateLabel: {
    fontFamily: fonts.sansMedium,
    color: colors.textMuted,
    fontSize: 10,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  dateInput: {
    backgroundColor: colors.bg0,
    color: colors.textPrimary,
    padding: spacing.sm,
    fontFamily: fonts.mono,
    fontSize: 13,
    borderWidth: 1,
    borderColor: colors.border,
  },
  dateActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  dateApplyButton: {
    backgroundColor: colors.accent,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xl,
  },
  dateApplyText: {
    fontFamily: fonts.sansSemiBold,
    color: colors.bg0,
    fontSize: 12,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  dateClearButton: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xl,
    borderWidth: 1,
    borderColor: colors.borderAccent,
  },
  dateClearText: {
    fontFamily: fonts.sans,
    color: colors.textSecondary,
    fontSize: 12,
  },
  loadMoreButton: {
    paddingVertical: spacing.lg,
    alignItems: 'center',
    marginBottom: spacing.xl,
    borderWidth: 1,
    borderColor: colors.border,
  },
  loadMoreText: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    fontSize: 12,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  loader: {
    marginTop: 40,
  },
  emptyText: {
    fontFamily: fonts.sans,
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: 'center',
    marginTop: 40,
  },
  activityCard: {
    backgroundColor: colors.bg1,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderLeftWidth: 2,
    borderLeftColor: colors.borderAccent,
    marginBottom: spacing.sm,
  },
  activityHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  activityName: {
    fontFamily: fonts.sansSemiBold,
    color: colors.textPrimary,
    fontSize: 15,
    flex: 1,
    marginRight: spacing.sm,
  },
  activityPower: {
    fontFamily: fonts.mono,
    color: colors.accent,
    fontSize: 14,
  },
  activityDetails: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  activityMeta: {
    fontFamily: fonts.sans,
    color: colors.textSecondary,
    fontSize: 12,
  },
  activityMax: {
    fontFamily: fonts.mono,
    color: colors.warning,
    fontSize: 11,
    marginTop: spacing.xs,
  },
});

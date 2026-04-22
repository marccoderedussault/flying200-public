import { colors } from './theme';
import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { View, Text, StyleSheet, Dimensions, ActivityIndicator } from 'react-native';
import Svg, { Path, Circle, Line, G, Polygon } from 'react-native-svg';
import { getTrackGeometry, TrackGeometry } from '../api/trackApi';

// Lap colors and labels (boundaries computed dynamically from geometry)
const LAP_COLORS = [
  { id: 0, name: 'Lap 0', color: '#1f77b4' },
  { id: 1, name: 'Lap 1', color: '#2ca02c' },
  { id: 2, name: 'Lap 2', color: '#ff7f0e' },
  { id: 3, name: 'Timed', color: '#d62728' },
];

// Fallback static definitions (used before geometry loads)
const DEFAULT_LAP_DEFINITIONS = [
  { id: 0, name: 'Lap 0', color: '#1f77b4', startS: 0, endS: 134 },
  { id: 1, name: 'Lap 1', color: '#2ca02c', startS: 135, endS: 384 },
  { id: 2, name: 'Lap 2', color: '#ff7f0e', startS: 385, endS: 694 },
  { id: 3, name: 'Timed', color: '#d62728', startS: 695, endS: 895 },
];

interface TrackProfilePoint {
  s_m: number;
  y_m: number;
  CdA_m2: number;
  P_W: number;
}

interface TrackVisualProps {
  trackProfile?: TrackProfilePoint[];
  showLap0?: boolean;
  showLap1?: boolean;
  showLap2?: boolean;
  showTimed?: boolean;
  width?: number;
  height?: number;
  trackName?: string;
}

export default function TrackVisual({
  trackProfile,
  showLap0 = true,
  showLap1 = true,
  showLap2 = true,
  showTimed = true,
  width: propWidth,
  height: propHeight,
  trackName = 'Bromont',
}: TrackVisualProps) {
  const [geometry, setGeometry] = useState<TrackGeometry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Screen dimensions - minimal padding for maximum track size
  const screenWidth = Dimensions.get('window').width;
  const width = propWidth ?? screenWidth - 16;
  const height = propHeight ?? 280;
  const padding = 8; // Reduced padding for bigger track

  useEffect(() => {
    loadGeometry(trackName);
  }, [trackName]);

  const loadGeometry = async (track: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTrackGeometry(track);
      setGeometry(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load track geometry');
    } finally {
      setLoading(false);
    }
  };

  // Transform track coordinates to SVG coordinates
  const getTransform = useCallback(() => {
    if (!geometry) return null;

    const { black_line, config } = geometry.track;

    // Calculate bounds including outer edge - tighter margins
    const allX = black_line.x;
    const allY = black_line.y;
    const minX = Math.min(...allX) - config.W - 1;
    const maxX = Math.max(...allX) + config.W + 1;
    const minY = Math.min(...allY) - config.W - 1;
    const maxY = Math.max(...allY) + config.W + 1;

    const dataWidth = maxX - minX;
    const dataHeight = maxY - minY;

    const scaleX = (width - 2 * padding) / dataWidth;
    const scaleY = (height - 2 * padding) / dataHeight;
    const scale = Math.min(scaleX, scaleY);

    const offsetX = padding + (width - 2 * padding - dataWidth * scale) / 2;
    const offsetY = padding + (height - 2 * padding - dataHeight * scale) / 2;

    return { scale, offsetX, offsetY, minX, minY };
  }, [geometry, width, height, padding]);

  // Convert track coords to SVG coords
  const toSvg = useCallback((x: number, y: number): [number, number] => {
    const transform = getTransform();
    if (!transform) return [0, 0];

    const { scale, offsetX, offsetY, minX, minY } = transform;
    const svgX = offsetX + (x - minX) * scale;
    const svgY = height - (offsetY + (y - minY) * scale); // Flip Y
    return [svgX, svgY];
  }, [getTransform, height]);

  // Convert track distance (s_m) and lateral offset (y_m) to SVG coordinates.
  // Uses the same linear mapping as Python track_model and web TrackViewPage:
  //   idx = (distance / 250) * (totalPoints - 1)
  // This is consistent with how finish.idx, pursuit lines, and the 200m start
  // position are all computed in the backend.
  const sToSvg = useCallback((s_m: number, y_m: number): [number, number] | null => {
    if (!geometry) return null;

    const { black_line, normals, finish } = geometry.track;
    const totalPoints = black_line.x.length;
    const lapLen = 250.0;
    const profileFinish = 895.0;

    // Convert finish index to distance using the same linear formula as Python
    const finishDistance = (finish.idx / (totalPoints - 1)) * lapLen;

    // Profile s_m=895 = finish line, compute track distance
    const trackDist = ((finishDistance + (s_m - profileFinish)) % lapLen + lapLen) % lapLen;

    // Convert distance to index using same linear mapping
    const idx = Math.max(0, Math.min(totalPoints - 1,
      Math.floor((trackDist / lapLen) * (totalPoints - 1))));

    // Offset from black line by lateral position
    const x_track = black_line.x[idx] + normals.nx[idx] * y_m;
    const y_track = black_line.y[idx] + normals.ny[idx] * y_m;

    return toSvg(x_track, y_track);
  }, [geometry, toSvg]);

  // Compute lap definitions dynamically from track geometry.
  // L0 ends at the first bottom pursuit line crossing after s_m=0.
  // L1 is the next full lap (250m). L2 goes to the 200m start. Timed is last 200m.
  const lapDefinitions = useMemo(() => {
    if (!geometry) return DEFAULT_LAP_DEFINITIONS;

    const { black_line, finish, pursuit_lines } = geometry.track;
    const totalPoints = black_line.x.length;
    const lapLen = 250.0;
    const profileFinish = 895.0;
    const timedStart = profileFinish - 200; // 695

    const pursuitDist = pursuit_lines?.bottom?.distance_m;
    if (pursuitDist == null) return DEFAULT_LAP_DEFINITIONS;

    const finishDistance = (finish.idx / (totalPoints - 1)) * lapLen;

    // Find s_m where rider crosses the bottom pursuit line.
    // trackDist = (finishDistance + (s_m - profileFinish)) % lapLen = pursuitDist
    // => s_m = profileFinish + pursuitDist - finishDistance + 250*k
    const s_base = profileFinish + pursuitDist - finishDistance;
    // Find the first crossing > 0
    let firstCrossing = s_base % lapLen;
    if (firstCrossing <= 0) firstCrossing += lapLen;

    const l0End = Math.round(firstCrossing);
    const l1End = Math.round(firstCrossing + lapLen);

    return [
      { id: 0, name: 'Lap 0', color: '#1f77b4', startS: 0, endS: l0End - 1 },
      { id: 1, name: 'Lap 1', color: '#2ca02c', startS: l0End, endS: l1End - 1 },
      { id: 2, name: 'Lap 2', color: '#ff7f0e', startS: l1End, endS: timedStart - 1 },
      { id: 3, name: 'Timed', color: '#d62728', startS: timedStart, endS: profileFinish },
    ];
  }, [geometry]);

  // Generate path for track area (outer edge to black line)
  const getTrackSurfacePath = useCallback((): string => {
    if (!geometry) return '';

    const { black_line, normals, config } = geometry.track;
    const points: [number, number][] = [];

    // Black line points
    for (let i = 0; i < black_line.x.length; i += 5) {
      points.push(toSvg(black_line.x[i], black_line.y[i]));
    }

    // Outer edge points (going backwards)
    const outerPoints: [number, number][] = [];
    for (let i = black_line.x.length - 1; i >= 0; i -= 5) {
      const outerX = black_line.x[i] + normals.nx[i] * config.W;
      const outerY = black_line.y[i] + normals.ny[i] * config.W;
      outerPoints.push(toSvg(outerX, outerY));
    }

    const allPoints = [...points, ...outerPoints];
    if (allPoints.length === 0) return '';

    let path = `M ${allPoints[0][0]} ${allPoints[0][1]}`;
    for (let i = 1; i < allPoints.length; i++) {
      path += ` L ${allPoints[i][0]} ${allPoints[i][1]}`;
    }
    path += ' Z';
    return path;
  }, [geometry, toSvg]);

  // Generate path for Cote d'Azur (inner edge to black line)
  const getCoteAzurPath = useCallback((): string => {
    if (!geometry) return '';

    const { black_line, inner_edge } = geometry.track;
    const points: [number, number][] = [];

    // Inner edge points
    for (let i = 0; i < inner_edge.x.length; i += 5) {
      points.push(toSvg(inner_edge.x[i], inner_edge.y[i]));
    }

    // Black line points (going backwards)
    const blackPoints: [number, number][] = [];
    for (let i = black_line.x.length - 1; i >= 0; i -= 5) {
      blackPoints.push(toSvg(black_line.x[i], black_line.y[i]));
    }

    const allPoints = [...points, ...blackPoints];
    if (allPoints.length === 0) return '';

    let path = `M ${allPoints[0][0]} ${allPoints[0][1]}`;
    for (let i = 1; i < allPoints.length; i++) {
      path += ` L ${allPoints[i][0]} ${allPoints[i][1]}`;
    }
    path += ' Z';
    return path;
  }, [geometry, toSvg]);

  // Generate line path
  const getLinePath = useCallback((xArr: number[], yArr: number[], step = 3): string => {
    const points: [number, number][] = [];
    for (let i = 0; i < xArr.length; i += step) {
      points.push(toSvg(xArr[i], yArr[i]));
    }
    if (points.length === 0) return '';

    let path = `M ${points[0][0]} ${points[0][1]}`;
    for (let i = 1; i < points.length; i++) {
      path += ` L ${points[i][0]} ${points[i][1]}`;
    }
    return path;
  }, [toSvg]);

  // Get lap visibility
  const isLapVisible = useCallback((lapId: number): boolean => {
    switch (lapId) {
      case 0: return showLap0;
      case 1: return showLap1;
      case 2: return showLap2;
      case 3: return showTimed;
      default: return true;
    }
  }, [showLap0, showLap1, showLap2, showTimed]);

  // Get lap for distance (uses dynamic lap boundaries)
  const getLapForDistance = useCallback((s_m: number): number => {
    for (const lap of lapDefinitions) {
      if (s_m >= lap.startS && s_m <= lap.endS) {
        return lap.id;
      }
    }
    return 3;
  }, [lapDefinitions]);

  // Generate trajectory paths grouped by lap (for different colors)
  const getTrajectoryPathsByLap = useCallback((points: TrackProfilePoint[]): Map<number, string> => {
    const lapPaths = new Map<number, string>();
    if (points.length === 0) return lapPaths;

    // Group consecutive points by lap
    let currentLap = -1;
    let currentPoints: [number, number][] = [];

    for (const point of points) {
      const lap = getLapForDistance(point.s_m);
      if (!isLapVisible(lap)) continue;

      const coords = sToSvg(point.s_m, point.y_m);
      if (!coords) continue;

      if (lap !== currentLap) {
        // Save previous lap's path
        if (currentPoints.length > 0 && currentLap >= 0) {
          let path = `M ${currentPoints[0][0]} ${currentPoints[0][1]}`;
          for (let i = 1; i < currentPoints.length; i++) {
            path += ` L ${currentPoints[i][0]} ${currentPoints[i][1]}`;
          }
          lapPaths.set(currentLap, path);
        }
        // Start new lap, include last point of previous for continuity
        currentLap = lap;
        currentPoints = currentPoints.length > 0 ? [currentPoints[currentPoints.length - 1]] : [];
      }
      currentPoints.push(coords);
    }

    // Save last lap's path
    if (currentPoints.length > 0 && currentLap >= 0) {
      let path = `M ${currentPoints[0][0]} ${currentPoints[0][1]}`;
      for (let i = 1; i < currentPoints.length; i++) {
        path += ` L ${currentPoints[i][0]} ${currentPoints[i][1]}`;
      }
      lapPaths.set(currentLap, path);
    }

    return lapPaths;
  }, [sToSvg, isLapVisible, getLapForDistance]);

  // Get trajectory start and end positions for markers
  const getTrajectoryEndpoints = useCallback(() => {
    if (!trackProfile || trackProfile.length === 0) return null;

    // Find first visible point (start)
    let startPoint: TrackProfilePoint | null = null;
    for (const point of trackProfile) {
      const lap = getLapForDistance(point.s_m);
      if (isLapVisible(lap)) {
        startPoint = point;
        break;
      }
    }

    // Find last visible point (end)
    let endPoint: TrackProfilePoint | null = null;
    for (let i = trackProfile.length - 1; i >= 0; i--) {
      const lap = getLapForDistance(trackProfile[i].s_m);
      if (isLapVisible(lap)) {
        endPoint = trackProfile[i];
        break;
      }
    }

    if (!startPoint || !endPoint) return null;

    const startCoords = sToSvg(startPoint.s_m, startPoint.y_m);
    const endCoords = sToSvg(endPoint.s_m, endPoint.y_m);

    // Get direction for arrow at end (from second-to-last to last point)
    let arrowAngle = 0;
    if (trackProfile.length >= 2) {
      const prevIdx = Math.max(0, trackProfile.length - 5);
      const prevCoords = sToSvg(trackProfile[prevIdx].s_m, trackProfile[prevIdx].y_m);
      if (prevCoords && endCoords) {
        arrowAngle = Math.atan2(endCoords[1] - prevCoords[1], endCoords[0] - prevCoords[0]) * 180 / Math.PI;
      }
    }

    return { startCoords, endCoords, arrowAngle };
  }, [trackProfile, sToSvg, isLapVisible, getLapForDistance]);

  if (loading) {
    return (
      <View style={[styles.container, { width, height }]}>
        <ActivityIndicator size="large" color="#4da6ff" />
        <Text style={styles.loadingText}>Loading track...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={[styles.container, { width, height }]}>
        <Text style={styles.errorText}>{error}</Text>
      </View>
    );
  }

  if (!geometry) {
    return null;
  }

  const { black_line, inner_edge, normals, config, start, finish, pursuit_lines } = geometry.track;

  // Calculate line positions
  const redX = black_line.x.map((x, i) => x + normals.nx[i] * config.RED_LINE_POSITION);
  const redY = black_line.y.map((y, i) => y + normals.ny[i] * config.RED_LINE_POSITION);
  const blueX = black_line.x.map((x, i) => x + normals.nx[i] * config.BLUE_LINE_POSITION);
  const blueY = black_line.y.map((y, i) => y + normals.ny[i] * config.BLUE_LINE_POSITION);
  const outerX = black_line.x.map((x, i) => x + normals.nx[i] * config.W);
  const outerY = black_line.y.map((y, i) => y + normals.ny[i] * config.W);

  // Start/finish line positions
  const [startX, startY] = toSvg(start.x, start.y);
  const startInner = toSvg(
    start.x - start.nx * config.BLACK_LINE_POSITION,
    start.y - start.ny * config.BLACK_LINE_POSITION
  );
  const startOuter = toSvg(
    start.x + start.nx * config.W,
    start.y + start.ny * config.W
  );

  const finishIdx = finish.idx;
  const [finishX, finishY] = toSvg(black_line.x[finishIdx], black_line.y[finishIdx]);
  const finishInner = toSvg(
    black_line.x[finishIdx] - normals.nx[finishIdx] * config.BLACK_LINE_POSITION,
    black_line.y[finishIdx] - normals.ny[finishIdx] * config.BLACK_LINE_POSITION
  );
  const finishOuter = toSvg(
    black_line.x[finishIdx] + normals.nx[finishIdx] * config.W,
    black_line.y[finishIdx] + normals.ny[finishIdx] * config.W
  );

  // Trajectory endpoints
  const trajectoryEndpoints = getTrajectoryEndpoints();

  return (
    <View style={[styles.container, { width, height }]}>
      <Svg width={width} height={height}>
        {/* Track surface (bisque) */}
        <Path d={getTrackSurfacePath()} fill="#ffe4c4" fillOpacity={0.8} />

        {/* Cote d'Azur (light blue) */}
        <Path d={getCoteAzurPath()} fill="#add8e6" fillOpacity={0.8} />

        {/* Infield */}
        <Path
          d={getLinePath(inner_edge.x, inner_edge.y) + ' Z'}
          fill="#add8e6"
          fillOpacity={0.3}
        />

        {/* Inner edge (dashed blue) */}
        <Path
          d={getLinePath(inner_edge.x, inner_edge.y)}
          stroke="#0000ff"
          strokeWidth={1}
          strokeDasharray="4,4"
          fill="none"
          strokeOpacity={0.7}
        />

        {/* Black line */}
        <Path
          d={getLinePath(black_line.x, black_line.y)}
          stroke="#000000"
          strokeWidth={2}
          fill="none"
        />

        {/* Red line */}
        <Path
          d={getLinePath(redX, redY)}
          stroke="#ff0000"
          strokeWidth={1.5}
          fill="none"
        />

        {/* Blue line */}
        <Path
          d={getLinePath(blueX, blueY)}
          stroke="#0000ff"
          strokeWidth={1.5}
          fill="none"
        />

        {/* Outer edge */}
        <Path
          d={getLinePath(outerX, outerY)}
          stroke="#000000"
          strokeWidth={2}
          fill="none"
        />

        {/* Start line (dashed) */}
        <Line
          x1={startInner[0]}
          y1={startInner[1]}
          x2={startOuter[0]}
          y2={startOuter[1]}
          stroke="#000000"
          strokeWidth={2}
          strokeDasharray="4,4"
        />

        {/* Finish line */}
        <Line
          x1={finishInner[0]}
          y1={finishInner[1]}
          x2={finishOuter[0]}
          y2={finishOuter[1]}
          stroke="#000000"
          strokeWidth={2}
        />

        {/* Pursuit lines */}
        {pursuit_lines.top && (() => {
          const topIdx = Math.floor((pursuit_lines.top.distance_m / 250) * black_line.x.length);
          const topInner = toSvg(
            black_line.x[topIdx] - normals.nx[topIdx] * config.BLACK_LINE_POSITION,
            black_line.y[topIdx] - normals.ny[topIdx] * config.BLACK_LINE_POSITION
          );
          const topOuter = toSvg(
            black_line.x[topIdx] + normals.nx[topIdx] * config.W,
            black_line.y[topIdx] + normals.ny[topIdx] * config.W
          );
          return (
            <Line
              x1={topInner[0]}
              y1={topInner[1]}
              x2={topOuter[0]}
              y2={topOuter[1]}
              stroke="#ff0000"
              strokeWidth={3}
              strokeOpacity={0.9}
            />
          );
        })()}

        {pursuit_lines.bottom && (() => {
          const bottomIdx = Math.floor((pursuit_lines.bottom.distance_m / 250) * black_line.x.length);
          const bottomInner = toSvg(
            black_line.x[bottomIdx] - normals.nx[bottomIdx] * config.BLACK_LINE_POSITION,
            black_line.y[bottomIdx] - normals.ny[bottomIdx] * config.BLACK_LINE_POSITION
          );
          const bottomOuter = toSvg(
            black_line.x[bottomIdx] + normals.nx[bottomIdx] * config.W,
            black_line.y[bottomIdx] + normals.ny[bottomIdx] * config.W
          );
          return (
            <Line
              x1={bottomInner[0]}
              y1={bottomInner[1]}
              x2={bottomOuter[0]}
              y2={bottomOuter[1]}
              stroke="#ff0000"
              strokeWidth={3}
              strokeOpacity={0.9}
            />
          );
        })()}

        {/* Trajectory lines - colored by lap section */}
        {trackProfile && trackProfile.length > 0 && (() => {
          const lapPaths = getTrajectoryPathsByLap(trackProfile);
          return Array.from(lapPaths.entries()).map(([lapId, path]) => {
            const lapDef = LAP_COLORS.find(l => l.id === lapId);
            const color = lapDef?.color ?? '#22c55e';
            return (
              <Path
                key={`traj-lap-${lapId}`}
                d={path}
                stroke={color}
                strokeWidth={3}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          });
        })()}

        {/* Trajectory start marker (X) - use first lap color */}
        {trajectoryEndpoints?.startCoords && trackProfile && (() => {
          const startLap = getLapForDistance(trackProfile[0]?.s_m ?? 0);
          const lapDef = LAP_COLORS.find(l => l.id === startLap);
          const color = lapDef?.color ?? '#1f77b4';
          return (
            <G>
              <Line
                x1={trajectoryEndpoints.startCoords[0] - 6}
                y1={trajectoryEndpoints.startCoords[1] - 6}
                x2={trajectoryEndpoints.startCoords[0] + 6}
                y2={trajectoryEndpoints.startCoords[1] + 6}
                stroke={color}
                strokeWidth={3}
                strokeLinecap="round"
              />
              <Line
                x1={trajectoryEndpoints.startCoords[0] + 6}
                y1={trajectoryEndpoints.startCoords[1] - 6}
                x2={trajectoryEndpoints.startCoords[0] - 6}
                y2={trajectoryEndpoints.startCoords[1] + 6}
                stroke={color}
                strokeWidth={3}
                strokeLinecap="round"
              />
            </G>
          );
        })()}

        {/* Trajectory end marker (arrow) - use last lap color */}
        {trajectoryEndpoints?.endCoords && trackProfile && (() => {
          const endLap = getLapForDistance(trackProfile[trackProfile.length - 1]?.s_m ?? 895);
          const lapDef = LAP_COLORS.find(l => l.id === endLap);
          const color = lapDef?.color ?? '#d62728';
          return (
            <G
              transform={`translate(${trajectoryEndpoints.endCoords[0]}, ${trajectoryEndpoints.endCoords[1]}) rotate(${trajectoryEndpoints.arrowAngle})`}
            >
              <Polygon
                points="-8,-5 0,0 -8,5"
                fill={color}
                stroke={color}
                strokeWidth={1}
              />
            </G>
          );
        })()}

        {/* Start marker (blue) - 200m start */}
        <Circle
          cx={startX}
          cy={startY}
          r={5}
          fill="#3b82f6"
          stroke="#fff"
          strokeWidth={1.5}
        />

        {/* Finish marker (red) */}
        <Circle
          cx={finishX}
          cy={finishY}
          r={5}
          fill="#ef4444"
          stroke="#fff"
          strokeWidth={1.5}
        />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    overflow: 'hidden',
  },
  loadingText: {
    marginTop: 8,
    color: '#6b7280',
    fontSize: 14,
  },
  errorText: {
    color: '#ef4444',
    fontSize: 14,
    textAlign: 'center',
    paddingHorizontal: 16,
  },
});

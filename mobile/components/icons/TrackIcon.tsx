import React from 'react';
import Svg, { Ellipse, Circle } from 'react-native-svg';

interface Props {
  size?: number;
  color?: string;
}

export const TrackIcon: React.FC<Props> = ({ size = 24, color = '#7A8BA0' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    {/* Velodrome oval */}
    <Ellipse
      cx={12}
      cy={12}
      rx={10}
      ry={7}
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    {/* Start/finish dot */}
    <Circle
      cx={12}
      cy={5}
      r={1.5}
      fill={color}
      stroke={color}
      strokeWidth={1.5}
    />
  </Svg>
);

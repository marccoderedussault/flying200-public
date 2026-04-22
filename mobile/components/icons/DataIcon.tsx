import React from 'react';
import Svg, { Polyline, Circle } from 'react-native-svg';

interface Props {
  size?: number;
  color?: string;
}

export const DataIcon: React.FC<Props> = ({ size = 24, color = '#7A8BA0' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <Polyline
      points="2,17 6,9 10,13 14,5 18,11 22,7"
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <Circle
      cx={22}
      cy={7}
      r={2}
      fill={color}
      stroke={color}
      strokeWidth={1.5}
    />
  </Svg>
);

import React from 'react';
import Svg, { Circle, Line, Polygon } from 'react-native-svg';

interface Props {
  size?: number;
  color?: string;
}

export const SimulateIcon: React.FC<Props> = ({ size = 24, color = '#7A8BA0' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    {/* Gear body */}
    <Circle
      cx={12}
      cy={12}
      r={9}
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    {/* Gear notch at 0° (right) */}
    <Line x1={21} y1={12} x2={23} y2={12} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Gear notch at 90° (bottom) */}
    <Line x1={12} y1={21} x2={12} y2={23} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Gear notch at 180° (left) */}
    <Line x1={3} y1={12} x2={1} y2={12} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Gear notch at 270° (top) */}
    <Line x1={12} y1={3} x2={12} y2={1} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Play triangle */}
    <Polygon
      points="10,8 16,12 10,16"
      fill={color}
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

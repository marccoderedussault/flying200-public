import React from 'react';
import Svg, { Line, Circle } from 'react-native-svg';

interface Props {
  size?: number;
  color?: string;
}

export const SettingsIcon: React.FC<Props> = ({ size = 24, color = '#7A8BA0' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    {/* Top fader line */}
    <Line x1={3} y1={6} x2={21} y2={6} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Middle fader line */}
    <Line x1={3} y1={12} x2={21} y2={12} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Bottom fader line */}
    <Line x1={3} y1={18} x2={21} y2={18} stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    {/* Top knob */}
    <Circle cx={8} cy={6} r={2} fill={color} stroke={color} strokeWidth={1.5} />
    {/* Middle knob */}
    <Circle cx={16} cy={12} r={2} fill={color} stroke={color} strokeWidth={1.5} />
    {/* Bottom knob */}
    <Circle cx={10} cy={18} r={2} fill={color} stroke={color} strokeWidth={1.5} />
  </Svg>
);

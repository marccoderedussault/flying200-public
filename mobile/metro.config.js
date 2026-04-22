// Learn more https://docs.expo.io/guides/customizing-metro
const { getDefaultConfig } = require('expo/metro-config');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

// Force Metro to resolve the CJS (react-native) exports instead of ESM (.mjs)
// on web. Zustand's ESM build uses import.meta.env which Metro doesn't support.
config.resolver.unstable_conditionNames = [
  'react-native',
  'browser',
  'require',
];

module.exports = config;

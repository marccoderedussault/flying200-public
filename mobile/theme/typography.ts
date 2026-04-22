export const fonts = {
  mono: 'JetBrainsMono_400Regular',
  monoMedium: 'JetBrainsMono_500Medium',
  monoBold: 'JetBrainsMono_700Bold',
  sans: 'Barlow_400Regular',
  sansMedium: 'Barlow_500Medium',
  sansSemiBold: 'Barlow_600SemiBold',
  sansBold: 'Barlow_700Bold',
} as const;

export const typography = {
  screenTitle: {
    fontFamily: fonts.sansSemiBold,
    fontSize: 20,
    letterSpacing: 1.5,
    textTransform: 'uppercase' as const,
  },
  sectionHeader: {
    fontFamily: fonts.sansSemiBold,
    fontSize: 14,
    letterSpacing: 1,
    textTransform: 'uppercase' as const,
  },
  body: {
    fontFamily: fonts.sans,
    fontSize: 13,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: 12,
  },
  keyNumber: {
    fontFamily: fonts.monoMedium,
    fontSize: 32,
  },
  dataValue: {
    fontFamily: fonts.mono,
    fontSize: 15,
  },
  dataValueSmall: {
    fontFamily: fonts.mono,
    fontSize: 13,
  },
  unit: {
    fontFamily: fonts.sans,
    fontSize: 11,
  },
  tabLabel: {
    fontFamily: fonts.sansMedium,
    fontSize: 10,
  },
  buttonLabel: {
    fontFamily: fonts.sansSemiBold,
    fontSize: 13,
    letterSpacing: 0.5,
    textTransform: 'uppercase' as const,
  },
} as const;

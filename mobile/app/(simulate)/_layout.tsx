import { Stack, useRouter } from 'expo-router';
import { TouchableOpacity } from 'react-native';
import { colors } from '../../theme';
import { fonts } from '../../theme/typography';
import { Svg, Path } from 'react-native-svg';

function BackArrow({ color }: { color: string }) {
  return (
    <Svg width={22} height={22} viewBox="0 0 24 24" fill="none">
      <Path d="M15 18l-6-6 6-6" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

export default function SimulateLayout() {
  const router = useRouter();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.bg1 },
        headerTintColor: colors.textPrimary,
        headerTitleStyle: { fontFamily: fonts.sansSemiBold, letterSpacing: 1 },
        contentStyle: { backgroundColor: colors.bg0 },
        animation: 'slide_from_right',
      }}
    >
      <Stack.Screen
        name="index"
        options={{
          title: 'Simulation',
          headerLeft: () => (
            <TouchableOpacity onPress={() => router.back()} style={{ marginRight: 8 }}>
              <BackArrow color={colors.textPrimary} />
            </TouchableOpacity>
          ),
        }}
      />
      <Stack.Screen name="sensitivity" options={{ title: 'Sensitivity' }} />
      <Stack.Screen name="optimizer" options={{ title: 'Optimizer' }} />
    </Stack>
  );
}

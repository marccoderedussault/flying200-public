import { Tabs } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Platform } from 'react-native';
import { useFonts } from 'expo-font';
import {
  JetBrainsMono_400Regular,
  JetBrainsMono_500Medium,
  JetBrainsMono_700Bold,
} from '@expo-google-fonts/jetbrains-mono';
import {
  Barlow_400Regular,
  Barlow_500Medium,
  Barlow_600SemiBold,
  Barlow_700Bold,
} from '@expo-google-fonts/barlow';
import { colors } from '../theme';
import { fonts } from '../theme/typography';
import { DataIcon, SimulateIcon, TrackIcon, SettingsIcon } from '../components/icons';

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium,
    JetBrainsMono_700Bold,
    Barlow_400Regular,
    Barlow_500Medium,
    Barlow_600SemiBold,
    Barlow_700Bold,
  });

  if (!fontsLoaded) {
    return null;
  }

  return (
    <>
      <StatusBar style="light" />
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            backgroundColor: colors.bg1,
            borderTopWidth: 1,
            borderTopColor: colors.border,
            height: Platform.OS === 'ios' ? 85 : 65,
            paddingBottom: Platform.OS === 'ios' ? 25 : 10,
            paddingTop: 8,
          },
          tabBarActiveTintColor: colors.accent,
          tabBarInactiveTintColor: colors.textSecondary,
          tabBarLabelStyle: {
            fontFamily: fonts.sansMedium,
            fontSize: 10,
            marginTop: 2,
          },
        }}
      >
        <Tabs.Screen
          name="(data)"
          options={{
            title: 'Data',
            tabBarIcon: ({ color }) => <DataIcon color={color} size={22} />,
          }}
        />
        <Tabs.Screen
          name="(simulate)"
          options={{
            title: 'Simulate',
            tabBarIcon: ({ color }) => <SimulateIcon color={color} size={22} />,
          }}
        />
        <Tabs.Screen
          name="(track)"
          options={{
            title: 'Track',
            tabBarIcon: ({ color }) => <TrackIcon color={color} size={22} />,
          }}
        />
        <Tabs.Screen
          name="(settings)"
          options={{
            title: 'Settings',
            tabBarIcon: ({ color }) => <SettingsIcon color={color} size={22} />,
          }}
        />
      </Tabs>
    </>
  );
}

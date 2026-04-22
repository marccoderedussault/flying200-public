import React, { useEffect, useRef } from 'react';
import {
  View,
  Text,
  Image,
  StyleSheet,
  TouchableOpacity,
  Modal,
  Animated,
  Dimensions,
  Pressable,
} from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import type { ImageSourcePropType } from 'react-native';

interface MenuItem {
  name: string;
  label: string;
  path: string;
  icon?: string;
  iconImage?: ImageSourcePropType;
}

const MENU_ITEMS: MenuItem[] = [
  // Row 1
  { name: 'inputs', label: 'Settings', path: '/inputs', iconImage: require('../assets/settingscog.png') },
  { name: 'kit', label: 'Kit', path: '/kit', iconImage: require('../assets/trackbikeNoframe.png') },
  { name: 'home', label: 'Connect Data', path: '/', iconImage: require('../assets/plug.png') },
  // Row 2
  { name: 'analysis', label: 'Efforts', path: '/analysis', iconImage: require('../assets/magglass.png') },
  { name: 'simulation', label: 'Simulate', path: '/simulation', iconImage: require('../assets/chain.png') },
  { name: 'optimizer', label: 'Optimizer', path: '/optimizer', iconImage: require('../assets/opti2.png') },
  // Row 3
  { name: 'sensitivity', label: 'Sensitivity', path: '/sensitivity', iconImage: require('../assets/gauge.png') },
  { name: 'track', label: 'Track View', path: '/track', iconImage: require('../assets/trackicon.png') },
];

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');
const PANEL_MARGIN = 16;
const PANEL_WIDTH = SCREEN_WIDTH - PANEL_MARGIN * 2;
const GRID_COLUMNS = 3;
const GRID_GAP = 8;
const GRID_PADDING = 10;
const TILE_SIZE = (PANEL_WIDTH - GRID_PADDING * 2 - GRID_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS;

interface HamburgerMenuProps {
  visible: boolean;
  onClose: () => void;
}

export default function HamburgerMenu({ visible, onClose }: HamburgerMenuProps) {
  const router = useRouter();
  const pathname = usePathname();
  const scaleAnim = useRef(new Animated.Value(0.9)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (visible) {
      Animated.parallel([
        Animated.spring(scaleAnim, {
          toValue: 1,
          tension: 65,
          friction: 9,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      Animated.parallel([
        Animated.timing(scaleAnim, {
          toValue: 0.9,
          duration: 150,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 0,
          duration: 150,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [visible]);

  const handleNavigate = (path: string) => {
    onClose();
    setTimeout(() => {
      router.push(path as never);
    }, 100);
  };

  const isActive = (path: string) => {
    if (path === '/') {
      return pathname === '/' || pathname === '/index';
    }
    return pathname === path || pathname.startsWith(path + '/');
  };

  if (!visible) return null;

  return (
    <Modal
      transparent
      visible={visible}
      animationType="none"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <View style={styles.container}>
        {/* Backdrop */}
        <Animated.View style={[styles.backdrop, { opacity: fadeAnim }]}>
          <Pressable style={styles.backdropPressable} onPress={onClose} />
        </Animated.View>

        {/* Menu Panel */}
        <Animated.View
          style={[
            styles.menuPanel,
            {
              opacity: fadeAnim,
              transform: [{ scale: scaleAnim }],
            },
          ]}
        >
          {/* Header */}
          <View style={styles.menuHeader}>
            <View>
              <Text style={styles.menuTitle}>Flying 200</Text>
              <Text style={styles.menuSubtitle}>Track Sprint Analyzer</Text>
            </View>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Text style={styles.closeButtonText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Grid */}
          <View style={styles.grid}>
            {MENU_ITEMS.map((item) => {
              const active = isActive(item.path);
              return (
                <TouchableOpacity
                  key={item.name}
                  style={[styles.tile, active && styles.tileActive]}
                  onPress={() => handleNavigate(item.path)}
                  activeOpacity={0.7}
                >
                  {item.iconImage ? (
                    <Image source={item.iconImage} style={styles.tileIconImage} />
                  ) : (
                    <Text style={styles.tileIcon}>{item.icon}</Text>
                  )}
                  <View style={styles.tileLabelOverlay}>
                    <Text
                      style={[styles.tileLabel, active && styles.tileLabelActive]}
                      numberOfLines={1}
                    >
                      {item.label}
                    </Text>
                  </View>
                  {active && <View style={styles.tileActiveBar} />}
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Footer */}
          <View style={styles.menuFooter}>
            <Text style={styles.footerText}>Version 1.0.0</Text>
          </View>
        </Animated.View>
      </View>
    </Modal>
  );
}

// Hamburger icon button component for the header
export function HamburgerButton({ onPress }: { onPress: () => void }) {
  return (
    <TouchableOpacity
      style={styles.hamburgerButton}
      onPress={onPress}
      activeOpacity={0.7}
      hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
    >
      <View style={styles.hamburgerLine} />
      <View style={styles.hamburgerLine} />
      <View style={styles.hamburgerLine} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
  },
  backdropPressable: {
    flex: 1,
  },
  menuPanel: {
    position: 'absolute',
    width: PANEL_WIDTH,
    maxHeight: SCREEN_HEIGHT * 0.75,
    backgroundColor: '#1a2f47',
    borderRadius: 20,
    paddingTop: 20,
    paddingBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.4,
    shadowRadius: 24,
    elevation: 30,
  },
  menuHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#2d4a6f',
  },
  menuTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  menuSubtitle: {
    fontSize: 13,
    color: '#8aa4c0',
    marginTop: 2,
  },
  closeButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#0f1f33',
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    color: '#8aa4c0',
    fontSize: 16,
    fontWeight: '600',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    padding: GRID_PADDING,
    gap: GRID_GAP,
  },
  tile: {
    width: TILE_SIZE,
    height: TILE_SIZE,
    backgroundColor: '#0f1f33',
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'transparent',
    overflow: 'hidden',
  },
  tileActive: {
    borderColor: '#4da6ff',
  },
  tileIcon: {
    fontSize: TILE_SIZE * 0.75,
    position: 'absolute',
    transform: [{ scale: 1.3 }],
  },
  tileIconImage: {
    width: TILE_SIZE,
    height: TILE_SIZE,
    position: 'absolute',
    resizeMode: 'cover',
  },
  tileLabelOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    paddingVertical: 6,
    paddingHorizontal: 4,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
  },
  tileLabel: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '700',
    textAlign: 'center',
  },
  tileLabelActive: {
    color: '#4da6ff',
  },
  tileActiveBar: {
    position: 'absolute',
    bottom: 0,
    left: 12,
    right: 12,
    height: 3,
    backgroundColor: '#4da6ff',
    borderRadius: 2,
  },
  menuFooter: {
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 4,
    alignItems: 'center',
  },
  footerText: {
    fontSize: 11,
    color: '#5a7a9a',
  },
  hamburgerButton: {
    width: 24,
    height: 20,
    justifyContent: 'space-between',
    marginLeft: 16,
  },
  hamburgerLine: {
    width: 24,
    height: 3,
    backgroundColor: '#ffffff',
    borderRadius: 2,
  },
});

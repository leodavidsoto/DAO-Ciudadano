/**
 * DAO Ciudadana - Mobile App
 * React Native app for reading Chilean ID card NFC chips
 */

import React from 'react';
import { DarkTheme, NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar, View, Text, ScrollView } from 'react-native';

// Screens
import HomeScreen from './src/screens/HomeScreen';
import ScanScreen from './src/screens/ScanScreen';
import SuccessScreen from './src/screens/SuccessScreen';
import WalletScreen from './src/screens/WalletScreen';
import type { ChileanIDData } from './src/services/nfcService';

type RootStackParamList = {
  Home: undefined;
  Scan: undefined;
  Success: {
    idData: ChileanIDData;
    serialNumber: string;
    identityVerified?: boolean;
  };
  Wallet: {
    idData?: ChileanIDData;
    serialNumber?: string;
    identityVerified?: boolean;
  } | undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();

/**
 * DIAGNÓSTICO TEMPORAL: en vez de dejar que un error de render tumbe
 * silenciosamente la app en release (Android la cierra sin mostrar nada),
 * esto lo captura y lo muestra en pantalla. Quitar una vez identificada
 * y resuelta la causa del cierre inmediato.
 */
class CrashScreenBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null; info: string }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null, info: '' };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ info: info?.componentStack || '' });
    // eslint-disable-next-line no-console
    console.error('CrashScreenBoundary capturó un error:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <ScrollView
          style={{ flex: 1, backgroundColor: '#1a0000' }}
          contentContainerStyle={{ padding: 20, paddingTop: 60 }}>
          <Text
            style={{
              color: '#ff5555',
              fontSize: 18,
              fontWeight: 'bold',
              marginBottom: 12,
            }}>
            La app encontró un error al abrir
          </Text>
          <View style={{ marginBottom: 16 }}>
            <Text selectable style={{ color: '#fff', fontSize: 13 }}>
              {String(this.state.error?.name || 'Error')}:{' '}
              {String(this.state.error?.message || this.state.error)}
            </Text>
          </View>
          <Text style={{ color: '#888', fontSize: 11, marginBottom: 6 }}>
            Stack:
          </Text>
          <Text selectable style={{ color: '#aaa', fontSize: 10 }}>
            {String(this.state.error?.stack || 'sin stack')}
          </Text>
          <Text style={{ color: '#888', fontSize: 11, marginTop: 16, marginBottom: 6 }}>
            Componentes:
          </Text>
          <Text selectable style={{ color: '#aaa', fontSize: 10 }}>
            {this.state.info}
          </Text>
        </ScrollView>
      );
    }
    return this.props.children;
  }
}

const screenOptions = {
  headerStyle: {
    backgroundColor: '#0a0a1a',
  },
  headerTintColor: '#00FFFF',
  headerTitleStyle: {
    fontWeight: 'bold' as const,
    letterSpacing: 1,
  },
  headerBackTitleVisible: false,
  contentStyle: {
    backgroundColor: '#0a0a1a',
  },
};

function App(): React.JSX.Element {
  return (
    <CrashScreenBoundary>
      <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor="#0a0a1a" />
      <NavigationContainer
        theme={{
          ...DarkTheme,
          dark: true,
          colors: {
            ...DarkTheme.colors,
            primary: '#00FFFF',
            background: '#0a0a1a',
            card: '#0a0a2a',
            text: '#ffffff',
            border: '#00FFFF30',
            notification: '#FF00FF',
          },
          // React Navigation v7 exige 'fonts' en el theme (useHeaderConfigProps
          // lee fonts.regular/medium/bold/heavy). Como este theme es un objeto
          // literal completo y no un merge parcial, sin esto 'fonts' queda
          // undefined y la app crashea apenas monta la primera pantalla con
          // header -- esta fue la causa real del cierre inmediato en release.
        }}
      >
        <Stack.Navigator
          initialRouteName="Home"
          screenOptions={screenOptions}
        >
          <Stack.Screen
            name="Home"
            component={HomeScreen}
            options={{ headerShown: false }}
          />
          <Stack.Screen
            name="Scan"
            component={ScanScreen}
            options={{ title: 'ESCANEO NFC' }}
          />
          <Stack.Screen
            name="Success"
            component={SuccessScreen}
            options={({ route }) => {
              return {
                title: route.params?.identityVerified === true
                  ? 'IDENTIDAD VERIFICADA'
                  : 'LECTURA NO VERIFICADA',
              };
            }}
          />
          <Stack.Screen
            name="Wallet"
            component={WalletScreen}
            options={{ title: 'MEMBRESÍA' }}
          />
        </Stack.Navigator>
      </NavigationContainer>
      </SafeAreaProvider>
    </CrashScreenBoundary>
  );
}

export default App;

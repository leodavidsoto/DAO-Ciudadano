/**
 * DAO Ciudadana - Mobile App
 * React Native app for reading Chilean ID card NFC chips
 */

import React from 'react';
import { DefaultTheme, NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar, View, Text, ScrollView } from 'react-native';
import { theme } from './src/styles/theme';

// Screens
import HomeScreen from './src/screens/HomeScreen';
import ScanScreen from './src/screens/ScanScreen';
import SuccessScreen from './src/screens/SuccessScreen';
import WalletScreen from './src/screens/WalletScreen';
import { OnboardingProvider } from './src/context/OnboardingContext';
import {
  isVerifiedNFCReadResult,
  type VerifiedNFCReadResult,
} from './src/services/nfcService';

type RootStackParamList = {
  Home: undefined;
  Scan: undefined;
  Success: {
    result: VerifiedNFCReadResult;
    /**
     * Whether the backend verified the same bytes and issued grants. A local
     * reading is not an enrolment, so only this flag lets Success advance to
     * minting — and it is still re-checked against the live grant in context.
     */
    grantIssued?: boolean;
  };
  Wallet: undefined;
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
          style={{ flex: 1, backgroundColor: theme.colors.background }}
          contentContainerStyle={{ padding: 20, paddingTop: 60 }}>
          <Text
            style={{
              color: theme.colors.danger,
              fontSize: 18,
              fontWeight: 'bold',
              marginBottom: 12,
            }}>
            La app encontró un error al abrir
          </Text>
          <View style={{ marginBottom: 16 }}>
            <Text selectable style={{ color: theme.colors.ink, fontSize: 13 }}>
              {String(this.state.error?.name || 'Error')}:{' '}
              {String(this.state.error?.message || this.state.error)}
            </Text>
          </View>
          <Text style={{ color: theme.colors.textSoft, fontSize: 11, marginBottom: 6 }}>
            Stack:
          </Text>
          <Text selectable style={{ color: theme.colors.ink, fontSize: 10 }}>
            {String(this.state.error?.stack || 'sin stack')}
          </Text>
          <Text style={{ color: theme.colors.textSoft, fontSize: 11, marginTop: 16, marginBottom: 6 }}>
            Componentes:
          </Text>
          <Text selectable style={{ color: theme.colors.ink, fontSize: 10 }}>
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
    backgroundColor: theme.colors.primary,
  },
  headerTintColor: '#FFFFFF',
  headerTitleStyle: {
    fontWeight: 'bold' as const,
    letterSpacing: 1,
  },
  headerBackTitleVisible: false,
  contentStyle: {
    backgroundColor: theme.colors.background,
  },
};

function App(): React.JSX.Element {
  return (
    <CrashScreenBoundary>
      <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor={theme.colors.primary} />
      {/* Los grants del alta viven aquí, en memoria y por encima del
          navegador: Scan los obtiene y Success/Wallet los gastan, y siguen
          disponibles al cambiar de pantalla sin tocar disco. */}
      <OnboardingProvider>
      <NavigationContainer
        theme={{
          ...DefaultTheme,
          dark: false,
          colors: {
            ...DefaultTheme.colors,
            primary: theme.colors.primary,
            background: theme.colors.background,
            card: theme.colors.primary,
            text: '#FFFFFF',
            border: theme.colors.borderDark,
            notification: theme.colors.danger,
          },
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
            options={({ route }) => ({
              title: isVerifiedNFCReadResult(route.params?.result)
                ? 'DOCUMENTO VERIFICADO'
                : 'LECTURA NO VERIFICADA',
            })}
          />
          <Stack.Screen
            name="Wallet"
            component={WalletScreen}
            options={{ title: 'MEMBRESÍA' }}
          />
        </Stack.Navigator>
      </NavigationContainer>
      </OnboardingProvider>
      </SafeAreaProvider>
    </CrashScreenBoundary>
  );
}

export default App;

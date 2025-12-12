/**
 * DAO Ciudadana - Mobile App
 * React Native app for reading Chilean ID card NFC chips
 */

import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'react-native';

// Screens
import HomeScreen from './src/screens/HomeScreen';
import ScanScreen from './src/screens/ScanScreen';
import SuccessScreen from './src/screens/SuccessScreen';

const Stack = createNativeStackNavigator();

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
    <SafeAreaProvider>
      <StatusBar barStyle="light-content" backgroundColor="#0a0a1a" />
      <NavigationContainer
        theme={{
          dark: true,
          colors: {
            primary: '#00FFFF',
            background: '#0a0a1a',
            card: '#0a0a2a',
            text: '#ffffff',
            border: '#00FFFF30',
            notification: '#FF00FF',
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
            options={{ title: 'VERIFICADO' }}
          />
        </Stack.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

export default App;

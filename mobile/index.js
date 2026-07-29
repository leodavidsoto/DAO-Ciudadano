/**
 * @format
 */

import React from 'react';
import { AppRegistry, ScrollView, Text, View } from 'react-native';
import { name as appName } from './app.json';

/**
 * DIAGNÓSTICO TEMPORAL: si el módulo ./App (o algo que importa
 * transitivamente) explota durante la carga -antes de que React
 * llegue a montar nada-, esto lo agarra y muestra el error en
 * pantalla en vez de dejar que la app se cierre en silencio.
 * Quitar junto con CrashScreenBoundary en App.tsx una vez resuelto.
 */
let RootComponent;
try {
  // eslint-disable-next-line global-require
  RootComponent = require('./App').default;
} catch (error) {
  // eslint-disable-next-line no-console
  console.error('Error cargando ./App:', error);
  const message = String((error && error.stack) || error);
  RootComponent = function LoadErrorScreen() {
    return React.createElement(
      ScrollView,
      {
        style: { flex: 1, backgroundColor: '#1a0000' },
        contentContainerStyle: { padding: 20, paddingTop: 60 },
      },
      React.createElement(
        Text,
        {
          style: {
            color: '#ff5555',
            fontSize: 18,
            fontWeight: 'bold',
            marginBottom: 12,
          },
        },
        'Error cargando la app (antes de renderizar)',
      ),
      React.createElement(
        View,
        { style: { marginBottom: 16 } },
        React.createElement(
          Text,
          { selectable: true, style: { color: '#fff', fontSize: 12 } },
          message,
        ),
      ),
    );
  };
}

if (global.ErrorUtils) {
  const defaultHandler = global.ErrorUtils.getGlobalHandler();
  global.ErrorUtils.setGlobalHandler((error, isFatal) => {
    // eslint-disable-next-line no-console
    console.error('GLOBAL JS ERROR (isFatal=' + isFatal + '):', error);
    if (defaultHandler) {
      defaultHandler(error, isFatal);
    }
  });
}

AppRegistry.registerComponent(appName, () => RootComponent);

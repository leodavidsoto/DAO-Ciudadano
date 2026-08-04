// Load configuration from environment or config file
const path = require('path');
const webpack = require('webpack');

// Environment variable overrides
const config = {
  disableHotReload: process.env.DISABLE_HOT_RELOAD === 'true',
};

module.exports = {
  jest: {
    configure: {
      moduleNameMapper: {
        '^@/(.*)$': '<rootDir>/src/$1',
        '^@zk-kit/baby-jubjub$': '<rootDir>/node_modules/@zk-kit/baby-jubjub/dist/index.cjs',
        '^@zk-kit/eddsa-poseidon$': '<rootDir>/node_modules/@zk-kit/eddsa-poseidon/dist/index.cjs',
        '^@zk-kit/poseidon-cipher$': '<rootDir>/node_modules/@zk-kit/poseidon-cipher/dist/index.cjs',
        '^@zk-kit/utils$': '<rootDir>/node_modules/@zk-kit/utils/dist/index.node.cjs',
        '^@zk-kit/utils/conversions$': '<rootDir>/node_modules/@zk-kit/utils/dist/lib.commonjs/conversions.cjs',
        '^@zk-kit/utils/error-handlers$': '<rootDir>/node_modules/@zk-kit/utils/dist/lib.commonjs/error-handlers.cjs',
        '^@zk-kit/utils/f1-field$': '<rootDir>/node_modules/@zk-kit/utils/dist/lib.commonjs/f1-field.cjs',
        '^@zk-kit/utils/scalar$': '<rootDir>/node_modules/@zk-kit/utils/dist/lib.commonjs/scalar.cjs',
        '^@zk-kit/utils/type-checks$': '<rootDir>/node_modules/@zk-kit/utils/dist/lib.commonjs/type-checks.cjs',
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {
      // CRA's final asset rule otherwise emits .cjs entries as URLs. MACI then
      // receives a string instead of the @zk-kit exports (for example `r`),
      // which makes ballot encryption fail at runtime. Parse only this audited
      // dependency family as CommonJS JavaScript before the asset catch-all.
      const oneOfRule = webpackConfig.module.rules.find((rule) =>
        Array.isArray(rule.oneOf)
      );
      if (!oneOfRule) {
        throw new Error('No se encontró la regla oneOf de CRA para cargar @zk-kit.');
      }
      oneOfRule.oneOf.unshift({
        test: /\.cjs$/,
        include: /node_modules[\\/]@zk-kit[\\/]/,
        type: 'javascript/auto',
      });

      // MACI 2.5 publishes CommonJS bundles which import Node core modules.
      // CRA 5 no longer injects those shims, so map only the browser-safe
      // primitives used by the MACI dependency graph. crypto-browserify's
      // randomBytes implementation delegates to Web Crypto in the browser.
      webpackConfig.resolve.fallback = {
        ...webpackConfig.resolve.fallback,
        crypto: require.resolve('crypto-browserify'),
        stream: require.resolve('stream-browserify'),
        assert: require.resolve('assert/'),
        buffer: require.resolve('buffer/'),
        process: require.resolve('process/browser.js'),
        util: require.resolve('util/'),
        vm: require.resolve('vm-browserify'),
      };
      webpackConfig.plugins.push(
        new webpack.ProvidePlugin({
          Buffer: ['buffer', 'Buffer'],
          process: [require.resolve('process/browser.js')],
        })
      );
      // MACI's npm artifacts reference TypeScript source maps that are not
      // shipped in the package. Ignore only that known packaging warning.
      webpackConfig.ignoreWarnings = [
        ...(webpackConfig.ignoreWarnings || []),
        (warning) =>
          /maci-(?:crypto|domainobjs)/.test(warning.module?.resource || '') &&
          /Failed to parse source map/.test(warning.message || ''),
      ];
      
      // Disable hot reload completely if environment variable is set
      if (config.disableHotReload) {
        // Remove hot reload related plugins
        webpackConfig.plugins = webpackConfig.plugins.filter(plugin => {
          return !(plugin.constructor.name === 'HotModuleReplacementPlugin');
        });
        
        // Disable watch mode
        webpackConfig.watch = false;
        webpackConfig.watchOptions = {
          ignored: /.*/, // Ignore all files
        };
      } else {
        // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
          ],
        };
      }
      
      return webpackConfig;
    },
  },
};

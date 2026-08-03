module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'transform-inline-environment-variables',
      {include: ['DAO_API_BASE_URL']},
    ],
  ],
};

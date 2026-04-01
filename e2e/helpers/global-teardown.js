'use strict';
const { stop } = require('./server');
module.exports = async function globalTeardown() {
  await stop();
};

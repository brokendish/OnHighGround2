'use strict';
const { start } = require('./server');
module.exports = async function globalSetup() {
  await start();
};

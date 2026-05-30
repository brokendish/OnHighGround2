'use strict';
const { start } = require('./server');
module.exports = async function globalSetup() {
  try { await start(); }
  catch (e) { if (e.code === 'EADDRINUSE') console.log('[e2e] server already running'); else throw e; }
};

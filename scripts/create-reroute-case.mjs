#!/usr/bin/env node
import fs from 'fs';
import path from 'path';

const [, , name, currentLat, currentLng, destLat, destLng, blockStartLat, blockStartLng, blockEndLat, blockEndLng] = process.argv;

if (!name || [currentLat, currentLng, destLat, destLng, blockStartLat, blockStartLng, blockEndLat, blockEndLng].some(v => typeof v === 'undefined')) {
  console.error('Usage: node scripts/create-reroute-case.mjs <name> <currentLat> <currentLng> <destLat> <destLng> <blockStartLat> <blockStartLng> <blockEndLat> <blockEndLng>');
  process.exit(1);
}

const baseDir = path.resolve('testdata/reroute_cases');
const fixturesDir = path.join(baseDir, 'fixtures');
fs.mkdirSync(fixturesDir, { recursive: true });

const json = {
  name,
  profile: 'walking',
  currentLocation: { lat: Number(currentLat), lng: Number(currentLng) },
  destination: { lat: Number(destLat), lng: Number(destLng) },
  blockedSegment: {
    start: { lat: Number(blockStartLat), lng: Number(blockStartLng) },
    end: { lat: Number(blockEndLat), lng: Number(blockEndLng) }
  },
  routeGeometry: [
    [Number(currentLng), Number(currentLat)],
    [Number(blockStartLng), Number(blockStartLat)],
    [Number(destLng), Number(destLat)]
  ],
  fixtures: {
    osrmAlternatives: `${name}.osrm.alternatives.json`,
    osrmNearest: `${name}.osrm.nearest.json`,
    osrmEscape: `${name}.osrm.escape.json`,
    pedestrianContext: `${name}.overpass.context.json`
  },
  expectations: {
    mustFindRoute: true,
    mustAvoidBlockedArea: true,
    mustAvoidDangerousCrossing: true,
    mustNotFinalConservativeHardReject: true
  }
};

const placeholders = {
  [json.fixtures.osrmAlternatives]: { stage1: [], stage2: [], stage3: [] },
  [json.fixtures.osrmNearest]: {},
  [json.fixtures.osrmEscape]: { escapeLegPoints: [], escapePoints: [], longDetourPoints: [], routes: {} },
  [json.fixtures.pedestrianContext]: {
    status: 'ready',
    source: 'fresh',
    context: { roads: [], crosswalks: [] },
    failure: { kind: 'none', detail: 'none', message: '', aborted: false }
  }
};

fs.writeFileSync(path.join(baseDir, `${name}.json`), JSON.stringify(json, null, 2));
for (const [fileName, payload] of Object.entries(placeholders)) {
  fs.writeFileSync(path.join(fixturesDir, fileName), JSON.stringify(payload, null, 2));
}

console.log(`Created reroute fixture template: testdata/reroute_cases/${name}.json`);

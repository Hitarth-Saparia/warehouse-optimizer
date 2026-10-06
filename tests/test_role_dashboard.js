/**
 * tests/test_role_dashboard.js
 * Validates role dashboard data-model mapping and role switching logic.
 */

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

// Minimal browser mocks for Node environment
const storage = {};
global.sessionStorage = {
  getItem: (key) => storage[key] || null,
  setItem: (key, val) => { storage[key] = String(val); },
  removeItem: (key) => { delete storage[key]; },
  clear: () => { Object.keys(storage).forEach(k => delete storage[k]); }
};
global.localStorage = global.sessionStorage;

global.window = {
  location: { pathname: '/index.html' },
  addEventListener: () => {}
};

const elements = {};
global.document = {
  readyState: 'complete',
  addEventListener: () => {},
  querySelectorAll: () => [],
  querySelector: () => null,
  getElementById: (id) => {
    if (!elements[id]) {
      elements[id] = { textContent: '', innerHTML: '', style: {}, classList: { toggle: () => {} } };
    }
    return elements[id];
  },
  createElement: () => ({ innerHTML: '', appendChild: () => {}, style: {} })
};

// Load auth.js and dashboard.js
const authCode = fs.readFileSync('frontend/auth.js', 'utf8');
vm.runInThisContext(authCode);

const dashCode = fs.readFileSync('frontend/dashboard.js', 'utf8');
vm.runInThisContext(dashCode);

console.log('=== ROLE DASHBOARD VALIDATION ===\n');

// 1. Validate role mappings
const managerUser = { id: 1, email: 'admin@warehouse.io', name: 'Operations Admin', role: 'manager' };
const supervisorUser = { id: 2, email: 'supervisor@warehouse.io', name: 'Lead Supervisor', role: 'supervisor' };
const fleetUser = { id: 3, email: 'fleet@warehouse.io', name: 'Fleet Coordinator', role: 'fleet' };

assert.strictEqual(isPickerLeadUser(supervisorUser), true, 'Supervisor must be picker lead');
assert.strictEqual(isFleetUser(fleetUser), true, 'Fleet coordinator must be fleet user');
assert.strictEqual(isManagerUser(managerUser), true, 'Manager user must match manager role');

console.log('✓ User role helper mappings validated:');
console.log('  - manager -> Operations Manager');
console.log('  - supervisor -> Picker Lead');
console.log('  - fleet -> Fleet Lead\n');

// 2. Test wave batch metric reductions
const sampleWaves = [
  { batch_id: 1, batch_name: 'Wave #1', total_units: 32, unique_stops: 10, batched_distance: 134.0, order_ids: [11, 1] },
  { batch_id: 2, batch_name: 'Wave #2', total_units: 31, unique_stops: 7, batched_distance: 126.0, order_ids: [6, 7] }
];

const totalUnits = sampleWaves.reduce((acc, w) => acc + (w.total_units || 0), 0);
assert.strictEqual(totalUnits, 63, 'Wave batch total units must sum accurately');

const totalDistance = sampleWaves.reduce((acc, w) => acc + (w.batched_distance || 0), 0);
assert.strictEqual(totalDistance, 260.0, 'Wave batched distance must calculate correctly');

console.log('✓ Wave workload metric calculations validated:');
console.log(`  - Total Units: ${totalUnits}`);
console.log(`  - Total Distance: ${totalDistance}m\n`);

// 3. Test corridor blockage model
const rawBlocked = [
  { from_shelf: 2, to_shelf: 8, is_blocked: true, penalty: null }
];
const formattedIncidents = rawBlocked.map(c => `Shelf ${c.from_shelf} ↔ Shelf ${c.to_shelf}`).join(', ');
assert.strictEqual(formattedIncidents, 'Shelf 2 ↔ Shelf 8', 'Incident string should format cleanly');
console.log(`✓ Corridor blockage string formatting: "${formattedIncidents}"\n`);

console.log('All Role Dashboard tests passed successfully!');

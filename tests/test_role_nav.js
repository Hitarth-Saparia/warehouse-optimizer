const fs = require('fs');

// Minimal browser mocks for Node environment
global.window = {
  location: { pathname: '/index.html' },
  addEventListener: () => {}
};
global.document = {
  readyState: 'complete',
  addEventListener: () => {},
  querySelectorAll: () => [],
  querySelector: () => null
};
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
};
global.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
};

const vm = require('vm');
const code = fs.readFileSync('frontend/auth.js', 'utf8');
vm.runInThisContext(code);

const pages = [
  'landing.html',
  'index.html',
  'products.html',
  'layout.html',
  'graph.html',
  'order-picking.html',
  'waves.html',
  'fleet.html'
];

console.log('=== ROLE NAVIGATION ACCESS VALIDATION ===');
for (const [key, account] of Object.entries(DEMO_ACCOUNTS)) {
  const allowed = pages.filter(p => isPageAllowedForUser(p, account));
  const hidden = pages.filter(p => !isPageAllowedForUser(p, account));
  console.log(`\nRole: ${account.role} [${key}] (${account.email})`);
  console.log('  Visible Functions:', allowed);
  console.log('  Hidden Functions: ', hidden);
}

// Check assertions
const managerHidden = pages.filter(p => !isPageAllowedForUser(p, DEMO_ACCOUNTS.manager));
if (managerHidden.length !== 0) throw new Error('Manager should have 0 hidden pages');

const supervisorHidden = pages.filter(p => !isPageAllowedForUser(p, DEMO_ACCOUNTS.supervisor));
if (!supervisorHidden.includes('layout.html') || !supervisorHidden.includes('fleet.html') || supervisorHidden.length !== 2) {
  throw new Error('Supervisor must hide layout.html and fleet.html');
}

const fleetHidden = pages.filter(p => !isPageAllowedForUser(p, DEMO_ACCOUNTS.fleet));
if (!fleetHidden.includes('products.html') || !fleetHidden.includes('layout.html') || !fleetHidden.includes('order-picking.html') || fleetHidden.length !== 3) {
  throw new Error('Fleet must hide products.html, layout.html, and order-picking.html');
}

console.log('\nAll role access assertions passed successfully!');

/**
 * frontend/digital-twin.js
 * 3D Interactive Warehouse Digital Twin powered by Three.js & OrbitControls.
 * Seamlessly interfaces with /api/warehouse/graph, /api/shelves, and /api/products.
 */

// Global State
let scene, camera, renderer, controls;
let raycaster, mouse;
let warehouseData = {
  shelves: [],
  products: [],
  graph: { nodes: [], edges: [] }
};
let rackMeshes = new Map(); // shelfId -> Three.Group
let corridorLinesGroup;
let aisleLabelsGroup;
let hoveredRack = null;
let selectedShelfId = null;
let animationFrameId = null;

// AGV & Route Simulation State
let agvGroup = null;
let routeMarkersGroup = null;
let agvWaypoints = [];
let agvAnimClock = new THREE.Clock();
let agvWheels = [];
let agvBeacon = null;
let agvBeaconLight = null;
let agvForkCarriage = null;
let agvPalletBoxes = [];
let agvStatusSprite = null;

let agvAnimState = {
  active: false,
  playing: false,
  completed: false,
  speed: 1.0, // 1x, 2x, 5x
  currentSegmentIndex: 0,
  segmentProgress: 0.0,
  isPicking: false,
  pickTimer: 0.0,
  pickDuration: 1.2,
  currentStopShelfId: null,
  visitedStopSet: new Set(),
  orderData: null,
  chaseCam: false,
  totalDistance: 0.0
};

// Thermal / Activity Heatmap State
let heatmapActive = false;
let heatmapMetric = 'velocity'; // 'velocity' | 'capacity'
let heatmapPulseRacks = [];
let heatmapTooltip = null;

// Cinematic Lighting & Post-Processing Bloom State
let composer = null;
let bloomPass = null;
let bloomActive = true;
let highBayLampsGroup = null;
let overheadGirdersGroup = null;
let architectureGroup = null;

// Configuration
const CONFIG = {
  floorWidth: 70,
  floorDepth: 55,
  rackWidth: 3.2,
  rackDepth: 1.4,
  rackHeight: 3.8,
  tiers: 3,
  scaleFactor: 0.05, // converts 2D pixel coords to 3D world units
  coordOffsetX: 25,
  coordOffsetZ: 20
};

// Category Colors for Box Pallets
const CATEGORY_COLORS = {
  'Electronics': 0x3b82f6, // Bright Blue
  'Fasteners':   0x8b5cf6, // Violet
  'Tools':       0xf59e0b, // Amber
  'Safety':      0x10b981, // Emerald Green
  'Fragile':     0xef4444, // Red
  'Heavy':       0x64748b  // Slate Steel
};

// Default box colors
const BOX_COLORS = [0xd4a373, 0xc28e5c, 0xb07d4b, 0xe6ccb2];

/**
 * Initializes Three.js Scene, Camera, Lights, and OrbitControls.
 */
function init3DScene() {
  const container = document.getElementById('canvas-container');
  if (!container) return;

  const width = container.clientWidth;
  const height = container.clientHeight;

  // Scene
  scene = new THREE.Scene();
  scene.background = new THREE.Color(document.documentElement.getAttribute('data-theme') === 'dark' ? 0x121417 : 0xeef2f6);
  scene.fog = new THREE.FogExp2(scene.background.getHex(), 0.012);

  // Camera
  camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 500);
  camera.position.set(28, 32, 42);

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;

  container.innerHTML = '';
  container.appendChild(renderer.domElement);

  // OrbitControls
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.maxPolarAngle = Math.PI / 2.05; // Don't flip under floor
  controls.minDistance = 6;
  controls.maxDistance = 120;
  controls.target.set(0, 1.5, 0);

  // Initialize Three.js Post-Processing (Cinematic Bloom & Glow)
  initPostProcessing(width, height);

  // Lighting
  setupLighting();

  // Floor Grid, Polished Epoxy & Surroundings
  buildWarehouseFloor();

  // Architectural Realism: Perimeter Walls, Loading Docks, Bollards & Guardrails
  buildWarehouseArchitecture();

  // Raycasting
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  // Event Listeners
  window.addEventListener('resize', onWindowResize);
  renderer.domElement.addEventListener('mousemove', onMouseMove);
  renderer.domElement.addEventListener('click', onMouseClick);

  // Corridor & Label Groups
  corridorLinesGroup = new THREE.Group();
  scene.add(corridorLinesGroup);

  aisleLabelsGroup = new THREE.Group();
  scene.add(aisleLabelsGroup);

  // Route & AGV Markers Group
  routeMarkersGroup = new THREE.Group();
  scene.add(routeMarkersGroup);

  // Global Keyboard Shortcuts (Space for Play/Pause)
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && agvAnimState.active && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault();
      toggleAGVPlayback();
    }
  });

  // Start Animation Loop
  animate();
}

/**
 * Initializes Three.js Post-Processing (UnrealBloomPass) for cinematic neon glow and industrial radiance.
 */
function initPostProcessing(width, height) {
  if (typeof THREE.EffectComposer === 'undefined' || typeof THREE.UnrealBloomPass === 'undefined') {
    console.info('Three.js Post-Processing scripts not loaded, using standard renderer fallback.');
    return;
  }
  try {
    composer = new THREE.EffectComposer(renderer);
    const renderPass = new THREE.RenderPass(scene, camera);
    composer.addPass(renderPass);

    // UnrealBloomPass: (resolution, strength, radius, threshold)
    // Strength 0.52 gives headlights, amber beacons, and hot racks a vibrant neon halo
    // Threshold 0.76 ensures normal diffuse racks/walls don't get blown out
    bloomPass = new THREE.UnrealBloomPass(
      new THREE.Vector2(width, height),
      0.52, // Bloom strength
      0.42, // Bloom radius
      0.76  // Bloom luminance threshold
    );
    composer.addPass(bloomPass);

    if (typeof THREE.ShaderPass !== 'undefined' && typeof THREE.CopyShader !== 'undefined') {
      const copyPass = new THREE.ShaderPass(THREE.CopyShader);
      copyPass.renderToScreen = true;
      composer.addPass(copyPass);
    }
  } catch (err) {
    console.warn('Post-processing composer initialization failed:', err);
    composer = null;
  }
}

/**
 * Toggles Cinematic Bloom Post-Processing on or off.
 */
function toggle3DBloom(forceState) {
  bloomActive = (forceState !== undefined) ? !!forceState : !bloomActive;
  const btn = document.getElementById('btn-toggle-3d-bloom');
  if (btn) {
    if (bloomActive) {
      btn.classList.add('active');
      btn.setAttribute('aria-pressed', 'true');
    } else {
      btn.classList.remove('active');
      btn.setAttribute('aria-pressed', 'false');
    }
  }
  showToast(bloomActive ? '✨ Cinematic Bloom & Volumetric Lighting: ON' : 'Cinematic Bloom: OFF (Standard Mode)', 'info');
}

/**
 * Dynamic cinematic lighting with high-bay industrial pendant fixtures,
 * steel roof rafters, soft ambient fill, and directional warehouse sunlight.
 */
function setupLighting() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

  // Ambient Fill Light
  const ambientLight = new THREE.AmbientLight(isDark ? 0x222a38 : 0xffffff, isDark ? 0.8 : 0.7);
  scene.add(ambientLight);

  // Key Directional Warehouse Light (Sunlight streaming from high warehouse clerestory windows)
  const mainLight = new THREE.DirectionalLight(0xfff8ee, 1.25);
  mainLight.position.set(25, 45, 30);
  mainLight.castShadow = true;
  mainLight.shadow.mapSize.width = 2048;
  mainLight.shadow.mapSize.height = 2048;
  mainLight.shadow.camera.near = 1;
  mainLight.shadow.camera.far = 140;
  const d = 40;
  mainLight.shadow.camera.left = -d;
  mainLight.shadow.camera.right = d;
  mainLight.shadow.camera.top = d;
  mainLight.shadow.camera.bottom = -d;
  mainLight.shadow.bias = -0.0004;
  scene.add(mainLight);

  // Subtle cool blue industrial rim fill
  const fillLight = new THREE.DirectionalLight(0x93c5fd, 0.45);
  fillLight.position.set(-30, 25, -20);
  scene.add(fillLight);

  // High-Bay Industrial Pendant Fixtures Group
  highBayLampsGroup = new THREE.Group();
  highBayLampsGroup.name = "HighBay_Industrial_Pendants";

  // Positions over major aisle corridors
  const lampPositions = [
    [-18, -12], [0, -12], [18, -12],
    [-18,  12], [0,  12], [18,  12]
  ];

  const hoodMat = new THREE.MeshStandardMaterial({
    color: 0x1e293b,
    metalness: 0.8,
    roughness: 0.3
  });
  const bulbMat = new THREE.MeshStandardMaterial({
    color: 0xfffbeb,
    emissive: 0xfff7ed,
    emissiveIntensity: 2.4,
    roughness: 0.1
  });

  lampPositions.forEach(([lx, lz]) => {
    const lampGroup = new THREE.Group();
    lampGroup.position.set(lx, 7.8, lz);

    // Suspension conduit wire
    const wireGeo = new THREE.CylinderGeometry(0.015, 0.015, 1.8);
    const wire = new THREE.Mesh(wireGeo, hoodMat);
    wire.position.y = 0.9;
    lampGroup.add(wire);

    // Bell reflector hood
    const hoodGeo = new THREE.ConeGeometry(0.85, 0.5, 16, 1, true);
    const hood = new THREE.Mesh(hoodGeo, hoodMat);
    hood.position.y = 0;
    lampGroup.add(hood);

    // Glowing LED core bulb
    const bulbGeo = new THREE.SphereGeometry(0.24, 16, 16);
    const bulb = new THREE.Mesh(bulbGeo, bulbMat);
    bulb.position.y = -0.08;
    lampGroup.add(bulb);

    // Downward Industrial Spotlight pool on the floor
    const spot = new THREE.SpotLight(0xfffaed, 0.9, 22, Math.PI / 4, 0.65, 1.2);
    spot.position.set(0, -0.1, 0);
    spot.target.position.set(0, -8, 0);
    lampGroup.add(spot);
    lampGroup.add(spot.target);

    highBayLampsGroup.add(lampGroup);
  });
  scene.add(highBayLampsGroup);

  // Overhead Structural Steel Trusses / Girders
  overheadGirdersGroup = new THREE.Group();
  overheadGirdersGroup.name = "Overhead_Steel_Trusses";
  const girderMat = new THREE.MeshStandardMaterial({
    color: 0x334155,
    metalness: 0.85,
    roughness: 0.4
  });

  [-18, 0, 18].forEach(gx => {
    // Cross beam spanning full floor depth
    const girderGeo = new THREE.BoxGeometry(0.35, 0.5, CONFIG.floorDepth + 2);
    const girder = new THREE.Mesh(girderGeo, girderMat);
    girder.position.set(gx, 8.8, 0);
    girder.castShadow = true;
    overheadGirdersGroup.add(girder);
  });
  scene.add(overheadGirdersGroup);
}

/**
 * Procedural warehouse floor with polished industrial epoxy coating,
 * high-contrast specular reflections, dispatch hazard perimeter, and safety lanes.
 */
function buildWarehouseFloor() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  
  // Polished Epoxy Concrete Floor
  const floorGeo = new THREE.PlaneGeometry(CONFIG.floorWidth, CONFIG.floorDepth);
  const floorMat = new THREE.MeshStandardMaterial({
    color: isDark ? 0x11161d : 0xdedede,
    roughness: 0.22,  // Polished epoxy gloss
    metalness: 0.26   // Industrial concrete resin specular sheen
  });
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0;
  floor.receiveShadow = true;
  scene.add(floor);

  // Floor Grid markings
  const gridHelper = new THREE.GridHelper(
    Math.max(CONFIG.floorWidth, CONFIG.floorDepth),
    Math.round(CONFIG.floorWidth / 2),
    isDark ? 0x1e293b : 0xc7d2fe,
    isDark ? 0x17202e : 0xe2e8f0
  );
  gridHelper.position.y = 0.008;
  scene.add(gridHelper);

  // Dispatch Hub (Shelf 1) Hazard Zone Perimeter (Safety Yellow / Black Crosshatch Border)
  const hubHazardGeo = new THREE.PlaneGeometry(8.5, 7.5);
  const hubHazardMat = new THREE.MeshBasicMaterial({
    color: 0xf59e0b,
    transparent: true,
    opacity: 0.22,
    side: THREE.DoubleSide
  });
  const hubHazard = new THREE.Mesh(hubHazardGeo, hubHazardMat);
  hubHazard.rotation.x = -Math.PI / 2;
  const hubCoords = mapCoordsTo3D(80, 260);
  hubHazard.position.set(hubCoords.x, 0.012, hubCoords.z);
  scene.add(hubHazard);

  // Dispatch Hub Yellow Warning Outline Border
  const hubBorderPoints = [
    new THREE.Vector3(hubCoords.x - 4.25, 0.014, hubCoords.z - 3.75),
    new THREE.Vector3(hubCoords.x + 4.25, 0.014, hubCoords.z - 3.75),
    new THREE.Vector3(hubCoords.x + 4.25, 0.014, hubCoords.z + 3.75),
    new THREE.Vector3(hubCoords.x - 4.25, 0.014, hubCoords.z + 3.75),
    new THREE.Vector3(hubCoords.x - 4.25, 0.014, hubCoords.z - 3.75)
  ];
  const hubBorderGeo = new THREE.BufferGeometry().setFromPoints(hubBorderPoints);
  const hubBorderMat = new THREE.LineBasicMaterial({ color: 0xf59e0b, linewidth: 3 });
  const hubBorderLine = new THREE.Line(hubBorderGeo, hubBorderMat);
  scene.add(hubBorderLine);

  // Safety perimeter curb
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.6, metalness: 0.4 });
  const curbGeo = new THREE.BoxGeometry(CONFIG.floorWidth + 1.2, 0.4, 0.6);

  const curbN = new THREE.Mesh(curbGeo, wallMat);
  curbN.position.set(0, 0.2, -CONFIG.floorDepth / 2 - 0.3);
  scene.add(curbN);

  const curbS = new THREE.Mesh(curbGeo, wallMat);
  curbS.position.set(0, 0.2, CONFIG.floorDepth / 2 + 0.3);
  scene.add(curbS);

  const curbGeoEW = new THREE.BoxGeometry(0.6, 0.4, CONFIG.floorDepth + 1.2);
  const curbW = new THREE.Mesh(curbGeoEW, wallMat);
  curbW.position.set(-CONFIG.floorWidth / 2 - 0.3, 0.2, 0);
  scene.add(curbW);

  const curbE = new THREE.Mesh(curbGeoEW, wallMat);
  curbE.position.set(CONFIG.floorWidth / 2 + 0.3, 0.2, 0);
  scene.add(curbE);
}

/**
 * Builds realistic warehouse architectural infrastructure:
 * 1. Perimeter industrial walls with corrugated siding, structural I-beams & clerestory daylight windows.
 * 2. Logistics loading docks on the West wall with roll-up ribbed shutter doors, exterior trailer ramps, and LED signal beacons.
 * 3. Heavy-duty yellow & black safety bollards at every aisle corner and dock portal.
 * 4. Dual-rail industrial steel guardrails protecting Central Dispatch Hub (Shelf 1) and pedestrian paths.
 * 5. High-contrast floor markings (zebra safety aprons, pedestrian green walkways, and AGV traffic direction arrows).
 */
function buildWarehouseArchitecture() {
  if (architectureGroup) {
    scene.remove(architectureGroup);
  }
  architectureGroup = new THREE.Group();
  architectureGroup.name = "Warehouse_Architecture";

  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const wallBaseColor = isDark ? 0x181e28 : 0xd8dce3;
  const steelColumnColor = isDark ? 0x242e3d : 0x94a3b8;
  const trimColor = isDark ? 0x0f172a : 0x475569;

  const wallMat = new THREE.MeshStandardMaterial({
    color: wallBaseColor,
    metalness: 0.72,
    roughness: 0.42
  });

  const steelMat = new THREE.MeshStandardMaterial({
    color: steelColumnColor,
    metalness: 0.85,
    roughness: 0.35
  });

  const trimMat = new THREE.MeshStandardMaterial({
    color: trimColor,
    metalness: 0.6,
    roughness: 0.5
  });

  // -------------------------------------------------------------
  // 1. NORTH WALL (Full-height high-bay wall with clerestory ribbon windows)
  // -------------------------------------------------------------
  const wallHeight = 9.2;
  const northZ = -CONFIG.floorDepth / 2 - 0.25;

  const northWallGeo = new THREE.BoxGeometry(CONFIG.floorWidth + 1.6, wallHeight, 0.5);
  const northWall = new THREE.Mesh(northWallGeo, wallMat);
  northWall.position.set(0, wallHeight / 2, northZ);
  northWall.receiveShadow = true;
  architectureGroup.add(northWall);

  // Upper Clerestory Ribbon Daylight Windows (y = 7.2 to 8.6)
  const windowMat = new THREE.MeshStandardMaterial({
    color: 0xfffbeb,
    emissive: 0xfffaed,
    emissiveIntensity: 0.45,
    roughness: 0.1,
    transparent: true,
    opacity: 0.88
  });
  const windowGeo = new THREE.BoxGeometry(CONFIG.floorWidth - 4, 1.2, 0.55);
  const clerestoryWin = new THREE.Mesh(windowGeo, windowMat);
  clerestoryWin.position.set(0, 7.8, northZ);
  architectureGroup.add(clerestoryWin);

  // Vertical Structural I-Beams along North Wall
  [-30, -20, -10, 0, 10, 20, 30].forEach(colX => {
    const colGeo = new THREE.BoxGeometry(0.5, wallHeight + 0.3, 0.6);
    const column = new THREE.Mesh(colGeo, steelMat);
    column.position.set(colX, (wallHeight + 0.3) / 2, northZ + 0.3);
    column.castShadow = true;
    architectureGroup.add(column);
  });

  // Horizontal Wall Girt / Support Beam
  const girtGeo = new THREE.BoxGeometry(CONFIG.floorWidth + 1.2, 0.22, 0.35);
  const girt1 = new THREE.Mesh(girtGeo, steelMat);
  girt1.position.set(0, 4.2, northZ + 0.25);
  architectureGroup.add(girt1);

  // -------------------------------------------------------------
  // 2. EAST WALL (Corrugated industrial siding with power equipment)
  // -------------------------------------------------------------
  const eastX = CONFIG.floorWidth / 2 + 0.25;
  const eastWallGeo = new THREE.BoxGeometry(0.5, wallHeight, CONFIG.floorDepth + 1.6);
  const eastWall = new THREE.Mesh(eastWallGeo, wallMat);
  eastWall.position.set(eastX, wallHeight / 2, 0);
  eastWall.receiveShadow = true;
  architectureGroup.add(eastWall);

  // Vertical Structural I-Beams along East Wall
  [-20, -10, 0, 10, 20].forEach(colZ => {
    const col = new THREE.Mesh(new THREE.BoxGeometry(0.6, wallHeight + 0.3, 0.5), steelMat);
    col.position.set(eastX - 0.3, (wallHeight + 0.3) / 2, colZ);
    col.castShadow = true;
    architectureGroup.add(col);
  });

  // Wall Equipment: Industrial Electrical Switchgear / Breaker Box
  const breakerBoxMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.8, roughness: 0.3 });
  const breakerBox = new THREE.Mesh(new THREE.BoxGeometry(0.35, 1.8, 1.2), breakerBoxMat);
  breakerBox.position.set(eastX - 0.28, 2.2, -6.0);
  architectureGroup.add(breakerBox);

  // High Voltage Warning Plate on Breaker Box
  const voltPlateMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });
  const voltPlate = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.3, 0.5), voltPlateMat);
  voltPlate.position.set(eastX - 0.46, 2.3, -6.0);
  architectureGroup.add(voltPlate);

  // Emergency Fire Hose Reel Cabinet (Bright Red)
  const fireCabinetMat = new THREE.MeshStandardMaterial({ color: 0xef4444, roughness: 0.3, metalness: 0.4 });
  const fireCabinet = new THREE.Mesh(new THREE.BoxGeometry(0.3, 1.2, 0.9), fireCabinetMat);
  fireCabinet.position.set(eastX - 0.26, 1.8, 8.0);
  architectureGroup.add(fireCabinet);

  // -------------------------------------------------------------
  // 3. WEST WALL: LOGISTICS LOADING DOCKS & ROLL-UP SHUTTER DOORS
  // -------------------------------------------------------------
  const westX = -CONFIG.floorWidth / 2 - 0.25;

  // Solid Wall Sections around the two loading dock openings
  const westSolidNorth = new THREE.Mesh(new THREE.BoxGeometry(0.5, wallHeight, 15.5), wallMat);
  westSolidNorth.position.set(westX, wallHeight / 2, -19.75);
  architectureGroup.add(westSolidNorth);

  const westSolidCenter = new THREE.Mesh(new THREE.BoxGeometry(0.5, wallHeight, 6.0), wallMat);
  westSolidCenter.position.set(westX, wallHeight / 2, 0);
  architectureGroup.add(westSolidCenter);

  const westSolidSouth = new THREE.Mesh(new THREE.BoxGeometry(0.5, wallHeight, 15.5), wallMat);
  westSolidSouth.position.set(westX, wallHeight / 2, 19.75);
  architectureGroup.add(westSolidSouth);

  // Lintel beams above dock openings (y = 5.2 to wallHeight)
  const lintelGeo = new THREE.BoxGeometry(0.5, wallHeight - 5.2, 6.2);
  const lintel1 = new THREE.Mesh(lintelGeo, wallMat);
  lintel1.position.set(westX, 5.2 + (wallHeight - 5.2) / 2, -6.0);
  architectureGroup.add(lintel1);

  const lintel2 = new THREE.Mesh(lintelGeo, wallMat);
  lintel2.position.set(westX, 5.2 + (wallHeight - 5.2) / 2, 6.0);
  architectureGroup.add(lintel2);

  // Build the 2 Loading Dock Portals
  buildLoadingDockPortal(westX, -6.0, "DOCK 01 • OUTBOUND DISPATCH", true);  // Dock 1 (Open with outdoor light & ramp)
  buildLoadingDockPortal(westX,  6.0, "DOCK 02 • INBOUND RECEIVING", false); // Dock 2 (Closed ribbed shutter door)

  // -------------------------------------------------------------
  // 4. SOUTH PERIMETER (Foreground Safety Parapet & Handrail)
  // -------------------------------------------------------------
  const southZ = CONFIG.floorDepth / 2 + 0.25;
  const southParapet = new THREE.Mesh(new THREE.BoxGeometry(CONFIG.floorWidth + 1.2, 0.6, 0.4), trimMat);
  southParapet.position.set(0, 0.3, southZ);
  architectureGroup.add(southParapet);

  // Dual-rail tubular safety yellow handrail along south parapet
  createSafetyGuardrail(-CONFIG.floorWidth / 2, southZ, CONFIG.floorWidth / 2, southZ, true);

  // -------------------------------------------------------------
  // 5. SAFETY BOLLARDS & GUARDRAILS
  // -------------------------------------------------------------
  // Aisle rack row corner bollards (protects upright columns from forklift turning damage)
  const aisleXPositions = [-14, -6, 2, 10];
  aisleXPositions.forEach(ax => {
    createSafetyBollard(ax - 2.0, -17.0);
    createSafetyBollard(ax + 2.0, -17.0);
    createSafetyBollard(ax - 2.0,  17.0);
    createSafetyBollard(ax + 2.0,  17.0);
  });

  // Bollards protecting Loading Docks
  createSafetyBollard(westX + 1.2, -9.2);
  createSafetyBollard(westX + 1.2, -2.8);
  createSafetyBollard(westX + 1.2,  2.8);
  createSafetyBollard(westX + 1.2,  9.2);

  // Heavy-Duty Guardrails enclosing Central Dispatch Hub (Shelf 1 at x = -21, z = -1)
  const hubX = -21, hubZ = -1;
  createSafetyGuardrail(hubX - 4.5, hubZ - 4.0, hubX + 4.5, hubZ - 4.0); // North boundary
  createSafetyGuardrail(hubX - 4.5, hubZ + 4.0, hubX + 4.5, hubZ + 4.0); // South boundary
  createSafetyGuardrail(hubX - 4.5, hubZ - 4.0, hubX - 4.5, hubZ + 4.0); // West boundary
  createSafetyGuardrail(hubX + 4.5, hubZ - 4.0, hubX + 4.5, hubZ - 1.5); // East boundary (North half)
  createSafetyGuardrail(hubX + 4.5, hubZ + 1.5, hubX + 4.5, hubZ + 4.0); // East boundary (South half)

  // Bollards at the open dispatch entrance gate
  createSafetyBollard(hubX + 4.5, hubZ - 1.5);
  createSafetyBollard(hubX + 4.5, hubZ + 1.5);

  // -------------------------------------------------------------
  // 6. DETAILED INDUSTRIAL FLOOR MARKINGS
  // -------------------------------------------------------------
  buildFloorSafetyMarkings(hubX, hubZ);

  scene.add(architectureGroup);
}

/**
 * Builds an industrial loading dock portal with roll-up shutter doors,
 * rubber dock bumpers, status beacons, and exterior trailer staging.
 */
function buildLoadingDockPortal(wallX, centerZ, bayTitle, isOpen) {
  const portalGroup = new THREE.Group();
  portalGroup.position.set(wallX, 0, centerZ);

  const frameMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, metalness: 0.8, roughness: 0.3 });
  const hazardMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });

  // 1. Steel Portal Jambs (Left & Right)
  const jambGeo = new THREE.BoxGeometry(0.7, 5.2, 0.4);
  const jambL = new THREE.Mesh(jambGeo, frameMat);
  jambL.position.set(0, 2.6, -2.8);
  portalGroup.add(jambL);

  const jambR = new THREE.Mesh(jambGeo, frameMat);
  jambR.position.set(0, 2.6, 2.8);
  portalGroup.add(jambR);

  // Hazard Stripes on Portal Frame
  const stripeGeo = new THREE.BoxGeometry(0.72, 0.2, 0.42);
  [-2.8, 2.8].forEach(jz => {
    [1.0, 2.0, 3.0, 4.0].forEach(sy => {
      const stripe = new THREE.Mesh(stripeGeo, hazardMat);
      stripe.position.set(0, sy, jz);
      portalGroup.add(stripe);
    });
  });

  // Top Header Beam across Portal
  const headerGeo = new THREE.BoxGeometry(0.7, 0.4, 6.0);
  const header = new THREE.Mesh(headerGeo, frameMat);
  header.position.set(0, 5.0, 0);
  portalGroup.add(header);

  // 2. Heavy Molded Rubber Dock Bumpers
  const bumperMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.9 });
  const bumperGeo = new THREE.BoxGeometry(0.4, 0.9, 0.3);
  const bL = new THREE.Mesh(bumperGeo, bumperMat);
  bL.position.set(-0.35, 0.5, -2.8);
  portalGroup.add(bL);

  const bR = new THREE.Mesh(bumperGeo, bumperMat);
  bR.position.set(-0.35, 0.5, 2.8);
  portalGroup.add(bR);

  // 3. Roll-Up Shutter Door & Exterior Trailer
  if (isOpen) {
    // Partially open roll-up shutter (rolled up to 3.8m)
    const rolledSlatGeo = new THREE.BoxGeometry(0.12, 1.4, 5.2);
    const rolledSlatMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.85, roughness: 0.35 });
    const rolledSlats = new THREE.Mesh(rolledSlatGeo, rolledSlatMat);
    rolledSlats.position.set(0, 4.5, 0);
    portalGroup.add(rolledSlats);

    // Coiled Door Drum at top
    const drumGeo = new THREE.CylinderGeometry(0.35, 0.35, 5.3, 16);
    const drum = new THREE.Mesh(drumGeo, frameMat);
    drum.rotation.x = Math.PI / 2;
    drum.position.set(0, 5.2, 0);
    portalGroup.add(drum);

    // Exterior Concrete Loading Ramp
    const rampMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.6 });
    const ramp = new THREE.Mesh(new THREE.BoxGeometry(4.0, 0.2, 5.4), rampMat);
    ramp.position.set(-2.0, 0.1, 0);
    portalGroup.add(ramp);

    // Parked Delivery Truck Trailer (Rear visible at dock seal)
    const trailerGroup = new THREE.Group();
    trailerGroup.position.set(-4.2, 0, 0);

    const trailerBodyMat = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, metalness: 0.3, roughness: 0.4 });
    const trailerBody = new THREE.Mesh(new THREE.BoxGeometry(4.0, 3.8, 4.8), trailerBodyMat);
    trailerBody.position.set(0, 2.1, 0);
    trailerGroup.add(trailerBody);

    // Rear Conspicuity Tape (Red & White reflective bar)
    const conspicMat = new THREE.MeshBasicMaterial({ color: 0xef4444 });
    const conspicBar = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.15, 4.6), conspicMat);
    conspicBar.position.set(2.02, 0.65, 0);
    trailerGroup.add(conspicBar);

    portalGroup.add(trailerGroup);

    // Outdoor Sunlight Spill streaming into warehouse
    const dockSunlight = new THREE.SpotLight(0xfff7ed, 1.8, 16, Math.PI / 3.2, 0.6, 1.2);
    dockSunlight.position.set(-1.0, 4.8, 0);
    dockSunlight.target.position.set(7.0, 0, 0);
    portalGroup.add(dockSunlight);
    portalGroup.add(dockSunlight.target);

    // Dock Traffic Signal Beacon: Green "CLEAR / READY"
    const beaconGeo = new THREE.SphereGeometry(0.12, 16, 16);
    const beaconMat = new THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: 0x10b981,
      emissiveIntensity: 2.8,
      roughness: 0.1
    });
    const beacon = new THREE.Mesh(beaconGeo, beaconMat);
    beacon.position.set(0.42, 5.4, -2.8);
    portalGroup.add(beacon);

  } else {
    // Closed Sectional Roll-Up Door with Corrugated Horizontal Ribs
    const doorMat = new THREE.MeshStandardMaterial({
      color: 0x334155,
      metalness: 0.85,
      roughness: 0.3
    });
    const doorPanel = new THREE.Mesh(new THREE.BoxGeometry(0.12, 4.9, 5.2), doorMat);
    doorPanel.position.set(0, 2.45, 0);
    portalGroup.add(doorPanel);

    // Horizontal Steel Rib Lines across shutter door
    const ribMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, metalness: 0.9, roughness: 0.2 });
    for (let ry = 0.5; ry < 4.8; ry += 0.5) {
      const rib = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.04, 5.18), ribMat);
      rib.position.set(0, ry, 0);
      portalGroup.add(rib);
    }

    // Dock Traffic Signal Beacon: Red "BUSY / INBOUND"
    const beaconGeo = new THREE.SphereGeometry(0.12, 16, 16);
    const beaconMat = new THREE.MeshStandardMaterial({
      color: 0xef4444,
      emissive: 0xef4444,
      emissiveIntensity: 2.5,
      roughness: 0.1
    });
    const beacon = new THREE.Mesh(beaconGeo, beaconMat);
    beacon.position.set(0.42, 5.4, -2.8);
    portalGroup.add(beacon);
  }

  // Overhead Stenciled Dock Placard
  const signCanvas = document.createElement('canvas');
  signCanvas.width = 384;
  signCanvas.height = 80;
  const sCtx = signCanvas.getContext('2d');
  sCtx.fillStyle = '#0f172a';
  sCtx.fillRect(0, 0, 384, 80);
  sCtx.strokeStyle = isOpen ? '#10b981' : '#f59e0b';
  sCtx.lineWidth = 6;
  sCtx.strokeRect(4, 4, 376, 72);
  sCtx.fillStyle = '#ffffff';
  sCtx.font = 'bold 24px sans-serif';
  sCtx.textAlign = 'center';
  sCtx.textBaseline = 'middle';
  sCtx.fillText(bayTitle, 192, 40);

  const signTexture = new THREE.CanvasTexture(signCanvas);
  const signSpriteMat = new THREE.SpriteMaterial({ map: signTexture, transparent: true });
  const signSprite = new THREE.Sprite(signSpriteMat);
  signSprite.scale.set(3.4, 0.72, 1);
  signSprite.position.set(0.4, 5.6, 0);
  portalGroup.add(signSprite);

  architectureGroup.add(portalGroup);
}

/**
 * Creates heavy-duty yellow & black safety bollards at rack corners and dock entries.
 */
function createSafetyBollard(x, z) {
  const bollardGroup = new THREE.Group();
  bollardGroup.position.set(x, 0, z);

  // Steel Baseplate
  const baseMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.8 });
  const base = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.04, 0.38), baseMat);
  base.position.y = 0.02;
  bollardGroup.add(base);

  // Safety Yellow Steel Post
  const postMat = new THREE.MeshStandardMaterial({
    color: 0xfacc15,
    metalness: 0.45,
    roughness: 0.28
  });
  const post = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 1.15, 16), postMat);
  post.position.y = 0.6;
  post.castShadow = true;
  bollardGroup.add(post);

  // Reflective Black Hazard Bands
  const bandMat = new THREE.MeshBasicMaterial({ color: 0x0f172a });
  const bandGeo = new THREE.CylinderGeometry(0.135, 0.135, 0.08, 16);

  const band1 = new THREE.Mesh(bandGeo, bandMat);
  band1.position.y = 0.72;
  bollardGroup.add(band1);

  const band2 = new THREE.Mesh(bandGeo, bandMat);
  band2.position.y = 0.94;
  bollardGroup.add(band2);

  // Top Cap Dome
  const domeMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.5 });
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), domeMat);
  dome.position.y = 1.17;
  bollardGroup.add(dome);

  architectureGroup.add(bollardGroup);
  return bollardGroup;
}

/**
 * Creates dual-rail tubular safety steel guardrails with kickplates.
 */
function createSafetyGuardrail(x1, z1, x2, z2, isLow = false) {
  const railGroup = new THREE.Group();

  const dist = Math.hypot(x2 - x1, z2 - z1);
  if (dist < 0.2) return;

  const ang = Math.atan2(z2 - z1, x2 - x1);
  const mx = (x1 + x2) / 2;
  const mz = (z1 + z2) / 2;

  railGroup.position.set(mx, 0, mz);
  railGroup.rotation.y = -ang;

  const railMat = new THREE.MeshStandardMaterial({
    color: 0xf59e0b,
    metalness: 0.65,
    roughness: 0.3
  });
  const postMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, metalness: 0.8, roughness: 0.4 });

  const topHeight = isLow ? 0.9 : 1.1;
  const midHeight = isLow ? 0.45 : 0.6;

  // Top Tubular Rail
  const topRailGeo = new THREE.CylinderGeometry(0.038, 0.038, dist, 12);
  const topRail = new THREE.Mesh(topRailGeo, railMat);
  topRail.rotation.z = Math.PI / 2;
  topRail.position.y = topHeight;
  railGroup.add(topRail);

  // Mid Tubular Rail
  const midRailGeo = new THREE.CylinderGeometry(0.032, 0.032, dist, 12);
  const midRail = new THREE.Mesh(midRailGeo, railMat);
  midRail.rotation.z = Math.PI / 2;
  midRail.position.y = midHeight;
  railGroup.add(midRail);

  // Base Kickplate / Toe-board
  const kickGeo = new THREE.BoxGeometry(dist, 0.12, 0.03);
  const kick = new THREE.Mesh(kickGeo, postMat);
  kick.position.y = 0.08;
  railGroup.add(kick);

  // Vertical Posts spaced ~2.2m apart
  const numPosts = Math.max(2, Math.round(dist / 2.2) + 1);
  for (let i = 0; i < numPosts; i++) {
    const t = i / (numPosts - 1);
    const px = -dist / 2 + t * dist;

    const post = new THREE.Mesh(new THREE.BoxGeometry(0.06, topHeight + 0.04, 0.06), postMat);
    post.position.set(px, (topHeight + 0.04) / 2, 0);
    railGroup.add(post);

    // Anchor baseplate
    const plate = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.02, 0.18), postMat);
    plate.position.set(px, 0.01, 0);
    railGroup.add(plate);
  }

  architectureGroup.add(railGroup);
  return railGroup;
}

/**
 * Builds industrial floor safety markings:
 * - High-contrast yellow/black hazard apron around Dispatch Hub
 * - Dedicated green non-slip pedestrian walkway
 * - AGV directional floor arrows along main transit aisles
 * - Stenciled aisle row numbers on the floor
 */
function buildFloorSafetyMarkings(hubX, hubZ) {
  // 1. High-Contrast Hazard Zebra Border around Dispatch Apron
  const borderGroup = new THREE.Group();
  const stripeMat = new THREE.MeshBasicMaterial({ color: 0x0f172a }); // Black zebra stripes

  // Top & bottom hazard borders (x from hubX-4.6 to hubX+4.6)
  for (let x = hubX - 4.2; x <= hubX + 4.2; x += 0.8) {
    const s1 = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.005, 0.4), stripeMat);
    s1.position.set(x, 0.015, hubZ - 3.75);
    s1.rotation.y = Math.PI / 4;
    borderGroup.add(s1);

    const s2 = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.005, 0.4), stripeMat);
    s2.position.set(x, 0.015, hubZ + 3.75);
    s2.rotation.y = Math.PI / 4;
    borderGroup.add(s2);
  }
  architectureGroup.add(borderGroup);

  // 2. Green Non-Slip Pedestrian Safety Walkway (Connecting Dock to Packing)
  const walkwayMat = new THREE.MeshStandardMaterial({
    color: 0x064e3b, // Dark Forest Green Epoxy
    roughness: 0.5,
    metalness: 0.1
  });
  // Walkway strip running along z = -12 from West wall to East side
  const walkway = new THREE.Mesh(new THREE.PlaneGeometry(50, 1.4), walkwayMat);
  walkway.rotation.x = -Math.PI / 2;
  walkway.position.set(-6.0, 0.01, -12.0);
  architectureGroup.add(walkway);

  // Parallel Solid White Border Lines along Walkway
  const lineMat = new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 });
  [-12.7, -11.3].forEach(lz => {
    const pts = [new THREE.Vector3(-31, 0.012, lz), new THREE.Vector3(19, 0.012, lz)];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    architectureGroup.add(new THREE.Line(geo, lineMat));
  });

  // 3. AGV Floor Directional Arrows (Painted on main corridor floors)
  const arrowPositions = [
    { x: -14, z: -8,  ang: 0 },
    { x: -14, z:  8,  ang: 0 },
    { x:  -6, z: -8,  ang: Math.PI },
    { x:  -6, z:  8,  ang: Math.PI },
    { x:   2, z: -8,  ang: 0 },
    { x:   2, z:  8,  ang: 0 },
    { x:  10, z: -8,  ang: Math.PI },
    { x:  10, z:  8,  ang: Math.PI }
  ];

  arrowPositions.forEach(ap => {
    const arrowGroup = new THREE.Group();
    arrowGroup.position.set(ap.x, 0.012, ap.z);
    arrowGroup.rotation.y = ap.ang;

    const chevronMat = new THREE.MeshBasicMaterial({ color: 0xf1f5f9 });
    // Chevron shaft & head
    const shaft = new THREE.Mesh(new THREE.PlaneGeometry(0.2, 0.9), chevronMat);
    shaft.rotation.x = -Math.PI / 2;
    arrowGroup.add(shaft);

    const headL = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.55), chevronMat);
    headL.rotation.x = -Math.PI / 2;
    headL.rotation.z = Math.PI / 4;
    headL.position.set(-0.16, 0, 0.32);
    arrowGroup.add(headL);

    const headR = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.55), chevronMat);
    headR.rotation.x = -Math.PI / 2;
    headR.rotation.z = -Math.PI / 4;
    headR.position.set(0.16, 0, 0.32);
    arrowGroup.add(headR);

    architectureGroup.add(arrowGroup);
  });

  // 4. Stenciled Aisle Floor Row Numbers
  const aisleStencils = [
    { text: "AISLE 1", x: -14, z: -16.0 },
    { text: "AISLE 2", x:  -6, z: -16.0 },
    { text: "AISLE 3", x:   2, z: -16.0 },
    { text: "AISLE 4", x:  10, z: -16.0 }
  ];

  aisleStencils.forEach(st => {
    const sCanvas = document.createElement('canvas');
    sCanvas.width = 256;
    sCanvas.height = 64;
    const ctx = sCanvas.getContext('2d');
    ctx.fillStyle = 'rgba(0, 0, 0, 0)';
    ctx.fillRect(0, 0, 256, 64);
    ctx.fillStyle = '#f59e0b';
    ctx.font = 'bold 36px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(st.text, 128, 32);

    const texture = new THREE.CanvasTexture(sCanvas);
    const spriteMat = new THREE.MeshBasicMaterial({ map: texture, transparent: true });
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.6), spriteMat);
    plane.rotation.x = -Math.PI / 2;
    plane.position.set(st.x, 0.015, st.z);
    architectureGroup.add(plane);
  });
}

/**
 * Maps 2D floorplan coordinates (x, y) from backend to 3D world space (X, 0, Z).
 */
function mapCoordsTo3D(x2d, y2d) {
  const x3d = (x2d - 500) * CONFIG.scaleFactor;
  const z3d = (y2d - 280) * CONFIG.scaleFactor;
  return { x: x3d, z: z3d };
}

/**
 * Builds a realistic 3D Multi-Tier Industrial Pallet Rack for a shelf.
 */
function createPalletRackMesh(shelf, productsOnShelf) {
  const rackGroup = new THREE.Group();
  rackGroup.userData = {
    shelfId: shelf.id,
    shelf: shelf,
    products: productsOnShelf || [],
    isRack: true
  };

  const pos = mapCoordsTo3D(shelf.x, shelf.y);
  rackGroup.position.set(pos.x, 0, pos.z);

  const w = CONFIG.rackWidth;
  const d = CONFIG.rackDepth;
  const h = CONFIG.rackHeight;

  // Materials
  const uprightMat = new THREE.MeshStandardMaterial({
    color: 0x1e3a8a, // Industrial Blue
    roughness: 0.4,
    metalness: 0.6
  });

  const beamMat = new THREE.MeshStandardMaterial({
    color: 0xf97316, // Safety Orange
    roughness: 0.35,
    metalness: 0.5
  });

  const palletMat = new THREE.MeshStandardMaterial({
    color: 0xb58953, // Wood
    roughness: 0.9,
    metalness: 0.05
  });

  // 1. Four Upright Steel Columns
  const colRadius = 0.06;
  const colGeo = new THREE.BoxGeometry(colRadius * 2, h, colRadius * 2);
  const corners = [
    [-w / 2 + colRadius, -d / 2 + colRadius],
    [ w / 2 - colRadius, -d / 2 + colRadius],
    [-w / 2 + colRadius,  d / 2 - colRadius],
    [ w / 2 - colRadius,  d / 2 - colRadius]
  ];

  corners.forEach(([cx, cz]) => {
    const col = new THREE.Mesh(colGeo, uprightMat);
    col.position.set(cx, h / 2, cz);
    col.castShadow = true;
    col.receiveShadow = true;
    rackGroup.add(col);
  });

  // 2. Diagonal Cross-bracing on sides
  const braceMat = new THREE.MeshStandardMaterial({ color: 0x93c5fd, roughness: 0.5 });
  const braceGeo = new THREE.CylinderGeometry(0.02, 0.02, Math.hypot(d, h / 3));
  [-w / 2 + colRadius, w / 2 - colRadius].forEach(bx => {
    for (let t = 0; t < CONFIG.tiers; t++) {
      const brace = new THREE.Mesh(braceGeo, braceMat);
      brace.position.set(bx, (t + 0.5) * (h / CONFIG.tiers), 0);
      brace.rotation.x = Math.atan2(d, h / CONFIG.tiers) * (t % 2 === 0 ? 1 : -1);
      rackGroup.add(brace);
    }
  });

  // 3. Tiers with Horizontal Beams & Pallets
  const tierHeight = h / CONFIG.tiers;
  const beamGeoLong = new THREE.BoxGeometry(w, 0.09, 0.06);

  for (let t = 0; t < CONFIG.tiers; t++) {
    const yLevel = (t + 1) * tierHeight - 0.05;

    // Front & Back Beams
    const frontBeam = new THREE.Mesh(beamGeoLong, beamMat);
    frontBeam.position.set(0, yLevel, d / 2 - colRadius);
    frontBeam.castShadow = true;
    rackGroup.add(frontBeam);

    const backBeam = new THREE.Mesh(beamGeoLong, beamMat);
    backBeam.position.set(0, yLevel, -d / 2 + colRadius);
    backBeam.castShadow = true;
    rackGroup.add(backBeam);

    // Pallets and Stock Boxes
    const numPallets = 2;
    for (let p = 0; p < numPallets; p++) {
      const px = (p === 0 ? -1 : 1) * (w / 4);

      // Wooden Pallet
      const palletGeo = new THREE.BoxGeometry(w * 0.42, 0.1, d * 0.85);
      const pallet = new THREE.Mesh(palletGeo, palletMat);
      pallet.position.set(px, yLevel + 0.05, 0);
      pallet.castShadow = true;
      pallet.receiveShadow = true;
      rackGroup.add(pallet);

      // Boxes on Pallet (only if shelf has products)
      if (productsOnShelf && productsOnShelf.length > 0) {
        const prod = productsOnShelf[(t * 2 + p) % productsOnShelf.length];
        const boxColor = CATEGORY_COLORS[prod.category] || BOX_COLORS[p % BOX_COLORS.length];
        const boxMat = new THREE.MeshStandardMaterial({
          color: boxColor,
          roughness: 0.65,
          metalness: 0.1
        });

        // Stack boxes
        const boxGeo = new THREE.BoxGeometry(w * 0.36, 0.45, d * 0.7);
        const box = new THREE.Mesh(boxGeo, boxMat);
        box.position.set(px, yLevel + 0.33, 0);
        box.castShadow = true;
        box.receiveShadow = true;
        rackGroup.add(box);
      }
    }
  }

  // 4. Floating Shelf Label Plaque
  const plaqueCanvas = document.createElement('canvas');
  plaqueCanvas.width = 128;
  plaqueCanvas.height = 64;
  const ctx = plaqueCanvas.getContext('2d');
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, 128, 64);
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 124, 60);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 28px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(`S-${shelf.id}`, 64, 32);

  const plaqueTex = new THREE.CanvasTexture(plaqueCanvas);
  const plaqueMat = new THREE.MeshBasicMaterial({ map: plaqueTex, transparent: true });
  const plaqueGeo = new THREE.PlaneGeometry(1.0, 0.5);
  const plaque = new THREE.Mesh(plaqueGeo, plaqueMat);
  plaque.position.set(0, h + 0.3, 0);
  plaque.userData.isPlaque = true;
  rackGroup.add(plaque);
  rackGroup.userData.plaque = plaque;

  // Invisible Hitbox for precise raycasting
  const hitboxGeo = new THREE.BoxGeometry(w + 0.4, h + 0.8, d + 0.4);
  const hitboxMat = new THREE.MeshBasicMaterial({ visible: false });
  const hitbox = new THREE.Mesh(hitboxGeo, hitboxMat);
  hitbox.position.set(0, h / 2, 0);
  hitbox.userData = { parentRack: rackGroup, isHitbox: true };
  rackGroup.add(hitbox);
  rackGroup.userData.hitbox = hitbox;

  return rackGroup;
}

/**
 * Builds the Special 3D Packing & Dispatch Station Hub (Shelf 1).
 */
function createPackingStationMesh(shelf) {
  const stationGroup = new THREE.Group();
  stationGroup.userData = {
    shelfId: 1,
    shelf: shelf,
    products: [],
    isPackingHub: true,
    isRack: true
  };

  const pos = mapCoordsTo3D(shelf.x, shelf.y);
  stationGroup.position.set(pos.x, 0, pos.z);

  // 1. Dual Conveyor Belts
  const conveyorMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.4, metalness: 0.7 });
  const beltMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.95 });

  const conveyorFrame = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.7, 2.2), conveyorMat);
  conveyorFrame.position.set(0, 0.35, 0);
  conveyorFrame.castShadow = true;
  conveyorFrame.receiveShadow = true;
  stationGroup.add(conveyorFrame);

  const belt = new THREE.Mesh(new THREE.BoxGeometry(3.8, 0.05, 1.8), beltMat);
  belt.position.set(0, 0.72, 0);
  stationGroup.add(belt);

  // 2. Dispatch Roller Rollers
  const rollerMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.8, roughness: 0.3 });
  for (let r = -1.6; r <= 1.6; r += 0.4) {
    const roller = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 1.8), rollerMat);
    roller.rotation.x = Math.PI / 2;
    roller.position.set(r, 0.75, 0);
    stationGroup.add(roller);
  }

  // 3. Status Light Tower (Green Beacon)
  const poleMat = new THREE.MeshStandardMaterial({ color: 0x475569 });
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 3.2), poleMat);
  pole.position.set(1.9, 1.6, 0.9);
  stationGroup.add(pole);

  const beaconGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.3);
  const beaconMat = new THREE.MeshStandardMaterial({
    color: 0x22c55e,
    emissive: 0x16a34a,
    emissiveIntensity: 0.8
  });
  const beacon = new THREE.Mesh(beaconGeo, beaconMat);
  beacon.position.set(1.9, 3.2, 0.9);
  stationGroup.add(beacon);

  // 4. Floating Hub Signboard
  const signCanvas = document.createElement('canvas');
  signCanvas.width = 256;
  signCanvas.height = 80;
  const ctx = signCanvas.getContext('2d');
  ctx.fillStyle = '#065f46';
  ctx.fillRect(0, 0, 256, 80);
  ctx.strokeStyle = '#34d399';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 74);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 24px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('PACKING & DISPATCH', 128, 40);

  const signTex = new THREE.CanvasTexture(signCanvas);
  const signMat = new THREE.MeshBasicMaterial({ map: signTex, transparent: true });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.8), signMat);
  sign.position.set(0, 2.6, 0);
  stationGroup.add(sign);

  // Hitbox
  const hitbox = new THREE.Mesh(new THREE.BoxGeometry(4.8, 3.5, 2.8), new THREE.MeshBasicMaterial({ visible: false }));
  hitbox.position.set(0, 1.5, 0);
  hitbox.userData = { parentRack: stationGroup };
  stationGroup.add(hitbox);
  stationGroup.userData.hitbox = hitbox;

  return stationGroup;
}

/**
 * Draws 3D laser-lit corridor routes connecting shelves based on Dijkstra graph edges.
 */
function renderCorridorEdges(edges, nodes) {
  corridorLinesGroup.clear();
  const nodeMap = new Map();
  nodes.forEach(n => nodeMap.set(n.id, mapCoordsTo3D(n.x, n.y)));

  const lineMat = new THREE.LineBasicMaterial({
    color: 0x0284c7,
    transparent: true,
    opacity: 0.45,
    linewidth: 2
  });

  edges.forEach(edge => {
    const from = nodeMap.get(edge.from_shelf_id);
    const to = nodeMap.get(edge.to_shelf_id);
    if (!from || !to) return;

    const points = [
      new THREE.Vector3(from.x, 0.05, from.z),
      new THREE.Vector3(to.x, 0.05, to.z)
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geo, lineMat);
    corridorLinesGroup.add(line);
  });
}

/**
 * Loads live data from backend APIs and assembles the 3D warehouse.
 */
async function loadWarehouseData() {
  showLoadingSpinner(true);
  try {
    const [shelvesRes, productsRes, graphRes] = await Promise.all([
      fetch('/api/shelves').then(r => r.json()),
      fetch('/api/products').then(r => r.json()),
      fetch('/api/warehouse/graph').then(r => r.json())
    ]);

    warehouseData.shelves = shelvesRes || [];
    warehouseData.products = productsRes || [];
    warehouseData.graph = graphRes || { nodes: [], edges: [] };

    // Group products by assigned shelf
    const productsByShelf = new Map();
    warehouseData.products.forEach(p => {
      const sid = p.assigned_shelf_id;
      if (!productsByShelf.has(sid)) productsByShelf.set(sid, []);
      productsByShelf.get(sid).push(p);
    });

    // Clear existing rack meshes
    rackMeshes.forEach(mesh => scene.remove(mesh));
    rackMeshes.clear();

    // Spawn 3D Racks
    warehouseData.shelves.forEach(shelf => {
      let mesh;
      if (shelf.id === 1) {
        mesh = createPackingStationMesh(shelf);
      } else {
        mesh = createPalletRackMesh(shelf, productsByShelf.get(shelf.id));
      }
      scene.add(mesh);
      rackMeshes.set(shelf.id, mesh);
    });

    // Render Corridor network
    if (warehouseData.graph.edges && warehouseData.graph.nodes) {
      renderCorridorEdges(warehouseData.graph.edges, warehouseData.graph.nodes);
    }

    // Populate category dropdown and UI telemetry
    populateCategoryFilter();
    updateWarehouseTelemetry();

    // Select shelf 1 by default
    selectShelf(1);

  } catch (err) {
    console.error('Failed to load warehouse 3D data:', err);
    showToast('Failed to load warehouse 3D data from server', 'error');
  } finally {
    showLoadingSpinner(false);
  }
}

/**
 * Updates UI telemetry stats in top status banner.
 */
function updateWarehouseTelemetry() {
  const elBays = document.getElementById('stat-total-bays');
  const elSkus = document.getElementById('stat-total-skus');
  const elCorridors = document.getElementById('stat-corridors');

  if (elBays) elBays.textContent = warehouseData.shelves.length;
  if (elSkus) elSkus.textContent = warehouseData.products.length;
  if (elCorridors) elCorridors.textContent = warehouseData.graph.edges ? warehouseData.graph.edges.length : 32;
}

/**
 * Populates category filter dropdown dynamically.
 */
function populateCategoryFilter() {
  const select = document.getElementById('filter-category');
  if (!select) return;

  const categories = new Set(warehouseData.products.map(p => p.category).filter(Boolean));
  select.innerHTML = '<option value="ALL">All Categories (60 SKUs)</option>';
  categories.forEach(cat => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = `${cat}`;
    select.appendChild(opt);
  });
}

/**
 * Filters and highlights racks containing products in the chosen category.
 */
function onCategoryFilterChange() {
  const select = document.getElementById('filter-category');
  const selectedCat = select ? select.value : 'ALL';

  rackMeshes.forEach((mesh, shelfId) => {
    if (shelfId === 1) return; // Keep packing hub always visible

    if (selectedCat === 'ALL') {
      mesh.traverse(child => {
        if (child.isMesh && child !== mesh.userData.hitbox) {
          child.material.opacity = 1.0;
          child.material.transparent = false;
        }
      });
      return;
    }

    const hasCat = mesh.userData.products.some(p => p.category === selectedCat);
    mesh.traverse(child => {
      if (child.isMesh && child !== mesh.userData.hitbox) {
        if (hasCat) {
          child.material.transparent = false;
          child.material.opacity = 1.0;
        } else {
          child.material.transparent = true;
          child.material.opacity = 0.2;
        }
      }
    });
  });
}

/**
 * Raycasting Mouse Move Event (Hover detection).
 */
function onMouseMove(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);

  const hitboxes = [];
  rackMeshes.forEach(mesh => {
    if (mesh.userData.hitbox) hitboxes.push(mesh.userData.hitbox);
  });

  const intersects = raycaster.intersectObjects(hitboxes);

  if (intersects.length > 0) {
    const parentRack = intersects[0].object.userData.parentRack;
    if (hoveredRack !== parentRack) {
      if (hoveredRack && hoveredRack.userData.shelfId !== selectedShelfId) {
        unhighlightRack(hoveredRack);
      }
      hoveredRack = parentRack;
      if (!heatmapActive) {
        highlightRack(hoveredRack, 0x38bdf8);
      }
      renderer.domElement.style.cursor = 'pointer';
    }
    if (heatmapActive && parentRack) {
      updateHeatmapTooltip(parentRack.userData.shelfId, event.clientX, event.clientY);
    }
  } else {
    if (hoveredRack && hoveredRack.userData.shelfId !== selectedShelfId) {
      unhighlightRack(hoveredRack);
    }
    hoveredRack = null;
    renderer.domElement.style.cursor = 'default';
    if (heatmapActive) {
      hideHeatmapTooltip();
    }
  }
}

/**
 * Raycasting Mouse Click Event (Selection).
 */
function onMouseClick(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);

  const hitboxes = [];
  rackMeshes.forEach(mesh => {
    if (mesh.userData.hitbox) hitboxes.push(mesh.userData.hitbox);
  });

  const intersects = raycaster.intersectObjects(hitboxes);

  if (intersects.length > 0) {
    const parentRack = intersects[0].object.userData.parentRack;
    selectShelf(parentRack.userData.shelfId);
  }
}

/**
 * Visual highlight for selected/hovered rack.
 */
function highlightRack(rackMesh, colorHex = 0xf59e0b) {
  if (!rackMesh) return;
  rackMesh.traverse(child => {
    if (child.isMesh && child.material && child !== rackMesh.userData.hitbox) {
      if (!child.userData.origEmissive) {
        child.userData.origEmissive = child.material.emissive ? child.material.emissive.getHex() : 0x000000;
      }
      if (child.material.emissive) {
        child.material.emissive.setHex(colorHex);
        child.material.emissiveIntensity = 0.55;
      }
    }
  });
}

function unhighlightRack(rackMesh) {
  if (!rackMesh) return;
  rackMesh.traverse(child => {
    if (child.isMesh && child.material && child.material.emissive) {
      child.material.emissive.setHex(child.userData.origEmissive || 0x000000);
      child.material.emissiveIntensity = 0;
    }
  });
}

/**
 * Selects a shelf and updates the detailed side Inspector HUD.
 */
function selectShelf(shelfId) {
  if (selectedShelfId && rackMeshes.has(selectedShelfId)) {
    unhighlightRack(rackMeshes.get(selectedShelfId));
  }

  selectedShelfId = shelfId;
  const rackMesh = rackMeshes.get(shelfId);
  if (rackMesh) {
    highlightRack(rackMesh, 0xf59e0b); // Gold glow for selected
  }

  updateInspectorHUD(shelfId);
}

/**
 * Updates the Inspector Drawer / Modal with live shelf details and products.
 */
function updateInspectorHUD(shelfId) {
  const shelf = warehouseData.shelves.find(s => s.id === shelfId);
  if (!shelf) return;

  const products = warehouseData.products.filter(p => p.assigned_shelf_id === shelfId);

  // Set IDs & Labels
  document.getElementById('hud-shelf-title').textContent = shelf.id === 1 ? 'Dispatch Hub (Shelf 1)' : `Storage Rack Bay S-${shelf.id}`;
  document.getElementById('hud-shelf-badge').textContent = shelf.id === 1 ? 'PACKING STATION' : (shelf.id <= 6 ? 'AISLE 1' : shelf.id <= 12 ? 'AISLE 2' : shelf.id <= 18 ? 'AISLE 3' : 'AISLE 4');
  document.getElementById('hud-dist-val').textContent = `${parseFloat(shelf.distance_to_packing || 0).toFixed(1)} m`;

  // Capacity Load Meter
  const capacity = shelf.capacity || 100;
  const load = shelf.current_load || (products.reduce((acc, p) => acc + (p.stock_quantity || 0), 0));
  const loadPct = Math.min(100, Math.round((load / capacity) * 100));

  const hudLoadVal = document.getElementById('hud-load-val');
  const hudLoadBar = document.getElementById('hud-load-bar');
  if (hudLoadVal) hudLoadVal.textContent = `${load} / ${capacity} units (${loadPct}%)`;
  if (hudLoadBar) {
    hudLoadBar.style.width = `${loadPct}%`;
    hudLoadBar.style.background = loadPct > 85 ? '#ef4444' : loadPct > 60 ? '#f59e0b' : '#10b981';
  }

  // Thermal Activity Heatmap Section in Inspector
  const analyticsContainer = document.getElementById('hud-heatmap-analytics');
  if (analyticsContainer) {
    if (shelf.id === 1) {
      analyticsContainer.innerHTML = '';
    } else {
      const metrics = computeWarehouseHeatmapMetrics();
      const score = metrics.shelfScores.get(shelfId);
      if (score) {
        const thermal = getThermalColorData(score.value, metrics.minVal, metrics.maxVal);
        const metricValText = heatmapMetric === 'velocity' ? `${Math.round(score.value).toLocaleString()} picks/yr` : `${score.value}% capacity`;
        analyticsContainer.innerHTML = `
          <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 8px; padding: 10px; margin: 10px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 700; font-size: 0.8rem; color: #fbbf24;">Thermal Zone:</span>
              <span style="background: ${thermal.css}; color: #ffffff; font-weight: 700; font-size: 0.72rem; padding: 2px 7px; border-radius: 4px;">${thermal.zone}</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 3px;">
              <span>${heatmapMetric === 'velocity' ? 'Pick Velocity' : 'Load Level'}:</span>
              <strong style="color: var(--text-main);">${metricValText} (${score.percentile}th %)</strong>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;">
              <span>Golden Zone Position:</span>
              <strong style="color: ${score.isGoldenZone ? '#10b981' : '#94a3b8'};">${score.isGoldenZone ? '★ YES (Prime Proximity)' : 'Standard Bay'}</strong>
            </div>
            <div style="font-size: 0.72rem; color: ${score.adviceColor}; line-height: 1.35; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.08);">
              ${score.advice}
            </div>
          </div>
        `;
      }
    }
  }

  // Product List
  const prodListContainer = document.getElementById('hud-products-list');
  if (!prodListContainer) return;

  if (shelf.id === 1) {
    prodListContainer.innerHTML = `
      <div style="padding: 1rem; text-align: center; color: var(--text-dim);">
        <p><strong>Central Dispatch & Packing Hub</strong></p>
        <p style="font-size: 0.85rem; margin-top: 0.4rem;">All picker routes begin and conclude here. Orders are packed, weighed, and sorted for carrier pickup.</p>
      </div>
    `;
    return;
  }

  if (products.length === 0) {
    prodListContainer.innerHTML = `
      <div style="padding: 1rem; text-align: center; color: var(--text-dim); font-size: 0.88rem;">
        No active SKUs assigned to this bay. Slot products from the <a href="layout.html" style="color: var(--primary);">Layout Optimizer</a>.
      </div>
    `;
    return;
  }

  prodListContainer.innerHTML = products.map(prod => `
    <div class="hud-product-item">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem;">
        <div>
          <div style="font-weight: 700; font-size: 0.9rem; color: var(--text-main);">${escapeHtml(prod.name)}</div>
          <div style="font-size: 0.78rem; color: var(--text-dim); margin-top: 2px;">SKU #${prod.id}</div>
        </div>
        <span class="category-pill ${prod.category ? prod.category.toLowerCase() : ''}">${escapeHtml(prod.category || 'Standard')}</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-top: 0.5rem; color: var(--text-dim);">
        <span>Stock: <strong style="color: var(--text-main);">${prod.stock_quantity || 0}</strong> units</span>
        <span>Pick Velocity: <strong style="color: #f59e0b;">${Math.round(prod.pick_frequency || 0)}</strong>/mo</span>
      </div>
    </div>
  `).join('');
}

/**
 * Camera View Angle Presets.
 */
function setCameraView(preset) {
  if (!camera || !controls) return;

  const target = new THREE.Vector3(0, 1.5, 0);
  controls.target.copy(target);

  switch (preset) {
    case 'isometric':
      smoothCameraMove(new THREE.Vector3(28, 30, 38), target);
      break;
    case 'topdown':
      smoothCameraMove(new THREE.Vector3(0, 56, 0.1), target);
      break;
    case 'front':
      smoothCameraMove(new THREE.Vector3(0, 12, 45), target);
      break;
    case 'dispatch':
      const hubPos = mapCoordsTo3D(80, 260);
      const hubTarget = new THREE.Vector3(hubPos.x, 1.5, hubPos.z);
      controls.target.copy(hubTarget);
      smoothCameraMove(new THREE.Vector3(hubPos.x + 8, 8, hubPos.z + 14), hubTarget);
      selectShelf(1);
      break;
    default:
      smoothCameraMove(new THREE.Vector3(28, 30, 38), target);
  }
}

/**
 * Smooth transition for camera navigation.
 */
function smoothCameraMove(targetPos, targetLookAt) {
  const startPos = camera.position.clone();
  const startLookAt = controls.target.clone();
  let progress = 0;

  function step() {
    progress += 0.05;
    if (progress <= 1) {
      camera.position.lerpVectors(startPos, targetPos, easeInOutCubic(progress));
      controls.target.lerpVectors(startLookAt, targetLookAt, easeInOutCubic(progress));
      controls.update();
      requestAnimationFrame(step);
    } else {
      camera.position.copy(targetPos);
      controls.target.copy(targetLookAt);
      controls.update();
    }
  }
  step();
}

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/**
 * Toggles Dijkstra Corridor Network lines visibility in 3D.
 */
function toggleCorridors(enabled) {
  if (corridorLinesGroup) corridorLinesGroup.visible = enabled;
}

/**
 * Animation loop.
 */
/**
 * Animation loop supporting both Cinematic Bloom (EffectComposer) and Standard WebGLRenderer.
 */
function animate() {
  animationFrameId = requestAnimationFrame(animate);
  const dt = Math.min(agvAnimClock.getDelta(), 0.1);
  if (controls) controls.update();
  if (typeof updateAGVAnimation === 'function') {
    updateAGVAnimation(dt);
  }
  if (typeof updateHeatmapAnimation === 'function') {
    updateHeatmapAnimation(dt);
  }
  
  if (bloomActive && composer) {
    composer.render();
  } else if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}

/**
 * Handles window resize for Camera, Renderer, and Post-Processing Composer.
 */
function onWindowResize() {
  const container = document.getElementById('canvas-container');
  if (!container || !renderer || !camera) return;

  const width = container.clientWidth;
  const height = container.clientHeight;

  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
  if (composer) {
    composer.setSize(width, height);
    if (bloomPass) {
      bloomPass.resolution.set(width, height);
    }
  }
}

/**
 * Search functionality: finds rack by Shelf ID or SKU Name.
 */
function searchWarehouse() {
  const query = (document.getElementById('search-input')?.value || '').trim().toLowerCase();
  if (!query) return;

  // Check if shelf number entered
  const shelfNum = parseInt(query.replace(/[^0-9]/g, ''));
  if (!isNaN(shelfNum) && rackMeshes.has(shelfNum)) {
    focusOnShelf(shelfNum);
    return;
  }

  // Check product name / category match
  const matchedProd = warehouseData.products.find(p =>
    p.name.toLowerCase().includes(query) ||
    (p.category && p.category.toLowerCase().includes(query)) ||
    String(p.id) === query
  );

  if (matchedProd && matchedProd.assigned_shelf_id && rackMeshes.has(matchedProd.assigned_shelf_id)) {
    focusOnShelf(matchedProd.assigned_shelf_id);
    showToast(`Found "${matchedProd.name}" on Bay S-${matchedProd.assigned_shelf_id}`, 'success');
  } else {
    showToast('No matching shelf or SKU found', 'warning');
  }
}

/**
 * Smoothly pans camera to focus on a specific shelf.
 */
function focusOnShelf(shelfId) {
  const mesh = rackMeshes.get(shelfId);
  if (!mesh) return;

  selectShelf(shelfId);
  const targetPos = new THREE.Vector3(mesh.position.x, 1.5, mesh.position.z);
  const camPos = new THREE.Vector3(mesh.position.x + 9, 7, mesh.position.z + 12);
  controls.target.copy(targetPos);
  smoothCameraMove(camPos, targetPos);
}

/**
 * Helper UI functions.
 */
function showLoadingSpinner(show) {
  const el = document.getElementById('loading-overlay');
  if (el) el.style.display = show ? 'flex' : 'none';
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container') || createToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

function createToastContainer() {
  const c = document.createElement('div');
  c.id = 'toast-container';
  c.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
  document.body.appendChild(c);
  return c;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[m]));
}

// ==============================================================================
// 3D AGV / FORKLIFT ROUTE SIMULATION ENGINE
// ==============================================================================

/**
 * Creates high-detail procedural 3D industrial AGV forklift.
 */
function createAGVMesh() {
  const group = new THREE.Group();
  group.name = "AGV_Forklift";

  // Materials
  const chassisMat = new THREE.MeshStandardMaterial({
    color: 0xf59e0b, // Safety Amber/Yellow
    metalness: 0.5,
    roughness: 0.35
  });
  const darkTrimMat = new THREE.MeshStandardMaterial({
    color: 0x1e293b, // Dark Slate Steel
    metalness: 0.6,
    roughness: 0.4
  });
  const chromeMat = new THREE.MeshStandardMaterial({
    color: 0x94a3b8, // Mast Chrome
    metalness: 0.9,
    roughness: 0.15
  });
  const rubberMat = new THREE.MeshStandardMaterial({
    color: 0x0f172a, // Tire Rubber
    roughness: 0.85
  });
  const rimMat = new THREE.MeshStandardMaterial({
    color: 0xcbd5e1,
    metalness: 0.8,
    roughness: 0.3
  });

  // 1. Lower Chassis
  const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.45, 1.8), chassisMat);
  chassis.position.set(0, 0.32, -0.05);
  chassis.castShadow = true;
  chassis.receiveShadow = true;
  group.add(chassis);

  // Black bumper guards
  const bumperF = new THREE.Mesh(new THREE.BoxGeometry(1.26, 0.18, 0.15), darkTrimMat);
  bumperF.position.set(0, 0.18, 0.85);
  group.add(bumperF);

  const bumperB = new THREE.Mesh(new THREE.BoxGeometry(1.26, 0.18, 0.15), darkTrimMat);
  bumperB.position.set(0, 0.18, -0.95);
  group.add(bumperB);

  // 2. Wheels (Rolling animated)
  agvWheels = [];
  const wheelRadius = 0.18;
  const wheelThickness = 0.12;
  const wheelGeo = new THREE.CylinderGeometry(wheelRadius, wheelRadius, wheelThickness, 24);
  const rimGeo = new THREE.CylinderGeometry(wheelRadius * 0.55, wheelRadius * 0.55, wheelThickness + 0.01, 16);

  const wheelPositions = [
    [-0.58, wheelRadius,  0.55],
    [ 0.58, wheelRadius,  0.55],
    [-0.58, wheelRadius, -0.65],
    [ 0.58, wheelRadius, -0.65]
  ];

  wheelPositions.forEach(([wx, wy, wz]) => {
    const wheelGroup = new THREE.Group();
    wheelGroup.position.set(wx, wy, wz);

    const tire = new THREE.Mesh(wheelGeo, rubberMat);
    tire.rotation.z = Math.PI / 2;
    tire.castShadow = true;
    wheelGroup.add(tire);

    const rim = new THREE.Mesh(rimGeo, rimMat);
    rim.rotation.z = Math.PI / 2;
    wheelGroup.add(rim);

    group.add(wheelGroup);
    agvWheels.push(wheelGroup);
  });

  // 3. Roll-Cage / Operator Cabin
  const colGeo = new THREE.CylinderGeometry(0.025, 0.025, 1.25);
  const cageCorners = [
    [-0.45, -0.15],
    [ 0.45, -0.15],
    [-0.45, -0.75],
    [ 0.45, -0.75]
  ];
  cageCorners.forEach(([cx, cz]) => {
    const post = new THREE.Mesh(colGeo, darkTrimMat);
    post.position.set(cx, 1.15, cz);
    group.add(post);
  });

  // Overhead roof
  const roof = new THREE.Mesh(new THREE.BoxGeometry(0.96, 0.04, 0.7), darkTrimMat);
  roof.position.set(0, 1.78, -0.45);
  group.add(roof);

  // Seat / Battery compartment
  const batteryBox = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.45, 0.6), darkTrimMat);
  batteryBox.position.set(0, 0.72, -0.45);
  group.add(batteryBox);

  // 4. Chrome Mast Rails
  const mastRailGeo = new THREE.BoxGeometry(0.08, 1.7, 0.08);
  const mastL = new THREE.Mesh(mastRailGeo, chromeMat);
  mastL.position.set(-0.35, 1.05, 0.88);
  group.add(mastL);

  const mastR = new THREE.Mesh(mastRailGeo, chromeMat);
  mastR.position.set(0.35, 1.05, 0.88);
  group.add(mastR);

  const mastCross = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.06, 0.06), chromeMat);
  mastCross.position.set(0, 1.85, 0.88);
  group.add(mastCross);

  // 5. Movable Fork Carriage
  agvForkCarriage = new THREE.Group();
  agvForkCarriage.position.set(0, 0.22, 0.92);

  const carriageBack = new THREE.Mesh(new THREE.BoxGeometry(0.82, 0.25, 0.06), darkTrimMat);
  carriageBack.position.set(0, 0.12, 0);
  agvForkCarriage.add(carriageBack);

  // Steel Fork Tines
  const forkMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.85, roughness: 0.25 });
  const tineGeo = new THREE.BoxGeometry(0.09, 0.04, 0.85);

  const tineL = new THREE.Mesh(tineGeo, forkMat);
  tineL.position.set(-0.25, 0.02, 0.42);
  agvForkCarriage.add(tineL);

  const tineR = new THREE.Mesh(tineGeo, forkMat);
  tineR.position.set(0.25, 0.02, 0.42);
  agvForkCarriage.add(tineR);

  // Wooden Pallet on Forks
  const palletMat = new THREE.MeshStandardMaterial({ color: 0xb45309, roughness: 0.9 });
  const pallet = new THREE.Mesh(new THREE.BoxGeometry(0.68, 0.06, 0.65), palletMat);
  pallet.position.set(0, 0.07, 0.42);
  pallet.castShadow = true;
  agvForkCarriage.add(pallet);

  // Cargo Boxes Container
  agvPalletBoxes = [];
  const boxesGroup = new THREE.Group();
  boxesGroup.name = "AGV_Cargo_Boxes";
  agvForkCarriage.add(boxesGroup);
  agvForkCarriage.userData.boxesGroup = boxesGroup;

  group.add(agvForkCarriage);

  // 6. Amber Safety Beacon
  const beaconDomeMat = new THREE.MeshStandardMaterial({
    color: 0xf59e0b,
    emissive: 0xf59e0b,
    emissiveIntensity: 0.9,
    roughness: 0.2
  });
  agvBeacon = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.14, 16), beaconDomeMat);
  agvBeacon.position.set(0, 1.88, -0.45);
  group.add(agvBeacon);

  agvBeaconLight = new THREE.PointLight(0xf59e0b, 1.5, 6);
  agvBeaconLight.position.set(0, 2.0, -0.45);
  group.add(agvBeaconLight);

  // 7. LED Headlights & Volumetric Light Cones
  const headLightMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0xfffbeb,
    emissiveIntensity: 2.8,
    roughness: 0.1
  });
  const headL = new THREE.Mesh(new THREE.CircleGeometry(0.06, 16), headLightMat);
  headL.position.set(-0.45, 0.48, 0.86);
  group.add(headL);

  const headR = new THREE.Mesh(new THREE.CircleGeometry(0.06, 16), headLightMat);
  headR.position.set(0.45, 0.48, 0.86);
  group.add(headR);

  // Volumetric Headlight Beams (Semi-transparent additive cones)
  const coneGeo = new THREE.ConeGeometry(0.55, 4.0, 16, 1, true);
  const coneMat = new THREE.MeshBasicMaterial({
    color: 0xfff7ed,
    transparent: true,
    opacity: 0.14,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    depthWrite: false
  });
  const beamL = new THREE.Mesh(coneGeo, coneMat);
  beamL.rotation.x = Math.PI / 2;
  beamL.position.set(-0.45, 0.48, 2.86);
  group.add(beamL);

  const beamR = new THREE.Mesh(coneGeo, coneMat);
  beamR.rotation.x = Math.PI / 2;
  beamR.position.set(0.45, 0.48, 2.86);
  group.add(beamR);

  const headBeam = new THREE.SpotLight(0xfffbeb, 2.5, 22, Math.PI / 4, 0.6, 1.2);
  headBeam.position.set(0, 0.5, 0.85);
  headBeam.target.position.set(0, 0, 8.0);
  group.add(headBeam);
  group.add(headBeam.target);

  // 8. Tail Lights
  const tailMat = new THREE.MeshBasicMaterial({ color: 0xef4444 });
  const tailL = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.06, 0.02), tailMat);
  tailL.position.set(-0.45, 0.45, -0.96);
  group.add(tailL);

  const tailR = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.06, 0.02), tailMat);
  tailR.position.set(0.45, 0.45, -0.96);
  group.add(tailR);

  // 9. Floating 3D Tag
  agvStatusSprite = createAGVSpriteTag("AGV-01: READY");
  agvStatusSprite.position.set(0, 2.35, 0);
  group.add(agvStatusSprite);

  group.scale.set(1.15, 1.15, 1.15);
  return group;
}

function createAGVSpriteTag(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  
  ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 4;
  drawRoundRect(ctx, 4, 4, 248, 56, 12, true, true);
  
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 20px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 32);

  const texture = new THREE.CanvasTexture(canvas);
  const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.set(2.4, 0.6, 1);
  sprite.userData = { canvas, ctx, texture };
  return sprite;
}

function updateAGVSpriteText(text, subColor = '#f59e0b') {
  if (!agvStatusSprite || !agvStatusSprite.userData || !agvStatusSprite.userData.canvas) return;
  const { canvas, ctx, texture } = agvStatusSprite.userData;
  ctx.clearRect(0, 0, 256, 64);
  
  ctx.fillStyle = 'rgba(15, 23, 42, 0.92)';
  ctx.strokeStyle = subColor;
  ctx.lineWidth = 4;
  drawRoundRect(ctx, 4, 4, 248, 56, 12, true, true);

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 20px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 32);
  texture.needsUpdate = true;
}

function createStopBadgeSprite(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 160;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  
  ctx.fillStyle = '#10b981';
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 4;
  drawRoundRect(ctx, 4, 4, 152, 56, 12, true, true);

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 22px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 80, 32);

  const texture = new THREE.CanvasTexture(canvas);
  const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(spriteMat);
  sprite.scale.set(1.6, 0.64, 1);
  return sprite;
}

function drawRoundRect(ctx, x, y, width, height, radius, fill, stroke) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
  ctx.lineTo(x + width, y + height - radius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  ctx.lineTo(x + radius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
  if (fill) ctx.fill();
  if (stroke) ctx.stroke();
}

/**
 * Loads order route into 3D Digital Twin and prepares animated AGV simulation.
 */
function loadRouteIn3DTwin(routeData) {
  if (!scene || !routeData || !routeData.full_path || routeData.full_path.length < 2) return;

  const nodeMap = new Map();
  if (warehouseData.graph && warehouseData.graph.nodes) {
    warehouseData.graph.nodes.forEach(n => nodeMap.set(n.id, n));
  }
  if (warehouseData.shelves) {
    warehouseData.shelves.forEach(s => {
      if (!nodeMap.has(s.id)) nodeMap.set(s.id, s);
    });
  }

  agvWaypoints = [];
  const stopsSet = new Set((routeData.stops || []).map(s => Number(s)));
  
  routeData.full_path.forEach((nodeId, idx) => {
    const n = nodeMap.get(Number(nodeId));
    if (n) {
      const pos3D = mapCoordsTo3D(n.x, n.y);
      const isPickStop = (idx > 0 && idx < routeData.full_path.length - 1 && stopsSet.has(Number(nodeId)));
      
      let matchedItem = null;
      if (isPickStop && routeData.items) {
        matchedItem = routeData.items.find(it => Number(it.shelf_id) === Number(nodeId));
      }

      agvWaypoints.push({
        x: pos3D.x,
        z: pos3D.z,
        nodeId: Number(nodeId),
        shelfId: Number(nodeId),
        isStop: isPickStop,
        item: matchedItem
      });
    }
  });

  if (agvWaypoints.length < 2) {
    console.warn("Could not map route waypoints in 3D");
    return;
  }

  // Calculate cumulative path distances
  let cumulative = 0;
  agvWaypoints[0].distFromStart = 0;
  for (let i = 1; i < agvWaypoints.length; i++) {
    const d = Math.hypot(agvWaypoints[i].x - agvWaypoints[i-1].x, agvWaypoints[i].z - agvWaypoints[i-1].z);
    cumulative += d;
    agvWaypoints[i].distFromStart = cumulative;
  }
  agvAnimState.totalDistance = cumulative;

  // Spawn or activate AGV
  if (!agvGroup) {
    agvGroup = createAGVMesh();
    scene.add(agvGroup);
  }
  agvGroup.visible = true;

  const startPt = agvWaypoints[0];
  const nextPt = agvWaypoints[1];
  agvGroup.position.set(startPt.x, 0.02, startPt.z);
  agvGroup.rotation.y = Math.atan2(nextPt.x - startPt.x, nextPt.z - startPt.z);

  // Clear previous boxes from pallet
  if (agvForkCarriage && agvForkCarriage.userData.boxesGroup) {
    agvForkCarriage.userData.boxesGroup.clear();
  }
  agvPalletBoxes = [];

  // Reset State
  agvAnimState.active = true;
  agvAnimState.playing = true;
  agvAnimState.completed = false;
  agvAnimState.currentSegmentIndex = 0;
  agvAnimState.segmentProgress = 0.0;
  agvAnimState.isPicking = false;
  agvAnimState.pickTimer = 0.0;
  agvAnimState.visitedStopSet = new Set();
  agvAnimState.orderData = routeData;
  agvAnimState.totalStops = routeData.stop_count || agvWaypoints.filter(w => w.isStop).length;

  // Render 3D Route Laser Line & Stop Markers
  render3DRouteVisuals(routeData);

  // Ensure Playback HUD is visible and updated
  ensurePlaybackHUD();
  updatePlaybackUI();

  // Focus camera towards route start with smooth transition
  smoothCameraMove(
    new THREE.Vector3(startPt.x + 12, 14, startPt.z + 16),
    new THREE.Vector3(startPt.x, 1.5, startPt.z)
  );

  showToast(`Simulating 3D AGV Picking Route for Order #${routeData.order_id || ''}`, "info");
}

/**
 * Draws 3D laser corridor route line and floating shelf stop badges.
 */
function render3DRouteVisuals(routeData) {
  if (!routeMarkersGroup) {
    routeMarkersGroup = new THREE.Group();
    scene.add(routeMarkersGroup);
  }
  routeMarkersGroup.clear();

  if (agvWaypoints.length < 2) return;

  // 1. Glowing Cyan Floor Line
  const points = agvWaypoints.map(w => new THREE.Vector3(w.x, 0.06, w.z));
  const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
  const lineMat = new THREE.LineBasicMaterial({
    color: 0x06b6d4, // Cyan
    linewidth: 3,
    transparent: true,
    opacity: 0.85
  });
  const routeLine = new THREE.Line(lineGeo, lineMat);
  routeMarkersGroup.add(routeLine);

  // 2. Shelf Stop Rings & Stop Badges
  let stopCounter = 1;
  agvWaypoints.forEach(w => {
    if (w.isStop) {
      // Emerald glowing ring on floor
      const ringGeo = new THREE.RingGeometry(0.5, 0.7, 24);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x10b981,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.75
      });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(w.x, 0.07, w.z);
      routeMarkersGroup.add(ring);

      // Stop badge sprite
      const badge = createStopBadgeSprite(`Stop ${stopCounter}`);
      badge.position.set(w.x, 3.4, w.z);
      routeMarkersGroup.add(badge);
      stopCounter++;
    }
  });
}

/**
 * Adds a picked cardboard box onto AGV pallet.
 */
function addBoxToPallet(category) {
  if (!agvForkCarriage || !agvForkCarriage.userData.boxesGroup) return;
  const boxesGroup = agvForkCarriage.userData.boxesGroup;
  
  const boxIndex = agvPalletBoxes.length;
  if (boxIndex >= 6) return; // Max 6 stacked boxes

  const boxW = 0.28, boxH = 0.22, boxD = 0.28;
  const catColor = CATEGORY_COLORS[category] || 0xd97706;
  const boxMat = new THREE.MeshStandardMaterial({
    color: catColor,
    roughness: 0.7,
    metalness: 0.1
  });

  const box = new THREE.Mesh(new THREE.BoxGeometry(boxW, boxH, boxD), boxMat);
  
  // Stacking pattern (2x2 grid, up to 2 layers)
  const layer = Math.floor(boxIndex / 4);
  const col = boxIndex % 2;
  const row = Math.floor((boxIndex % 4) / 2);

  const posX = (col === 0 ? -0.15 : 0.15);
  const posZ = (row === 0 ? 0.28 : 0.56);
  const posY = 0.12 + layer * (boxH + 0.02) + boxH / 2;

  box.position.set(posX, posY, posZ);
  box.castShadow = true;
  boxesGroup.add(box);
  agvPalletBoxes.push(box);
}

/**
 * Frame-by-frame animation update for AGV route traversal and shelf picking.
 */
function updateAGVAnimation(dt) {
  if (!agvAnimState.active || !agvGroup || agvWaypoints.length < 2) return;

  // Beacon flash always active
  if (agvBeacon) {
    const flashFreq = agvAnimState.isPicking ? 18 : 6;
    const intensity = 0.5 + 0.8 * Math.abs(Math.sin(agvAnimClock.getElapsedTime() * flashFreq));
    agvBeacon.material.emissiveIntensity = intensity;
    if (agvBeaconLight) agvBeaconLight.intensity = intensity * 1.5;
  }

  // If paused, maintain camera follow but don't advance
  if (!agvAnimState.playing) {
    updateChaseCamera();
    return;
  }

  const speedMultiplier = agvAnimState.speed;

  // 1. If currently in a Shelf Pick sequence
  if (agvAnimState.isPicking) {
    agvAnimState.pickTimer += dt * speedMultiplier;
    const progress = Math.min(1.0, agvAnimState.pickTimer / agvAnimState.pickDuration);

    // Fork carriage lifts up then lowers
    if (agvForkCarriage) {
      if (progress < 0.5) {
        agvForkCarriage.position.y = 0.22 + (progress / 0.5) * 0.85;
      } else {
        agvForkCarriage.position.y = 1.07 - ((progress - 0.5) / 0.5) * 0.85;
      }
    }

    if (agvAnimState.pickTimer >= agvAnimState.pickDuration) {
      // Pick completed
      agvAnimState.isPicking = false;
      agvAnimState.pickTimer = 0.0;
      if (agvForkCarriage) agvForkCarriage.position.y = 0.22;
      
      // Advance to next segment
      agvAnimState.currentSegmentIndex++;
      agvAnimState.segmentProgress = 0.0;
      updateAGVSpriteText(`AGV-01: TO STOP #${agvAnimState.visitedStopSet.size + 1}`);
    }

    updatePlaybackUI();
    updateChaseCamera();
    return;
  }

  // 2. Check if reached destination Hub
  if (agvAnimState.currentSegmentIndex >= agvWaypoints.length - 1) {
    agvAnimState.playing = false;
    agvAnimState.completed = true;
    updateAGVSpriteText("AGV-01: TOUR COMPLETE", "#10b981");
    updatePlaybackUI();
    updateChaseCamera();
    return;
  }

  const pA = agvWaypoints[agvAnimState.currentSegmentIndex];
  const pB = agvWaypoints[agvAnimState.currentSegmentIndex + 1];
  const segDist = Math.hypot(pB.x - pA.x, pB.z - pA.z);

  if (segDist < 0.001) {
    agvAnimState.currentSegmentIndex++;
    agvAnimState.segmentProgress = 0.0;
    return;
  }

  // Move speed in 3D units/sec (4.5m/s base * speed multiplier)
  const moveSpeed = 4.5 * speedMultiplier;
  const progressIncrement = (moveSpeed * dt) / segDist;
  agvAnimState.segmentProgress += progressIncrement;

  // Advance wheels
  agvWheels.forEach(w => {
    w.rotation.x += moveSpeed * dt * 4.0;
  });

  if (agvAnimState.segmentProgress >= 1.0) {
    // Arrived at waypoint pB
    agvGroup.position.set(pB.x, 0.02, pB.z);
    agvAnimState.segmentProgress = 0.0;
    
    // Check if pB is a pick stop that hasn't been visited yet
    if (pB.isStop && !agvAnimState.visitedStopSet.has(pB.shelfId)) {
      agvAnimState.isPicking = true;
      agvAnimState.pickTimer = 0.0;
      agvAnimState.currentStopShelfId = pB.shelfId;
      agvAnimState.visitedStopSet.add(pB.shelfId);

      // Add box to pallet
      const cat = pB.item ? pB.item.category : 'Tools';
      addBoxToPallet(cat);

      const itemName = pB.item ? pB.item.product_name : `Bay S-${pB.shelfId}`;
      updateAGVSpriteText(`PICKING: S-${pB.shelfId}`, "#10b981");
      showToast(`📦 AGV Picked: ${itemName} from Bay S-${pB.shelfId}`, "success");
    } else {
      agvAnimState.currentSegmentIndex++;
      agvAnimState.segmentProgress = 0.0;
    }
  } else {
    // Interpolate position along segment
    const t = agvAnimState.segmentProgress;
    const curX = pA.x + (pB.x - pA.x) * t;
    const curZ = pA.z + (pB.z - pA.z) * t;
    agvGroup.position.set(curX, 0.02, curZ);

    // Smooth heading rotation
    const targetAngle = Math.atan2(pB.x - pA.x, pB.z - pA.z);
    let diff = targetAngle - agvGroup.rotation.y;
    while (diff < -Math.PI) diff += Math.PI * 2;
    while (diff > Math.PI) diff -= Math.PI * 2;
    agvGroup.rotation.y += diff * Math.min(1.0, dt * 14.0);
  }

  updatePlaybackUI();
  updateChaseCamera();
}

/**
 * Camera Follow Mode (Locks behind AGV).
 */
function updateChaseCamera() {
  if (!agvAnimState.chaseCam || !agvGroup || !camera || !controls) return;

  const angle = agvGroup.rotation.y;
  const distBehind = 9.0;
  const heightAbove = 5.5;

  const camX = agvGroup.position.x - Math.sin(angle) * distBehind;
  const camZ = agvGroup.position.z - Math.cos(angle) * distBehind;
  const camY = agvGroup.position.y + heightAbove;

  camera.position.lerp(new THREE.Vector3(camX, camY, camZ), 0.08);
  controls.target.lerp(new THREE.Vector3(agvGroup.position.x, 1.2, agvGroup.position.z), 0.08);
}

/**
 * Ensures Playback HUD exists on the DOM.
 */
function ensurePlaybackHUD() {
  let hud = document.getElementById('agv-playback-hud');
  if (!hud) {
    const card = document.querySelector('#section-3d-studio .canvas-card') || document.getElementById('canvas-container');
    if (!card) return;

    hud = document.createElement('div');
    hud.id = 'agv-playback-hud';
    hud.className = 'agv-playback-hud';
    hud.innerHTML = `
      <div class="agv-hud-left">
        <button class="agv-btn-play" id="agv-btn-play" onclick="toggleAGVPlayback()" title="Play / Pause (Space)">
          <span id="agv-play-icon">❚❚</span>
        </button>
        <button class="agv-btn-icon" onclick="resetAGVSimulation()" title="Restart Tour">
          ↺
        </button>
        <div class="agv-status-info">
          <div id="agv-hud-title" class="agv-hud-title">Order Pick Tour</div>
          <div id="agv-hud-subtitle" class="agv-hud-sub">Simulating AGV</div>
        </div>
      </div>

      <div class="agv-hud-center">
        <input type="range" id="agv-scrubber" class="agv-slider" min="0" max="100" value="0" step="0.2" oninput="onAGVScrub(this.value)">
        <div class="agv-scrub-meta">
          <span id="agv-progress-text">0.0m / 0.0m</span>
          <span id="agv-stops-badge" class="agv-badge">0 / 0 Stops</span>
        </div>
      </div>

      <div class="agv-hud-right">
        <div class="agv-speed-group">
          <span class="agv-speed-label">Speed:</span>
          <button class="agv-speed-pill active" id="agv-spd-1" onclick="setAGVSpeed(1)">1x</button>
          <button class="agv-speed-pill" id="agv-spd-2" onclick="setAGVSpeed(2)">2x</button>
          <button class="agv-speed-pill" id="agv-spd-5" onclick="setAGVSpeed(5)">5x</button>
        </div>
        <button class="agv-btn-chase" id="agv-btn-chase" onclick="toggleAGVChaseCam()" title="Lock Camera Behind AGV">
          🎥 Chase Cam
        </button>
        <button class="agv-btn-close" onclick="closeAGVSimulation()" title="Close Simulation">
          ✕
        </button>
      </div>
    `;
    card.appendChild(hud);
  }
  hud.style.display = 'flex';
}

/**
 * Updates UI HUD telemetry (scrubber slider, stop count, status).
 */
function updatePlaybackUI() {
  const btnPlay = document.getElementById('agv-btn-play');
  const iconPlay = document.getElementById('agv-play-icon');
  const scrubber = document.getElementById('agv-scrubber');
  const txtProgress = document.getElementById('agv-progress-text');
  const badgeStops = document.getElementById('agv-stops-badge');
  const hudTitle = document.getElementById('agv-hud-title');
  const hudSub = document.getElementById('agv-hud-subtitle');

  if (iconPlay) {
    if (agvAnimState.completed) {
      iconPlay.textContent = '↺';
    } else {
      iconPlay.textContent = agvAnimState.playing ? '❚❚' : '▶';
    }
  }

  // Calculate current distance traveled
  let currentDist = 0;
  if (agvWaypoints.length > 0 && agvAnimState.currentSegmentIndex < agvWaypoints.length) {
    const pA = agvWaypoints[agvAnimState.currentSegmentIndex];
    currentDist = pA.distFromStart || 0;
    if (agvAnimState.currentSegmentIndex + 1 < agvWaypoints.length) {
      const pB = agvWaypoints[agvAnimState.currentSegmentIndex + 1];
      const d = Math.hypot(pB.x - pA.x, pB.z - pA.z);
      currentDist += d * agvAnimState.segmentProgress;
    }
  }

  const totalD = agvAnimState.totalDistance || 1;
  const pct = Math.min(100, Math.max(0, (currentDist / totalD) * 100));

  if (scrubber && document.activeElement !== scrubber) {
    scrubber.value = pct.toFixed(1);
  }

  if (txtProgress) {
    const distMeter = agvAnimState.orderData ? (agvAnimState.orderData.total_distance * (pct / 100)).toFixed(1) : (currentDist * 20).toFixed(1);
    const totalMeter = agvAnimState.orderData ? agvAnimState.orderData.total_distance : (totalD * 20).toFixed(1);
    txtProgress.textContent = `${distMeter}m / ${totalMeter}m (${pct.toFixed(0)}%)`;
  }

  if (badgeStops) {
    const visited = agvAnimState.visitedStopSet.size;
    badgeStops.textContent = `${visited} / ${agvAnimState.totalStops} Stops`;
  }

  if (hudTitle && agvAnimState.orderData) {
    hudTitle.textContent = `Order #${agvAnimState.orderData.order_id || 1} Tour`;
  }

  if (hudSub) {
    if (agvAnimState.completed) {
      hudSub.textContent = "Tour Complete (Returned to Packing)";
      hudSub.style.color = "#10b981";
    } else if (agvAnimState.isPicking) {
      hudSub.textContent = `Picking at Bay S-${agvAnimState.currentStopShelfId}...`;
      hudSub.style.color = "#fbbf24";
    } else {
      hudSub.textContent = agvAnimState.playing ? `En route (Speed: ${agvAnimState.speed}x)` : "Paused";
      hudSub.style.color = "#94a3b8";
    }
  }
}

/**
 * Toggles Play / Pause.
 */
function toggleAGVPlayback() {
  if (agvAnimState.completed) {
    resetAGVSimulation();
    return;
  }
  agvAnimState.playing = !agvAnimState.playing;
  updatePlaybackUI();
}

/**
 * Resets simulation back to start.
 */
function resetAGVSimulation() {
  if (agvWaypoints.length < 2) return;
  agvAnimState.playing = true;
  agvAnimState.completed = false;
  agvAnimState.currentSegmentIndex = 0;
  agvAnimState.segmentProgress = 0.0;
  agvAnimState.isPicking = false;
  agvAnimState.pickTimer = 0.0;
  agvAnimState.visitedStopSet = new Set();

  if (agvForkCarriage && agvForkCarriage.userData.boxesGroup) {
    agvForkCarriage.userData.boxesGroup.clear();
  }
  agvPalletBoxes = [];

  const startPt = agvWaypoints[0];
  const nextPt = agvWaypoints[1];
  agvGroup.position.set(startPt.x, 0.02, startPt.z);
  agvGroup.rotation.y = Math.atan2(nextPt.x - startPt.x, nextPt.z - startPt.z);

  updateAGVSpriteText("AGV-01: READY");
  updatePlaybackUI();
}

/**
 * Changes playback speed (1x, 2x, 5x).
 */
function setAGVSpeed(spd) {
  agvAnimState.speed = Number(spd);
  [1, 2, 5].forEach(s => {
    const btn = document.getElementById(`agv-spd-${s}`);
    if (btn) btn.className = (s === agvAnimState.speed ? 'agv-speed-pill active' : 'agv-speed-pill');
  });
  updatePlaybackUI();
}

/**
 * Scrubber seek along route.
 */
function onAGVScrub(val) {
  const pct = Number(val) / 100;
  const targetDist = pct * agvAnimState.totalDistance;

  // Find corresponding segment
  for (let i = 0; i < agvWaypoints.length - 1; i++) {
    const pA = agvWaypoints[i];
    const pB = agvWaypoints[i + 1];
    if (targetDist >= pA.distFromStart && targetDist <= pB.distFromStart) {
      agvAnimState.currentSegmentIndex = i;
      const segLen = pB.distFromStart - pA.distFromStart;
      agvAnimState.segmentProgress = segLen > 0 ? (targetDist - pA.distFromStart) / segLen : 0;
      
      const t = agvAnimState.segmentProgress;
      agvGroup.position.set(
        pA.x + (pB.x - pA.x) * t,
        0.02,
        pA.z + (pB.z - pA.z) * t
      );
      agvGroup.rotation.y = Math.atan2(pB.x - pA.x, pB.z - pA.z);
      break;
    }
  }

  // Update visited stops up to current waypoint
  agvAnimState.visitedStopSet = new Set();
  for (let i = 0; i <= agvAnimState.currentSegmentIndex; i++) {
    if (agvWaypoints[i].isStop) {
      agvAnimState.visitedStopSet.add(agvWaypoints[i].shelfId);
    }
  }

  updatePlaybackUI();
}

/**
 * Toggles Chase Cam (Lock camera behind AGV).
 */
function toggleAGVChaseCam() {
  agvAnimState.chaseCam = !agvAnimState.chaseCam;
  const btn = document.getElementById('agv-btn-chase');
  if (btn) {
    btn.className = (agvAnimState.chaseCam ? 'agv-btn-chase active' : 'agv-btn-chase');
  }
}

/**
 * Closes AGV route simulation.
 */
function closeAGVSimulation() {
  agvAnimState.active = false;
  agvAnimState.playing = false;
  if (agvGroup) agvGroup.visible = false;
  if (routeMarkersGroup) routeMarkersGroup.clear();
  const hud = document.getElementById('agv-playback-hud');
  if (hud) hud.style.display = 'none';
}

/**
 * Fetches order route from backend and launches 3D simulation.
 */
async function simulate3DOrder(orderId) {
  if (!orderId) {
    closeAGVSimulation();
    return;
  }
  showLoadingSpinner(true);
  try {
    const res = await fetch(`/api/orders/${orderId}/route`, { method: 'POST' });
    if (!res.ok) throw new Error("Failed to compute order route");
    const routeData = await res.json();
    loadRouteIn3DTwin(routeData);
  } catch (err) {
    console.error("Error launching 3D AGV simulation:", err);
    showToast("Error loading order route: " + err.message, "error");
  } finally {
    showLoadingSpinner(false);
  }
}

// ==============================================================================
// 3D THERMAL / ACTIVITY HEATMAP LAYER ENGINE
// ==============================================================================

/**
 * Calculates operational metrics (Sales Velocity or Capacity %) across all bays.
 */
function computeWarehouseHeatmapMetrics() {
  const shelfScores = new Map();
  const sortedByDist = [...warehouseData.shelves].filter(s => s.id !== 1).sort((a, b) => (a.distance_to_packing || 0) - (b.distance_to_packing || 0));
  const goldenSet = new Set(sortedByDist.slice(0, 6).map(s => s.id));

  let minVal = Infinity;
  let maxVal = -Infinity;

  const storageShelves = warehouseData.shelves.filter(s => s.id !== 1);

  storageShelves.forEach(shelf => {
    let val = 0;
    if (heatmapMetric === 'velocity') {
      const prods = warehouseData.products.filter(p => p.assigned_shelf_id === shelf.id);
      val = prods.reduce((sum, p) => sum + (p.pick_frequency || 0), 0);
    } else {
      const cap = shelf.capacity || 5;
      const prods = warehouseData.products.filter(p => p.assigned_shelf_id === shelf.id);
      const load = shelf.current_load || prods.length;
      val = Math.round((load / cap) * 100);
    }

    if (val < minVal) minVal = val;
    if (val > maxVal) maxVal = val;

    shelfScores.set(shelf.id, {
      shelfId: shelf.id,
      value: val,
      isGoldenZone: goldenSet.has(shelf.id),
      distance: shelf.distance_to_packing || 0
    });
  });

  if (minVal === Infinity) { minVal = 0; maxVal = 100; }
  if (minVal === maxVal) { maxVal = minVal + 1; }

  // Compute percentile ranking & slotting advice
  const allVals = Array.from(shelfScores.values()).map(s => s.value).sort((a, b) => a - b);
  shelfScores.forEach(s => {
    const rank = allVals.indexOf(s.value);
    const pct = Math.round(((rank + 1) / allVals.length) * 100);
    s.percentile = pct;

    if (heatmapMetric === 'velocity') {
      if (pct >= 75 && s.isGoldenZone) {
        s.advice = "Optimal Golden Zone Slotting! High-velocity SKUs positioned nearest to dispatch.";
        s.adviceColor = "#10b981";
      } else if (pct >= 75 && !s.isGoldenZone) {
        s.advice = "Sub-Optimal Slotting! High-velocity items located far from dispatch cause travel bloat. Run Layout Optimizer.";
        s.adviceColor = "#f87171";
      } else if (pct < 35 && s.isGoldenZone) {
        s.advice = "Prime Space Underutilized! Low-velocity SKU occupies dispatch-adjacent bay.";
        s.adviceColor = "#fbbf24";
      } else {
        s.advice = "Standard Storage Slotting: Appropriate balance between turnover and distance.";
        s.adviceColor = "#94a3b8";
      }
    } else {
      if (s.value >= 90) {
        s.advice = "High Capacity Warning: Shelf is near maximum physical weight/SKU limit.";
        s.adviceColor = "#f87171";
      } else if (s.value <= 30) {
        s.advice = "Underloaded Bay: Available capacity for high-volume consolidation.";
        s.adviceColor = "#38bdf8";
      } else {
        s.advice = "Balanced Capacity: Normal operational occupancy.";
        s.adviceColor = "#10b981";
      }
    }
  });

  return { shelfScores, minVal, maxVal, goldenSet };
}

/**
 * Maps normalized score [0..1] to smooth thermal color spectrum.
 */
function getThermalColorData(val, minVal, maxVal) {
  const range = Math.max(1, maxVal - minVal);
  const t = Math.min(1.0, Math.max(0.0, (val - minVal) / range));
  
  let hex, css, zone, emissiveHex, emissiveIntensity;
  
  if (t < 0.25) {
    const subT = t / 0.25;
    hex = interpolateHex(0x1e3a8a, 0x0284c7, subT);
    css = '#0284c7';
    zone = 'Cold Zone (Low Velocity)';
    emissiveHex = 0x000000;
    emissiveIntensity = 0.0;
  } else if (t < 0.55) {
    const subT = (t - 0.25) / 0.30;
    hex = interpolateHex(0x059669, 0x84cc16, subT);
    css = '#84cc16';
    zone = 'Moderate Turnover';
    emissiveHex = 0x059669;
    emissiveIntensity = 0.15;
  } else if (t < 0.80) {
    const subT = (t - 0.55) / 0.25;
    hex = interpolateHex(0xf59e0b, 0xea580c, subT);
    css = '#ea580c';
    zone = 'Active Zone (High Turnover)';
    emissiveHex = 0xf59e0b;
    emissiveIntensity = 0.35;
  } else {
    const subT = (t - 0.80) / 0.20;
    hex = interpolateHex(0xef4444, 0xff1744, subT);
    css = '#ff1744';
    zone = '🔥 Hot Zone (Golden / Bottleneck)';
    emissiveHex = 0xef4444;
    emissiveIntensity = 0.65;
  }

  return { t, hex, css, zone, emissiveHex, emissiveIntensity };
}

function interpolateHex(color1, color2, factor) {
  const r1 = (color1 >> 16) & 255;
  const g1 = (color1 >> 8) & 255;
  const b1 = color1 & 255;

  const r2 = (color2 >> 16) & 255;
  const g2 = (color2 >> 8) & 255;
  const b2 = color2 & 255;

  const r = Math.round(r1 + factor * (r2 - r1));
  const g = Math.round(g1 + factor * (g2 - g1));
  const b = Math.round(b1 + factor * (b2 - b1));

  return (r << 16) | (g << 8) | b;
}

/**
 * Toggles Heatmap Mode ON / OFF.
 */
function toggle3DHeatmap(forceState) {
  if (typeof forceState === 'boolean') {
    heatmapActive = forceState;
  } else {
    heatmapActive = !heatmapActive;
  }

  const btn = document.getElementById('btn-toggle-3d-heatmap');
  if (btn) {
    btn.classList.toggle('active', heatmapActive);
    btn.innerHTML = heatmapActive 
      ? `<span class="heatmap-fire-icon">🔥</span> Heatmap: ON`
      : `<span class="heatmap-fire-icon">🔥</span> Heatmap Mode`;
  }

  if (heatmapActive) {
    applyHeatmapMaterials();
    showToast(`Thermal Activity Heatmap Active (${heatmapMetric === 'velocity' ? 'Sales Turnover' : 'Capacity Load %'})`, 'info');
  } else {
    restoreOriginalRackMaterials();
    showToast('Thermal Heatmap deactivated', 'info');
  }
}

/**
 * Changes active heatmap metric: 'velocity' or 'capacity'.
 */
function set3DHeatmapMetric(metric) {
  heatmapMetric = metric;
  const btnVel = document.getElementById('btn-metric-velocity');
  const btnCap = document.getElementById('btn-metric-capacity');
  if (btnVel) btnVel.className = (metric === 'velocity' ? 'heatmap-metric-pill active' : 'heatmap-metric-pill');
  if (btnCap) btnCap.className = (metric === 'capacity' ? 'heatmap-metric-pill active' : 'heatmap-metric-pill');

  if (heatmapActive) {
    applyHeatmapMaterials();
  }
}

/**
 * Applies thermal gradient materials to 3D racks.
 */
function applyHeatmapMaterials() {
  heatmapPulseRacks = [];
  const metrics = computeWarehouseHeatmapMetrics();

  rackMeshes.forEach((mesh, shelfId) => {
    if (shelfId === 1) return; // Keep Hub distinct

    const score = metrics.shelfScores.get(shelfId);
    if (!score) return;

    const thermal = getThermalColorData(score.value, metrics.minVal, metrics.maxVal);
    score.thermal = thermal;

    if (thermal.t >= 0.75) {
      heatmapPulseRacks.push(mesh);
    }

    mesh.traverse(child => {
      if (child.isMesh && !child.userData.isHitbox && !child.userData.isPlaque) {
        if (!child.userData.origMaterial) {
          child.userData.origMaterial = child.material;
        }

        child.material = new THREE.MeshStandardMaterial({
          color: thermal.hex,
          roughness: 0.35,
          metalness: 0.35,
          emissive: thermal.emissiveHex,
          emissiveIntensity: thermal.emissiveIntensity
        });
      }
    });
  });

  applyCorridorTrafficHeatmap(metrics);
  updateHeatmapLegend(metrics);

  if (selectedShelfId) {
    updateInspectorHUD(selectedShelfId);
  }
}

/**
 * Restores original materials to all racks and corridors.
 */
function restoreOriginalRackMaterials() {
  heatmapPulseRacks = [];
  rackMeshes.forEach((mesh, shelfId) => {
    if (shelfId === 1) return;
    mesh.traverse(child => {
      if (child.isMesh && child.userData.origMaterial) {
        child.material = child.userData.origMaterial;
      }
    });
  });

  if (warehouseData.graph && warehouseData.graph.edges && warehouseData.graph.nodes) {
    renderCorridorEdges(warehouseData.graph.edges, warehouseData.graph.nodes);
  }

  const legend = document.getElementById('heatmap-3d-legend');
  if (legend) legend.style.display = 'none';
  hideHeatmapTooltip();

  if (selectedShelfId) {
    updateInspectorHUD(selectedShelfId);
  }
}

/**
 * Colors corridor floor segments based on traffic / hot zone proximity.
 */
function applyCorridorTrafficHeatmap(metrics) {
  if (!corridorLinesGroup || !warehouseData.graph || !warehouseData.graph.edges || !warehouseData.graph.nodes) return;
  corridorLinesGroup.clear();

  const nodeMap = new Map();
  warehouseData.graph.nodes.forEach(n => nodeMap.set(n.id, mapCoordsTo3D(n.x, n.y)));

  warehouseData.graph.edges.forEach(edge => {
    const from = nodeMap.get(edge.from_shelf_id);
    const to = nodeMap.get(edge.to_shelf_id);
    if (!from || !to) return;

    const scoreFrom = metrics.shelfScores.get(edge.from_shelf_id);
    const scoreTo = metrics.shelfScores.get(edge.to_shelf_id);
    const tFrom = scoreFrom ? scoreFrom.thermal.t : 0.2;
    const tTo = scoreTo ? scoreTo.thermal.t : 0.2;
    const maxT = Math.max(tFrom, tTo);

    let colorHex = 0x0284c7;
    let opacity = 0.45;
    let linewidth = 2;

    if (maxT >= 0.75) {
      colorHex = 0xff1744; // Hot Red corridor
      opacity = 0.95;
      linewidth = 4;
    } else if (maxT >= 0.5) {
      colorHex = 0xf59e0b; // Amber corridor
      opacity = 0.8;
      linewidth = 3;
    } else if (maxT >= 0.3) {
      colorHex = 0x84cc16; // Lime corridor
      opacity = 0.6;
    }

    const points = [
      new THREE.Vector3(from.x, 0.05, from.z),
      new THREE.Vector3(to.x, 0.05, to.z)
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const lineMat = new THREE.LineBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: opacity,
      linewidth: linewidth
    });
    const line = new THREE.Line(geo, lineMat);
    corridorLinesGroup.add(line);
  });
}

/**
 * Breathing emissive pulse animation on Hot Zone racks.
 */
function updateHeatmapAnimation(dt) {
  if (!heatmapActive || heatmapPulseRacks.length === 0) return;
  const time = agvAnimClock.getElapsedTime();
  heatmapPulseRacks.forEach(mesh => {
    const pulse = 0.45 + 0.35 * Math.sin(time * 3.8 + (mesh.userData.shelfId || 0) * 0.7);
    mesh.traverse(child => {
      if (child.isMesh && child.material && child.material.emissive && !child.userData.isHitbox && !child.userData.isPlaque) {
        child.material.emissiveIntensity = pulse;
      }
    });
  });
}

/**
 * Floating 3D Colorbar Legend.
 */
function ensureHeatmapLegend() {
  let legend = document.getElementById('heatmap-3d-legend');
  if (!legend) {
    const card = document.querySelector('#section-3d-studio .canvas-card') || document.getElementById('canvas-container');
    if (!card) return null;

    legend = document.createElement('div');
    legend.id = 'heatmap-3d-legend';
    legend.className = 'heatmap-3d-legend';
    legend.innerHTML = `
      <div class="heatmap-legend-header">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span class="heatmap-fire-icon">🔥</span>
          <strong>Thermal Activity Heatmap</strong>
        </div>
        <button class="heatmap-close-btn" onclick="toggle3DHeatmap(false)" title="Close Heatmap">✕</button>
      </div>

      <div class="heatmap-metric-selector">
        <button class="heatmap-metric-pill active" id="btn-metric-velocity" onclick="set3DHeatmapMetric('velocity')">
          Sales Velocity
        </button>
        <button class="heatmap-metric-pill" id="btn-metric-capacity" onclick="set3DHeatmapMetric('capacity')">
          Capacity Load %
        </button>
      </div>

      <div class="heatmap-colorbar-track"></div>
      <div class="heatmap-colorbar-labels">
        <span id="heatmap-lbl-min">Cold (0)</span>
        <span>Moderate</span>
        <span id="heatmap-lbl-max" style="color: #ff3366; font-weight: 700;">Hot (Max)</span>
      </div>

      <div class="heatmap-telemetry-meta">
        <div class="heatmap-meta-row">
          <span>Golden Zone Bays:</span>
          <strong id="heatmap-golden-count" style="color: #fbbf24;">6 Bays (Near Hub)</strong>
        </div>
        <div class="heatmap-meta-row">
          <span>Corridor Traffic Glow:</span>
          <strong id="heatmap-bottleneck-label" style="color: #ff3366;">Active Gradient</strong>
        </div>
      </div>
    `;
    card.appendChild(legend);
  }
  return legend;
}

function updateHeatmapLegend(metrics) {
  const legend = ensureHeatmapLegend();
  if (!legend) return;
  legend.style.display = 'block';

  const lblMin = document.getElementById('heatmap-lbl-min');
  const lblMax = document.getElementById('heatmap-lbl-max');
  if (lblMin && lblMax) {
    if (heatmapMetric === 'velocity') {
      lblMin.textContent = `Min (${Math.round(metrics.minVal).toLocaleString()})`;
      lblMax.textContent = `Hot (${Math.round(metrics.maxVal).toLocaleString()})`;
    } else {
      lblMin.textContent = `Min (${metrics.minVal}%)`;
      lblMax.textContent = `Max (${metrics.maxVal}%)`;
    }
  }
}

/**
 * Hover Telemetry Tooltip.
 */
function ensureHeatmapTooltip() {
  if (!heatmapTooltip) {
    heatmapTooltip = document.createElement('div');
    heatmapTooltip.id = 'heatmap-hover-tooltip';
    heatmapTooltip.className = 'heatmap-hover-tooltip';
    document.body.appendChild(heatmapTooltip);
  }
  return heatmapTooltip;
}

function updateHeatmapTooltip(shelfId, clientX, clientY) {
  if (!heatmapActive || shelfId === 1) {
    hideHeatmapTooltip();
    return;
  }
  const tooltip = ensureHeatmapTooltip();
  const metrics = computeWarehouseHeatmapMetrics();
  const score = metrics.shelfScores.get(shelfId);
  if (!score) return;

  const thermal = getThermalColorData(score.value, metrics.minVal, metrics.maxVal);
  const metricLabel = heatmapMetric === 'velocity' ? `${Math.round(score.value).toLocaleString()} picks/yr` : `${score.value}% capacity`;

  tooltip.innerHTML = `
    <div style="font-weight: 800; font-size: 0.8rem; margin-bottom: 2px; color: ${thermal.css};">
      Bay S-${shelfId} &bull; ${thermal.zone}
    </div>
    <div style="font-size: 0.72rem; color: #cbd5e1; margin-bottom: 2px;">
      ${heatmapMetric === 'velocity' ? 'Pick Velocity' : 'Load'}: <strong>${metricLabel}</strong> (${score.percentile}th %)
    </div>
    <div style="font-size: 0.7rem; color: ${score.isGoldenZone ? '#fbbf24' : '#94a3b8'};">
      Golden Zone: <strong>${score.isGoldenZone ? '★ YES (Prime Proximity)' : 'Standard Bay'}</strong>
    </div>
  `;
  tooltip.style.left = `${clientX + 14}px`;
  tooltip.style.top = `${clientY}px`;
  tooltip.style.display = 'block';
}

function hideHeatmapTooltip() {
  if (heatmapTooltip) heatmapTooltip.style.display = 'none';
}

// Bootstrap on DOM ready (standalone mode)
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('canvas-container');
  if (container && !document.getElementById('graph-canvas')) {
    init3DScene();
    loadWarehouseData();
  }
});


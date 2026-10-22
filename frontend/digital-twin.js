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

  // Lighting
  setupLighting();

  // Floor Grid & Surroundings
  buildWarehouseFloor();

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

  // Start Animation Loop
  animate();
}

/**
 * Dynamic lighting with soft industrial ambient and directional warehouse bays.
 */
function setupLighting() {
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
  scene.add(ambientLight);

  const mainLight = new THREE.DirectionalLight(0xfff8ee, 1.2);
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
  mainLight.shadow.bias = -0.0005;
  scene.add(mainLight);

  // Subtle cool fill light
  const fillLight = new THREE.DirectionalLight(0x93c5fd, 0.4);
  fillLight.position.set(-30, 25, -20);
  scene.add(fillLight);
}

/**
 * Procedural warehouse concrete floor with safety stripes and perimeter curb.
 */
function buildWarehouseFloor() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const floorGeo = new THREE.PlaneGeometry(CONFIG.floorWidth, CONFIG.floorDepth);
  const floorMat = new THREE.MeshStandardMaterial({
    color: isDark ? 0x1a1e24 : 0xdedede,
    roughness: 0.85,
    metalness: 0.15
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
    isDark ? 0x334155 : 0xc7d2fe,
    isDark ? 0x222a35 : 0xe2e8f0
  );
  gridHelper.position.y = 0.01;
  scene.add(gridHelper);

  // Safety perimeter curb
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x3b4252, roughness: 0.7 });
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
  rackGroup.add(plaque);

  // Invisible Hitbox for precise raycasting
  const hitboxGeo = new THREE.BoxGeometry(w + 0.4, h + 0.8, d + 0.4);
  const hitboxMat = new THREE.MeshBasicMaterial({ visible: false });
  const hitbox = new THREE.Mesh(hitboxGeo, hitboxMat);
  hitbox.position.set(0, h / 2, 0);
  hitbox.userData = { parentRack: rackGroup };
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
      highlightRack(hoveredRack, 0x38bdf8);
      renderer.domElement.style.cursor = 'pointer';
    }
  } else {
    if (hoveredRack && hoveredRack.userData.shelfId !== selectedShelfId) {
      unhighlightRack(hoveredRack);
    }
    hoveredRack = null;
    renderer.domElement.style.cursor = 'default';
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
function animate() {
  animationFrameId = requestAnimationFrame(animate);
  if (controls) controls.update();
  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}

/**
 * Handles window resize.
 */
function onWindowResize() {
  const container = document.getElementById('canvas-container');
  if (!container || !renderer || !camera) return;

  const width = container.clientWidth;
  const height = container.clientHeight;

  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
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

// Bootstrap on DOM ready (standalone mode)
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('canvas-container');
  if (container && !document.getElementById('graph-canvas')) {
    init3DScene();
    loadWarehouseData();
  }
});

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";

const PROJECT_ROOT = "..";
const MATERIAL_JOBS_ROOT = `${PROJECT_ROOT}/material-jobs`;
const GLB_URL = `${PROJECT_ROOT}/assets/models/fixed-ball-valve-issue8-industrial-uv.glb`;
const NODE_MAP_URL = `${PROJECT_ROOT}/assets-manifest/node-map.json`;
const JOBS_URL = `${PROJECT_ROOT}/controls/material-jobs/index.json`;
const LIGHTING_URL = `${PROJECT_ROOT}/controls/lighting/issue8-lighting.json`;

const ROLE_COLORS = [
  "#9fa3a3",
  "#c3c7c4",
  "#9ca8a2",
  "#c6c9c4",
  "#87918e",
  "#b6bab7",
  "#818884",
  "#aab1ad",
  "#b8c0bc",
  "#a8b0ad",
  "#a7afac",
  "#d7d9d6",
  "#d9d5c8",
  "#222522",
  "#adb4b1",
  "#575f5c",
  "#6d7672"
];

const VIEW_LABELS = {
  assembled: "装配",
  "hero-exploded": "商业爆炸",
  exploded: "角色爆炸",
  "material-grid": "17 材质"
};

const VALID_VIEWS = new Set(Object.keys(VIEW_LABELS));
const ZERO = new THREE.Vector3();
const EASE_IN_OUT = cubicBezierEasing(0.77, 0, 0.175, 1);
const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

const EXPLODE_DIRECTIONS = {
  body_cast_shell: [0, 0, 0],
  body_flange_machined_faces: [-1, 0.18, 0.18],
  cover_cast_shell: [1, 0.16, -0.12],
  cover_flange_machined_faces: [1.1, 0.32, 0.18],
  packing_box_cast_shell: [0.08, 1, 0.15],
  packing_box_machined_faces: [0.18, 1.15, -0.24],
  bracket_cast_shell: [0, -0.9, -0.45],
  bracket_machined_faces: [0.28, -1.05, -0.1],
  machined_surface: [-0.85, 0.28, 0.55],
  bearing_surface: [0.78, 0.44, 0.48],
  precision_machined: [0.18, 0.18, 1],
  polished_ball: [0, 0.08, 1.2],
  soft_seal: [-0.42, 0.55, 0.82],
  gasket_graphite: [-0.75, -0.08, 0.62],
  fastener_zinc: [1.12, -0.18, 0.38],
  threaded_dark: [1.15, -0.5, -0.15],
  spring_steel: [-0.18, -0.82, 0.55]
};

const HERO_RULES = {
  minGapRatio: 0.035,
  blockGapRatio: 0.02,
  laneGapRatio: 0.048,
  rowStepRatio: 0.07,
  maxOffsetRatio: 2.45,
  depthLayerRatio: 0.14,
  sidePortDepthRatio: 0.18
};

const AXIS_RIG_CLEARANCE_DELAY = 0.035;
const AXIS_RIG_TIMELINE = {
  flow_neg_cover_fasteners: [0.03, 0.16],
  bracket_fastener_array: [0.03, 0.18],
  bottom_trunnion_fasteners: [0.04, 0.18],
  drain_plug_side: [0.14, 0.3],
  body_exterior_shell: [0.18, 0.38],
  flow_neg_cover_shell: [0.2, 0.36],
  bracket_connector: [0.22, 0.4],
  bottom_trunnion_stack: [0.24, 0.42],
  packing_fastener_array: [0.44, 0.56],
  flow_neg_spring_ring: [0.44, 0.62],
  flow_pos_spring_ring: [0.46, 0.64],
  stem_packing_stack: [0.6, 0.8],
  flow_neg_seat_stack: [0.66, 0.88],
  flow_pos_seat_stack: [0.7, 0.92]
};

const AXIS_RIG_BLOCKERS = {
  flow_neg_cover_shell: ["flow_neg_cover_fasteners"],
  flow_neg_spring_ring: ["flow_neg_cover_shell"],
  flow_neg_seat_stack: ["flow_neg_spring_ring"],
  flow_pos_spring_ring: ["body_exterior_shell"],
  flow_pos_seat_stack: ["body_exterior_shell", "flow_pos_spring_ring"],
  bracket_connector: ["bracket_fastener_array"],
  packing_fastener_array: ["bracket_connector"],
  stem_packing_stack: ["packing_fastener_array"],
  bottom_trunnion_stack: ["bottom_trunnion_fasteners"]
};

const state = {
  mode: "styled",
  viewMode: "assembled",
  mapChannel: "baseColor",
  activeRole: "all",
  explosionProgress: 0,
  reducedMotion: reduceMotionQuery.matches,
  lightStrength: 1,
  envStrength: 1,
  roughnessScale: 1,
  normalScale: 1,
  heightScale: 1,
  axisXScale: 1,
  axisZScale: 0.75,
  axisYScale: 0.12,
  axisSpacingScale: 1,
  roles: [],
  manifests: new Map(),
  materialControls: new Map(),
  textureCache: new Map(),
  materials: new Map(),
  records: [],
  meshes: [],
  visibleMeshes: 0,
  roleGroups: new Map(),
  roleLayout: new Map(),
  motionUnits: [],
  heroLayout: {
    status: "pending",
    origin: [0, 0, 0],
    units: 0,
    minGap: 0,
    maxOffset: 0,
    axisScales: { x: 1, z: 0.75, y: 0.12, spacing: 1 },
    hierarchyNodes: 0,
    blockingChecks: 0,
    blockingResolutions: 0,
    unresolvedBlocking: 0,
    maxOffsetClamps: 0,
    maxBlockingEscape: 0,
    maxResolvedOffset: 0
  },
  motion: null,
  modelCenter: new THREE.Vector3(),
  modelSize: new THREE.Vector3(),
  modelMaxDim: 1,
  match: { matched: 0, fallback: 0, missingRoleJobs: 0 },
  mapAudit: { declaredMaps: 0, loadRequests: 0, missingMaps: 0, availableMaps: 0 },
  lightingRig: {
    path: LIGHTING_URL,
    loaded: false,
    name: "fallback-preview-lights",
    lightCount: 0,
    intent: ""
  }
};

const qs = new URLSearchParams(window.location.search);
function readScaleParam(key, fallback, min, max) {
  if (!qs.has(key)) return fallback;
  const value = Number(qs.get(key));
  return Number.isFinite(value) ? THREE.MathUtils.clamp(value, min, max) : fallback;
}

if (qs.has("mode")) state.mode = qs.get("mode");
if (qs.has("role")) state.activeRole = qs.get("role");
if (qs.has("map")) state.mapChannel = qs.get("map");
if (qs.has("view") && VALID_VIEWS.has(qs.get("view"))) state.viewMode = qs.get("view");
state.axisXScale = readScaleParam("axisX", state.axisXScale, 0.25, 1.8);
state.axisZScale = readScaleParam("axisZ", state.axisZScale, 0.15, 1.6);
state.axisYScale = readScaleParam("axisY", state.axisYScale, 0, 0.55);
state.axisSpacingScale = readScaleParam("spacing", state.axisSpacingScale, 0.55, 1.8);
if (qs.has("explode")) {
  state.explosionProgress = THREE.MathUtils.clamp(Number(qs.get("explode")) || 0, 0, 1);
}
if (!qs.has("explode") && state.viewMode !== "assembled") state.explosionProgress = 1;
if (state.viewMode === "assembled") state.explosionProgress = 0;

const canvas = document.querySelector("#scene");
const statusEl = document.querySelector("#status");
const summaryEl = document.querySelector("#summary");
const rolesEl = document.querySelector("#roles");
const logEl = document.querySelector("#gate-log");
const viewEl = document.querySelector("#view-mode");
const modeEl = document.querySelector("#mode");
const mapEl = document.querySelector("#map-channel");
const explodeEl = document.querySelector("#explode-progress");
const axisXEl = document.querySelector("#axis-x-scale");
const axisZEl = document.querySelector("#axis-z-scale");
const axisYEl = document.querySelector("#axis-y-scale");
const axisSpacingEl = document.querySelector("#axis-spacing-scale");
const lightEl = document.querySelector("#light-strength");
const envEl = document.querySelector("#env-strength");
const roughnessEl = document.querySelector("#roughness-scale");
const normalEl = document.querySelector("#normal-scale");
const heightEl = document.querySelector("#height-scale");

viewEl.value = state.viewMode;
modeEl.value = state.mode;
mapEl.value = state.mapChannel;
explodeEl.value = String(state.explosionProgress);
syncAxisControls();

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  preserveDrawingBuffer: true
});
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x080a0b);
RectAreaLightUniformsLib.init();

const camera = new THREE.PerspectiveCamera(38, 1, 0.001, 100);
camera.position.set(0.9, 0.8, 0.55);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

const previewLights = [];
const lightRigGroup = new THREE.Group();
lightRigGroup.name = "loaded_lighting_rig";
scene.add(lightRigGroup);

function registerPreviewLight(light, baseIntensity, parent = scene) {
  light.userData.baseIntensity = baseIntensity;
  previewLights.push(light);
  parent.add(light);
  return light;
}

const keyLight = registerPreviewLight(new THREE.DirectionalLight(0xffffff, 2.3), 2.3);
keyLight.position.set(1.7, 2.1, 1.4);

const fillLight = registerPreviewLight(new THREE.DirectionalLight(0xdde8ec, 0.7), 0.7);
fillLight.position.set(-1.8, 0.8, -1.1);

const rimLight = registerPreviewLight(new THREE.DirectionalLight(0xffffff, 1.25), 1.25);
rimLight.position.set(-1.1, -1.6, 1.3);

const hemiLight = registerPreviewLight(new THREE.HemisphereLight(0xf2f7f8, 0x1d2527, 0.28), 0.28);

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const modelRoot = new THREE.Group();
scene.add(modelRoot);

function normalizePath(path) {
  if (!path) return "";
  const clean = String(path).replaceAll("\\", "/");
  if (clean.startsWith("http://") || clean.startsWith("https://")) return clean;
  if (clean.startsWith("/")) return clean;
  if (clean.startsWith("./") || clean.startsWith("../")) return clean;
  return `${PROJECT_ROOT}/${clean.replace(/^\.?\//u, "")}`;
}

function normalizeTextureSet(textureSet) {
  const maps = textureSet?.maps || textureSet || {};
  return Object.fromEntries(
    Object.entries(maps).map(([key, value]) => {
      if (typeof value === "string") return [key, normalizePath(value)];
      return [key, { ...value, path: normalizePath(value?.path || value?.url || "") }];
    })
  );
}

function blenderOffsetToThree(offset = [0, 0, 0]) {
  const [x = 0, y = 0, z = 0] = offset;
  return new THREE.Vector3(x, z, -y);
}

function colorFromConfig(color, fallback = 0xffffff) {
  if (Array.isArray(color) && color.length >= 3) {
    return new THREE.Color(color[0], color[1], color[2]);
  }
  return new THREE.Color(fallback);
}

function rectEnergyToIntensity(energy) {
  return THREE.MathUtils.clamp((Number(energy) || 0) / 85, 0.12, 6.5);
}

function clearPreviewLights() {
  for (const light of previewLights) {
    light.parent?.remove(light);
  }
  previewLights.length = 0;
  lightRigGroup.clear();
}

function applyLightingRig(rig) {
  const lights = rig?.lighting?.lights || [];
  if (!lights.length) return;

  clearPreviewLights();
  const rigScale = Number(rig?.lighting?.strengthScale ?? 1);
  const targetBase = state.modelCenter.clone();
  let loadedCount = 0;

  for (const item of lights) {
    const color = colorFromConfig(item.color);
    const position = targetBase.clone().add(blenderOffsetToThree(item.offset));
    const target = targetBase.clone().add(blenderOffsetToThree(item.targetOffset));
    const shape = String(item.shape || "").toUpperCase();
    const baseIntensity = rectEnergyToIntensity(item.energy) * rigScale;
    let light;

    if (shape === "RECTANGLE") {
      light = new THREE.RectAreaLight(color, baseIntensity, Number(item.size) || 1, Number(item.sizeY || item.size) || 1);
    } else {
      light = new THREE.DirectionalLight(color, baseIntensity);
    }

    light.name = item.name || `rig_light_${loadedCount + 1}`;
    light.position.copy(position);
    light.lookAt(target);
    registerPreviewLight(light, baseIntensity, lightRigGroup);
    loadedCount += 1;
  }

  const ambient = new THREE.HemisphereLight(0xf4f8fa, 0x101416, 0.16 * rigScale);
  ambient.name = "viewer_soft_ambient";
  registerPreviewLight(ambient, ambient.intensity, lightRigGroup);

  state.lightingRig = {
    path: LIGHTING_URL,
    loaded: true,
    name: rig.name || "project-lighting-rig",
    lightCount: loadedCount,
    intent: rig?.lighting?.intent || ""
  };
  setLightStrength(state.lightStrength);
}

function normalizeName(name) {
  return String(name || "")
    .trim()
    .replace(/\.\d{3}$/u, "")
    .replace(/_\d+$/u, "")
    .toLowerCase();
}

function cubicBezierEasing(x1, y1, x2, y2) {
  const sample = (t, a1, a2) => {
    const inv = 1 - t;
    return 3 * inv * inv * t * a1 + 3 * inv * t * t * a2 + t * t * t;
  };

  return (x) => {
    let low = 0;
    let high = 1;
    let t = x;
    for (let i = 0; i < 16; i += 1) {
      const estimate = sample(t, x1, x2);
      if (Math.abs(estimate - x) < 0.0001) break;
      if (estimate < x) low = t;
      else high = t;
      t = (low + high) / 2;
    }
    return sample(t, y1, y2);
  };
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

function loadTexture(info, colorSpace) {
  const url = normalizePath(info?.path || info);
  if (!url) return null;
  const cacheKey = `${url}|${colorSpace}`;
  if (state.textureCache.has(cacheKey)) return state.textureCache.get(cacheKey);

  state.mapAudit.loadRequests += 1;
  const loader = new THREE.TextureLoader();
  const texture = loader.load(
    url,
    () => updateLog(),
    undefined,
    () => {
      state.mapAudit.missingMaps += 1;
      updateLog();
    }
  );
  texture.colorSpace = colorSpace;
  texture.flipY = false;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  state.textureCache.set(cacheKey, texture);
  return texture;
}

function roleColor(role) {
  const index = Math.max(0, state.roles.findIndex((item) => item.role === role));
  return ROLE_COLORS[index % ROLE_COLORS.length];
}

function materialConfig(role) {
  const control = state.materialControls.get(role);
  return control?.materials?.[role] || {};
}

function textureSet(role) {
  const manifest = state.manifests.get(role);
  return normalizeTextureSet(manifest?.textureSet || {});
}

function createMaterial(role) {
  const key = [
    state.mode,
    state.mapChannel,
    role,
    state.roughnessScale,
    state.normalScale,
    state.heightScale,
    state.envStrength
  ].join("|");
  if (state.materials.has(key)) return state.materials.get(key);

  const maps = textureSet(role);
  const config = materialConfig(role);
  state.mapAudit.declaredMaps = Math.max(state.mapAudit.declaredMaps, Object.keys(maps).length);
  state.mapAudit.availableMaps = Math.max(
    state.mapAudit.availableMaps,
    Object.values(maps).filter((item) => Boolean(item?.path || item)).length
  );

  let material;
  if (state.mode === "texture-only") {
    const selected = maps[state.mapChannel] || maps.baseColor;
    const isColor = state.mapChannel === "baseColor";
    material = new THREE.MeshBasicMaterial({
      map: loadTexture(selected, isColor ? THREE.SRGBColorSpace : THREE.NoColorSpace),
      color: 0xffffff,
      side: THREE.DoubleSide
    });
  } else {
    const color = config.baseColor
      ? new THREE.Color(config.baseColor[0], config.baseColor[1], config.baseColor[2])
      : new THREE.Color(roleColor(role));
    const roughness = THREE.MathUtils.clamp((config.roughness ?? 0.48) * state.roughnessScale, 0.02, 1);
    const metallic = THREE.MathUtils.clamp(config.metallic ?? 1, 0, 1);
    material = new THREE.MeshStandardMaterial({
      color,
      map: loadTexture(maps.baseColor, THREE.SRGBColorSpace),
      normalMap: loadTexture(maps.normal, THREE.NoColorSpace),
      metalnessMap: loadTexture(maps.metallic, THREE.NoColorSpace),
      roughnessMap: loadTexture(maps.roughness, THREE.NoColorSpace),
      aoMap: loadTexture(maps.ao, THREE.NoColorSpace),
      bumpMap: loadTexture(maps.height, THREE.NoColorSpace),
      metalness: metallic,
      roughness,
      envMapIntensity: state.envStrength,
      side: THREE.DoubleSide
    });
    material.normalScale.setScalar((config.normalStrength ?? 0.08) * state.normalScale * 4.0);
    material.bumpScale = (config.heightDistance ?? 0.004) * state.heightScale;
  }

  material.name = `preview_${state.mode}_${role}`;
  state.materials.set(key, material);
  return material;
}

function createFallbackMaterial(role) {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(roleColor(role || "fallback")),
    metalness: 0.7,
    roughness: 0.55,
    envMapIntensity: state.envStrength,
    side: THREE.DoubleSide
  });
}

function buildRoleMaps(nodeMap) {
  state.records = Array.isArray(nodeMap.records) ? nodeMap.records : [];
  const exact = new Map();
  const loose = new Map();
  const exactRecord = new Map();
  const looseRecord = new Map();
  for (const record of state.records) {
    const role = record.materialRole || record.materialKey;
    if (!role) continue;
    for (const key of [record.objectName, record.renderRecordId, record.productName, record.sourceProductName]) {
      if (!key) continue;
      exact.set(String(key), role);
      loose.set(normalizeName(key), role);
      exactRecord.set(String(key), record);
      looseRecord.set(normalizeName(key), record);
    }
  }
  return { exact, loose, exactRecord, looseRecord };
}

function resolveRole(mesh, index, maps) {
  const candidates = [
    mesh.name,
    mesh.parent?.name,
    mesh.userData?.name,
    mesh.userData?.renderRecordId,
    mesh.userData?.extras?.renderRecordId
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (maps.exact.has(candidate)) return maps.exact.get(candidate);
    const normalized = normalizeName(candidate);
    if (maps.loose.has(normalized)) return maps.loose.get(normalized);
  }
  return state.records[index]?.materialRole || state.records[index]?.materialKey || "unmatched";
}

function resolveRecord(mesh, index, maps) {
  const candidates = [
    mesh.name,
    mesh.parent?.name,
    mesh.userData?.name,
    mesh.userData?.renderRecordId,
    mesh.userData?.extras?.renderRecordId
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (maps.exactRecord.has(candidate)) return maps.exactRecord.get(candidate);
    const normalized = normalizeName(candidate);
    if (maps.looseRecord.has(normalized)) return maps.looseRecord.get(normalized);
  }
  return state.records[index] || null;
}

function ensureRoleGroup(role) {
  if (state.roleGroups.has(role)) return state.roleGroups.get(role);
  const group = new THREE.Group();
  group.name = `role_${role}`;
  modelRoot.add(group);
  state.roleGroups.set(role, group);
  return group;
}

function groupMeshesByRole() {
  modelRoot.updateMatrixWorld(true);
  for (const mesh of state.meshes) {
    const role = mesh.userData.materialRole || "unmatched";
    ensureRoleGroup(role).attach(mesh);
  }
  modelRoot.updateMatrixWorld(true);
}

function vectorToArray(vector) {
  return [vector.x, vector.y, vector.z].map((value) => Number(value.toFixed(5)));
}

function copyBox(box) {
  return new THREE.Box3(box.min.clone(), box.max.clone());
}

function safeDirection(vector, fallback = new THREE.Vector3(1, 0, 0)) {
  if (!vector || vector.lengthSq() < 0.000001) return fallback.clone().normalize();
  return vector.clone().normalize();
}

function signedAxis(value, fallback = 1) {
  if (Math.abs(value) < 0.00001) return fallback;
  return value >= 0 ? 1 : -1;
}

function tangentFor(direction) {
  const up = new THREE.Vector3(0, 1, 0);
  const tangent = new THREE.Vector3().crossVectors(direction, up);
  if (tangent.lengthSq() < 0.000001) {
    tangent.crossVectors(direction, new THREE.Vector3(0, 0, 1));
  }
  return safeDirection(tangent, new THREE.Vector3(0, 0, 1));
}

function meshWorldBox(mesh) {
  modelRoot.updateMatrixWorld(true);
  return new THREE.Box3().setFromObject(mesh);
}

function centerOfRole(role) {
  const group = state.roleGroups.get(role);
  if (!group) return null;
  const box = new THREE.Box3().setFromObject(group);
  return box.isEmpty() ? null : box.getCenter(new THREE.Vector3());
}

function findCoreOrigin() {
  const polished = state.meshes.find((mesh) => mesh.userData.materialRole === "polished_ball");
  if (polished) {
    return meshWorldBox(polished).getCenter(new THREE.Vector3());
  }
  return state.modelCenter.clone();
}

function roleBand(role) {
  if (role === "polished_ball") return "core";
  if (role.includes("cast_shell")) return "shell";
  if (role.includes("machined_faces")) return "surface";
  if (["soft_seal", "gasket_graphite", "bearing_surface", "machined_surface"].includes(role)) return "core-ring";
  if (["threaded_dark", "fastener_zinc", "spring_steel"].includes(role)) return "fastener";
  if (role === "precision_machined") return "axis";
  return "part";
}

function clampTimingPair(start, end) {
  const duration = Math.max(0.06, end - start);
  const clampedStart = THREE.MathUtils.clamp(start, 0, Math.max(0, 0.99 - duration));
  return [clampedStart, Math.min(0.99, clampedStart + duration)];
}

function addTimingOffset(pair, offset) {
  return clampTimingPair(pair[0] + offset, pair[1] + offset);
}

function linearTimingOffset(value, min, max, amount, invert = false) {
  const local = THREE.MathUtils.clamp((value - min) / Math.max(0.0001, max - min), 0, 1);
  return (invert ? 1 - local : local) * amount;
}

function stackTimingOffset(unit) {
  if (unit.assemblyKey === "flow_neg_seat_stack" || unit.assemblyKey === "flow_pos_seat_stack") {
    return linearTimingOffset(seatStackRatio(unit), 0.3, 0.6, 0.06, true);
  }
  if (unit.assemblyKey === "stem_packing_stack") {
    return linearTimingOffset(stemStackRatio(unit), 0.34, 1.08, 0.08, true);
  }
  if (unit.assemblyKey === "bottom_trunnion_stack") {
    return linearTimingOffset(bottomStackRatio(unit), 0.36, 0.58, 0.04, true);
  }
  return 0;
}

function timingForUnit(unit) {
  if (unit.anchor || unit.assemblyKey === "ball_core") return [0, 1];

  const keyedTiming = AXIS_RIG_TIMELINE[unit.assemblyKey];
  if (keyedTiming) return addTimingOffset(keyedTiming, stackTimingOffset(unit));

  if (unit.assemblyKey === "flow_neg_cover_fasteners") return [0.04, 0.2];
  if (unit.assemblyKey === "bracket_fastener_array") return [0.04, 0.22];
  if (unit.assemblyKey === "packing_fastener_array") return [0.08, 0.26];
  if (unit.assemblyKey === "bottom_trunnion_fasteners") return [0.08, 0.26];
  if (unit.assemblyKey === "drain_plug_side") return [0.1, 0.32];

  if (unit.assemblyKey === "flow_neg_cover_shell") return [0.28, 0.48];
  if (unit.assemblyKey === "bracket_connector") return [0.3, 0.52];
  if (unit.assemblyKey === "bottom_trunnion_stack") return [0.42, 0.64];

  if (unit.assemblyKey?.startsWith("flow_") && unit.assemblyKey.includes("spring_ring")) return [0.54, 0.78];
  if (unit.assemblyKey?.startsWith("flow_") && unit.assemblyKey.includes("seat_stack")) return [0.58, 0.86];
  if (unit.assemblyKey === "stem_packing_stack") return [0.58, 0.82];

  if (unit.band === "fastener") return [0.04, 0.26];
  if (unit.role.includes("cast_shell")) return [0.28, 0.5];
  if (unit.band === "axis") return [0.48, 0.76];
  if (unit.band === "core-ring") return [0.58, 0.86];
  if (unit.band === "surface") return [0.5, 0.8];
  return [0.42, 0.78];
}

function timingBlockersForUnit(unit) {
  return AXIS_RIG_BLOCKERS[unit.assemblyKey] || [];
}

function resolveRigTimingDependencies(units) {
  for (let pass = 0; pass < 8; pass += 1) {
    const keyEnds = new Map();
    for (const unit of units) {
      keyEnds.set(unit.assemblyKey, Math.max(keyEnds.get(unit.assemblyKey) || 0, unit.end));
    }

    let changed = false;
    for (const unit of units) {
      const blockers = timingBlockersForUnit(unit);
      let requiredStart = unit.start;
      for (const blockerKey of blockers) {
        if (keyEnds.has(blockerKey)) {
          requiredStart = Math.max(requiredStart, keyEnds.get(blockerKey) + AXIS_RIG_CLEARANCE_DELAY);
        }
      }
      if (requiredStart > unit.start + 0.0001) {
        [unit.start, unit.end] = clampTimingPair(requiredStart, requiredStart + Math.max(0.06, unit.end - unit.start));
        changed = true;
      }
      unit.dependsOn = blockers;
    }
    if (!changed) break;
  }
}

function selfMotionForUnit(unit) {
  const rigAxis = axisVectorForRig(unit.assemblyAxis, unit.axisSign || 1);
  const axis = rigAxis.lengthSq() > 0
    ? rigAxis
    : safeDirection(unit.size.x > unit.size.y && unit.size.x > unit.size.z
    ? new THREE.Vector3(1, 0, 0)
    : unit.size.y > unit.size.z
      ? new THREE.Vector3(0, 1, 0)
      : new THREE.Vector3(0, 0, 1));

  return { axis, turns: 0 };
}

function heroDistanceForUnit(unit) {
  const base = state.modelMaxDim;
  if (unit.role === "polished_ball") return 0;
  if (unit.role === "body_cast_shell") return base * 0.11;
  if (unit.band === "surface") return base * 0.18;
  if (unit.band === "core-ring") return base * 0.28;
  if (unit.band === "axis") return base * 0.42;
  if (unit.band === "shell") return base * 0.46;
  if (unit.role === "spring_steel") return base * 0.46;
  if (unit.band === "fastener") return base * 0.58;
  return base * 0.4;
}

function distanceForAssemblyNode(node) {
  const base = state.modelMaxDim;
  const key = node.key;
  if (node.anchor || key === "ball-core") return 0;
  if (key === "ball-trunnion-core") return base * 0.2;
  if (key.startsWith("seat-seal-system")) return base * 0.3;
  if (key.startsWith("seat-springs")) return base * 0.42;
  if (key.startsWith("end-caps-covers")) return base * 0.46;
  if (key.startsWith("cover-fasteners")) return base * 0.6;
  if (key === "stem-packing-stack") return base * 0.36;
  if (key === "top-bracket-connector") return base * 0.5;
  if (key === "top-bracket-fasteners") return base * 0.62;
  return base * 0.34;
}

function axisScalesSummary() {
  return {
    flowX: Number(state.axisXScale.toFixed(2)),
    stemY: Number(state.axisZScale.toFixed(2)),
    depthZ: Number(state.axisYScale.toFixed(2)),
    spacing: Number(state.axisSpacingScale.toFixed(2))
  };
}

function heroMaxOffset() {
  const axisExtent = Math.max(state.axisXScale, state.axisZScale, state.axisSpacingScale, 1);
  return state.modelMaxDim * HERO_RULES.maxOffsetRatio * axisExtent;
}

function scaledAxisOffset(x, y, z) {
  return new THREE.Vector3(
    x * state.axisXScale * state.axisSpacingScale,
    y * state.axisZScale * state.axisSpacingScale,
    z * state.axisYScale * state.axisSpacingScale
  );
}

function clampTargetPlanarDistance(target, coreOrigin, maxOffset) {
  const result = target.clone();
  const dx = result.x - coreOrigin.x;
  const dz = result.z - coreOrigin.z;
  const planarDistance = Math.hypot(dx, dz);
  if (planarDistance > maxOffset) {
    const scale = maxOffset / planarDistance;
    result.x = coreOrigin.x + dx * scale;
    result.z = coreOrigin.z + dz * scale;
  }
  return result;
}

function sideKeyFromCenter(center, coreOrigin, index = 0) {
  return signedAxis(center.x - coreOrigin.x, index % 2 === 0 ? 1 : -1) > 0 ? "right" : "left";
}

function sideSignFromKey(key, fallback = 1) {
  if (key.includes(":right")) return 1;
  if (key.includes(":left")) return -1;
  return fallback;
}

function inferSmallHardwareAssemblyKey(unit, coreOrigin, index) {
  const text = `${unit.name} ${unit.productName}`.toLowerCase();
  const side = sideKeyFromCenter(unit.center, coreOrigin, index);
  if (text.includes("支架") || text.includes("socket head") || text.includes("washer_sw")) {
    return "top-bracket-fasteners";
  }
  if (text.includes("parallel pins") || text.includes("平键")) return "top-bracket-connector";
  if (unit.role === "spring_steel" || text.includes("弹簧")) return `seat-springs:${side}`;
  if (text.includes("m14") || text.includes("体盖") || text.includes("m10x55")) return `cover-fasteners:${side}`;
  if (unit.center.z > coreOrigin.z + state.modelMaxDim * 0.16) return "top-bracket-fasteners";
  return `cover-fasteners:${side}`;
}

function inferAssemblyKey(unit, coreOrigin, index) {
  const group = unit.animationGroup || "ungrouped";
  const side = sideKeyFromCenter(unit.center, coreOrigin, index);
  if (group === "central-body-anchor") return "central-body-anchor";
  if (unit.role === "polished_ball") return "ball-core";
  if (group === "ball-trunnion-core") return "ball-trunnion-core";
  if (group === "end-caps-covers") return `end-caps-covers:${side}`;
  if (group === "seat-seal-system") return `seat-seal-system:${side}`;
  if (group === "stem-packing-stack") return "stem-packing-stack";
  if (group === "top-bracket-connector") return "top-bracket-connector";
  if (group === "top-bracket-fasteners") return "top-bracket-fasteners";
  if (group === "fasteners-small-hardware") return inferSmallHardwareAssemblyKey(unit, coreOrigin, index);
  return `${group}:${side}`;
}

function parentAssemblyKey(key) {
  if (key.startsWith("cover-fasteners:")) return `end-caps-covers:${key.split(":")[1]}`;
  if (key.startsWith("seat-springs:")) return `seat-seal-system:${key.split(":")[1]}`;
  if (key === "top-bracket-fasteners") return "top-bracket-connector";
  if (key === "top-bracket-connector") return "stem-packing-stack";
  if (key === "stem-packing-stack") return "central-body-anchor";
  if (key === "ball-trunnion-core" || key === "ball-core") return "central-body-anchor";
  if (key.startsWith("end-caps-covers:") || key.startsWith("seat-seal-system:")) return "central-body-anchor";
  if (key === "central-body-anchor") return null;
  return "central-body-anchor";
}

function nodeLabel(key) {
  const labels = {
    "central-body-anchor": "central body anchor",
    "ball-core": "polished ball core",
    "ball-trunnion-core": "ball trunnion core",
    "stem-packing-stack": "stem and packing stack",
    "top-bracket-connector": "top bracket connector",
    "top-bracket-fasteners": "top bracket fasteners"
  };
  if (labels[key]) return labels[key];
  if (key.startsWith("end-caps-covers")) return `end cap cover ${key.split(":")[1]}`;
  if (key.startsWith("cover-fasteners")) return `cover fasteners ${key.split(":")[1]}`;
  if (key.startsWith("seat-seal-system")) return `seat seal system ${key.split(":")[1]}`;
  if (key.startsWith("seat-springs")) return `seat springs ${key.split(":")[1]}`;
  return key;
}

function planForAssemblyNode(node, coreOrigin) {
  const fallbackSign = signedAxis(node.center.x - coreOrigin.x, 1);
  const sideSign = sideSignFromKey(node.key, fallbackSign);
  const plan = {
    axis: "center",
    sign: 0,
    vector: new THREE.Vector3(),
    depth: 0
  };

  if (node.anchor || node.key === "ball-core") return plan;
  if (node.key === "ball-trunnion-core") {
    plan.axis = "z";
    plan.sign = signedAxis(node.center.z - coreOrigin.z, -1);
  } else if (node.key === "stem-packing-stack" || node.key === "top-bracket-connector" || node.key === "top-bracket-fasteners") {
    plan.axis = "z";
    plan.sign = 1;
  } else {
    plan.axis = "x";
    plan.sign = sideSign;
  }

  const distance = distanceForAssemblyNode(node);
  const depth = signedAxis(node.center.y - coreOrigin.y, plan.sign || 1) * state.modelMaxDim * HERO_RULES.depthLayerRatio;
  if (plan.axis === "x") plan.vector.copy(scaledAxisOffset(plan.sign * distance, depth, 0));
  if (plan.axis === "z") plan.vector.copy(scaledAxisOffset(0, depth, plan.sign * distance));
  plan.depth = depth;
  return plan;
}

function expandBox(box, padding) {
  return copyBox(box).expandByScalar(padding);
}

function boxesOverlapOnAxis(boxA, boxB, axis, padding = 0) {
  return boxA.min[axis] <= boxB.max[axis] + padding && boxA.max[axis] >= boxB.min[axis] - padding;
}

function boxesOverlapExceptAxis(boxA, boxB, motionAxis, padding = 0) {
  return ["x", "y", "z"]
    .filter((axis) => axis !== motionAxis)
    .every((axis) => boxesOverlapOnAxis(boxA, boxB, axis, padding));
}

function escapeDistanceAlongAxis(box, blockerBoxes, motionAxis, axisSign, gap, stats) {
  if (motionAxis !== "x" && motionAxis !== "z") return 0;
  let required = 0;
  for (const blockerBox of blockerBoxes) {
    stats.blockingChecks += 1;
    if (!boxesOverlapExceptAxis(box, blockerBox, motionAxis, gap * 0.35)) continue;
    const needed = axisSign > 0
      ? blockerBox.max[motionAxis] - box.min[motionAxis] + gap
      : box.max[motionAxis] - blockerBox.min[motionAxis] + gap;
    if (needed > required) required = needed;
  }
  if (required > 0) {
    stats.blockingResolutions += 1;
    stats.maxBlockingEscape = Math.max(stats.maxBlockingEscape, required);
  }
  return Math.max(0, required);
}

function translatedBox(box, offset) {
  return copyBox(box).translate(offset);
}

function collectAnchorBlockers(nodes) {
  const blockers = [];
  for (const node of nodes.values()) {
    if (!node.anchor && node.key !== "ball-core") continue;
    for (const unit of node.units) blockers.push(expandBox(unit.sourceBox, state.modelMaxDim * HERO_RULES.blockGapRatio * 0.25));
  }
  return blockers;
}

function createAssemblyNodes(units, coreOrigin) {
  const nodes = new Map();
  const ensureNode = (key) => {
    if (nodes.has(key)) return nodes.get(key);
    const node = {
      key,
      label: nodeLabel(key),
      parentKey: parentAssemblyKey(key),
      units: [],
      children: [],
      box: new THREE.Box3(),
      center: coreOrigin.clone(),
      size: new THREE.Vector3(),
      depth: 0,
      anchor: key === "central-body-anchor" || key === "ball-core",
      plan: null,
      ownOffset: new THREE.Vector3(),
      targetOffset: new THREE.Vector3(),
      dependsOn: []
    };
    nodes.set(key, node);
    return node;
  };

  for (const [index, unit] of units.entries()) {
    const key = inferAssemblyKey(unit, coreOrigin, index);
    unit.assemblyKey = key;
    unit.parentAssemblyKey = parentAssemblyKey(key);
    ensureNode(key).units.push(unit);
    if (unit.parentAssemblyKey) ensureNode(unit.parentAssemblyKey);
  }

  for (const node of nodes.values()) {
    if (node.parentKey && nodes.has(node.parentKey)) {
      nodes.get(node.parentKey).children.push(node.key);
    }
    for (const unit of node.units) node.box.union(unit.sourceBox);
    if (node.box.isEmpty()) node.box.setFromCenterAndSize(coreOrigin, new THREE.Vector3(0.001, 0.001, 0.001));
    node.center.copy(node.box.getCenter(new THREE.Vector3()));
    node.size.copy(node.box.getSize(new THREE.Vector3()));
  }

  const assignDepth = (node, depth = 0) => {
    node.depth = depth;
    for (const childKey of node.children) assignDepth(nodes.get(childKey), depth + 1);
  };
  const roots = [...nodes.values()].filter((node) => !node.parentKey || !nodes.has(node.parentKey));
  for (const root of roots) assignDepth(root, 0);

  return nodes;
}

function dependencyKeysForNode(node) {
  if (node.key.startsWith("end-caps-covers:")) return [`cover-fasteners:${node.key.split(":")[1]}`];
  if (node.key.startsWith("seat-seal-system:")) return [`end-caps-covers:${node.key.split(":")[1]}`];
  if (node.key === "top-bracket-connector") return ["top-bracket-fasteners"];
  if (node.key === "stem-packing-stack") return ["top-bracket-connector"];
  return [];
}

function localQueueOffsetForUnit(unit, node, coreOrigin) {
  if (unit.anchor || node.anchor) return new THREE.Vector3();
  const count = node.units.length;
  const isSmall = unit.band === "fastener" || count > 6;
  if (!isSmall && count <= 2) return new THREE.Vector3();

  const columns = isSmall ? 8 : 4;
  const column = unit.indexWithinNode % columns;
  const row = Math.floor(unit.indexWithinNode / columns);
  const centeredColumn = column - (Math.min(count, columns) - 1) / 2;
  const gap = Math.max(state.modelMaxDim * HERO_RULES.laneGapRatio, unit.radius * 2 + state.modelMaxDim * HERO_RULES.minGapRatio);
  const rowStep = state.modelMaxDim * HERO_RULES.rowStepRatio;
  const depthSign = signedAxis(unit.center.y - coreOrigin.y, unit.indexWithinNode % 2 === 0 ? 1 : -1);

  if (node.plan?.axis === "z") {
    return scaledAxisOffset(centeredColumn * gap, depthSign * state.modelMaxDim * 0.06, node.plan.sign * row * rowStep);
  }
  if (node.plan?.axis === "x") {
    return scaledAxisOffset(node.plan.sign * row * rowStep, depthSign * state.modelMaxDim * 0.06, centeredColumn * gap);
  }
  return scaledAxisOffset(centeredColumn * gap * 0.5, depthSign * state.modelMaxDim * 0.04, row * rowStep * 0.5);
}

function solveHierarchicalExplosion(units, coreOrigin, maxOffset) {
  const nodes = createAssemblyNodes(units, coreOrigin);
  const stats = {
    blockingChecks: 0,
    blockingResolutions: 0,
    unresolvedBlocking: 0,
    maxOffsetClamps: 0,
    maxBlockingEscape: 0
  };
  const anchorBlockers = collectAnchorBlockers(nodes);
  const orderedNodes = [...nodes.values()].sort((a, b) => a.depth - b.depth || a.key.localeCompare(b.key));
  const blockGap = state.modelMaxDim * HERO_RULES.blockGapRatio * state.axisSpacingScale;

  for (const node of orderedNodes) {
    node.plan = planForAssemblyNode(node, coreOrigin);
    node.dependsOn = dependencyKeysForNode(node).filter((key) => nodes.has(key));
    if (node.anchor || node.plan.axis === "center") {
      node.ownOffset.set(0, 0, 0);
      node.targetOffset.copy(nodes.get(node.parentKey)?.targetOffset || ZERO);
      continue;
    }

    const parent = nodes.get(node.parentKey);
    const parentOffset = parent?.targetOffset || ZERO;
    const blockerBoxes = [...anchorBlockers];
    if (parent && !parent.anchor) blockerBoxes.push(translatedBox(parent.box, parentOffset));

    const rawDistance = Math.abs(node.plan.axis === "x" ? node.plan.vector.x : node.plan.vector.z);
    const escapeDistance = escapeDistanceAlongAxis(node.box, blockerBoxes, node.plan.axis, node.plan.sign, blockGap, stats);
    const resolvedDistance = Math.max(rawDistance, escapeDistance);
    const resolvedOffset = node.plan.axis === "x"
      ? scaledAxisOffset(node.plan.sign * resolvedDistance, node.plan.depth, 0)
      : scaledAxisOffset(0, node.plan.depth, node.plan.sign * resolvedDistance);

    node.ownOffset.copy(resolvedOffset);
    node.targetOffset.copy(parentOffset).add(node.ownOffset);
    const unclamped = node.center.clone().add(node.targetOffset);
    const clamped = clampTargetPlanarDistance(unclamped, coreOrigin, maxOffset);
    if (clamped.distanceTo(unclamped) > 0.00001) stats.unresolvedBlocking += 1;
    node.targetOffset.copy(clamped.sub(node.center));
  }

  const positions = new Map();
  for (const node of orderedNodes) {
    node.units.sort((a, b) => a.indexWithinNode - b.indexWithinNode);
    for (const unit of node.units) {
      const localOffset = localQueueOffsetForUnit(unit, node, coreOrigin);
      const targetOffset = unit.anchor ? new THREE.Vector3() : node.targetOffset.clone().add(localOffset);
      const targetCenter = clampTargetPlanarDistance(unit.center.clone().add(targetOffset), coreOrigin, maxOffset);
      if (targetCenter.distanceTo(unit.center.clone().add(targetOffset)) > 0.00001) stats.maxOffsetClamps += 1;
      positions.set(unit.id, targetCenter);
      unit.motionAxis = node.plan?.axis || "center";
      unit.axisSign = node.plan?.sign || 0;
      unit.parent = node.parentKey || "root";
      unit.dependsOn = node.dependsOn;
    }
  }

  return { positions, nodes, stats };
}

function unitSearchText(unit) {
  return `${unit.name || ""} ${unit.productName || ""} ${unit.role || ""}`.toLowerCase();
}

function unitHas(unit, needle) {
  return unitSearchText(unit).includes(String(needle).toLowerCase());
}

function unitHasAny(unit, needles) {
  return needles.some((needle) => unitHas(unit, needle));
}

function flowSideKey(unit, coreOrigin) {
  return unit.center.x >= coreOrigin.x ? "pos" : "neg";
}

function flowSideSign(unit, coreOrigin) {
  return flowSideKey(unit, coreOrigin) === "pos" ? 1 : -1;
}

function axisVectorForRig(axis, sign = 1) {
  if (axis === "flowX") return new THREE.Vector3(sign || 1, 0, 0);
  if (axis === "stemY") return new THREE.Vector3(0, 1, 0);
  if (axis === "trunnionYNeg") return new THREE.Vector3(0, -1, 0);
  if (axis === "drainZ") return new THREE.Vector3(0, 0, 1);
  return new THREE.Vector3();
}

function axisScaleForRig(axis) {
  if (axis === "flowX") return state.axisXScale * state.axisSpacingScale;
  if (axis === "stemY" || axis === "trunnionYNeg") return state.axisZScale * state.axisSpacingScale;
  if (axis === "drainZ") return Math.max(0.28, state.axisYScale) * state.axisSpacingScale;
  return 0;
}

function makeRig(id, options) {
  return {
    id,
    label: options.label,
    family: options.family,
    parent: options.parent || "body_anchor",
    axis: options.axis || "hold",
    sign: options.sign || 0,
    slotOrder: options.slotOrder || 0,
    localArray: options.localArray || null,
    confidence: options.confidence || "high",
    anchor: options.anchor || false
  };
}

function classifyAxisRig(unit, coreOrigin) {
  const group = unit.animationGroup || "ungrouped";
  const side = flowSideKey(unit, coreOrigin);
  const sign = flowSideSign(unit, coreOrigin);
  const topFastenerY = coreOrigin.y + state.modelMaxDim * 0.25;
  const bottomFastenerY = coreOrigin.y - state.modelMaxDim * 0.18;

  if (unit.role === "polished_ball") {
    return makeRig("ball_core", {
      label: "polished ball core",
      family: "core",
      parent: "root",
      anchor: true,
      confidence: "high"
    });
  }

  if (unitHasAny(unit, ["堵头", "排污阀垫片"])) {
    return makeRig("drain_plug_side", {
      label: "side drain plug and gasket",
      family: "drain-side-port",
      parent: "body_anchor",
      axis: "drainZ",
      sign: 1,
      slotOrder: 1,
      localArray: "side-port-pair",
      confidence: "medium"
    });
  }

  if (unitHasAny(unit, ["m10x45"]) || (unitHas(unit, "m10 normal") && unit.center.y < bottomFastenerY)) {
    return makeRig("bottom_trunnion_fasteners", {
      label: "bottom trunnion fastener array",
      family: "bottom-fasteners",
      parent: "bottom_trunnion_stack",
      axis: "trunnionYNeg",
      sign: -1,
      slotOrder: 1,
      localArray: "bottom-six-point-array",
      confidence: "high"
    });
  }

  if (unitHas(unit, "固定轴")) {
    return makeRig("bottom_trunnion_stack", {
      label: "bottom trunnion bearing stack",
      family: "trunnion-stack",
      parent: "ball_core",
      axis: "trunnionYNeg",
      sign: -1,
      slotOrder: 2,
      confidence: "medium"
    });
  }

  if (unitHas(unit, "体盖螺柱") || unitHas(unit, "m14 normal")) {
    return makeRig("flow_neg_cover_fasteners", {
      label: "left cover stud and nut array",
      family: "cover-fasteners",
      parent: "flow_neg_cover_shell",
      axis: "flowX",
      sign: -1,
      slotOrder: 1,
      localArray: "cover-flange-ring",
      confidence: "high"
    });
  }

  if (
    group === "body-exterior-shell" ||
    unit.role === "body_cast_shell" ||
    unit.role === "body_flange_machined_faces"
  ) {
    return makeRig("body_exterior_shell", {
      label: "movable body exterior shell",
      family: "body-exterior-shell",
      parent: "ball_core",
      axis: "flowX",
      sign: 1,
      slotOrder: 2,
      confidence: "high"
    });
  }

  if (group === "central-body-anchor") {
    return makeRig("body_anchor", {
      label: "central valve body anchor",
      family: "body-anchor",
      parent: "root",
      anchor: true,
      confidence: "high"
    });
  }

  if (group === "end-caps-covers") {
    return makeRig("flow_neg_cover_shell", {
      label: "left cover shell and machined face",
      family: "cover-shell",
      parent: "body_anchor",
      axis: "flowX",
      sign: -1,
      slotOrder: 2,
      confidence: "high"
    });
  }

  if (unit.role === "spring_steel") {
    return makeRig(`flow_${side}_spring_ring`, {
      label: `${side === "pos" ? "right" : "left"} seat spring ring`,
      family: "seat-spring-ring",
      parent: `flow_${side}_seat_stack`,
      axis: "flowX",
      sign,
      slotOrder: 4,
      localArray: "seat-spring-ring",
      confidence: "high"
    });
  }

  if (group === "seat-seal-system") {
    return makeRig(`flow_${side}_seat_stack`, {
      label: `${side === "pos" ? "right" : "left"} seat seal stack`,
      family: "seat-seal-stack",
      parent: side === "neg" ? "flow_neg_cover_shell" : "body_anchor",
      axis: "flowX",
      sign,
      slotOrder: 3,
      confidence: "high"
    });
  }

  if (unitHas(unit, "socket head")) {
    return makeRig("packing_fastener_array", {
      label: "packing gland screw array",
      family: "packing-fasteners",
      parent: "stem_packing_stack",
      axis: "stemY",
      sign: 1,
      slotOrder: 1,
      localArray: "packing-screw-array",
      confidence: "medium"
    });
  }

  if (
    group === "top-bracket-fasteners" ||
    unitHas(unit, "支架螺柱") ||
    unitHas(unit, "m10x55") ||
    unitHas(unit, "washer_sw") ||
    (unitHas(unit, "m10 normal") && unit.center.y > topFastenerY)
  ) {
    return makeRig("bracket_fastener_array", {
      label: "top bracket stud nut washer array",
      family: "bracket-fasteners",
      parent: "bracket_connector",
      axis: "stemY",
      sign: 1,
      slotOrder: 1,
      localArray: "bracket-hole-array",
      confidence: "medium"
    });
  }

  if (unitHasAny(unit, ["parallel pins", "平键", "连接轴"]) || group === "top-bracket-connector") {
    return makeRig("bracket_connector", {
      label: "top bracket connector stack",
      family: "bracket-connector",
      parent: "stem_packing_stack",
      axis: "stemY",
      sign: 1,
      slotOrder: 3,
      confidence: "high"
    });
  }

  if (group === "stem-packing-stack" || unitHas(unit, "球体轴承")) {
    return makeRig("stem_packing_stack", {
      label: "stem packing vertical stack",
      family: "stem-packing-stack",
      parent: "body_anchor",
      axis: "stemY",
      sign: 1,
      slotOrder: 2,
      confidence: "high"
    });
  }

  if (group === "ball-trunnion-core") {
    return makeRig("bottom_trunnion_stack", {
      label: "bottom trunnion bearing stack",
      family: "trunnion-stack",
      parent: "ball_core",
      axis: "trunnionYNeg",
      sign: -1,
      slotOrder: 2,
      confidence: "medium"
    });
  }

  return makeRig(`fallback_${side}`, {
    label: `fallback ${side} flow-axis part`,
    family: "fallback",
    parent: "body_anchor",
    axis: "flowX",
    sign,
    slotOrder: 9,
    confidence: "low"
  });
}

function seatStackRatio(unit) {
  if (unitHas(unit, "阀座") && !unitHasAny(unit, ["密封圈", "压圈", "盘根"])) return 0.3;
  if (unitHas(unit, "密封圈")) return 0.4;
  if (unitHas(unit, "压圈")) return 0.5;
  return 0.6;
}

function stemStackRatio(unit) {
  if (unitHasAny(unit, ["止推垫", "阀杆轴承", "球体轴承"])) return 0.34;
  if (unitHas(unit, "填料箱垫片")) return 0.5;
  if (unitHas(unit, "填料") && !unitHasAny(unit, ["填料箱", "填料压圈", "填料压盖"])) return 0.62;
  if (unitHas(unit, "填料压圈")) return 0.74;
  if (unitHas(unit, "阀杆") && !unitHas(unit, "阀杆轴承")) return 0.84;
  if (unitHas(unit, "填料压盖")) return 0.94;
  if (unitHas(unit, "填料箱")) return 1.08;
  return 0.72;
}

function bracketStackRatio(unit) {
  if (unitHas(unit, "支架")) return 1.34;
  if (unitHas(unit, "平键")) return 1.5;
  if (unitHas(unit, "连接轴")) return 1.62;
  return 1.42;
}

function topFastenerRatio(unit) {
  if (unit.role === "threaded_dark") return 1.78;
  if (unit.role === "fastener_zinc") return 1.94;
  return 1.86;
}

function bottomStackRatio(unit) {
  if (unitHas(unit, "固定轴垫片")) return 0.36;
  if (unitHas(unit, "固定轴轴承")) return 0.46;
  if (unitHas(unit, "固定轴")) return 0.58;
  return 0.46;
}

function bottomFastenerRatio(unit) {
  if (unit.role === "threaded_dark") return 0.78;
  if (unit.role === "fastener_zinc") return 0.92;
  return 0.86;
}

function rigDistanceForUnit(unit) {
  const base = state.modelMaxDim;
  switch (unit.assemblyKey) {
    case "body_anchor":
    case "ball_core":
      return 0;
    case "body_exterior_shell":
      return base * 0.92;
    case "flow_neg_cover_fasteners":
      return base * (unit.role === "fastener_zinc" ? 1.2 : 1.06);
    case "flow_neg_cover_shell":
      return base * 0.84;
    case "flow_neg_spring_ring":
    case "flow_pos_spring_ring":
      return base * 0.66;
    case "flow_neg_seat_stack":
    case "flow_pos_seat_stack":
      return base * seatStackRatio(unit);
    case "stem_packing_stack":
      return base * stemStackRatio(unit);
    case "packing_fastener_array":
      return base * (unit.role === "threaded_dark" ? 1.18 : 1.3);
    case "bracket_connector":
      return base * bracketStackRatio(unit);
    case "bracket_fastener_array":
      return base * topFastenerRatio(unit);
    case "bottom_trunnion_stack":
      return base * bottomStackRatio(unit);
    case "bottom_trunnion_fasteners":
      return base * bottomFastenerRatio(unit);
    case "drain_plug_side":
      return base * 0.56;
    default:
      return base * 0.48;
  }
}

function targetCenterForAxisRig(unit, coreOrigin) {
  if (unit.anchor || unit.assemblyAxis === "hold") return unit.center.clone();
  const distance = rigDistanceForUnit(unit) * axisScaleForRig(unit.assemblyAxis);
  const target = unit.center.clone();

  if (unit.assemblyAxis === "flowX") {
    target.x = coreOrigin.x + unit.axisSign * distance;
  } else if (unit.assemblyAxis === "stemY") {
    target.y = coreOrigin.y + distance;
  } else if (unit.assemblyAxis === "trunnionYNeg") {
    target.y = coreOrigin.y - distance;
  } else if (unit.assemblyAxis === "drainZ") {
    target.z = coreOrigin.z + distance;
  }

  return target;
}

function rigNodeSort(a, b) {
  return a.slotOrder - b.slotOrder || a.key.localeCompare(b.key);
}

function unitSortWithinRig(a, b) {
  const da = rigDistanceForUnit(a);
  const db = rigDistanceForUnit(b);
  if (Math.abs(da - db) > 0.00001) return da - db;
  return (a.record?.renderNodeIndex || 0) - (b.record?.renderNodeIndex || 0);
}

function solveAxisAssemblyExplosion(units, coreOrigin) {
  const nodes = new Map();
  const stats = {
    blockingChecks: 0,
    blockingResolutions: 0,
    unresolvedBlocking: 0,
    maxOffsetClamps: 0,
    maxBlockingEscape: 0,
    ambiguousUnits: 0,
    localArrayUnits: 0
  };

  for (const unit of units) {
    const rig = classifyAxisRig(unit, coreOrigin);
    unit.assemblyKey = rig.id;
    unit.parentAssemblyKey = rig.parent;
    unit.assemblyAxis = rig.axis;
    unit.axisSign = rig.sign;
    unit.slotOrder = rig.slotOrder;
    unit.localArray = rig.localArray;
    unit.confidence = rig.confidence;
    unit.anchor = rig.anchor;
    if (rig.confidence === "low") stats.ambiguousUnits += 1;
    if (rig.localArray) stats.localArrayUnits += 1;

    if (!nodes.has(rig.id)) {
      nodes.set(rig.id, {
        key: rig.id,
        label: rig.label,
        family: rig.family,
        parentKey: rig.parent,
        units: [],
        box: new THREE.Box3(),
        center: coreOrigin.clone(),
        size: new THREE.Vector3(),
        targetOffset: new THREE.Vector3(),
        axis: rig.axis,
        axisSign: rig.sign,
        slotOrder: rig.slotOrder,
        localArray: rig.localArray,
        confidence: rig.confidence,
        anchor: rig.anchor
      });
    }
    nodes.get(rig.id).units.push(unit);
  }

  for (const node of nodes.values()) {
    node.units.sort(unitSortWithinRig);
    node.units.forEach((unit, index) => {
      unit.indexWithinNode = index;
    });
    for (const unit of node.units) node.box.union(unit.sourceBox);
    if (node.box.isEmpty()) node.box.setFromCenterAndSize(coreOrigin, new THREE.Vector3(0.001, 0.001, 0.001));
    node.center.copy(node.box.getCenter(new THREE.Vector3()));
    node.size.copy(node.box.getSize(new THREE.Vector3()));
  }

  const positions = new Map();
  let maxResolvedOffset = 0;
  for (const node of [...nodes.values()].sort(rigNodeSort)) {
    const targetAverage = new THREE.Vector3();
    for (const unit of node.units) {
      const targetCenter = targetCenterForAxisRig(unit, coreOrigin);
      const targetOffset = targetCenter.clone().sub(unit.center);
      targetAverage.add(targetCenter);
      maxResolvedOffset = Math.max(maxResolvedOffset, targetOffset.length());
      positions.set(unit.id, targetCenter);
      unit.motionAxis = unit.assemblyAxis;
      unit.parent = node.parentKey || "root";
      unit.dependsOn = node.parentKey && nodes.has(node.parentKey) ? [node.parentKey] : [];
    }
    if (node.units.length) targetAverage.multiplyScalar(1 / node.units.length);
    node.targetOffset.copy(targetAverage.sub(node.center));
  }

  stats.maxResolvedOffset = maxResolvedOffset;
  return { positions, nodes, stats };
}

function buildHeroExplodedLayout() {
  modelRoot.updateMatrixWorld(true);
  const coreOrigin = findCoreOrigin();
  const maxOffset = heroMaxOffset();
  const buckets = new Map();

  state.motionUnits = state.meshes.map((mesh, index) => {
    mesh.userData.assembledPosition = mesh.position.clone();
    mesh.userData.assembledQuaternion = mesh.quaternion.clone();

    const box = meshWorldBox(mesh);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const role = mesh.userData.materialRole || "unmatched";
    const record = mesh.userData.nodeRecord || {};
    const sourceGroup = record.animationGroup || record.sourceAnimationGroup || "ungrouped";
    const bucketKey = `${sourceGroup}|${role}|${record.productName || mesh.name}`;
    const bucketIndex = buckets.get(bucketKey) || 0;
    buckets.set(bucketKey, bucketIndex + 1);
    const radius = Math.max(size.x, size.y, size.z, state.modelMaxDim * 0.012) * 0.5;

    return {
      id: `unit-${String(index + 1).padStart(3, "0")}`,
      mesh,
      record,
      role,
      name: mesh.userData.originalName || mesh.name || `mesh-${index + 1}`,
      productName: record.productName || "",
      animationGroup: sourceGroup,
      parent: "root",
      parentAssemblyKey: null,
      assemblyKey: "unassigned",
      assemblyAxis: "hold",
      dependsOn: [],
      band: roleBand(role),
      anchor: role === "polished_ball",
      indexWithinBucket: bucketIndex,
      indexWithinNode: 0,
      slotOrder: 0,
      localArray: null,
      confidence: "unknown",
      sourceBox: copyBox(box),
      center,
      size,
      radius,
      candidateCenter: center.clone(),
      targetCenter: center.clone(),
      targetOffset: ZERO.clone(),
      motionAxis: "center",
      axisSign: 0,
      start: 0,
      end: 1,
      selfAxis: new THREE.Vector3(0, 1, 0),
      selfTurns: 0
    };
  });

  const solved = solveAxisAssemblyExplosion(state.motionUnits, coreOrigin);
  let maxResolvedOffset = 0;
  for (const unit of state.motionUnits) {
    unit.targetCenter = solved.positions.get(unit.id) || unit.center.clone();
    unit.candidateCenter = unit.targetCenter.clone();
    unit.targetOffset = unit.targetCenter.clone().sub(unit.center);
    maxResolvedOffset = Math.max(maxResolvedOffset, unit.targetOffset.length());
    [unit.start, unit.end] = timingForUnit(unit);
    const selfMotion = selfMotionForUnit(unit);
    unit.selfAxis = selfMotion.axis;
    unit.selfTurns = selfMotion.turns;
  }
  resolveRigTimingDependencies(state.motionUnits);

  const hierarchyNodes = [...solved.nodes.values()].map((node) => ({
    id: node.key,
    label: node.label,
    family: node.family,
    parent: node.parentKey || "root",
    slotOrder: node.slotOrder,
    anchor: node.anchor,
    unitCount: node.units.length,
    axis: node.axis,
    axisSign: node.axisSign,
    localArray: node.localArray,
    confidence: node.confidence,
    center: vectorToArray(node.center),
    targetOffset: vectorToArray(node.targetOffset),
    products: [...new Set(node.units.map((unit) => unit.productName).filter(Boolean))]
  }));

  state.heroLayout = {
    status: "computed",
    algorithm: "axis-rigged commercial assembly exploded view",
    originRole: "polished_ball",
    origin: vectorToArray(coreOrigin),
    axes: {
      flowX: [1, 0, 0],
      stemY: [0, 1, 0],
      drainZ: [0, 0, 1],
      screen: "hero camera maps model X to horizontal and model Y to vertical"
    },
    units: state.motionUnits.length,
    minGap: Number((state.modelMaxDim * HERO_RULES.minGapRatio * state.axisSpacingScale).toFixed(5)),
    maxOffset: Number(maxOffset.toFixed(5)),
    axisScales: axisScalesSummary(),
    hierarchyNodes: hierarchyNodes.length,
    blockingChecks: solved.stats.blockingChecks,
    blockingResolutions: solved.stats.blockingResolutions,
    unresolvedBlocking: solved.stats.unresolvedBlocking,
    maxOffsetClamps: solved.stats.maxOffsetClamps,
    maxBlockingEscape: Number(solved.stats.maxBlockingEscape.toFixed(5)),
    ambiguousUnits: solved.stats.ambiguousUnits,
    localArrayUnits: solved.stats.localArrayUnits,
    maxResolvedOffset: Number(maxResolvedOffset.toFixed(5)),
    nodes: hierarchyNodes
  };

  window.__issue8HeroExplosion = exportHeroContract();
}

function exportHeroContract() {
  return {
    productFrame: {
      originRole: "polished_ball",
      origin: state.heroLayout.origin,
      flowX: "model +X/-X valve flow axis, screen horizontal",
      stemY: "model +Y stem and bracket axis, screen vertical",
      drainZ: "model +Z side drain/depth axis",
      cameraRule: "front commercial inspection view; no free-space radial scatter"
    },
    algorithm: {
      name: "axis-rigged-commercial-assembly-explosion",
      sourcePattern: "axis-aligned assembly rig from confirmed issue8 rig table",
      minGap: state.heroLayout.minGap,
      maxOffset: state.heroLayout.maxOffset,
      axisScales: state.heroLayout.axisScales,
      hierarchyNodes: state.heroLayout.hierarchyNodes,
      blockingChecks: state.heroLayout.blockingChecks,
      blockingResolutions: state.heroLayout.blockingResolutions,
      unresolvedBlocking: state.heroLayout.unresolvedBlocking,
      maxOffsetClamps: state.heroLayout.maxOffsetClamps,
      ambiguousUnits: state.heroLayout.ambiguousUnits,
      localArrayUnits: state.heroLayout.localArrayUnits,
      orderRule: "part families bind to fixed slots on flowX, stemY, trunnionYNeg, or drainZ",
      sequenceRule: "outer blockers complete before inner same-axis stacks start",
      collisionRule: "blocking can only delay same-axis dependents or increase same-axis clearance; directions stay fixed by the rig table"
    },
    groups: state.heroLayout.nodes,
    units: state.motionUnits.map((unit) => ({
      id: unit.id,
      role: unit.role,
      objectName: unit.name,
      productName: unit.productName,
      animationGroup: unit.animationGroup,
      assemblyKey: unit.assemblyKey,
      parent: unit.parent,
      band: unit.band,
      anchor: unit.anchor,
      assemblyAxis: unit.assemblyAxis,
      slotOrder: unit.slotOrder,
      localArray: unit.localArray,
      confidence: unit.confidence,
      motionAxis: unit.motionAxis,
      axisSign: unit.axisSign,
      start: unit.start,
      end: unit.end,
      dependsOn: unit.dependsOn,
      center: vectorToArray(unit.center),
      targetCenter: vectorToArray(unit.targetCenter),
      targetOffset: vectorToArray(unit.targetOffset),
      selfMotion: {
        axis: vectorToArray(unit.selfAxis),
        turns: unit.selfTurns
      }
    }))
  };
}

function resetHeroPose() {
  for (const unit of state.motionUnits) {
    unit.mesh.position.copy(unit.mesh.userData.assembledPosition);
    unit.mesh.quaternion.copy(unit.mesh.userData.assembledQuaternion);
  }
}

function unitProgress(unit, progress) {
  return THREE.MathUtils.clamp((progress - unit.start) / Math.max(0.001, unit.end - unit.start), 0, 1);
}

function applyHeroPose(progress) {
  for (const group of state.roleGroups.values()) {
    group.position.set(0, 0, 0);
  }

  for (const unit of state.motionUnits) {
    const localRaw = unitProgress(unit, progress);
    const eased = EASE_IN_OUT(localRaw);
    const basePosition = unit.mesh.userData.assembledPosition;
    unit.mesh.position.copy(basePosition).add(unit.targetOffset.clone().multiplyScalar(eased));

    const baseQuaternion = unit.mesh.userData.assembledQuaternion;
    unit.mesh.quaternion.copy(baseQuaternion);
    if (unit.selfTurns) {
      const rotation = new THREE.Quaternion().setFromAxisAngle(
        unit.selfAxis,
        Math.PI * 2 * unit.selfTurns * localRaw
      );
      unit.mesh.quaternion.multiply(rotation);
    }
  }
  modelRoot.updateMatrixWorld(true);
}

function fallbackDirection(index, total) {
  const angle = (index / Math.max(1, total)) * Math.PI * 2;
  const y = ((index % 5) - 2) * 0.16;
  return new THREE.Vector3(Math.cos(angle), y, Math.sin(angle)).normalize();
}

function roleDirection(role, index, total, roleCenter) {
  const preset = EXPLODE_DIRECTIONS[role];
  const vector = preset
    ? new THREE.Vector3(preset[0], preset[1], preset[2])
    : roleCenter.clone().sub(state.modelCenter);
  if (vector.lengthSq() < 0.000001) return fallbackDirection(index, total);
  return vector.normalize();
}

function computeRoleLayouts() {
  modelRoot.updateMatrixWorld(true);
  const modelBox = new THREE.Box3().setFromObject(modelRoot);
  if (modelBox.isEmpty()) return;

  state.modelCenter.copy(modelBox.getCenter(new THREE.Vector3()));
  state.modelSize.copy(modelBox.getSize(new THREE.Vector3()));
  state.modelMaxDim = Math.max(state.modelSize.x, state.modelSize.y, state.modelSize.z, 0.01);
  state.roleLayout.clear();

  const roles = state.roles.map((job) => job.role);
  const columns = 5;
  const rows = Math.ceil(roles.length / columns);
  const gridX = state.modelMaxDim * 0.95;
  const gridZ = state.modelMaxDim * 0.06;
  const gridY = Math.max(state.modelSize.y * 0.55, state.modelMaxDim * 0.32);

  roles.forEach((role, index) => {
    const group = state.roleGroups.get(role);
    if (!group) return;

    const roleBox = new THREE.Box3().setFromObject(group);
    const roleCenter = roleBox.getCenter(new THREE.Vector3());
    const direction = roleDirection(role, index, roles.length, roleCenter);
    const isAnchor = role === "polished_ball";
    const explodeDistance = isAnchor ? 0 : state.modelMaxDim * (0.55 + (index % 4) * 0.045);
    const exploded = direction.multiplyScalar(explodeDistance);

    const column = index % columns;
    const row = Math.floor(index / columns);
    const slotCenter = state.modelCenter.clone().add(
      new THREE.Vector3(
        (column - (columns - 1) / 2) * gridX,
        ((rows - 1) / 2 - row) * gridY,
        (row - (rows - 1) / 2) * gridZ
      )
    );

    state.roleLayout.set(role, {
      order: index,
      roleCenter,
      exploded,
      materialGrid: slotCenter.sub(roleCenter)
    });
  });
}

function layoutTarget(role, viewMode = state.viewMode) {
  const layout = state.roleLayout.get(role);
  if (!layout || viewMode === "assembled") return ZERO.clone();
  if (viewMode === "hero-exploded") return ZERO.clone();
  if (viewMode === "material-grid") return layout.materialGrid.clone();
  return layout.exploded.clone();
}

function applyLayoutFromProgress() {
  const progress = state.viewMode === "assembled" ? 0 : state.explosionProgress;
  if (state.viewMode === "hero-exploded") {
    applyHeroPose(progress);
    modelRoot.updateMatrixWorld(true);
    return;
  }

  resetHeroPose();
  for (const [role, group] of state.roleGroups.entries()) {
    group.position.copy(layoutTarget(role)).multiplyScalar(progress);
  }
  modelRoot.updateMatrixWorld(true);
}

function syncViewControls() {
  const progress = state.viewMode === "assembled" ? 0 : state.explosionProgress;
  viewEl.value = state.viewMode;
  explodeEl.value = String(progress);
  document.querySelector("#explode-value").textContent = `${Math.round(progress * 100)}%`;
  document.body.dataset.view = state.viewMode;

  const activeMap = {
    "#reset-assembly": state.viewMode === "assembled",
    "#hold-hero-exploded": state.viewMode === "hero-exploded",
    "#hold-exploded": state.viewMode === "exploded",
    "#show-material-grid": state.viewMode === "material-grid"
  };
  for (const [selector, active] of Object.entries(activeMap)) {
    document.querySelector(selector).classList.toggle("is-active", active);
  }
  updateStatus();
}

function syncAxisControls() {
  axisXEl.value = String(state.axisXScale);
  axisZEl.value = String(state.axisZScale);
  axisYEl.value = String(state.axisYScale);
  axisSpacingEl.value = String(state.axisSpacingScale);
  document.querySelector("#axis-x-value").textContent = state.axisXScale.toFixed(2);
  document.querySelector("#axis-z-value").textContent = state.axisZScale.toFixed(2);
  document.querySelector("#axis-y-value").textContent = state.axisYScale.toFixed(2);
  document.querySelector("#axis-spacing-value").textContent = state.axisSpacingScale.toFixed(2);
}

function recomputeHeroLayout(options = {}) {
  state.motion = null;
  for (const group of state.roleGroups.values()) {
    group.position.set(0, 0, 0);
  }
  if (state.motionUnits.length) resetHeroPose();
  buildHeroExplodedLayout();
  applyLayoutFromProgress();
  syncViewControls();
  updateLog();
  if (options.fit && state.viewMode === "hero-exploded") fitVisibleView();
}

function setAxisScales(nextScales = {}, options = {}) {
  if (Object.hasOwn(nextScales, "x")) {
    state.axisXScale = THREE.MathUtils.clamp(Number(nextScales.x) || 0, 0.25, 1.8);
  }
  if (Object.hasOwn(nextScales, "z")) {
    state.axisZScale = THREE.MathUtils.clamp(Number(nextScales.z) || 0, 0.15, 1.6);
  }
  if (Object.hasOwn(nextScales, "y")) {
    state.axisYScale = THREE.MathUtils.clamp(Number(nextScales.y) || 0, 0, 0.55);
  }
  if (Object.hasOwn(nextScales, "spacing")) {
    state.axisSpacingScale = THREE.MathUtils.clamp(Number(nextScales.spacing) || 0, 0.55, 1.8);
  }
  syncAxisControls();
  if (state.meshes.length) recomputeHeroLayout(options);
  else updateLog();
}

function bindAxisControl(element, key) {
  element.addEventListener("input", () => {
    setAxisScales({ [key]: element.value }, { fit: false });
  });
  element.addEventListener("change", () => {
    if (state.viewMode === "hero-exploded") fitVisibleView();
  });
}

function animateToView(viewMode, options = {}) {
  if (!VALID_VIEWS.has(viewMode)) return;
  const duration = state.reducedMotion || options.instant ? 0 : options.duration ?? 1800;
  const currentView = state.viewMode;
  const currentHeroProgress = currentView === "hero-exploded" ? state.explosionProgress : 0;
  const from = new Map();
  const to = new Map();
  const fromMeshes = new Map();
  const toMeshes = new Map();
  for (const [role, group] of state.roleGroups.entries()) {
    from.set(role, group.position.clone());
    to.set(role, layoutTarget(role, viewMode));
  }
  for (const unit of state.motionUnits) {
    fromMeshes.set(unit.id, {
      position: unit.mesh.position.clone(),
      quaternion: unit.mesh.quaternion.clone()
    });
    toMeshes.set(unit.id, {
      position: viewMode === "hero-exploded"
        ? unit.mesh.userData.assembledPosition.clone().add(unit.targetOffset)
        : unit.mesh.userData.assembledPosition.clone(),
      quaternion: unit.mesh.userData.assembledQuaternion.clone()
    });
  }

  if (viewMode === "hero-exploded") {
    state.viewMode = viewMode;

    for (const group of state.roleGroups.values()) {
      group.position.set(0, 0, 0);
    }
    resetHeroPose();

    if (duration === 0) {
      state.motion = null;
      state.explosionProgress = 1;
      applyHeroPose(1);
      syncViewControls();
      updateLog();
      if (options.fit !== false) fitVisibleView();
      return;
    }

    state.explosionProgress = currentHeroProgress;
    applyHeroPose(currentHeroProgress);
    state.motion = {
      start: performance.now(),
      duration,
      targetView: viewMode,
      fitWhenDone: options.fit !== false,
      heroProgressFrom: currentHeroProgress,
      heroProgressTo: 1
    };
    syncViewControls();
    updateLog();
    return;
  }

  state.viewMode = viewMode;
  state.explosionProgress = viewMode === "assembled" ? 0 : 1;

  if (duration === 0) {
    state.motion = null;
    for (const [role, group] of state.roleGroups.entries()) {
      group.position.copy(to.get(role) || ZERO);
    }
    if (viewMode === "hero-exploded") applyHeroPose(1);
    else resetHeroPose();
    syncViewControls();
    updateLog();
    if (options.fit !== false) fitVisibleView();
    return;
  }

  state.motion = {
    start: performance.now(),
    duration,
    from,
    to,
    fromMeshes,
    toMeshes,
    targetView: viewMode,
    fitWhenDone: options.fit !== false,
    stagger: options.stagger !== false
  };
  syncViewControls();
  updateLog();
}

function updateMotion(now) {
  if (!state.motion) return;
  const raw = THREE.MathUtils.clamp((now - state.motion.start) / state.motion.duration, 0, 1);
  if (state.motion.targetView === "hero-exploded") {
    const fromProgress = state.motion.heroProgressFrom ?? 0;
    const toProgress = state.motion.heroProgressTo ?? 1;
    state.explosionProgress = THREE.MathUtils.lerp(fromProgress, toProgress, raw);
    applyHeroPose(state.explosionProgress);
    syncViewControls();

    if (raw >= 1) {
      const shouldFit = state.motion.fitWhenDone;
      state.motion = null;
      state.explosionProgress = 1;
      applyHeroPose(1);
      syncViewControls();
      updateLog();
      if (shouldFit) fitVisibleView();
    }
    return;
  }

  for (const [role, group] of state.roleGroups.entries()) {
    const layout = state.roleLayout.get(role);
    const roleIndex = layout?.order ?? 0;
    const roleCount = Math.max(1, state.roleGroups.size - 1);
    const delay = state.motion.stagger ? (roleIndex / roleCount) * 0.34 : 0;
    const localRaw = THREE.MathUtils.clamp((raw - delay) / Math.max(0.001, 1 - delay), 0, 1);
    const eased = EASE_IN_OUT(localRaw);
    const from = state.motion.from.get(role) || ZERO;
    const to = state.motion.to.get(role) || ZERO;
    group.position.lerpVectors(from, to, eased);
  }

  for (const unit of state.motionUnits) {
    const snapshot = state.motion.fromMeshes.get(unit.id);
    const target = state.motion.toMeshes.get(unit.id);
    if (!snapshot || !target) continue;

    if (state.motion.targetView === "hero-exploded") {
      const localRaw = unitProgress(unit, raw);
      const eased = EASE_IN_OUT(localRaw);
      unit.mesh.position.lerpVectors(snapshot.position, target.position, eased);
      unit.mesh.quaternion.copy(unit.mesh.userData.assembledQuaternion);
      if (unit.selfTurns) {
        const rotation = new THREE.Quaternion().setFromAxisAngle(
          unit.selfAxis,
          Math.PI * 2 * unit.selfTurns * localRaw
        );
        unit.mesh.quaternion.multiply(rotation);
      }
    } else {
      const eased = EASE_IN_OUT(raw);
      unit.mesh.position.lerpVectors(snapshot.position, target.position, eased);
      unit.mesh.quaternion.copy(snapshot.quaternion).slerp(target.quaternion, eased);
    }
  }
  modelRoot.updateMatrixWorld(true);

  if (raw >= 1) {
    const shouldFit = state.motion.fitWhenDone;
    const targetView = state.motion.targetView;
    state.motion = null;
    state.explosionProgress = state.viewMode === "assembled" ? 0 : 1;
    if (targetView === "hero-exploded") applyHeroPose(1);
    else resetHeroPose();
    syncViewControls();
    updateLog();
    if (shouldFit) fitVisibleView();
  }
}

function setExplodeProgress(value) {
  state.motion = null;
  const next = THREE.MathUtils.clamp(Number(value) || 0, 0, 1);
  if (next > 0 && state.viewMode === "assembled") state.viewMode = "hero-exploded";
  state.explosionProgress = state.viewMode === "assembled" ? 0 : next;
  applyLayoutFromProgress();
  syncViewControls();
  updateLog();
}

function setActiveRole(role, options = {}) {
  state.activeRole = role;
  assignMaterials();
  renderRoles();
  if (options.fit !== false) fitVisibleView();
}

function playExplosion() {
  const targetView = state.viewMode === "assembled" ? "hero-exploded" : state.viewMode;
  animateToView("assembled", { instant: true, fit: false });
  requestAnimationFrame(() => animateToView(targetView, { duration: targetView === "hero-exploded" ? 3400 : 1800 }));
}

function updateStatus() {
  const viewLabel = VIEW_LABELS[state.viewMode] || state.viewMode;
  statusEl.textContent = `${viewLabel} / ${state.activeRole} / ${state.mode} / visible ${state.visibleMeshes}`;
}

function assignMaterials() {
  let visible = 0;
  for (const mesh of state.meshes) {
    const role = mesh.userData.materialRole || "unmatched";
    mesh.visible = state.activeRole === "all" || state.activeRole === role;
    if (mesh.visible) visible += 1;
    mesh.material = state.manifests.has(role) ? createMaterial(role) : createFallbackMaterial(role);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    if (mesh.geometry?.attributes?.uv && !mesh.geometry.attributes.uv2) {
      mesh.geometry.setAttribute("uv2", mesh.geometry.attributes.uv);
    }
  }
  state.visibleMeshes = visible;
  updateStatus();
  updateLog();
}

function fitCameraToBox(box) {
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  if (state.viewMode === "hero-exploded") {
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const fitHeightDistance = (Math.max(size.y, 0.01) * 0.5) / Math.tan(fov / 2);
    const fitWidthDistance = (Math.max(size.x, 0.01) * 0.5) / (Math.tan(fov / 2) * Math.max(camera.aspect, 0.1));
    const depthAllowance = Math.max(size.z, 0.01) * 1.35;
    const narrowViewportPadding = camera.aspect < 0.76 ? 1.72 : 1.28;
    const distance = Math.max(0.18, fitHeightDistance, fitWidthDistance, depthAllowance) * narrowViewportPadding;
    camera.up.set(0, 1, 0);
    camera.position.copy(center).add(new THREE.Vector3(distance * 0.02, -distance * 0.08, distance));
    camera.near = Math.max(0.0001, distance / 200);
    camera.far = Math.max(10, distance * 20);
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
    return;
  }

  camera.up.set(0, 1, 0);
  const maxDim = Math.max(size.x, size.y, size.z);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const distance = Math.max(0.18, (maxDim / Math.tan(fov / 2)) * 1.15);
  camera.position.copy(center).add(new THREE.Vector3(distance * 0.86, distance * 0.78, distance * 0.54));
  camera.near = Math.max(0.0001, distance / 200);
  camera.far = Math.max(10, distance * 20);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function fitCamera(object = modelRoot) {
  modelRoot.updateMatrixWorld(true);
  fitCameraToBox(new THREE.Box3().setFromObject(object));
}

function visibleMeshBox() {
  modelRoot.updateMatrixWorld(true);
  const box = new THREE.Box3();
  let hasVisibleMesh = false;
  for (const mesh of state.meshes) {
    if (!mesh.visible) continue;
    box.expandByObject(mesh);
    hasVisibleMesh = true;
  }
  return hasVisibleMesh ? box : null;
}

function fitVisibleView() {
  fitCameraToBox(visibleMeshBox() || new THREE.Box3().setFromObject(modelRoot));
}

function renderRoles() {
  rolesEl.innerHTML = "";
  for (const [index, job] of state.roles.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `role-button${state.activeRole === job.role ? " active" : ""}`;
    button.dataset.role = job.role;
    button.innerHTML = `
      <span class="swatch" style="background:${ROLE_COLORS[index % ROLE_COLORS.length]}"></span>
      <span class="role-name">${job.role}</span>
      <span class="role-count">${job.objectCount ?? ""}</span>
    `;
    button.addEventListener("click", () => {
      setActiveRole(job.role);
    });
    rolesEl.appendChild(button);
  }
}

function updateLog() {
  const assignedRoles = new Set(state.meshes.map((mesh) => mesh.userData.materialRole));
  const missingRoleJobs = [...assignedRoles].filter((role) => role && role !== "unmatched" && !state.manifests.has(role));
  state.match.missingRoleJobs = missingRoleJobs.length;
  const summary = {
    status: "preview-ready",
    glb: GLB_URL,
    viewMode: state.viewMode,
    viewLabel: VIEW_LABELS[state.viewMode] || state.viewMode,
    explosionProgress: Number(state.explosionProgress.toFixed(3)),
    heroExplosion: state.heroLayout,
    reducedMotion: state.reducedMotion,
    mode: state.mode,
    activeRole: state.activeRole,
    roles: state.roles.length,
    roleGroups: state.roleGroups.size,
    roleLayouts: state.roleLayout.size,
    meshes: state.meshes.length,
    visibleMeshes: state.visibleMeshes,
    matchedMeshes: state.match.matched,
    fallbackMeshes: state.match.fallback,
    materialJobs: state.manifests.size,
    declaredMapsPerRole: state.mapAudit.declaredMaps,
    availableMapsPerRole: state.mapAudit.availableMaps,
    textureRequests: state.mapAudit.loadRequests,
    missingTextureLoads: state.mapAudit.missingMaps,
    lightingRig: state.lightingRig,
    missingRoleJobs,
    controls: {
      lightStrength: state.lightStrength,
      envStrength: state.envStrength,
      roughnessScale: state.roughnessScale,
      normalScale: state.normalScale,
      heightScale: state.heightScale,
      axisScales: axisScalesSummary()
    }
  };
  summaryEl.textContent = `${summary.viewLabel} / ${summary.roles} 个材质族 / ${summary.materialJobs} 个 PBR job / ${summary.meshes} 个 mesh`;
  logEl.textContent = JSON.stringify(summary, null, 2);
  window.__issue8PreviewState = summary;
}

function setLightStrength(value) {
  state.lightStrength = Number(value);
  for (const light of previewLights) {
    light.intensity = (light.userData.baseIntensity ?? light.intensity) * state.lightStrength;
  }
  document.querySelector("#light-value").textContent = state.lightStrength.toFixed(2);
  updateLog();
}

function clearMaterialCache() {
  for (const material of state.materials.values()) {
    material.dispose();
  }
  state.materials.clear();
}

function bindControls() {
  viewEl.addEventListener("change", () => {
    animateToView(viewEl.value);
  });
  explodeEl.addEventListener("input", () => {
    setExplodeProgress(explodeEl.value);
  });
  bindAxisControl(axisXEl, "x");
  bindAxisControl(axisZEl, "z");
  bindAxisControl(axisYEl, "y");
  bindAxisControl(axisSpacingEl, "spacing");
  document.querySelector("#reset-assembly").addEventListener("click", () => animateToView("assembled"));
  document.querySelector("#hold-hero-exploded").addEventListener("click", () => animateToView("hero-exploded", { duration: 3200 }));
  document.querySelector("#hold-exploded").addEventListener("click", () => animateToView("exploded"));
  document.querySelector("#show-material-grid").addEventListener("click", () => animateToView("material-grid"));
  document.querySelector("#play-explode").addEventListener("click", playExplosion);
  modeEl.addEventListener("change", () => {
    state.mode = modeEl.value;
    clearMaterialCache();
    assignMaterials();
  });
  mapEl.addEventListener("change", () => {
    state.mapChannel = mapEl.value;
    clearMaterialCache();
    assignMaterials();
  });
  document.querySelector("#show-all").addEventListener("click", () => {
    setActiveRole("all");
  });
  document.querySelector("#fit-view").addEventListener("click", fitVisibleView);
  document.querySelector("#copy-state").addEventListener("click", async () => {
    await navigator.clipboard.writeText(JSON.stringify(window.__issue8PreviewState, null, 2));
  });
  lightEl.addEventListener("input", () => setLightStrength(lightEl.value));
  envEl.addEventListener("input", () => {
    state.envStrength = Number(envEl.value);
    document.querySelector("#env-value").textContent = state.envStrength.toFixed(2);
    clearMaterialCache();
    assignMaterials();
  });
  roughnessEl.addEventListener("input", () => {
    state.roughnessScale = Number(roughnessEl.value);
    document.querySelector("#roughness-value").textContent = state.roughnessScale.toFixed(2);
    clearMaterialCache();
    assignMaterials();
  });
  normalEl.addEventListener("input", () => {
    state.normalScale = Number(normalEl.value);
    document.querySelector("#normal-value").textContent = state.normalScale.toFixed(2);
    clearMaterialCache();
    assignMaterials();
  });
  heightEl.addEventListener("input", () => {
    state.heightScale = Number(heightEl.value);
    document.querySelector("#height-value").textContent = state.heightScale.toFixed(2);
    clearMaterialCache();
    assignMaterials();
  });
  reduceMotionQuery.addEventListener("change", (event) => {
    state.reducedMotion = event.matches;
    updateLog();
  });

  window.__issue8PreviewControls = {
    setRole: (role) => setActiveRole(role),
    setView: (viewMode, instant = true) => animateToView(viewMode, { instant }),
    setProgress: (progress) => setExplodeProgress(progress),
    setAxisScales: (scales, fit = true) => setAxisScales(scales, { fit }),
    playExplosion,
    getHeroContract: () => window.__issue8HeroExplosion,
    setMode: (mode) => {
      state.mode = mode;
      modeEl.value = mode;
      clearMaterialCache();
      assignMaterials();
    }
  };
}

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(rect.width, rect.height, false);
  camera.aspect = rect.width / Math.max(1, rect.height);
  camera.updateProjectionMatrix();
}

async function loadIndependentJobs(jobs) {
  state.roles = jobs.jobs || [];
  await Promise.all(
    state.roles.map(async (job) => {
      const role = job.role;
      const manifest = await fetchJson(`${MATERIAL_JOBS_ROOT}/${role}/pbr-job-manifest.json`);
      state.manifests.set(role, manifest);
      const controlPath = normalizePath(manifest.materialControl?.path);
      if (controlPath) {
        state.materialControls.set(role, await fetchJson(controlPath));
      }
    })
  );
}

async function main() {
  bindControls();
  setLightStrength(state.lightStrength);
  resize();
  window.addEventListener("resize", resize);

  const [nodeMap, jobs, lightingRig] = await Promise.all([
    fetchJson(NODE_MAP_URL),
    fetchJson(JOBS_URL),
    fetchJson(LIGHTING_URL)
  ]);
  await loadIndependentJobs(jobs);
  const roleMaps = buildRoleMaps(nodeMap);
  renderRoles();

  const gltf = await new GLTFLoader().loadAsync(GLB_URL);
  modelRoot.add(gltf.scene);

  let index = 0;
  gltf.scene.traverse((child) => {
    if (!child.isMesh) return;
    const role = resolveRole(child, index, roleMaps);
    child.userData.materialRole = role;
    child.userData.originalName = child.name;
    child.userData.nodeRecord = resolveRecord(child, index, roleMaps);
    if (role && role !== "unmatched") state.match.matched += 1;
    else state.match.fallback += 1;
    state.meshes.push(child);
    index += 1;
  });

  groupMeshesByRole();
  computeRoleLayouts();
  buildHeroExplodedLayout();
  applyLightingRig(lightingRig);
  syncViewControls();
  assignMaterials();
  applyLayoutFromProgress();
  fitVisibleView();

  let readyFrames = 0;
  function animate() {
    updateMotion(performance.now());
    controls.update();
    renderer.render(scene, camera);
    readyFrames += 1;
    if (readyFrames === 8) {
      window.__issue8PreviewReady = true;
      document.body.dataset.ready = "true";
    }
    requestAnimationFrame(animate);
  }
  animate();
}

main().catch((error) => {
  console.error(error);
  statusEl.textContent = "error";
  logEl.textContent = String(error?.stack || error);
  window.__issue8PreviewError = String(error?.stack || error);
});

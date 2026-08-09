#!/usr/bin/env python3
"""Render the fixed-ball-valve hero from the corrected GLB.

This renderer keeps the independent model-cleanup path that proved the source
geometry is sound: import the new GLB directly, clear custom split normals, and
rebuild normals locally. It then layers back the control-stack animation/camera
controls, node-map part binding, and studio lighting/lookdev controls.

It intentionally does not call the old official renderer, material matrix,
flange-face split, or legacy motion/lookdev side effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Quaternion, Vector
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Run with Blender: blender --background --python "
        "scripts/render_fixed_ball_valve_hero.py -- ..."
    ) from exc


DEFAULT_GLB = "assets/models/fixed-ball-valve-new-13f3886b.glb"
DEFAULT_NODE_MAP = "assets-manifest/fixed-ball-valve-node-map.json"
DEFAULT_CONTROL_STACK = "controls/stacks/current.json"
DEFAULT_CONTROL = ""
DEFAULT_LOOKDEV = ""
DEFAULT_OUT_DIR = "renders/fixed-ball-valve-hero-transparent-1080p"
LOOKDEV_ALLOWED_KEYS = ("view", "environment", "grounding", "lighting", "materials", "mapping")

CONTROL: dict[str, Any] = {}
CONTROL_SOURCES: dict[str, Any] = {}
REPO_ROOT: Path = Path.cwd()
MATERIAL_TEXTURE_AUDIT: list[dict[str, Any]] = []
MATERIAL_MAPPING_AUDIT: list[dict[str, Any]] = []
MATERIAL_DIAGNOSTIC_MODE = ""
ISOLATED_MATERIAL_ROLES: set[str] = set()
ISOLATE_ORTHO_SCALE_OVERRIDE: float | None = None
SUPPORTED_NODE_MAP_SCHEMAS = {
    "ztovalve-fixed-ball-valve-node-map/v1",
    "ztovalve-fixed-ball-valve-industrial-uv-node-map/v2",
}

ADVANCED_MATERIAL_FIELDS = (
    "textureSet",
    "roughVar",
    "castGrain",
    "normalStrength",
    "noiseScale",
    "noiseDetail",
    "roughnessNoiseScale",
    "roughnessNoiseDetail",
    "bumpNoiseScale",
    "bumpNoiseDetail",
    "bumpRamp",
    "bumpDistance",
    "bumpStrengthMax",
    "mottleColor",
    "mottleFac",
    "aniso",
    "waveRings",
    "radialRotation",
    "thread",
)

MATERIAL_DEFAULTS: dict[str, tuple[tuple[float, float, float, float], float, float, float, float]] = {
    "body": ((0.37, 0.38, 0.37, 1.0), 1.0, 0.45, 0.52, 0.024),
    "flange": ((0.56, 0.57, 0.56, 1.0), 1.0, 0.22, 0.76, 0.002),
    "machined": ((0.52, 0.53, 0.52, 1.0), 1.0, 0.20, 0.74, 0.003),
    "ball": ((0.45, 0.46, 0.45, 1.0), 1.0, 0.10, 0.82, 0.0),
    "seal": ((0.024, 0.026, 0.023, 1.0), 0.02, 0.82, 0.18, 0.008),
    "fastener": ((0.32, 0.33, 0.32, 1.0), 1.0, 0.28, 0.68, 0.008),
    "threaded": ((0.32, 0.33, 0.32, 1.0), 1.0, 0.25, 0.70, 0.008),
    "spring": ((0.28, 0.29, 0.28, 1.0), 1.0, 0.32, 0.58, 0.008),
    "top": ((0.34, 0.35, 0.34, 1.0), 1.0, 0.40, 0.56, 0.012),
    "dark": ((0.075, 0.08, 0.074, 1.0), 0.72, 0.52, 0.32, 0.012),
    "reveal_body": ((0.37, 0.38, 0.37, 1.0), 1.0, 0.45, 0.52, 0.024),
    "reveal_dark": ((0.075, 0.08, 0.074, 1.0), 0.72, 0.52, 0.32, 0.012),
    "flange_reveal": ((0.56, 0.57, 0.56, 1.0), 1.0, 0.22, 0.76, 0.0),
}

DEFAULT_MATERIAL_KEYS = (
    "body",
    "flange",
    "machined",
    "ball",
    "seal",
    "fastener",
    "threaded",
    "spring",
    "top",
    "dark",
)
REVEAL_MATERIAL_KEYS = ("reveal_body", "reveal_dark", "flange_reveal")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--glb", default="")
    parser.add_argument("--node-map", default="")
    parser.add_argument("--control-stack", default=DEFAULT_CONTROL_STACK)
    parser.add_argument("--control", default=DEFAULT_CONTROL)
    parser.add_argument("--lookdev-control", default=DEFAULT_LOOKDEV)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--out-root", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--frame-count", type=int, default=0)
    parser.add_argument("--frame-list", default="")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--samples", type=int, default=0)
    parser.add_argument("--no-clear", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--material-diagnostic-mode", choices=("", "checker", "texture-only"), default="")
    parser.add_argument("--isolate-material-role", default="")
    parser.add_argument("--isolate-fit-scale", type=float, default=1.85)
    parser.add_argument("--isolate-min-ortho-scale", type=float, default=0.08)

    # Kept for command compatibility. The corrected independent chain does not
    # read STEP input or old geometry split controls.
    parser.add_argument("--step", default="")

    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    return parser.parse_args(argv)


def repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def rel(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def control_path(keys: tuple[str, ...], default: Any) -> Any:
    node: Any = CONTROL
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def feature_enabled(name: str, default: bool = True) -> bool:
    value = control_path(("features", name, "enabled"), None)
    if value is not None:
        return bool(value)
    return default


def control_source_record(repo_root: Path, path: Path, schema: str | None = None, name: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": rel(repo_root, path), "sha256": sha256(path)}
    if schema:
        record["schema"] = schema
    if name:
        record["name"] = name
    return record


def control_body(doc: Any, key: str) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    value = doc.get(key, doc)
    if not isinstance(value, dict):
        return {}
    if key == "materials":
        body = dict(value)
        renderer_support = doc.get("rendererSupport")
        if isinstance(renderer_support, dict):
            body["_rendererSupport"] = renderer_support
        material_aliases = doc.get("materialAliases")
        if isinstance(material_aliases, dict):
            body["_materialAliases"] = material_aliases
        return body
    return value


def source_doc(repo_root: Path, source_path: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = repo_path(repo_root, source_path)
    doc = read_json(path)
    schema = doc.get("schema") if isinstance(doc, dict) else None
    name = doc.get("name", doc.get("variant")) if isinstance(doc, dict) else None
    return path, doc, control_source_record(repo_root, path, schema, name)


def filtered_lookdev(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}, {"appliedTopLevelKeys": [], "ignoredTopLevelKeys": []}
    applied = {key: raw[key] for key in LOOKDEV_ALLOWED_KEYS if key in raw}
    ignored = sorted(key for key in raw if key not in LOOKDEV_ALLOWED_KEYS)
    return applied, {
        "allowedTopLevelKeys": list(LOOKDEV_ALLOWED_KEYS),
        "appliedTopLevelKeys": sorted(applied),
        "ignoredTopLevelKeys": ignored,
    }


def load_control_stack(repo_root: Path, stack_path_arg: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    stack_path = repo_path(repo_root, stack_path_arg)
    stack = read_json(stack_path)
    if not isinstance(stack, dict) or stack.get("schema") != "ztovalve-control-stack/v1":
        raise RuntimeError(f"Unexpected control stack schema in {stack_path}")

    sources: dict[str, Any] = {
        "stack": control_source_record(repo_root, stack_path, stack.get("schema"), stack.get("name")),
    }
    combined: dict[str, Any] = {
        "schema": "ztovalve-composed-render-control/v1",
        "controlStack": {"path": rel(repo_root, stack_path), "name": stack.get("name")},
    }

    def load_named(label: str, source_path: str) -> dict[str, Any]:
        path, doc, record = source_doc(repo_root, source_path)
        sources[label] = record
        return doc

    asset = stack.get("asset", {})
    if isinstance(asset, dict):
        combined["asset"] = dict(asset)

    diagnostic = stack.get("diagnostic", {})
    if isinstance(diagnostic, dict) and diagnostic:
        combined["diagnostic"] = dict(diagnostic)

    parts = stack.get("parts", {})
    if isinstance(parts, dict):
        combined["parts"] = {}
        if parts.get("nodeMap"):
            combined["parts"]["nodeMap"] = parts["nodeMap"]
            node_map_path = repo_path(repo_root, str(parts["nodeMap"]))
            sources["parts.nodeMap"] = control_source_record(repo_root, node_map_path)
        if parts.get("roles"):
            roles_doc = load_named("parts.roles", str(parts["roles"]))
            combined["parts"]["roles"] = roles_doc

    render_ref = stack.get("render")
    if render_ref:
        render_doc = load_named("render", str(render_ref))
        combined["render"] = render_doc
        if "sequence" in render_doc:
            combined["sequence"] = render_doc["sequence"]
        if "output" in render_doc:
            combined["output"] = render_doc["output"]

    lookdev: dict[str, Any] = {}
    lookdev_refs = stack.get("lookdev", {})
    if isinstance(lookdev_refs, dict):
        for key in LOOKDEV_ALLOWED_KEYS:
            if key in lookdev_refs:
                doc = load_named(f"lookdev.{key}", str(lookdev_refs[key]))
                lookdev[key] = control_body(doc, key)
    combined["lookdev"] = lookdev
    lookdev_audit = {
        "allowedTopLevelKeys": list(LOOKDEV_ALLOWED_KEYS),
        "appliedTopLevelKeys": sorted(lookdev),
        "ignoredTopLevelKeys": [],
    }

    animation_refs = stack.get("animation", {})
    if isinstance(animation_refs, dict):
        if animation_refs.get("features"):
            feature_doc = load_named("animation.features", str(animation_refs["features"]))
            combined["features"] = control_body(feature_doc, "features")
        if animation_refs.get("motion"):
            motion_doc = load_named("animation.motion", str(animation_refs["motion"]))
            if "animation" in motion_doc:
                combined["animation"] = dict(motion_doc["animation"])
            if "morph" in motion_doc:
                combined["morph"] = motion_doc["morph"]
            if "motionDesign" in motion_doc:
                combined["motionDesign"] = motion_doc["motionDesign"]
        if animation_refs.get("camera"):
            camera_doc = load_named("animation.camera", str(animation_refs["camera"]))
            camera_timing = control_body(camera_doc, "timing")
            if camera_timing:
                combined.setdefault("animation", {})["camera"] = camera_timing
            combined["camera"] = control_body(camera_doc, "camera")

    return combined, {"schema": "ztovalve-composed-lookdev-control/v1", "lookdev": lookdev}, lookdev_audit, sources


def parse_frame_list(value: str, frame_count: int) -> list[int] | None:
    if not value.strip():
        return None
    frames: list[int] = []
    for raw in value.split(","):
        frame = int(raw.strip())
        if frame < 0 or frame >= frame_count:
            raise RuntimeError(f"Frame {frame} is outside 0..{frame_count - 1}.")
        if frame not in frames:
            frames.append(frame)
    return frames


def duplicate_base_name(name: str) -> str:
    return re.sub(r"\.\d{3}$", "", name)


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.lights, bpy.data.cameras):
        for item in list(collection):
            if item.users == 0:
                collection.remove(item)


def clear_previous_frames(frames_dir: Path) -> None:
    if not frames_dir.is_dir():
        return
    for path in frames_dir.glob("*.png"):
        path.unlink()


def look_at(obj: Any, target: Vector, roll_radians: float = 0.0) -> None:
    direction = target - obj.location
    quat = direction.to_track_quat("-Z", "Y")
    if roll_radians:
        quat = quat @ Quaternion((0, 0, 1), roll_radians)
    obj.rotation_euler = quat.to_euler()


def color4(value: Any, default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]), 1.0)
    return default


def optional_color4(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]), 1.0)
    return None


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def set_input(node: Any, names: tuple[str, ...], value: float) -> bool:
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


def fac_output(node: Any) -> Any:
    return node.outputs["Fac"] if "Fac" in node.outputs else node.outputs[0]


def add_weighted_scalar(
    nodes: Any,
    links: Any,
    current: Any | None,
    source: Any,
    weight: float,
    name: str,
) -> Any:
    weighted = source
    if abs(weight - 1.0) > 0.0001:
        multiply = nodes.new(type="ShaderNodeMath")
        multiply.name = f"{name}_weight"
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = weight
        links.new(source, multiply.inputs[0])
        weighted = multiply.outputs["Value"]
    if current is None:
        return weighted
    add = nodes.new(type="ShaderNodeMath")
    add.name = f"{name}_add"
    add.operation = "ADD"
    links.new(current, add.inputs[0])
    links.new(weighted, add.inputs[1])
    return add.outputs["Value"]


def blend_scalar(
    nodes: Any,
    links: Any,
    base: Any,
    source: Any,
    strength: float,
    name: str,
) -> Any:
    strength = clamp(strength, 0.0, 1.0)
    if strength <= 0.0001:
        return base
    if strength >= 0.9999:
        return source
    base_weight = nodes.new(type="ShaderNodeMath")
    base_weight.name = f"{name}_base_weight"
    base_weight.operation = "MULTIPLY"
    base_weight.inputs[1].default_value = 1.0 - strength
    links.new(base, base_weight.inputs[0])

    source_weight = nodes.new(type="ShaderNodeMath")
    source_weight.name = f"{name}_source_weight"
    source_weight.operation = "MULTIPLY"
    source_weight.inputs[1].default_value = strength
    links.new(source, source_weight.inputs[0])

    add = nodes.new(type="ShaderNodeMath")
    add.name = f"{name}_blend"
    add.operation = "ADD"
    links.new(base_weight.outputs["Value"], add.inputs[0])
    links.new(source_weight.outputs["Value"], add.inputs[1])
    return add.outputs["Value"]


def color_value_node(nodes: Any, color: tuple[float, float, float, float], name: str) -> Any:
    rgb = nodes.new(type="ShaderNodeRGB")
    rgb.name = name
    rgb.outputs["Color"].default_value = color
    return rgb.outputs["Color"]


def blend_color(
    nodes: Any,
    links: Any,
    base_color: tuple[float, float, float, float],
    base_signal: Any | None,
    source_signal: Any,
    strength: float,
    name: str,
) -> Any:
    strength = clamp(strength, 0.0, 1.0)
    if strength >= 0.9999:
        return source_signal
    if strength <= 0.0001:
        return base_signal or color_value_node(nodes, base_color, f"{name}_base_color")
    mix = nodes.new(type="ShaderNodeMixRGB")
    mix.name = name
    mix.blend_type = "MIX"
    mix.inputs["Fac"].default_value = strength
    if base_signal is not None:
        links.new(base_signal, mix.inputs["Color1"])
    else:
        mix.inputs["Color1"].default_value = base_color
    links.new(source_signal, mix.inputs["Color2"])
    return mix.outputs["Color"]


def color_to_scalar(nodes: Any, links: Any, source: Any, name: str) -> Any:
    convert = nodes.new(type="ShaderNodeRGBToBW")
    convert.name = name
    links.new(source, convert.inputs["Color"])
    return convert.outputs["Val"]


def ramp_config_value(ramp_config: Any, keys: tuple[str, ...], default: float) -> float:
    if isinstance(ramp_config, dict):
        for key in keys:
            if key in ramp_config:
                value = optional_float(ramp_config.get(key))
                if value is not None:
                    return value
    return default


def add_value_ramp(nodes: Any, links: Any, source: Any, name: str, ramp_config: Any) -> Any:
    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.name = name
    black = clamp(ramp_config_value(ramp_config, ("black", "blackPosition", "fromMin"), 0.0), 0.0, 1.0)
    white = clamp(ramp_config_value(ramp_config, ("white", "whitePosition", "fromMax"), 1.0), 0.0, 1.0)
    if white < black:
        black, white = white, black
    ramp.color_ramp.elements[0].position = black
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].position = white
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(source, ramp.inputs["Fac"])
    return color_to_scalar(nodes, links, ramp.outputs["Color"], f"{name}_bw")


def add_wave_texture(nodes: Any, name: str, wave_type: str, scale: float, distortion: float) -> Any:
    wave = nodes.new(type="ShaderNodeTexWave")
    wave.name = name
    if hasattr(wave, "wave_type"):
        wave.wave_type = wave_type
    if wave_type == "RINGS" and hasattr(wave, "rings_direction"):
        wave.rings_direction = "SPHERICAL"
    if wave_type == "BANDS" and hasattr(wave, "bands_direction"):
        wave.bands_direction = "Z"
    if "Scale" in wave.inputs:
        wave.inputs["Scale"].default_value = scale
    if "Distortion" in wave.inputs:
        wave.inputs["Distortion"].default_value = distortion
    return wave


def texture_value(texture_set: dict[str, Any] | None, key: str, default: float) -> float:
    if not isinstance(texture_set, dict):
        return default
    value = texture_set.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def texture_color(
    texture_set: dict[str, Any] | None,
    key: str,
    default: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    if not isinstance(texture_set, dict):
        return default
    value = texture_set.get(key)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]), 1.0)
    return default


def texture_map_path(texture_set: dict[str, Any] | None, keys: tuple[str, ...]) -> Path | None:
    if not isinstance(texture_set, dict):
        return None
    for key in keys:
        value = texture_set.get(key)
        if isinstance(value, str) and value.strip():
            return repo_path(REPO_ROOT, value.strip())
    return None


def set_image_color_space(image: Any, color_space: str) -> None:
    candidates = (color_space, "Non-Color" if color_space == "Non-Color Data" else color_space)
    for candidate in candidates:
        try:
            image.colorspace_settings.name = candidate
            return
        except (TypeError, ValueError):
            continue


def mapping_control() -> dict[str, Any]:
    mapping = control_path(("lookdev", "mapping"), {})
    return mapping if isinstance(mapping, dict) else {}


def mapping_for_role(role_key: str) -> dict[str, Any]:
    mapping = mapping_control()
    resolved: dict[str, Any] = {}
    default = mapping.get("default")
    if isinstance(default, dict):
        resolved.update(default)
    roles = mapping.get("roles")
    if isinstance(roles, dict):
        role_mapping = roles.get(role_key)
        if isinstance(role_mapping, dict):
            resolved.update(role_mapping)
    return resolved


def mapping_diagnostic_mode(role_key: str, role_mapping: dict[str, Any]) -> str:
    if MATERIAL_DIAGNOSTIC_MODE:
        return MATERIAL_DIAGNOSTIC_MODE
    stack_mode = control_path(("diagnostic", "materialMode"), "")
    if isinstance(stack_mode, str) and stack_mode in {"checker", "texture-only"}:
        return stack_mode
    mode = role_mapping.get("materialMode")
    if isinstance(mode, str) and mode in {"checker", "texture-only"}:
        return mode
    diagnostic = mapping_control().get("diagnostic")
    if isinstance(diagnostic, dict) and bool(diagnostic.get("enabled", False)):
        mode = diagnostic.get("materialMode")
        if isinstance(mode, str) and mode in {"checker", "texture-only"}:
            return mode
    return ""


def mapped_texture_value(
    texture_set: dict[str, Any] | None,
    role_mapping: dict[str, Any] | None,
    key: str,
    default: float,
) -> float:
    if isinstance(role_mapping, dict) and key in role_mapping:
        value = role_mapping.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return texture_value(texture_set, key, default)


def texture_coordinate_name(texcoord: Any, role_mapping: dict[str, Any]) -> tuple[str, str | None]:
    requested = str(role_mapping.get("coordinate", role_mapping.get("coordinateSource", "Generated"))).strip()
    if requested:
        candidates = [requested[:1].upper() + requested[1:]]
    else:
        candidates = []
    candidates.extend(["Generated", "Object", "UV"])
    for candidate in candidates:
        if candidate in texcoord.outputs:
            return candidate, None if candidate == requested else requested or None
    return next(iter(texcoord.outputs.keys())), requested or None


def projection_for_mapping(role_mapping: dict[str, Any]) -> str:
    projection = str(role_mapping.get("projection", "")).upper()
    if projection:
        return projection
    mode = str(role_mapping.get("mode", "")).lower()
    if mode in {"box", "triplanar", "triplanar-like"}:
        return "BOX"
    if mode in {"sphere", "spherical"}:
        return "SPHERE"
    if mode in {"tube", "cylindrical"}:
        return "TUBE"
    return "FLAT"


def apply_image_projection(node: Any, role_mapping: dict[str, Any]) -> dict[str, Any]:
    requested = projection_for_mapping(role_mapping)
    applied = None
    error = None
    if hasattr(node, "projection"):
        try:
            node.projection = requested
            applied = node.projection
        except (TypeError, ValueError) as exc:
            error = str(exc)
    blend = role_mapping.get("blend", role_mapping.get("projectionBlend", None))
    if hasattr(node, "projection_blend") and blend is not None:
        try:
            node.projection_blend = clamp(float(blend), 0.0, 1.0)
        except (TypeError, ValueError):
            pass
    return {"requestedProjection": requested, "appliedProjection": applied, "projectionError": error}


def texture_strength(texture_set: dict[str, Any] | None, role_mapping: dict[str, Any] | None, key: str, default: float, texture_only: bool) -> float:
    if texture_only:
        return 1.0
    return mapped_texture_value(texture_set, role_mapping, key, default)


def audit_mesh_uv_layers(objects: list[Any]) -> dict[str, Any]:
    with_uv = 0
    without_uv = 0
    samples: list[dict[str, Any]] = []
    for obj in objects:
        layers = list(getattr(obj.data, "uv_layers", []))
        layer_count = len(layers)
        if layer_count:
            with_uv += 1
        else:
            without_uv += 1
        if len(samples) < 24:
            samples.append(
                {
                    "objectName": obj.name,
                    "uvLayerCount": layer_count,
                    "uvLayerNames": [layer.name for layer in layers],
                }
            )
    return {
        "meshObjects": len(objects),
        "meshWithUvLayers": with_uv,
        "meshWithoutUvLayers": without_uv,
        "uvCoverageRatio": round(with_uv / max(1, len(objects)), 6),
        "sample": samples,
    }


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    metallic: float,
    roughness: float,
    specular: float,
    bump_strength: float = 0.0,
    rough_var: float = 0.0,
    cast_grain: bool = False,
    mottle_color: tuple[float, float, float, float] | None = None,
    mottle_fac: float = 0.0,
    aniso: float = 0.0,
    wave_rings: float = 0.0,
    radial_rotation: bool = False,
    thread: float = 0.0,
    noise_scale: float | None = None,
    noise_detail: float | None = None,
    roughness_noise_scale: float | None = None,
    roughness_noise_detail: float | None = None,
    bump_noise_scale: float | None = None,
    bump_noise_detail: float | None = None,
    bump_ramp: dict[str, Any] | None = None,
    bump_distance: float | None = None,
    bump_strength_max: float = 0.24,
    texture_set: dict[str, Any] | None = None,
    texture_mapping: dict[str, Any] | None = None,
    diagnostic_mode: str = "",
    role_key: str = "",
    alpha_driver: bool = False,
) -> Any:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = color
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    for spec_name in ("Specular IOR Level", "Specular"):
        if spec_name in bsdf.inputs:
            bsdf.inputs[spec_name].default_value = specular
            break

    set_input(bsdf, ("Anisotropic",), clamp(aniso, 0.0, 1.0))
    if radial_rotation:
        set_input(bsdf, ("Anisotropic Rotation",), 0.25)

    rough_var = max(0.0, rough_var)
    mottle_fac = clamp(mottle_fac, 0.0, 1.0)
    wave_rings = max(0.0, wave_rings)
    thread = max(0.0, thread)
    noise_scale = max(0.001, noise_scale) if noise_scale is not None else None
    noise_detail = max(0.0, noise_detail) if noise_detail is not None else None
    roughness_noise_scale = max(0.001, roughness_noise_scale) if roughness_noise_scale is not None else None
    roughness_noise_detail = max(0.0, roughness_noise_detail) if roughness_noise_detail is not None else None
    bump_noise_scale = max(0.001, bump_noise_scale) if bump_noise_scale is not None else None
    bump_noise_detail = max(0.0, bump_noise_detail) if bump_noise_detail is not None else None
    bump_distance = max(0.0, bump_distance) if bump_distance is not None else None
    bump_strength_max = max(0.0, bump_strength_max)
    texture_set = texture_set if isinstance(texture_set, dict) else None
    role_mapping = texture_mapping if isinstance(texture_mapping, dict) else {}
    diagnostic_mode = diagnostic_mode if diagnostic_mode in {"checker", "texture-only"} else ""
    texture_only = diagnostic_mode == "texture-only"
    checker_mode = diagnostic_mode == "checker"
    if diagnostic_mode:
        bump_strength = 0.0
        rough_var = 0.0
        cast_grain = False
        mottle_color = None
        mottle_fac = 0.0
        wave_rings = 0.0
        thread = 0.0

    should_audit_mapping = bool(role_mapping or texture_set or diagnostic_mode)
    texture_audit: dict[str, Any] | None = None
    mapping_audit: dict[str, Any] = {
        "material": name,
        "roleKey": role_key or name,
        "mode": role_mapping.get("mode", "generated"),
        "diagnosticMode": diagnostic_mode or "styled",
        "mappingIntent": role_mapping.get("intent"),
        "imageProjections": [],
    }
    if should_audit_mapping:
        MATERIAL_MAPPING_AUDIT.append(mapping_audit)
    mapping_output = None
    if texture_set:
        texture_audit = {
            "material": name,
            "roleKey": role_key or name,
            "source": texture_set.get("source"),
            "assetId": texture_set.get("assetId"),
            "sourceUrl": texture_set.get("sourceUrl"),
            "license": texture_set.get("license"),
            "loadedMaps": [],
            "missingMaps": [],
        }
        MATERIAL_TEXTURE_AUDIT.append(texture_audit)

    def texture_vector() -> Any:
        nonlocal mapping_output
        if mapping_output is not None:
            return mapping_output
        texcoord = nodes.new(type="ShaderNodeTexCoord")
        texcoord.name = "zt_texture_coordinates"
        mapping = nodes.new(type="ShaderNodeMapping")
        mapping.name = "zt_texture_mapping"
        coord_name, fallback_from = texture_coordinate_name(texcoord, role_mapping)
        links.new(texcoord.outputs[coord_name], mapping.inputs["Vector"])
        if checker_mode:
            try:
                scale = max(0.001, float(role_mapping.get("checkerVectorScale", 1.0)))
            except (TypeError, ValueError):
                scale = 1.0
        else:
            scale = max(0.001, mapped_texture_value(texture_set, role_mapping, "scale", 1.0))
        if "Scale" in mapping.inputs:
            mapping.inputs["Scale"].default_value[0] = scale
            mapping.inputs["Scale"].default_value[1] = scale
            mapping.inputs["Scale"].default_value[2] = scale
        mapping_audit["coordinate"] = coord_name
        mapping_audit["requestedCoordinate"] = role_mapping.get("coordinate", role_mapping.get("coordinateSource", "Generated"))
        if fallback_from:
            mapping_audit["coordinateFallbackFrom"] = fallback_from
        mapping_audit["scale"] = scale
        mapping_audit["projection"] = projection_for_mapping(role_mapping)
        mapping_audit["blend"] = role_mapping.get("blend", role_mapping.get("projectionBlend"))
        mapping_output = mapping.outputs["Vector"]
        return mapping_output

    def image_texture_node(label: str, keys: tuple[str, ...], color_space: str) -> Any | None:
        if not texture_set:
            return None
        path = texture_map_path(texture_set, keys)
        if path is None:
            return None
        if not path.is_file():
            if texture_audit is not None:
                texture_audit["missingMaps"].append({"map": label, "path": path.as_posix()})
            raise RuntimeError(f"Texture map declared for {name}/{label} but file is missing: {path}")
        image = bpy.data.images.load(str(path), check_existing=True)
        set_image_color_space(image, color_space)
        node = nodes.new(type="ShaderNodeTexImage")
        node.name = f"zt_texture_{label}"
        node.image = image
        if hasattr(node, "extension"):
            node.extension = "REPEAT"
        links.new(texture_vector(), node.inputs["Vector"])
        projection_record = apply_image_projection(node, role_mapping)
        mapping_audit["imageProjections"].append({"map": label, **projection_record})
        if texture_audit is not None:
            texture_audit["loadedMaps"].append(
                {
                    "map": label,
                    "path": rel(REPO_ROOT, path),
                    "sha256": sha256(path),
                    "fileSizeBytes": path.stat().st_size,
                    "dimensions": [int(image.size[0]), int(image.size[1])],
                    "colorSpace": image.colorspace_settings.name,
                    "node": node.name,
                }
            )
        return node

    if checker_mode:
        checker = nodes.new(type="ShaderNodeTexChecker")
        checker.name = "zt_mapping_checker"
        checker_scale = max(0.001, float(role_mapping.get("checkerScale", 10.0)))
        if "Scale" in checker.inputs:
            checker.inputs["Scale"].default_value = checker_scale
        if "Color1" in checker.inputs:
            checker.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)
        if "Color2" in checker.inputs:
            checker.inputs["Color2"].default_value = (0.02, 0.025, 0.03, 1.0)
        links.new(texture_vector(), checker.inputs["Vector"])
        links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.62
        mapping_audit["checkerScale"] = checker_scale
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        return mat

    base_color_signal = None
    base_texture = image_texture_node("base_color", ("baseColor", "basecolor", "color"), "sRGB")
    if base_texture is not None:
        texture_color_signal = base_texture.outputs["Color"]
        tint = texture_color(texture_set, "colorTint")
        tint_strength = clamp(texture_value(texture_set, "tintStrength", 1.0), 0.0, 1.0)
        if not texture_only and tint is not None and tint_strength > 0.0:
            tint_mix = nodes.new(type="ShaderNodeMixRGB")
            tint_mix.name = "zt_texture_color_tint"
            tint_mix.blend_type = "MULTIPLY"
            tint_mix.inputs["Fac"].default_value = tint_strength
            links.new(texture_color_signal, tint_mix.inputs["Color1"])
            tint_mix.inputs["Color2"].default_value = tint
            texture_color_signal = tint_mix.outputs["Color"]
        if texture_only:
            base_color_signal = texture_color_signal
        else:
            base_color_signal = blend_color(
                nodes,
                links,
                color,
                base_color_signal,
                texture_color_signal,
                mapped_texture_value(texture_set, role_mapping, "baseColorStrength", 1.0),
                "zt_texture_base_color_blend",
            )

    ao_texture = image_texture_node("ao", ("ao", "ambientOcclusion"), "Non-Color")
    if ao_texture is not None and "Color" in ao_texture.outputs:
        ao_strength = clamp(
            float(role_mapping.get("aoStrength", 0.55)) if texture_only else mapped_texture_value(texture_set, role_mapping, "aoStrength", 0.35),
            0.0,
            1.0,
        )
        if ao_strength > 0.0:
            ao_mix = nodes.new(type="ShaderNodeMixRGB")
            ao_mix.name = "zt_texture_ao_multiply"
            ao_mix.blend_type = "MULTIPLY"
            ao_mix.inputs["Fac"].default_value = ao_strength
            if base_color_signal is not None:
                links.new(base_color_signal, ao_mix.inputs["Color1"])
            else:
                ao_mix.inputs["Color1"].default_value = color
            links.new(ao_texture.outputs["Color"], ao_mix.inputs["Color2"])
            base_color_signal = ao_mix.outputs["Color"]

    if mottle_color is not None and mottle_fac > 0.0 and "Base Color" in bsdf.inputs:
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.name = "zt_mottle_noise"
        noise.inputs["Scale"].default_value = 18.0 if cast_grain else 8.0
        noise.inputs["Detail"].default_value = 9.0 if cast_grain else 5.0
        factor = nodes.new(type="ShaderNodeMath")
        factor.name = "zt_mottle_factor"
        factor.operation = "MULTIPLY"
        factor.inputs[1].default_value = mottle_fac
        mix = nodes.new(type="ShaderNodeMixRGB")
        mix.name = "zt_mottle_mix"
        mix.blend_type = "MIX"
        if base_color_signal is not None:
            links.new(base_color_signal, mix.inputs["Color1"])
        else:
            mix.inputs["Color1"].default_value = color
        mix.inputs["Color2"].default_value = mottle_color
        links.new(fac_output(noise), factor.inputs[0])
        links.new(factor.outputs["Value"], mix.inputs["Fac"])
        base_color_signal = mix.outputs["Color"]

    if base_color_signal is not None and "Base Color" in bsdf.inputs:
        links.new(base_color_signal, bsdf.inputs["Base Color"])

    metallic_texture = image_texture_node("metallic", ("metallic", "metalness"), "Non-Color")
    if metallic_texture is not None and "Metallic" in bsdf.inputs:
        metallic_base = nodes.new(type="ShaderNodeValue")
        metallic_base.name = "zt_metallic_base"
        metallic_base.outputs[0].default_value = metallic
        metallic_signal = blend_scalar(
            nodes,
            links,
            metallic_base.outputs[0],
            color_to_scalar(nodes, links, metallic_texture.outputs["Color"], "zt_metallic_texture_bw"),
            texture_strength(texture_set, role_mapping, "metallicStrength", 1.0, texture_only),
            "zt_texture_metallic",
        )
        links.new(metallic_signal, bsdf.inputs["Metallic"])

    roughness_signal = None
    roughness_texture = image_texture_node("roughness", ("roughness",), "Non-Color")
    if roughness_texture is not None:
        roughness_base = nodes.new(type="ShaderNodeValue")
        roughness_base.name = "zt_roughness_base"
        roughness_base.outputs[0].default_value = roughness
        roughness_signal = blend_scalar(
            nodes,
            links,
            roughness_base.outputs[0],
            color_to_scalar(nodes, links, roughness_texture.outputs["Color"], "zt_roughness_texture_bw"),
            texture_strength(texture_set, role_mapping, "roughnessStrength", 1.0, texture_only),
            "zt_texture_roughness",
        )
    elif rough_var > 0.0 or wave_rings > 0.0 or thread > 0.0:
        roughness_base = nodes.new(type="ShaderNodeValue")
        roughness_base.name = "zt_roughness_base"
        roughness_base.outputs[0].default_value = roughness
        roughness_signal = roughness_base.outputs[0]

    if rough_var > 0.0:
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.name = "zt_rough_variation_noise"
        noise.inputs["Scale"].default_value = roughness_noise_scale or noise_scale or (32.0 if cast_grain else 20.0)
        noise.inputs["Detail"].default_value = roughness_noise_detail if roughness_noise_detail is not None else (noise_detail if noise_detail is not None else (8.0 if cast_grain else 5.0))
        rough_range = nodes.new(type="ShaderNodeMapRange")
        rough_range.name = "zt_rough_variation_range"
        rough_range.inputs["From Min"].default_value = 0.0
        rough_range.inputs["From Max"].default_value = 1.0
        rough_range.inputs["To Min"].default_value = -rough_var
        rough_range.inputs["To Max"].default_value = rough_var
        links.new(fac_output(noise), rough_range.inputs["Value"])
        roughness_signal = add_weighted_scalar(nodes, links, roughness_signal, rough_range.outputs["Result"], 1.0, "zt_rough_variation")

    if wave_rings > 0.0:
        wave = add_wave_texture(nodes, "zt_machined_wave_rings", "RINGS", 18.0 + wave_rings * 520.0, 6.0)
        ring_range = nodes.new(type="ShaderNodeMapRange")
        ring_range.name = "zt_wave_rings_range"
        ring_range.inputs["From Min"].default_value = 0.0
        ring_range.inputs["From Max"].default_value = 1.0
        ring_range.inputs["To Min"].default_value = -wave_rings * 0.5
        ring_range.inputs["To Max"].default_value = wave_rings
        links.new(fac_output(wave), ring_range.inputs["Value"])
        roughness_signal = add_weighted_scalar(nodes, links, roughness_signal, ring_range.outputs["Result"], 1.0, "zt_wave_rings")

    if thread > 0.0:
        thread_wave = add_wave_texture(nodes, "zt_thread_roughness_bands", "BANDS", 48.0 + thread * 150.0, 2.0)
        thread_range = nodes.new(type="ShaderNodeMapRange")
        thread_range.name = "zt_thread_roughness_range"
        thread_range.inputs["From Min"].default_value = 0.0
        thread_range.inputs["From Max"].default_value = 1.0
        thread_range.inputs["To Min"].default_value = -thread * 0.03
        thread_range.inputs["To Max"].default_value = thread * 0.07
        links.new(fac_output(thread_wave), thread_range.inputs["Value"])
        roughness_signal = add_weighted_scalar(nodes, links, roughness_signal, thread_range.outputs["Result"], 1.0, "zt_thread_roughness")

    if roughness_signal is not None and "Roughness" in bsdf.inputs:
        links.new(roughness_signal, bsdf.inputs["Roughness"])

    height_signal = None
    height_texture = image_texture_node("height", ("height", "displacement"), "Non-Color")
    if height_texture is not None:
        height_signal = add_weighted_scalar(
            nodes,
            links,
            height_signal,
            color_to_scalar(nodes, links, height_texture.outputs["Color"], "zt_height_texture_bw"),
            1.0,
            "zt_texture_height",
        )

    if bump_strength > 0.0 or cast_grain:
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.name = "zt_surface_grain_bump"
        noise.inputs["Scale"].default_value = bump_noise_scale or noise_scale or (115.0 if cast_grain else 42.0)
        noise.inputs["Detail"].default_value = bump_noise_detail if bump_noise_detail is not None else (noise_detail if noise_detail is not None else (12.0 if cast_grain else 4.0))
        surface_height = fac_output(noise)
        if bump_ramp is not None or noise_scale is not None or noise_detail is not None or bump_distance is not None:
            surface_height = add_value_ramp(nodes, links, surface_height, "zt_surface_grain_color_ramp", bump_ramp)
        height_signal = add_weighted_scalar(nodes, links, height_signal, surface_height, 1.0, "zt_surface_grain")

    if cast_grain:
        fine_noise = nodes.new(type="ShaderNodeTexNoise")
        fine_noise.name = "zt_cast_grain_fine_bump"
        fine_noise.inputs["Scale"].default_value = 185.0
        fine_noise.inputs["Detail"].default_value = 10.0
        height_signal = add_weighted_scalar(nodes, links, height_signal, fac_output(fine_noise), 0.45, "zt_cast_grain_fine")

    if wave_rings > 0.0:
        wave = add_wave_texture(nodes, "zt_machined_ring_bump", "RINGS", 22.0 + wave_rings * 620.0, 3.0)
        height_signal = add_weighted_scalar(nodes, links, height_signal, fac_output(wave), clamp(wave_rings * 8.0, 0.12, 0.38), "zt_machined_ring_bump")

    if thread > 0.0:
        thread_wave = add_wave_texture(nodes, "zt_thread_ridge_bump", "BANDS", 64.0 + thread * 160.0, 1.2)
        height_signal = add_weighted_scalar(nodes, links, height_signal, fac_output(thread_wave), clamp(thread * 1.4, 0.18, 0.48), "zt_thread_ridge_bump")

    normal_signal = None
    normal_texture = image_texture_node("normal", ("normal", "normalMap"), "Non-Color")
    if normal_texture is not None:
        normal_map = nodes.new(type="ShaderNodeNormalMap")
        normal_map.name = "zt_texture_normal_map"
        normal_strength = (
            float(role_mapping.get("normalStrength", 0.7))
            if texture_only
            else mapped_texture_value(texture_set, role_mapping, "normalStrength", 0.25)
        )
        normal_map.inputs["Strength"].default_value = clamp(normal_strength, 0.0, 1.0)
        links.new(normal_texture.outputs["Color"], normal_map.inputs["Color"])
        normal_signal = normal_map.outputs["Normal"]

    if height_signal is not None and "Normal" in bsdf.inputs:
        height_strength = (
            float(role_mapping.get("heightStrength", 0.08))
            if texture_only
            else mapped_texture_value(texture_set, role_mapping, "heightStrength", 0.0)
        )
        if bump_distance is not None:
            height_distance = bump_distance
        else:
            height_distance = (
                float(role_mapping.get("heightDistance", 0.018))
                if texture_only
                else mapped_texture_value(texture_set, role_mapping, "heightDistance", 0.014 + (0.026 if thread > 0.0 else 0.0))
            )
        bump = nodes.new(type="ShaderNodeBump")
        bump.name = "zt_material_detail_bump"
        bump.inputs["Strength"].default_value = clamp(
            bump_strength
            + height_strength
            + (0.055 if cast_grain else 0.0)
            + wave_rings * 1.2
            + thread * 0.24,
            0.0,
            max(0.24, bump_strength_max),
        )
        bump.inputs["Distance"].default_value = height_distance
        links.new(height_signal, bump.inputs["Height"])
        if normal_signal is not None and "Normal" in bump.inputs:
            links.new(normal_signal, bump.inputs["Normal"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    elif normal_signal is not None and "Normal" in bsdf.inputs:
        links.new(normal_signal, bsdf.inputs["Normal"])

    if alpha_driver and "Alpha" in bsdf.inputs:
        value = nodes.new(type="ShaderNodeValue")
        value.name = "zt_reveal_transmission"
        value.outputs[0].default_value = 0.0
        invert = nodes.new(type="ShaderNodeMath")
        invert.operation = "SUBTRACT"
        invert.inputs[0].default_value = 1.0
        links.new(value.outputs[0], invert.inputs[1])
        links.new(invert.outputs["Value"], bsdf.inputs["Alpha"])
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = True

    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def mat_param(key: str, field: str, default: Any) -> Any:
    value = control_path(("lookdev", "materials", key, field), None)
    if value is not None:
        return value
    alias = material_source_key(key)
    if alias != key:
        return control_path(("lookdev", "materials", alias, field), default)
    return default


def material_source_key(key: str) -> str:
    aliases = control_path(("lookdev", "materials", "_materialAliases"), {})
    if isinstance(aliases, dict):
        value = aliases.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return key


def advanced_material_nodes_enabled() -> bool:
    support = control_path(("lookdev", "materials", "_rendererSupport"), {})
    active_fields = support.get("activeFields") if isinstance(support, dict) else None
    return isinstance(active_fields, list) and any(field in active_fields for field in ADVANCED_MATERIAL_FIELDS)


def make_lookdev_material(key: str, reveal: bool = False) -> Any:
    source_key = material_source_key(key)
    base, metallic, roughness, specular, bump = MATERIAL_DEFAULTS.get(source_key, MATERIAL_DEFAULTS.get(key, MATERIAL_DEFAULTS["machined"]))
    enable_advanced = advanced_material_nodes_enabled()
    role_mapping = mapping_for_role(key)
    diagnostic_mode = mapping_diagnostic_mode(key, role_mapping)
    use_procedural_detail = enable_advanced and diagnostic_mode == ""
    bump_value = mat_param(key, "bump", None)
    if bump_value is None:
        bump_value = mat_param(key, "normalStrength", bump)
    bump_ramp = mat_param(key, "bumpRamp", None) if use_procedural_detail else None
    return make_material(
        f"fixed_ball_valve_hero_{key}",
        color4(mat_param(key, "baseColor", None), base),
        float(mat_param(key, "metallic", metallic)),
        float(mat_param(key, "roughness", roughness)),
        float(mat_param(key, "specular", specular)),
        float(bump_value),
        rough_var=float(mat_param(key, "roughVar", 0.0)) if use_procedural_detail else 0.0,
        cast_grain=bool(mat_param(key, "castGrain", False)) if use_procedural_detail else False,
        mottle_color=optional_color4(mat_param(key, "mottleColor", None)) if use_procedural_detail else None,
        mottle_fac=float(mat_param(key, "mottleFac", 0.0)) if use_procedural_detail else 0.0,
        aniso=float(mat_param(key, "aniso", 0.0)) if enable_advanced else 0.0,
        wave_rings=float(mat_param(key, "waveRings", 0.0)) if use_procedural_detail else 0.0,
        radial_rotation=bool(mat_param(key, "radialRotation", False)) if enable_advanced else False,
        thread=float(mat_param(key, "thread", 0.0)) if use_procedural_detail else 0.0,
        noise_scale=optional_float(mat_param(key, "noiseScale", None)) if use_procedural_detail else None,
        noise_detail=optional_float(mat_param(key, "noiseDetail", None)) if use_procedural_detail else None,
        roughness_noise_scale=optional_float(mat_param(key, "roughnessNoiseScale", None)) if use_procedural_detail else None,
        roughness_noise_detail=optional_float(mat_param(key, "roughnessNoiseDetail", None)) if use_procedural_detail else None,
        bump_noise_scale=optional_float(mat_param(key, "bumpNoiseScale", None)) if use_procedural_detail else None,
        bump_noise_detail=optional_float(mat_param(key, "bumpNoiseDetail", None)) if use_procedural_detail else None,
        bump_ramp=bump_ramp if isinstance(bump_ramp, dict) else None,
        bump_distance=optional_float(mat_param(key, "bumpDistance", None)) if use_procedural_detail else None,
        bump_strength_max=float(mat_param(key, "bumpStrengthMax", 0.24)) if use_procedural_detail else 0.24,
        texture_set=mat_param(key, "textureSet", None) if enable_advanced else None,
        texture_mapping=role_mapping,
        diagnostic_mode=diagnostic_mode,
        role_key=key,
        alpha_driver=reveal,
    )


def configured_material_keys() -> list[str]:
    keys = list(DEFAULT_MATERIAL_KEYS)
    configured = control_path(("lookdev", "materials"), {})
    if isinstance(configured, dict):
        for key in sorted(str(item) for item, value in configured.items() if isinstance(value, dict)):
            if not key.startswith("_") and key not in keys and key not in REVEAL_MATERIAL_KEYS:
                keys.append(key)
        aliases = configured.get("_materialAliases", {})
        if isinstance(aliases, dict):
            for key in sorted(str(item) for item in aliases):
                if key not in keys and key not in REVEAL_MATERIAL_KEYS:
                    keys.append(key)
    mapping_roles = mapping_control().get("roles")
    if isinstance(mapping_roles, dict):
        for key in sorted(str(item) for item in mapping_roles):
            if key not in keys and key not in REVEAL_MATERIAL_KEYS:
                keys.append(key)
    return keys


def material_sets() -> dict[str, dict[str, Any]]:
    clay = make_material("independent_clay", (0.62, 0.62, 0.58, 1.0), 0.0, 0.78, 0.35)
    lookdev = {
        key: make_lookdev_material(key)
        for key in configured_material_keys()
    }
    for key in REVEAL_MATERIAL_KEYS:
        lookdev[key] = make_lookdev_material(key, reveal=True)
    return {
        "clay": {key: clay for key in lookdev},
        "lookdev": lookdev,
    }


def fastener_role(name: str) -> str:
    if name == "弹簧":
        return "spring"
    if any(token in name for token in ("stud", "screw", "SCREW", "螺柱")):
        return "threaded"
    return "fastener"


def role_from_rules(record: dict[str, Any]) -> str | None:
    role_doc = control_path(("parts", "roles", "materialRoles"), {})
    if not isinstance(role_doc, dict):
        return None
    group = record["animationGroup"]
    product = record["productName"]

    products = role_doc.get("products", {})
    if isinstance(products, dict) and product in products:
        return str(products[product])

    product_contains = role_doc.get("productContains", [])
    if isinstance(product_contains, list):
        for rule in product_contains:
            if isinstance(rule, dict) and str(rule.get("contains", "")) in product:
                return str(rule.get("role"))

    groups = role_doc.get("groups", {})
    if isinstance(groups, dict) and group in groups:
        return str(groups[group])

    group_contains = role_doc.get("groupContains", [])
    if isinstance(group_contains, list):
        for rule in group_contains:
            if isinstance(rule, dict) and str(rule.get("contains", "")) in group:
                return str(rule.get("role"))

    fallback = role_doc.get("fallback")
    return str(fallback) if fallback else None


def material_key(record: dict[str, Any]) -> str:
    direct_role = record.get("materialRole")
    if isinstance(direct_role, str) and direct_role.strip():
        return direct_role.strip()

    configured_role = role_from_rules(record)
    if configured_role:
        return configured_role

    group = record["animationGroup"]
    product = record["productName"]
    if group == "ball-trunnion-core":
        return "ball" if product == "球体" else "machined"
    if group == "seat-seal-system":
        return "seal" if any(term in product for term in ("密封", "盘根", "垫片")) else "machined"
    if "fasteners" in group:
        return fastener_role(product)
    if group in {"top-bracket-connector", "stem-packing-stack"}:
        return "top"
    if group == "end-caps-covers":
        return "machined"
    if product in {"阀体", "阀盖"}:
        return "body"
    return "dark"


def clear_custom_normals(obj: Any) -> bool:
    mesh = obj.data
    had_custom = bool(getattr(mesh, "has_custom_normals", False))
    if not had_custom:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    except Exception:
        try:
            mesh.normals_split_custom_set(None)
            mesh.update()
        except Exception:
            pass
    return had_custom


def rebuild_mesh_normals(objects: list[Any]) -> dict[str, Any]:
    audit = {
        "objects": len(objects),
        "customNormalsCleared": 0,
        "faces": 0,
        "edges": 0,
        "angleDegrees": 40.0,
        "mergeDistance": 0.00035,
    }
    for obj in objects:
        if obj.animation_data:
            obj.animation_data_clear()
        if clear_custom_normals(obj):
            audit["customNormalsCleared"] += 1

        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=audit["mergeDistance"])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for face in bm.faces:
            face.smooth = True
        audit["faces"] += len(bm.faces)
        audit["edges"] += len(bm.edges)
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        try:
            bpy.ops.mesh.set_sharpness_by_angle(angle=math.radians(audit["angleDegrees"]))
        except Exception:
            pass
        bpy.ops.mesh.faces_shade_smooth()
        bpy.ops.object.mode_set(mode="OBJECT")

        bevel = obj.modifiers.new(name="independent_micro_bevel", type="BEVEL")
        bevel.width = 0.00018
        bevel.segments = 2
        bevel.limit_method = "ANGLE"
        bevel.angle_limit = math.radians(45)
        weighted = obj.modifiers.new(name="independent_weighted_normals", type="WEIGHTED_NORMAL")
        if hasattr(weighted, "keep_sharp"):
            weighted.keep_sharp = True
    return audit


def world_bounds(objects: list[Any]) -> dict[str, Any]:
    mins = Vector((math.inf, math.inf, math.inf))
    maxs = Vector((-math.inf, -math.inf, -math.inf))
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, point.x)
            mins.y = min(mins.y, point.y)
            mins.z = min(mins.z, point.z)
            maxs.x = max(maxs.x, point.x)
            maxs.y = max(maxs.y, point.y)
            maxs.z = max(maxs.z, point.z)
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    return {
        "min": [round(v, 6) for v in mins],
        "max": [round(v, 6) for v in maxs],
        "center": [round(v, 6) for v in center],
        "extent": [round(v, 6) for v in extent],
        "radius": round(max(extent.x, extent.y, extent.z), 6),
    }


def add_studio_world(repo_root: Path) -> dict[str, Any]:
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("fixed_ball_valve_hero_world")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputWorld")
    light_path = nodes.new(type="ShaderNodeLightPath")
    hdri_cfg = control_path(("lookdev", "environment", "hdri"), {})
    hdri_path = str(hdri_cfg.get("path", "")) if isinstance(hdri_cfg, dict) else ""
    strength = float(control_path(("lookdev", "environment", "hdri", "strength"), 0.18))
    fallback_color = control_path(("lookdev", "environment", "hdri", "fallbackColor"), [0.74, 0.76, 0.77])
    fallback_strength = float(control_path(("lookdev", "environment", "hdri", "fallbackStrength"), 0.14))
    rotation = float(control_path(("lookdev", "environment", "hdri", "rotationDegrees"), 0.0))

    lit = nodes.new(type="ShaderNodeBackground")
    lit.inputs["Color"].default_value = (*[float(c) for c in fallback_color], 1.0)
    lit.inputs["Strength"].default_value = fallback_strength
    cam_bg = nodes.new(type="ShaderNodeBackground")
    cam_bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    cam_bg.inputs["Strength"].default_value = 1.0

    env_ok = False
    if hdri_path:
        hdri = repo_path(repo_root, hdri_path)
        if hdri.is_file():
            try:
                env = nodes.new(type="ShaderNodeTexEnvironment")
                env.image = bpy.data.images.load(str(hdri))
                if rotation:
                    env.texture_mapping.rotation.z = math.radians(rotation)
                links.new(env.outputs["Color"], lit.inputs["Color"])
                lit.inputs["Strength"].default_value = strength
                env_ok = True
            except Exception as exc:
                print(f"[lookdev] HDRI load failed ({hdri}): {exc}")
        else:
            print(f"[lookdev] HDRI missing ({hdri}); using fallback environment")

    mix = nodes.new(type="ShaderNodeMixShader")
    links.new(light_path.outputs["Is Camera Ray"], mix.inputs[0])
    links.new(lit.outputs["Background"], mix.inputs[1])
    links.new(cam_bg.outputs["Background"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])
    return {"hdri": hdri_path, "loaded": env_ok, "strength": strength, "rotationDegrees": rotation}


def configure_render(width: int, height: int, samples: int, repo_root: Path) -> dict[str, Any]:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 15
    try:
        scene.render.image_settings.alpha_mode = "STRAIGHT"
    except Exception:
        pass

    scene.view_settings.view_transform = str(control_path(("lookdev", "view", "transform"), "AgX"))
    scene.view_settings.look = str(control_path(("lookdev", "view", "look"), "AgX - High Contrast"))
    scene.view_settings.exposure = float(control_path(("lookdev", "view", "exposure"), -0.46))
    scene.view_settings.gamma = float(control_path(("lookdev", "view", "gamma"), 1))

    cycles = scene.cycles
    cycles.samples = samples
    cycles.preview_samples = min(samples, 32)
    cycles.use_denoising = True
    cycles.max_bounces = 5
    cycles.diffuse_bounces = 2
    cycles.glossy_bounces = 3

    return {
        "renderer": "Blender Cycles",
        "width": width,
        "height": height,
        "samples": samples,
        "filmTransparent": True,
        "pngColorMode": "RGBA",
        "background": "transparent",
        "viewTransform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "environment": add_studio_world(repo_root),
    }


def add_lighting(center: Vector, extent: Vector) -> list[dict[str, Any]]:
    default_lights = [
        {"name": "broad_key", "offset": [-4.25, -1.48, 3.0], "energy": 225, "shape": "RECTANGLE", "size": 0.95, "sizeY": 2.85},
        {"name": "controlled_right_rim", "offset": [2.9, -2.55, 1.42], "energy": 252, "shape": "RECTANGLE", "size": 0.82, "sizeY": 2.05},
        {"name": "top_softbox", "offset": [-0.1, -0.72, 3.95], "energy": 32, "shape": "RECTANGLE", "size": 2.8, "sizeY": 1.05},
        {"name": "left_edge_pin", "offset": [-4.15, -2.45, 0.72], "energy": 72, "shape": "RECTANGLE", "size": 1.8, "sizeY": 3.4},
        {"name": "front_low_lift", "offset": [-0.24, -3.28, 0.5], "energy": 68, "shape": "RECTANGLE", "size": 7.2, "sizeY": 2.45},
    ]
    light_cfgs = control_path(("lookdev", "lighting", "lights"), default_lights)
    strength_scale = float(control_path(("lookdev", "lighting", "strengthScale"), 1.0))
    span = max(extent.x, extent.y, extent.z, 0.4)
    records: list[dict[str, Any]] = []

    for cfg in light_cfgs:
        name = str(cfg["name"])
        offset = Vector((float(cfg["offset"][0]), float(cfg["offset"][1]), float(cfg["offset"][2])))
        target_cfg = cfg.get("targetOffset", [0.0, 0.0, 0.0])
        target_offset = Vector((float(target_cfg[0]), float(target_cfg[1]), float(target_cfg[2])))
        energy = float(cfg.get("energy", 100.0)) * strength_scale
        shape = str(cfg.get("shape", "SQUARE")).upper()
        size = float(cfg.get("size", 4.0))
        size_y = cfg.get("sizeY")
        soft = float(cfg.get("softSize", 0.5))
        roll = math.radians(float(cfg.get("rollDegrees", 0.0)))

        data = bpy.data.lights.new(f"fixed_ball_valve_hero_{name}_data", "AREA")
        data.energy = min(energy, 400.0)
        color = cfg.get("color")
        if isinstance(color, list) and len(color) >= 3:
            data.color = (float(color[0]), float(color[1]), float(color[2]))
        if shape in {"SQUARE", "RECTANGLE", "DISK", "ELLIPSE"}:
            data.shape = shape
        data.size = size
        if size_y is not None and hasattr(data, "size_y"):
            data.size_y = float(size_y)
        data.shadow_soft_size = soft

        obj = bpy.data.objects.new(f"fixed_ball_valve_hero_{name}", data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = center + offset * span
        look_at(obj, center + target_offset * span, roll)

        ray_visibility_record: dict[str, bool] = {}
        cycles_visibility = getattr(obj, "cycles_visibility", None)
        visibility_fields = {
            "visibleCamera": "camera",
            "visibleDiffuse": "diffuse",
            "visibleGlossy": "glossy",
            "visibleTransmission": "transmission",
            "visibleVolumeScatter": "scatter",
            "visibleShadow": "shadow",
        }
        for cfg_key, attr_name in visibility_fields.items():
            if cfg_key in cfg and cycles_visibility is not None and hasattr(cycles_visibility, attr_name):
                value = bool(cfg[cfg_key])
                setattr(cycles_visibility, attr_name, value)
                ray_visibility_record[cfg_key] = value

        records.append(
            {
                "name": name,
                "role": cfg.get("role"),
                "energy": data.energy,
                "shape": data.shape,
                "color": [round(v, 5) for v in data.color],
                "size": size,
                "sizeY": float(size_y) if size_y is not None else None,
                "softSize": soft,
                "targetOffset": [round(v, 5) for v in target_offset],
                "rayVisibility": ray_visibility_record,
                "location": [round(v, 5) for v in obj.location],
            }
        )
    return records


def add_contact_shadow(product_bounds: dict[str, Any]) -> dict[str, Any] | None:
    grounding = control_path(("lookdev", "grounding", "contactShadow"), {"enabled": False})
    if not isinstance(grounding, dict) or not bool(grounding.get("enabled", False)):
        return None
    radius = float(grounding.get("radius", 0.42))
    opacity = float(grounding.get("opacity", 0.16))
    z_offset = float(grounding.get("zOffset", 0.018))
    center_x = product_bounds["center"][0]
    center_y = product_bounds["center"][1]
    z = product_bounds["min"][2] - z_offset
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=radius, location=(center_x, center_y, z))
    disc = bpy.context.active_object
    disc.name = "fixed_ball_valve_hero_contact_shadow"
    mat = bpy.data.materials.new("fixed_ball_valve_hero_contact_shadow_mat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    mix = nodes.new(type="ShaderNodeMixShader")
    transparent = nodes.new(type="ShaderNodeBsdfTransparent")
    shade = nodes.new(type="ShaderNodeEmission")
    shade.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    shade.inputs["Strength"].default_value = 1.0
    coord = nodes.new(type="ShaderNodeTexCoord")
    gradient = nodes.new(type="ShaderNodeTexGradient")
    gradient.gradient_type = "SPHERICAL"
    mr = nodes.new(type="ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.0
    mr.inputs["From Max"].default_value = radius
    mr.inputs["To Min"].default_value = 1.0
    mr.inputs["To Max"].default_value = 0.0
    mul = nodes.new(type="ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = opacity
    links.new(coord.outputs["Object"], gradient.inputs["Vector"])
    links.new(gradient.outputs["Fac"], mr.inputs["Value"])
    links.new(mr.outputs["Result"], mul.inputs[0])
    links.new(mul.outputs["Value"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(shade.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    disc.data.materials.clear()
    disc.data.materials.append(mat)
    return {"z": round(z, 5), "radius": radius, "opacity": opacity}


def record_source_node_index(record: dict[str, Any]) -> int:
    for key in ("sourceNodeIndex", "nodeIndex"):
        value = record.get(key)
        if value is not None:
            return int(value)
    raise RuntimeError(f"Node map record lacks node index: {record}")


def record_render_index(record: dict[str, Any]) -> int:
    for key in ("renderNodeIndex", "nodeIndex", "sourceNodeIndex"):
        value = record.get(key)
        if value is not None:
            return int(value)
    raise RuntimeError(f"Node map record lacks render index: {record}")


def record_node_index(record: dict[str, Any]) -> int:
    return record_source_node_index(record)


def record_render_record_id(record: dict[str, Any]) -> str | None:
    value = record.get("renderRecordId")
    return str(value) if isinstance(value, str) and value.strip() else None


def object_source_node_index(obj: Any) -> int | None:
    for key in ("zt_source_node_index", "zt_node_index"):
        value = obj.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def object_render_record_id(obj: Any) -> str | None:
    value = obj.get("zt_render_record_id")
    return str(value) if isinstance(value, str) and value.strip() else None


def node_map_records(node_map: dict[str, Any]) -> list[dict[str, Any]]:
    if str(node_map.get("schema", "")) == "ztovalve-fixed-ball-valve-industrial-uv-node-map/v2":
        return sorted(node_map["records"], key=record_render_index)
    return sorted(node_map["records"], key=record_source_node_index)


def pair_node_map_objects(objects: list[Any], records: list[dict[str, Any]], node_map_schema: str) -> tuple[list[tuple[Any, dict[str, Any]]], str]:
    if node_map_schema == "ztovalve-fixed-ball-valve-industrial-uv-node-map/v2":
        by_render_id: dict[str, Any] = {}
        for obj in objects:
            render_id = object_render_record_id(obj)
            if render_id is not None and render_id not in by_render_id:
                by_render_id[render_id] = obj
        expected_ids = [record_render_record_id(record) for record in records]
        if (
            len(by_render_id) == len(objects)
            and all(render_id is not None and render_id in by_render_id for render_id in expected_ids)
        ):
            return [(by_render_id[str(render_id)], record) for render_id, record in zip(expected_ids, records)], "object-extra-render-record-id"

        by_source_index: dict[int, Any] = {}
        for obj in objects:
            source_index = object_source_node_index(obj)
            if source_index is not None and source_index not in by_source_index:
                by_source_index[source_index] = obj
        expected = [record_source_node_index(record) for record in records]
        if len(by_source_index) == len(objects) and len(set(expected)) == len(expected) and all(index in by_source_index for index in expected):
            return [(by_source_index[index], record) for index, record in zip(expected, records)], "object-extra-source-node-index"
    return list(zip(objects, records)), "import-order"


def record_expected_names(record: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("productName", "sourceProductName", "objectName"):
        value = record.get(key)
        if isinstance(value, str) and value:
            names.add(duplicate_base_name(value))
            names.add(value)
    return names


def uv_layer_names(obj: Any) -> list[str]:
    return [layer.name for layer in getattr(obj.data, "uv_layers", [])]


def has_required_uv_layer(obj: Any, uv_layer: str | None) -> bool:
    names = uv_layer_names(obj)
    if not names:
        return False
    if uv_layer:
        return uv_layer in names
    return True


def audit_required_uv(records: list[dict[str, Any]]) -> dict[str, Any]:
    role_audit: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for ordinal, record in enumerate(records):
        obj = record["object"]
        role = str(record.get("materialKey", record.get("materialRole", "unknown")))
        role_mapping = mapping_for_role(role)
        uv_layer = role_mapping.get("uvLayer")
        if not isinstance(uv_layer, str):
            uv_layer = None
        require_uv = bool(role_mapping.get("requireUv", False))
        names = uv_layer_names(obj)
        has_uv = has_required_uv_layer(obj, uv_layer)
        entry = role_audit.setdefault(
            role,
            {
                "objectCount": 0,
                "withUvObjectCount": 0,
                "missingUvObjectCount": 0,
                "requireUv": require_uv,
                "uvLayer": uv_layer,
                "coordinate": role_mapping.get("coordinate", role_mapping.get("coordinateSource")),
                "uvFamilyCounts": {},
                "sample": [],
                "missingSample": [],
            },
        )
        entry["objectCount"] += 1
        entry["requireUv"] = bool(entry["requireUv"] or require_uv)
        if has_uv:
            entry["withUvObjectCount"] += 1
        else:
            entry["missingUvObjectCount"] += 1
        uv_family = str(record.get("uvFamily", role_mapping.get("uvFamily", "")) or "")
        if uv_family:
            family_counts = entry["uvFamilyCounts"]
            family_counts[uv_family] = family_counts.get(uv_family, 0) + 1
        sample = {
            "ordinal": ordinal,
            "objectName": obj.name,
            "productName": record.get("productName"),
            "nodeIndex": record.get("nodeIndex"),
            "sourceNodeIndex": record.get("sourceNodeIndex"),
            "uvLayerNames": names,
            "uvRequired": require_uv,
        }
        if len(entry["sample"]) < 6:
            entry["sample"].append(sample)
        if require_uv and not has_uv:
            missing.append(sample)
            if len(entry["missingSample"]) < 6:
                entry["missingSample"].append(sample)
    role_audit = {key: role_audit[key] for key in sorted(role_audit)}
    gate = {
        "schema": "ztovalve-render-uv-gate-audit/v1",
        "status": "pass" if not missing else "fail",
        "requiredRoleObjectMissingUvCount": len(missing),
        "missingRequiredUvSample": missing[:24],
        "roles": role_audit,
    }
    if missing:
        sample = json.dumps(missing[:8], ensure_ascii=False)
        raise RuntimeError(f"UV gate failed for requireUv=true roles: {sample}")
    return gate


def parse_material_role_filter(value: str) -> set[str]:
    roles = {item.strip() for item in value.split(",") if item.strip()}
    return roles


def apply_material_role_isolation(records: list[dict[str, Any]], roles: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    visible_records: list[dict[str, Any]] = []
    hidden_counts: dict[str, int] = {}
    visible_counts: dict[str, int] = {}
    for record in records:
        role = str(record.get("materialKey", ""))
        show = not roles or role in roles
        obj = record["object"]
        obj.hide_render = not show
        obj.hide_viewport = not show
        try:
            obj.hide_set(not show)
        except Exception:
            pass
        counts = visible_counts if show else hidden_counts
        counts[role] = counts.get(role, 0) + 1
        if show:
            visible_records.append(record)
    if roles and not visible_records:
        available = sorted({str(record.get("materialKey", "")) for record in records})
        raise RuntimeError(f"No mesh objects matched isolated material role(s) {sorted(roles)}. Available roles: {available}")
    return visible_records or records, {
        "enabled": bool(roles),
        "roles": sorted(roles),
        "visibleObjectCount": len(visible_records) if roles else len(records),
        "hiddenObjectCount": len(records) - len(visible_records) if roles else 0,
        "visibleCounts": dict(sorted(visible_counts.items())),
        "hiddenCounts": dict(sorted(hidden_counts.items())),
    }


def bind_node_map(objects: list[Any], node_map: dict[str, Any], mats: dict[str, Any], glb_sha: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    node_map_schema = str(node_map.get("schema", ""))
    records = node_map_records(node_map)
    mismatches: list[dict[str, Any]] = []
    bound: list[dict[str, Any]] = []
    pairs, binding_mode = pair_node_map_objects(objects, records, node_map_schema)
    if len(pairs) != len(records) or len(pairs) != len(objects):
        raise RuntimeError(f"Expected {len(records)} mesh objects from node map, got {len(objects)}")
    for ordinal, (obj, record) in enumerate(pairs):
        object_base = duplicate_base_name(obj.name)
        expected_names = record_expected_names(record)
        object_source_index = object_source_node_index(obj)
        expected_source_index = record_source_node_index(record)
        source_index_matches = object_source_index is not None and object_source_index == expected_source_index
        if not source_index_matches and object_base not in expected_names:
            mismatches.append(
                {
                    "ordinal": ordinal,
                    "objectName": obj.name,
                    "objectBaseName": object_base,
                    "nodeIndex": record.get("nodeIndex"),
                    "sourceNodeIndex": record.get("sourceNodeIndex"),
                    "productName": record.get("productName"),
                    "sourceProductName": record.get("sourceProductName"),
                    "expectedNames": sorted(expected_names),
                }
            )
        key = material_key(record)
        if key not in mats:
            raise RuntimeError(f"Material role {key!r} from node map has no configured material.")
        material = mats[key]
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj["zt_node_index"] = int(record.get("nodeIndex", expected_source_index))
        obj["zt_source_node_index"] = expected_source_index
        obj["zt_product_name"] = record.get("productName", record.get("sourceProductName", ""))
        obj["zt_animation_group"] = record.get("animationGroup", record.get("sourceAnimationGroup", ""))
        if record.get("uvFamily"):
            obj["zt_uv_family"] = str(record.get("uvFamily"))
        bound.append({**record, "object": obj, "baseMatrix": obj.matrix_world.copy(), "materialKey": key})

    if mismatches:
        sample = json.dumps(mismatches[:5], ensure_ascii=False)
        raise RuntimeError(f"New GLB mesh order does not match node map records: {sample}")

    source_glb = node_map.get("sources", {}).get("glb")
    source_glb_sha = source_glb.get("sha256") if isinstance(source_glb, dict) else None
    comparison_count = min(len(objects), len(records))
    samples = [
        {
            "ordinal": index,
            "objectName": pairs[index][0].name,
            "productName": records[index].get("productName"),
            "sourceProductName": records[index].get("sourceProductName"),
            "nodeIndex": records[index].get("nodeIndex"),
            "sourceNodeIndex": records[index].get("sourceNodeIndex"),
        }
        for index in list(range(min(5, comparison_count))) + list(range(max(5, comparison_count - 5), comparison_count))
    ]
    audit = {
        "nodeMapSchema": node_map_schema,
        "meshObjects": len(objects),
        "nodeMapRecords": len(records),
        "bindingMode": binding_mode,
        "allNamesMatchAfterNumericSuffixStrip": True,
        "mismatchCount": 0,
        "nodeMapSourceGlb": source_glb,
        "nodeMapSourceGlbSha256MatchesImportedGlb": bool(source_glb_sha and source_glb_sha.lower() == glb_sha.lower()),
        "orderSample": samples,
    }
    assignment_counts: dict[str, int] = {}
    assignment_samples: list[dict[str, Any]] = []
    for index, record in enumerate(bound):
        key = str(record["materialKey"])
        assignment_counts[key] = assignment_counts.get(key, 0) + 1
        if len(assignment_samples) < 24:
            assignment_samples.append(
                {
                    "ordinal": index,
                    "objectName": record["object"].name,
                    "productName": record.get("productName"),
                    "sourceProductName": record.get("sourceProductName"),
                    "animationGroup": record.get("animationGroup", record.get("sourceAnimationGroup")),
                    "materialKey": key,
                    "uvFamily": record.get("uvFamily"),
                    "uvRequired": record.get("uvRequired"),
                    "uvLayerNames": uv_layer_names(record["object"]),
                }
            )
    audit["materialAssignmentCounts"] = dict(sorted(assignment_counts.items()))
    audit["materialAssignmentSample"] = assignment_samples
    audit["uvRequirementGate"] = audit_required_uv(bound)
    return bound, audit


def ease_in_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def to_mesh(value: Vector) -> Vector:
    return Vector((value.x, -value.z, value.y))


def record_mesh_center(record: dict[str, Any]) -> Vector:
    return to_mesh(Vector(record["bounds"]["center"]))


def stage_for(progress: float, frame_count: int) -> dict[str, Any]:
    public_frame = round(progress * max(1, frame_count - 1)) + 1
    stages = control_path(("animation", "stages"), [])
    if isinstance(stages, list) and stages:
        for entry in stages:
            if public_frame <= entry.get("lastFrame", frame_count - 1):
                return {"stage": entry.get("stage", "final-stable-hold")}
        return {"stage": stages[-1].get("stage", "final-stable-hold")}
    return {"stage": "fixed-ball-valve-hero"}


def section_reveal_opacity(progress: float) -> float:
    if not feature_enabled("sectionReveal", False):
        return 1.0
    cfg = control_path(("animation", "sectionReveal"), {})
    in_from = float(cfg.get("inFrom", 0.52))
    in_to = float(cfg.get("inTo", 0.60))
    out_from = float(cfg.get("outFrom", 0.80))
    out_to = float(cfg.get("outTo", 0.90))
    min_opacity = float(cfg.get("minOpacity", 0.25))
    if progress <= in_from or progress >= out_to:
        return 1.0
    if progress < in_to:
        return 1.0 - (1.0 - min_opacity) * ease_in_out((progress - in_from) / max(1e-9, in_to - in_from))
    if progress < out_from:
        return min_opacity
    return min_opacity + (1.0 - min_opacity) * ease_in_out((progress - out_from) / max(1e-9, out_to - out_from))


def quarter_turn_value(progress: float) -> float:
    cfg = control_path(("animation", "quarterTurn"), {"from": 0.64, "to": 0.75})
    qt_from = float(cfg.get("from", 0.64))
    qt_to = float(cfg.get("to", 0.75))
    if progress <= qt_from:
        return 0.0
    if progress >= qt_to:
        return 1.0
    return ease_in_out((progress - qt_from) / max(1e-9, qt_to - qt_from))


def state_for(progress: float) -> dict[str, float]:
    assembly_cfg = control_path(("animation", "assembly"), {"from": 0.02, "to": 0.50, "holdFrom": 0.50})
    camera_cfg = control_path(("animation", "camera"), {"from": 0.12, "to": 0.54})
    yaw_cfg = control_path(("animation", "yawDegrees"), {"base": -5, "per": 14})
    min_explosion = float(control_path(("morph", "global", "minExplosion"), 0.0))
    assembly_from = float(assembly_cfg.get("from", 0.02))
    assembly_to = float(assembly_cfg.get("to", 0.50))
    hold_from = float(assembly_cfg.get("holdFrom", 0.50))
    camera_from = float(camera_cfg.get("from", 0.12))
    camera_to = float(camera_cfg.get("to", 0.54))
    yaw_base = float(yaw_cfg.get("base", -5))
    yaw_per = float(yaw_cfg.get("per", 14))
    peak_assembly = 1.0 - min_explosion

    if progress < assembly_from:
        assembly = 0.0
    elif progress < assembly_to:
        assembly = peak_assembly * ease_in_out((progress - assembly_from) / max(1e-9, assembly_to - assembly_from))
    else:
        assembly = peak_assembly
    camera = ease_in_out(max(0, min(1, (progress - camera_from) / max(1e-9, camera_to - camera_from))))
    hold = progress >= hold_from
    return {
        "progress": progress,
        "assembly": peak_assembly if hold else assembly,
        "explosion": min_explosion if hold else 1.0 - assembly,
        "cameraProgress": 1.0 if hold else camera,
        "yawDegrees": yaw_base + yaw_per * (1.0 if hold else camera),
        "quarterTurn": quarter_turn_value(progress),
        "sectionOpacity": section_reveal_opacity(progress),
    }


def find_ball_center(records: list[dict[str, Any]]) -> Vector | None:
    for record in records:
        if record["productName"] == "球体":
            return record_mesh_center(record)
    return None


def build_motion_context(records: list[dict[str, Any]], ball_center: Vector) -> dict[str, Any]:
    context: dict[str, Any] = {"ballCenter": ball_center, "productRecords": {}, "groupRecords": {}, "productCenters": {}, "groupCenters": {}}
    for record in records:
        context["productRecords"].setdefault(record["productName"], []).append(record)
        context["groupRecords"].setdefault(record["animationGroup"], []).append(record)
    for scope in ("product", "group"):
        records_key = f"{scope}Records"
        centers_key = f"{scope}Centers"
        for name, scoped_records in context[records_key].items():
            center = Vector((0.0, 0.0, 0.0))
            for scoped_record in scoped_records:
                center += record_mesh_center(scoped_record)
            context[centers_key][name] = center / max(1, len(scoped_records))
    return context


def node_map_center(value: Any) -> Vector | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return to_mesh(Vector((float(value[0]), float(value[1]), float(value[2]))))
    return None


def nearest_record_center(records: list[dict[str, Any]], target: Vector) -> tuple[Vector, dict[str, Any]]:
    closest = min(records, key=lambda item: (record_mesh_center(item) - target).length)
    return record_mesh_center(closest), closest


def selector_center_and_record(selector: Any, record: dict[str, Any], context: dict[str, Any]) -> tuple[Vector, dict[str, Any] | None] | None:
    if not isinstance(selector, str) or not selector:
        return None
    target = record_mesh_center(record)
    product_records = context.get("productRecords", {})
    if selector in product_records:
        return nearest_record_center(product_records[selector], target)
    group_records = context.get("groupRecords", {})
    if selector in group_records:
        return nearest_record_center(group_records[selector], target)
    return None


def selected_host(record: dict[str, Any], cfg: dict[str, Any], context: dict[str, Any]) -> tuple[str, Vector, dict[str, Any] | None] | None:
    raw_candidates = cfg.get("hostCandidates", cfg.get("host"))
    if raw_candidates is None:
        return None
    candidates = raw_candidates if isinstance(raw_candidates, list) else [raw_candidates]
    record_center = record_mesh_center(record)
    best: tuple[str, Vector, dict[str, Any] | None] | None = None
    best_distance = float("inf")
    for candidate in candidates:
        resolved = selector_center_and_record(candidate, record, context)
        if resolved is None:
            continue
        center, host_record = resolved
        distance = (center - record_center).length
        if distance < best_distance:
            best = (str(candidate), center, host_record)
            best_distance = distance
    return best


def resolve_radial_origin(record: dict[str, Any], cfg: dict[str, Any], ball_center: Vector, context: dict[str, Any], host: tuple[str, Vector, dict[str, Any] | None] | None) -> Vector:
    local_center = node_map_center(cfg.get("localCenter"))
    if local_center is not None:
        return local_center
    spec = cfg.get("radialOrigin", "host" if host is not None else "ball")
    if isinstance(spec, dict):
        explicit = node_map_center(spec.get("localCenter"))
        if explicit is not None:
            return explicit
        if spec.get("host"):
            resolved = selected_host(record, {"host": spec.get("host")}, context)
            if resolved is not None:
                return resolved[1]
        if spec.get("product"):
            resolved = selector_center_and_record(spec.get("product"), record, context)
            if resolved is not None:
                return resolved[0]
        if spec.get("group"):
            resolved = selector_center_and_record(spec.get("group"), record, context)
            if resolved is not None:
                return resolved[0]
        spec = spec.get("mode", "ball")
    explicit = node_map_center(spec)
    if explicit is not None:
        return explicit
    if spec == "host" and host is not None:
        return host[1]
    if spec == "product":
        return context.get("productCenters", {}).get(record["productName"], ball_center)
    if spec == "group":
        return context.get("groupCenters", {}).get(record["animationGroup"], ball_center)
    if isinstance(spec, str) and spec not in {"ball", "self"}:
        resolved = selector_center_and_record(spec, record, context)
        if resolved is not None:
            return resolved[0]
    if spec == "self":
        return record_mesh_center(record)
    return ball_center


def radial_direction(bounds_center: Vector, origin: Vector, base_direction: Vector, cfg: dict[str, Any]) -> Vector:
    radial_vec = bounds_center - origin
    plane = cfg.get("radialPlane")
    if not plane:
        radial_vec.z = 0.0
        if radial_vec.length > 1e-6:
            radial_vec.normalize()
            return Vector((radial_vec.x, radial_vec.y, base_direction.z))
        return base_direction
    axes = {axis for axis in str(plane).lower() if axis in {"x", "y", "z"}}
    filtered = Vector((radial_vec.x if "x" in axes else 0.0, radial_vec.y if "y" in axes else 0.0, radial_vec.z if "z" in axes else 0.0))
    if filtered.length <= 1e-6:
        return base_direction
    filtered.normalize()
    out_of_plane = float(cfg.get("radialOutOfPlaneWeight", 0.0))
    if out_of_plane:
        filtered.x += 0.0 if "x" in axes else base_direction.x * out_of_plane
        filtered.y += 0.0 if "y" in axes else base_direction.y * out_of_plane
        filtered.z += 0.0 if "z" in axes else base_direction.z * out_of_plane
    return filtered


def record_morph_config(record: dict[str, Any]) -> dict[str, Any] | None:
    records = control_path(("morph", "records"), {})
    if isinstance(records, dict):
        for key in (
            record.get("renderRecordId"),
            record.get("objectName"),
            record.get("sourceProductName"),
            str(record.get("renderNodeIndex", "")),
            str(record.get("nodeIndex", "")),
        ):
            if isinstance(key, str) and key in records and isinstance(records[key], dict):
                return records[key]

    objects = control_path(("morph", "objects"), {})
    obj = record.get("object")
    if isinstance(objects, dict) and obj is not None:
        for key in (getattr(obj, "name", ""), duplicate_base_name(getattr(obj, "name", "")), record.get("objectName")):
            if isinstance(key, str) and key in objects and isinstance(objects[key], dict):
                return objects[key]
    return None


def group_offset(record: dict[str, Any], ball_center: Vector, progress: float, context: dict[str, Any], include_host: bool = True) -> tuple[Vector, float]:
    bounds_center = record_mesh_center(record)
    parts = control_path(("morph", "parts"), {})
    whitelist_enabled = bool(control_path(("morph", "partsWhitelist", "enabled"), False))
    name = record["productName"]
    cfg: dict[str, Any] | None = record_morph_config(record)

    if cfg is None and isinstance(parts, dict) and name in parts and isinstance(parts[name], dict):
        cfg = parts[name]
    elif cfg is None and whitelist_enabled:
        return Vector((0, 0, 0)), 0.0

    if cfg is None:
        groups = control_path(("morph", "groups"), {})
        cfg = groups.get(record["animationGroup"], {}) if isinstance(groups, dict) else {}

    timing = cfg.get("timing", {"start": 0.0, "end": 0.8})
    start = float(timing.get("start", 0.0))
    end = float(timing.get("end", 0.8))
    distance = float(cfg.get("distance", 0.6))
    rotate_z = float(cfg.get("rotateZ", 0.0))
    radial = bool(cfg.get("radial", False))
    max_explosion = float(cfg.get("maxExplosion", 1.0))
    mirror = cfg.get("mirror")
    multiplier = float(control_path(("morph", "global", "explosionMultiplier"), 1.0))
    host = selected_host(record, cfg, context)

    gp = max(0.0, min(1.0, (progress - start) / max(1e-9, end - start)))
    min_explosion = float(control_path(("morph", "global", "minExplosion"), 0.0))
    explosion = max_explosion * (min_explosion + (1.0 - min_explosion) * (1.0 - ease_in_out(gp)))
    if explosion <= 1e-6:
        return Vector((0, 0, 0)), 0.0

    dx, dy, dz = (float(v) for v in cfg.get("direction", (1.0, 0.0, 0.0)))
    base_direction = Vector((dx, -dz, dy))
    if radial:
        origin = resolve_radial_origin(record, cfg, ball_center, context, host)
        direction = radial_direction(bounds_center, origin, base_direction, cfg)
    elif mirror == "x":
        side_x = -1 if bounds_center.x < ball_center.x else 1
        direction = Vector((base_direction.x * side_x, base_direction.y, base_direction.z))
    else:
        direction = base_direction

    translation = direction * (distance * explosion * multiplier)
    if include_host and host is not None and bool(cfg.get("followHost", True)) and host[2] is not None and host[2] is not record:
        host_translation, _ = group_offset(host[2], ball_center, progress, context, include_host=False)
        translation += host_translation * float(cfg.get("hostInfluence", 1.0))
    return translation, rotate_z * explosion * multiplier


def yaw_matrix(degrees: float, center: Vector) -> Matrix:
    return Matrix.Translation(center) @ Matrix.Rotation(math.radians(degrees), 4, "Z") @ Matrix.Translation(-center)


def apply_state(records: list[dict[str, Any]], center: Vector, state: dict[str, float], ball_center: Vector | None = None) -> dict[str, Any]:
    rotation = yaw_matrix(state["yawDegrees"], center)
    explosion_origin = ball_center if ball_center is not None else center
    motion_context = build_motion_context(records, explosion_origin)
    progress = float(state.get("progress", 0.0))
    quarter_turn = float(state.get("quarterTurn", 0.0))
    quarter_turn_degrees = float(control_path(("animation", "quarterTurn", "degrees"), 90.0))
    section_opacity = float(state.get("sectionOpacity", 1.0))
    transmission = (1.0 - section_opacity) * 0.9
    moved = 0
    max_offset = 0.0

    for record in records:
        for material in record["object"].data.materials:
            if material is None or material.node_tree is None:
                continue
            value_node = material.node_tree.nodes.get("zt_reveal_transmission")
            if value_node is not None:
                value_node.outputs[0].default_value = transmission

    for record in records:
        obj = record["object"]
        translation, rotate_z = group_offset(record, explosion_origin, progress, motion_context)
        if translation.length > 0.00001:
            moved += 1
        max_offset = max(max_offset, translation.length)
        base = record["baseMatrix"]
        if quarter_turn > 1e-6 and record["productName"] == "球体":
            qt_rot = Matrix.Translation(explosion_origin) @ Matrix.Rotation(quarter_turn * math.radians(quarter_turn_degrees), 4, "Z") @ Matrix.Translation(-explosion_origin)
            base = qt_rot @ base
        if abs(rotate_z) > 1e-6:
            obj_center = record_mesh_center(record)
            self_rot = Matrix.Translation(obj_center) @ Matrix.Rotation(rotate_z, 4, "Z") @ Matrix.Translation(-obj_center)
            obj.matrix_world = rotation @ self_rot @ Matrix.Translation(translation) @ base
        else:
            obj.matrix_world = rotation @ Matrix.Translation(translation) @ base
    bpy.context.view_layer.update()
    return {
        "movedObjectCount": moved,
        "maxOffsetMeters": round(max_offset, 6),
        "yawDegrees": round(state["yawDegrees"], 4),
        "assembly": round(state["assembly"], 6),
        "explosion": round(state["explosion"], 6),
        "quarterTurn": round(quarter_turn, 6),
        "quarterTurnDegrees": round(quarter_turn * quarter_turn_degrees, 4),
        "sectionOpacity": round(section_opacity, 6),
    }


def proof_dive_factor(progress: float) -> float:
    if not feature_enabled("proofCamera", False):
        return 0.0
    proof = control_path(("camera", "proof"), {"inFrom": 0.56, "inTo": 0.64, "outFrom": 0.80, "outTo": 0.92})
    in_from = float(proof.get("inFrom", 0.56))
    in_to = float(proof.get("inTo", 0.64))
    out_from = float(proof.get("outFrom", 0.80))
    out_to = float(proof.get("outTo", 0.92))
    if progress <= in_from or progress >= out_to:
        return 0.0
    if progress < in_to:
        return ease_in_out((progress - in_from) / max(1e-9, in_to - in_from))
    if progress < out_from:
        return 1.0
    return 1.0 - ease_in_out((progress - out_from) / max(1e-9, out_to - out_from))


def configure_camera(center: Vector, state: dict[str, float], ball_center: Vector | None = None) -> dict[str, Any]:
    scene = bpy.context.scene
    camera = scene.camera
    camera_data = camera.data
    camera_progress = state["cameraProgress"]
    progress = float(state.get("progress", 0.0))
    orbit_cfg = control_path(("camera", "orbitDegrees"), {"base": 88, "per": -10})
    radius_cfg = control_path(("camera", "radius"), {"base": 2.34, "per": -0.38})
    height_cfg = control_path(("camera", "height"), {"base": 0.16, "per": 0.50})
    target_x_cfg = control_path(("camera", "targetX"), {"base": 0.015, "per": -0.0059})
    target_z_cfg = control_path(("camera", "targetZ"), {"base": 0.15, "per": -0.142})
    ortho_cfg = control_path(("camera", "orthoScale"), {"base": 2.6, "per": -1.25})
    proof_cfg = control_path(("camera", "proof"), {})

    def linear(cfg: dict[str, Any], default: float) -> float:
        return float(cfg.get("base", default)) + float(cfg.get("per", 0.0)) * camera_progress

    base_orbit = linear(orbit_cfg, 88)
    base_height = linear(height_cfg, 0.16)
    base_ortho = linear(ortho_cfg, 2.6)
    dive = proof_dive_factor(progress)
    orbit_degrees = base_orbit + (float(proof_cfg.get("orbitDegrees", 8.0)) - base_orbit) * dive
    height = base_height + (float(proof_cfg.get("height", 0.0)) - base_height) * dive
    ortho_scale = base_ortho + (float(proof_cfg.get("orthoScale", 0.8)) - base_ortho) * dive

    radius = linear(radius_cfg, 2.34)
    camera.location = center + Vector((math.cos(math.radians(orbit_degrees)) * radius, math.sin(math.radians(orbit_degrees)) * radius, height))
    base_target = center + Vector((linear(target_x_cfg, 0.015), 0.0, linear(target_z_cfg, 0.15)))
    proof_target = ball_center if ball_center is not None else center
    target = base_target.lerp(proof_target, dive)
    if ISOLATED_MATERIAL_ROLES:
        target = center
    roll_cfg = control_path(("camera", "rollDegrees"), {"base": 0.0, "per": 0.0})
    look_at(camera, target, math.radians(linear(roll_cfg, 0.0)))
    camera_data.type = "ORTHO"
    camera_data.clip_end = 1000
    if ISOLATED_MATERIAL_ROLES and ISOLATE_ORTHO_SCALE_OVERRIDE is not None:
        ortho_scale = ISOLATE_ORTHO_SCALE_OVERRIDE
    camera_data.ortho_scale = ortho_scale
    return {
        "location": [round(v, 5) for v in camera.location],
        "target": [round(v, 5) for v in target],
        "orthoScale": round(camera_data.ortho_scale, 6),
        "isolateOrthoOverride": bool(ISOLATED_MATERIAL_ROLES and ISOLATE_ORTHO_SCALE_OVERRIDE is not None),
    }


def create_camera() -> Any:
    cam_data = bpy.data.cameras.new("CAM_independent_motion")
    cam = bpy.data.objects.new("CAM_independent_motion", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def render_frames(repo_root: Path, out_dir: Path, records: list[dict[str, Any]], product_bounds: dict[str, Any], frame_count: int, frame_list: list[int] | None) -> list[dict[str, Any]]:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    center = Vector(product_bounds["center"])
    ball_center = find_ball_center(records)
    create_camera()
    indices = frame_list if frame_list is not None else list(range(frame_count))
    frames: list[dict[str, Any]] = []
    started = time.perf_counter()
    for ordinal, frame_index in enumerate(indices, start=1):
        progress = frame_index / max(1, frame_count - 1)
        state = state_for(progress)
        motion = apply_state(records, center, state, ball_center)
        camera = configure_camera(center, state, ball_center)
        output_path = frames_dir / f"{frame_index:04d}.png"
        bpy.context.scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        frames.append(
            {
                "frameIndex": frame_index,
                "publicFrameNumber": frame_index + 1,
                "progress": round(progress, 6),
                **stage_for(progress, frame_count),
                "path": rel(repo_root, output_path),
                "bytes": output_path.stat().st_size,
                "sha256": sha256(output_path),
                "motion": motion,
                "camera": camera,
            }
        )
        if ordinal % 12 == 0 or ordinal == len(indices):
            print(f"rendered fixed ball valve hero frame {ordinal}/{len(indices)} in {time.perf_counter() - started:.1f}s")
    return frames


def load_controls(
    repo_root: Path,
    control_stack_arg: str,
    control_path_arg: str,
    lookdev_path_arg: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if control_stack_arg.strip():
        control, lookdev_doc, lookdev_audit, sources = load_control_stack(repo_root, control_stack_arg)
        CONTROL.clear()
        CONTROL.update(control)
        return control, lookdev_doc, lookdev_audit, sources

    if not control_path_arg.strip():
        raise RuntimeError("Legacy control mode requires --control when --control-stack is blank.")

    control_path_obj = repo_path(repo_root, control_path_arg)
    lookdev_path_obj = repo_path(repo_root, lookdev_path_arg)
    control = read_json(control_path_obj)
    lookdev_doc = read_json(lookdev_path_obj) if lookdev_path_obj.is_file() else {}
    raw_lookdev = lookdev_doc.get("lookdev", lookdev_doc) if isinstance(lookdev_doc, dict) else {}
    lookdev, lookdev_audit = filtered_lookdev(raw_lookdev)
    CONTROL.clear()
    CONTROL.update(control if isinstance(control, dict) else {})
    CONTROL["lookdev"] = lookdev
    sources = {
        "control": control_source_record(repo_root, control_path_obj, control.get("schema") if isinstance(control, dict) else None),
    }
    if lookdev_path_obj.is_file():
        sources["lookdev"] = control_source_record(
            repo_root,
            lookdev_path_obj,
            lookdev_doc.get("schema") if isinstance(lookdev_doc, dict) else None,
            lookdev_doc.get("variant") if isinstance(lookdev_doc, dict) else None,
        )
    return control, lookdev_doc, lookdev_audit, sources


def main() -> int:
    args = parse_args()
    global REPO_ROOT, MATERIAL_DIAGNOSTIC_MODE, ISOLATED_MATERIAL_ROLES, ISOLATE_ORTHO_SCALE_OVERRIDE
    repo_root = Path(args.repo_root).resolve()
    REPO_ROOT = repo_root
    MATERIAL_DIAGNOSTIC_MODE = args.material_diagnostic_mode.strip()
    ISOLATED_MATERIAL_ROLES = parse_material_role_filter(args.isolate_material_role)
    started = time.perf_counter()

    control_doc, lookdev_doc, lookdev_audit, control_sources = load_controls(repo_root, args.control_stack, args.control, args.lookdev_control)
    stack_material_mode = control_path(("diagnostic", "materialMode"), "")
    if not MATERIAL_DIAGNOSTIC_MODE and isinstance(stack_material_mode, str) and stack_material_mode in {"checker", "texture-only"}:
        MATERIAL_DIAGNOSTIC_MODE = stack_material_mode
    glb_value = args.glb or control_path(("asset", "glb"), DEFAULT_GLB)
    node_map_value = args.node_map or control_path(("parts", "nodeMap"), DEFAULT_NODE_MAP)
    glb_path = repo_path(repo_root, str(glb_value))
    node_map_path = repo_path(repo_root, str(node_map_value))
    sequence = control_doc.get("sequence", {}) if isinstance(control_doc, dict) else {}
    output_cfg = control_doc.get("output", {}) if isinstance(control_doc, dict) else {}
    default_out_dir = output_cfg.get("defaultOutDir", DEFAULT_OUT_DIR) if isinstance(output_cfg, dict) else DEFAULT_OUT_DIR
    out_value = args.out_root or args.out_dir or default_out_dir
    out_dir = repo_path(repo_root, out_value)
    manifest_path = repo_path(repo_root, args.manifest) if args.manifest else out_dir / "manifest.json"
    frames_dir = out_dir / "frames"
    frame_count = args.frame_count or int(sequence.get("frameCount", 240))
    width = args.width or int(sequence.get("width", 1920))
    height = args.height or int(sequence.get("height", 1080))
    samples = args.samples or int(sequence.get("samples", 48))
    frame_list = parse_frame_list(args.frame_list, frame_count)

    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_clear:
        clear_previous_frames(frames_dir)

    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not objects:
        raise RuntimeError(f"No mesh objects imported from {glb_path}")
    mesh_uv_audit = audit_mesh_uv_layers(objects)

    node_map = read_json(node_map_path)
    node_map_schema = str(node_map.get("schema", ""))
    if node_map_schema not in SUPPORTED_NODE_MAP_SCHEMAS:
        raise RuntimeError(f"Unexpected node map schema: {node_map.get('schema')!r}")
    glb_hash = sha256(glb_path)
    node_map_hash = sha256(node_map_path)
    normal_audit = rebuild_mesh_normals(objects)
    render_profile = configure_render(width, height, samples, repo_root)
    MATERIAL_TEXTURE_AUDIT.clear()
    MATERIAL_MAPPING_AUDIT.clear()
    mats = material_sets()["lookdev"]
    records, node_map_audit = bind_node_map(objects, node_map, mats, glb_hash)
    visible_records, isolation_audit = apply_material_role_isolation(records, ISOLATED_MATERIAL_ROLES)
    assigned_material_keys = set(node_map_audit.get("materialAssignmentCounts", {}).keys())
    assigned_mapping_audit = [
        entry for entry in MATERIAL_MAPPING_AUDIT if str(entry.get("roleKey")) in assigned_material_keys
    ]
    unused_mapping_audit = [
        entry for entry in MATERIAL_MAPPING_AUDIT if str(entry.get("roleKey")) not in assigned_material_keys
    ]
    product_bounds = world_bounds([record["object"] for record in visible_records])
    if ISOLATED_MATERIAL_ROLES:
        ISOLATE_ORTHO_SCALE_OVERRIDE = max(
            float(args.isolate_min_ortho_scale),
            float(product_bounds["radius"]) * max(0.01, float(args.isolate_fit_scale)),
        )
    center = Vector(product_bounds["center"])
    extent = Vector(product_bounds["extent"])
    lighting = add_lighting(center, extent)
    contact_shadow = add_contact_shadow(product_bounds)
    frames = render_frames(repo_root, out_dir, records, product_bounds, frame_count, frame_list)
    all_rendered = frame_list is None and len(frames) == frame_count

    manifest = {
        "schema": "ztovalve-fixed-ball-valve-hero-render/v1",
        "status": "rendered-full-sequence" if all_rendered else "rendered-sample",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "renderer": "standalone Blender script; corrected GLB normals + control-stack lookdev",
        "sources": {
            "glb": {"path": rel(repo_root, glb_path), "sha256": glb_hash},
            "nodeMap": {"path": rel(repo_root, node_map_path), "sha256": node_map_hash},
            "controls": control_sources,
        },
        "pipelineIsolation": {
            "usesCorrectedIndependentGlb": True,
            "clearsCustomSplitNormals": True,
            "rebuildsNormalsLocally": True,
            "readsNodeMap": True,
            "readsControlStack": bool(args.control_stack.strip()),
            "readsAnimationControls": True,
            "readsLookdevControls": True,
            "readsMappingControls": bool(control_path(("lookdev", "mapping"), {})),
            "usesLegacyOfficialRenderer": False,
            "usesLegacyMaterialMatrix": False,
            "usesLegacySplitFlangeFaces": False,
        },
        "renderProfile": {
            **render_profile,
            "frameCount": frame_count,
            "renderedFrameCount": len(frames),
            "renderedFrameList": frame_list,
            "stagingFrameNames": f"0000.png..{frame_count - 1:04d}.png",
        },
        "importedMeshObjects": len(objects),
        "materialRoleIsolation": isolation_audit,
        "nodeMapOrderAudit": node_map_audit,
        "lookdevAudit": lookdev_audit,
        "mappingAudit": {
            "schema": "ztovalve-render-mapping-audit/v1",
            "materialDiagnosticMode": MATERIAL_DIAGNOSTIC_MODE or "styled",
            "control": control_path(("lookdev", "mapping"), {}),
            "meshUvCoverage": mesh_uv_audit,
            "uvRequirementGate": node_map_audit.get("uvRequirementGate"),
            "assignedRoleMappings": assigned_mapping_audit,
            "unusedRoleMappingCount": len(unused_mapping_audit),
        },
        "textureAudit": MATERIAL_TEXTURE_AUDIT,
        "normalAudit": normal_audit,
        "bounds": product_bounds,
        "lighting": lighting,
        "contactShadow": contact_shadow,
        "outputs": {
            "stagingDir": rel(repo_root, out_dir),
            "framesDir": rel(repo_root, frames_dir),
            "manifest": rel(repo_root, manifest_path),
        },
        "frames": frames,
        "durationSeconds": round(time.perf_counter() - started, 3),
    }
    write_json(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "frames": len(frames), "manifest": rel(repo_root, manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

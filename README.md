# ZTO Valve Issue8 Independent PBR Lab

Clean migration repo for the successful issue8 fixed ball valve assets.

This is not a continuation of the earlier incorrect handoff project. The material authority is the independent per-role job batch:

```text
material-jobs/<role>/pbr-job-manifest.json
material-jobs/<role>/material-control.json
material-jobs/<role>/textures/<role>_*.png
```

The forbidden old source is intentionally absent:

```text
assets/textures/issue8-role-pbr
issue8 procedural PBR generator
```

## What Is Included

- Model: `assets/models/fixed-ball-valve-issue8-industrial-uv.glb`
- STEP source: `assets/source/固定式球阀.STEP`
- Node map: `assets-manifest/node-map.json`
- Independent PBR jobs: `material-jobs/`
- Merged material control: `controls/materials/role-pbr-materials.json`
- Axis exploded animation: `controls/animation/axis-assembly-clean-blender.json`
- Lighting rig: `controls/lighting/issue8-lighting.json`
- Three.js preview: `viewer/`
- Blender renderer: `scripts/render_fixed_ball_valve_hero.py`
- Independent preview evidence: `evidence/material-jobs-substance-v1/`

## Validate

```powershell
powershell -ExecutionPolicy Bypass -File tools\quick_validate.ps1
```

## Local Viewer

Install viewer dependencies once:

```powershell
npm --prefix viewer install
```

Then serve the repo root and open:

```text
http://127.0.0.1:<port>/viewer/?view=hero-exploded&explode=1
```

The viewer reads model, node map, material jobs, PBR maps, and lighting rig from local relative paths.

## Blender Smoke

Use the texture-only gate before any full 240-frame render:

```powershell
& 'D:\Tools\render-pipeline\apps\Blender-5.2.0\Blender Foundation\Blender 5.2\blender.exe' --background --python scripts\render_fixed_ball_valve_hero.py -- --repo-root . --control-stack controls\stacks\material-texture-only-gate.json --out-dir renders\material-gate\body_cast_shell --frame-list 120 --width 640 --height 360 --samples 8 --material-diagnostic-mode texture-only --isolate-material-role body_cast_shell
```

Only after material and lighting preview pass should the 240-frame stack be used.

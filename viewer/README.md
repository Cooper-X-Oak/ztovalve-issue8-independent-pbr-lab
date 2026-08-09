# Viewer

This viewer is a local Three.js rig/material preview. It is not the final renderer.

It loads:

- `../assets/models/fixed-ball-valve-issue8-industrial-uv.glb`
- `../assets-manifest/node-map.json`
- `../controls/material-jobs/index.json`
- `../material-jobs/<role>/pbr-job-manifest.json`
- `../material-jobs/<role>/material-control.json`
- `../controls/lighting/issue8-lighting.json`

Install dependencies:

```powershell
npm --prefix viewer install
```

Serve the repository root, then open:

```text
http://127.0.0.1:<port>/viewer/?view=hero-exploded&explode=1
```

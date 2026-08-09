# Handoff Notes

This repository is a clean migration from issue8 successful assets.

Authoritative material source:

```text
material-jobs/<role>/pbr-job-manifest.json
```

Do not promote any render unless its manifest proves:

- material preset path is `controls/materials/role-pbr-materials.json`
- texture paths resolve under `material-jobs/<role>/textures/`
- source is `substance-3d-texturing skill; local Substance-style procedural PBR authoring`
- kind is `single_role_substance_style_pbr_job`
- `oneBatchGeneratesAllRolesAllowed` is false
- missing maps count is zero

The `evidence/material-jobs-substance-v1/` folder contains the issue8 independent texture-only and styled per-role previews.

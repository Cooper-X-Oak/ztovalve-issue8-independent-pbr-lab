# AGENTS.md

- 唯一权威：本仓库以 `controls/stacks/main.json`、`controls/materials/role-pbr-materials.json`、`material-jobs/<role>/pbr-job-manifest.json`、`assets-manifest/node-map.json` 为当前 handoff 主线。
- 选定工作流：`industrial-texture-materials -> axis-assembly-exploded-view -> threejs-webgl -> industrial-render-gate`。
- 范围边界：本仓库只复用 issue8 成功资产；不要从旧错误 handoff 仓库、线上 viewer、`.scratch` 控制路径或 `assets/textures/issue8-role-pbr` 回读配置。
- 材质原则：17 个 role 必须来自 `single_role_substance_style_pbr_job` 独立 job；每个 role 8 张 1024 PBR/packed map。
- 爆炸原则：球心 / `polished_ball` 是装配基准；轴线式爆炸 rig 只迁移既有 issue8 contract，不在本仓库内重新发明散射算法。
- 灯光原则：本地 viewer 和 Blender stack 都读取 `controls/lighting/issue8-lighting.json`，不要用写死灯光代替 rig。
- 验收命令：`powershell -ExecutionPolicy Bypass -File tools/quick_validate.ps1`。
- 渲染 smoke 只允许低成本抽帧；全量 240 帧必须等材质 gate 和关键帧视觉确认后再跑。

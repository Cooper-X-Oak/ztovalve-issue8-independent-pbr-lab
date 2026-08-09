$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Failures = New-Object System.Collections.Generic.List[string]

function Add-Failure([string]$Message) {
  $Failures.Add($Message) | Out-Null
}

function Full-Path([string]$RelPath) {
  return Join-Path $Root $RelPath
}

function Read-Json([string]$RelPath) {
  $Path = Full-Path $RelPath
  if (-not (Test-Path -LiteralPath $Path)) {
    Add-Failure "Missing JSON: $RelPath"
    return $null
  }
  return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Require-File([string]$RelPath) {
  $Path = Full-Path $RelPath
  if (-not (Test-Path -LiteralPath $Path)) {
    Add-Failure "Missing file: $RelPath"
    return $false
  }
  return $true
}

function Sha256([string]$RelPath) {
  $Path = Full-Path $RelPath
  if (-not (Test-Path -LiteralPath $Path)) { return '' }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$RequiredFiles = @(
  'assets/models/fixed-ball-valve-issue8-industrial-uv.glb',
  'assets/source/固定式球阀.STEP',
  'assets-manifest/node-map.json',
  'controls/parts/role-segmentation.json',
  'controls/mapping/role-render-mapping.json',
  'controls/materials/role-pbr-materials.json',
  'controls/materials/per-role-independent-pbr-jobs.json',
  'controls/material-jobs/index.json',
  'controls/animation/features.json',
  'controls/animation/axis-assembly-clean-blender.json',
  'controls/animation/camera-hero-orbit.json',
  'controls/lighting/issue8-lighting.json',
  'controls/render/transparent-240-1080p.json',
  'controls/render/material-gate-640.json',
  'controls/stacks/main.json',
  'controls/stacks/material-texture-only-gate.json',
  'controls/stacks/material-styled-gate.json',
  'scripts/render_fixed_ball_valve_hero.py',
  'viewer/index.html',
  'viewer/src/app.js',
  'viewer/package.json',
  'README.md',
  'AGENTS.md'
)

foreach ($RelPath in $RequiredFiles) {
  Require-File $RelPath | Out-Null
}

$ForbiddenText = @(
  'assets/textures/issue8-role-pbr',
  'issue8 procedural PBR generator',
  'ztovalve-issue8-pbr-handoff'
)

$TextFiles = Get-ChildItem -LiteralPath $Root -Recurse -File |
  Where-Object {
    $_.Extension -in @('.json','.js','.html') -and
    $_.FullName -notlike '*\viewer\node_modules\*'
  }
foreach ($File in $TextFiles) {
  $Text = Get-Content -LiteralPath $File.FullName -Raw -Encoding UTF8
  foreach ($Needle in $ForbiddenText) {
    if ($Text -like "*$Needle*") {
      Add-Failure "Forbidden text '$Needle' found in $($File.FullName.Substring($Root.Length + 1))"
    }
  }
}

if (Test-Path -LiteralPath (Full-Path 'assets/textures/issue8-role-pbr')) {
  Add-Failure 'Forbidden old texture directory exists: assets/textures/issue8-role-pbr'
}

$Stacks = @(
  'controls/stacks/main.json',
  'controls/stacks/material-texture-only-gate.json',
  'controls/stacks/material-styled-gate.json'
)

foreach ($StackPath in $Stacks) {
  $Stack = Read-Json $StackPath
  if ($null -eq $Stack) { continue }
  $Refs = @(
    $Stack.asset.glb,
    $Stack.parts.nodeMap,
    $Stack.parts.roles,
    $Stack.render,
    $Stack.lookdev.view,
    $Stack.lookdev.environment,
    $Stack.lookdev.grounding,
    $Stack.lookdev.lighting,
    $Stack.lookdev.materials,
    $Stack.lookdev.mapping,
    $Stack.animation.features,
    $Stack.animation.motion,
    $Stack.animation.camera
  )
  foreach ($Ref in $Refs) {
    if ([string]::IsNullOrWhiteSpace($Ref)) {
      Add-Failure "Blank stack reference in $StackPath"
      continue
    }
    if ($Ref -like '.scratch*' -or $Ref -like '*\.scratch\*' -or $Ref -like '*\\.scratch/*') {
      Add-Failure "Scratch reference in ${StackPath}: $Ref"
    }
    Require-File $Ref | Out-Null
  }
}

$Index = Read-Json 'controls/material-jobs/index.json'
$Materials = Read-Json 'controls/materials/role-pbr-materials.json'
if ($null -ne $Index -and $null -ne $Materials) {
  $Jobs = @($Index.jobs)
  if ($Index.roleCount -ne 17 -or $Jobs.Count -ne 17) {
    Add-Failure "Expected 17 indexed material jobs, found roleCount=$($Index.roleCount), jobs=$($Jobs.Count)"
  }
  $MaterialRoles = @($Materials.materials.PSObject.Properties.Name | Sort-Object)
  if ($MaterialRoles.Count -ne 17) {
    Add-Failure "Expected 17 material roles, found $($MaterialRoles.Count)"
  }
  foreach ($Job in $Jobs) {
    $Role = $Job.role
    if ([string]::IsNullOrWhiteSpace($Role)) {
      Add-Failure 'Material job with blank role'
      continue
    }
    $ManifestRel = "material-jobs/$Role/pbr-job-manifest.json"
    $ControlRel = "material-jobs/$Role/material-control.json"
    $RenderStackRel = "material-jobs/$Role/render-stack.json"
    Require-File $ManifestRel | Out-Null
    Require-File $ControlRel | Out-Null
    Require-File $RenderStackRel | Out-Null
    $Manifest = Read-Json $ManifestRel
    $Control = Read-Json $ControlRel
    $JobDoc = Read-Json "controls/material-jobs/$Role.json"
    if ($null -eq $Manifest -or $null -eq $Control -or $null -eq $JobDoc) { continue }
    if ($Manifest.kind -ne 'single_role_substance_style_pbr_job') {
      Add-Failure "$Role manifest kind is $($Manifest.kind)"
    }
    if ($Manifest.issue8Rules.oneBatchGeneratesAllRolesAllowed -ne $false) {
      Add-Failure "$Role oneBatchGeneratesAllRolesAllowed is not false"
    }
    if ($Manifest.issue8Rules.wholeAssemblyTexturePassAllowed -ne $false) {
      Add-Failure "$Role wholeAssemblyTexturePassAllowed is not false"
    }
    $Source = $Control.materials.$Role.textureSet.source
    if ($Source -ne 'substance-3d-texturing skill; local Substance-style procedural PBR authoring') {
      Add-Failure "$Role unexpected material source: $Source"
    }
    foreach ($MapKey in @('baseColor','normal','metallic','roughness','height','ao','metallicRoughness','ORM')) {
      $MapRecord = $Manifest.textureSet.$MapKey
      if ($null -eq $MapRecord) {
        Add-Failure "$Role missing manifest map $MapKey"
        continue
      }
      $MapRel = $MapRecord.path
      if ($MapRel -notlike "material-jobs/$Role/textures/*") {
        Add-Failure "$Role map $MapKey is outside local material job textures: $MapRel"
      }
      Require-File $MapRel | Out-Null
      if ($MapRecord.sha256 -and ((Sha256 $MapRel) -ne $MapRecord.sha256.ToLowerInvariant())) {
        Add-Failure "$Role map $MapKey sha256 mismatch"
      }
      if (@($MapRecord.dimensions)[0] -ne 1024 -or @($MapRecord.dimensions)[1] -ne 1024) {
        Add-Failure "$Role map $MapKey dimensions are not 1024x1024"
      }
    }
    if ($JobDoc.validation.expectedMaps -ne 8 -or $Job.mapCount -ne 8) {
      Add-Failure "$Role job expected map count is not 8"
    }
  }
}

$MaterialJobDirs = @(Get-ChildItem -LiteralPath (Full-Path 'material-jobs') -Directory | Where-Object { $_.Name -ne 'material-jobs' })
$MaterialPngs = @(Get-ChildItem -LiteralPath (Full-Path 'material-jobs') -Recurse -File -Filter '*.png')
$EvidencePngs = @(Get-ChildItem -LiteralPath (Full-Path 'evidence/material-jobs-substance-v1') -Recurse -File -Filter '*.png')
if ($MaterialJobDirs.Count -ne 17) { Add-Failure "Expected 17 material-jobs role dirs, found $($MaterialJobDirs.Count)" }
if ($MaterialPngs.Count -ne 136) { Add-Failure "Expected 136 independent PBR map PNGs, found $($MaterialPngs.Count)" }
if ($EvidencePngs.Count -ne 36) { Add-Failure "Expected 36 evidence render PNGs, found $($EvidencePngs.Count)" }

$ViewerIndex = Get-Content -LiteralPath (Full-Path 'viewer/index.html') -Raw -Encoding UTF8
$ViewerApp = Get-Content -LiteralPath (Full-Path 'viewer/src/app.js') -Raw -Encoding UTF8
foreach ($Needle in @(
  './node_modules/three/build/three.module.js',
  'const PROJECT_ROOT = ".."',
  'assets/models/fixed-ball-valve-issue8-industrial-uv.glb',
  'controls/material-jobs/index.json',
  'MATERIAL_JOBS_ROOT',
  'controls/lighting/issue8-lighting.json',
  'RectAreaLightUniformsLib',
  'applyLightingRig'
)) {
  if ($ViewerIndex -notlike "*$Needle*" -and $ViewerApp -notlike "*$Needle*") {
    Add-Failure "Viewer missing expected marker: $Needle"
  }
}

if ($Failures.Count -gt 0) {
  Write-Host 'quick_validate: FAIL'
  foreach ($Failure in $Failures) {
    Write-Host " - $Failure"
  }
  exit 1
}

Write-Host 'quick_validate: PASS'
Write-Host ' - clean issue8 migration repo'
Write-Host ' - 17 independent single-role PBR jobs'
Write-Host ' - 136 PBR/packed maps from material-jobs'
Write-Host ' - 36 evidence preview PNGs'
Write-Host ' - local viewer paths and lighting rig resolved'

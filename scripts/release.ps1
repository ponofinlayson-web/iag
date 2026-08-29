<#
.SYNOPSIS
  IAG release tagger: version bump + changelog + annotated tag + GitHub release.

.DESCRIPTION
  Bumps backend (backend/pyproject.toml) and frontend (frontend/package.json)
  versions in lockstep, verifies the CHANGELOG.md has an entry for the target
  version, creates an annotated git tag, and optionally publishes a GitHub
  release from the changelog section.

  Idempotent-ish: refuses to run with a dirty tree or on a version that
  already has a tag. Safe to abort before -Push/-Publish.

.EXAMPLE
  # dry run: show what would happen
  ./scripts/release.ps1 -Version 0.4.0

  # full release: commit, push, tag, GitHub release
  ./scripts/release.ps1 -Version 0.4.0 -Push -Publish
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [switch]$Push,
    [switch]$Publish
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Fail([string]$m) { Write-Host "release: $m" -ForegroundColor Red; exit 1 }

# --- preflight ------------------------------------------------------------
$tag = "v$Version"
if (git status --porcelain) { Fail "dirty tree - commit or stash first" }
if (git rev-parse -q --verify "refs/tags/$tag") { Fail "tag $tag already exists" }

$pyproject = 'backend/pyproject.toml'
$pkgjson   = 'frontend/package.json'
$changelog = 'CHANGELOG.md'
foreach ($f in @($pyproject, $pkgjson, $changelog)) {
    if (-not (Test-Path $f)) { Fail "missing $f (run from repo root layout)" }
}

# --- changelog section must exist -----------------------------------------
$cl = Get-Content $changelog -Raw
if ($cl -notmatch "(?m)^## \[$([regex]::Escape($Version))\]") {
    Fail "CHANGELOG.md has no '## [$Version]' section - add it before releasing"
}
$pattern = "(?s)\## \[$([regex]::Escape($Version))\](.*?)(?=\n\## \[|\z)"
if ($cl -match $pattern) { $releaseNotes = $Matches[1].Trim() } else { $releaseNotes = '' }

# --- bump versions --------------------------------------------------------
$py = Get-Content $pyproject -Raw
$pyNew = $py -replace '(?m)^version\s*=\s*"[^"]*"', "version = `"$Version`""
if ($pyNew -eq $py) { Fail "could not find version in $pyproject" }
[IO.File]::WriteAllText((Resolve-Path $pyproject), $pyNew)

$json = Get-Content $pkgjson -Raw
$jsonNew = $json -replace '(?m)^(\s*)"version":\s*"[^"]*"', "`$1`"version`": `"$Version`""
if ($jsonNew -eq $json) { Fail "could not find version in $pkgjson" }
[IO.File]::WriteAllText((Resolve-Path $pkgjson), $jsonNew)

Write-Host "release: bumped backend + frontend to $Version" -ForegroundColor Green

# --- commit + tag (always) ------------------------------------------------
$msg = "release: v$Version"
git add $pyproject $pkgjson
git -c user.name="Pono Finlayson" -c user.email="ponofinlayson@users.noreply.github.com" commit -m $msg --quiet
git tag -a $tag -m "IAG $Version"
Write-Host "release: committed + tagged $tag" -ForegroundColor Green

if (-not $Push) {
    Write-Host "release: dry run complete - inspect, then re-run with -Push" -ForegroundColor Yellow
    exit 0
}

git push origin HEAD
git push origin $tag
Write-Host "release: pushed $tag" -ForegroundColor Green

if ($Publish) {
    $nl = [char]10
    $notesFile = Join-Path $env:TEMP "iag-release-notes-$Version.md"
    [IO.File]::WriteAllText($notesFile, $releaseNotes)
    gh release create $tag --repo ponofinlayson-web/iag --title "IAG $tag" --notes-file $notesFile
    Write-Host "release: GitHub release published for $tag" -ForegroundColor Green
}

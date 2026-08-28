# collect-evidence.ps1 — iag profile evidence collector (docs-forge)
# Logs into the ISOLATED test stack on :8091 and prints a JSON evidence
# snapshot for the guide's validation appendix.
$ErrorActionPreference = 'Stop'
$ROOT = $PWD.Path
$BASE = 'http://localhost:8091'

$pw = (Get-Content "$ROOT\.env" | Where-Object { $_ -match '^IAG_BOOTSTRAP_ADMIN_PASSWORD=' }) -replace '.*=', ''
if (-not $pw) { throw "no IAG_BOOTSTRAP_ADMIN_PASSWORD in $ROOT\.env" }

$e = [ordered]@{ generated = (Get-Date).ToString('yyyy-MM-dd HH:mm zzz'); base = $BASE }

try {
  $e.health = Invoke-RestMethod -Uri "$BASE/api/health" -TimeoutSec 5
} catch {
  throw "stack not healthy on $BASE - is the iag-test stack up? ($_)"
}

$login = Invoke-RestMethod -Method Post -Uri "$BASE/api/auth/login" -ContentType 'application/json' `
  -Body ('{"username":"admin","password":"' + $pw + '"}') -SessionVariable s

$e.dashboard       = Invoke-RestMethod -Uri "$BASE/api/dashboard" -WebSession $s
$e.audit_verify    = Invoke-RestMethod -Uri "$BASE/api/audit/verify" -WebSession $s
$camps             = Invoke-RestMethod -Uri "$BASE/api/campaigns" -WebSession $s
$e.campaigns       = @{ count = @($camps.items).Count
                        statuses = ($camps.items | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ' ' }
$e.api_keys        = @((Invoke-RestMethod -Uri "$BASE/api/api-keys" -WebSession $s).items).Count
$e.users           = @((Invoke-RestMethod -Uri "$BASE/api/users" -WebSession $s).items).Count

$json = $e | ConvertTo-Json -Depth 5
$json | Set-Content -Path "$ROOT\docs\_evidence.json" -Encoding utf8
Write-Output $json

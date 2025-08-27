param(
  [string]$Rail   = "https://glassserver.up.railway.app",
  [string]$Secret = "<YOUR_ADMIN_SECRET>"
)

function New-ProKey {
  param([string]$Email="test@example.com", [int]$MaxConcurrent=5, [int]$MaxActivations=1, [string]$Prefix="GL")
  $h=@{ Authorization = "Bearer $Secret" }
  $body = @{ tier="pro"; max_concurrent=$MaxConcurrent; max_activations=$MaxActivations; email=$Email; prefix=$Prefix } | ConvertTo-Json
  Invoke-RestMethod "$Rail/license/issue" -Headers $h -Method Post -ContentType "application/json" -Body $body
}

function Activate-License {
  param([string]$Key, [string]$HWID = $("nt-$env:COMPUTERNAME"))
  Invoke-RestMethod "$Rail/license/activate" -Method Post -ContentType "application/json" `
    -Body (@{ key=$Key; hwid=$HWID } | ConvertTo-Json)
}

function Validate-Token {
  param([string]$Token, [string]$HWID = $("nt-$env:COMPUTERNAME"))
  Invoke-RestMethod "$Rail/license/validate" -Method Post -ContentType "application/json" `
    -Body (@{ token=$Token; hwid=$HWID } | ConvertTo-Json)
}

function Verify-HWID {
  param([string]$HWID = $("nt-$env:COMPUTERNAME"))
  Invoke-RestMethod "$Rail/verify" -Method Post -ContentType "application/json" `
    -Body (@{ hwid=$HWID } | ConvertTo-Json)
}

function Introspect-Token {
  param([string]$Token)
  $h=@{ Authorization = "Bearer $Secret" }
  Invoke-RestMethod "$Rail/token/introspect" -Headers $h -Method Post -ContentType "application/json" `
    -Body (@{ token=$Token } | ConvertTo-Json)
}

function Revoke-Token {
  param([string]$Token)
  $h=@{ Authorization = "Bearer $Secret" }
  Invoke-RestMethod "$Rail/token/revoke" -Headers $h -Method Post -ContentType "application/json" `
    -Body (@{ token=$Token } | ConvertTo-Json)
}

function Static-List    { Invoke-RestMethod "$Rail/static-list" }
function Public-Config  { Invoke-RestMethod "$Rail/public-config" }
function Health         { Invoke-RestMethod "$Rail/healthz" }

Write-Host "Admin helpers loaded. Examples:" -ForegroundColor Cyan
Write-Host '  $k = (New-ProKey -Email "buyer@ex.com").key'
Write-Host '  $act = Activate-License -Key $k; $t=$act.token'
Write-Host '  Validate-Token -Token $t'
Write-Host '  Verify-HWID'
Write-Host '  Introspect-Token -Token $t'
Write-Host '  Revoke-Token -Token $t'

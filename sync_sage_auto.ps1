# =============================================================================
# SODIGAZ — Script de synchronisation automatique Sage X3 via Planificateur Windows
# =============================================================================

# CONFIGURATION
$ApiUrl = "https://sodigazback.yingr-ai.com/api/integration/sage/sync-today-system"
$Token = "test-token-123"  # Remplacer par ta valeur personnalisée de SAGE_X3_INBOUND_TOKEN / SAGE_X3_PUSH_TOKEN

$LogDir = "C:\SageExports\logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = "$LogDir\sync_sage_auto_log.txt"

# DATE ET HEURE DE DÉBUT
$Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$StartMsg = "$Now | =============================="
$StartMsg2 = "$Now | DEBUT SYNC AUTO Sage -> Backend"
$StartMsg3 = "$Now | =============================="
Write-Host $StartMsg
Write-Host $StartMsg2
Write-Host $StartMsg3
$StartMsg | Out-File -FilePath $LogFile -Append -Encoding utf8
$StartMsg2 | Out-File -FilePath $LogFile -Append -Encoding utf8
$StartMsg3 | Out-File -FilePath $LogFile -Append -Encoding utf8

# REQUÊTE API
try {
    $Headers = @{
        "X-Sage-X3-Token" = $Token
        "Content-Type"    = "application/json"
    }

    $Response = Invoke-RestMethod -Uri $ApiUrl -Method Post -Headers $Headers -TimeoutSec 120

    $Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $SuccessMsg = "$Now | OK | Sync réussie ! Programmes synchronisés: $($Response.synced) | Créés: $($Response.created) | Mis à jour: $($Response.updated)"
    Write-Host $SuccessMsg -ForegroundColor Green
    $SuccessMsg | Out-File -FilePath $LogFile -Append -Encoding utf8
} catch {
    $Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $ErrorMsg = "$Now | ERR | La synchronisation a échoué : $_"
    Write-Host $ErrorMsg -ForegroundColor Red
    $ErrorMsg | Out-File -FilePath $LogFile -Append -Encoding utf8
}

# FIN
$Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$EndMsg = "$Now | =============================="
$EndMsg2 = "$Now | FIN SYNC AUTO"
$EndMsg3 = "$Now | =============================="
Write-Host $EndMsg
Write-Host $EndMsg2
Write-Host $EndMsg3
$EndMsg | Out-File -FilePath $LogFile -Append -Encoding utf8
$EndMsg2 | Out-File -FilePath $LogFile -Append -Encoding utf8
$EndMsg3 | Out-File -FilePath $LogFile -Append -Encoding utf8

param(
  [int]$Limit = 20
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Split-Path -Parent $scriptDir
$repoDir = Split-Path -Parent $backendDir
$workspaceDir = Split-Path -Parent $repoDir
$pythonExe = Join-Path $workspaceDir '.venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
  throw "Python introuvable: $pythonExe"
}

Push-Location $backendDir
try {
  Write-Host "== Retry integration_outbox ==" -ForegroundColor Cyan
  & $pythonExe process_integration_outbox.py --limit $Limit --json

  Write-Host "`n== Etat recent outbox et deliveries ==" -ForegroundColor Cyan
$pythonSnippet = @"
LIMIT = $Limit

from app.database import SessionLocal
from app.models import Delivery, IntegrationOutbox

db = SessionLocal()
try:
    print()
    print("[Derniers evenements integration_outbox]")
    events = db.query(IntegrationOutbox).order_by(IntegrationOutbox.created_at.desc()).limit(LIMIT).all()
    if not events:
        print("Aucun evenement outbox.")
    for event in events:
        print(
            f"- #{event.id} {event.event_type} agg={event.aggregate_id} "
            f"status={event.status} retry={event.retry_count} "
            f"sent_at={event.sent_at.isoformat() if event.sent_at else '-'} "
            f"error={event.error_message or '-'}"
        )

    print()
    print("[Dernieres deliveries liees Sage]")
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.program_id.isnot(None))
        .order_by(Delivery.created_at.desc())
        .limit(LIMIT)
        .all()
    )
    if not deliveries:
        print("Aucune delivery liee a un programme Sage.")
    for delivery in deliveries:
        print(
            f"- delivery=#{delivery.id} program_id={delivery.program_id} "
            f"status={delivery.status.value if delivery.status else '-'} "
            f"sage_status={delivery.external_status.value if delivery.external_status else '-'} "
            f"sync_at={delivery.external_sync_at.isoformat() if delivery.external_sync_at else '-'} "
            f"error={delivery.external_error or '-'}"
        )
finally:
    db.close()
"@
  $tempPy = Join-Path $backendDir 'tmp_retry_outbox_status.py'
  Set-Content -Path $tempPy -Value $pythonSnippet -Encoding ASCII
  try {
    & $pythonExe $tempPy
  }
  finally {
    Remove-Item $tempPy -ErrorAction SilentlyContinue
  }
}
finally {
  Pop-Location
}
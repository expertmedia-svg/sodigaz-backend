@echo off
REM =============================================================================
REM SODIGAZ — Script Batch d'envoi des programmes vers l'API
REM Version 3.0 — Conversion CSV Sage X3 → JSON format SODIGAZ exact
REM
REM Auteur   : Comstrat Media Group
REM Date     : 06 mai 2026
REM
REM CSV Source : D:\Sage\X3V12\dossiers\SODIGAZG\EXPORT\export.json
REM API cible  : https://sodigazback.yingr-ai.com/api/logistics/v1/sage-missions/inbound
REM
REM Format CSV Sage (ligne E = entête) :
REM   E ; SITE ; NUM_PROG ; CHAUFFEUR ; CAMION ; DATE(AAAAMMJJ) ; HEURE(HHMM) ; TYPE
REM   L ; CLIENT ; PLV ; QUARTIER ; MODE ; ARTICLE ; QTE ; NUMFICHE
REM =============================================================================

setlocal enabledelayedexpansion

REM ── CONFIGURATION — MODIFIER CES VALEURS ─────────────────────────────────
SET API_URL=https://sodigazback.yingr-ai.com/api/logistics/v1/sage-missions/inbound
SET TOKEN=VOTRE_TOKEN_ICI
SET CSV_SOURCE=D:\Sage\X3V12\dossiers\SODIGAZG\EXPORT\export.json
SET DOSSIER=C:\SageExports\SODIGAZ\
SET LOG=C:\SageExports\logs\sodigaz_log.txt
SET JSON_OUT=C:\SageExports\SODIGAZ\tmp\converted.json
SET TIMEOUT=30

REM ── INITIALISATION ────────────────────────────────────────────────────────
if not exist "C:\SageExports\logs\"      mkdir "C:\SageExports\logs\"
if not exist "%DOSSIER%done\"            mkdir "%DOSSIER%done\"
if not exist "%DOSSIER%tmp\"             mkdir "%DOSSIER%tmp\"

echo ============================================
echo  SODIGAZ - Conversion CSV Sage et Envoi API
echo  %DATE% %TIME%
echo ============================================

REM ── VÉRIFIER QUE LE FICHIER CSV SOURCE EXISTE ────────────────────────────
if not exist "%CSV_SOURCE%" (
    echo ERREUR : Fichier source introuvable : %CSV_SOURCE%
    echo %DATE% %TIME% ^| ERREUR ^| Fichier source introuvable >> "%LOG%"
    exit /b 1
)

echo Fichier source trouve : %CSV_SOURCE%

REM ── CONVERSION CSV SAGE → JSON SODIGAZ via PowerShell ────────────────────
echo.
echo Conversion CSV Sage vers JSON SODIGAZ...

powershell -NoProfile -ExecutionPolicy Bypass -Command "
$csvFile = '%CSV_SOURCE%'
$outFile = '%JSON_OUT%'

$lines = Get-Content $csvFile -Encoding UTF8
$header = $null
$linesArr = New-Object System.Collections.ArrayList

foreach ($line in $lines) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split ';'

    if ($parts[0] -eq 'E') {
        # Ligne entete du programme
        $dateRaw  = $parts[5].Trim()   # ex: 20251103
        $heureRaw = $parts[6].Trim()   # ex: 1200

        # Formater date AAAAMMJJ -> AAAA-MM-JJ
        $dateFormatted = $dateRaw.Substring(0,4) + '-' + $dateRaw.Substring(4,2) + '-' + $dateRaw.Substring(6,2)

        # Formater heure HHMM -> HH:MM
        $heureFormatted = '00:00'
        if ($heureRaw.Length -ge 4) {
            $heureFormatted = $heureRaw.Substring(0,2) + ':' + $heureRaw.Substring(2,2)
        }

        # Determiner type programme
        $typeRaw = $parts[7].Trim()
        $typeLabel = if ($typeRaw -eq 'PCOL') { 'PCOL' } else { 'PRES' }

        $header = @{
            YTRSTYP  = $typeLabel
            YNUMPROG = $parts[2].Trim()
            YSTA     = '1'
            YFCY     = $parts[1].Trim()
            YFCYNAM  = $parts[1].Trim()
            YDATE    = $dateFormatted
            YTIME    = $heureFormatted
            YLIV     = $parts[3].Trim()
            YLIVNAM  = $parts[3].Trim()
            YMATCAM  = $parts[4].Trim()
            YCAMLIB  = $parts[4].Trim()
        }
        $linesArr.Clear()

    } elseif ($parts[0] -eq 'L' -and $header -ne $null) {
        # Ligne detail client
        $qtyRaw = $parts[6].Trim()
        $qty = 0
        [int]::TryParse(($qtyRaw -replace '[^0-9]',''), [ref]$qty) | Out-Null

        $lineObj = @{
            YBPC      = $parts[1].Trim()
            YBPCNAM   = $parts[1].Trim()
            YSOHNUM   = ''
            YSOPLIN   = ''
            YPLV      = $parts[2].Trim()
            YQUARTIER = $parts[3].Trim()
            YMOD      = $parts[4].Trim()
            YITMREF   = $parts[5].Trim()
            YITMDES   = $parts[5].Trim()
            YQTY      = $qty
            YNUMFICHE = $parts[7].Trim()
            YDES      = ''
        }
        $linesArr.Add($lineObj) | Out-Null
    }
}

if ($header -eq $null) {
    Write-Host 'ERREUR: Aucune ligne E (entete) trouvee dans le CSV'
    exit 1
}

# Construire le JSON final au format exact SODIGAZ
$payload = @{
    header = $header
    lines  = $linesArr.ToArray()
}

$json = $payload | ConvertTo-Json -Depth 10 -Compress:$false
$json | Set-Content $outFile -Encoding UTF8

Write-Host 'Conversion OK'
Write-Host ('Programme : ' + $header.YNUMPROG)
Write-Host ('Type      : ' + $header.YTRSTYP)
Write-Host ('Site      : ' + $header.YFCY)
Write-Host ('Chauffeur : ' + $header.YLIV)
Write-Host ('Camion    : ' + $header.YMATCAM)
Write-Host ('Lignes    : ' + $linesArr.Count)
"

IF ERRORLEVEL 1 (
    echo ERREUR : Conversion CSV echouee - verifiez le format du fichier CSV
    echo %DATE% %TIME% ^| ERREUR ^| Conversion CSV echouee >> "%LOG%"
    exit /b 1
)

echo.
echo JSON genere : %JSON_OUT%

REM ── ENVOI JSON VERS API SODIGAZ ───────────────────────────────────────────
echo.
echo Envoi vers API SODIGAZ...

SET RESULTAT=ERR
SET HTTP_CODE=000

REM Tentative 1
call :ENVOYER 1
IF "!RESULTAT!"=="OK" goto :ENVOI_OK

REM Tentative 2
echo Retry 2/3...
timeout /t 5 /nobreak >nul
call :ENVOYER 2
IF "!RESULTAT!"=="OK" goto :ENVOI_OK

REM Tentative 3
echo Retry 3/3...
timeout /t 10 /nobreak >nul
call :ENVOYER 3
IF "!RESULTAT!"=="OK" goto :ENVOI_OK

REM Echec definitif
echo.
echo ERREUR DEFINITIVE : Envoi echoue apres 3 tentatives
echo Code HTTP : !HTTP_CODE!
IF "!HTTP_CODE!"=="401" echo CAUSE : Token incorrect - verifiez VOTRE_TOKEN_ICI
IF "!HTTP_CODE!"=="400" echo CAUSE : JSON invalide - verifiez le format CSV Sage
IF "!HTTP_CODE!"=="500" echo CAUSE : Erreur serveur SODIGAZ - contacter Comstrat
echo %DATE% %TIME% ^| ERREUR ^| Envoi echoue ^| HTTP !HTTP_CODE! >> "%LOG%"
exit /b 1

:ENVOI_OK
echo.
echo ============================================
echo  SUCCES : Programme envoye a SODIGAZ !
echo  HTTP : 200 OK
echo ============================================

REM Archiver le CSV source avec timestamp
SET TS=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
SET TS=!TS: =0!
copy "%CSV_SOURCE%" "%DOSSIER%done\export_!TS!.csv" >nul 2>&1

REM Afficher la reponse de l'API
echo.
echo Reponse API SODIGAZ :
type "%DOSSIER%tmp\resp_tmp.json" 2>nul
echo.

echo %DATE% %TIME% ^| OK ^| Programme envoye ^| HTTP 200 >> "%LOG%"

endlocal
exit /b 0

REM ── SOUS-ROUTINE ENVOI ────────────────────────────────────────────────────
:ENVOYER
SET TENTATIVE=%~1
SET HTTP_CODE=000

curl -s -X POST "%API_URL%" ^
     -H "Content-Type: application/json" ^
     -H "X-Sage-X3-Token: %TOKEN%" ^
     --data-binary "@%JSON_OUT%" ^
     --max-time %TIMEOUT% ^
     -w "%%{http_code}" ^
     -o "%DOSSIER%tmp\resp_tmp.json" > "%DOSSIER%tmp\code.txt" 2>&1

SET /p HTTP_CODE=<"%DOSSIER%tmp\code.txt"

IF "%HTTP_CODE%"=="200" (
    echo OK - HTTP 200 ^| Tentative %TENTATIVE%
    echo %DATE% %TIME% ^| OK ^| HTTP 200 ^| Tentative %TENTATIVE% >> "%LOG%"
    SET RESULTAT=OK
) ELSE IF "%HTTP_CODE%"=="201" (
    echo OK - HTTP 201 ^| Tentative %TENTATIVE%
    echo %DATE% %TIME% ^| OK ^| HTTP 201 ^| Tentative %TENTATIVE% >> "%LOG%"
    SET RESULTAT=OK
) ELSE (
    echo WARN - HTTP %HTTP_CODE% ^| Tentative %TENTATIVE%
    echo %DATE% %TIME% ^| WARN ^| HTTP %HTTP_CODE% ^| Tentative %TENTATIVE% >> "%LOG%"
    SET RESULTAT=ERR
)

goto :EOF

REM =============================================================================
REM ORDRE DES COLONNES CSV SAGE (à adapter si votre modèle est différent)
REM
REM Ligne E (entête) :
REM   0=E ; 1=SITE(YFCY) ; 2=NUM_PROG ; 3=CHAUFFEUR(YLIV) ; 4=CAMION(YMATCAM)
REM   5=DATE(AAAAMMJJ) ; 6=HEURE(HHMM) ; 7=TYPE(PCOL/PRES)
REM
REM Ligne L (détail) :
REM   0=L ; 1=CLIENT(YBPC) ; 2=PLV ; 3=QUARTIER ; 4=MODE(YMOD)
REM   5=ARTICLE(YITMREF) ; 6=QTE ; 7=NUMFICHE
REM
REM PLANIFICATION :
REM   Programme : cmd.exe
REM   Arguments : /c "C:\SageExports\send_sodigaz.bat"
REM   Fréquence : Toutes les 5 minutes
REM =============================================================================

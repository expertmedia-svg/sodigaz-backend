# Retry Outbox Sage

## But

Relancer manuellement les evenements `pending` ou `failed_retryable` de `integration_outbox` quand Sage redevient joignable.

## Commande recommandee

Depuis [gas-platform/backend](gas-platform/backend):

```powershell
c:/Users/BNT/Documents/PROJET SODIGAZ/.venv/Scripts/python.exe process_integration_outbox.py --limit 20 --json
```

## Script PowerShell pret a l'emploi

Depuis [gas-platform/backend](gas-platform/backend):

```powershell
powershell -ExecutionPolicy Bypass -File RECETTE-SAGE/retry-outbox-and-check.ps1 -Limit 20
```

Ce script:

- rejoue l'outbox Sage
- affiche un resume JSON du traitement
- liste les derniers statuts `integration_outbox`
- liste les derniers statuts `deliveries` avec `external_status`, `external_sync_at`, `external_error`

## Effet attendu

- les evenements en attente sont rejoues
- si l'envoi reussit, leur statut passe a `sent`
- pour les evenements de type livraison/collecte, `deliveries.external_status` passe a `SYNCED`
- `deliveries.external_sync_at` est renseigne
- `deliveries.external_error` est vide

## Variante rapide

```powershell
c:/Users/BNT/Documents/PROJET SODIGAZ/.venv/Scripts/python.exe process_integration_outbox.py
```

## Quand l'utiliser

- apres une panne reseau vers Sage
- apres un incident d'authentification Sage corrige
- apres validation d'une mission si l'outbox est restee en `failed_retryable`

## Verification apres retry

Verifier dans la base ou l'admin:

- `integration_outbox.status`
- `deliveries.external_status`
- `deliveries.external_sync_at`
- `deliveries.external_error`
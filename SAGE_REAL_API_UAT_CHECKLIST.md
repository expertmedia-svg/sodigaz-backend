# Checklist UAT Sage Reel

Document de reference partage: voir aussi [backend/RECETTE-SAGE/README.md](backend/RECETTE-SAGE/README.md).

## 1. Parametres obligatoires

- URL reelle Sage X3
- Type d'auth sortante: `bearer` ou header simple
- Type d'auth entrante vers `/api/integration/sage/programs`
- Secret/token entrant partage
- Exemples reels de `YLIV` et `YMATCAM`
- 2 payloads reels minimum: un mappe, un non mappe

## 2. Configuration backend

- Copier `.env.sage-real.example` vers `.env.production` ou votre fichier de deploiement
- Passer `SAGE_X3_PUSH_MODE=http`
- Renseigner `SAGE_X3_BASE_URL`
- Renseigner `SAGE_X3_API_KEY`
- Renseigner `SAGE_X3_INBOUND_AUTH_HEADER`
- Renseigner `SAGE_X3_INBOUND_AUTH_SCHEME`
- Renseigner `SAGE_X3_INBOUND_TOKEN`

## 3. Verification avant tests reels

- Migration schema programme deja executee: `migrations/20260408_add_program_pricing_schema.py`
- Migration mapping deja executee: `migrations/20260409_add_driver_mapping_table.py`
- Mappings reels saisis dans l'admin `/driver-mappings`
- Health backend OK: `GET /health`
- Health Sage sortant OK via worker/check health

## 4. Tests d'entree Sage reels

### Cas A: programme mappe

- Envoyer un payload reel avec `YLIV` connu
- `YMATCAM` connu
- Verifier en base:
  - `program.driver_id` renseigne
  - `program.status = active` ou statut attendu
- Verifier API chauffeur:
  - `/api/driver/bootstrap` contient le `program_code`
  - `today_programs` contient le programme
  - `assignments` contient les lignes projetees

### Cas B: programme non mappe

- Envoyer un payload reel avec `YLIV` ou `YMATCAM` inconnu
- Verifier en base:
  - `program.driver_id IS NULL`
  - `program.status = UNASSIGNED`
- Verifier API chauffeur:
  - le `program_code` n'apparait pas dans `/api/driver/bootstrap`

## 5. Tests de robustesse

- Rejouer le meme `program_code` avec meme `sync_version`
- Rejouer le meme `program_code` avec `sync_version` plus haut
- Envoyer un payload avec date/heure manquantes
- Envoyer un produit inconnu
- Envoyer un `depot_id` inconnu
- Couper l'acces reseau Sage et tester les checks health sortants

## 6. Critere go/no-go

- Un programme mappe visible uniquement chez le bon chauffeur
- Un programme non mappe reste `UNASSIGNED`
- Aucune fuite de programme vers un autre chauffeur
- Auth entrante Sage validee avec le vrai header attendu
- Health sortant Sage en `healthy`
- Aucun conflit de schema en base

## 7. Commandes utiles

### Export des mappings locaux

```powershell
c:/Users/BNT/Documents/PROJET SODIGAZ/.venv/Scripts/python.exe backend/export_driver_mapping_reference.py
```

### Test manuel d'injection vers le backend

```powershell
c:/Users/BNT/Documents/PROJET SODIGAZ/.venv/Scripts/python.exe backend/test_sage_real_program_push.py --file backend/samples/sage_program_real_template.json
```
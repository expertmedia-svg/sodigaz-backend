# Recette UAT Flux Programme Sage Chauffeur

Document de reference partage: voir aussi [backend/RECETTE-SAGE/README.md](backend/RECETTE-SAGE/README.md).

## But

Verifier manuellement le flux bidirectionnel suivant:

1. Sage envoie un programme
2. le bon chauffeur voit le programme du jour et les missions associees
3. une validation terrain met a jour les tables backend
4. le retour part automatiquement vers Sage
5. la mission validee quitte le programme du jour et passe en historique termine cote chauffeur

## Prerequis

- backend demarre avec schema a jour
- mapping chauffeur/camion Sage deja saisi
- mode Sage au moins en `mock` ou en environnement reel de test
- un chauffeur de test capable de se connecter sur l'application mobile

## Cas 1: programme completement termine

### Preparation

- injecter un programme Sage avec une seule ligne pour le chauffeur cible
- verifier dans l'admin que le programme apparait dans [gas-platform/frontend-admin/src/pages/ProgramsPage.jsx](gas-platform/frontend-admin/src/pages/ProgramsPage.jsx)
- verifier dans le dashboard que le compteur “Programmes du jour” augmente

### Verifications avant terrain

- appeler `/api/driver/bootstrap` pour le chauffeur cible
- verifier:
  - `assignments` contient 1 mission
  - `today_programs` contient 1 programme
  - le `program_code` est correct

### Action terrain

- depuis l'application chauffeur, ouvrir la mission
- valider la livraison ou la collecte avec signature/photo

### Resultat attendu

- la mission disparait de la vue “Programme du jour”
- la mission apparait dans l'historique “Termine” cote chauffeur
- dans la base:
  - `deliveries.status = COMPLETED`
  - `program_lines.status = delivered` ou `collected`
  - `programs.status = completed`
- dans `integration_outbox`:
  - un evenement `DELIVERY_CONFIRMED` ou `COLLECTION_CONFIRMED` existe
  - son statut devient `sent`
- si Sage est joignable:
  - `deliveries.external_status = SYNCED`
  - `deliveries.external_sync_at` est renseigne

## Cas 2: programme partiellement termine

### Preparation

- injecter un programme Sage avec 2 lignes pour le meme chauffeur
- verifier que `today_programs` contient 1 programme avec 2 lignes

### Action terrain

- valider uniquement la premiere mission
- ne pas valider la seconde

### Resultat attendu

- cote chauffeur:
  - il reste 1 mission dans `assignments`
  - `today_programs` contient toujours le programme
  - le programme passe en statut `in_progress`
- dans la base:
  - la ligne 1 est `delivered` ou `collected`
  - la ligne 2 reste `pending`
  - `programs.status = in_progress`
- l'evenement de retour Sage de la premiere mission part sans erreur

## Cas 3: controle d'isolation chauffeur

### Preparation

- injecter un programme mappe pour un chauffeur A

### Resultat attendu

- le chauffeur A voit le programme
- un autre chauffeur B ne voit ni le programme ni les missions correspondantes

## Points de controle SQL recommandés

- `programs.program_code`
- `programs.status`
- `program_lines.line_code`
- `program_lines.status`
- `program_lines.quantity_delivered`
- `program_lines.quantity_collected`
- `deliveries.status`
- `deliveries.external_status`
- `deliveries.external_sync_at`
- `integration_outbox.event_type`
- `integration_outbox.status`

## Reference automatisee

Les scenarii automatises equivalents sont dans [gas-platform/backend/tests/test_program_integration.py](gas-platform/backend/tests/test_program_integration.py):

- `test_bidirectional_program_flow_completes_program_and_removes_it_from_driver_today_view`
- `test_partial_driver_validation_keeps_program_in_progress_until_all_lines_are_done`
- `test_collection_program_upsert_and_confirmation_creates_collection_event`
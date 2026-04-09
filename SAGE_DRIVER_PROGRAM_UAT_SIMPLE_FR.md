# Test Utilisateur Simple Programme Sage

Document de reference partage: voir aussi [backend/RECETTE-SAGE/README.md](backend/RECETTE-SAGE/README.md).

## Pour qui

- superviseur depot
- equipe support
- chauffeur test

## Ce qu'on veut verifier

- le bon chauffeur recoit le bon programme
- quand une mission est validee, elle disparait du programme du jour
- la mission va dans `Termine`
- le retour Sage part automatiquement

## Test 1: programme recu par le bon chauffeur

### Etapes

1. Envoyer un programme Sage de test pour un chauffeur connu.
2. Ouvrir l'application chauffeur avec ce compte.
3. Ouvrir l'ecran `Programme du jour`.

### Resultat attendu

- le programme apparait
- les missions du programme apparaissent
- un autre chauffeur ne voit pas ce programme

## Test 2: mission validee sur le terrain

### Etapes

1. Le chauffeur ouvre une mission du programme.
2. Il valide avec signature ou photo.
3. Attendre la fin de la synchronisation automatique.

### Resultat attendu

- la mission n'apparait plus dans `Programme du jour`
- la mission apparait dans `Termine`
- dans l'admin, le programme ou la ligne change de statut
- le retour Sage est envoye automatiquement

## Test 3: programme partiellement traite

### Etapes

1. Envoyer un programme avec 2 missions.
2. Le chauffeur valide seulement la premiere.

### Resultat attendu

- la premiere mission disparait des missions actives
- la seconde reste visible
- le programme reste visible mais passe en `in_progress`

## Test 4: retour Sage en erreur

### Etapes

1. Simuler une indisponibilite Sage ou couper le retour sortant.
2. Valider une mission cote chauffeur.

### Resultat attendu

- la mission est bien terminee cote chauffeur
- elle sort du programme du jour
- elle reste en historique `Termine`
- le backend garde une trace de l'erreur Sage pour reessai

## Si tout est bon

Le flux suivant est conforme:

- Sage -> programme chauffeur
- chauffeur -> validation terrain
- backend -> mise a jour programme
- backend -> retour automatique Sage

## Reference technique

- detail de recette: [gas-platform/backend/SAGE_DRIVER_PROGRAM_UAT_FR.md](gas-platform/backend/SAGE_DRIVER_PROGRAM_UAT_FR.md)
- mapping des champs: [gas-platform/backend/SAGE_SHARED_FIELD_MAPPING.md](gas-platform/backend/SAGE_SHARED_FIELD_MAPPING.md)
- tests automatiques: [gas-platform/backend/tests/test_program_integration.py](gas-platform/backend/tests/test_program_integration.py)
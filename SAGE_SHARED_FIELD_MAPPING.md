# Mapping partage Sage X3 / Backend / Chauffeur

Document de reference partage: voir aussi [backend/RECETTE-SAGE/README.md](backend/RECETTE-SAGE/README.md).

## Objectif

Ce document fixe la correspondance entre les donnees partagees par Sage X3, les tables backend Sodigaz, et les vues exposees au chauffeur/admin.

Il couvre le flux bidirectionnel V3:

- Sage pousse un programme dans `Program` et `ProgramLine`
- Le backend projette les lignes en `Delivery`
- Le chauffeur valide sur le terrain
- Le backend met a jour `Program`, `ProgramLine`, `Delivery`
- Le retour est emis vers Sage via `IntegrationOutbox`

## Tables backend de reference

- `programs`: entete du programme Sage du jour
- `program_lines`: lignes detaillees du programme par client/article
- `deliveries`: projection terrain exploitable par le chauffeur
- `integration_outbox`: file d'echange retour vers Sage

## Mapping entete programme

| Champ Sage | Sens metier | Table backend | Colonne backend | Exposition admin/chauffeur |
| --- | --- | --- | --- | --- |
| `YTRSTYP` | type de programme (`PCOL`, `PRES`, etc.) | `programs` | `program_type` | Dashboard, ProgramsPage, bootstrap chauffeur |
| `YNUMPROG` | code programme Sage | `programs` | `program_code` | Dashboard, ProgramsPage, programme du jour chauffeur |
| `YFCY` | code site | `programs` | `site_code` | Dashboard, ProgramsPage, debug payload |
| `YDATE` | date programme | `programs` | `program_date` | Dashboard, ProgramsPage, programme du jour |
| `YTIME` | heure programme | `programs` | `program_time` | Dashboard, ProgramsPage |
| `YLIV` | code chauffeur Sage | `programs` + metadata payload | `source_payload.assignment.sage_driver_code` | controle d'affectation, traçabilite |
| `YMATCAM` | matricule camion Sage | `programs` + metadata payload | `source_payload.assignment.truck_code` | controle d'affectation, programme du jour |
| transporteur/libelle | nom transporteur | `programs` | `transporter_name` | Dashboard, ProgramsPage |
| statut Sage entrant | statut programme source | `programs` | `status` | filtre programme actif/en cours/termine |

## Mapping lignes programme

| Champ Sage | Sens metier | Table backend | Colonne backend | Exposition admin/chauffeur |
| --- | --- | --- | --- | --- |
| `external_line_id` / ref ligne Sage | identifiant ligne unique | `program_lines` | `external_line_id` | suivi d'idempotence et sync |
| `line_code` | code ligne fonctionnel | `program_lines` | `line_code` | ProgramsPage, bootstrap |
| `YBPC` | code client | `program_lines` | `client_code` / `client_id` | bootstrap chauffeur, ProgramsPage |
| `YBPCNAM` | nom client | `program_lines` | `client_name` | admin + chauffeur |
| `destination_address` | adresse client | `program_lines` | `destination_address` | navigation chauffeur |
| `contact_name` | interlocuteur | `program_lines` | `contact_name` | detail mission |
| `contact_phone` | telephone | `program_lines` | `contact_phone` | detail mission |
| `YITMREF` | code article | `program_lines` | `product_code` | ProgramsPage, bootstrap, driver history |
| `YITMDES` | libelle article | `program_lines` | `product_label` | ProgramsPage |
| `article` | reference bouteille/business | `program_lines` | `article` | programme du jour chauffeur |
| `YQUARTIER` | zone/quartier | `program_lines` | `zone` | detail terrain |
| `YQTY` | quantite prevue | `program_lines` | `quantity_planned` | ProgramsPage, programme du jour |
| quantite livree retour terrain | execution livraison | `program_lines` | `quantity_delivered` | ProgramsPage, sync retour Sage |
| quantite collectee retour terrain | execution collecte | `program_lines` | `quantity_collected` | ProgramsPage, sync retour Sage |
| `YPLV` / mode / fiche | enrichissements terrain | `program_lines` | `delivery_mode`, `collection_sheet`, `comment` | chauffeur + admin |

## Projection terrain dans deliveries

Chaque `program_line` cree ou met a jour une ligne `deliveries` pour le chauffeur.

| Source | Table backend | Colonne backend | Usage terrain |
| --- | --- | --- | --- |
| `programs.id` | `deliveries` | `program_id` | rattachement programme |
| `program_lines.id` | `deliveries` | `program_line_id` | rattachement ligne |
| `programs.program_type` | `deliveries` | `program_type` | savoir si livraison ou collecte |
| `program_lines.quantity_planned` | `deliveries` | `quantity`, `quantity_6kg`, `quantity_12kg` | mission visible chauffeur |
| retour terrain livre | `deliveries` | `delivered_quantity_total` | suivi execution |
| retour terrain collecte | `deliveries` | `collected_quantity_total` | suivi execution |
| montant resolu | `deliveries` | `unit_price_applied`, `tax_rate_applied`, `subtotal_amount`, `tax_amount`, `total_amount` | reporting et retour Sage |
| statut mission | `deliveries` | `status` | `PENDING`, `IN_PROGRESS`, `COMPLETED` |
| statut sync Sage | `deliveries` | `external_status`, `external_sync_at`, `external_error` | traçabilite flux bidirectionnel |

## Regles de cycle de vie

### A la reception d'un programme Sage

- `Program.status` est initialise selon le payload entrant
- chaque ligne Sage alimente `ProgramLine`
- chaque `ProgramLine` est projete en `Delivery`
- le bootstrap chauffeur expose:
  - `assignments`: seulement les `Delivery` en `PENDING` ou `IN_PROGRESS`
  - `today_programs`: seulement les `Program` en `active` ou `in_progress`

### A la validation terrain chauffeur

- le batch `/api/driver/sync/batch` met a jour la ligne `ProgramLine`
- `Delivery` passe en `COMPLETED`
- les quantites executees sont consolidees dans `Delivery`
- le backend recalcule `Program.status`
  - toutes les lignes traitees -> `completed`
  - au moins une ligne commencee -> `in_progress`
  - sinon -> `active`
- un evenement `DELIVERY_CONFIRMED` ou `COLLECTION_CONFIRMED` est ecrit dans `integration_outbox`
- l'outbox est traitee immediatement
- si l'envoi Sage reussit:
  - `deliveries.external_status = SYNCED`
  - `deliveries.external_sync_at` est renseigne
- si l'envoi Sage echoue:
  - `deliveries.external_error` conserve le message d'erreur

### Effet attendu cote chauffeur

- une mission validee sort de `assignments`
- si elle cloture la derniere ligne du programme, le programme disparait de `today_programs`
- la mission reste visible en historique local avec statut metier `termine`
- l'etat de synchronisation reste porte par `sync_state`, pas par un faux statut metier

## Test de reference disponible

Le scenario de reference est execute par:

- `backend/tests/test_program_integration.py::test_bidirectional_program_flow_completes_program_and_removes_it_from_driver_today_view`

Ce test verifie:

- creation du programme Sage
- projection en mission chauffeur
- validation terrain via `/api/driver/sync/batch`
- mise a jour de `ProgramLine`, `Delivery`, `Program`
- emission et traitement outbox Sage
- disparition du programme du jour apres completion
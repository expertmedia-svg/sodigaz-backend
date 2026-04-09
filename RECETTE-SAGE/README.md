# Dossier Recette Sage

Ce dossier regroupe les documents a partager pour la recette fonctionnelle et technique du flux programme Sage X3.

Les fichiers racine `SAGE_*.md` restent les sources completes. Ce dossier sert de package de partage compact, avec index, raccourcis et commandes utiles, pour eviter de diffuser plusieurs points d'entree concurrents.

## Ordre de lecture recommande

1. [01-UAT-Simple.md](01-UAT-Simple.md)
2. [02-UAT-Detaillee.md](02-UAT-Detaillee.md)
3. [03-Mapping-Champs.md](03-Mapping-Champs.md)
4. [04-UAT-API-Reelle.md](04-UAT-API-Reelle.md)
5. [05-Retry-Outbox.md](05-Retry-Outbox.md)

## Contenu

- `01-UAT-Simple.md`: guide court pour superviseurs, support et chauffeur test
- `02-UAT-Detaillee.md`: recette detaillee de bout en bout
- `03-Mapping-Champs.md`: correspondance champs Sage -> backend -> vues admin/chauffeur
- `04-UAT-API-Reelle.md`: checklist de branchement vers la vraie API Sage
- `05-Retry-Outbox.md`: commande manuelle de relecture/retry de l'outbox Sage

## Reference de tests automatiques

- [../tests/test_program_integration.py](../tests/test_program_integration.py)

Scenarios de reference:

- complet: `test_bidirectional_program_flow_completes_program_and_removes_it_from_driver_today_view`
- partiel: `test_partial_driver_validation_keeps_program_in_progress_until_all_lines_are_done`
- collecte: `test_collection_program_upsert_and_confirmation_creates_collection_event`
- echec sortant: `test_outbound_sage_failure_sets_external_error_but_keeps_driver_flow_consistent`
- retry apres reprise Sage: `test_failed_retryable_outbox_event_is_sent_after_sage_recovers`
# UAT Detaillee

Voir la version source complete: [../SAGE_DRIVER_PROGRAM_UAT_FR.md](../SAGE_DRIVER_PROGRAM_UAT_FR.md)

## Points controles

- presence dans `/api/driver/bootstrap`
- mise a jour de `Program`, `ProgramLine`, `Delivery`
- emission `IntegrationOutbox`
- sortie du programme du jour apres completion totale
- maintien du programme en `in_progress` apres completion partielle
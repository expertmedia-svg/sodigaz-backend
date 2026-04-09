# UAT API Reelle

Voir la source complete: [../SAGE_REAL_API_UAT_CHECKLIST.md](../SAGE_REAL_API_UAT_CHECKLIST.md)

## Controle minimum avant go-live

- auth entrante Sage validee
- mapping chauffeur/camion complet
- programme mappe visible uniquement chez le bon chauffeur
- programme non mappe reste `UNASSIGNED`
- health sortant Sage `healthy`
- retour outbox correctement traite
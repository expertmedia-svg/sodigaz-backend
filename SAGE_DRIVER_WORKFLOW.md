# Workflow Complet: Chauffeurs Sage → App Mobile → Validation Sage

Ce document décrit le flux complet d'intégration entre Sage X3, le backend et l'app mobile des chauffeurs.

---

## 📋 Vue d'ensemble

```
Sage X3 SQL
    ↓
    ├─ Lire codes YLIV (chauffeur) et YMATCAM (camion)
    ├─ Lire programmes YPRGCOLL
    ↓
Backend (auto-création de chauffeurs et mappages)
    ├─ Créer compte chauffeur si absent
    ├─ Créer mapping chauffeur ↔ camion
    ├─ Créer programmes/livraisonsassignés au chauffeur
    ↓
App Mobile Chauffeur
    ├─ Se connecter: email + password
    ├─ Voir programmes du jour
    ├─ Effectuer livraisons
    ├─ Compléter et synchroniser
    ↓
Backend (validation)
    ├─ Valider toutes les livraisons
    ├─ Marquer programme comme complété
    ├─ Appeler Sage SQL pour mettre à jour YFLGVAL2_0=2
    ↓
Sage X3 SQL
    └─ YFLGVAL2_0 = 2 (programme validé)
```

---

## 🚀 Mise en place initiale

### 1️⃣ Lancer la synchronisation des chauffeurs depuis Sage

#### Option A: Via l'API Admin (recommandé)

```bash
curl -X GET https://sodigazback.yingr-ai.com/api/admin/sync-sage-drivers \
  -H "Authorization: Bearer <TOKEN_ADMIN>" \
  -H "Content-Type: application/json"
```

Réponse:
```json
{
  "success": true,
  "message": "Synchronisation réussie: 3 créés, 1 réactivé, 2 existants",
  "sage_codes_found": 6,
  "drivers_created": 3,
  "drivers_reactivated": 1,
  "drivers_existing": 2,
  "drivers": [
    {
      "sage_code": "DRV001",
      "user_id": 5,
      "email": "drv001@sodigaz-app.local",
      "password": "CodeDRV001@2026",
      "status": "created",
      "message": "Chauffeur créé (ID: 5)"
    }
  ]
}
```

#### Option B: Via le script Python

```bash
python bulk_create_drivers_from_sage.py
```

Output:
```
INFO: === Lecture des codes YLIV uniques depuis Sage ===
INFO: Trouvé 6 codes chauffeurs uniques
INFO: === Création/vérification des chauffeurs ===
INFO: ✅ Chauffeur créé: drv001@sodigaz-app.local / CodeDRV001@2026
INFO: ✓ Chauffeur DRV002 existe déjà (ID: 2)
...
INFO: === RÉSUMÉ ===
INFO: ✅ 3 chauffeurs créés/réactivés
INFO: ✓ 3 chauffeurs existaient déjà
INFO: 📊 Total: 6 chauffeurs
```

### 2️⃣ Synchroniser les mappages chauffeur/camion

```bash
curl -X POST https://sodigazback.yingr-ai.com/api/admin/sync-sage-mappings \
  -H "Authorization: Bearer <TOKEN_ADMIN>" \
  -H "Content-Type: application/json"
```

Réponse:
```json
{
  "success": true,
  "message": "Synchronisation des mappages: 4 créés, 2 activés",
  "mappings_created": 4,
  "mappings_activated": 2,
  "suggestions": [
    {
      "sage_driver_code": "DRV001",
      "truck_code": "VH-001",
      "user_id": 5,
      "user_email": "drv001@sodigaz-app.local",
      "auto_created": true
    }
  ]
}
```

---

## 👤 Gestion des chauffeurs

### Via le script helper

```bash
# Créer un chauffeur pour un code Sage
python driver_mapping_helper.py create-driver DRV001 "Mohammed Ali"

# Lister tous les chauffeurs
python driver_mapping_helper.py list-drivers

# Lister tous les mappages
python driver_mapping_helper.py list-mappings

# Synchroniser complètement depuis Sage
python driver_mapping_helper.py sync-from-sage

# Créer un mapping spécifique
python driver_mapping_helper.py create-mapping DRV001 "VH-001"
```

### Via l'API Admin

#### Créer/mettre à jour un chauffeur

```bash
POST /api/admin/users
{
  "email": "drv001@sodigaz-app.local",
  "username": "drv001",
  "password": "CodeDRV001@2026",
  "full_name": "Chauffeur DRV001",
  "role": "ravitailleur",
  "is_active": true
}
```

---

## 🔗 Mappages chauffeur/camion

### Création automatique

Lors de la synchronisation des programmes Sage, le système **crée automatiquement**:

1. ✅ Chauffeur (s'il n'existe pas)
2. ✅ Camion (s'il n'existe pas)
3. ✅ Mapping chauffeur ↔ camion

### Création manuelle

Via l'API Admin:

```bash
POST /api/admin/driver-mappings
{
  "sage_driver_code": "DRV001",
  "truck_code": "VH-001",
  "user_id": 5,
  "status": "active"
}
```

### Consulter les mappages

```bash
GET /api/admin/driver-mappings

[
  {
    "id": 1,
    "user_id": 5,
    "sage_driver_code": "DRV001",
    "truck_code": "VH-001",
    "status": "active",
    "is_active": true,
    "auto_created": true,
    "source_program_code": "PROG001",
    "created_at": "2026-05-18T10:30:00Z"
  }
]
```

---

## 📱 Flux chauffeur mobile

### Étape 1: Connexion

**Endpoint:**
```
POST /api/driver/login
{
  "email": "drv001@sodigaz-app.local",
  "password": "CodeDRV001@2026"
}
```

**Réponse:**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": 5,
    "email": "drv001@sodigaz-app.local",
    "full_name": "Chauffeur DRV001",
    "role": "ravitailleur"
  }
}
```

### Étape 2: Récupérer les programmes du jour

**Endpoint:**
```
GET /api/driver/programs/today
Authorization: Bearer <TOKEN>
```

**Réponse:**
```json
{
  "programs": [
    {
      "id": 1,
      "program_code": "PROG001",
      "program_type": "DELIVERY",
      "program_date": "2026-05-18",
      "truck": {
        "id": 3,
        "license_plate": "VH-001"
      },
      "driver": {
        "id": 5,
        "email": "drv001@sodigaz-app.local"
      },
      "lines": [
        {
          "id": 10,
          "line_code": "L001",
          "client_name": "Client A",
          "client_code": "CLI001",
          "destination_address": "Rue du Marché, 123",
          "destination_latitude": -4.2850,
          "destination_longitude": 15.3125,
          "quantity_planned": 5,
          "product_code": "BOT6KG",
          "status": "pending"
        }
      ]
    }
  ]
}
```

### Étape 3: Démarrer une livraison

**Endpoint:**
```
POST /api/driver/start-delivery/{delivery_id}
Authorization: Bearer <TOKEN>
{
  "latitude": -4.2850,
  "longitude": 15.3125
}
```

### Étape 4: Compléter une livraison

**Endpoint:**
```
POST /api/driver/complete-delivery/{delivery_id}
Authorization: Bearer <TOKEN>
{
  "latitude": -4.2850,
  "longitude": 15.3125
}
```

**Ce qui se passe automatiquement:**
1. ✅ Livraison marquée COMPLETED
2. ✅ Si TOUS les items du programme sont complétés:
   - Programme marqué COMPLETED
   - **Sage SQL mis à jour:** YFLGVAL2_0 = 2 pour le programme PROG001
   - Réponse Sage confirmée

### Étape 5: Synchroniser (mode offline)

**Endpoint:**
```
POST /api/driver/sync/batch
Authorization: Bearer <TOKEN>
{
  "device_id": "device_uuid",
  "batch_id": "batch_uuid",
  "operations": [
    {
      "operation_type": "delivery_completed",
      "delivery_id": 1,
      "payload": { ... }
    }
  ]
}
```

---

## ✅ Validation Sage

### Flux de validation automatique

Quand le chauffeur complète **TOUS** les items d'un programme:

```python
# 1. Le backend détecte que toutes les livraisons sont complètes
if all_deliveries_complete(program):
    # 2. Appel à valider_programme_sage()
    status = valider_programme_sage(program.program_code)
    
    # 3. Sage SQL reçoit:
    # UPDATE YPRGCOLL SET YFLGVAL2_0 = 2 WHERE YPROGCOLL_0 = 'PROG001'
    
    # 4. Programme marqué comme synced
    program.status = "completed"
    program.source_payload["sage_validation"] = {
        "status": "OK",
        "validated_at": "2026-05-18T14:30:00Z"
    }
```

### Vérifier le statut de validation

```bash
GET /api/admin/sage-missions?external_status=synced
```

Réponse:
```json
{
  "deliveries": [
    {
      "id": 1,
      "external_delivery_id": "PROG001:L001",
      "external_status": "synced",
      "external_sync_at": "2026-05-18T14:30:00Z",
      "program": {
        "program_code": "PROG001",
        "status": "completed",
        "source_payload": {
          "sage_validation": {
            "status": "OK",
            "validated_at": "2026-05-18T14:30:00Z"
          }
        }
      }
    }
  ]
}
```

---

## 🔐 Sécurité des credentials

### Format des passwords auto-générés

- **Format:** `Code{SAGE_CODE_EN_MAJUSCULES}@2026`
- **Exemple pour DRV001:** `CodeDRV001@2026`
- **Recommandation:** Après la première connexion, le chauffeur doit changer son password

### Réinitialisation de password

Admin change le password du chauffeur:

```bash
PUT /api/admin/users/{user_id}
Authorization: Bearer <TOKEN_ADMIN>
{
  "password": "NewPassword@2026"
}
```

---

## 🐛 Troubleshooting

### Problème: Chauffeur non trouvé lors de la synchronisation

```
Message: "Aucun mapping actif et le code YLIV n'est pas resolu de facon unique"
```

**Solutions:**
1. Vérifier que le code YLIV existe dans Sage SQL
2. Lancer `/api/admin/sync-sage-drivers` pour créer les chauffeurs
3. Lancer `/api/admin/sync-sage-mappings` pour créer les mappages

### Problème: Camion non trouvé

```
Message: "Le camion YMATCAM n'existe pas dans le referentiel local"
```

**Solutions:**
1. Créer le camion via l'API:
```bash
POST /api/admin/trucks
{
  "license_plate": "VH-001",
  "capacity_6kg": 100,
  "capacity_12kg": 50
}
```
2. Lancer la synchronisation `/api/admin/sync-sage-mappings` (crée auto les camions)

### Problème: Validation Sage échoue

```
Message: "ERROR" dans program.source_payload.sage_validation.status
```

**Vérifications:**
1. Vérifier que la connexion Sage SQL est opérationnelle: `/api/admin/integration/sage-sql-health`
2. Vérifier que le programme existe dans YPRGCOLL
3. Vérifier que le programme n'est pas déjà validé (YFLGVAL2_0 ≠ 1)
4. Vérifier les logs du backend

---

## 📊 Schéma de la base de données

### Users (chauffeurs)
```sql
SELECT * FROM users
WHERE role = 'ravitailleur'
AND is_active = true
ORDER BY email;
```

### Trucks (camions)
```sql
SELECT * FROM trucks
WHERE is_active = true
ORDER BY license_plate;
```

### DriverMappings (mappages)
```sql
SELECT 
    dm.sage_driver_code,
    dm.truck_code,
    u.email,
    dm.status,
    dm.auto_created,
    dm.created_at
FROM driver_mappings dm
JOIN users u ON dm.user_id = u.id
WHERE dm.is_active = true
ORDER BY dm.sage_driver_code, dm.truck_code;
```

### Programs (programmes Sage)
```sql
SELECT 
    p.program_code,
    p.program_type,
    p.status,
    u.email as driver_email,
    t.license_plate,
    COUNT(d.id) as deliveries_count,
    SUM(CASE WHEN d.status = 'completed' THEN 1 ELSE 0 END) as deliveries_completed
FROM programs p
LEFT JOIN users u ON p.driver_id = u.id
LEFT JOIN trucks t ON p.truck_id = t.id
LEFT JOIN deliveries d ON p.id = d.program_id
WHERE CAST(p.program_date AS DATE) = CAST(GETDATE() AS DATE)
GROUP BY p.id
ORDER BY p.program_code;
```

---

## 🔄 Processus de synchronisation

### Auto-synchronisation (Cron task)

Le système synchronise automatiquement les programmes Sage toutes les heures:

```python
# app/services/sage_sync_scheduler.py
SYNC_INTERVAL = 3600  # 1 heure
SYNC_HOUR_START = 6   # À partir de 6h du matin
SYNC_HOUR_END = 22    # Jusqu'à 22h
```

### Synchronisation manuelle

```bash
POST /api/integration/sage/programs/sync
Authorization: Bearer <TOKEN_ADMIN>
{
  "force_full_sync": false
}
```

---

## 📝 Checklist d'intégration

- [ ] **Sage SQL** configuré avec les variables d'env (SAGE_SQL_SERVER, USER, PASSWORD, etc.)
- [ ] **Chauffeurs créés** via `/api/admin/sync-sage-drivers`
- [ ] **Mappages configurés** via `/api/admin/sync-sage-mappings`
- [ ] **Camions existants** ou créés automatiquement
- [ ] **Programmes Sage** lus et stockés localement
- [ ] **App mobile** peut se connecter avec les credentials auto-générés
- [ ] **Livraisons complètes** trigger la validation Sage (YFLGVAL2_0 = 2)
- [ ] **Logs vérifiés** pour aucune erreur de synchronisation

---

## 🎯 Cas d'usage courants

### Cas 1: Nouveau chauffeur Sage détecté

**Flux automatique:**
1. Programmes Sage lus avec code YLIV = "DRV_NEW"
2. Système recherche mapping → pas trouvé
3. Système crée chauffeur "drv_new@sodigaz-app.local" avec password "CodeDRV_NEW@2026"
4. Système crée mapping DRV_NEW ↔ VH-001
5. Programme assigné au chauffeur
6. Chauffeur reçoit notification (si configuré)

### Cas 2: Camion partagé par plusieurs chauffeurs

**Scénario:**
- Camion VH-001 peut être utilisé par DRV001 ou DRV002 selon le jour
- Mappages: (DRV001, VH-001) et (DRV002, VH-001) tous actifs
- Chaque jour, les programmes Sage décident qui l'utilise

**Résolution:**
- Programme PROG001 avec YLIV=DRV001 → assigné à DRV001
- Programme PROG002 avec YLIV=DRV002 → assigné à DRV002

### Cas 3: Reactivation d'un ancien chauffeur

**Scénario:**
- Chauffeur DRV001 était inactif (is_active=false)
- Nouveau programme Sage le réaffecte
- Système détecte et réactive automatiquement

**Code:**
```python
if mapping.status == DriverMappingStatusEnum.INACTIVE:
    mapping.is_active = True
    mapping.status = DriverMappingStatusEnum.ACTIVE
    # "Mapping réactivé automatiquement par le programme Sage"
```

---

## 📞 Support

Pour des problèmes:
1. Vérifier les logs: `tail -f backend/logs/app.log`
2. Tester la connexion Sage: `GET /api/admin/integration/sage-sql-health`
3. Consulter les conflits: `GET /api/driver/sync/conflicts`
4. Vérifier les events Sage: `GET /api/admin/integration/outbox`

# 🧪 Guide Complet - Test Sage X3 en MODE MOCK

## PRÉREQUIS

Avant de tester, assurez-vous que:

- ✅ Backend FastAPI est en cours d'exécution
- ✅ Base de données créée et initialisée
- ✅ Admin utilisateur existe (username: `admin`, password: `password123`)
- ✅ Driver utilisateur existe (username: `driver1`, password: `password123`)
- ✅ Un dépôt (depot_id: 1) existe
- ✅ Un camion (truck_id: 1) existe et assigné à un driver

---

## 📋 DÉMARRER LE BACKEND

```bash
# Aller dans le dossier backend
cd gas-platform/backend

# Démarrer le serveur
python -m uvicorn app.main:app --reload --port 8000
```

Vous devriez voir:
```
Uvicorn running on http://127.0.0.1:8000
```

---

## 🧪 TEST 1: Avec Python (Recommandé - Plus de contrôle)

### Installer les dépendances Python

```bash
cd backend
pip install requests python-dotenv
```

### Lancer le test complet

```bash
python test_sage_workflow.py
```

**Cela va:**
1. ✅ Se connecter comme admin et driver
2. ✅ Simuler l'envoi d'une mission par Sage X3
3. ✅ Afficher la mission en attente
4. ✅ Admin approuve et assigne un camion
5. ✅ Driver télécharge la mission
6. ✅ Vérifier l'état de l'intégration Sage
7. ✅ Afficher le contenu de l'IntegrationOutbox
8. ✅ Vérifier le dashboard

**Résultat attendu:**
```
═══════════════════════════════════════════════════════════════
  TEST COMPLET SAGE X3 - MODE MOCK
═══════════════════════════════════════════════════════════════

✅ Admin connecté: ...
✅ Driver connecté: ...
✅ Mission reçue et enregistrée: delivery_id=123
✅ Missions en attente d'approbation: 1
✅ Mission approuvée: ...
✅ Missions téléchargées: 1
✅ Mode: mock
✅ Status: healthy
...
═══════════════════════════════════════════════════════════════
  ✅ TEST COMPLET TERMINÉ
═══════════════════════════════════════════════════════════════
```

---

## 🧪 TEST 2: Avec cURL (Alternatif - Pas de dépendances)

### Sur Linux/Mac:

```bash
cd backend
bash test_sage.sh
```

### Sur Windows (avec PowerShell):

```powershell
# Créez un fichier test_sage.ps1 avec le contenu ci-dessous
# Puis lancez:
powershell -ExecutionPolicy Bypass -File test_sage.ps1
```

---

## 🧪 TEST 3: Manuel avec cURL (Étape par étape)

### 1️⃣ Login Admin

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password123"}'
```

**Réponse:**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": {...}
}
```

**Copier le token pour la suite (remplacer `YOUR_ADMIN_TOKEN`)**

### 2️⃣ Sage envoie une mission

```bash
curl -X POST http://localhost:8000/api/logistics/v1/sage-missions/inbound \
  -H "Content-Type: application/json" \
  -H "X-Sage-X3-Token: test-token-123" \
  -d '{
    "external_delivery_id": "SAGE-MOCK-001",
    "destination_name": "Boutique Ouaga",
    "destination_address": "123 Avenue Paix",
    "destination_latitude": 12.3656,
    "destination_longitude": -1.5197,
    "contact_name": "Mr. Koné",
    "contact_phone": "+226 70123456",
    "depot_id": 1,
    "quantity_6kg": 50,
    "quantity_12kg": 30,
    "scheduled_date": "2025-03-22T08:00:00Z",
    "notes": "Livraison test"
  }'
```

**Réponse:**
```json
{
  "success": true,
  "message": "Mission SAGE-MOCK-001 reçue avec succès",
  "delivery_id": 123,
  "external_delivery_id": "SAGE-MOCK-001",
  "status": "pending_approval"
}
```

**Copier `delivery_id: 123` pour la suite**

### 3️⃣ Admin voit les missions en attente

```bash
curl -X GET "http://localhost:8000/api/admin/sage-missions?status=pending_approval" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json"
```

**Réponse:**
```json
[
  {
    "id": 123,
    "external_delivery_id": "SAGE-MOCK-001",
    "destination_name": "Boutique Ouaga",
    "external_status": "pending_approval",
    ...
  }
]
```

### 4️⃣ Admin approuve la mission

```bash
curl -X POST http://localhost:8000/api/admin/sage-missions/123/approve \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"truck_id": 1}'
```

**Réponse:**
```json
{
  "success": true,
  "message": "Mission 123 approuvée avec succès",
  "mission_id": 123,
  "delivery_id": 123
}
```

### 5️⃣ Login Driver

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"driver1","password":"password123"}'
```

**Copier le token pour `YOUR_DRIVER_TOKEN`**

### 6️⃣ Driver télécharge les missions

```bash
curl -X GET http://localhost:8000/api/admin/sage-missions/mobile/download \
  -H "Authorization: Bearer YOUR_DRIVER_TOKEN" \
  -H "Content-Type: application/json"
```

**Réponse:**
```json
{
  "success": true,
  "count": 1,
  "missions": [
    {
      "id": 123,
      "external_delivery_id": "SAGE-MOCK-001",
      "destination_name": "Boutique Ouaga",
      "quantity_6kg": 50,
      "quantity_12kg": 30,
      ...
    }
  ]
}
```

### 7️⃣ Vérifier l'état Sage X3

```bash
curl -X POST http://localhost:8000/api/admin/integration-outbox/health/check \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Réponse:**
```json
{
  "status": "healthy",
  "mode": "mock",
  "detail": "Mock mode enabled",
  "outbox": {
    "pending": 0,
    "sent": 0,
    "failed_dead_letter": 0
  },
  ...
}
```

### 8️⃣ Voir l'IntegrationOutbox

```bash
curl "http://localhost:8000/api/admin/integration-outbox?status=all" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json"
```

---

## ✅ VÉRIFICATIONS

Pour confirmer que tout fonctionne:

### Dashboard Widget Sage X3
1. Ouvrir le Dashboard Admin: http://localhost:5173/dashboard
2. Chercher le widget "Sage X3 - Cahier de Charge"
3. Vérifier:
   - ✅ Missions en attente (compteur)
   - ✅ État connexion (Online/Offline)
   - ✅ Statistiques outbox

### Page Cahier de Charge
1. Cliquer sur "Cahier de Charge Sage" dans la barre latérale
2. Vérifier:
   - ✅ Mission affichée avec statut "En attente d'approbation"
   - ✅ Boutons "Approuver" et "Rejeter" disponibles
   - ✅ Modal pour sélectionner le camion

### Base de données
```bash
# Vérifier les Deliveries créées avec source_type='sage_inbound'
sqlite3 dev.db

sqlite> SELECT id, external_delivery_id, destination_name, external_status, source_type 
        FROM deliveries 
        WHERE source_type = 'sage_inbound';

# Résultat attendu:
# 123|SAGE-MOCK-001|Boutique Ouaga|approved|sage_inbound
```

---

## 🔍 DÉPANNAGE

### Erreur: "Mission introuvable"
```bash
# Vérifier que delivery_id est correct
# Relancer le test avec le bon delivery_id
```

### Erreur: "Token invalide"
```bash
# Le token a expiré après 24h
# Reconnectez-vous avec /api/auth/login
```

### Erreur: "Mode endpoint introuvable"
```bash
# Vérifier que SAGE_X3_PUSH_MODE=mock dans .env
# Redémarrer le backend
```

### Missions n'apparaissent pas au mobile
```bash
# Vérifier:
# 1. Mission est approuvée (external_status = 'approved')
# 2. Driver_id du token correspond au driver assigné
# 3. Endpoint: GET /api/admin/sage-missions/mobile/download
```

---

## 📊 PROCHAINE ÉTAPE: TRANSITION VERS PRODUCTION

Une fois que les tests MOCK passent, pour passer en production Sage:

1. **Obtenir credentials Sage X3 réels** auprès de votre équipe Sage
2. **Mettre à jour .env:**
   ```bash
   SAGE_X3_PUSH_MODE=http
   SAGE_X3_BASE_URL=https://sage-prod.yourcompany.com/api
   SAGE_X3_API_KEY=real-api-key-here
   ```
3. **Configurer authentification** (Bearer token, API Key, etc.)
4. **Tester avec webhook Sage** (au lieu de POST manuel)
5. **Activer retry policy** et monitoring dead-letter queue

---

**Besoin d'aide?** Faites tourner le test et partagez les erreurs! 🚀

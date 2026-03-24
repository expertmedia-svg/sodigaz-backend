# ✅ CHECKLIST PRÉ-TEST SAGE X3

Vérifiez que tous les éléments sont en place avant de lancer les tests.

---

## 🔧 **ÉTAPE 1: Configuration & Environnement**

- [ ] Fichier `.env` existe et contient:
  ```bash
  SAGE_X3_PUSH_MODE=mock
  SAGE_X3_INBOUND_TOKEN=test-token-123
  ```

- [ ] Python 3.8+ installé:
  ```bash
  python --version
  ```
  
- [ ] Dépendances Python installées:
  ```bash
  pip install fastapi uvicorn sqlalchemy requests python-dotenv
  ```

---

## 📦 **ÉTAPE 2: Fichiers Créés**

- [ ] ✅ Services Sage X3 créés:
  - [ ] `app/services/sage_x3_service.py`
  - [ ] `app/services/integration_outbox_service.py`

- [ ] ✅ Tests créés:
  - [ ] `test_sage_workflow.py`
  - [ ] `test_sage.sh` (Linux/Mac)
  - [ ] `test_sage.ps1` (Windows)

- [ ] ✅ Documentation créée:
  - [ ] `QUICK_SAGE_TEST.md`
  - [ ] `SAGE_X3_TEST_GUIDE.md`
  - [ ] `SAGE_X3_IMPLEMENTATION_README.md`
  - [ ] `INDEX.md`

---

## 🗄️ **ÉTAPE 3: Base de Données**

- [ ] Base de données `dev.db` existe

- [ ] Tables créées avec:
  ```bash
  python seed_db.py
  ```

- [ ] Données de seed créées:
  ```bash
  python seed_frontend_users.py
  ```

- [ ] Vérifier les données:
  ```bash
  sqlite3 dev.db
  sqlite> SELECT username, role FROM users WHERE username IN ('admin', 'driver1');
  # Doit retourner:
  # admin|admin
  # driver1|driver
  ```

---

## 🚚 **ÉTAPE 4: Données d'Exemple**

Créer les entités nécessaires (si pas déjà présentes):

```bash
python -c "
from app.database import SessionLocal
from app.models import Depot, Truck, User
db = SessionLocal()

# Vérifier Dépôt 1
depot = db.query(Depot).filter(Depot.id == 1).first()
if not depot:
    depot = Depot(id=1, name='Ouaga Central', is_active=True)
    db.add(depot)
    print('✅ Dépôt créé')
else:
    print('✅ Dépôt 1 existe')

# Vérifier Camion 1
truck = db.query(Truck).filter(Truck.id == 1).first()
driver = db.query(User).filter(User.username == 'driver1').first()
if not truck:
    truck = Truck(id=1, model='Iveco', plate='ABC123', depot_id=1, driver_id=driver.id if driver else None)
    db.add(truck)
    print('✅ Camion créé')
else:
    print('✅ Camion 1 existe')
    if not truck.driver_id and driver:
        truck.driver_id = driver.id
        print('✅ Driver assigné au camion')

db.commit()
db.close()
"
```

---

## 🔐 **ÉTAPE 5: Utilisateurs de Test**

Vérifier que les utilisateurs existent:

```bash
sqlite3 dev.db "SELECT username, role FROM users WHERE username IN ('admin', 'driver1');"
```

**Résultat attendu:**
```
admin|admin
driver1|driver
```

Si pas d'utilisateurs, créer avec:
```bash
python seed_frontend_users.py
```

---

## 🌐 **ÉTAPE 6: Backend Fonctionnel**

- [ ] FastAPI peut démarrer:
  ```bash
  python -m uvicorn app.main:app --reload --port 8000
  ```

- [ ] Accessible sur http://localhost:8000/docs
  - [ ] Voir la liste de tous les endpoints
  - [ ] Voir `/api/logistics/v1/sage-missions/inbound`
  - [ ] Voir `/api/admin/sage-missions/{mission_id}/approve`

- [ ] Health check:
  ```bash
  curl http://localhost:8000/health
  ```
  **Résultat:** `{"status":"ok","service":"..."}`

---

## 🧪 **ÉTAPE 7: Dépendances du Test**

- [ ] `requests` installé:
  ```bash
  pip install requests
  ```

- [ ] `python-dotenv` installé:
  ```bash
  pip install python-dotenv
  ```

- [ ] Test Python accessible:
  ```bash
  python test_sage_workflow.py --help
  ```

---

## 📊 **ÉTAPE 8: Vérifications Finales**

Avant de lancer le test complet:

- [ ] Backend démarre sans erreurs
  ```bash
  python -m uvicorn app.main:app --reload --port 8000
  # Attendre 3-5 secondes
  # Voir "Uvicorn running on http://127.0.0.1:8000"
  ```

- [ ] Endpoints Sage sont présents:
  ```bash
  curl -s http://localhost:8000/openapi.json | grep -i sage
  # Doit voir endpoints Sage
  ```

- [ ] Admin peut se connecter:
  ```bash
  curl -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"password123"}'
  # Résultat: token JWT
  ```

- [ ] Driver peut se connecter:
  ```bash
  curl -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"driver1","password":"password123"}'
  # Résultat: token JWT
  ```

---

## 🎯 **PRÊT À TESTER?**

Si **TOUTES les cases** sont cochées ✅:

1. **Ouvrez 2 terminaux PowerShell**

2. **Terminal 1** - Démarrer le backend:
   ```powershell
   cd c:\Users\BNT\Documents\PROJET SODIGAZ\gas-platform\backend
   python -m uvicorn app.main:app --reload --port 8000
   ```

3. **Terminal 2** - Lancer le test:
   ```powershell
   cd c:\Users\BNT\Documents\PROJET SODIGAZ\gas-platform\backend
   python test_sage_workflow.py
   ```

4. **Vérifier le résultat** - Vous devriez voir:
   ```
   ═══════════════════════════════════════════════════════════════
     TEST COMPLET SAGE X3 - MODE MOCK
   ═══════════════════════════════════════════════════════════════
   
   ✅ Admin connecté...
   ✅ Driver connecté...
   ✅ Mission reçue: SAGE-MOCK-001
   ✅ Missions en attente: 1
   ✅ Mission approuvée...
   ✅ Driver télécharge missions...
   
   ═══════════════════════════════════════════════════════════════
   ✅ TEST COMPLET TERMINÉ AVEC SUCCÈS!
   ═══════════════════════════════════════════════════════════════
   ```

---

## ❌ SI PROBLÈME

| Problème | Solution |
|---------|----------|
| ❌ Module `requests` introuvable | `pip install requests` |
| ❌ "Connection refused" sur port 8000 | Backend pas lancé - Étape Terminal 1 |
| ❌ "Depot introuvable (depot_id=1)" | Créer dépôt: `python seed_db.py` |
| ❌ "Admin not found" | Créer users: `python seed_frontend_users.py` |
| ❌ "Truck not found" | Créer camion (script Étape 4) |
| ❌ Token JWT invalide | Reconnecter avec `/api/auth/login` |
| ❌ "source_type" colonne manquante | Mise à jour DB réquise - `DROP all tables && seed_db.py` |

---

## 📚 **RESSOURCES**

- [QUICK_SAGE_TEST.md](QUICK_SAGE_TEST.md) - Quick start 2 min
- [SAGE_X3_TEST_GUIDE.md](SAGE_X3_TEST_GUIDE.md) - Guide détaillé
- [INDEX.md](INDEX.md) - Vue globale du projet
- [SAGE_X3_IMPLEMENTATION_README.md](SAGE_X3_IMPLEMENTATION_README.md) - Architecture

---

**✨ Tous les points vérifiés? Allez-y! 🚀**

Lancez le test avec: `python test_sage_workflow.py`

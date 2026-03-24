# ⚡ QUICK START - Test Sage X3 en 2 minutes

## **EN 2 SECONDES** (Copier-coller direct)

### 1️⃣ Dans PowerShell - Démarrer le backend:
```powershell
cd "C:\Users\BNT\Documents\PROJET SODIGAZ\gas-platform\backend"
python -m uvicorn app.main:app --reload --port 8000
```

### 2️⃣ Dans un NOUVEAU PowerShell - Lancer le test:
```powershell
cd "C:\Users\BNT\Documents\PROJET SODIGAZ\gas-platform\backend"
python test_sage_workflow.py
```

---

## ✅ RÉSULTAT ATTENDU (< 5 secondes)

```
═══════════════════════════════════════════════════════════════
  TEST COMPLET SAGE X3 - MODE MOCK
═══════════════════════════════════════════════════════════════

✅ Admin connecté avec token: eyJhbGc...
✅ Driver connecté avec token: eyJhbGc...

🔄 ÉTAPE 1: Sage envoie une mission
✅ Mission reçue: SAGE-MOCK-001 (delivery_id=123)

🔄 ÉTAPE 2: Admin approuve la mission
✅ Missions en attente: 1
✅ Mission approuvée et camion assigné

🔄 ÉTAPE 3: Driver télécharge les missions
✅ Missions téléchargées: 1

🔄 ÉTAPE 4: Vérifier l'intégration Sage
✅ Mode: mock
✅ Status: healthy
✅ Outbox - Pending: 0, Sent: 0, Failed: 0

🔄 ÉTAPE 5: Dashboard Sage
✅ Sage X3 Status Widget: Online
✅ Missions en attente: 1
✅ Outbox status: 0 pending

═══════════════════════════════════════════════════════════════
✅ TEST COMPLET TERMINÉ AVEC SUCCÈS!
═══════════════════════════════════════════════════════════════
```

---

## 📝 NOTES IMPORTANTES

| ⚠️ | Spécification |
|----|---|
| 🔐 | Admin: `admin` / `password123` |
| 🔐 | Driver: `driver1` / `password123` |
| 🗄️ | Base de données: `dev.db` |
| 🌐 | Backend URL: `http://localhost:8000` |
| ⏱️ | Durée test: ~5-10 secondes |
| 📡 | Mode: `mock` (aucun appel Sage réel) |

---

## 🚨 SI ERREUR

### ❌ "Connection refused on 8000"
→ Le backend n'est pas lancé. Faire Ctrl+C et recommencer étape 1

### ❌ "Admin not found"
→ Seed database non exécuté:
```bash
python seed_frontend_users.py
```

### ❌ "Module not found: requests"
→ Installer dépendances:
```bash
pip install requests python-dotenv
```

### ❌ Autre erreur?
→ Lancer avec plus de détails:
```bash
python test_sage_workflow.py -v
```

---

## 🎯 PROCHAINES ÉTAPES

1. ✅ **Passer les tests MOCK** (vous êtes là!)
2. ⏭️ **Configurer Sage X3 réel** (credentials, webhooks)
3. ⏭️ **Tester intégration production** (endpoints réels)
4. ⏭️ **Monitorer outbox** (vérifier envois à Sage)
5. ⏭️ **Metrics & alertes** (déploiement complet)

---

**Prêt? Lancez le test maintenant! 🚀**

# 🔐 Gestion Sécurisée des Credentials

**⚠️ CONFIDENTIEL - Traiter avec prudence**

---

## 📋 Résumé

| Item | Status | Details |
|------|--------|---------|
| `.env` | ✅ Ignoré | Dans `.gitignore` (ligne 4) |
| `.env.example` | ✅ Public | Template SANS secrets |
| `.env.production` | ⚠️ Template | Template pour prod SANS secrets |
| Sage SQL credentials | 🔒 SECRETS | À configurer via env vars uniquement |

---

## 🔒 Credentials Sage SQL

### ⚠️ JAMAIS à commiter!

```bash
SAGE_SQL_SERVER=35.203.21.23,50389
SAGE_SQL_DATABASE=x3v12
SAGE_SQL_SCHEMA=SODIGAZG
SAGE_SQL_USER=sodigazg_app
SAGE_SQL_PASSWORD=S0digaz@Sage2026!
SAGE_SQL_DRIVER=ODBC Driver 17 for SQL Server
```

### Configuration recommandée

#### En local (développement)
```bash
# 1. Créer ou éditer .env
cat > .env << 'EOF'
SAGE_SQL_SERVER=35.203.21.23,50389
SAGE_SQL_DATABASE=x3v12
SAGE_SQL_SCHEMA=SODIGAZG
SAGE_SQL_USER=sodigazg_app
SAGE_SQL_PASSWORD=S0digaz@Sage2026!
SAGE_SQL_DRIVER=ODBC Driver 17 for SQL Server
EOF

# 2. Vérifier que .env est dans .gitignore
grep "^\.env$" .gitignore  # Doit afficher ".env"

# 3. JAMAIS faire git add .env
# JAMAIS faire git commit
```

#### En production (SERVEUR/KUBERNETES)
```bash
# ❌ NE PAS utiliser .env en production!
# ✅ Utiliser les secrets du serveur:

# Option 1: Variables d'environnement système
export SAGE_SQL_SERVER=35.203.21.23,50389
export SAGE_SQL_DATABASE=x3v12
export SAGE_SQL_SCHEMA=SODIGAZG
export SAGE_SQL_USER=sodigazg_app
export SAGE_SQL_PASSWORD=S0digaz@Sage2026!

# Option 2: Fichier secrets (avec permissions 600)
# /etc/sodigaz/sage-sql-secrets.env (permissions: 600)
source /etc/sodigaz/sage-sql-secrets.env

# Option 3: Kubernetes Secrets
kubectl create secret generic sage-sql-creds \
  --from-literal=SAGE_SQL_SERVER=35.203.21.23,50389 \
  --from-literal=SAGE_SQL_DATABASE=x3v12 \
  --from-literal=SAGE_SQL_SCHEMA=SODIGAZG \
  --from-literal=SAGE_SQL_USER=sodigazg_app \
  --from-literal=SAGE_SQL_PASSWORD=S0digaz@Sage2026!

# Option 4: HashiCorp Vault
vault write secret/sodigaz/sage-sql \
  server=35.203.21.23,50389 \
  database=x3v12 \
  schema=SODIGAZG \
  user=sodigazg_app \
  password=S0digaz@Sage2026!
```

---

## ✅ Checklist de sécurité

### Avant de commiter

```bash
# Vérifier que .env n'est pas staged
git status | grep ".env"  # Ne doit rien afficher

# Vérifier que .env est ignoré
git check-ignore .env  # Doit afficher ".env"

# Vérifier aucun secret dans git history
git log -p | grep "SAGE_SQL_PASSWORD"  # Ne doit rien afficher
git log -p | grep "sodigazg_app"       # Ne doit rien afficher
```

### Avant de déployer

```bash
# Vérifier les permissions du fichier secrets
ls -la /etc/sodigaz/sage-sql-secrets.env  # Doit être 600

# Vérifier les variables d'env
echo "Server: $SAGE_SQL_SERVER"
echo "User: $SAGE_SQL_USER"
echo "Password: ****"  # Afficher juste qu'il est défini

# Tester la connexion
python -c "from app.services.sage_sql_service import get_sage_sql_connection; c = get_sage_sql_connection(); print('✅ Connection OK')"
```

---

## 📁 Structure des fichiers

```
backend/
├── .env                    ← ❌ JAMAIS commiter (ignoré par .gitignore)
├── .env.example            ← ✅ Public (template SANS secrets)
├── .env.production         ← ⚠️ Template pour prod (SANS secrets)
├── .gitignore              ← ✅ Contient ".env"
├── app/
│   └── config.py           ← ✅ Lit les vars d'env (via os.getenv)
└── ...
```

---

## 🔍 Code de lecture des secrets

### En `app/config.py`

```python
# Ligne 48-54: Sage SQL vars lues depuis os.environ
SAGE_SQL_SERVER = os.getenv("SAGE_SQL_SERVER", "")
SAGE_SQL_DATABASE = os.getenv("SAGE_SQL_DATABASE", "")
SAGE_SQL_SCHEMA = os.getenv("SAGE_SQL_SCHEMA", "")
SAGE_SQL_USER = os.getenv("SAGE_SQL_USER", "")
SAGE_SQL_PASSWORD = os.getenv("SAGE_SQL_PASSWORD", "")
SAGE_SQL_DRIVER = os.getenv("SAGE_SQL_DRIVER", "ODBC Driver 17 for SQL Server")
```

**→ Les secrets sont TOUJOURS lus depuis l'environnement, jamais hardcodés**

### En `app/services/sage_sql_service.py`

```python
# Ligne 31-38: Construire la connection string à partir des settings
def get_sage_sql_connection():
    conn_str = (
        f"DRIVER={{{settings.SAGE_SQL_DRIVER}}};"
        f"SERVER={settings.SAGE_SQL_SERVER};"
        f"DATABASE={settings.SAGE_SQL_DATABASE};"
        f"UID={settings.SAGE_SQL_USER};"
        f"PWD={settings.SAGE_SQL_PASSWORD};"
    )
    return pyodbc.connect(conn_str)
```

**→ Les credentials ne sont JAMAIS loggés ou affichés**

---

## 🚨 Qu'est-ce qu'on NE DOIT PAS faire

❌ **Commiter le `.env`**
```bash
git add .env  # ❌ MAUVAIS
```

❌ **Hardcoder les credentials en code**
```python
SAGE_SQL_PASSWORD = "S0digaz@Sage2026!"  # ❌ MAUVAIS
```

❌ **Passer les credentials en argument**
```bash
python run.py --sage-password="S0digaz@Sage2026!"  # ❌ MAUVAIS
```

❌ **Écrire les secrets dans les logs**
```python
logger.info(f"Connecting with: {settings.SAGE_SQL_PASSWORD}")  # ❌ MAUVAIS
```

❌ **Mettre les secrets dans les fichiers `.md` en git**
```markdown
# .env content:
SAGE_SQL_PASSWORD=S0digaz@Sage2026!  # ❌ MAUVAIS
```

---

## ✅ Qu'est-ce qu'on DOIT faire

✅ **Utiliser `.env` en local (NON commité)**
```bash
# .env (ignoré par git)
SAGE_SQL_PASSWORD=S0digaz@Sage2026!
```

✅ **Utiliser variables d'env en production**
```bash
export SAGE_SQL_PASSWORD=S0digaz@Sage2026!  # En serveur ou K8s
```

✅ **Lire depuis `os.getenv()` en Python**
```python
password = os.getenv("SAGE_SQL_PASSWORD", "")  # ✅ BON
```

✅ **Documenter le template SANS secrets**
```markdown
# .env.example (public)
SAGE_SQL_PASSWORD=your-actual-password-here
```

✅ **Vérifier `.gitignore` contient `.env`**
```bash
grep "^\.env$" .gitignore  # ✅ BON
```

---

## 🔐 Rotation des credentials

### Quand la password Sage change

1. **Mettre à jour le `.env` local** (pas commité)
   ```bash
   sed -i "s/S0digaz@Sage2026!/NEW_PASSWORD/g" .env
   ```

2. **Tester la connexion localement**
   ```bash
   python -c "from app.services.sage_sql_service import get_sage_sql_connection; get_sage_sql_connection()"
   ```

3. **Mettre à jour en production** (via système secrets)
   ```bash
   # Via Kubernetes
   kubectl patch secret sage-sql-creds -p '{"data":{"SAGE_SQL_PASSWORD":"..."}}'
   
   # Ou via variables d'env du serveur
   # Modifier /etc/sodigaz/sage-sql-secrets.env (permissions 600)
   ```

4. **Redémarrer l'application**
   ```bash
   systemctl restart sodigaz-backend
   # Ou
   docker-compose restart backend
   # Ou
   kubectl rollout restart deployment/sodigaz-backend
   ```

5. **NE PAS commiter la password en git!**

---

## 📞 Audit et vérification

### Vérifier qu'aucun secret n'est en git

```bash
# Chercher les patterns de secrets
git log -p | grep -i "sage_sql_password"
git log -p | grep -i "sodigazg_app"
git log -p | grep -i "S0digaz@"

# Résultat attendu: Aucun match
```

### Vérifier les permissions des fichiers secrets

```bash
# En production, les fichiers secrets doivent être 600
ls -la /etc/sodigaz/sage-sql-secrets.env
# -rw------- (600) OK
# -rw-r--r-- (644) ❌ MAUVAIS - Trop permissif!

# Corriger si nécessaire
chmod 600 /etc/sodigaz/sage-sql-secrets.env
```

---

## 📚 Ressources

- [OWASP - Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [Python-dotenv documentation](https://python-dotenv.readthedocs.io/)
- [Docker secrets](https://docs.docker.com/engine/swarm/secrets/)
- [Kubernetes secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [HashiCorp Vault](https://www.vaultproject.io/)

---

## 🎯 Résumé rapide

| Environnement | Fichier | Méthode | Secrets? |
|---------------|---------|---------|----------|
| Local dev | `.env` | Fichier local (ignoré) | ✅ Oui |
| CI/CD | `.env.example` | Template | ❌ Non |
| Production | Variables système | Env vars ou Secrets Manager | ✅ Oui |
| Git repo | Aucun | Jamais commiter `.env` | ❌ Non |

---

**⚠️ SÉCURITÉ AVANT TOUT!**

Si vous avez besoin de changer les credentials Sage SQL, faites-le:
1. Localement dans `.env` (NON commité)
2. En production via un Secrets Manager
3. Jamais en git


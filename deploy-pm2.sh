#!/bin/bash

# Script de déploiement SODIGAZ Backend avec PM2
# Ce script doit être exécuté DANS le dossier backend sur la VM
# Usage: cd ~/sodigaz-backend && ./deploy-pm2.sh

set -e  # Arrêter en cas d'erreur

echo "🚀 Déploiement SODIGAZ Backend avec PM2"
echo "========================================"

# Variables de configuration
CURRENT_DIR=$(pwd)
VENV_DIR="$CURRENT_DIR/venv"
DB_FILE="gas_platform.db"

# Vérifier qu'on est dans le bon répertoire
if [ ! -f "./requirements.txt" ]; then
    echo "❌ Erreur: Exécutez ce script depuis le dossier backend/"
    echo "   Usage: cd ~/sodigaz-backend && ./deploy-pm2.sh"
    exit 1
fi

# Créer la structure de répertoires
echo "📁 Vérification des répertoires..."
mkdir -p logs

# Créer l'environnement virtuel Python
echo "🐍 Configuration de l'environnement Python..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv $VENV_DIR
    echo "✅ Environnement virtuel créé"
else
    echo "ℹ️  Environnement virtuel existant trouvé"
fi

# Activer l'environnement
source $VENV_DIR/bin/activate

# Installer les dépendances
echo "📦 Installation des dépendances..."
pip3 install --upgrade pip
pip3 install -r requirements.txt

# Créer le fichier .env
echo "⚙️  Configuration de l'environnement..."
if [ ! -f "$CURRENT_DIR/.env" ]; then
    cat > $CURRENT_DIR/.env << EOF
DATABASE_URL=sqlite:///./$DB_FILE
SECRET_KEY=$(openssl rand -hex 32)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
FRONTEND_URL=http://localhost:5173
EOF
    echo "✅ Fichier .env créé"
else
    echo "ℹ️  Fichier .env existant conservé"
fi

# Initialiser la base de données
echo "🗄️  Initialisation de la base de données..."
if [ ! -f "$CURRENT_DIR/$DB_FILE" ]; then
    python3 seed_data.py
    echo "✅ Base de données initialisée avec les données de test"
else
    echo "ℹ️  Base de données existante conservée"
    # Exécuter les migrations si nécessaire
    if [ -f "add_phone_field.py" ]; then
        echo "🔄 Exécution des migrations..."
        python3 add_phone_field.py || true
    fi
fi

# Vérifier si PM2 est installé
if ! command -v pm2 &> /dev/null; then
    echo "❌ PM2 n'est pas installé"
    echo "   Installez-le avec: npm install -g pm2"
    exit 1
fi

# Vérifier si ecosystem.config.js existe
if [ ! -f "ecosystem.config.js" ]; then
    echo "❌ Fichier ecosystem.config.js introuvable"
    echo "   Assurez-vous que tous les fichiers ont été transférés"
    exit 1
fi

# Mettre à jour les chemins dans ecosystem.config.js
echo "🔧 Configuration de PM2..."
sed -i "s|/home/debian/sodigaz-backend|$CURRENT_DIR|g" ecosystem.config.js

# Arrêter l'ancienne instance si elle existe
pm2 delete sodigaz-backend 2>/dev/null || true

# Démarrer avec PM2
echo "▶️  Démarrage avec PM2..."
pm2 start ecosystem.config.js

# Sauvegarder la configuration PM2
pm2 save

# Configurer le démarrage automatique
pm2 startup | grep -v PM2 | bash || true

echo ""
echo "✅ Déploiement terminé!"
echo "========================================"
echo ""
echo "📊 Statut des services PM2:"
pm2 status
echo ""
echo "🔗 URLs:"
echo "  - API Locale: http://localhost:8000"
echo "  - Health Check: http://localhost:8000/health"
echo "  - Documentation: http://localhost:8000/docs"
echo ""
echo "📝 Commandes utiles:"
echo "  - Voir les logs: pm2 logs sodigaz-backend"
echo "  - Logs en temps réel: pm2 logs sodigaz-backend --lines 100"
echo "  - Redémarrer: pm2 restart sodigaz-backend"
echo "  - Arrêter: pm2 stop sodigaz-backend"
echo "  - Statut: pm2 status"
echo ""
echo "⚠️  PROCHAINE ÉTAPE: Configurer nginx"
echo ""
echo "1. Copier la configuration nginx:"
echo "   sudo cp nginx-sodigaz.conf /etc/nginx/sites-available/sodigaz-api"
echo ""
echo "2. Activer le site:"
echo "   sudo ln -s /etc/nginx/sites-available/sodigaz-api /etc/nginx/sites-enabled/"
echo ""
echo "3. Tester et recharger nginx:"
echo "   sudo nginx -t && sudo systemctl reload nginx"
echo ""

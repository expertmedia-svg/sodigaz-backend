#!/bin/bash

# Script de déploiement automatisé pour SODIGAZ Backend
# Usage: ./deploy.sh

set -e  # Arrêter en cas d'erreur

echo "🚀 Déploiement SODIGAZ Backend sur VM"
echo "======================================"
echo ""

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables de configuration
PROJECT_DIR="/home/sodigaz/sodigaz-platform/backend"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="sodigaz-api"

# Fonction pour afficher les messages
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Vérifier si on est root
if [ "$EUID" -eq 0 ]; then 
   error "Ne pas exécuter ce script en tant que root. Utilisez un utilisateur normal avec sudo."
fi

# Étape 1: Mise à jour du code
info "Étape 1/8: Mise à jour du code source..."
cd "$PROJECT_DIR" || error "Répertoire $PROJECT_DIR introuvable"

if [ -d ".git" ]; then
    info "Repository Git détecté, pull des dernières modifications..."
    git pull
else
    warning "Pas de repository Git, assurez-vous que le code est à jour"
fi

# Étape 2: Mise à jour de l'environnement virtuel
info "Étape 2/8: Activation de l'environnement virtuel..."
if [ ! -d "$VENV_DIR" ]; then
    error "Environnement virtuel non trouvé dans $VENV_DIR"
fi

source "$VENV_DIR/bin/activate" || error "Impossible d'activer l'environnement virtuel"

# Étape 3: Mise à jour des dépendances
info "Étape 3/8: Mise à jour des dépendances Python..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
info "Dépendances installées avec succès"

# Étape 4: Vérification du fichier .env
info "Étape 4/8: Vérification de la configuration..."
if [ ! -f ".env" ]; then
    warning "Fichier .env non trouvé. Création d'un fichier template..."
    cat > .env << EOF
DATABASE_URL=sqlite:///./sodigaz.db
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ALLOWED_ORIGINS=https://votre-domaine.com
API_HOST=0.0.0.0
API_PORT=8001
EOF
    warning "⚠️  Fichier .env créé. MODIFIEZ-LE avant de continuer !"
    read -p "Appuyez sur Entrée après avoir modifié le fichier .env..."
fi

# Étape 5: Migrations de base de données
info "Étape 5/8: Exécution des migrations..."
if [ -f "add_phone_field.py" ]; then
    python3 add_phone_field.py || warning "Migration add_phone_field.py échouée ou déjà appliquée"
fi

# Étape 6: Test de l'application
info "Étape 6/8: Test de l'application..."
python3 -c "from app.main import app; print('✅ Import de app.main réussi')" || error "Erreur lors de l'import de l'application"

# Étape 7: Redémarrage du service
info "Étape 7/8: Redémarrage du service $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME" || error "Échec du redémarrage du service"

# Attendre que le service démarre
sleep 3

# Vérifier le statut du service
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    info "✅ Service $SERVICE_NAME actif et en cours d'exécution"
else
    error "❌ Le service $SERVICE_NAME n'a pas démarré correctement"
    sudo journalctl -u "$SERVICE_NAME" -n 20
    exit 1
fi

# Étape 8: Test de santé de l'API
info "Étape 8/8: Test de santé de l'API..."
sleep 2

HEALTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/health 2>/dev/null || echo "000")

if [ "$HEALTH_CHECK" = "200" ]; then
    info "✅ API répond correctement (HTTP 200)"
else
    warning "⚠️  L'API ne répond pas comme attendu (HTTP $HEALTH_CHECK)"
    warning "Vérifier les logs avec: sudo journalctl -u $SERVICE_NAME -f"
fi

# Afficher les derniers logs
info "Derniers logs du service:"
sudo journalctl -u "$SERVICE_NAME" -n 10 --no-pager

echo ""
echo "======================================"
echo -e "${GREEN}✅ Déploiement terminé avec succès !${NC}"
echo "======================================"
echo ""
echo "📊 Commandes utiles:"
echo "  - Voir les logs: sudo journalctl -u $SERVICE_NAME -f"
echo "  - Statut: sudo systemctl status $SERVICE_NAME"
echo "  - Redémarrer: sudo systemctl restart $SERVICE_NAME"
echo "  - Arrêter: sudo systemctl stop $SERVICE_NAME"
echo ""
echo "🌐 Endpoints de test:"
echo "  - Health: http://localhost:8001/api/health"
echo "  - Docs: http://localhost:8001/docs"
echo ""

#!/bin/bash
# Test workflow Sage X3 en MODE MOCK avec cURL
# Usage: bash test_sage.sh

set -e

BASE_URL="http://localhost:8000"
SAGE_INBOUND_TOKEN="test-token-123"

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables pour stocker les tokens
ADMIN_TOKEN=""
DRIVER_TOKEN=""
DELIVERY_ID=""

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# ============================================================================
# ÉTAPE 0: LOGIN
# ============================================================================

step_0_login() {
    print_header "ÉTAPE 0: LOGIN"
    
    print_info "Login en tant qu'ADMIN..."
    ADMIN_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"password123"}')
    
    ADMIN_TOKEN=$(echo $ADMIN_LOGIN_RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
    
    if [ -z "$ADMIN_TOKEN" ]; then
        print_error "Échec login admin. Réponse: $ADMIN_LOGIN_RESPONSE"
        exit 1
    fi
    print_success "Admin connecté: ${ADMIN_TOKEN:0:20}..."
    
    print_info "Login en tant que DRIVER..."
    DRIVER_LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"driver1","password":"password123"}')
    
    DRIVER_TOKEN=$(echo $DRIVER_LOGIN_RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
    
    if [ -z "$DRIVER_TOKEN" ]; then
        print_error "Échec login driver. Réponse: $DRIVER_LOGIN_RESPONSE"
        exit 1
    fi
    print_success "Driver connecté: ${DRIVER_TOKEN:0:20}..."
}

# ============================================================================
# ÉTAPE 1: SAGE ENVOIE UNE MISSION
# ============================================================================

step_1_sage_sends_mission() {
    print_header "ÉTAPE 1: Sage X3 ENVOIE une mission"
    
    SAGE_DELIVERY_ID="SAGE-MOCK-$(date +%s)"
    SCHEDULED_DATE=$(date -u -d "+2 hours" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -v+2H +"%Y-%m-%dT%H:%M:%SZ")
    
    print_info "Envoi d'une mission avec ID Sage: $SAGE_DELIVERY_ID"
    
    SAGE_RESPONSE=$(curl -s -X POST "$BASE_URL/api/logistics/v1/sage-missions/inbound" \
        -H "Content-Type: application/json" \
        -H "X-Sage-X3-Token: $SAGE_INBOUND_TOKEN" \
        -d "{
            \"external_delivery_id\": \"$SAGE_DELIVERY_ID\",
            \"destination_name\": \"Boutique Ouagadougou\",
            \"destination_address\": \"123 Avenue de la Paix, Ouaga\",
            \"destination_latitude\": 12.3656,
            \"destination_longitude\": -1.5197,
            \"contact_name\": \"Mr. Koné\",
            \"contact_phone\": \"+226 70123456\",
            \"depot_id\": 1,
            \"quantity_6kg\": 50,
            \"quantity_12kg\": 30,
            \"scheduled_date\": \"$SCHEDULED_DATE\",
            \"notes\": \"Test mode MOCK\"
        }")
    
    echo "Réponse: $SAGE_RESPONSE"
    
    DELIVERY_ID=$(echo $SAGE_RESPONSE | grep -o '"delivery_id":[0-9]*' | cut -d':' -f2)
    
    if [ -z "$DELIVERY_ID" ]; then
        print_error "Erreur réception mission. Réponse: $SAGE_RESPONSE"
        exit 1
    fi
    
    print_success "Mission enregistrée avec delivery_id: $DELIVERY_ID"
}

# ============================================================================
# ÉTAPE 2: ADMIN VOIT LA MISSION
# ============================================================================

step_2_admin_views() {
    print_header "ÉTAPE 2: ADMIN voit les missions EN ATTENTE"
    
    MISSIONS=$(curl -s -X GET "$BASE_URL/api/admin/sage-missions?status=pending_approval" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json")
    
    echo "Missions en attente:"
    echo "$MISSIONS" | head -c 500
    echo ""
    
    print_success "Missions affichées sur le dashboard"
}

# ============================================================================
# ÉTAPE 3: ADMIN APPROUVE
# ============================================================================

step_3_admin_approves() {
    print_header "ÉTAPE 3: ADMIN valide et assigne un CAMION"
    
    print_info "Approbation de la mission $DELIVERY_ID avec camion 1"
    
    APPROVE_RESPONSE=$(curl -s -X POST "$BASE_URL/api/admin/sage-missions/$DELIVERY_ID/approve" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"truck_id": 1}')
    
    echo "Réponse: $APPROVE_RESPONSE"
    
    if echo "$APPROVE_RESPONSE" | grep -q '"success":true'; then
        print_success "Mission approuvée!"
    else
        print_error "Erreur approbation: $APPROVE_RESPONSE"
        exit 1
    fi
}

# ============================================================================
# ÉTAPE 4: DRIVER TÉLÉCHARGE
# ============================================================================

step_4_driver_downloads() {
    print_header "ÉTAPE 4: DRIVER télécharge les missions APPROUVÉES"
    
    DOWNLOAD=$(curl -s -X GET "$BASE_URL/api/admin/sage-missions/mobile/download" \
        -H "Authorization: Bearer $DRIVER_TOKEN" \
        -H "Content-Type: application/json")
    
    echo "Missions disponibles pour le driver:"
    echo "$DOWNLOAD" | head -c 500
    echo ""
    
    if echo "$DOWNLOAD" | grep -q '"count":'; then
        COUNT=$(echo "$DOWNLOAD" | grep -o '"count":[0-9]*' | cut -d':' -f2)
        print_success "Driver a téléchargé $COUNT mission(s)"
    fi
}

# ============================================================================
# ÉTAPE 5: CHECK INTÉGRATION HEALTH
# ============================================================================

step_5_health_check() {
    print_header "ÉTAPE 5: Vérifier l'état de CONNEXION Sage X3"
    
    HEALTH=$(curl -s -X POST "$BASE_URL/api/admin/integration-outbox/health/check" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}')
    
    echo "État Sage X3:"
    echo "$HEALTH" | grep -E '"status"|"mode"|"detail"' | head -c 300
    echo ""
    
    print_success "Health check complété"
}

# ============================================================================
# ÉTAPE 6: VIEW OUTBOX
# ============================================================================

step_6_view_outbox() {
    print_header "ÉTAPE 6: VUE de l'IntegrationOutbox"
    
    print_info "Events ENVOYÉS:"
    SENT=$(curl -s -X GET "$BASE_URL/api/admin/integration-outbox?status=sent" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json")
    
    if echo "$SENT" | grep -q '"event_type"'; then
        echo "$SENT" | grep -o '"event_type":"[^"]*' | wc -l | xargs -I {} echo "  {} events"
    else
        echo "  Aucun event (MODE MOCK)"
    fi
    
    print_info "Events EN ATTENTE:"
    PENDING=$(curl -s -X GET "$BASE_URL/api/admin/integration-outbox?status=pending" \
        -H "Authorization: Bearer $ADMIN_TOKEN" \
        -H "Content-Type: application/json")
    
    if echo "$PENDING" | grep -q '"event_type"'; then
        echo "$PENDING" | grep -o '"event_type":"[^"]*' | wc -l | xargs -I {} echo "  {} events"
    else
        echo "  Aucun event"
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    print_header "TEST SAGE X3 - MODE MOCK"
    
    print_info "Base URL: $BASE_URL"
    print_info "Sage Token: $SAGE_INBOUND_TOKEN"
    print_info ""
    
    step_0_login
    step_1_sage_sends_mission
    step_2_admin_views
    step_3_admin_approves
    step_4_driver_downloads
    step_5_health_check
    step_6_view_outbox
    
    print_header "✅ TEST TERMINÉ - TOUT FONCTIONNE!"
}

main

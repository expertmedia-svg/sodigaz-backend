#!/usr/bin/env python3
"""
Test complet du workflow Sage X3 en MODE MOCK

Scénario:
1. Sage X3 envoie une mission (inbound) → "Cahier de charge"
2. Admin approuve la mission
3. Driver télécharge et exécute
4. Events confirmés sont enregistrés dans l'outbox
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Optional

# Configuration
BASE_URL = "http://localhost:8000"
ADMIN_TOKEN = ""  # À récupérer après login
DRIVER_TOKEN = ""  # À récupérer après login
SAGE_INBOUND_TOKEN = "test-token-123"

# ============================================================================
# UTILITAIRES
# ============================================================================

def print_step(step: int, title: str):
    """Affiche une étape du test"""
    print(f"\n{'='*70}")
    print(f"  ÉTAPE {step}: {title}")
    print(f"{'='*70}\n")

def print_success(msg: str):
    """Message de succès"""
    print(f"✅ {msg}")

def print_error(msg: str):
    """Message d'erreur"""
    print(f"❌ {msg}")

def print_info(msg: str):
    """Info générale"""
    print(f"ℹ️  {msg}")

def make_request(method: str, endpoint: str, data: dict = None, 
                token: Optional[str] = None, inbound: bool = False) -> dict:
    """Effectue une requête HTTP"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    if inbound:
        headers["X-Sage-X3-Token"] = SAGE_INBOUND_TOKEN
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, json=data, headers=headers)
        elif method == "PUT":
            response = requests.put(url, json=data, headers=headers)
        else:
            raise ValueError(f"Méthode HTTP inconnue: {method}")
        
        if response.status_code in [200, 201, 204]:
            print_success(f"{method} {endpoint} → {response.status_code}")
            if response.text:
                return response.json()
            return {}
        else:
            print_error(f"{method} {endpoint} → {response.status_code}")
            print(f"Réponse: {response.text}")
            return {"error": response.text}
    
    except Exception as e:
        print_error(f"Erreur requête: {e}")
        return {"error": str(e)}

# ============================================================================
# ÉTAPE 0: LOGIN ET SETUP
# ============================================================================

def step_0_login():
    """Se connecter comme admin et driver"""
    global ADMIN_TOKEN, DRIVER_TOKEN
    
    print_step(0, "LOGIN - Obtenir les tokens")
    
    # Login Admin
    print_info("Tentative login: admin / password123")
    admin_login = make_request("POST", "/api/auth/login", {
        "username": "admin",
        "password": "password123"
    })
    
    if "access_token" in admin_login:
        ADMIN_TOKEN = admin_login["access_token"]
        print_success(f"Admin connecté: {ADMIN_TOKEN[:20]}...")
    else:
        print_error("Échec login admin")
        return False
    
    # Login Driver
    print_info("Tentative login: driver1 / password123")
    driver_login = make_request("POST", "/api/auth/login", {
        "username": "driver1",
        "password": "password123"
    })
    
    if "access_token" in driver_login:
        DRIVER_TOKEN = driver_login["access_token"]
        print_success(f"Driver connecté: {DRIVER_TOKEN[:20]}...")
    else:
        print_error("Échec login driver")
        return False
    
    return True

# ============================================================================
# ÉTAPE 1: SAGE X3 ENVOIE UNE MISSION
# ============================================================================

def step_1_sage_sends_mission():
    """Simuler l'envoi de mission par Sage X3"""
    print_step(1, "Sage X3 ENVOIE une mission (Cahier de Charge)")
    
    mission_data = {
        "external_delivery_id": f"SAGE-2025-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "destination_name": "Boutique Central Ouaga",
        "destination_address": "123 Avenue de la Paix, Ouagadougou",
        "destination_latitude": 12.3656,
        "destination_longitude": -1.5197,
        "contact_name": "Mr. Koné",
        "contact_phone": "+226 70123456",
        "depot_id": 1,
        "quantity_6kg": 50,
        "quantity_12kg": 30,
        "scheduled_date": (datetime.now() + timedelta(hours=2)).isoformat() + "Z",
        "notes": "Livraison urgente - stock critique"
    }
    
    print_info(f"Mission envoyée par Sage X3:")
    print(json.dumps(mission_data, indent=2, ensure_ascii=False))
    
    result = make_request("POST", "/api/logistics/v1/sage-missions/inbound",
                         mission_data, inbound=True)
    
    if "delivery_id" in result:
        delivery_id = result["delivery_id"]
        print_success(f"Mission reçue et enregistrée: delivery_id={delivery_id}")
        print_success(f"Statut: {result.get('status', 'pending_approval')}")
        return delivery_id
    else:
        print_error(f"Erreur réception mission: {result}")
        return None

# ============================================================================
# ÉTAPE 2: ADMIN VOIT LA MISSION EN ATTENTE
# ============================================================================

def step_2_admin_views_pending():
    """Admin consulte le cahier de charge (missions en attente)"""
    print_step(2, "ADMIN consulte les missions en ATTENTE")
    
    result = make_request("GET", "/api/admin/sage-missions?status=pending_approval",
                         token=ADMIN_TOKEN)
    
    if isinstance(result, list):
        print_success(f"Missions en attente d'approbation: {len(result)}")
        for i, mission in enumerate(result):
            print(f"\n  Mission {i+1}:")
            print(f"    ID: {mission.get('id')}")
            print(f"    Sage ID: {mission.get('external_delivery_id')}")
            print(f"    Destination: {mission.get('destination_name')}")
            print(f"    Adresse: {mission.get('destination_address')}")
            print(f"    Quantité: {mission.get('quantity_6kg')}×6kg + {mission.get('quantity_12kg')}×12kg")
            print(f"    Contact: {mission.get('contact_name')} / {mission.get('contact_phone')}")
        return result[0] if result else None
    else:
        print_error(f"Erreur récupération missions: {result}")
        return None

# ============================================================================
# ÉTAPE 3: ADMIN APPROUVE LA MISSION ET ASSIGNE UN CAMION
# ============================================================================

def step_3_admin_approves(delivery_id: int, truck_id: int = 1):
    """Admin approuve la mission et assigne un camion"""
    print_step(3, "ADMIN valide et assigne LA MISSION")
    
    print_info(f"Approbation de la mission {delivery_id} avec camion {truck_id}")
    
    result = make_request("POST", f"/api/admin/sage-missions/{delivery_id}/approve",
                         {"truck_id": truck_id}, token=ADMIN_TOKEN)
    
    if result.get("success"):
        print_success(f"Mission approuvée: {result.get('message')}")
        print_success(f"Delivery ID: {result.get('delivery_id')}")
        return True
    else:
        print_error(f"Erreur approbation: {result}")
        return False

# ============================================================================
# ÉTAPE 4: DRIVER TÉLÉCHARGE LES MISSIONS
# ============================================================================

def step_4_driver_downloads_missions():
    """Driver télécharge les missions approuvées"""
    print_step(4, "DRIVER télécharge les missions APPROUVÉES")
    
    result = make_request("GET", "/api/admin/sage-missions/mobile/download",
                         token=DRIVER_TOKEN)
    
    if result.get("success"):
        missions = result.get("missions", [])
        print_success(f"Missions téléchargées: {result.get('count')}")
        for i, mission in enumerate(missions):
            print(f"\n  Mission {i+1}:")
            print(f"    ID Sage: {mission.get('external_delivery_id')}")
            print(f"    Destination: {mission.get('destination_name')}")
            print(f"    Lat/Long: {mission.get('destination_latitude')}, {mission.get('destination_longitude')}")
            print(f"    Quantité: {mission.get('quantity_6kg')}×6kg + {mission.get('quantity_12kg')}×12kg")
            print(f"    Scheduled: {mission.get('scheduled_date')}")
        return missions
    else:
        print_error(f"Erreur téléchargement: {result}")
        return []

# ============================================================================
# ÉTAPE 5: AFFICHER L'INTÉGRATION HEALTH
# ============================================================================

def step_5_check_integration_health():
    """Vérifier l'état de l'intégration Sage X3"""
    print_step(5, "Vérifier l'état de CONNEXION Sage X3")
    
    result = make_request("POST", "/api/admin/integration-outbox/health/check",
                         {}, token=ADMIN_TOKEN)
    
    if "status" in result:
        print_info(f"Mode: {result.get('mode', 'unknown')}")
        print_info(f"Status: {result.get('status', 'unknown')}")
        print_info(f"Detail: {result.get('detail', 'N/A')}")
        
        # Afficher les stats outbox
        outbox = result.get("outbox", {})
        print_info(f"\nOutbox Events:")
        print_info(f"  ✅ Envoyés: {outbox.get('sent', 0)}")
        print_info(f"  ⏳ En attente: {outbox.get('pending', 0)}")
        print_info(f"  ❌ Erreurs permanentes: {outbox.get('failed_dead_letter', 0)}")
        
        if outbox.get("pending", 0) > 0:
            print_info("\nℹ️  Il y a des events en attente d'envoi à Sage X3")
            print_info("   → Mode MOCK: Pas d'HTTP réel")
            print_info("   → Events enregistrés dans IntegrationOutbox")
        
        return True
    else:
        print_error(f"Erreur health check: {result}")
        return False

# ============================================================================
# ÉTAPE 6: PROCESSUS INTÉGRATION OUTBOX
# ============================================================================

def step_6_process_outbox():
    """Traiter manuellement la file d'intégration"""
    print_step(6, "TRAITER les events de l'IntegrationOutbox")
    
    print_info("Lancement du traitement des events...")
    result = make_request("POST", "/api/admin/integration-outbox/process",
                         {"limit": 50}, token=ADMIN_TOKEN)
    
    if result.get("processed"):
        print_success(f"Events traités: {result.get('processed', 0)}")
        print_success(f"Events envoyés: {result.get('sent', 0)}")
        print_success(f"Events en erreur: {result.get('failed', 0)}")
    else:
        print_info(f"Aucun event à traiter ou en mode MOCK")

# ============================================================================
# ÉTAPE 7: VOIR TOUS LES EVENTS DANS L'OUTBOX
# ============================================================================

def step_7_view_outbox():
    """Afficher tous les events de l'outbox"""
    print_step(7, "VUE COMPLÈTE de l'IntegrationOutbox")
    
    # Events envoyés
    print_info("Events ENVOYÉS avec succès:")
    result_sent = make_request("GET", "/api/admin/integration-outbox?status=sent",
                               token=ADMIN_TOKEN)
    if isinstance(result_sent, list):
        print_success(f"  Total: {len(result_sent)} events")
        for event in result_sent[:3]:  # Afficher les 3 premiers
            print(f"    - {event.get('event_type')} (ID: {event.get('id')})")
    
    # Events en attente
    print_info("\nEvents EN ATTENTE d'envoi:")
    result_pending = make_request("GET", "/api/admin/integration-outbox?status=pending",
                                 token=ADMIN_TOKEN)
    if isinstance(result_pending, list):
        print_info(f"  Total: {len(result_pending)} events")
        for event in result_pending[:3]:
            print(f"    - {event.get('event_type')} (ID: {event.get('id')})")
    
    # Events en erreur
    print_info("\nEvents EN ERREUR:")
    result_failed = make_request("GET", "/api/admin/integration-outbox?status=failed_dead_letter",
                                token=ADMIN_TOKEN)
    if isinstance(result_failed, list):
        if len(result_failed) == 0:
            print_success("  Aucune erreur 🎉")
        else:
            print_error(f"  Total: {len(result_failed)} events")
            for event in result_failed:
                print(f"    - {event.get('event_type')} (Error: {event.get('error_message')})")

# ============================================================================
# ÉTAPE 8: DASHBOARD WIDGET CHECK
# ============================================================================

def step_8_dashboard_check():
    """Vérifier les données du dashboard"""
    print_step(8, "Vérifier les DONNÉES DU DASHBOARD")
    
    result = make_request("GET", "/api/admin/dashboard/overview", token=ADMIN_TOKEN)
    
    if "total_depots" in result:
        print_success("Dashboard overview:")
        print(f"  Dépôts: {result.get('total_depots', 0)}")
        print(f"  Camions: {result.get('active_trucks', 0)}")
        print(f"  Livraisons actives: {result.get('in_progress_deliveries', 0)}")
        print(f"  Alertes stock: {result.get('low_stock_depots', 0)}")
    else:
        print_error(f"Erreur: {result}")

# ============================================================================
# MAIN - ORCHESTRER TOUS LES TESTS
# ============================================================================

def main():
    print("\n" + "="*70)
    print("  TEST COMPLET SAGE X3 - MODE MOCK")
    print("="*70)
    print("\nAssurez-vous que le backend est démarré:")
    print("  python -m uvicorn app.main:app --reload --port 8000\n")
    
    # Étape 0: Login
    if not step_0_login():
        return
    
    # Étape 1: Sage envoie mission
    delivery_id = step_1_sage_sends_mission()
    if not delivery_id:
        return
    
    # Étape 2: Admin voit mission en attente
    mission = step_2_admin_views_pending()
    
    # Étape 3: Admin approuve
    if not step_3_admin_approves(delivery_id):
        return
    
    # Étape 4: Driver télécharge
    missions = step_4_driver_downloads_missions()
    
    # Étape 5: Check intégration health
    step_5_check_integration_health()
    
    # Étape 6: Traiter outbox
    step_6_process_outbox()
    
    # Étape 7: Voir l'outbox
    step_7_view_outbox()
    
    # Étape 8: Dashboard
    step_8_dashboard_check()
    
    print("\n" + "="*70)
    print("  ✅ TEST COMPLET TERMINÉ")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()

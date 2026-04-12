#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import date, datetime, timezone
from typing import Any

import httpx


DEFAULT_BASE_URL = os.getenv("SODIGAZ_BACKEND_URL", "http://localhost:8000")
DEFAULT_ADMIN_USERNAME = os.getenv("SODIGAZ_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("SODIGAZ_ADMIN_PASSWORD", "password123")
DEFAULT_DRIVER_USERNAME = os.getenv("SODIGAZ_DRIVER_USERNAME", "driver1")
DEFAULT_DRIVER_PASSWORD = os.getenv("SODIGAZ_DRIVER_PASSWORD", "password123")
DEFAULT_SAGE_HEADER = os.getenv("SAGE_X3_INBOUND_AUTH_HEADER", "X-Sage-X3-Token")
DEFAULT_SAGE_SCHEME = os.getenv("SAGE_X3_INBOUND_AUTH_SCHEME", "token")
DEFAULT_SAGE_TOKEN = os.getenv("SAGE_X3_INBOUND_TOKEN", "test-token-123")


def banner(title: str) -> None:
    print(f"\n{'=' * 78}")
    print(title)
    print(f"{'=' * 78}\n")


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def build_auth_header(header_name: str, scheme: str, token: str) -> dict[str, str]:
    if scheme.lower() == "bearer":
        return {header_name: f"Bearer {token}"}
    return {header_name: token}


def login(client: httpx.Client, base_url: str, username: str, password: str) -> dict[str, Any]:
    response = client.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()


def get_json(response: httpx.Response) -> Any:
    response.raise_for_status()
    return response.json()


def build_program_payload(driver_id: int, truck_id: int) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    program_code = f"DEMO-SAGE-{timestamp}"
    return {
        "program_code": program_code,
        "program_type": "DELIVERY",
        "site": "SOD-BF-DEMO",
        "date": date.today().isoformat(),
        "time": "08:30",
        "depot_id": 1,
        "truck_id": truck_id,
        "driver_id": driver_id,
        "transporter": "SODIGAZ DEMO",
        "status": "active",
        "source_updated_at": datetime.now(timezone.utc).isoformat(),
        "sync_version": 1,
        "lines": [
            {
                "external_line_id": f"DEMO-LINE-{timestamp}",
                "line_code": "LINE-001",
                "client_code": "CLI-DEMO-001",
                "client_name": "Client Demonstration",
                "destination_address": "Zone Industrielle, Ouagadougou",
                "destination_latitude": 12.3714,
                "destination_longitude": -1.5197,
                "contact_name": "Responsable Client",
                "contact_phone": "+22670123456",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12kg",
                "article": "B12",
                "zone": "OUAGA",
                "quantity_planned": 5,
                "delivery_mode": "TRUCK",
                "comment": "Programme de demonstration Sage -> chauffeur",
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Démonstration aller-retour Sage -> SODIGAZ -> Chauffeur -> Sage (mode mock conseillé).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--admin-username", default=DEFAULT_ADMIN_USERNAME)
    parser.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD)
    parser.add_argument("--driver-username", default=DEFAULT_DRIVER_USERNAME)
    parser.add_argument("--driver-password", default=DEFAULT_DRIVER_PASSWORD)
    parser.add_argument("--driver-id", type=int, default=None, help="ID interne du chauffeur cible pour le programme Sage. Si absent, l'ID du compte chauffeur connecté est utilisé.")
    parser.add_argument("--truck-id", type=int, default=1, help="ID interne du camion à affecter")
    parser.add_argument("--sage-header", default=DEFAULT_SAGE_HEADER)
    parser.add_argument("--sage-scheme", choices=["token", "bearer"], default=DEFAULT_SAGE_SCHEME)
    parser.add_argument("--sage-token", default=DEFAULT_SAGE_TOKEN)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    banner("DEMO ALLER-RETOUR SAGE X3 -> SODIGAZ -> CHAUFFEUR -> SAGE")
    print(f"Backend: {args.base_url}")
    print(f"Driver cible: {args.driver_username} (driver_id={args.driver_id})")
    print(f"Camion cible: truck_id={args.truck_id}")

    inbound_headers = {
        "Content-Type": "application/json",
        **build_auth_header(args.sage_header, args.sage_scheme, args.sage_token),
    }

    with httpx.Client(timeout=args.timeout) as client:
        step("1. Connexion admin et chauffeur")
        admin_session = login(client, args.base_url, args.admin_username, args.admin_password)
        driver_session = login(client, args.base_url, args.driver_username, args.driver_password)
        admin_token = admin_session["access_token"]
        driver_token = driver_session["access_token"]
        driver_user = driver_session.get("user") or {}
        resolved_driver_id = args.driver_id or driver_user.get("id")
        if not resolved_driver_id:
            raise RuntimeError("Impossible de déterminer l'ID du chauffeur. Fournir --driver-id explicitement.")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        driver_headers = {"Authorization": f"Bearer {driver_token}"}
        print("OK admin connecté")
        print(f"OK chauffeur connecté (driver_id={resolved_driver_id})")

        step("2. Sage envoie un programme au backend")
        program_payload = build_program_payload(int(resolved_driver_id), args.truck_id)
        print(json.dumps(program_payload, indent=2, ensure_ascii=False))
        inbound_response = get_json(
            client.post(
                f"{args.base_url.rstrip('/')}/api/integration/sage/programs",
                headers=inbound_headers,
                json=program_payload,
            )
        )
        print(json.dumps(inbound_response, indent=2, ensure_ascii=False))
        program_code = inbound_response["program_code"]

        step("3. Contrôle admin: le programme existe côté SODIGAZ")
        program_response = get_json(
            client.get(
                f"{args.base_url.rstrip('/')}/api/integration/programs/{program_code}",
                headers=admin_headers,
            )
        )
        print(f"Programme: {program_response['program_code']} | statut={program_response['status']} | lignes={len(program_response.get('lines', []))}")

        step("4. Côté chauffeur: bootstrap et programmes du jour")
        bootstrap = get_json(
            client.get(
                f"{args.base_url.rstrip('/')}/api/driver/bootstrap",
                headers=driver_headers,
            )
        )
        today_programs = bootstrap.get("today_programs", [])
        assignments = bootstrap.get("assignments", [])
        print(f"Programmes du jour visibles: {len(today_programs)}")
        print(f"Missions actives visibles: {len(assignments)}")
        matching_assignment = next(
            (item for item in assignments if item.get("program_code") == program_code),
            None,
        )
        if matching_assignment is None:
            raise RuntimeError(
                f"Aucune mission chauffeur trouvée pour le programme {program_code}. Vérifier driver_id/truck_id et le compte utilisé."
            )
        print(json.dumps(matching_assignment, indent=2, ensure_ascii=False))

        step("5. Simulation app mobile: confirmation de livraison")
        delivery_id = int(matching_assignment["id"])
        quantity_delivered = int(matching_assignment.get("quantity_12kg") or matching_assignment.get("quantity_6kg") or 1)
        product_code = "GAZ_12KG" if int(matching_assignment.get("quantity_12kg") or 0) > 0 else "GAZ_6KG"
        confirmation_id = f"demo-confirm-{delivery_id}-{int(datetime.now(timezone.utc).timestamp())}"
        batch_payload = {
            "device_id": f"android-driver-{resolved_driver_id}",
            "driver_id": resolved_driver_id,
            "batch_id": f"demo-batch-{int(datetime.now(timezone.utc).timestamp())}",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": f"driver-{resolved_driver_id}-{confirmation_id}",
                    "payload": {
                        "confirmation_id": confirmation_id,
                        "delivery_id": delivery_id,
                        "operation_type": "delivery_confirmation",
                        "program_type": "DELIVERY",
                        "product": product_code,
                        "quantity_delivered": quantity_delivered,
                        "quantity_collected": 0,
                        "quantity_empty_collected": 0,
                        "customer": matching_assignment.get("destination_name"),
                        "customer_phone": matching_assignment.get("contact_phone"),
                        "confirmed_by": "Client Demonstration",
                        "signature_base64": base64.b64encode(b"signature-demo").decode("ascii"),
                        "confirmation_code": "DEMO-OK",
                        "notes": "Validation effectuee depuis la demonstration mobile",
                        "gps": {
                            "latitude": 12.3714,
                            "longitude": -1.5197,
                            "accuracy": 8.5,
                        },
                        "delivered_at": datetime.now(timezone.utc).isoformat(),
                        "confirmation_mode": "signature",
                    },
                }
            ],
        }
        batch_response = get_json(
            client.post(
                f"{args.base_url.rstrip('/')}/api/driver/sync/batch",
                headers=driver_headers,
                json=batch_payload,
            )
        )
        print(json.dumps(batch_response, indent=2, ensure_ascii=False))

        step("6. Vérification admin: l'événement Sage est visible dans l'outbox")
        outbox_before = get_json(
            client.get(
                f"{args.base_url.rstrip('/')}/api/admin/integration-outbox?status=all&limit=10",
                headers=admin_headers,
            )
        )
        interesting = [
            item for item in outbox_before
            if item.get("aggregate_id") == str(delivery_id) or program_code in (item.get("message_id") or "")
        ]
        print(json.dumps(interesting, indent=2, ensure_ascii=False))

        step("7. Traitement complémentaire de l'outbox si nécessaire")
        process_response = get_json(
            client.post(
                f"{args.base_url.rstrip('/')}/api/admin/integration-outbox/process",
                headers=admin_headers,
                json={"limit": 20},
            )
        )
        print(json.dumps(process_response, indent=2, ensure_ascii=False))

        step("8. Preuve finale: l'événement est maintenant marque comme envoye")
        outbox_after = get_json(
            client.get(
                f"{args.base_url.rstrip('/')}/api/admin/integration-outbox?status=all&limit=10",
                headers=admin_headers,
            )
        )
        final_events = [
            item for item in outbox_after
            if item.get("aggregate_id") == str(delivery_id) or (item.get("message_id") or "").endswith(confirmation_id)
        ]
        print(json.dumps(final_events, indent=2, ensure_ascii=False))

        step("9. Vérification santé intégration")
        health = get_json(
            client.post(
                f"{args.base_url.rstrip('/')}/api/admin/integration-outbox/health/check",
                headers=admin_headers,
                json={},
            )
        )
        print(json.dumps(health, indent=2, ensure_ascii=False))

    banner("DEMO TERMINEE")
    print("Ce que vous pouvez dire au client:")
    print("1. Sage pousse un programme vers le backend via une API sécurisée.")
    print("2. Le backend projette ce programme en missions visibles chez le bon chauffeur.")
    print("3. Le chauffeur confirme la livraison depuis l'app, même via le moteur offline-first.")
    print("4. La confirmation crée un événement d'intégration vers Sage.")
    print("5. L'outbox prouve l'envoi vers Sage: pending puis sent en mode mock/http.")


if __name__ == "__main__":
    main()
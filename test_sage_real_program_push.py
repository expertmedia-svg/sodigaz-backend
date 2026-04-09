import argparse
import json
import os
from pathlib import Path

import httpx


DEFAULT_BACKEND_URL = os.getenv("SODIGAZ_BACKEND_URL", "http://localhost:8000")
DEFAULT_INBOUND_HEADER = os.getenv("SAGE_X3_INBOUND_AUTH_HEADER", "X-Sage-X3-Token")
DEFAULT_INBOUND_SCHEME = os.getenv("SAGE_X3_INBOUND_AUTH_SCHEME", "token")
DEFAULT_INBOUND_TOKEN = os.getenv("SAGE_X3_INBOUND_TOKEN", "test-token-123")


def build_headers(header_name: str, scheme: str, token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if scheme.lower() == "bearer":
        headers[header_name] = f"Bearer {token}"
    else:
        headers[header_name] = token
    return headers


def main() -> None:
    parser = argparse.ArgumentParser(description="Push un payload programme Sage reel vers le backend Sodigaz.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL, help="Base URL du backend Sodigaz, ex: http://localhost:8000")
    parser.add_argument("--file", required=True, help="Chemin du fichier JSON a envoyer")
    parser.add_argument("--header", default=DEFAULT_INBOUND_HEADER, help="Header d'authentification entrante")
    parser.add_argument("--scheme", default=DEFAULT_INBOUND_SCHEME, choices=["token", "bearer"], help="Scheme d'authentification entrante")
    parser.add_argument("--token", default=DEFAULT_INBOUND_TOKEN, help="Token/secret entrant attendu par le backend")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout HTTP en secondes")
    args = parser.parse_args()

    payload_path = Path(args.file).resolve()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    url = f"{args.backend_url.rstrip('/')}/api/integration/sage/programs"
    headers = build_headers(args.header, args.scheme, args.token)

    print(f"POST {url}")
    print(f"Auth header: {args.header} ({args.scheme})")
    print(f"Payload file: {payload_path}")

    with httpx.Client(timeout=args.timeout) as client:
        response = client.post(url, json=payload, headers=headers)

    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)


if __name__ == "__main__":
    main()
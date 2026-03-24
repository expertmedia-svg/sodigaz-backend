#!/usr/bin/env python
"""
Lancer le serveur FastAPI Sodigaz
"""

import uvicorn
import os

if __name__ == "__main__":
    # Lire le port depuis les env vars ou utiliser 8001 par défaut
    port = int(os.getenv("BACKEND_PORT", 8001))
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    
    print(f"🚀 Démarrage du backend Sodigaz sur {host}:{port}")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )

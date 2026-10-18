"""Poste le message de la semaine (ou le message d'échec) sur le salon Discord de l'AJA.

Usage : python scripts/discord.py 2026-W42   |   python scripts/discord.py --echec
L'adresse du webhook vient de la variable d'environnement DISCORD_WEBHOOK_URL (secret GitHub), jamais du code.
"""
import json
import os
import pathlib
import sys
import urllib.request

RACINE = pathlib.Path(__file__).resolve().parent.parent
ECHEC = "Récap de la semaine indisponible, le relevé Listhammer a échoué."


def poster(texte):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("DISCORD_WEBHOOK_URL absent : message non envoyé.\n---\n" + texte)
        return
    corps = json.dumps({"content": texte, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(url, data=corps, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "MetaHebdoAJA/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"Message Discord envoyé (HTTP {r.status}).")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--echec":
        poster(ECHEC)
    else:
        poster((RACINE / "data" / sys.argv[1] / "discord.txt").read_text().strip())

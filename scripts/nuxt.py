"""Décodage des données embarquées dans les pages Listhammer (format Nuxt « devalue »)."""
import json
import re

WRAPPERS = {"ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}


def charger_payload(html):
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("bloc __NUXT_DATA__ introuvable dans la page")
    table = json.loads(m.group(1))
    memo = {}

    def resoudre(i):
        if i in memo:
            return memo[i]
        v = table[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in WRAPPERS:
                out = resoudre(v[1]) if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] == "Set":
                out = [resoudre(x) for x in v[1:]]
            elif v and isinstance(v[0], str) and v[0] == "Date":
                out = v[1]
            else:
                out = [resoudre(x) if isinstance(x, int) and not isinstance(x, bool) else x for x in v]
        elif isinstance(v, dict):
            out = {k: resoudre(x) for k, x in v.items()}
        else:
            out = v
        memo[i] = out
        return out

    return resoudre(0)


def blocs(payload):
    """Liste des blocs de données de la page (les clés changent, on cherche par contenu)."""
    return list((payload.get("data") or {}).values())


def trouver(payload, *cles):
    for b in blocs(payload):
        if isinstance(b, dict) and all(c in b for c in cles):
            return b
    raise ValueError(f"bloc de données avec {cles} introuvable")


def texte_visible(html):
    t = re.sub(r"<style.*?</style>|<script.*?</script>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

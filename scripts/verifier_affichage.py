"""Test d'affichage avant publication : pas de défilement horizontal à 380 px ni en grand écran,
navigation burger fonctionnelle, sections présentes. Usage : python scripts/verifier_affichage.py fichier.html [dossier_captures]"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

SECTIONS = ["bref", "armees", "prep", "fd", "perf", "emerge"]


def main():
    page_html = pathlib.Path(sys.argv[1]).resolve()
    captures = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch()
        for largeur, hauteur, theme in [(380, 800, "light"), (380, 800, "dark"), (1280, 900, "light")]:
            pg = nav.new_page(viewport={"width": largeur, "height": hauteur}, color_scheme=theme)
            pg.goto(page_html.as_uri())
            pg.wait_for_timeout(500)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            if sw > largeur:
                trop = pg.evaluate(f"""[...document.querySelectorAll('body *')]
                    .filter(e=>e.getBoundingClientRect().right>{largeur}+1).slice(0,5)
                    .map(e=>e.tagName+'.'+e.className)""")
                erreurs.append(f"{largeur}px : défilement horizontal ({sw}px), éléments : {trop}")
            deborde = pg.evaluate("""[...document.querySelectorAll('.army,.fdcard,.em,.take,.note')].flatMap(c=>{
                const r=c.getBoundingClientRect();
                return [...c.querySelectorAll('*')].filter(e=>{const q=e.getBoundingClientRect();
                  return q.width>0 && q.right>r.right+0.5 && !e.closest('.tscroll')}).slice(0,1)
                  .map(e=>c.className+' > '+e.tagName+'.'+e.className)})""")
            if deborde:
                erreurs.append(f"{largeur}px : contenu qui dépasse de sa carte : {deborde[:5]}")
            for s in SECTIONS:
                if not pg.query_selector(f"#{s}"):
                    erreurs.append(f"section #{s} absente")
            if largeur == 380 and theme == "light":
                pg.evaluate("window.scrollTo(0, 2500)")
                pg.wait_for_timeout(400)
                if not pg.evaluate("document.getElementById('nav').classList.contains('collapsed')"):
                    erreurs.append("la navigation ne se replie pas au défilement")
                pg.click("#burger")
                if not pg.evaluate("document.getElementById('nav').classList.contains('open')"):
                    erreurs.append("le burger n'ouvre pas la liste des sections")
                pg.keyboard.press("Escape")
                if pg.evaluate("document.getElementById('nav').classList.contains('open')"):
                    erreurs.append("Échap ne referme pas le menu")
                pg.evaluate("window.scrollTo(0, 0)")
            if captures:
                captures.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(captures / f"page-{largeur}-{theme}.png"), full_page=True)
            pg.close()
        nav.close()
    if erreurs:
        print("ÉCHEC DU TEST D'AFFICHAGE :\n- " + "\n- ".join(erreurs), file=sys.stderr)
        sys.exit(1)
    print("Affichage OK : 380 px (clair et sombre) et 1280 px, sans défilement horizontal.")


if __name__ == "__main__":
    main()

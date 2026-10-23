"""Capturas de conferência do redesign (ADR-140, guia §13.6).

Tira foto das telas principais no computador (1440px) e no celular (390px), em Claro e em Noturno, e mais uma vez
em Compacta. Rodar antes e depois de cada mudança mostra o que mudou sem querer; a usuária compara com o canvas.

NÃO roda em produção. Aponte para um servidor local (ou de staging) com uma conta fictícia.

Como usar:
    pip install playwright
    playwright install chromium
    # suba o servidor com uma conta fictícia já criada e o quiz concluído, então:
    POLARIS_URL=http://localhost:8000 POLARIS_EMAIL=ficticia@exemplo.com POLARIS_SENHA=... \
        python design/capturas.py

As imagens vão para design/capturas/<tela>__<largura>__<tema>[__compacta].png.
O tema e a densidade são forçados no navegador (data-bs-theme / data-densidade + prefers-color-scheme), então não
é preciso mexer na conta para alternar.
"""

import os
import pathlib

from playwright.sync_api import sync_playwright

URL = os.environ.get("POLARIS_URL", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("POLARIS_EMAIL", "ficticia@exemplo.com")
SENHA = os.environ.get("POLARIS_SENHA", "")

SAIDA = pathlib.Path(__file__).parent / "capturas"
SAIDA.mkdir(exist_ok=True)

# As telas principais. (nome do arquivo, caminho.) As de dentro da ficha e os painéis laterais entram quando as
# etapas que os desenham ficarem prontas.
TELAS = [
    ("painel", "/"),
    ("agenda", "/agenda/"),
    ("meus-horarios", "/agenda/horarios/"),
    ("pacientes", "/pacientes/"),
    ("prontuarios", "/prontuarios/"),
    ("financeiro", "/financeiro/"),
    ("vitrine", "/vitrine/"),
]

LARGURAS = {"1440": 1440, "390": 390}
TEMAS = ("claro", "noturno")


def _forcar_aparencia(context, tema: str, compacta: bool) -> None:
    """Antes de cada página, fixa o tema e a densidade no <html>, para a captura não depender da conta."""
    bs = "dark" if tema == "noturno" else "light"
    densidade = 'd.setAttribute("data-densidade","compacta");' if compacta else ""
    context.add_init_script(
        f'document.addEventListener("DOMContentLoaded",function(){{var d=document.documentElement;'
        f'd.setAttribute("data-bs-theme","{bs}");{densidade}}});')


def entrar(page) -> None:
    page.goto(f"{URL}/conta/entrar/")
    page.fill('input[name="username"]', EMAIL)
    page.fill('input[name="password"]', SENHA)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def main() -> None:
    if not SENHA:
        raise SystemExit("Defina POLARIS_SENHA (e POLARIS_EMAIL) de uma conta fictícia. NÃO use a produção.")
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for rotulo, largura in LARGURAS.items():
            for tema in TEMAS:
                for compacta in ((False, True) if tema == "claro" and largura == 1440 else (False,)):
                    context = navegador.new_context(
                        viewport={"width": largura, "height": 900},
                        color_scheme="dark" if tema == "noturno" else "light",
                        device_scale_factor=2)
                    _forcar_aparencia(context, tema, compacta)
                    page = context.new_page()
                    entrar(page)
                    sufixo = f"__{rotulo}__{tema}" + ("__compacta" if compacta else "")
                    for nome, caminho in TELAS:
                        page.goto(f"{URL}{caminho}")
                        page.wait_for_load_state("networkidle")
                        page.screenshot(path=str(SAIDA / f"{nome}{sufixo}.png"), full_page=True)
                        print("ok", nome, sufixo)
                    context.close()
        navegador.close()


if __name__ == "__main__":
    main()

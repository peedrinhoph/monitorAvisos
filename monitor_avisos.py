"""
Monitor de Avisos v2 - verifica periodicamente páginas web e notifica quando
aparecem itens novos (ou quando itens existentes são alterados).

Requisitos:  pip install -r requirements.txt
Execução:    python monitor_avisos.py   (ou pythonw / .pyw para não abrir console)
Opcional:    pip install playwright && python -m playwright install chromium
             (apenas para sites marcados com "Renderizar com navegador")
"""
import csv
import hashlib
import json
import logging
import mimetypes
import os
import queue
import re
import sys
import threading
import time
import unicodedata
import uuid
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler
from urllib.parse import unquote, urljoin, urlparse

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import requests
import urllib3
from bs4 import BeautifulSoup

try:
    from plyer import notification
except ImportError:
    notification = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None

# --------------------------------------------------------------------------- #
# Caminhos, log e constantes
# --------------------------------------------------------------------------- #
if getattr(sys, "frozen", False):          # executável gerado com PyInstaller
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(BASE, "config.json")
ARQ_ESTADO = os.path.join(BASE, "estado.json")
ARQ_LOG = os.path.join(BASE, "monitor.log")

log = logging.getLogger("monitor")
log.setLevel(logging.INFO)
try:
    _h = RotatingFileHandler(ARQ_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)
except OSError:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
LIMITE_FALHAS = 3          # falhas seguidas antes de alertar
MAX_HISTORICO = 500
MAX_VISTOS = 5000

SITE_PADRAO = {
    "nome": "", "url": "", "seletor": "a", "filtro_href": "",
    "verificar_ssl": True, "intervalo_min": 0, "detectar_alteracoes": False,
    "baixar_arquivos": False, "usar_navegador": False,
}

CONFIG_PADRAO = {
    "intervalo_min": 30,
    "palavras_chave": [],
    "pasta_downloads": "",
    "aviso_bandeja_mostrado": False,
    "sites": [
        {"nome": "NFC-e SVRS - Avisos", "url": "https://dfe-portal.svrs.rs.gov.br/Nfce/Avisos",
         "seletor": "article"},
        {"nome": "NF-e SVRS - Avisos", "url": "https://dfe-portal.svrs.rs.gov.br/Nfe/Avisos",
         "seletor": "article"},
        {"nome": "NF-e - Notas Técnicas",
         "url": "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY=",
         "filtro_href": "exibirArquivo", "verificar_ssl": False, "baixar_arquivos": True},
        {"nome": "Schemas XML",
         "url": "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=BMPFMBoln3w=",
         "filtro_href": "exibirArquivo", "verificar_ssl": False},
        {"nome": "NFS-e - Notícias", "url": "https://www.gov.br/nfse/pt-br/noticias",
         "filtro_href": r"/nfse/pt-br/noticias/[^?#]+"},
        {"nome": "Documentação técnica - RTC",
         "url": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc",
         "filtro_href": r"/nfse/pt-br/[^?#]+"},
        {"nome": "Tecnospeed", "url": "https://blog.tecnospeed.com.br/category/documentos-fiscais/",
         "seletor": "article"},
    ],
}


# --------------------------------------------------------------------------- #
# Utilitários
# --------------------------------------------------------------------------- #
def carregar_json(caminho, padrao):
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.exception("Falha ao ler %s", caminho)
    return json.loads(json.dumps(padrao))


def salvar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def completar_site(site):
    return {**SITE_PADRAO, **site}


def normalizar(texto):
    """Minúsculas e sem acentos, para buscas e palavras-chave."""
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def encontrar_palavras(texto, palavras):
    t = normalizar(texto)
    return [p for p in palavras if p and normalizar(p) in t]


def data_txt(ts=None):
    return datetime.fromtimestamp(ts or time.time()).strftime("%d/%m/%Y %H:%M")


def nome_seguro(texto):
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", texto or "").strip(" ._")[:120] or "arquivo"


def abrir_no_sistema(caminho):
    if hasattr(os, "startfile"):
        os.startfile(caminho)
    else:
        webbrowser.open("file://" + os.path.abspath(caminho))


# --------------------------------------------------------------------------- #
# Coleta
# --------------------------------------------------------------------------- #
def requisitar(url, verificar_ssl=True, tentativas=3):
    """GET com retentativa e espera crescente (5s, 15s) para falhas temporárias."""
    if not verificar_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    ultimo_erro = None
    for t in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30, verify=verificar_ssl)
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError:
            raise                                   # não adianta repetir
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code < 500:
                raise                               # 4xx: erro definitivo
            ultimo_erro = e
        except (requests.ConnectionError, requests.Timeout) as e:
            ultimo_erro = e
        if t < tentativas - 1:
            espera = 5 * 3 ** t
            log.warning("Falha em %s (%s). Nova tentativa em %ss", url, ultimo_erro, espera)
            time.sleep(espera)
    raise ultimo_erro


def renderizar(url, verificar_ssl=True):
    """Abre a página num Chromium (Playwright) para sites que montam o conteúdo via JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright não instalado: pip install playwright && "
                           "python -m playwright install chromium")
    with sync_playwright() as p:
        nav = p.chromium.launch()
        try:
            pag = nav.new_page(ignore_https_errors=not verificar_ssl, user_agent=UA)
            pag.goto(url, wait_until="networkidle", timeout=60000)
            return pag.content(), pag.url
        finally:
            nav.close()


def extrair_itens(html, url_base, site):
    """Retorna {chave: {"texto", "link", "hash"}} com os itens encontrados na página."""
    soup = BeautifulSoup(html, "html.parser")
    filtro = re.compile(site["filtro_href"], re.I) if site.get("filtro_href") else None
    itens = {}
    for el in soup.select(site.get("seletor") or "a"):
        a = el if el.name == "a" else el.find("a", href=True)
        texto = " ".join(el.get_text(" ", strip=True).split())
        href = (a.get("href") or "").strip() if a else ""
        if href.lower().startswith(("javascript:", "#", "mailto:")):
            href = ""
        link = urljoin(url_base, href) if href else ""
        if filtro and not filtro.search(link or texto):
            continue
        if not texto and not link:
            continue
        chave = link or texto[:250]
        if chave in itens and itens[chave]["texto"] != itens[chave]["link"]:
            continue                                 # já tem versão com texto
        itens[chave] = {
            "texto": texto[:250] or link,
            "link": link or url_base,
            "hash": hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16],
        }
    return itens


def coletar(site):
    if site.get("usar_navegador"):
        html, final = renderizar(site["url"], site.get("verificar_ssl", True))
    else:
        r = requisitar(site["url"], site.get("verificar_ssl", True))
        html, final = r.content, r.url
    return extrair_itens(html, final, site)


def baixar_arquivo(site, item, pasta):
    """Baixa o arquivo do link do item (PDF, ZIP, XSD...). Ignora links que são páginas HTML."""
    link = item.get("link")
    if not link or link == site["url"]:
        return None
    r = requisitar(link, site.get("verificar_ssl", True), tentativas=2)
    tipo = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if tipo in ("text/html", "application/xhtml+xml") or not r.content:
        return None
    nome = ""
    cd = r.headers.get("Content-Disposition", "")
    m = (re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", cd, re.I)
         or re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I))
    if m:
        nome = unquote(m.group(1).strip().strip('"'))
    if not nome:
        nome = unquote(os.path.basename(urlparse(r.url).path))
    base, ext = os.path.splitext(nome_seguro(nome))
    if not ext or ext.lower() in (".aspx", ".asp", ".php", ".jsp", ".do"):
        ext = mimetypes.guess_extension(tipo) or ".bin"
    destino_dir = os.path.join(pasta, nome_seguro(site["nome"]))
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, f"{datetime.now():%Y%m%d_%H%M}_{base}{ext}")
    with open(destino, "wb") as f:
        f.write(r.content)
    log.info("Arquivo baixado: %s", destino)
    return destino


# --------------------------------------------------------------------------- #
# Diálogos
# --------------------------------------------------------------------------- #
class DialogoSite(tk.Toplevel):
    CAMPOS = [("nome", "Nome"), ("url", "URL"), ("seletor", "Seletor CSS"),
              ("filtro_href", "Filtro (regex no link)")]
    OPCOES = [("verificar_ssl", "Verificar certificado SSL"),
              ("detectar_alteracoes", "Avisar quando um item existente for alterado"),
              ("baixar_arquivos", "Baixar automaticamente arquivos (PDF, ZIP, XSD...) dos itens novos"),
              ("usar_navegador", "Renderizar com navegador (páginas com JavaScript, requer Playwright)")]

    def __init__(self, master, site=None):
        super().__init__(master)
        self.title("Site monitorado")
        self.transient(master)
        self.resultado = None
        self.fila_teste = queue.Queue()
        site = completar_site(site or {})

        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        self.vars = {}
        linha = 0
        for chave, rotulo in self.CAMPOS:
            ttk.Label(frm, text=rotulo).grid(row=linha, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=site.get(chave, ""))
            self.vars[chave] = v
            ttk.Entry(frm, textvariable=v, width=80).grid(row=linha, column=1, sticky="ew", pady=3)
            linha += 1

        ttk.Label(frm, text="Intervalo (min)").grid(row=linha, column=0, sticky="w", pady=3)
        fi = ttk.Frame(frm)
        fi.grid(row=linha, column=1, sticky="w")
        self.intervalo = tk.StringVar(value=str(site.get("intervalo_min") or ""))
        ttk.Entry(fi, textvariable=self.intervalo, width=8).pack(side="left")
        ttk.Label(fi, text="  vazio = usa o intervalo padrão", foreground="gray").pack(side="left")
        linha += 1

        self.bools = {}
        for chave, rotulo in self.OPCOES:
            v = tk.BooleanVar(value=bool(site.get(chave)))
            self.bools[chave] = v
            ttk.Checkbutton(frm, text=rotulo, variable=v).grid(row=linha, column=1, sticky="w")
            linha += 1

        ttk.Label(frm, foreground="gray", justify="left",
                  text="Seletor 'a' = todos os links; 'article' = cada bloco de notícia. "
                       "Use o filtro para ignorar menus/rodapé.\n"
                       "Detectar alterações pode gerar falsos avisos em páginas com datas relativas "
                       "('há 2 dias') ou contadores."
                  ).grid(row=linha, column=1, sticky="w", pady=(4, 6))
        linha += 1

        botoes = ttk.Frame(frm)
        botoes.grid(row=linha, column=1, sticky="ew")
        self.btn_testar = ttk.Button(botoes, text="Testar", command=self.testar)
        self.btn_testar.pack(side="left")
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text="OK", command=self.ok).pack(side="right", padx=4)
        linha += 1

        ft = ttk.Frame(frm)
        ft.grid(row=linha, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        frm.rowconfigure(linha, weight=1)
        self.txt = tk.Text(ft, height=14, wrap="word", state="disabled")
        sb = ttk.Scrollbar(ft, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.mostrar("Clique em 'Testar' para ver os itens que o seletor e o filtro encontram.")

        self.grab_set()
        self.wait_window()

    def mostrar(self, texto):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", texto)
        self.txt.configure(state="disabled")

    def coletar_campos(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        if not d["nome"] or not d["url"].lower().startswith("http"):
            messagebox.showwarning("Atenção", "Informe nome e uma URL http(s).", parent=self)
            return None
        if d["filtro_href"]:
            try:
                re.compile(d["filtro_href"])
            except re.error as e:
                messagebox.showwarning("Atenção", f"Regex inválida: {e}", parent=self)
                return None
        try:
            d["intervalo_min"] = max(0, int(self.intervalo.get().strip() or 0))
        except ValueError:
            messagebox.showwarning("Atenção", "Intervalo deve ser um número inteiro.", parent=self)
            return None
        d["seletor"] = d["seletor"] or "a"
        d.update({k: v.get() for k, v in self.bools.items()})
        return completar_site(d)

    def testar(self):
        d = self.coletar_campos()
        if not d:
            return
        self.btn_testar.state(["disabled"])
        self.mostrar("Testando...")
        threading.Thread(target=self._testar_thread, args=(d,), daemon=True).start()
        self.after(200, self._aguardar_teste)

    def _testar_thread(self, site):
        try:
            itens = coletar(site)
            if not itens:
                self.fila_teste.put("Nenhum item encontrado. Revise o seletor ou o filtro.")
                return
            linhas = [f"{len(itens)} item(ns) encontrado(s):", ""]
            for v in list(itens.values())[:150]:
                linhas.append(f"• {v['texto'][:160]}\n    {v['link']}")
            if len(itens) > 150:
                linhas.append(f"... e mais {len(itens) - 150}")
            self.fila_teste.put("\n".join(linhas))
        except Exception as e:
            self.fila_teste.put(f"ERRO: {e}")

    def _aguardar_teste(self):
        try:
            try:
                texto = self.fila_teste.get_nowait()
            except queue.Empty:
                self.after(200, self._aguardar_teste)
                return
            self.mostrar(texto)
            self.btn_testar.state(["!disabled"])
        except tk.TclError:
            pass                                     # diálogo fechado durante o teste

    def ok(self):
        d = self.coletar_campos()
        if d:
            self.resultado = d
            self.destroy()


class DialogoPalavras(tk.Toplevel):
    def __init__(self, master, palavras):
        super().__init__(master)
        self.title("Palavras-chave prioritárias")
        self.transient(master)
        self.resultado = None
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, justify="left",
                  text="Uma palavra ou expressão por linha (não diferencia maiúsculas nem acentos).\n"
                       "Itens que contêm alguma delas ficam em destaque e geram notificação prioritária."
                  ).pack(anchor="w")
        self.txt = tk.Text(frm, width=60, height=15)
        self.txt.pack(fill="both", expand=True, pady=6)
        self.txt.insert("1.0", "\n".join(palavras))
        b = ttk.Frame(frm)
        b.pack(fill="x")
        ttk.Button(b, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self.ok).pack(side="right", padx=4)
        self.grab_set()
        self.wait_window()

    def ok(self):
        linhas = [l.strip() for l in self.txt.get("1.0", "end").splitlines()]
        self.resultado = list(dict.fromkeys(l for l in linhas if l))
        self.destroy()


# --------------------------------------------------------------------------- #
# Aplicação
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root):
        self.root = root
        self.config = carregar_json(ARQ_CONFIG, CONFIG_PADRAO)
        for k, v in CONFIG_PADRAO.items():
            if k != "sites":
                self.config.setdefault(k, v)
        self.config["sites"] = [completar_site(s) for s in self.config.get("sites", [])]
        self.estado = carregar_json(ARQ_ESTADO, {"vistos": {}, "historico": []})
        self.migrar_estado()
        self.salvar_config()

        self.fila = queue.Queue()
        self.acordar = threading.Event()
        self.trava_verif = threading.Lock()
        self.trava_estado = threading.RLock()
        self.trava_pend = threading.Lock()
        self.pendentes = set()
        self.proximo = {}
        self.falhas = {}
        self.cache_status = {}       # url -> {"status", "ultima", "proxima"}
        self.tray = None
        self.saindo = False

        self.montar_ui()
        self.recarregar_sites()
        self.recarregar_historico()
        self.iniciar_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        threading.Thread(target=self.loop, daemon=True).start()
        self.root.after(500, self.processar_fila)
        log.info("Monitor iniciado com %d site(s)", len(self.config["sites"]))

    # ---------------- Dados ----------------
    def migrar_estado(self):
        self.estado.setdefault("vistos", {})
        self.estado.setdefault("historico", [])
        for url, v in list(self.estado["vistos"].items()):
            if isinstance(v, list):                  # formato da v1: lista de chaves
                self.estado["vistos"][url] = {k: None for k in v}
        for reg in self.estado["historico"]:
            reg.setdefault("id", uuid.uuid4().hex)
            reg.setdefault("lido", True)
            reg.setdefault("tipo", "Novo")
            reg.setdefault("prioridade", False)
            reg.setdefault("arquivo", "")

    def salvar_config(self):
        salvar_json(ARQ_CONFIG, self.config)

    def salvar_estado(self):
        with self.trava_estado:
            salvar_json(ARQ_ESTADO, self.estado)

    def pasta_downloads(self):
        return self.config.get("pasta_downloads") or os.path.join(BASE, "downloads")

    def intervalo_site(self, site):
        return int(site.get("intervalo_min") or 0) or max(1, int(self.config.get("intervalo_min", 30)))

    def reg_por_id(self, iid):
        return next((r for r in self.estado["historico"] if r["id"] == iid), None)

    # ---------------- UI ----------------
    def montar_ui(self):
        self.root.title("Monitor de Avisos")
        self.root.geometry("1150x700")
        self.fonte_negrito = tkfont.nametofont("TkDefaultFont").copy()
        self.fonte_negrito.configure(weight="bold")

        topo = ttk.Frame(self.root, padding=6)
        topo.pack(fill="x")
        ttk.Label(topo, text="Intervalo padrão (min):").pack(side="left")
        self.intervalo = tk.StringVar(value=str(self.config.get("intervalo_min", 30)))
        sp = ttk.Spinbox(topo, from_=1, to=1440, width=6, textvariable=self.intervalo,
                         command=self.mudar_intervalo)
        sp.pack(side="left", padx=(2, 12))
        sp.bind("<FocusOut>", lambda e: self.mudar_intervalo())
        sp.bind("<Return>", lambda e: self.mudar_intervalo())
        for texto, cmd in [("Verificar todos", lambda: self.verificar_agora()),
                           ("Verificar selecionado", self.verificar_selecionado),
                           ("Adicionar site", self.adicionar),
                           ("Editar", self.editar),
                           ("Remover", self.remover),
                           ("Palavras-chave", self.editar_palavras),
                           ("Pasta de downloads", self.escolher_pasta)]:
            ttk.Button(topo, text=texto, command=cmd).pack(side="left", padx=2)

        painel = ttk.PanedWindow(self.root, orient="vertical")
        painel.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Sites
        f1 = ttk.Labelframe(painel, text="Sites monitorados", padding=4)
        cols = [("nome", "Nome", 220), ("intervalo", "Intervalo", 100), ("status", "Status", 470),
                ("ultima", "Última verificação", 120), ("proxima", "Próxima", 120)]
        self.tree_sites = ttk.Treeview(f1, columns=[c[0] for c in cols], show="headings", height=7)
        for col, tit, larg in cols:
            self.tree_sites.heading(col, text=tit)
            self.tree_sites.column(col, width=larg, anchor="w")
        self.tree_sites.tag_configure("erro", foreground="#c62828")
        self.tree_sites.pack(fill="both", expand=True)
        self.tree_sites.bind("<Double-1>", lambda e: self.editar())
        painel.add(f1, weight=1)

        # Novidades
        f2 = ttk.Labelframe(painel, text="Novidades (duplo clique abre o link, botão direito para mais opções)",
                            padding=4)
        barra = ttk.Frame(f2)
        barra.pack(fill="x", pady=(0, 4))
        ttk.Label(barra, text="Buscar:").pack(side="left")
        self.busca = tk.StringVar()
        self.busca.trace_add("write", lambda *a: self.recarregar_historico())
        ttk.Entry(barra, textvariable=self.busca, width=30).pack(side="left", padx=(2, 8))
        self.so_nao_lidas = tk.BooleanVar(value=False)
        ttk.Checkbutton(barra, text="Só não lidas", variable=self.so_nao_lidas,
                        command=self.recarregar_historico).pack(side="left", padx=(0, 8))
        for texto, cmd in [("Marcar todas como lidas", self.marcar_todas_lidas),
                           ("Exportar CSV", self.exportar_csv),
                           ("Abrir downloads", self.abrir_downloads),
                           ("Limpar histórico", self.limpar_historico)]:
            ttk.Button(barra, text=texto, command=cmd).pack(side="left", padx=2)

        fl = ttk.Frame(f2)
        fl.pack(fill="both", expand=True)
        cols = [("data", "Data", 120), ("site", "Site", 190), ("tipo", "Tipo", 150), ("texto", "Item", 640)]
        self.tree_nov = ttk.Treeview(fl, columns=[c[0] for c in cols], show="headings")
        for col, tit, larg in cols:
            self.tree_nov.heading(col, text=tit)
            self.tree_nov.column(col, width=larg, anchor="w")
        self.tree_nov.tag_configure("naolido", font=self.fonte_negrito)
        self.tree_nov.tag_configure("prioridade", foreground="#c62828")
        sb = ttk.Scrollbar(fl, orient="vertical", command=self.tree_nov.yview)
        self.tree_nov.configure(yscrollcommand=sb.set)
        self.tree_nov.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_nov.bind("<Double-1>", lambda e: self.abrir_link())
        self.tree_nov.bind("<Button-3>", self.menu_contexto)
        painel.add(f2, weight=3)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Abrir link", command=self.abrir_link)
        self.menu.add_command(label="Abrir arquivo baixado", command=self.abrir_arquivo)
        self.menu.add_command(label="Copiar link", command=self.copiar_link)
        self.menu.add_separator()
        self.menu.add_command(label="Marcar como lida", command=lambda: self.marcar_lido(True))
        self.menu.add_command(label="Marcar como não lida", command=lambda: self.marcar_lido(False))

    def texto_intervalo(self, site):
        if site.get("intervalo_min"):
            return f"{site['intervalo_min']} min"
        return f"padrão ({self.intervalo_site(site)} min)"

    def recarregar_sites(self):
        self.tree_sites.delete(*self.tree_sites.get_children())
        for s in self.config["sites"]:
            c = self.cache_status.get(s["url"], {})
            status = c.get("status", "aguardando")
            self.tree_sites.insert("", "end", iid=s["url"],
                                   values=(s["nome"], self.texto_intervalo(s), status,
                                           c.get("ultima", ""), c.get("proxima", "")),
                                   tags=("erro",) if status.startswith("ERRO") else ())

    def atualizar_site(self, url, **campos):
        self.cache_status.setdefault(url, {}).update(campos)
        if self.tree_sites.exists(url):
            for k, v in campos.items():
                self.tree_sites.set(url, k, v)
            if "status" in campos:
                self.tree_sites.item(url, tags=("erro",) if campos["status"].startswith("ERRO") else ())

    def tags_reg(self, reg):
        tags = []
        if not reg["lido"]:
            tags.append("naolido")
        if reg["prioridade"]:
            tags.append("prioridade")
        return tags

    def tipo_reg(self, reg):
        t = reg["tipo"]
        if reg["prioridade"]:
            t += " · prioridade"
        if reg["arquivo"]:
            t += " · arquivo"
        return t

    def recarregar_historico(self):
        termo = normalizar(self.busca.get().strip())
        so_nl = self.so_nao_lidas.get()
        self.tree_nov.delete(*self.tree_nov.get_children())
        for reg in self.estado["historico"]:
            if so_nl and reg["lido"]:
                continue
            if termo and termo not in normalizar(f"{reg['site']} {reg['texto']}"):
                continue
            self.tree_nov.insert("", "end", iid=reg["id"], tags=self.tags_reg(reg),
                                 values=(reg["data"], reg["site"], self.tipo_reg(reg), reg["texto"]))
        self.atualizar_titulo()

    def atualizar_titulo(self):
        n = sum(1 for r in self.estado["historico"] if not r["lido"])
        titulo = "Monitor de Avisos" + (f" ({n} não lida{'s' if n > 1 else ''})" if n else "")
        self.root.title(titulo)
        if self.tray:
            try:
                self.tray.title = titulo
            except Exception:
                pass

    # ---------------- Novidades: ações ----------------
    def selecionados(self):
        return [r for r in (self.reg_por_id(i) for i in self.tree_nov.selection()) if r]

    def menu_contexto(self, evento):
        iid = self.tree_nov.identify_row(evento.y)
        if not iid:
            return
        if iid not in self.tree_nov.selection():
            self.tree_nov.selection_set(iid)
        regs = self.selecionados()
        tem_arquivo = any(r["arquivo"] and os.path.exists(r["arquivo"]) for r in regs)
        self.menu.entryconfigure("Abrir arquivo baixado", state="normal" if tem_arquivo else "disabled")
        self.menu.tk_popup(evento.x_root, evento.y_root)

    def abrir_link(self):
        regs = self.selecionados()
        for r in regs[:5]:
            webbrowser.open(r["link"])
        self.marcar_lido(True, regs)

    def abrir_arquivo(self):
        for r in self.selecionados():
            if r["arquivo"] and os.path.exists(r["arquivo"]):
                abrir_no_sistema(r["arquivo"])
                self.marcar_lido(True, [r])

    def copiar_link(self):
        regs = self.selecionados()
        if regs:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(r["link"] for r in regs))

    def marcar_lido(self, valor, regs=None):
        regs = regs if regs is not None else self.selecionados()
        with self.trava_estado:
            for r in regs:
                r["lido"] = valor
        self.salvar_estado()
        for r in regs:
            if self.tree_nov.exists(r["id"]):
                self.tree_nov.item(r["id"], tags=self.tags_reg(r))
        self.atualizar_titulo()

    def marcar_todas_lidas(self):
        self.marcar_lido(True, [r for r in self.estado["historico"] if not r["lido"]])

    def exportar_csv(self):
        regs = [r for r in (self.reg_por_id(i) for i in self.tree_nov.get_children()) if r]
        if not regs:
            messagebox.showinfo("Monitor", "Não há novidades para exportar.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"novidades_{datetime.now():%Y%m%d_%H%M}.csv")
        if not caminho:
            return
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Data", "Site", "Tipo", "Prioridade", "Item", "Link", "Arquivo", "Lido"])
            for r in regs:
                w.writerow([r["data"], r["site"], r["tipo"], "sim" if r["prioridade"] else "",
                            r["texto"], r["link"], r["arquivo"], "sim" if r["lido"] else "não"])
        messagebox.showinfo("Monitor", f"{len(regs)} registro(s) exportado(s).")

    def abrir_downloads(self):
        pasta = self.pasta_downloads()
        os.makedirs(pasta, exist_ok=True)
        abrir_no_sistema(pasta)

    def limpar_historico(self):
        if not messagebox.askyesno("Monitor", "Limpar a lista de novidades?"):
            return
        with self.trava_estado:
            self.estado["historico"] = []
        self.salvar_estado()
        self.recarregar_historico()

    # ---------------- Sites: ações ----------------
    def mudar_intervalo(self):
        try:
            self.config["intervalo_min"] = max(1, int(self.intervalo.get()))
            self.salvar_config()
            for s in self.config["sites"]:
                self.atualizar_site(s["url"], intervalo=self.texto_intervalo(s))
        except ValueError:
            self.intervalo.set(str(self.config.get("intervalo_min", 30)))

    def site_selecionado(self):
        sel = self.tree_sites.selection()
        if not sel:
            messagebox.showinfo("Monitor", "Selecione um site na lista.")
            return None
        return next((s for s in self.config["sites"] if s["url"] == sel[0]), None)

    def verificar_agora(self, urls=None):
        with self.trava_pend:
            self.pendentes.update(urls or [s["url"] for s in self.config["sites"]])
        self.acordar.set()

    def verificar_selecionado(self):
        site = self.site_selecionado()
        if site:
            self.verificar_agora([site["url"]])

    def adicionar(self):
        d = DialogoSite(self.root).resultado
        if not d:
            return
        if any(s["url"] == d["url"] for s in self.config["sites"]):
            messagebox.showwarning("Monitor", "Essa URL já está cadastrada.")
            return
        self.config["sites"].append(d)
        self.salvar_config()
        self.recarregar_sites()
        self.verificar_agora([d["url"]])

    def editar(self):
        site = self.site_selecionado()
        if not site:
            return
        d = DialogoSite(self.root, site).resultado
        if not d:
            return
        if d["url"] != site["url"] and any(s["url"] == d["url"] for s in self.config["sites"]):
            messagebox.showwarning("Monitor", "Essa URL já está cadastrada.")
            return
        regra = ("url", "seletor", "filtro_href", "usar_navegador")
        if any(d[k] != site.get(k) for k in regra):
            # regra mudou: refaz a linha de base para não gerar falsos avisos
            with self.trava_estado:
                self.estado["vistos"].pop(site["url"], None)
                self.estado["vistos"].pop(d["url"], None)
            self.salvar_estado()
        for u in (site["url"], d["url"]):
            self.proximo.pop(u, None)
            self.falhas.pop(u, None)
        self.config["sites"][self.config["sites"].index(site)] = d
        self.salvar_config()
        self.recarregar_sites()
        self.verificar_agora([d["url"]])

    def remover(self):
        site = self.site_selecionado()
        if site and messagebox.askyesno("Monitor", f"Remover '{site['nome']}'?"):
            self.config["sites"].remove(site)
            with self.trava_estado:
                self.estado["vistos"].pop(site["url"], None)
            self.salvar_estado()
            self.proximo.pop(site["url"], None)
            self.salvar_config()
            self.recarregar_sites()

    def editar_palavras(self):
        palavras = DialogoPalavras(self.root, self.config.get("palavras_chave", [])).resultado
        if palavras is None:
            return
        self.config["palavras_chave"] = palavras
        self.salvar_config()
        with self.trava_estado:                      # reavalia o histórico com as novas palavras
            for r in self.estado["historico"]:
                r["prioridade"] = bool(encontrar_palavras(r["texto"], palavras))
        self.salvar_estado()
        self.recarregar_historico()

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(initialdir=self.pasta_downloads(),
                                        title="Pasta onde os arquivos serão baixados")
        if pasta:
            self.config["pasta_downloads"] = pasta
            self.salvar_config()

    # ---------------- Verificação (thread) ----------------
    def loop(self):
        while not self.saindo:
            try:
                self.ciclo()
            except Exception:
                log.exception("Falha no ciclo de verificação")
            self.acordar.wait(20)
            self.acordar.clear()

    def ciclo(self):
        with self.trava_verif:
            with self.trava_pend:
                pendentes = set(self.pendentes)
                self.pendentes.clear()
            for site in list(self.config["sites"]):
                if self.saindo:
                    return
                url = site["url"]
                if url not in pendentes and time.time() < self.proximo.get(url, 0):
                    continue
                self.verificar_site(site)
                self.proximo[url] = time.time() + self.intervalo_site(site) * 60
                self.fila.put(("site", url, {"proxima": data_txt(self.proximo[url])}))

    def verificar_site(self, site):
        url, nome = site["url"], site["nome"]
        self.fila.put(("site", url, {"status": "verificando..."}))
        try:
            itens = coletar(site)
        except Exception as e:
            n = self.falhas.get(url, 0) + 1
            self.falhas[url] = n
            log.warning("Erro em %s (%dx): %s", nome, n, e)
            self.fila.put(("site", url, {"status": f"ERRO ({n}x): {e}"[:250], "ultima": data_txt()}))
            if n == LIMITE_FALHAS:
                self.fila.put(("alerta", f"{nome}: sem resposta",
                               f"{n} falhas seguidas. O monitor continuará tentando.\n{str(e)[:150]}"))
            return
        if self.falhas.get(url, 0) >= LIMITE_FALHAS:
            self.fila.put(("alerta", f"{nome}: voltou a responder", "O site voltou a responder normalmente."))
        self.falhas[url] = 0

        if not itens:
            self.fila.put(("site", url, {"status": "nenhum item encontrado. Revise seletor/filtro",
                                         "ultima": data_txt()}))
            return

        novos, alterados = [], []
        with self.trava_estado:
            vistos = self.estado["vistos"].get(url)
            if vistos is None:
                self.estado["vistos"][url] = {k: v["hash"] for k, v in itens.items()}
                status = f"linha de base criada ({len(itens)} itens)"
            else:
                for k, v in itens.items():
                    if k not in vistos:
                        novos.append(v)
                    elif site.get("detectar_alteracoes") and vistos[k] and vistos[k] != v["hash"]:
                        alterados.append(v)
                    vistos[k] = v["hash"]
                if len(vistos) > MAX_VISTOS:          # poda: remove os mais antigos que sumiram da página
                    for k in list(vistos):
                        if len(vistos) <= MAX_VISTOS:
                            break
                        if k not in itens:
                            del vistos[k]
                status = f"OK: {len(itens)} itens, {len(novos)} novo(s)"
                if site.get("detectar_alteracoes"):
                    status += f", {len(alterados)} alterado(s)"
            salvar_json(ARQ_ESTADO, self.estado)

        if novos and site.get("baixar_arquivos"):
            for v in novos:
                try:
                    v["arquivo"] = baixar_arquivo(site, v, self.pasta_downloads()) or ""
                except Exception as e:
                    log.warning("Falha ao baixar %s: %s", v["link"], e)
        if novos or alterados:
            log.info("%s: %d novo(s), %d alterado(s)", nome, len(novos), len(alterados))
            self.fila.put(("novidades", nome, novos, alterados))
        self.fila.put(("site", url, {"status": status, "ultima": data_txt()}))

    # ---------------- Fila -> UI (thread principal) ----------------
    def processar_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                tipo = msg[0]
                if tipo == "site":
                    self.atualizar_site(msg[1], **msg[2])
                elif tipo == "novidades":
                    self.registrar_novidades(*msg[1:])
                elif tipo == "alerta":
                    self.notificar(msg[1], msg[2])
                elif tipo == "tray":
                    if msg[1] == "mostrar":
                        self.mostrar_janela()
                    elif msg[1] == "verificar":
                        self.verificar_agora()
                    elif msg[1] == "sair":
                        self.sair()
                        return
        except queue.Empty:
            pass
        self.root.after(500, self.processar_fila)

    def registrar_novidades(self, nome, novos, alterados):
        palavras = self.config.get("palavras_chave", [])
        agora = data_txt()
        regs = []
        for tipo, lista in (("Novo", novos), ("Alterado", alterados)):
            for it in lista:
                regs.append({"id": uuid.uuid4().hex, "data": agora, "site": nome, "tipo": tipo,
                             "texto": it["texto"], "link": it["link"], "arquivo": it.get("arquivo", ""),
                             "prioridade": bool(encontrar_palavras(it["texto"], palavras)), "lido": False})
        with self.trava_estado:
            self.estado["historico"][0:0] = regs
            del self.estado["historico"][MAX_HISTORICO:]
        self.salvar_estado()
        self.recarregar_historico()

        prioritarios = [r for r in regs if r["prioridade"]]
        partes = []
        if novos:
            partes.append(f"{len(novos)} novo(s)")
        if alterados:
            partes.append(f"{len(alterados)} alterado(s)")
        titulo = ("⚠ PRIORIDADE: " if prioritarios else "") + f"{nome}: " + ", ".join(partes)
        destaque = prioritarios or regs
        corpo = "\n".join("• " + r["texto"][:80] for r in destaque[:3])
        if len(destaque) > 3:
            corpo += f"\n... e mais {len(destaque) - 3}"
        self.notificar(titulo, corpo, urgente=bool(prioritarios))

    def notificar(self, titulo, corpo, urgente=False):
        enviado = False
        if notification:
            try:
                notification.notify(title=titulo[:63], message=corpo[:250],
                                    app_name="Monitor de Avisos", timeout=15)
                enviado = True
            except Exception:
                log.exception("Falha na notificação")
        if not enviado and self.tray:
            try:
                self.tray.notify(corpo[:250], titulo[:63])
                enviado = True
            except Exception:
                pass
        self.root.bell()
        if urgente or not enviado:
            self.mostrar_janela(topo=True)

    # ---------------- Janela e bandeja ----------------
    def iniciar_tray(self):
        if not pystray:
            return
        try:
            img = Image.new("RGB", (64, 64), "#1f6feb")
            d = ImageDraw.Draw(img)
            d.ellipse((10, 10, 54, 54), fill="white")
            d.rectangle((28, 18, 36, 38), fill="#1f6feb")
            d.rectangle((28, 42, 36, 49), fill="#1f6feb")
            menu = pystray.Menu(
                pystray.MenuItem("Abrir", lambda i, it: self.fila.put(("tray", "mostrar")), default=True),
                pystray.MenuItem("Verificar agora", lambda i, it: self.fila.put(("tray", "verificar"))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", lambda i, it: self.fila.put(("tray", "sair"))),
            )
            self.tray = pystray.Icon("monitor_avisos", img, "Monitor de Avisos", menu)
            self.tray.run_detached()
        except Exception:
            log.exception("Não foi possível criar o ícone na bandeja")
            self.tray = None

    def mostrar_janela(self, topo=False):
        self.root.deiconify()
        self.root.lift()
        if topo:
            self.root.attributes("-topmost", True)
            self.root.after(1500, lambda: self.root.attributes("-topmost", False))

    def ao_fechar(self):
        if self.tray:
            self.root.withdraw()
            if not self.config.get("aviso_bandeja_mostrado"):
                self.config["aviso_bandeja_mostrado"] = True
                self.salvar_config()
                self.notificar("Monitor de Avisos", "Continua rodando na bandeja do sistema. "
                                                    "Use o ícone para abrir ou sair.")
        elif messagebox.askyesno("Monitor", "Fechar encerra o monitoramento. Deseja sair?"):
            self.sair()

    def sair(self):
        self.saindo = True
        self.acordar.set()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        log.info("Monitor encerrado")
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()

"""
Monitor de Avisos - verifica periodicamente páginas web e notifica quando
aparecem novos itens (links) nelas.

Requisitos:  pip install requests beautifulsoup4 plyer
Execução:    python monitor_avisos.py   (ou pythonw para não abrir console)
"""
import json
import os
import queue
import re
import sys
import threading
import webbrowser
from datetime import datetime
from urllib.parse import urljoin

import tkinter as tk
from tkinter import ttk, messagebox

import requests
import urllib3
from bs4 import BeautifulSoup

try:
    from plyer import notification
except ImportError:
    notification = None

if getattr(sys, "frozen", False):          # executável gerado com PyInstaller
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(BASE, "config.json")
ARQ_ESTADO = os.path.join(BASE, "estado.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CONFIG_PADRAO = {
    "intervalo_min": 30,
    "sites": [
        {
            "nome": "NFC-e SVRS - Avisos",
            "url": "https://dfe-portal.svrs.rs.gov.br/Nfce/Avisos",
            "seletor": "article",
            "filtro_href": "",
            "verificar_ssl": True,
        },
        {
            "nome": "NF-e - Notas Técnicas",
            "url": "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY=",
            "seletor": "a",
            "filtro_href": "exibirArquivo",
            "verificar_ssl": False,   # o portal costuma usar cadeia ICP-Brasil
        },
        {
            "nome": "NFS-e - Notícias",
            "url": "https://www.gov.br/nfse/pt-br/noticias",
            "seletor": "a",
            "filtro_href": r"/nfse/pt-br/noticias/[^?#]+",
            "verificar_ssl": True,
        },
    ],
}


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #
def carregar_json(caminho, padrao):
    if os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return json.loads(json.dumps(padrao))


def salvar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


# --------------------------------------------------------------------------- #
# Coleta
# --------------------------------------------------------------------------- #
def extrair_itens(html, url_base, site):
    """Retorna {chave: {"texto", "link"}} com os itens encontrados na página."""
    soup = BeautifulSoup(html, "html.parser")
    filtro = re.compile(site["filtro_href"], re.I) if site.get("filtro_href") else None
    itens = {}
    for el in soup.select(site.get("seletor") or "a"):
        a = el if el.name == "a" else el.find("a")
        texto = " ".join(el.get_text(" ", strip=True).split())[:250]
        href = (a.get("href") or "").strip() if a else ""
        if href.lower().startswith(("javascript:", "#", "mailto:")):
            href = ""
        link = urljoin(url_base, href) if href else ""
        if filtro and not filtro.search(link or texto):
            continue
        if not texto and not link:
            continue
        chave = link or texto
        if chave not in itens or (texto and not itens[chave]["texto"]):
            itens[chave] = {"texto": texto or link, "link": link or url_base}
    return itens


def coletar(site):
    verificar = site.get("verificar_ssl", True)
    if not verificar:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.get(site["url"], headers={"User-Agent": UA},
                     timeout=30, verify=verificar)
    r.raise_for_status()
    return extrair_itens(r.content, r.url, site)


# --------------------------------------------------------------------------- #
# Diálogo de cadastro de site
# --------------------------------------------------------------------------- #
class DialogoSite(tk.Toplevel):
    CAMPOS = [("nome", "Nome"), ("url", "URL"),
              ("seletor", "Seletor CSS"), ("filtro_href", "Filtro (regex no link)")]

    def __init__(self, master, site=None):
        super().__init__(master)
        self.title("Site monitorado")
        self.resizable(False, False)
        self.transient(master)
        self.resultado = None
        site = site or {"nome": "", "url": "", "seletor": "a",
                        "filtro_href": "", "verificar_ssl": True}
        self.vars = {}
        for i, (chave, rotulo) in enumerate(self.CAMPOS):
            ttk.Label(self, text=rotulo).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=site.get(chave, ""))
            self.vars[chave] = v
            ttk.Entry(self, textvariable=v, width=75).grid(row=i, column=1, padx=8, pady=4)
        self.ssl = tk.BooleanVar(value=site.get("verificar_ssl", True))
        ttk.Checkbutton(self, text="Verificar certificado SSL",
                        variable=self.ssl).grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(self, foreground="gray",
                  text="Seletor 'a' = todos os links. Use o filtro para ignorar menus/rodapé."
                  ).grid(row=5, column=1, sticky="w", padx=8)
        botoes = ttk.Frame(self)
        botoes.grid(row=6, column=1, sticky="e", padx=8, pady=8)
        ttk.Button(botoes, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="left")
        self.grab_set()
        self.wait_window()

    def ok(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        if not d["nome"] or not d["url"].lower().startswith("http"):
            messagebox.showwarning("Atenção", "Informe nome e uma URL http(s).", parent=self)
            return
        if d["filtro_href"]:
            try:
                re.compile(d["filtro_href"])
            except re.error as e:
                messagebox.showwarning("Atenção", f"Regex inválida: {e}", parent=self)
                return
        d["seletor"] = d["seletor"] or "a"
        d["verificar_ssl"] = self.ssl.get()
        self.resultado = d
        self.destroy()


# --------------------------------------------------------------------------- #
# Aplicação
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root):
        self.root = root
        self.config = carregar_json(ARQ_CONFIG, CONFIG_PADRAO)
        self.estado = carregar_json(ARQ_ESTADO, {"vistos": {}, "historico": []})
        salvar_json(ARQ_CONFIG, self.config)

        self.fila = queue.Queue()
        self.acordar = threading.Event()
        self.trava_verif = threading.Lock()
        self.trava_estado = threading.Lock()
        self.links = {}

        self.montar_ui()
        self.recarregar_sites()
        for reg in self.estado.get("historico", []):
            self.inserir_novidade(reg, no_topo=False)

        threading.Thread(target=self.loop, daemon=True).start()
        self.root.after(500, self.processar_fila)

    # ---------------- UI ----------------
    def montar_ui(self):
        self.root.title("Monitor de Avisos")
        self.root.geometry("1000x620")

        topo = ttk.Frame(self.root, padding=6)
        topo.pack(fill="x")
        ttk.Label(topo, text="Intervalo (min):").pack(side="left")
        self.intervalo = tk.StringVar(value=str(self.config.get("intervalo_min", 30)))
        sp = ttk.Spinbox(topo, from_=1, to=1440, width=6, textvariable=self.intervalo,
                         command=self.mudar_intervalo)
        sp.pack(side="left", padx=(2, 12))
        sp.bind("<FocusOut>", lambda e: self.mudar_intervalo())
        for texto, cmd in [("Verificar agora", self.acordar.set),
                           ("Adicionar site", self.adicionar),
                           ("Editar", self.editar),
                           ("Remover", self.remover),
                           ("Limpar histórico", self.limpar_historico)]:
            ttk.Button(topo, text=texto, command=cmd).pack(side="left", padx=2)

        painel = ttk.PanedWindow(self.root, orient="vertical")
        painel.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        f1 = ttk.Labelframe(painel, text="Sites monitorados", padding=4)
        self.tree_sites = ttk.Treeview(f1, columns=("nome", "status", "ultima"),
                                       show="headings", height=6)
        for col, tit, larg in [("nome", "Nome", 220), ("status", "Status", 560),
                               ("ultima", "Última verificação", 140)]:
            self.tree_sites.heading(col, text=tit)
            self.tree_sites.column(col, width=larg, anchor="w")
        self.tree_sites.pack(fill="both", expand=True)
        self.tree_sites.bind("<Double-1>", lambda e: self.editar())
        painel.add(f1, weight=1)

        f2 = ttk.Labelframe(painel, text="Novidades (duplo clique abre o link)", padding=4)
        self.tree_nov = ttk.Treeview(f2, columns=("data", "site", "texto"), show="headings")
        for col, tit, larg in [("data", "Data", 130), ("site", "Site", 200),
                               ("texto", "Item", 620)]:
            self.tree_nov.heading(col, text=tit)
            self.tree_nov.column(col, width=larg, anchor="w")
        sb = ttk.Scrollbar(f2, orient="vertical", command=self.tree_nov.yview)
        self.tree_nov.configure(yscrollcommand=sb.set)
        self.tree_nov.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_nov.bind("<Double-1>", self.abrir_link)
        painel.add(f2, weight=3)

    def recarregar_sites(self):
        self.tree_sites.delete(*self.tree_sites.get_children())
        for s in self.config["sites"]:
            self.tree_sites.insert("", "end", iid=s["url"], values=(s["nome"], "aguardando", ""))

    def inserir_novidade(self, reg, no_topo=True):
        iid = self.tree_nov.insert("", 0 if no_topo else "end",
                                   values=(reg["data"], reg["site"], reg["texto"]))
        self.links[iid] = reg["link"]

    def abrir_link(self, _evento):
        sel = self.tree_nov.selection()
        if sel and self.links.get(sel[0]):
            webbrowser.open(self.links[sel[0]])

    # ---------------- Ações ----------------
    def salvar_config(self):
        salvar_json(ARQ_CONFIG, self.config)

    def mudar_intervalo(self):
        try:
            self.config["intervalo_min"] = max(1, int(self.intervalo.get()))
            self.salvar_config()
        except ValueError:
            self.intervalo.set(str(self.config.get("intervalo_min", 30)))

    def site_selecionado(self):
        sel = self.tree_sites.selection()
        if not sel:
            messagebox.showinfo("Monitor", "Selecione um site na lista.")
            return None
        return next((s for s in self.config["sites"] if s["url"] == sel[0]), None)

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
        self.acordar.set()

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
        mudou_regra = any(d[k] != site.get(k) for k in ("url", "seletor", "filtro_href"))
        idx = self.config["sites"].index(site)
        self.config["sites"][idx] = d
        if mudou_regra:   # regra mudou: refaz a linha de base para não gerar falsos avisos
            with self.trava_estado:
                self.estado["vistos"].pop(site["url"], None)
                self.estado["vistos"].pop(d["url"], None)
                salvar_json(ARQ_ESTADO, self.estado)
        self.salvar_config()
        self.recarregar_sites()
        self.acordar.set()

    def remover(self):
        site = self.site_selecionado()
        if site and messagebox.askyesno("Monitor", f"Remover '{site['nome']}'?"):
            self.config["sites"].remove(site)
            with self.trava_estado:
                self.estado["vistos"].pop(site["url"], None)
                salvar_json(ARQ_ESTADO, self.estado)
            self.salvar_config()
            self.recarregar_sites()

    def limpar_historico(self):
        if not messagebox.askyesno("Monitor", "Limpar a lista de novidades?"):
            return
        with self.trava_estado:
            self.estado["historico"] = []
            salvar_json(ARQ_ESTADO, self.estado)
        self.tree_nov.delete(*self.tree_nov.get_children())
        self.links.clear()

    # ---------------- Verificação (thread) ----------------
    def loop(self):
        while True:
            self.verificar_todos()
            minutos = max(1, int(self.config.get("intervalo_min", 30)))
            self.acordar.wait(minutos * 60)
            self.acordar.clear()

    def verificar_todos(self):
        with self.trava_verif:
            for site in list(self.config["sites"]):
                url = site["url"]
                self.fila.put(("status", url, "verificando...", None))
                agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                try:
                    itens = coletar(site)
                except Exception as e:
                    self.fila.put(("status", url, f"ERRO: {e}"[:200], agora))
                    continue
                if not itens:
                    self.fila.put(("status", url,
                                   "nenhum item encontrado — revise seletor/filtro", agora))
                    continue
                novos = []
                with self.trava_estado:
                    vistos = self.estado["vistos"].get(url)
                    if vistos is None:
                        self.estado["vistos"][url] = list(itens)
                        status = f"linha de base criada ({len(itens)} itens)"
                    else:
                        conhecidos = set(vistos)
                        novos = [v for k, v in itens.items() if k not in conhecidos]
                        vistos.extend(k for k in itens if k not in conhecidos)
                        self.estado["vistos"][url] = vistos[-5000:]
                        status = f"OK — {len(itens)} itens, {len(novos)} novo(s)"
                    salvar_json(ARQ_ESTADO, self.estado)
                if novos:
                    self.fila.put(("novos", site, novos))
                self.fila.put(("status", url, status, agora))

    # ---------------- Fila -> UI (thread principal) ----------------
    def processar_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                if msg[0] == "status":
                    _, url, texto, quando = msg
                    if self.tree_sites.exists(url):
                        self.tree_sites.set(url, "status", texto)
                        if quando:
                            self.tree_sites.set(url, "ultima", quando)
                elif msg[0] == "novos":
                    _, site, itens = msg
                    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    with self.trava_estado:
                        for it in reversed(itens):
                            reg = {"data": agora, "site": site["nome"],
                                   "texto": it["texto"], "link": it["link"]}
                            self.estado["historico"].insert(0, reg)
                            self.inserir_novidade(reg)
                        del self.estado["historico"][500:]
                        salvar_json(ARQ_ESTADO, self.estado)
                    self.notificar(site["nome"], itens)
        except queue.Empty:
            pass
        self.root.after(500, self.processar_fila)

    def notificar(self, nome, itens):
        titulo = f"{nome}: {len(itens)} novidade(s)"
        corpo = "\n".join("• " + i["texto"][:80] for i in itens[:3])
        if len(itens) > 3:
            corpo += f"\n... e mais {len(itens) - 3}"
        enviado = False
        if notification:
            try:
                notification.notify(title=titulo[:63], message=corpo[:250],
                                    app_name="Monitor de Avisos", timeout=15)
                enviado = True
            except Exception:
                pass
        self.root.bell()
        if not enviado:   # sem plyer: traz a janela para frente
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(1500, lambda: self.root.attributes("-topmost", False))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()

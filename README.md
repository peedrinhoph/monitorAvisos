# Monitor de Avisos

Programa desktop (Python + Tkinter) que monitora páginas web periodicamente e envia uma notificação do Windows sempre que aparece um item novo.
Desenvolvido para automatizar o acompanhamento de atualizações técnicas e avisos por parte do SEFAZ, por exemplo: Nota técnica, Avisos ou atualizações de schemas XML. Opcionalmente, também é possível configurar para avisar quando um tópico existente é alterado.

**Tela Principal**

<img width="1918" height="823" alt="image" src="https://github.com/user-attachments/assets/44618774-66cc-429b-a5a4-b14966ce8528" />


**Configuração do Site**

<img width="679" height="569" alt="image" src="https://github.com/user-attachments/assets/ac29fff7-d248-4967-983d-71467c7b21db" />

**Configuração de Palavras Chaves**

<img width="504" height="362" alt="image" src="https://github.com/user-attachments/assets/c52e99e0-23d3-4446-9da3-58311a93d202" />

## Funcionalidades

**Monitoramento**
- Verificação periódica com intervalo padrão e intervalo próprio por site.
- Detecção de itens novos e, opcionalmente, de itens alterados (mudança de texto).
- Download automático dos arquivos (PDF, ZIP, XSD...) dos itens novos.
- Suporte opcional a páginas montadas por JavaScript (Playwright).

**Usabilidade**
- Ícone na bandeja do sistema: fechar a janela minimiza, e o monitoramento continua.
- Botão **Testar** no cadastro do site, que mostra os itens encontrados antes de salvar.
- Novidades lidas e não lidas (não lidas em negrito) e contador no título da janela.
- Busca no histórico, filtro "só não lidas" e exportação para CSV (abre no Excel).

**Inteligência**
- Palavras-chave prioritárias: itens com esses termos ficam em vermelho, geram notificação "⚠ PRIORIDADE" e trazem a janela para frente.

**Confiabilidade**
- Retentativa automática em falhas temporárias (espera de 5s e depois 15s).
- Alerta quando um site falha 3 vezes seguidas e outro quando ele volta a responder.
- Log em `monitor.log` (rotativo, até 4 arquivos de 1 MB).

## Sites configurados por padrão

| Nome | Seletor | Filtro |
|---|---|---|
| NFC-e SVRS - Avisos | `article` | (nenhum) |
| NF-e SVRS - Avisos | `article` | (nenhum) |
| NF-e - Notas Técnicas | `a` | `exibirArquivo` (baixa os arquivos) |
| Schemas XML | `a` | `exibirArquivo` |
| NFS-e - Notícias | `a` | `/nfse/pt-br/noticias/[^?#]+` |
| Documentação técnica - RTC | `a` | `/nfse/pt-br/[^?#]+` |
| Tecnospeed | `article` | (nenhum) |

Se já existir um `config.json`, ele é mantido. A lista acima só vale para instalações novas.

## Como funciona

1. A cada intervalo, o programa baixa cada página e extrai os itens definidos pelo **seletor CSS**.
2. Na **primeira verificação** de cada site, ele só cria uma *linha de base*, sem notificar.
3. Nas seguintes:
   - itens que não existiam viram **Novo**;
   - se *detectar alterações* estiver ligado, itens cujo texto mudou viram **Alterado**;
   - se *baixar arquivos* estiver ligado, o arquivo de cada item novo é salvo em `downloads\<site>\`.
4. Uma notificação é enviada e a novidade entra na lista.

A identidade de cada item é o seu link. Para blocos sem link, é o próprio texto.

## A tela

**Barra superior:** intervalo padrão, *Verificar todos*, *Verificar selecionado*, *Adicionar site*, *Editar*, *Remover*, *Palavras-chave* e *Pasta de downloads*.

**Sites monitorados:** nome, intervalo, status, última e próxima verificação. Erros aparecem em vermelho. Duplo clique edita o site.

**Novidades:**
- Barra com *Buscar*, *Só não lidas*, *Marcar todas como lidas*, *Exportar CSV*, *Abrir downloads* e *Limpar histórico*.
- Duplo clique abre o link e marca como lida.
- Botão direito oferece *Abrir link*, *Abrir arquivo baixado*, *Copiar link* e *Marcar como lida/não lida*.
- Não lidas aparecem em **negrito** e prioritárias em **vermelho**. A coluna *Tipo* mostra `Novo` ou `Alterado`, além de `prioridade` e `arquivo` quando for o caso.

**Bandeja do sistema:** fechar a janela a envia para a bandeja (perto do relógio). O menu do ícone tem *Abrir*, *Verificar agora* e *Sair*. Para encerrar de fato, use **Sair**.

### Campos de um site

| Campo | Descrição |
|---|---|
| Nome | Exibido na tela e na notificação |
| URL | Página a monitorar |
| Seletor CSS | `a` = cada link; `article` = cada bloco de notícia; aceita qualquer seletor CSS (ex.: `div.aviso`, `ul.lista li`) |
| Filtro (regex no link) | Só considera itens cujo link casa com a expressão. Serve para ignorar menus e rodapé |
| Intervalo (min) | Vazio = usa o intervalo padrão |
| Verificar certificado SSL | Desmarque se der erro de certificado (comum nos portais com cadeia ICP-Brasil) |
| Avisar quando um item existente for alterado | Detecta mudança no texto do item |
| Baixar automaticamente arquivos | Baixa o arquivo do link de cada item novo. Páginas HTML são ignoradas |
| Renderizar com navegador | Usa Chromium (Playwright) para páginas montadas por JavaScript |

Ao alterar URL, seletor, filtro ou o modo navegador, a linha de base é refeita automaticamente.

### Seletores CSS (encadeamento e combinações)

O campo *Seletor CSS* aceita qualquer seletor suportado pelo BeautifulSoup, então dá para encadear, combinar e filtrar:

| Seletor | O que pega |
|---|---|
| `main article` | `article` em qualquer nível dentro de `main` |
| `div.lista > ul > li` | `li` filhos diretos de `ul`, que é filho direto de `div.lista` |
| `article h2 a` | o link dentro do título de cada artigo |
| `#conteudo .aviso` | elementos com classe `aviso` dentro do id `conteudo` |
| `article, div.noticia` | os dois tipos (a vírgula soma seletores) |
| `article:not(.destaque)` | artigos, exceto os que têm a classe `destaque` |
| `a[href*="exibirArquivo"]` | links cujo endereço contém o texto (alternativa ao campo Filtro) |
| `a[href$=".pdf"]` | links que terminam em `.pdf` |
| `li:-soup-contains("Nota Técnica")` | `li` que contêm esse texto (extensão do BeautifulSoup) |

**Como o resultado vira item:** cada elemento encontrado é um item.
- **Texto do item:** todo o texto do elemento. É usado nas palavras-chave e na detecção de alterações.
- **Link do item:** o próprio elemento, se for `a`, ou o primeiro `a` dentro dele.

**Escolha do nível (exemplo: Tecnospeed)**

| Seletor | Vantagem | Desvantagem |
|---|---|---|
| `article` | Texto rico (título, resumo, data, categoria), bom para palavras-chave | Mudanças no resumo ou em contadores contam como "Alterado" |
| `article h2 a` | Só título e link, mais estável, poucos alertas falsos | Palavras-chave só olham o título |

Regra prática:
- Para **detectar novidades com estabilidade**, mire no título com link (`article h2 a`, `article .entry-title a`).
- Para **palavras-chave casarem também no resumo**, use o bloco (`article`) e deixe *detectar alterações* desligado.

**Como descobrir o seletor:**
1. No Chrome ou no Edge, clique com o botão direito sobre o aviso e escolha **Inspecionar**.
2. Veja as tags e classes ao redor do elemento.
3. Monte o seletor e confira com o botão **Testar** no cadastro do site.

Mudar o seletor refaz a linha de base daquele site, então ele não dispara avisos antigos.

**Dicas de calibração**
- Use sempre o botão **Testar** antes de salvar.
- `nenhum item encontrado`: o seletor ou o filtro está restritivo demais, ou a página depende de JavaScript.
- Novidades falsas a cada verificação: adicione um filtro, ou troque `a` por um seletor mais específico.
- "Alterado" falso com frequência: a página tem datas relativas ("há 2 dias") ou contadores. Desligue a detecção de alterações nesse site.

### Arquivos

| Arquivo | Descrição |
|---|---|
| `monitor_avisos.py` | Programa principal |
| `requirements.txt` | Dependências |
| `config.json` | Sites, intervalo, palavras-chave e pasta de downloads (criado automaticamente) |
| `estado.json` | Itens já vistos e histórico de novidades (criado automaticamente) |
| `monitor.log` | Log de verificações e erros |
| `downloads\` | Arquivos baixados, organizados por site (pode ser alterada na tela) |

O `estado.json` da versão anterior é convertido automaticamente. O histórico antigo aparece como lido.

---

## Instalação e execução (Windows)

### 1. Instalar o Python

Baixe em https://www.python.org/downloads/ e marque **"Add Python to PATH"**.

Se aparecer o assistente do **Python install manager**:
- **Caminhos longos (260 caracteres):** pode responder `N`.
- **Aliases de execução:** em *Configurações > Aplicativos > Configurações avançadas de aplicativos > Aliases de execução de aplicativo*, **ative** "Python (default)" e "Python install manager" e **desative** os itens "Instalador de aplicativo" de `python.exe` / `python3.exe`.
- Se perguntar se deseja instalar um runtime do Python, responda `y`.

Feche o Prompt de Comando, abra um novo e confira:
```
python --version
```

### 2. Preparar a pasta

Coloque `monitor_avisos.py` e `requirements.txt` em uma pasta própria, por exemplo `C:\MonitorAvisos`. Se estiver atualizando, basta substituir esses dois arquivos. `config.json` e `estado.json` são mantidos.

### 3. Instalar as dependências
```
cd C:\MonitorAvisos
python -m pip install -r requirements.txt
```

Opcional, só se algum site usar *Renderizar com navegador*:
```
python -m pip install playwright
python -m playwright install chromium
```

### 4. Executar
```
python monitor_avisos.py
```
Sem janela de console:
```
pythonw monitor_avisos.py
```
Ou renomeie para `monitor_avisos.pyw` e abra com duplo clique.

### 5. Iniciar junto com o Windows

`Win + R`, digite `shell:startup` e crie nessa pasta um atalho para `monitor_avisos.pyw` (ou para o `.exe`).

---

## Gerar executável (opcional)

```
cd C:\MonitorAvisos
python -m pip install pyinstaller
```

**Opção A: modo pasta (recomendado, menos bloqueado por antivírus)**
```
python -m PyInstaller --onedir --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification --hidden-import pystray._win32 monitor_avisos.py
```
Resultado: `dist\MonitorAvisos\MonitorAvisos.exe`. Para distribuir, compacte a pasta inteira.

**Opção B: arquivo único**
```
python -m PyInstaller --onefile --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification --hidden-import pystray._win32 monitor_avisos.py
```
Resultado: `dist\MonitorAvisos.exe`.

**Observações**
- Os dois `--hidden-import` são **obrigatórios**: sem eles, as notificações e o ícone da bandeja não funcionam no `.exe`.
- Ícone próprio: acrescente `--icon=icone.ico`.
- `build\` e `MonitorAvisos.spec` podem ser apagados.
- Use uma pasta com permissão de escrita (evite `C:\Arquivos de Programas`), porque `config.json`, `estado.json`, `monitor.log` e `downloads\` ficam ao lado do executável.
- Sites com *Renderizar com navegador* são mais confiáveis rodando pelo `.pyw` do que pelo `.exe`.

### Antivírus apagando o executável

Executáveis do PyInstaller, principalmente os de `--onefile`, são um falso positivo conhecido.
1. Confira em *Segurança do Windows > Proteção contra vírus e ameaças > Histórico de proteção*.
2. **Máquina da empresa:** solicite a liberação à TI ou à segurança.
3. **Máquina pessoal:** *Permitir no dispositivo* ou exclusão para `C:\MonitorAvisos`. Também é possível enviar o arquivo à Microsoft como falso positivo.
4. Prefira `--onedir`.
5. Alternativa: use o `monitor_avisos.pyw` com atalho, sem gerar `.exe`.

---

## Resumo dos comandos

```
:: Verificar Python
python --version

:: Instalar dependências
cd C:\MonitorAvisos
python -m pip install -r requirements.txt

:: (Opcional) Navegador para páginas com JavaScript
python -m pip install playwright
python -m playwright install chromium

:: Executar
python monitor_avisos.py
pythonw monitor_avisos.py

:: Gerar executável (modo pasta)
python -m pip install pyinstaller
python -m PyInstaller --onedir --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification --hidden-import pystray._win32 monitor_avisos.py

:: Gerar executável (arquivo único)
python -m PyInstaller --onefile --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification --hidden-import pystray._win32 monitor_avisos.py
```

## Problemas comuns

| Sintoma | Solução |
|---|---|
| `'python' não é reconhecido` | Reinstale com "Add Python to PATH" ou ajuste os aliases de execução |
| `'pip' não é reconhecido` | Use `python -m pip ...` |
| `No module named ...` | `python -m pip install -r requirements.txt` |
| Não aparece ícone na bandeja | Instale `pystray` e `pillow`. No `.exe`, use `--hidden-import pystray._win32`. Ele pode estar oculto na seta "^" perto do relógio |
| Status `ERRO: ... SSL ...` | Edite o site e desmarque *Verificar certificado SSL* |
| Status `ERRO (3x)` e alerta "sem resposta" | Site fora do ar ou bloqueando. Detalhes em `monitor.log` |
| `nenhum item encontrado` | Use *Testar*. Revise o seletor e o filtro, ou ative *Renderizar com navegador* |
| `Playwright não instalado` | Rode os comandos opcionais do Playwright |
| Novidades ou alterações falsas | Ajuste o filtro ou o seletor, ou desligue *detectar alterações* no site |
| Arquivo não foi baixado | O link aponta para uma página HTML, não para um arquivo. Veja `monitor.log` |
| Notificação não aparece | Verifique se o `plyer` está instalado e se as notificações do Windows estão ativas. No `.exe`, use o `--hidden-import` |
| `.exe` some da pasta `dist` | Antivírus. Veja a seção correspondente |

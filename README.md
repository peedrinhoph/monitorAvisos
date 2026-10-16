# Monitor de Avisos

Programa desktop (Python + Tkinter) que monitora páginas web periodicamente e envia uma notificação do Windows sempre que aparece um item novo, como um aviso, uma nota técnica ou uma notícia.

## Sites configurados por padrão

| Nome | URL | Filtro |
|---|---|---|
| NFC-e SVRS - Avisos | https://dfe-portal.svrs.rs.gov.br/Nfce/Avisos | (nenhum) |
| NF-e - Notas Técnicas | https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=04BIflQt1aY= | `exibirArquivo` |
| NFS-e - Notícias | https://www.gov.br/nfse/pt-br/noticias | `/nfse/pt-br/noticias/[^?#]+` |

Outros sites podem ser adicionados pela própria tela do programa.

## Como funciona

1. A cada intervalo (padrão de 30 minutos), o programa baixa cada página e extrai os links dela.
2. Na **primeira verificação** de cada site, ele só cria uma *linha de base* com os itens existentes e não notifica nada.
3. Nas verificações seguintes, todo link que ainda não existia vira uma **novidade**:
   - aparece uma notificação do Windows (via `plyer`);
   - a novidade entra na lista da tela, com data, site e título;
   - um duplo clique na novidade abre o link no navegador.
4. O histórico fica salvo, então fechar e reabrir o programa não gera avisos repetidos.

### Arquivos

| Arquivo | Descrição |
|---|---|
| `monitor_avisos.py` | Programa principal |
| `requirements.txt` | Dependências (`requests`, `beautifulsoup4`, `plyer`) |
| `config.json` | Criado automaticamente. Lista de sites e intervalo |
| `estado.json` | Criado automaticamente. Itens já vistos e histórico de novidades |

`config.json` e `estado.json` ficam na mesma pasta do programa (ou do `.exe`).

## A tela

- **Barra superior**: intervalo em minutos e os botões *Verificar agora*, *Adicionar site*, *Editar*, *Remover* e *Limpar histórico*.
- **Sites monitorados**: status de cada site (`OK — N itens, X novo(s)`, `linha de base criada`, `verificando...` ou mensagem de erro) e data/hora da última verificação. Duplo clique edita o site.
- **Novidades**: tudo o que já foi detectado, com os mais recentes no topo. Duplo clique abre o link.

Fechar a janela **encerra o monitoramento**. Para continuar recebendo avisos, deixe a janela aberta ou minimizada.

### Campos de um site

| Campo | Descrição |
|---|---|
| Nome | Nome exibido na tela e na notificação |
| URL | Página a monitorar |
| Seletor CSS | Elementos considerados itens. `a` = todos os links |
| Filtro (regex no link) | Só conta links que casam com a expressão. Serve para ignorar menus e rodapé |
| Verificar certificado SSL | Desmarque se o site falhar por certificado (comum no portal NF-e, que usa cadeia ICP-Brasil) |

Ao alterar URL, seletor ou filtro de um site, a linha de base é refeita automaticamente para não gerar avisos falsos.

**Calibração:** se o status mostrar `nenhum item encontrado`, o filtro está restritivo demais. Se aparecerem novidades falsas (menus que mudam, links com token de sessão), adicione ou ajuste o filtro.

---

## Instalação e execução (Windows)

### 1. Instalar o Python

Baixe em https://www.python.org/downloads/ e, na instalação, marque **"Add Python to PATH"**.

Se aparecer o assistente do **Python install manager**:

- **Caminhos longos (260 caracteres):** pode responder `N`. Não é necessário para este programa.
- **Aliases de execução:** em *Configurações > Aplicativos > Configurações avançadas de aplicativos > Aliases de execução de aplicativo*:
  - **ative** "Python (default)" e "Python install manager";
  - **desative** os itens "Instalador de aplicativo" de `python.exe` / `python3.exe` (atalhos da Microsoft Store).
- Se o assistente perguntar se deseja instalar um runtime do Python, responda `y`.

Feche o Prompt de Comando, abra um novo e confira:

```
python --version
```

### 2. Preparar a pasta

Coloque `monitor_avisos.py` e `requirements.txt` em uma pasta própria, por exemplo `C:\MonitorAvisos`.

### 3. Instalar as dependências

```
cd C:\MonitorAvisos
python -m pip install -r requirements.txt
```

### 4. Executar

Com janela de console:

```
python monitor_avisos.py
```

Sem janela de console:

```
pythonw monitor_avisos.py
```

Ou renomeie o arquivo para `monitor_avisos.pyw` e abra com duplo clique.

### 5. Iniciar junto com o Windows

1. Pressione `Win + R`, digite `shell:startup` e confirme.
2. Crie nessa pasta um atalho para `monitor_avisos.pyw` (ou para o `.exe`, se gerar um).

---

## Gerar executável (opcional)

### Instalar o PyInstaller

```
cd C:\MonitorAvisos
python -m pip install pyinstaller
```

### Opção A: modo pasta (recomendado, menos bloqueado por antivírus)

```
python -m PyInstaller --onedir --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification monitor_avisos.py
```

Resultado: pasta `dist\MonitorAvisos\` contendo o `MonitorAvisos.exe`. Para distribuir, compacte a pasta inteira.

### Opção B: arquivo único

```
python -m PyInstaller --onefile --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification monitor_avisos.py
```

Resultado: `dist\MonitorAvisos.exe`.

### Observações

- `--hidden-import plyer.platforms.win.notification` é **obrigatório**. Sem ele o programa abre, mas as notificações não aparecem.
- Ícone próprio: acrescente `--icon=icone.ico` ao comando.
- As pastas `build\` e o arquivo `MonitorAvisos.spec` podem ser apagados depois.
- Coloque o executável em uma pasta com permissão de escrita (evite `C:\Arquivos de Programas`), pois `config.json` e `estado.json` são criados ao lado dele.
- Para levar a configuração atual, copie o `config.json` para junto do `.exe`.

### Antivírus apagando o executável

Executáveis do PyInstaller, principalmente os de `--onefile`, são um **falso positivo** conhecido.

1. Confira em *Segurança do Windows > Proteção contra vírus e ameaças > Histórico de proteção* se o arquivo aparece lá (ex.: `Trojan:Win32/Wacatac`).
2. **Máquina da empresa:** solicite a liberação à TI ou à equipe de segurança. Não contorne a política.
3. **Máquina pessoal:** use *Permitir no dispositivo* ou adicione uma exclusão para `C:\MonitorAvisos`. Você também pode enviar o arquivo à Microsoft como falso positivo (Microsoft Security Intelligence, envio de arquivos).
4. Prefira a **Opção A (`--onedir`)**, que costuma ser bem menos bloqueada.
5. **Alternativa sem executável:** use o `monitor_avisos.pyw` com atalho, que o antivírus não bloqueia.

---

## Resumo dos comandos

```
:: Verificar Python
python --version

:: Instalar dependências
cd C:\MonitorAvisos
python -m pip install -r requirements.txt

:: Executar
python monitor_avisos.py
pythonw monitor_avisos.py

:: Gerar executável (modo pasta)
python -m pip install pyinstaller
python -m PyInstaller --onedir --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification monitor_avisos.py

:: Gerar executável (arquivo único)
python -m PyInstaller --onefile --noconsole --name MonitorAvisos --hidden-import plyer.platforms.win.notification monitor_avisos.py
```

## Problemas comuns

| Sintoma | Solução |
|---|---|
| `'python' não é reconhecido` | Reinstale marcando "Add Python to PATH" ou ajuste os aliases de execução |
| `'pip' não é reconhecido` | Use `python -m pip ...` |
| `No module named requests` / `bs4` / `plyer` | `python -m pip install -r requirements.txt` |
| Status `ERRO: ... SSL ...` | Edite o site e desmarque *Verificar certificado SSL* |
| Status `nenhum item encontrado` | Revise o seletor e o filtro do site |
| Novidades falsas a cada verificação | Adicione um filtro que pegue só os links de avisos |
| Notificação não aparece | Verifique se o `plyer` está instalado, se as notificações do Windows estão ativas e, no `.exe`, se usou o `--hidden-import` |
| `.exe` some da pasta `dist` | Antivírus. Veja a seção "Antivírus apagando o executável" |

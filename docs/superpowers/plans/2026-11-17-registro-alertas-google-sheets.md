# Registro de Alertas no Google Sheets - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar cada alerta estadual do ES uma unica vez na planilha, com
municipios reunidos e recuperacao de falhas sem depender da retencao do mapa.

**Architecture:** O coletor captura uma fila antes dos filtros de mapa e retencao.
Um sincronizador separado reconcilia essa fila com a aba de destino e acrescenta
somente chaves ausentes. GitHub Actions autentica a conta de servico via OIDC,
serializa o processamento e persiste estado independentemente da disponibilidade
do Google Sheets.

**Tech Stack:** Python >=3.11,<3.14, unittest, Poetry, google-auth,
requests/AuthorizedSession, Sheets API v4, GitHub Actions e OIDC/WIF.

**Spec:** `docs/superpowers/specs/2026-11-17-registro-alertas-google-sheets-design.md`.

## Global Constraints

- Destino: `1YUA-PqviqmEesI5nMFJTJcs13XwUueLxSW_-RuPWUlE`, sheetId `0`.
- Somente Defesa Civil Estadual do Espirito Santo; uma linha por alerta.
- Chave: emissor normalizado + identifier, fallback entry_id valido; rejeitar UNKNOWN.
- Doze colunas, na ordem da especificacao; municipios separados por `; `.
- Datas texto `DD/MM/AAAA HH:mm:ss`, fuso `America/Sao_Paulo`; escrita RAW.
- Nao sobrescrever linhas existentes nem excluir alertas expirados.
- Nao alterar mapa, dashboard, compartilhamento ou agendamento.
- Persistir `.cache/sheets_pending.json` sem retencao temporal.
- Somente main escreve na planilha real; development e testes usam simulacao.
- Credenciais temporarias; nada de chave privada em codigo, log ou artefato.
- Nao prometer entrega de alertas nao observados ou exactly-once com escritores externos.

## Review Focus

1. Timeout apos append: verificar chave no destino antes de repetir (tarefa 3).
2. Falha de enriquecimento ou alerta sem geometria: captura continua recuperavel (tarefa 2).
3. Cabecalho vazio com dados abaixo/aba renomeada: nao sobrescrever dados (tarefa 3).
4. Falha no push apos gravacao: persistir/reconciliar fila sem reenvio cego (tarefa 4).
5. Politica OIDC ou ref incorreta: nenhuma escrita fora da main (tarefas 4 e 5).

## Arquivos e Responsabilidades

- `scripts/sheets_registry.py`: funcoes puras de chave, colunas, datas e fila atomica.
- `scripts/sync_alerts_sheets.py`: cliente autenticado, reconciliacao e CLI simulavel.
- `scripts/persist_idap_state.py`: persistencia Git com retentativa limitada e sem force.
- `scripts/idap_daily_maps.py`: captura antes dos filtros e enriquecimento posterior.
- `.github/workflows/idap_daily_maps.yml`: orquestracao e identidade.
- `pyproject.toml` / `poetry.lock`: dependencias de autenticacao/transporte.
- `.gitignore`: permitir apenas os novos testes; ignorar credenciais temporarias.
- `README.md`, `scripts/run_fake_idap_test.ps1`: manter comandos de coleta funcionais.
- `docs/google-sheets-setup.md`: configuracao, ativacao, recuperacao e limites.
- Novos testes: `tests/test_sheets_registry.py`, `tests/test_sheets_capture.py`,
  `tests/test_sheets_sync.py`, `tests/test_sheets_workflow.py`,
  `tests/test_persist_idap_state.py`. Preservar testes locais preexistentes.

## Task 1: Modelo de Linha e Fila Persistente

Status: implementado e testado (6 testes, incluindo regressao da revisao).

**Files:** criar `scripts/sheets_registry.py`, `tests/test_sheets_registry.py`;
alterar `.gitignore` somente para liberar os novos testes explicitamente.

**Interfaces:** `alert_key(alert: dict) -> tuple[str, str] | None`;
`row_values(alert: dict, registered_at: datetime) -> list[str]`;
`load_pending(path: Path) -> list[dict]`;
`merge_pending(pending: list[dict], candidates: list[dict]) -> list[dict]`;
`save_pending(path: Path, records: list[dict]) -> None`;
constante `HEADERS: tuple[str, ...]` com os doze rotulos aprovados.
Fila JSON: objeto `{"version": 1, "alerts": [...]}`; sem marcacao de enviado local
como autoridade. Arquivo inexistente inicia vazio; arquivo corrompido falha sem sobrescrever.

- [ ] Escrever testes: ID repetido resulta em uma chave; fallback valido; UNKNOWN
  nao gera chave; outros emissores sao rejeitados; alerta com dois municipios
  repetidos produz uma celula ordenada sem duplicacao e exatamente 12 colunas.
- [ ] Testar `2026-11-17T15:00:00Z` -> `17/11/2026 12:00:00`; ID `123/2026`
  e mensagem `=1+1` continuam texto; campos ausentes viram vazio com aviso para
  datas invalidas. Sem ID ou emissor elegivel nao ha linha exportavel.
- [ ] Rodar `poetry run python -m unittest discover -s tests -p test_sheets_registry.py`;
  confirmar falha pela ausencia das interfaces.
- [ ] Implementar com ZoneInfo, normalizacao consistente do emissor e escrita
  em temporario no mesmo diretorio seguida de os.replace. Guardar o primeiro
  conteudo; permitir completar nomes antes do envio, avisando divergencias.
- [ ] Testar falha durante escrita preservando arquivo anterior; candidato de
  dez dias continua na fila; JSON corrompido nao e convertido silenciosamente em vazio.
- [ ] Reexecutar testes ate PASS e criar commit limitado aos arquivos da tarefa.

## Task 2: Captura Independente do Mapa

Status: implementado e testado (4 testes, incluindo regressao da revisao).

**Files:** alterar `scripts/idap_daily_maps.py`, `README.md`,
`scripts/run_fake_idap_test.ps1`; criar `tests/test_sheets_capture.py`.

**Interfaces:** consumir as funcoes da tarefa 1 via import relativo; invocacao
padrao `python -m scripts.idap_daily_maps`, tambem no script PowerShell e README.
Configuracao `SHEETS_CAPTURE_ENABLED` (default false local) e
`SHEETS_PENDING_PATH` (default `.cache/sheets_pending.json`).

- [ ] Escrever testes de coleta fake, sem rede: capturar historico disponivel
  mais feed antes de `_filter_recent_history`, `_clip_alerts_to_continental_mask`
  e `_filter_window`; descartar outros emissores; repetir coleta sem duplicar.
- [ ] Testar alerta expirado, antigo, sem geometria e falha da malha municipal:
  todos os candidatos elegiveis permanecem na fila mesmo se a geracao do mapa falhar.
- [ ] Rodar `poetry run python -m unittest discover -s tests -p test_sheets_capture.py`
  e confirmar RED; implementar captura habilitavel antes da retencao.
- [ ] Apos enriquecimento bem-sucedido, completar municipios na fila; usar
  affected_municipios e nomes explicitos de areaDesc quando nao houver geometria.
  Nao inventar nomes a partir de texto livre ambiguo; emitir aviso de incompletude.
- [ ] Testar que captura desabilitada nao cria fila e nao muda saidas existentes;
  manter comandos fake sem gravacao em producao. Reexecutar ate PASS e commitar.

## Task 3: Reconciliacao com Google Sheets

Status: implementado e testado (7 testes).

**Files:** criar `scripts/sync_alerts_sheets.py`, `tests/test_sheets_sync.py`;
alterar `pyproject.toml` e `poetry.lock` com dependencias resolvidas pelo Poetry.

**Interfaces:** `SheetsClient(session, spreadsheet_id: str, sheet_id: int)`;
metodos `read_rows() -> list[list[str]]`, `initialize_headers() -> None`,
`append_rows(rows: list[list[str]]) -> None`;
`sync_pending(client: SheetsClient, pending_path: Path, now: datetime) -> dict`.
Resultado: inserted, already_present, pending, warnings, status. CLI
`python -m scripts.sync_alerts_sheets --dry-run` nao autentica nem acessa Google;
`--apply` usa ADC com escopo spreadsheets, `SHEETS_SPREADSHEET_ID`, `SHEETS_SHEET_ID`.
Modo apply exige `GITHUB_REF=refs/heads/main` e o repositorio esperado.

- [ ] Escrever testes com transporte falso que exercitem a logica real: IDs
  existentes nao sao reenviados; duas geometrias nao geram duas linhas; RAW;
  lote vazio nao escreve; primeira carga inclui candidatos expirados.
- [ ] Testar metadados com sheetId 0 renomeado; cabecalho incompativel e primeira
  linha vazia com dados abaixo impedem inicializacao/escrita; IDs preexistentes
  duplicados geram erro diagnostico e mantem fila sem agravar a duplicacao.
- [ ] Testar timeout apos servidor gravar: segunda leitura encontra a chave e
  remove pendencia sem segundo append. Se reconciliacao falhar, manter fila;
  nao fazer retry automatico de POST. Em 403/429/5xx conservar candidatos.
- [ ] Rodar `poetry run python -m unittest discover -s tests -p test_sheets_sync.py`
  e confirmar RED; instalar dependencias com Poetry, implementar cliente sobre
  google.auth.default e AuthorizedSession com timeout finito.
- [ ] Usar metadados para titulo e dimensoes; ler A:L em paginas de 1000 linhas
  ate cobrir a regiao utilizada. Inicializar cabecalho apenas com aba vazia.
  Acrescentar em lotes de ate 100 linhas via append RAW/INSERT_ROWS; apos cada
  lote confirmar chaves e persistir fila. Avisar conteudo divergente sem sobrescrever.
- [ ] Testar dados maiores que o limite de celula (50000 caracteres): nao truncar
  silenciosamente; reter candidato e identificar o ID no resumo. Nao impedir os
  demais candidatos validos de serem enviados.
- [ ] Reexecutar ate PASS, `poetry check`, e commitar implementacao e lock.

## Task 4: Workflow e Persistencia Duravel

Status: implementado e testado (5 testes).

**Files:** alterar `.github/workflows/idap_daily_maps.yml`, `.gitignore`;
criar `scripts/persist_idap_state.py`, `tests/test_sheets_workflow.py`,
`tests/test_persist_idap_state.py`. Nao alterar workflow de deploy-only.

**Interfaces:** CLI `python -m scripts.persist_idap_state`, whitelist dos arquivos
ja persistidos e `.cache/sheets_pending.json`; maximo de tres tentativas.
Variaveis GitHub: `SHEETS_ENABLED`, `SHEETS_SPREADSHEET_ID`, `SHEETS_SHEET_ID`,
`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`. Default sem configuracao:
integracao desabilitada explicitamente no resumo, sem tentar autenticar.

- [ ] Escrever testes que verifiquem ref/repo, cancel-in-progress false e captura
  antes do sync; negar apply em development. Usar PyYAML em dependencia de testes
  para validar a estrutura YAML, nao comparacoes frageis de texto.
- [ ] Em repositorios temporarios com bare remoto, testar push rejeitado por
  atualizacao de dados e por conflito em codigo: no primeiro integrar e preservar
  fila; no segundo parar com erro e artefato recuperavel, sem force ou perder arquivo.
- [ ] Rodar os dois modulos de teste, confirmar RED e implementar:
  atualizar checkout antes da coleta; rodar coleta/captura; autenticar via
  google-github-actions/auth com SHA revisado, OIDC/ADC e conta impersonada;
  sincronizar somente se coleta/persistencia de candidatos produzir arquivo valido.
- [ ] Tratar sync/auth como etapas nao bloqueantes para dashboard/deploy; registrar
  seus outcomes separadamente. Persistir estado/pendencias mesmo com falha do
  Sheets; upload de recuperacao com always. Expor alertas e contagens em
  GITHUB_STEP_SUMMARY, sem mensagens completas ou credenciais.
- [ ] No push retry, integrar origin/main sem repetir sync; nunca resolver
  conflitos de fila escolhendo um lado silenciosamente. Falha no push apos tres
  tentativas deve ser visivel e nao anunciada como entrega duravel.
- [ ] Excluir `gha-creds-*.json` do Git e garantir que upload nao inclua o arquivo
  ADC, tokens ou dumps de ambiente. Reexecutar testes e commitar.

## Task 5: Configuracao Externa e Validacao Controlada

Status: documentacao e simulacao local concluidas; configuracao Google/GitHub,
ativacao e teste real aguardam o usuario. Nenhum passo externo foi executado.

**Files:** criar `docs/google-sheets-setup.md`; atualizar README com link.
As operacoes externas abaixo precisam ser realizadas com o usuario, sem supor
acesso administrativo ao Google Cloud ou equivalencia com a conexao deste chat.

- [ ] Documentar: criar/selecionar projeto, habilitar Sheets/STS/IAM Credentials,
  criar conta dedicada e compartilhar apenas a planilha com seu email de editor.
  Nao conceder Editor do projeto nem delegacao de dominio.
- [ ] Configurar WIF para GitHub com restricoes a organizacao/repositorio por IDs
  imutaveis verificados e ref main; conceder workloadIdentityUser somente ao
  principal restrito da conta. Configurar variaveis do repo com SHEETS_ENABLED=false.
- [ ] Rodar suite completa `poetry run python -m unittest discover -s tests` e
  `node --test tests/alert_validity.test.cjs`; reportar qualquer teste local
  preexistente que falhe. Verificar `poetry check` e `git diff --check`.
- [ ] Rodar dry-run com fixture conhecida, nao com producao; comparar as doze
  colunas com o desenho. Documentar recuperacao de artefato/fila, cabecalho
  incompatível, acesso negado, IDs editados e falha duravel do Git.
- [ ] Pedir autorizacao para um teste real na planilha: conferir novamente o
  conteudo atual e habilitar main somente apos configuracao e revisao aprovadas.
  Primeira execucao registra candidatos; segunda execucao com os mesmos IDs
  deve acrescentar zero linhas. Nao inserir alerta ficticio nem excluir linhas.
- [ ] Conferir resumo e pendencias no GitHub; confirmar que dashboard continua
  publicado. Documentar que falha duradoura no RSS/Git ou alertas nao observados
  nao sao recuperados automaticamente. Nao ampliar compartilhamento da planilha.
- [ ] Commitar somente documentacao; merge/push para main e ativacao devem ser
  solicitados explicitamente, nao inferidos da aprovacao do plano.

## Revisao do Plano

- Escopo coberto nas tarefas 1-5; nenhuma mudanca de frontend prevista.
- Interfaces de fila/sync definidas antes dos seus consumidores.
- Cinco riscos do Review Focus possuem testes ou validacoes externas explicitas.
- Deploy real depende da configuracao da identidade e autorizacao para escrita.
- Estado inicial: apenas desenho aprovado; todas as tarefas de implementacao pendentes.

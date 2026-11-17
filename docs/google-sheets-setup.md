# Registro de alertas no Google Sheets

## Estado de Entrega

Codigo preparado, mas integracao desabilitada por padrao. Nenhuma conta foi
criada, nenhuma permissao foi concedida e nenhuma linha foi gravada por esta
implementacao. A conexao Google do chat nao autentica o GitHub Actions.
Execute os passos administrativos somente com aprovacao do responsavel.

Destino: planilha `1YUA-PqviqmEesI5nMFJTJcs13XwUueLxSW_-RuPWUlE`, aba sheetId `0`.
O titulo e resolvido pelo ID; renomear a aba nao altera o destino.

## Comportamento

- Apenas o emissor Defesa Civil Estadual do Espirito Santo e aceito.
- Uma linha por ID; todos os municipios conhecidos ficam em uma celula.
- Doze colunas: ID do alerta, Emissao, Inicio da vigencia, Fim da vigencia,
  Municipios atingidos, Evento, Nivel, Emissor, Titulo, Mensagem, Orientacoes,
  Registrado em. Os cabecalhos escritos pelo codigo tem acentuacao.
- Datas texto em horario de Brasilia, formato DD/MM/AAAA HH:mm:ss. IDs e
  mensagens sao texto RAW: formula recebida no RSS nao e executada.
- Cabecalhos sao criados somente em aba inteiramente vazia. Estrutura diferente
  ou IDs duplicados bloqueiam o envio; nao sobrescrevemos dados existentes.
- Linhas ja existentes sao preservadas mesmo que o RSS tenha alterado o conteudo.
  Ha aviso no log para divergencias; alertas com novo ID criam nova linha.
- A primeira execucao captura o historico ainda disponivel e o feed; nao ha
  recuperacao completa de tudo que ja saiu do RSS/historico.
- Expiracao ou ausencia de poligono nao impedem o registro.
- Nomes de municipios vem do enriquecimento existente ou nomes explicitos do CAP,
  validados contra os 78 municipios da malha do projeto; estado/regiao nao viram municipio.
  Se nao for possivel identificar municipios, a celula fica vazia com aviso.
- Uma resposta perdida de escrita e reconciliada lendo IDs antes de reenviar.
- Nao editar as colunas ID/Emissor nem criar outro escritor automatizado.
  Sem essa restricao, o Sheets nao garante unicidade transacional.

## 1. Google Cloud: Conta de Servico e Federacao

Escolha/crie um projeto institucional com permissao administrativa para IAM e
Workload Identity Federation. Nao sao necessarias chaves JSON, delegacao de
dominio ou papel Editor do projeto para a conta de servico.

Os comandos abaixo sao exemplos para Bash no Cloud Shell; substitua os valores.
Nao execute placeholders literalmente. Nao ha dados secretos nesses identificadores.
Obtenha os IDs numericos reais do repositorio e da organizacao por consulta
autenticada ao GitHub, por exemplo:

```bash
gh api repos/defesacivil-es/Alertas_Idap --jq '{repository_id: .id, owner_id: .owner.id}'
```

```bash
PROJECT_ID="SEU_PROJETO"
REPOSITORY_ID="ID_NUMERICO_DO_REPOSITORIO"
OWNER_ID="ID_NUMERICO_DA_ORGANIZACAO"
gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

gcloud services enable sheets.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com
gcloud iam service-accounts create idap-sheets --display-name="Registro de alertas IDAP"
SA_EMAIL="idap-sheets@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam workload-identity-pools create idap-github --location=global --display-name="IDAP GitHub"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=idap-github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_id == '$REPOSITORY_ID' && assertion.repository_owner_id == '$OWNER_ID' && assertion.ref == 'refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/idap-github/attribute.repository_id/${REPOSITORY_ID}"
```

Compartilhe somente a planilha de destino com `$SA_EMAIL` como editor.
Nao e necessario publicar a planilha nem ampliar seu compartilhamento.
Politicas institucionais de compartilhamento podem exigir intervencao do administrador.
O escopo utilizado pelo cliente e `https://www.googleapis.com/auth/spreadsheets`.

Referencias oficiais:
- https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- https://github.com/google-github-actions/auth
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append

## 2. Variaveis do Repositorio no GitHub

Em Settings > Secrets and variables > Actions > Variables:

| Variavel | Valor |
|---|---|
| SHEETS_ENABLED | false durante configuracao; true apenas na ativacao autorizada |
| SHEETS_SPREADSHEET_ID | 1YUA-PqviqmEesI5nMFJTJcs13XwUueLxSW_-RuPWUlE |
| SHEETS_SHEET_ID | 0 |
| GCP_SERVICE_ACCOUNT | email da conta de servico criada |
| GCP_WORKLOAD_IDENTITY_PROVIDER | projects/NUMERO/locations/global/workloadIdentityPools/idap-github/providers/github |

Use o NUMERO do projeto no provider, nao o PROJECT_ID. Nao adicionar chave privada
como secret: a autenticacao usa a identidade temporaria do workflow.
Permissoes `id-token: write` e `contents: write` ja estao previstas no workflow.
Se protecao de branch impedir o bot de persistir estado, definir antes da ativacao
um mecanismo institucional autorizado; nao desativar protecoes silenciosamente.

## 3. Testes Locais e Simulacao

Na raiz do checkout isolado, instale o projeto com Poetry. Coleta padrao nao
captura para Sheets se `SHEETS_CAPTURE_ENABLED` nao estiver true.

```powershell
poetry install --no-root
poetry run python -m unittest discover -s tests
node --test tests/alert_validity.test.cjs
poetry check
git diff --check
```

Para inspecionar uma fila criada por coleta controlada:

```powershell
poetry run python -m scripts.sync_alerts_sheets --dry-run --pending-path CAMINHO_DA_FILA
```

Dry-run nao acessa Google, nao escreve nem altera a fila e imprime apenas
contagem/schema. Fixtures e testes usam arquivos temporarios, nao a planilha real.
Development com SHEETS_ENABLED=true coleta candidatos e simula; nao autentica,
nao persiste estado remoto nem grava na planilha de producao.

## 4. Ativacao Assistida

1. Revisar codigo/configuracao e autorizar merge/push para main separadamente.
2. Revalidar planilha atual, cabecalhos e eventual conteudo antes da primeira escrita.
3. Confirmar acesso da conta de servico e politica WIF restrita ao repositorio/main.
4. Autorizar escrita real e definir SHEETS_ENABLED=true.
5. Executar o workflow de coleta existente na main. Ele usa o mesmo download RSS,
   captura antes da retencao e tenta sincronizar; nao acrescenta agendamento novo.
6. Conferir resumo, arquivo de fila persistido e as doze colunas no Sheets.
7. Reexecutar sem novos candidatos e confirmar zero novas linhas para os mesmos IDs.
   Nao inserir alerta ficticio nem apagar linhas reais para testar.

Falhas de autenticacao ou Sheets aparecem em outcome/summary, mas nao bloqueiam
a publicacao do dashboard. Falha de persistencia Git falha o build para nao
anunciar uma fila apenas local como duravel. A desativacao de Sheets nao remove
registros da planilha nem apaga a fila ja existente.

## 5. Diagnostico e Recuperacao

- **403/acesso negado:** conferir email editor, API habilitada, politica WIF,
  ID numerico do repositorio e ref main. Nao ampliar papeis do projeto por tentativa.
- **Cabecalho incompativel/IDs duplicados:** nenhuma sobrescrita automatica.
  Revisar manualmente cabecalhos e chaves; retentar apenas apos corrigir com autorizacao.
- **Timeout ou erro 429/5xx:** candidatos nao confirmados continuam pendentes.
  Nao repetir append manualmente; a proxima execucao reconcilia com os IDs reais.
- **Celula acima de 50000 caracteres:** alerta fica pendente e os demais podem
  seguir. Nao ha truncamento silencioso; decidir manualmente um armazenamento adequado.
- **Fila invalida/disco cheio:** arquivo nao e descartado; captura gera aviso.
  Recuperar uma copia valida antes de retomar; nao substituir uma fila por lista vazia.
- **Push rejeitado:** ate tres tentativas de integrar main, preservando uniao das
  filas e historicos. Conflitos em codigo nao sao resolvidos automaticamente.
  Reintroduzir uma chave ja confirmada na fila e seguro: ela sera reconciliada.
- **Recuperacao:** baixar `idap_daily_outputs` da execucao (retencao 7 dias).
  Recuperar `.cache/sheets_pending.json`, validar seu JSON e unir registros com a
  fila atual usando `merge_pending`/deduplicacao, nunca sobrescrever uma pela outra.
  Commitar a fila consolidada via fluxo autorizado e reexecutar a main.
- **Credenciais:** ADC temporario tem nome `gha-creds-*.json`, e ignorado no Git
  e nao esta nos caminhos do artefato. Nunca anexar esse arquivo em chamados.
- **Limites:** nao recuperamos alertas que saiam do RSS entre consultas; falhas
  prolongadas em RSS/Git e artefatos expirados podem exigir recuperacao manual.
  Atualizacoes concorrentes de outra automacao na planilha nao estao suportadas.

## Validacoes Ainda Externas

Pendente: criar/configurar projeto/conta/WIF, conceder acesso, configurar variaveis,
teste de credenciais reais, primeira escrita autorizada, repeticao sem duplicacao
e deploy real. Testes locais nao substituem essas verificacoes.

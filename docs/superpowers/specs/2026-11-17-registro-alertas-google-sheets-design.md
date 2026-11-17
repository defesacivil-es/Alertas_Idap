# Registro de alertas IDAP no Google Sheets

Status: desenho aprovado pelo usuario em 17/11/2026; plano de implementacao em
preparacao. Nenhuma gravacao na planilha ou ativacao em producao realizada.

## Objetivo e Escopo

Registrar os alertas observados pela coleta existente, exclusivamente do emissor
Defesa Civil Estadual do Espirito Santo. Manter uma linha por alerta, com todos os
municipios atingidos em uma unica celula. A expiracao nao remove o registro.
Nao alterar o funcionamento ou o visual dos mapas e do dashboard.

Destino informado pelo usuario:
- Planilha: `1YUA-PqviqmEesI5nMFJTJcs13XwUueLxSW_-RuPWUlE`.
- Aba inicialmente inspecionada: `Pagina1` com acento em Pagina; sheetId `0`.
- Resolver o titulo pelo sheetId em cada execucao, permitindo renomear a aba.
- Revalidar conteudo e cabecalhos antes de qualquer escrita; a inspecao inicial
  encontrou as cinco primeiras linhas vazias, nao verificou a aba inteira.

## Decisoes Confirmadas

- Uma linha por alerta, nao por poligono ou municipio.
- Municipios reunidos em uma coluna.
- Integracao Python com a API do Google Sheets e uma conta de servico.
- Execucao associada a coleta do workflow atual, sem criar um novo agendamento.

## Abordagens Consideradas

1. API do Sheets no Python existente: escolhida pelo usuario. Centraliza a logica
   no repositorio; exige habilitar API, autenticar e compartilhar a planilha.
2. Apps Script receptor: descartado nesta etapa. Evita cliente Google no Python,
   mas acrescenta um endpoint e codigo para manter fora do repositorio.

## Colunas Propostas, Nesta Ordem

1. ID do alerta (`identifier`; fallback `entry_id` valido).
2. Emissao (`sent`).
3. Inicio da vigencia (`onset`).
4. Fim da vigencia (`expires`).
5. Municipios atingidos (nomes unicos, ordenados, separados por `; `).
6. Evento (`event`).
7. Nivel (classificacao ja utilizada pelo projeto).
8. Emissor (`senderName`).
9. Titulo (`headline`).
10. Mensagem (`description`, sem resumo).
11. Orientacoes (`instruction`).
12. Registrado em (primeira confirmacao de registro).

Datas como texto `DD/MM/AAAA HH:mm:ss`, convertidas explicitamente para
`America/Sao_Paulo`, sem depender do fuso da planilha ou do runner. Ausencias
ficam em branco. Usar escrita RAW para preservar IDs e nao executar mensagens
que se parecam com formulas. Nao incluir geometria bruta na planilha.

## Fluxo e Duplicidade

- Reaproveitar os registros CAP, o filtro por emissor e a identificacao de
  municipios; nao fazer uma segunda consulta ao RSS.
- Arquivar candidatos antes dos filtros de vigencia, janela de 24h e geometria.
  Um alerta sem poligono tambem deve ser registrado. Usar nomes enriquecidos
  quando disponiveis; se indisponiveis, aproveitar nomes informados no CAP e
  registrar a limitacao no log, sem inventar municipios.
- Chave logica: emissor normalizado + ID. Sem ID valido, rejeitar com log; nunca
  gravar todos os alertas incompletos sob UNKNOWN ou uma chave vazia.
- Consultar IDs e emissores ja existentes na aba antes de acrescentar linhas.
  Eliminar tambem repeticoes dentro do lote recebido.
- Preservar o primeiro registro de um mesmo ID; nao sobrescrever edicoes humanas.
  Diferencas no mesmo ID geram aviso. Outro ID gera outra linha.
- Inicializacao proposta: importar o historico local disponivel e os alertas do
  RSS, com a mesma deduplicacao. Nao prometer recuperar alertas ja ausentes de ambos.

## Falhas, Retentativas e Concorrencia

- Manter fila persistente `.cache/sheets_pending.json`, independente da retencao
  de 72h. Capturar os candidatos antes da limpeza do historico.
- So retirar candidatos apos confirmacao da escrita ou verificacao de que sua
  chave ja esta na planilha. Uma resposta perdida exige reconciliacao antes de
  repetir append; nao repetir uma escrita cegamente.
- Persistir fila com escrita atomica, commit e push; incluir copia no artefato
  de recuperacao. Se a persistencia remota falhar, sinalizar falha explicitamente.
  Arquivo apenas no runner nao e considerado persistencia duravel.
- Falha no Sheets nao deve interromper a geracao/publicacao do dashboard.
  Exibir resultado e pendencias no resumo do workflow, sem ocultar o erro.
- Serializar escritores; nao cancelar uma execucao enquanto grava. Rever o
  cancel-in-progress atual e tornar o push do estado compativel com atualizacoes
  remotas, sem force push e sem repetir a gravacao no Sheets por causa do Git.
- Somente a main escreve na planilha de producao. Development usa simulacao.
- A garantia de deduplicacao depende de um unico escritor automatizado e da
  preservacao das colunas ID/Emissor. O Sheets nao fornece chave unica nem
  transacao atomica entre leitura e append. Edicoes externas nessas colunas ou
  outro escritor exigem reconciliacao; nao prometer exactly-once irrestrito.
- Alertas que aparecam e desaparecam entre consultas ao RSS podem nao ser vistos.

## Autenticacao Proposta

Usar conta de servico dedicada, com acesso de editor apenas a planilha de destino.
Minha recomendacao tecnica e autenticar o GitHub via OIDC / Workload Identity
Federation, impersonando essa conta, sem armazenar chave privada permanente.
Restringir a identidade ao repositorio defesacivil-es/Alertas_Idap e a main.
Essa escolha integra o desenho aprovado; a configuracao no Google esta pendente.

Preparacao externa: projeto Google Cloud, APIs necessarias, conta de servico,
federacao e permissoes, compartilhamento da planilha com o email da conta e
variaveis de configuracao no GitHub. Nao solicitar chaves privadas no chat nem
publicar credenciais em commits, artefatos ou logs.

## Validacao e Entrega

Testar: repeticao de lote, ID ja registrado, multiplas geometrias, municipios
repetidos, ausencia de geometria/campos, datas e formulas, esquema inesperado,
falha de permissao, timeout depois de escrita, concorrencia e recuperacao de fila
apos mais de 72h. Testes precisam ser versionados; ajustar de forma especifica
a regra atual que ignora tests/, sem incluir arquivos de teste locais alheios.

Antes da ativacao: simulacao na development, validacao de cabecalhos e um teste
autorizado de escrita/reexecucao com a conta do workflow. A conexao Google deste
chat nao substitui a identidade do GitHub. Implantar na main somente apos
aprovacao. Preparar instrucoes de configuracao e diagnostico para o usuario.

## Fora do Escopo

Recuperacao completa de alertas antigos, mudancas no mapa, novos emissores,
atualizacao automatica de linhas existentes, exclusao de linhas, alteracoes no
compartilhamento publico da planilha e novos agendamentos.

## Revisao do Desenho

Revisao local: distingue captura de alerta de sua exibicao no mapa, evita usar o
historico temporario como prova de envio e explicita os limites de concorrencia,
retencao do RSS e autenticacao externa. Nao houve alteracao na planilha ou no
codigo de producao durante o planejamento.

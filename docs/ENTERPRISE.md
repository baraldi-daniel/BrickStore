# 🏢 Só no workspace corporativo

Extras que dependem de recursos disponíveis em workspaces corporativos (em preview). O lab funciona sem eles: o App
é o mesmo, só sem essas partes. O SAC por voz entra pelo `INSTALAR` com `enterprise: true` no `config.yaml`; os outros
você segue pela interface, com os passos abaixo, **no final**, depois do `INSTALAR` (parte C do roteiro manual do `INSTALAR`: C1, C2 e C3).

| # | Extra | O que mostra | Onde |
|:-:|-------|--------------|------|
| 0 | **SAC por voz** com **Whisper** | Grave no microfone ou envie um áudio: viram atendimentos (categoria, sentimento, pedido) na aba 📞 do Estúdio | `config.yaml` → `enterprise: true` + `INSTALAR` |
| C1 | **Service policies do Unity Gateway** com **LLM-as-a-judge** | Guardrails gerenciados no model service do Assistente, sem mudar o código do App | Unity Gateway → Models → `assistente_llm` → Policies |
| C2 | **Omnigent** | Agentes de código trabalhando no repositório do lab com **Smart Routing**, os MCPs e as **policies** que o workspace já tem | `<workspace>/omnigent` |
| C3 | **Genie App Builder** | Um App simples do BrickStore (*Vendas da BrickStore*) criado por linguagem natural sobre as mesmas tabelas | Apps → **Build** |

> ### ⚠️ Antes de tudo: habilite os previews (Beta)
> Todos estão em **Beta** e vêm **desligados**. Um admin do workspace liga em
> **Settings → Previews** (ou no menu do usuário → *Previews*):
>
> | Para usar | Ligue o preview |
> |-----------|-----------------|
> | **Omnigent** | **Omnigent** (e **Sandbox**, se for usar o host gerenciado) |
> | **Genie App Builder** | **Governed agentic app-building** (liga também as App Spaces) |
> | Service policies | **Unity Gateway Service Policies** |
>
> Sem o preview ligado, o item não aparece no menu. Depois de ligar, recarregue a página do workspace.

> Antes de começar: rode o `INSTALAR` com o `config.yaml` ajustado para o seu catálogo e um `app_name` só seu
> (veja *Workspace corporativo* no [README](../README.md#-workspace-corporativo-compartilhado)).

---

## 0. SAC por voz com Whisper

O **Whisper** (modelo aberto da OpenAI, bom em português) é servido no **Model Serving** do próprio workspace e
transcreve as ligações; depois as funções de IA estruturam cada atendimento:

```
áudio ──Whisper (endpoint <app_name>-whisper)──► texto ──ai_classify──► troca | atraso | defeito | elogio | garantia | cancelamento
                                                       ──ai_analyze_sentiment──► positivo / negativo…
                                                       ──ai_extract──► pedido, produto, motivo ──JOIN pedidos──► atendimentos_voz
```

**Como ligar:** no `config.yaml`, `enterprise: true` e rode o `INSTALAR`.
- Etapa **2b** (`setup/02b_whisper`): baixa o modelo (`whisper_modelo`, padrão `openai/whisper-large-v3-turbo`) do
  Hugging Face, registra em `<catalog>.<schema>.whisper` e publica o endpoint `<app_name>-whisper` em **CPU** com
  **scale to zero**, sem esperar (ele sobe enquanto as outras etapas rodam).
- Etapa **9** (`setup/05a_sac_voz`): espera o endpoint ficar pronto, transcreve as 6 ligações de `audios_sac/` e cria
  `atendimentos_voz` (que o Genie passa a usar).
- Roda em **CPU** (padrão). Para áudios longos dá para usar `whisper_compute: GPU_SMALL`, se o workspace tiver GPU no
  Model Serving. Precisa de saída para o Hugging Face no momento da instalação. Se algo faltar, as etapas são puladas e
  o App segue igual.

**No App: marque Admin no topo → Estúdio → 📞 SAC por voz** (a aba só aparece quando o Whisper e a tabela existem; no modo admin
ela mostra as ligações de **todos** os clientes):
- **🎙️ Gravar agora:** grave no microfone do navegador (até 60 s); o áudio vira WAV 16 kHz no próprio navegador, passa
  pelo Whisper e pela análise, e entra no histórico.
- **Histórico:** as 6 ligações gravadas antes, já transcritas na instalação, e tudo o que for gravado ou enviado na aba.
- **📁 Enviar um arquivo** (.wav ou .mp3) e o **histórico** de `atendimentos_voz`, com o cliente de cada ligação.
- **Cadastrar no SAC:** abre a solicitação (troca, devolução, garantia ou reclamação) ligada ao **pedido** citado na ligação.
  O pedido fica editável (o Whisper pode errar um dígito) e o cliente é o dono do pedido; a solicitação aparece em
  *Meus pedidos* desse cliente e na lista *Solicitações do SAC* da aba.
- **🎙️ no Assistente:** com o Whisper ligado, o chat ganha um botão de microfone: a fala vira texto e vai para os agentes.

```sql
SELECT arquivo, fonte_transcricao, categoria, sentimento, pedido_id, status_pedido, produto, motivo
FROM <catalog>.<schema>.atendimentos_voz ORDER BY processado_em DESC;
```

**Custo:** o endpoint tem *scale to zero*: sem uso ele desliga e não cobra compute; a primeira chamada depois disso
demora alguns minutos (o App avisa para tentar de novo). Cobra enquanto está ligado (o tempo de uso mais o período
ocioso até desligar). O padrão já é CPU, o mais barato; para gastar ainda menos, `whisper_modelo: openai/whisper-small`
(menor, porém erra mais em português); para não gastar nada, `enterprise: false`. O `99_limpar_ambiente` apaga o endpoint.

---

## C1. Service policies do Unity Gateway (LLM-as-a-judge)

O Assistente chama o LLM pelo model service do próprio lab, **`<catalog>.<schema>.assistente_llm`** (etapa
`setup/05b_roteador_llm`). As *service policies* ficam **só nesse serviço**: não afetam os modelos `system.ai.*` nem
outras pessoas do workspace. Elas somam com os guardrails do grafo LangGraph do App (que continuam valendo).

### Pré-requisitos
- **Habilite o Beta:** preview **Unity Gateway Service Policies** ligado em *Settings → Previews* (admin do workspace).
- `MANAGE` no model service `assistente_llm` (você tem, porque o `INSTALAR` o criou).
- `EXECUTE` no modelo avaliador (ex.: `system.ai.claude-haiku-4-5`) e `USE CATALOG`/`USE SCHEMA` no catálogo dele.

### Passo a passo (uma policy só)
1. **Unity Gateway** (barra lateral) → aba **Models** → `assistente_llm` → aba **Policies** → **New policy** → **Service policy**.
2. **Name:** `brickstore_concorrencia` · **Guardrail type:** Custom · **Implementation:** LLM-as-a-judge · **Phase:** Input + Output ·
   **Evaluator model service:** Claude Haiku 4.5 (`system.ai.claude-haiku-4-5`).
3. **Prompt** (cole como está; não escreva ALLOW/DENY nem formato de saída: o Databricks acrescenta isso):
   ```text
   Você avalia a conversa do assistente de compras da BrickStore.
   Sinalize o conteúdo que cite outra loja ou marketplace pelo nome, compare a BrickStore com outra loja
   ou recomende comprar em outro lugar.
   NÃO sinalize marcas de produtos vendidos pela BrickStore nem a palavra "loja" usada de forma genérica.
   ```
4. **Create policy**.

### Como aparece no App
Quando uma policy bloqueia, o Unity Gateway responde com **HTTP 200**: a mensagem do assistente diz qual policy
bloqueou e o objeto `databricks_service_policy` traz o motivo. O App reconhece isso e mostra o selo
**🛡️ Unity Gateway · service policy**; na trilha 🕸️ o nó do agente aparece como *bloqueado por uma service policy*, o
evento vai para `guardrail_eventos` (categoria `unity_gateway`) e a mensagem **não** entra na memória do chat.

**Teste no App** (Assistente, com o modelo do roteador, o padrão):

| # | Pergunta no chat | ✔️ Esperado |
|:-:|------------------|-------------|
| C1.1 | *"A loja X vende esse sofá mais barato?"* | selo **🛡️ Unity Gateway · service policy**; na trilha 🕸️, *bloqueado por uma service policy* |
| C1.2 | *"Monte um setup gamer até R$ 3 mil"* | resposta normal (a policy não bloqueia o que é da loja) |

> Para comparar: no modo **Admin**, *Estúdio → 🧠 Modelo* → um modelo direto (`system.ai.*`) e repita o C1.1. Sem o
> roteador a policy não age (quem responde é só o guardrail do grafo do App).

```sql
-- eventos do gateway registrados pelo App
SELECT data_hora, cliente_id, acao, trecho FROM <catalog>.<schema>.guardrail_eventos
WHERE categoria = 'unity_gateway' ORDER BY data_hora DESC;
```

> Limites (Beta): a policy é anexada só pela interface; o avaliador é cobrado no model service avaliador; com policy
> anexada, pedidos com várias respostas (`n` > 1) retornam HTTP 400 (o App usa `n` = 1). Documentação:
> [Service policies](https://docs.databricks.com/data-governance/unity-catalog/service-policies/) ·
> [Criar e anexar](https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/create-service-policy).

---

## C2. Omnigent

O **Omnigent** é a camada da Databricks sobre agentes de código (Claude Code, Codex e agentes próprios), com o
acesso aos modelos pelo Unity Gateway e **policies** que decidem cada ação do agente (ALLOW, ASK ou DENY). Aqui ele
trabalha no repositório do lab com o que o workspace **já tem**: **Smart Routing**, os MCPs já configurados e as
policies já existentes. Nada precisa ser criado.

### Pré-requisitos
- **Habilite o Beta:** preview **Omnigent** ligado em *Settings → Previews* (e **Sandbox**, se for usar o host gerenciado).
- Workspace numa região com Unity Gateway.

### Passo a passo
1. Abra `<url-do-workspace>/omnigent` → **New session**.
2. **Repository** → escolha o repositório do lab no GitHub.
3. Deixe **Smart Routing** (ele escolhe harness e modelo) e os **MCPs** que já estão na sessão.
4. Peça, por exemplo:
   - *"Leia o README e explique em 5 tópicos a arquitetura do BrickStore."*
   - *"Na tela Detetive, adicione um filtro por faixa de preço nos produtos parecidos. Mostre o diff antes de aplicar."*
   - *"Explique como a memória do chat é gravada no Lakebase e como ela entra no prompt do agente."*
   - *"Revise o notebook setup/05c_lakebase e liste o que pode falhar numa reinstalação."*
5. As policies do workspace valem na sessão; quando uma pedir aprovação (ASK), aprove ou recuse na própria conversa.

Documentação: [Omnigent na Databricks](https://docs.databricks.com/omnigent/) ·
[policies do Omnigent](https://omnigent.ai/docs/policies/overview).

---

## C3. Genie App Builder

O **Genie App Builder** cria um **Databricks App** (com AppKit) a partir de uma descrição em linguagem natural: você
vê a prévia, refina com novos pedidos e publica. Aqui ele gera um App **simples**, de uma tela só: *Vendas da
BrickStore*, sobre as tabelas que o `INSTALAR` criou.

### Pré-requisitos
- **Habilite o Beta:** preview **Governed agentic app-building** ligado em *Settings → Previews* (admin do workspace).
  Ele também liga as **App Spaces**.
- Região AWS suportada (ex.: `us-east-1`, `us-east-2`, `us-west-2`, `eu-west-1`, `ap-southeast-2`…; não há GovCloud).
- *Partner-powered AI features* ligado no workspace.
- Permissão **CAN CREATE APP** numa **App Space**. Criar a App Space é tarefa de admin: em **Apps → App Spaces → New
  space** (escopo padrão *Data + AI*), com acesso ao schema `<catalog>.<schema>` do lab e a um SQL warehouse.

### Passo a passo
1. **Apps** → aba **Build** (menu da esquerda).
2. Escolha a **App Space** e dê o nome `vendas-brickstore`.
3. Cole o pedido, troque `<catalog>.<schema>` e envie:

   ```text
   Crie um App simples, em português do Brasil, chamado "Vendas da BrickStore", com uma tela só:
   - no topo, três números dos últimos 30 dias: receita, quantidade de pedidos e ticket médio;
   - abaixo, um gráfico de barras com a receita por departamento;
   - por último, uma tabela com os 20 pedidos mais recentes (data, status e valor).
   Use a view <catalog>.<schema>.vw_pedidos_todos, juntando com <catalog>.<schema>.vw_itens_pedido_todos e
   <catalog>.<schema>.produtos para o departamento, e ignore pedidos com status 'Cancelado'.
   ```
4. Quando aparecer, clique em **Sign in** e conclua o login na aba nova. Confira a prévia.
5. Se quiser, refine com um pedido curto: *"Adicione um filtro de departamento no topo"* ou *"Use as cores da
   BrickStore: vermelho #FF3621 e azul-escuro #0B2026"*.
6. **Deploy**. Para liberar para outras pessoas: na página do App → **Share** → **CAN USE**.

**Como o App acessa os dados:** como o usuário logado (vê só o que ele pode ver, dentro dos escopos da App Space) ou
com a identidade do próprio App, usando os dados e recursos compartilhados na App Space. O App dorme quando fica
parado (o primeiro acesso depois disso é mais lento) e perde o que estava em memória; para guardar dados, use uma
tabela no Lakebase ou no Unity Catalog.

> Limites (Beta): sem internet de saída (só o workspace e os proxies de pacotes da Databricks); sem logs de acesso
> HTTP; o login pode falhar se o App estiver embutido em outro site. Sem custo durante o Beta.
> Documentação: [Genie App Builder](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/genie-app-builder) ·
> [App Spaces](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/app-spaces).

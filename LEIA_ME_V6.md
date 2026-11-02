> Atualização posterior: consulte LEIA_ME_PARCIAIS.md. Ela substitui as regras abaixo sobre fechamento integral obrigatório e uma única sessão por passagem.

# J2I MES 6.2.1 — Roteiros, métricas, metas e estoque

Atualização do projeto enviado em 23/10/2026. O uso industrial deve começar em uma cópia para conferir uma OP real do início ao fim. Os testes automatizados não substituem a conferência na fábrica nem a medição de carga do seu servidor Windows.

## Instalação sem substituir seus dados atuais

1. Extraia o pacote em uma pasta separada. Não extraia por cima do servidor em funcionamento.
2. Encerre o Streamlit/MES e os alimentadores durante a atualização.
3. Na pasta extraída, execute `python atualizar_mes.py --destino "CAMINHO_DA_PASTA_ATUAL_DO_APP" --servidor-parado`.
4. Na pasta atual do aplicativo, execute `python -m pip install -r requirements.txt`.
5. Reinicie pelo comando/serviço habitual. Para uso local: `python -m streamlit run J2I_MES.py` ou `INICIAR_MES_V6.bat`.

O atualizador faz backup dos arquivos substituídos, dos bancos locais e da planilha. Nunca copia os bancos ou a planilha que vieram no pacote para cima do servidor. Se utiliza `PPCP_BANCO_OPERACIONAL` ou `PPCP_CATALOGO_FICHAS` apontando para outras pastas, faça também backup desses caminhos antes de atualizar. O processo não altera configuração de Cloudflare, portas ou serviços existentes.

Os bancos incluídos no pacote completo correspondem à cópia enviada pelo usuário, não à posição atual do servidor. Utilize-os apenas para conferência isolada; para atualizar o servidor, use o atualizador.

## Sequência inicial de configuração

1. Entre com o acesso administrativo atual. As credenciais existentes foram preservadas. É possível configurar `J2I_ADMIN_USER` e `J2I_ADMIN_PASSWORD` no ambiente do serviço.
2. Abra **Métricas e Metas**. As configurações previamente cadastradas são migradas; confira especialmente a unidade dimensional. No PDF de exemplo, as medidas são em **metros** (`0,905/0,905/0,018`). Configure os demais equipamentos.
3. Abra **Estoque de Insumos** e importe o PDF de conferência. Confira a prévia e aplique a posição atual. Produto, revestimento e local formam a identidade do material. Um saldo informado substitui o saldo daquele material; não é uma entrada a somar. Materiais ausentes permanecem como estavam. PDF repetido é bloqueado.
4. Selecione cada material e marque todos os equipamentos autorizados em **Material → equipamentos autorizados**. Confira o modo de rateio de cada máquina; ajuste a passagem na tabela somente no modo de passagem única e clique em **Salvar equipamentos da MP**. Os vínculos da 6.0 são migrados automaticamente. Nenhum equipamento consumidor é adivinhado pelo nome do material.
5. Em **Importar Lotes PDF**, leia o PDF de OPs, confira os avisos e informe uma data por equipamento. A leitura ocorre em processo separado para não bloquear apontamentos de outros operadores.
6. Confirme a importação. O sistema salva o catálogo, prepara a programação por passagem, atribui os consumos conforme os vínculos e gera um Excel em `exportacoes`. O Excel também fica disponível para download.
7. Resolva pendências de materiais. Depois de ajustar os vínculos, use **Preparar lote já importado** para reaplicar os vínculos nas OPs ainda não iniciadas. OPs com qualquer apontamento são preservadas integralmente. Essa ação substitui os consumos das OPs não iniciadas com base nos vínculos atuais; não reaplique se deseja preservar ajustes manuais de consumo.
8. Ative a baixa de estoque somente após importar saldos atuais e revisar consumos. O estado desativado é indicado tanto ao administrador quanto ao operador. Ao ativar, etapas sem revisão de materiais ficam bloqueadas.

O alimentador integrado abre pelo navegador do próprio MES. O atalho opcional `python alimentador_industrial.py` permite informar o endereço do servidor e abrir importação de OPs ou estoque. O antigo alimentador de PDFs por setor fica preservado como legado, sem participação no novo fluxo.

## Regras operacionais

- Cada passagem do roteiro tem uma identidade própria. A mesma máquina pode aparecer duas vezes.
- O intertravamento exige encerramento integral das etapas anteriores cadastradas, preservando o comportamento anterior. Não há liberação parcial nesta versão.
- Equipamentos desconhecidos/inativos são ignorados na importação e aparecem nos avisos persistentes. Não bloqueiam o roteiro ativo. Para incluí-los depois, cadastre e reimporte um lote sem apontamentos; lotes já executados não são substituídos.
- A próxima etapa recebe apenas a quantidade boa da anterior. Se não restar peça boa, não abre uma nova etapa de produção.
- Boas + sucata precisam fechar a quantidade recebida. Retrabalho representa peças recuperadas que já estão incluídas nas boas: não é somado novamente à produção boa. O apontamento e a observação de fechamento existentes foram mantidos. Não foi adicionado ciclo separado de tempo de retrabalho.
- A métrica é congelada na programação e no apontamento. Alterar o cadastro do equipamento não recalcula o passado. Etapas iniciadas não podem trocar regra/consumo.
- Ordens abertas antes da migração e sem snapshot recebem a regra configurada ao serem encerradas. Se não existir métrica válida, configure-a antes de fechar. Para ativar o estoque, encerre previamente as ordens abertas sem consumo revisado.

## Métricas e metas

Regras disponíveis: peças/passagens; área; comprimento; largura; bordas combinadas; quantidade vezes fator em unidade personalizada. Não são executadas expressões de código inseridas por usuários.

Seccionadoras: comprimento × largura × peças. Furadeiras: peças de cada passagem. Coladeiras: primeira medida para comprimento, segunda para largura. Nas operações explícitas `COLAR 1º/2º COMP` e `COLAR 1ª/2ª LARG`, cada etapa representa uma borda e não deve ser duplicada pelo ordinal. `PINTURA UV 1 LADO` e `PINTURA UV 2 LADO` ajustam o multiplicador para 1 e 2. Textos genéricos usam o padrão cadastrado; revise-os em Programação de Etapas.

Metas têm valor, período (hora/turno/dia) e vigência. Uma vigência existente não é sobrescrita. No painel, selecione um equipamento e um dia para comparar com a meta; metas horárias/por turno usam as horas/turnos informados para esse dia. A agregação automática de metas de vários dias/turnos não foi implementada. Programado e realizado podem ser consultados por intervalo, equipamento e setor, separados por unidade.

Programado usa a data da etapa. Realizado usa a data de encerramento. O índice pode exceder 100% quando se concluem pendências de outros dias. Cada passagem é capacidade processada; somar passagens não equivale à quantidade de peças únicas acabadas. Históricos legados sem snapshot de métrica são mantidos nas consultas antigas, sem conversão retroativa presumida.

## Materiais e saldo

Conforme confirmado pelo usuário, a última coluna do resumo de MP é consumo **por peça, já com perda**. O sistema multiplica pela quantidade de peças processadas (boas + sucata). Não aplica novamente o percentual de perda. Retrabalho não gera consumo adicional presumido; a ficha não informa esse consumo extra.

O PDF não informa a etapa consumidora nem a unidade da MP. Os vínculos cadastrados definem os equipamentos/passagens autorizados, e a unidade vem do estoque correspondente. Correspondências ambíguas de revestimento, local ou material não são aceitas automaticamente. Pendências precisam de revisão do PCP. Etapas sem consumo também precisam estar revisadas quando o estoque estiver ativo.

No fechamento, saldo, movimento, exceção e resultado são gravados na mesma transação SQLite. Com bloqueio ligado, insuficiência deixa a OP aberta e nenhum saldo é alterado. Com negativo permitido, a gravação é concluída e gera ocorrência auditável. Saldo final zero também é registrado. As ocorrências podem ser baixadas em CSV por período.

A conferência de estoque deve representar a posição atual. Pause apontamentos durante essa conferência. Alterações de saldo entre a prévia e a confirmação são detectadas e exigem nova validação. Não existe reconciliação automática de uma posição histórica com movimentos posteriores.

## Concorrência e desempenho

Todos os operadores devem acessar **o mesmo servidor MES pelo navegador**. Os arquivos SQLite ficam no disco local do servidor; não instale cópias independentes do banco em cada computador e não compartilhe o SQLite por pasta de rede. WAL permite leitura durante escrita; as gravações são serializadas por transações curtas. Importação de PDF ocorre em processo separado. O fechamento não lê nem grava Excel.

Índices atendem consultas por OP, etapa, equipamento e fechamento. Restrições impedem duas OPs abertas na mesma máquina e dupla gravação da mesma passagem. O cadastro de métricas/programação detecta versões alteradas durante edição. Excel é uma saída, não o banco transacional.

Os horários continuam usando o relógio e o fuso configurados no servidor, como no projeto original. Mantenha o Windows no fuso da fábrica.

## Recuperação e limites explícitos

Catálogo e banco operacional continuam separados para preservar a arquitetura existente. A importação salva o catálogo antes da preparação operacional. Se a segunda parte falhar, o catálogo permanece salvo e a tela orienta retomar por **Preparar lote já importado**. Não há garantia de transação única entre esses dois arquivos em uma queda de energia; o fechamento de produção/estoque, por sua vez, usa uma única transação no banco operacional.

Não foram criados cancelamento automático, estorno de apontamentos, migração para PostgreSQL, cálculo de OEE, OCR de imagens ou adaptação universal a qualquer PDF. Os layouts foram verificados com os dois PDFs enviados. Mudanças no layout precisam ser validadas antes de uso.

As telas antigas permanecem em **Exibir telas legadas (consulta)**. O acesso aos antigos apontamentos manuais de produção e parada foi desativado no menu para evitar bypass do roteiro/estoque. Os históricos e as análises anteriores foram preservados.

## Testes

Instale `pytest` e execute `python -m pytest -q tests`. Os testes opcionais dos PDFs reais usam a variável `J2I_TEST_PDFS` apontando para a pasta com `10689.pdf` e `local 5.pdf`.

O pacote inclui verificações de cálculos, regras congeladas, sequenciamento, sucata, passagem repetida, fechamento duplicado, concorrência de saldo, rollback e telas Streamlit. A migração foi verificada em cópia dos bancos recebidos. A instalação e a carga com todos os operadores no servidor Windows ainda precisam de validação local.


## Mesma MP em vários equipamentos

- Cada MP/variante pode ter vários equipamentos autorizados, com modo de distribuição configurável por equipamento. Todos usam o mesmo saldo do material.
- A OP determina o destino: quando somente um equipamento autorizado aparece no roteiro ativo, recebe o consumo previsto dessa MP, distribuído entre suas passagens conforme a configuração.
- Exemplo: MDF autorizado nas seccionadoras 1 e 2. OP A com corte apenas na 1 baixa na 1; OP B com corte apenas na 2 baixa na 2.
- Se a mesma OP tiver dois ou mais equipamentos diferentes autorizados para a mesma MP, o consumo dessa MP não é atribuído automaticamente a nenhuma delas. Aparece uma pendência para o PCP definir a etapa ou distribuir as quantidades em Programação de Etapas. As outras etapas, inclusive sem consumo, também precisam ser revisadas. Não repita o total da OP em cada máquina. Essa distribuição entre máquinas diferentes exige decisão do PCP.
- Alterações do cadastro não modificam consumos existentes por si só. Para OPs ainda não iniciadas, use Preparar lote já importado; para OPs que já tenham qualquer apontamento, essa ação preserva todos os consumos e apresenta um aviso.
- Desmarcar um equipamento e salvar remove sua autorização para futuras preparações, sem apagar históricos. É permitido deixar o material sem equipamentos; as novas OPs então ficarão com pendência.
- A edição verifica alterações concorrentes para evitar sobrescrever o cadastro que outro administrador acabou de salvar. O registro auditável guarda a lista anterior e a nova lista.

Para atualizar as versões 6.0 ou 6.1, use o mesmo `atualizar_mes.py`, com o MES parado e a pasta atual informada em `--destino`. O atualizador preserva bancos, planilha e configuração do servidor. Teste inicialmente em uma cópia.


## Atualização 6.2 — consumo dividido entre processos

Em **Métricas e Metas → Distribuição de MP entre os processos**, escolha por equipamento:

- **Dividir igualmente:** total da MP na OP dividido pelo número de processos daquele equipamento. É o padrão inicial para equipamentos cujo nome contém Coladeira ou Pintura UV. Por exemplo, 100 m de fita e quatro processos geram 25 m previstos em cada processo; 6 kg de produto e dois processos UV geram 3 kg em cada um.
- **Dividir proporcionalmente à métrica:** o peso de cada processo vem da regra de produção congelada na programação. Na coladeira, comprimento e largura podem receber parcelas diferentes. Na UV, dois lados têm o dobro do peso de um lado com a mesma área. O total continua na unidade da MP cadastrada no estoque; a métrica fornece a proporção, não converte kg em m².
- **Somente a passagem cadastrada:** mantém o comportamento anterior, com todo o consumo atribuído à passagem indicada no vínculo da MP. É o padrão dos demais equipamentos.

Nos dois modos de divisão, o campo passagem do vínculo é ignorado: participam todas as ocorrências daquele equipamento na OP. As passagens dos outros equipamentos não entram no divisor. Com uma única ocorrência, ela recebe o total. Pesos inválidos ou unidades de produção diferentes entre as etapas geram pendência para revisão.

O rateio usa seis casas decimais e distribui os restos de arredondamento para preservar o total previsto. **Programação de Etapas** mostra os consumos previstos por etapa, equipamento e unidade da MP. O fechamento baixa somente a parcela daquela etapa, proporcionalmente às peças efetivamente processadas (boas + sucata). Peças descartadas antes não consomem material nas etapas seguintes.

Ao atualizar, configurações de rateio já existentes são preservadas. Após mudar o modo ou os vínculos, use **Preparar lote já importado** para recalcular os consumos de OPs ainda não iniciadas. OPs com qualquer apontamento são preservadas integralmente, evitando duplicação de baixas. O rateio não altera metas nem métricas de produção anteriores.


## Atualização 6.2.1 — identificação somente por equipamento

A importação identifica cada passagem exclusivamente pelo código do equipamento ativo. Setor ausente ou divergente não bloqueia nem gera aviso; o campo permanece apenas como informação. Equipamentos desconhecidos ou inativos continuam no resumo de etapas ignoradas.

Cadastre equipamentos em Equipamentos e acessos, informando Código no PDF, nome, login e senha. Setor é opcional. Para o exemplo enviado, use código 62 para Tapeçaria encosto/assento. A lista EQUIPAMENTOS_OPERADORES em J2I_MES.py, linha 196, fornece apenas os cadastros iniciais: editar essa lista não altera registros já existentes no banco. A tela preserva a identidade de códigos existentes; para um código diferente, cadastre outro equipamento e revise seus vínculos de MP e métricas.

Feche o aplicativo e use o atualizador antes de reiniciar. Reimporte o PDF para gerar uma prévia sem os avisos antigos. Etapas ignoradas anteriormente só serão incluídas ao reimportar OPs ainda não iniciadas.

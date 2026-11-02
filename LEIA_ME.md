# J2I MES — sessão e reimportação por equipamento

Atualização preparada sobre o projeto app(2).rar enviado em 29/10/2026. Instala somente cinco módulos. Preserva J2I_MES.py, nomes de menus, configurações e bancos atuais. Não contém bancos, senhas ou credenciais do servidor.

## Instalação

1. Extraia este ZIP em uma pasta separada da instalação.
2. Pare o MES/Streamlit, a API e os alimentadores. Faça backup dos bancos e da instalação; inclua bancos externos caso os caminhos tenham sido configurados fora da pasta app.
3. Abra o terminal na pasta extraída, com o ambiente Python usado pelo MES ativado, e execute:

   `python atualizar_sessao_importacao.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado`

4. Reinicie o MES pelo comando habitual e atualize as páginas dos terminais. Na primeira entrada após reiniciar, faça login normalmente.

O instalador verifica as versões dos arquivos e cria backup dos módulos e dos dois bancos locais pela API SQLite, incluindo dados do WAL. Se encontrar um módulo modificado após o projeto enviado, interrompe antes de copiar para preservar essa alteração. Não troque os bancos atuais pelos bancos enviados anteriormente.

## Sessão do equipamento

A sessão antiga expirava após três minutos sem renovação. Agora a mesma sessão pode retomar após inatividade se o token ainda pertencer ao equipamento. A renovação continua ocorrendo enquanto a página está ativa. Um token substituído por outro login, ou liberado pelo botão Sair, não pode voltar a apontar.

O bloqueio de uso simultâneo continua validado no servidor. Uma conexão abandonada ainda pode ser substituída por novo login após o prazo de três minutos. Se isso acontecer, a sessão anterior precisará entrar novamente. Esta correção não memoriza senhas nem recupera uma sessão web apagada por fechamento/recarregamento do navegador, reinício do servidor ou encerramento do processo; nesses casos pode ser necessário novo login.

## Reimportar lote com produção já registrada

Em PPCP → Importar Lote (PDF), envie o PDF, clique Ler PDF e preparar prévia e escolha **Reimportar / completar preservando apontamentos**.

Confira datas, equipamentos e a tabela de etapas incluídas. Confirme a importação pelo botão habitual.

- OPs ausentes no catálogo são incluídas. Processos novos ou ainda não iniciados são preparados.
- A proteção é por etapa. Ter apontamento em um processo não impede preparar os outros processos pendentes da mesma OP.
- Etapas abertas, parciais, concluídas ou encerradas manualmente pelo PPCP são preservadas. Parciais continuam retomando somente o saldo; concluídas e encerradas manualmente não são reabertas.
- OPs ou processos existentes que não aparecem no novo PDF não são apagados. Datas já programadas são conservadas; o calendário escolhido é usado nas etapas ainda sem programação.
- Quando há histórico ou etapas fora da seleção, os dados comuns da OP (quantidade, medidas, peça e materiais) são conservados e as diferenças são avisadas. Isso evita alterar saldos de sessões anteriores.
- Se o PDF alterar equipamento/operação de uma etapa já apontada, a mescla é bloqueada para conferir a numeração do roteiro. Não se presume que uma etapa renumerada seja outra etapa.
- Consumos já revisados de OPs iniciadas são preservados. Uma nova etapa sem rateio seguro fica com aviso para revisão em Consumo de Insumos, sem nova baixa de estoque. Com o controle de estoque ligado, a revisão permanece necessária para abrir essa etapa.
- As permissões de sequência existentes são apresentadas com seu valor salvo; só mudam se o PPCP alterar a seleção e confirmar.

## Importar somente um ou alguns equipamentos

Após ler o PDF, marque **Importar somente equipamentos selecionados** e escolha os equipamentos. A prévia e a confirmação abrangem apenas as OPs e processos desses equipamentos. O modo de mescla é usado automaticamente, permitindo complementar o mesmo lote depois com outros equipamentos.

A numeração original das etapas é preservada. O roteiro completo é mantido apenas como referência para sequência e rateio de material; os processos não selecionados não são disponibilizados para apontamento por essa importação. Se houver etapa anterior ainda não importada/concluída, a sequência normal bloqueia a etapa seguinte. O PPCP pode usar a opção existente de liberação de sequência do lote, quando essa for sua decisão operacional.

## Conferência dos dados enviados e validação

Os dois bancos passaram na verificação de integridade. O catálogo enviado contém 52 OPs do lote 10699, sem a OP 01328771. Para incluí-la, use a nova reimportação com o PDF que contém seus dados. Não foi inventada uma ficha para essa OP.

70 testes automatizados passaram, incluindo retomada de sessão após oito horas, rejeição do token substituído, reimportação com apontamento parcial/total, preservação de encerramento PPCP, filtro sem renumeração, complementação posterior, não duplicação de consumo e reversão dos dois bancos em falha simulada. Teste de interface confirmou importação filtrada e complementação com outro equipamento.

Em cópias isoladas dos bancos, a mescla de 52 OPs e 173 etapas do lote 10699 manteve apontamentos, resultados, movimentos, saldos, políticas e encerramentos manuais. Essa simulação usou as fichas já salvas no catálogo, pois o PDF do lote não acompanhou o projeto. Os bancos originais não foram alterados.

As tabelas auxiliares são criadas na primeira mescla; instalar o código não reimporta lotes nem modifica a produção automaticamente. As gravações usam transação e revertem em caso de erro de validação. Mantenha o backup conjunto dos dois bancos para recuperação após interrupções do servidor.

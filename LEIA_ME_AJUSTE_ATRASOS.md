# Atualização — saldo em atraso e consulta do realizado

Na tela Saldo em atraso, passagens com conversão zerada ficam temporariamente fora da soma. Continuam nas contagens de OPs/passagens e no detalhamento. O resumo informa quantas foram ignoradas e mostra aviso de total parcial. Se todas estiverem zeradas, o total exibido será zero com esse aviso, não significando ausência de pendências. Outros erros continuam bloqueando o total. Nenhuma medida, quantidade, programação ou estoque é alterado.

Programado × realizado ganhou o botão Atualizar consulta. A regra já inclui todos os equipamentos com sessões encerradas no período, inclusive encerramentos parciais e sem programação. Ordens apenas abertas ainda não são produção realizada. O filtro de data usa o fechamento da sessão.

Diagnóstico PADE 123: no banco enviado, equipamento id 16, não existem sessões vinculadas à PADE, em qualquer data. Os últimos horários gerais são abertura 28/10/2026 15:38:40 e fechamento 28/10/2026 16:49:07. Não é possível concluir a causa dos apontamentos mais recentes sem uma cópia atualizada do banco efetivamente usado pelo servidor. Conferir data, setor/equipamento e clicar Atualizar consulta. Não foi inventada produção nem alterada a consulta para contar ordens abertas como produzidas.

## Instalação no Windows

1. Extraia este ZIP em uma pasta separada da instalação atual.
2. Pare o MES/Streamlit e os alimentadores. Faça backup da instalação e dos bancos atuais; se usar caminhos externos, inclua esses bancos no backup.
3. Abra o terminal na pasta extraída que contém atualizar_mes.py e execute, substituindo o caminho abaixo pela pasta real:

   python atualizar_mes.py --destino "C:\CAMINHO\J2I_MES\app" --servidor-parado

4. Reinicie o MES pelo comando habitual e atualize a página do navegador.

O atualizador preserva bancos/planilhas e cria backup antes de substituir os módulos. Este pacote é cumulativo com a correção anterior das coladeiras; não inclui bancos, senhas nem alterações da futura tela Fechar lotes manual, que permanece pendente.

Validação: 46 testes automatizados passaram. Consulta somente leitura no banco enviado confirmou 2.694,080838 m² válidos para Pintura UV, com 9 passagens ignoradas, mantendo 134 OPs e 206 passagens.

# Encerramento seletivo de atrasos — PPCP

Na tela Saldo em atraso por equipamento:
1. Selecione um equipamento e clique Preparar encerramento dos atrasos.
2. Escolha Todas as passagens em atraso (mantém o funcionamento anterior) ou Somente as passagens marcadas.
3. No modo seletivo, marque a nova coluna Encerrar, à esquerda da prévia. Somente essa coluna é editável. Confira a quantidade de passagens indicada abaixo.
4. Informe o motivo, confirme e clique no botão de encerramento.

Cada linha é uma passagem, identificada por OP, lote e etapa. Para encerrar todas as passagens de uma OP, marque suas respectivas linhas. As demais permanecem pendentes. Seleção vazia não executa nenhuma ação; alteração dos dados desde a prévia exige nova conferência. Ao mudar a seleção, confira e confirme novamente.

As antigas caixas da coluna Ignorada por conversão zerada eram apenas indicadores de cálculo, não seleção. A nova seleção usa a coluna Encerrar. No modo Todas, essas caixas ficam desabilitadas para deixar claro que todas as passagens da prévia serão encerradas.

Mantém auditoria de usuário, motivo, data, equipamento, OP, lote e passagem. Não gera produção, consumo, refugo, retrabalho ou tempo produtivo. Preserva produção anterior e programação histórica. Sem mudanças no banco além dos registros de encerramento quando o PPCP confirma.

## Instalação
Extraia em uma pasta separada. Pare o MES e alimentadores e faça backup dos bancos e da instalação. Na pasta app extraída, execute com o caminho real:

    python atualizar_mes.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado

Reinicie pelo comando habitual. O pacote é cumulativo e preserva os ajustes anteriores. Nenhuma OP é encerrada na instalação. As instruções deste arquivo complementam LEIA_ME_ENCERRAR_ATRASOS.md.

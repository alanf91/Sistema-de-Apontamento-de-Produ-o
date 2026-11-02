# Programado × realizado — todos os equipamentos

Todos os equipamentos cadastrados aparecem, respeitando os filtros de setor e equipamento, inclusive os inativos. Sem programação e sem apontamentos: Programado 0 e Realizado 0. Com apontamentos encerrados no período e sem programação: Programado 0 e Realizado correspondente. Válido para uma data ou um intervalo. A métrica histórica dos registros continua preservada; unidades diferentes não são somadas.

Instalação: extraia o ZIP em pasta separada, pare o MES e alimentadores, faça backup e execute na pasta app extraída:

    python atualizar_mes.py --destino "C:\CAMINHO\J2I_MES\app" --servidor-parado

Substitua o caminho pelo real. Reinicie pelo comando habitual. O atualizador preserva bancos/planilhas e cria backup. Inclua bancos externos em seu backup, se houver.

Pacote cumulativo: inclui o ajuste anterior de medidas zeradas na tela de atrasos. A tela Fechar lotes manual permanece pendente e não está incluída.

Validação: 48 testes passaram. Consulta somente leitura ao banco enviado confirmou PADE 123 visível com Programado 0 e Realizado 0 em 28/10/2026. Não houve alteração de dados no banco.

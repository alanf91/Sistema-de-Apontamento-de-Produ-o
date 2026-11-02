# Equipamentos ativos — Desempenho Industrial

A seleção em Métricas e Metas → Equipamentos ativos define os equipamentos exibidos em Programado × realizado e Saldo em atraso. Programação diária × meta, Estatística por equipamento, Paradas registradas e Histórico de OPs já aplicavam esse filtro, conferido nesta revisão.

Salve a seleção e atualize ou reabra o relatório. Não há atualização automática de uma página já aberta em outro navegador. Desativar apenas oculta os registros dos relatórios; reativar volta a mostrá-los, sem apagar histórico. No Programado × realizado, todos os ativos dos filtros aparecem, mesmo sem atividade: Programado 0 e Realizado 0. Com apontamentos encerrados no período, o realizado é preenchido normalmente.

Instalação: extraia este pacote em pasta separada. Pare o MES e alimentadores, faça backup e execute na pasta app extraída, substituindo o caminho pelo real:

    python atualizar_mes.py --destino "C:\CAMINHO\J2I_MES\app" --servidor-parado

Reinicie pelo comando habitual. O atualizador preserva bancos e planilhas e cria backup dos arquivos locais. Inclua bancos externos no backup, se houver.

Este pacote é cumulativo e substitui o pacote anterior Todos Equipamentos. Esta instrução prevalece sobre as notas antigas que mencionam exibição de inativos. Mantém o ajuste das conversões zeradas na tela de atrasos. Fechar lotes manual continua pendente e não está incluído.

Validação: 48 testes passaram, incluindo ocultação, reativação e preservação do histórico. Consultas somente leitura na base enviada confirmaram exclusivamente equipamentos ativos em ambos os relatórios corrigidos.

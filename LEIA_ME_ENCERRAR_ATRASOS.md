# Encerramento manual de atrasos pelo PPCP

## Usar

1. Entre com o acesso administrativo do PPCP e abra Desempenho Industrial → Saldo em atraso por equipamento.
2. Selecione um único equipamento ativo no filtro.
3. Ao final da tela, clique Preparar encerramento dos atrasos.
4. Confira todas as OPs/passagens da prévia, informe o motivo, marque a confirmação e clique Encerrar atrasos manualmente pelo PPCP.
5. Consulte o histórico de encerramentos manuais do equipamento, disponível na mesma seção, com exportação CSV.

O corte é a data de ontem, conforme o relógio do servidor. Inclui passagens não iniciadas, abertas e saldos parciais vencidos, inclusive conversões zeradas. Não afeta etapas de outros equipamentos, etapas já concluídas ou previstas para hoje/futuro. Registros sem data programada válida não são classificados como atraso e não entram. Se a carteira mudar após a prévia, a confirmação é recusada até gerar nova prévia.

## Efeitos

- Registra separadamente OP, lote, etapa, equipamento, login administrativo, data/hora, motivo, corte e cópia dos dados anteriores na tabela mes_encerramentos_ppcp; também registra o evento em mes_auditoria.
- Não cria apontamentos fictícios. Sessões abertas recebem status ENCERRADA_PPCP, horário de encerramento e tempo produtivo zero. Não são tratadas como FINALIZADA nos indicadores de produção. A duração original e demais dados anteriores ficam preservados no registro de auditoria da passagem.
- Não soma boas, refugo, retrabalho, volume ou tempo de processamento por esse encerramento. Não movimenta estoque. Eventual baixa real já feita na abertura não é estornada automaticamente.
- Produção real anteriormente apontada, inclusive em sessões parciais, permanece nos indicadores; apenas o saldo restante é encerrado administrativamente.
- Programação e metas históricas permanecem: o encerramento não transforma programado em realizado nem altera atingimento para simular produção.
- Passagens encerradas somem dos atrasos, da lista de OPs pendentes e do sequenciamento sugerido; não podem ser reabertas. A ação não libera peças fictícias para etapas posteriores. As regras existentes de sequência continuam valendo, inclusive a liberação de sequência por lote quando configurada.
- Não encerra paradas registradas. O histórico de produção e o histórico de encerramentos administrativos são preservados.
- A identificação utiliza o login administrativo PPCP existente no sistema. Se a empresa compartilha esse login, o registro identifica essa conta, não uma pessoa individual.

## Instalar no Windows

Extraia o ZIP em uma pasta separada. Pare o MES/Streamlit e alimentadores, faça backup da instalação e dos bancos atuais. Inclua bancos externos no backup, se usados. Na pasta app extraída execute, substituindo o caminho pelo real:

    python atualizar_mes.py --destino "C:\CAMINHO\J2I_MES\app" --servidor-parado

Reinicie o MES pelo comando habitual. A tabela administrativa é criada automaticamente ao inicializar o aplicativo; nenhum encerramento é executado durante a instalação. O atualizador cria backup local e preserva bancos/planilhas. O ZIP não contém cópia do banco de produção.

Pacote cumulativo: mantém filtro de equipamentos ativos, exibição 0/0 no Programado × realizado, ajustes de medidas zeradas e correções anteriores. Este documento prevalece sobre as notas antigas sobre ausência de encerramento manual. Esta implementação fica na tela de atrasos, por equipamento; não acrescenta a tela separada de seleção de vários lotes/equipamentos.

## Validação

56 testes automatizados passaram. Teste de interface validou seleção, prévia, motivo, confirmação, saldo atualizado e histórico. Simulação em cópia isolada do banco enviado encerrou 206 passagens da Pintura UV, mantendo resultados, programação, movimentos, estoque e realizado inalterados. Banco original preservado.

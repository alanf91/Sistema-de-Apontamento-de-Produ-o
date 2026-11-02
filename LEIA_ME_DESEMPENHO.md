# J2I MES — Programado × realizado sem programação

Atualização cumulativa baseada no último pacote desta conversa. Inclui encerramento parcial, saldo em atraso por equipamento e esta melhoria de desempenho.

## Funcionamento

Menu Desempenho Industrial → Programado × realizado.

Selecione De e Até. Para um dia, use a mesma data nos dois campos. Para vários dias, informe o intervalo: os dois extremos são incluídos.

A consulta reúne todos os equipamentos com programação ou apontamentos no período, inclusive equipamentos atualmente inativos. Os filtros de setor/equipamento permanecem disponíveis; mantenha Todos para ver todos os equipamentos.

- Programado: soma das etapas com data prevista no período selecionado.
- Sem programação no período: Programado = 0, mesmo que haja produção, OP sem plano ou plano previsto para outro dia.
- Realizado total: soma das quantidades boas e de sucata efetivamente apontadas no período, na unidade do equipamento.
- Realizado bom, Sucata e Retrabalho: colunas separadas. Retrabalho já está incluído nas boas e não é somado outra vez ao realizado total.
- Cada parcial é computada no dia do seu encerramento. Reabrir a mesma OP não duplica a produção já registrada.
- OP aberta sem encerramento/apontamento ainda não gera realizado.
- Equipamento com programação mas sem apontamentos: realizado = 0.
- Equipamento sem programação e sem apontamentos: não ocupa uma linha no resumo.
- Programado = 0: atingimento fica sem percentual, evitando divisão por zero.

O comparativo desta tela passa a ter uma única regra por datas: previsão do calendário versus produção apontada no intervalo. A antiga opção que usava a quantidade de abertura das OPs concluídas como Programado foi retirada desta tela, para não apresentar uma programação inexistente no período. A consulta detalhada dos apontamentos permanece disponível.

Exemplo: um equipamento apontou 120 m² no dia, sem programação para esse dia. O resumo mostra Programado 0 m² e Realizado total 120 m². Se forem selecionados três dias, soma os apontamentos desses três dias e somente a programação prevista nesses mesmos dias.

## Métricas e registros antigos

Os resultados métricos preservados no apontamento são prioritários. Equipamentos/unidades diferentes não são misturados. Mudanças posteriores no cadastro não recalculam resultados preservados.

Registros legados sem resultado métrico preservado são convertidos pela regra da programação, quando disponível, ou pelo cadastro atual. Essa conversão é identificada na coluna Origem da métrica e em avisos; não é uma garantia de que o cadastro atual era o vigente na data antiga. A consulta não grava essa conversão no banco.

Se não existir regra ou medida suficiente, o apontamento aparece em uma linha separada em “peças (conversão pendente)”, com aviso. Ele não desaparece e não é misturado a m² ou metros. Programações com conversão inválida são sinalizadas, não tratadas como zero.

O detalhamento e os arquivos CSV permitem conferir todas as linhas que formam os totais. A comparação com meta vigente continua disponível ao selecionar um equipamento e um único dia.

## Instalação no Windows

1. Extraia o ZIP em uma pasta separada do servidor.
2. Pare o MES/Streamlit, API e alimentadores durante a atualização.
3. Abra o PowerShell na pasta app extraída, onde está atualizar_mes.py.
4. Execute:

```powershell
py -3.11 atualizar_mes.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado
```

5. Aguarde a confirmação e anote o caminho do backup.
6. Reinicie pelo procedimento habitual e atualize o navegador.

O atualizador faz backup e preserva bancos, Excel e configurações existentes. Não altera Cloudflare ou portas. Se os bancos estiverem configurados em caminhos externos à pasta do aplicativo, faça também backup consistente desses caminhos. Não houve nova dependência de execução.

Este pacote já inclui as duas melhorias anteriores; não é necessário reinstalá-las separadamente. Consulte LEIA_ME_PARCIAIS.md antes de considerar retorno ao código antigo após usar parciais.

## Validação

35 testes automatizados com SQLite temporário, incluindo regressões de parciais e atrasos, mais teste de interface Streamlit da tela de desempenho. Foram conferidos período de um dia e vários dias, inclusão do último segundo do dia final, equipamentos sem programação, programação fora do período, equipamentos inativos, sucata/retrabalho, conversão de legados, filtros e unidades distintas.

Para repetir na pasta app:

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 tests\verificar_interface_desempenho.py
```

O segundo comando requer Streamlit instalado. Os testes usam dados fictícios e isolam a autenticação web. Falta conferir a instalação e os volumes reais no servidor Windows; esta entrega não altera o servidor em execução.
